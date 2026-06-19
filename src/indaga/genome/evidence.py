"""Genome evidence — Indaga's OWN store, fully self-contained (no external project).

Indaga computes all of its genome evidence itself: ClinVar significance (position-join
against its downloaded ClinVar), the P/LP screen, and polygenic scores — materialized
per-subject into ``~/.indaga/<subject>/evidence.sqlite`` by the annotate pipeline.

These readers query ONLY that store. A product install has just the user's raw DNA plus
what Indaga downloads/computes — there is no other project on disk to borrow from. If a
subject hasn't been annotated yet, the readers return empty/None (honest "not computed
yet"), and the capability surfaces ``not_measured`` rather than a fabricated answer.

ClinVar is joined by genomic POSITION in the genome's build (the complete join — ~20% of
ClinVar P/LP rows lack an RS= tag), with rsID as a convenience. PharmCAT (PGx) and GWAS
are not yet computed in-house (Phase D) — they honestly report "not assessed" until then.
"""

from __future__ import annotations

from ..evidence.store import EvidenceStoreReader
from ..runtime import paths
from .agi import AGIReader


def _store(subject_id: str | None) -> EvidenceStoreReader | None:
    """Open the subject's in-house evidence reader iff annotation is complete."""
    if not subject_id:
        return None
    r = EvidenceStoreReader.open(paths.evidence_path(subject_id))
    if r is None:
        return None
    if not r.annotation_complete:
        r.close()
        return None
    return r


# ============================ ClinVar ===================================== #

def clinvar_for_rsid(user_dir: str | None, rsid: str, subject_id: str | None = None) -> dict | None:
    """ClinVar significance for an rsID: {gene, clinvar_sig, clinvar_disease, achange, effect}.
    Resolves rsID→position via the AGI so RS-less ClinVar records are found. None if the
    variant isn't in ClinVar (or the subject isn't annotated yet)."""
    r = _store(subject_id)
    if r is None:
        return None
    try:
        hit = r.clinvar_by_rsid(rsid, build=r.build)
        if hit is None:
            agi = AGIReader.open(str(paths.active_genome_index_path(subject_id)))
            if agi is not None:
                v = agi.lookup_rsid(rsid)
                if v is not None:
                    hit = r.clinvar_by_position(v.chrom, v.pos, build=r.build,
                                                carried_alleles=v.alleles)
                agi.close()
        return hit
    finally:
        r.close()


def pl_findings(user_dir: str | None = None, subject_id: str | None = None) -> list[dict]:
    """High-penetrance P/LP screen findings with honest false-alarm classification."""
    r = _store(subject_id)
    if r is None:
        return []
    try:
        return r.pl_findings()
    finally:
        r.close()


def pgs_scores(user_dir: str | None = None, subject_id: str | None = None) -> list[dict]:
    """Polygenic scores (PGS Catalog) as population percentiles."""
    r = _store(subject_id)
    if r is None:
        return []
    try:
        return r.pgs_results()
    finally:
        r.close()


# ============================ GWAS ======================================== #

def gwas_available(subject_id: str | None = None) -> bool:
    """True when GWAS associations CAN be answered for this subject — annotated, on a
    GRCh38 genome (the catalog's build), with the catalog installed. Lets the capability
    distinguish 'searched, nothing matched' (empty_consulted_scope) from 'can't assess'
    (not_measured)."""
    r = _store(subject_id)
    if r is None:
        return False
    try:
        if r.build != "GRCh38":
            return False
        if r.has_gwas:
            return True
        from ..reference import manager as refmgr
        return refmgr.gwas_zip_path().exists()  # installed → a query will self-heal-import
    finally:
        r.close()


def gwas_associations(user_dir: str | None = None, trait: str | None = None, limit: int = 25,
                      subject_id: str | None = None) -> list[dict]:
    """GWAS-Catalog trait/disease associations at loci the subject carries, strongest
    p-value first. Position-joins the GRCh38 catalog against the subject's imputed AGI
    (a GRCh37-only chip won't position-match). Empty if the subject isn't annotated, the
    catalog isn't installed, or the genome is GRCh37-only — the capability surfaces that
    honestly rather than fabricating associations."""
    r = _store(subject_id)
    if r is None:
        return []
    try:
        if not r.has_gwas:
            # self-heal: build the shared GWAS table once from the installed catalog so an
            # already-annotated subject gets GWAS without a full re-annotate.
            from ..evidence.store import import_gwas_catalog
            from ..reference import manager as refmgr
            zip_path = refmgr.gwas_zip_path()
            if not zip_path.exists():
                return []
            import_gwas_catalog(str(zip_path))
            r = EvidenceStoreReader.open(paths.evidence_path(subject_id))  # reopen to see new table
            if r is None:
                return []
        agi_path = str(paths.active_genome_index_path(subject_id))
        return r.gwas_carriers(agi_path, trait=trait, limit=limit, build=r.build)
    finally:
        r.close()


# ============================ PharmCAG (PGx) ============================== #
# In-house PharmCAT: Indaga downloads + runs PharmCAT on the subject's imputed genome
# (connectors/pharmcat.py), materializing the subject's own phenotype.json. These readers
# parse that file — no borrowed annotation. Empty until PharmCAT has been run for the
# subject, so the capability honestly reports "not assessed" rather than fabricating.

# diplotype labels / phenotypes that mean "no confident call" (an imputation blind spot).
_PGX_NOCALL = ("unknown", "no result", "indeterminate", "n/a")


def _is_reference_label(label: str | None) -> bool:
    """True if a diplotype is reference-only (``*1/*1``, ``Reference/Reference``). A NON-reference
    call requires an OBSERVED alt at a defining position, so it can never be a PharmCAT
    ``--absent-to-ref`` false-normal; only a reference call can rest on assumed (absent) positions."""
    parts = [p.strip() for p in (label or "").replace("(heterozygous)", "")
             .replace("(homozygous)", "").split("/")]
    return bool(parts) and all(p in ("*1", "Reference", "") for p in parts)


def _pharmcat_pheno_path(subject_id: str | None):
    if not subject_id:
        return None
    from ..connectors.pharmcat import phenotype_path
    p = phenotype_path(subject_id)
    return p if p.exists() else None


def pharmcat_report(user_dir: str | None = None, subject_id: str | None = None) -> str | None:
    """Path to the subject's own PharmCAT phenotype JSON, or None if PGx hasn't been run."""
    p = _pharmcat_pheno_path(subject_id)
    return str(p) if p else None


def pharmcat_available(subject_id: str | None = None) -> bool:
    return _pharmcat_pheno_path(subject_id) is not None


def pharmcat_genes(user_dir: str | None = None, subject_id: str | None = None) -> list[dict]:
    """Per-gene diplotypes + metabolizer phenotype from the subject's own PharmCAT run.
    ``called`` is False for genes the imputed genome can't confidently resolve (the honest
    PGx blind spots — e.g. CYP2C19/CYP2D6, which arrays/imputation under-call)."""
    import json
    p = _pharmcat_pheno_path(subject_id)
    if p is None:
        return []
    try:
        reports = json.loads(p.read_text(encoding="utf-8")).get("geneReports", {})
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for sym, g in sorted(reports.items()):
        src = (g.get("sourceDiplotypes") or [{}])[0]
        label = src.get("label") or ""
        phenotype = ", ".join(src.get("phenotypes") or []) or None
        a1 = (src.get("allele1") or {}).get("function")
        a2 = (src.get("allele2") or {}).get("function")
        function = a1 if a1 == a2 else (f"{a1} / {a2}" if (a1 or a2) else None)
        low = (label + " " + (phenotype or "")).lower()
        # defining-position coverage: PharmCAT runs with --absent-to-ref, which fills any PGx position
        # the imputed subset lacks with reference. That is safe for a NON-reference call (it needs an
        # observed alt) but a REFERENCE call resting on mostly-absent positions is an ASSUMPTION, not a
        # measurement — flag it so it is never dressed up as a confident "normal metabolizer".
        variants = g.get("variants") or []
        n_pos = len(variants)
        n_obs = sum(1 for v in variants if (v.get("call") or "").strip())
        coverage = round(n_obs / n_pos, 2) if n_pos else None
        reference_assumed = bool(_is_reference_label(label) and n_pos and (n_obs / n_pos) < 0.5)
        called = (g.get("callSource") == "MATCHER" and bool(label)
                  and not any(t in low for t in _PGX_NOCALL)
                  and not reference_assumed)  # a low-coverage reference-fill is not a confident call
        out.append({"gene": sym, "called": called, "diplotype": label or None,
                    "phenotype": phenotype, "function": function,
                    "activity_score": src.get("activityScore"),
                    "coverage": coverage, "reference_assumed": reference_assumed})
    return out
