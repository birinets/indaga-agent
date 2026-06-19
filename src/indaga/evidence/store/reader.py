"""EvidenceStoreReader — the only class genome handlers touch for in-house evidence.

GenomeIndex-style (like AGIReader): opens a subject's ``evidence.sqlite`` with the
shared ClinVar DB ATTACHed, and answers the same shapes ``genome/evidence.py``
returns today. ClinVar is joined by **genomic position** in the chip's native build
(GRCh37) — the complete join, since ~20% of ClinVar P/LP rows lack an ``RS=`` tag.
The multi-omic fusion layer never sees this class — it sees the graded ``Fact``s the
handlers write from these reads (port boundary intact).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ...genome import vrs
from . import connection as conn

_CHIP_BUILD = "GRCh37"
_PL_SIGS = ("pathogenic", "likely_pathogenic", "likely pathogenic")  # ClinVar uses both spellings


def _first_gene(gene_info: str | None) -> str | None:
    if not gene_info:
        return None
    return gene_info.split("|", 1)[0].split(":", 1)[0].strip() or None


def _norm_chrom(c: str) -> str:
    c = str(c).strip()
    return c[3:] if c.lower().startswith("chr") else c


def _is_pl(sig: str | None) -> bool:
    low = (sig or "").lower()
    return ("pathogenic" in low) and ("conflicting" not in low) and ("non-pathogenic" not in low)


def _allele_carried(v_ref: str | None, v_alt: str | None, allele1: str | None, allele2: str | None,
                    agi_ref: str | None = None, agi_alt: str | None = None) -> bool:
    """True iff the subject genuinely carries ClinVar's EXACT ref→alt at this position.

    The release-blocking bug was a ``(chrom,pos)``-only join that accepted a carrier whenever the
    ClinVar ALT appeared among the subject's two alleles — with no REF/ALT identity. That let a
    ClinVar indel ``AA>C`` inherit a chip SNP genotype ``A/C`` (ALT ``C`` ∈ {A,C}), and let a
    ref/alt mismatch count as carried. This restores allele identity:

      * imputed AGI rows carry their OWN ref/alt → require exact ``(agi_ref,agi_alt)==(v_ref,v_alt)``
        and that the genotype includes the alt;
      * chip AGI rows store only the observed genotype letters → only a SNV ClinVar record is
        representable on a chip, so require both alleles drawn from ``{ref,alt}`` and the alt carried.
        A ClinVar indel/MNV is unconfirmable from a chip SNP genotype and is rejected.
    """
    if not (v_ref and v_alt and allele1 and allele2):
        return False
    alleles = {allele1, allele2}
    if agi_ref and agi_alt:                                  # imputed: VRS-normalized ref→alt identity
        # Minimal-representation match (see genome/vrs.py) so the SAME variant encoded with a different
        # anchor length at this locus still matches; the subject's genotype must carry the AGI's alt.
        # SNVs normalize to identity, so this never loosens the SNV path.
        return vrs.same_allele(agi_ref, agi_alt, v_ref, v_alt) and agi_alt in alleles
    if len(v_ref) == 1 and len(v_alt) == 1:                  # chip SNV consistency (indel-safe)
        return v_alt in alleles and alleles <= {v_ref, v_alt}
    return False                                             # ClinVar indel/MNV ≠ a chip SNP call


class EvidenceStoreReader:
    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con
        self._has_clinvar = conn.has_shared_clinvar(con)

    @classmethod
    def open(cls, subject_path: str | Path) -> "EvidenceStoreReader | None":
        con = conn.open_reader(subject_path, attach_shared=True)
        return cls(con) if con is not None else None

    @property
    def annotation_complete(self) -> bool:
        return conn.get_meta(self._con, "annotation_complete") == "1"

    @property
    def build(self) -> str:
        return conn.get_meta(self._con, "genome_build") or _CHIP_BUILD

    @property
    def has_clinvar(self) -> bool:
        return self._has_clinvar

    # -- ClinVar (shared, ATTACH-blended, position-keyed) ------------------ #

    def _record(self, row) -> dict:
        return {"gene": _first_gene(row["gene_info"]), "clinvar_sig": row["clinical_significance"],
                "clinvar_disease": row["conditions"], "clinvar_review": row["review_status"],
                "achange": None, "effect": row["hgvs"], "ref": row["ref"], "alt": row["alt"],
                "clinvar_id": row["clinvar_id"], "chrom": row["chrom"], "pos": row["pos"],
                "consequence": row["mc"]}

    def clinvar_by_position(self, chrom: str, pos: int, *, build: str = _CHIP_BUILD,
                            carried_alleles: tuple[str, ...] | None = None) -> dict | None:
        """Best ClinVar record at a position. Prefers a P/LP record whose alt the subject
        carries, then any record with a significance. Returns the legacy shape (+coords)."""
        if not self._has_clinvar:
            return None
        rows = self._con.execute(
            f"SELECT chrom,pos,ref,alt,clinvar_id,clinical_significance,review_status,conditions,"
            f"gene_info,hgvs,mc FROM {conn.SHARED_ALIAS}.clinvar_variants "
            f"WHERE chrom=? AND pos=? AND genome_build=?", (_norm_chrom(chrom), int(pos), build),
        ).fetchall()
        if not rows:
            return None
        ca = tuple(carried_alleles or ())
        a1 = ca[0] if len(ca) > 0 else None
        a2 = ca[1] if len(ca) > 1 else a1

        def rank(r) -> tuple:
            # allele-safe: an indel/MNV or ref/alt mismatch must NOT rank as "carried" (same fix
            # as the P/LP screen) — otherwise an indel at a SNP position would be preferred.
            carries = 1 if (ca and _allele_carried(r["ref"], r["alt"], a1, a2)) else 0
            pl = 1 if _is_pl(r["clinical_significance"]) else 0
            has_sig = 1 if r["clinical_significance"] else 0
            return (carries, pl, has_sig)

        return self._record(max(rows, key=rank))

    def clinvar_by_rsid(self, rsid: str, *, build: str = _CHIP_BUILD) -> dict | None:
        """ClinVar significance by rsID (convenience; only covers RS-tagged records).
        Position lookup is the complete path — prefer it when coords are known."""
        if not self._has_clinvar:
            return None
        rs = rsid.strip()
        rs = rs if rs.lower().startswith("rs") else f"rs{rs}"
        row = self._con.execute(
            f"SELECT v.chrom,v.pos,v.ref,v.alt,v.clinvar_id,v.clinical_significance,v.review_status,"
            f"v.conditions,v.gene_info,v.hgvs,v.mc "
            f"FROM {conn.SHARED_ALIAS}.clinvar_variant_rsids r "
            f"JOIN {conn.SHARED_ALIAS}.clinvar_variants v ON v.rowid = r.variant_rowid "
            f"WHERE r.rsid=? AND r.genome_build=? ORDER BY (v.clinical_significance IS NULL) LIMIT 1",
            (rs, build),
        ).fetchone()
        return self._record(row) if row else None

    def clinvar_pl_in_genes(self, genes: set[str], *, build: str = _CHIP_BUILD) -> list[dict]:
        """All ClinVar P/LP rows whose gene ∈ ``genes`` — the P/LP screen's candidate set,
        keyed by position (so RS-less records are included). One row per variant."""
        if not self._has_clinvar or not genes:
            return []
        out: list[dict] = []
        seen: set[int] = set()
        sql = (
            f"SELECT g.variant_rowid, r.rsid, v.chrom,v.pos,v.ref,v.alt,v.clinvar_id,"
            f"v.clinical_significance,v.review_status,v.conditions,v.gene_info,v.hgvs "
            f"FROM {conn.SHARED_ALIAS}.clinvar_variant_genes g "
            f"JOIN {conn.SHARED_ALIAS}.clinvar_variants v ON v.rowid = g.variant_rowid "
            f"LEFT JOIN {conn.SHARED_ALIAS}.clinvar_variant_rsids r ON r.variant_rowid = g.variant_rowid "
            f"WHERE g.gene_symbol=? AND g.genome_build=?"
        )
        for gene in genes:
            for row in self._con.execute(sql, (gene, build)).fetchall():
                if not _is_pl(row["clinical_significance"]):
                    continue
                rid = row["variant_rowid"]
                if rid in seen:
                    continue
                seen.add(rid)
                rec = self._record(row)
                rec["gene"] = gene
                rec["rsid"] = row["rsid"]
                out.append(rec)
        return out

    # ClinVar significance values that count as P/LP (cleaned spellings).
    _PL_SET = ("Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic",
               "Pathogenic/Likely pathogenic/Pathogenic, low penetrance",
               "Pathogenic, low penetrance", "Likely pathogenic, low penetrance")

    def clinvar_pl_carriers(self, agi_path: str, *, build: str = _CHIP_BUILD) -> list[dict]:
        """Genome-wide ClinVar P/LP variants the subject CARRIES — the screen's candidate
        set. Joins ClinVar ⋈ AGI on (chrom,pos) in the chip's build, returning only loci
        present on the chip; the Python caller confirms the carried allele + adds gnomAD.
        ESR1's panel='—' confirms the screen is genome-wide, not panel-restricted."""
        if not self._has_clinvar:
            return []
        # ATTACH the AGI alongside the shared ClinVar DB (idempotent per connection).
        try:
            self._con.execute("ATTACH DATABASE ? AS agi", (str(Path(agi_path).resolve()),))
        except sqlite3.OperationalError:
            pass  # already attached
        # Pull the AGI's own ref/alt + typed marker so the join can verify EXACT allele identity
        # (older chip AGIs may lack these columns → select safe literals instead).
        agi_cols = {r[1] for r in self._con.execute("PRAGMA agi.table_info(variants)")}
        ref_sel = "a.ref AS agi_ref" if "ref" in agi_cols else "NULL AS agi_ref"
        alt_sel = "a.alt AS agi_alt" if "alt" in agi_cols else "NULL AS agi_alt"
        typed_sel = "a.typed AS agi_typed" if "typed" in agi_cols else "0 AS agi_typed"
        # A chip-built AGI is directly-typed throughout; only the imputed AGI mixes typed/imputed.
        agi_imputed = False
        try:
            mrow = self._con.execute("SELECT value FROM agi.metadata WHERE key='source'").fetchone()
            agi_imputed = bool(mrow) and mrow[0] == "imputed"
        except sqlite3.Error:
            pass
        placeholders = ",".join("?" * len(self._PL_SET))
        sql = (
            f"SELECT v.chrom,v.pos,v.ref,v.alt,v.clinvar_id,v.clinical_significance,v.review_status,"
            f"v.conditions,v.gene_info,v.hgvs, a.genotype,a.allele1,a.allele2,a.zygosity,a.rsid AS agi_rsid, "
            f"{ref_sel}, {alt_sel}, {typed_sel}, r.rsid "
            f"FROM {conn.SHARED_ALIAS}.clinvar_variants v "
            f"JOIN agi.variants a ON a.chrom = v.chrom AND a.pos = v.pos "
            f"LEFT JOIN {conn.SHARED_ALIAS}.clinvar_variant_rsids r ON r.variant_rowid = v.rowid "
            f"WHERE v.genome_build = ? AND a.record_kind = 'variant_call' "
            f"AND v.clinical_significance IN ({placeholders})"
        )
        rows = self._con.execute(sql, (build, *self._PL_SET)).fetchall()
        out: list[dict] = []
        seen: set[tuple] = set()
        for row in rows:
            # EXACT-ALLELE match: a (chrom,pos) hit is NOT enough — a ClinVar indel must not inherit
            # a chip SNP's significance, and a ref/alt mismatch must not count as carried. This is
            # the allele-safety fix (see _allele_carried + indaga.eval.allele_safety_eval).
            if not _allele_carried(row["ref"], row["alt"], row["allele1"], row["allele2"],
                                   row["agi_ref"], row["agi_alt"]):
                continue
            key = (row["chrom"], row["pos"], row["ref"], row["alt"])
            if key in seen:
                continue
            seen.add(key)
            # directly-typed = a chip hard-call (typed=1 from the chip-overlay) or any call on a
            # chip-built (non-imputed) AGI. The authoritative signal is the `typed` COLUMN, not an
            # rsID prefix — imputed sites can also carry rs… ids — so an imputed P/LP no longer
            # masquerades as a directly-typed (confident) call downstream.
            directly_typed = bool(row["agi_typed"]) or (not agi_imputed)
            out.append({
                "rsid": row["rsid"] or (row["agi_rsid"] if directly_typed else None),
                "gene": _first_gene(row["gene_info"]),
                "chrom": row["chrom"], "pos": row["pos"], "ref": row["ref"], "alt": row["alt"],
                "genotype": row["genotype"], "zygosity": row["zygosity"],
                "clinvar_sig": row["clinical_significance"], "clinvar_disease": row["conditions"],
                "clinvar_review": row["review_status"], "clinvar_id": row["clinvar_id"],
                "effect": row["hgvs"], "directly_typed": directly_typed,
                # durable, representation-stable allele identity (VRS-style; provenance / join key)
                "allele_id": vrs.allele_id(build, row["chrom"], row["pos"], row["ref"], row["alt"]),
            })
        return out

    def gene_region(self, gene: str, *, build: str = _CHIP_BUILD) -> tuple[str, int, int] | None:
        """(chrom, min_pos, max_pos) for a gene, derived from its ClinVar variants — an
        approximate gene span (no separate gene-coordinate download needed)."""
        if not self._has_clinvar:
            return None
        row = self._con.execute(
            f"SELECT v.chrom, MIN(v.pos), MAX(v.pos), COUNT(*) c "
            f"FROM {conn.SHARED_ALIAS}.clinvar_variant_genes g "
            f"JOIN {conn.SHARED_ALIAS}.clinvar_variants v ON v.rowid = g.variant_rowid "
            f"WHERE g.gene_symbol=? AND g.genome_build=? GROUP BY v.chrom ORDER BY c DESC LIMIT 1",
            (gene, build),
        ).fetchone()
        return (row[0], int(row[1]), int(row[2])) if row else None

    # -- GWAS Catalog (shared, ATTACH-blended, position-keyed) ------------- #

    @property
    def has_gwas(self) -> bool:
        try:
            return self._con.execute(
                f"SELECT 1 FROM {conn.SHARED_ALIAS}.gwas_associations LIMIT 1").fetchone() is not None
        except sqlite3.Error:
            return False

    def gwas_carriers(self, agi_path: str, *, trait: str | None = None, limit: int = 25,
                      build: str = "GRCh38") -> list[dict]:
        """GWAS-Catalog trait associations at loci the subject CARRIES (non-ref variant
        call). Joins the catalog ⋈ AGI on (chrom,pos) — the catalog is GRCh38, so this is
        meaningful only on an imputed GRCh38 genome (a GRCh37-only chip won't position-match;
        the caller should report that). Collapses multi-study dupes per (locus,trait) to the
        strongest p-value; strongest associations first."""
        if not self.has_gwas or build != "GRCh38":
            return []
        try:
            self._con.execute("ATTACH DATABASE ? AS agi", (str(Path(agi_path).resolve()),))
        except sqlite3.OperationalError:
            pass  # already attached
        where = "a.record_kind = 'variant_call' AND g.mlog IS NOT NULL"
        args: list = []
        if trait:
            where += " AND g.trait LIKE ?"
            args.append(f"%{trait}%")
        # MAX(g.mlog) + GROUP BY: SQLite returns the other columns from the max-significance row.
        # Significance is ranked by -log10(p) (mlog) — the raw p-value underflows float64 to 0
        # for the most significant hits, which would silently drop/mis-rank them.
        sql = (
            f"SELECT g.chrom, g.pos, g.rsid, g.trait, g.gene, g.or_beta, g.pval, MAX(g.mlog) AS mlog, "
            f"g.pmid, a.genotype, a.zygosity, a.rsid AS agi_rsid "
            f"FROM {conn.SHARED_ALIAS}.gwas_associations g "
            f"JOIN agi.variants a ON a.chrom = g.chrom AND a.pos = g.pos "
            f"WHERE {where} "
            f"GROUP BY g.chrom, g.pos, g.trait "
            f"ORDER BY mlog DESC LIMIT ?"
        )
        args.append(int(limit))
        out: list[dict] = []
        for row in self._con.execute(sql, args).fetchall():
            out.append({
                "rsid": row["rsid"] or row["agi_rsid"], "chrom": row["chrom"], "pos": row["pos"],
                "gene": row["gene"], "trait": row["trait"], "or_beta": row["or_beta"],
                "pval": row["pval"], "neg_log10_p": row["mlog"], "pmid": row["pmid"],
                "genotype": row["genotype"], "zygosity": row["zygosity"],
            })
        return out

    # -- per-subject materialized findings --------------------------------- #

    def pl_findings(self) -> list[dict]:
        build = self.build
        rows = self._con.execute(
            "SELECT rsid,gene,panel,chrom,pos,ref,alt,achange,candidate_reason,"
            "clinvar_sig,clinvar_disease,clinvar_review,gnomad_af,gnomad_source,classification,"
            "zygosity,inheritance,carrier_status,interpretation,directly_typed,confidence,review_stars "
            "FROM pl_findings").fetchall()
        from ...genome.acmg_carrier import carrier_info
        from ...genome.acmg_sf import sf_info
        out = []
        for r in rows:
            d = dict(r)
            # durable, representation-stable allele identity (VRS-style) computed at read time — no
            # schema migration; a stable key for dedup across encodings/builds + the FHIR export.
            d["allele_id"] = (vrs.allele_id(build, d["chrom"], d["pos"], d["ref"], d["alt"])
                              if d.get("ref") and d.get("alt") else None)
            # Standard-panel annotations, computed at read time from the gene (no re-materialization):
            # ACMG SF v3.3 (medically-actionable secondary finding) + ACMG 2021 carrier screening.
            sf = sf_info(d.get("gene"))
            d["acmg_sf"] = bool(sf)
            d["acmg_sf_category"] = sf["category"] if sf else None
            d["acmg_sf_disorder"] = sf["disorder"] if sf else None
            car = carrier_info(d.get("gene"))
            d["acmg_carrier"] = bool(car)
            d["acmg_carrier_condition"] = car["condition"] if car else None
            out.append(d)
        return out

    def pgs_results(self) -> list[dict]:
        rows = self._con.execute(
            "SELECT pgs_id,category,trait_label,direction,note,raw_score,n_total,n_matched,"
            "coverage,z_score,percentile,pop_mu,pop_sd FROM pgs_results").fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._con.close()
