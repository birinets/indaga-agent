"""Import a ClinVar VCF into the shared evidence DB (slim port of
genomi/evidence/store/clinvar_import.py).

Imports the FULL ClinVar (all records) keyed by genomic position, plus rsID and
gene join-indexes. The position key is load-bearing: ~20% of ClinVar P/LP records
carry NO ``RS=`` tag, so a position join (chip's native build vs same-build ClinVar)
is the only complete one. Build-scoped + idempotent via a per-build source
fingerprint. stdlib only (gzip + sqlite3).
"""

from __future__ import annotations

import gzip
from datetime import datetime, timezone
from pathlib import Path

from . import connection as conn

_BATCH = 50_000


def _info_get(info: str, key: str) -> str | None:
    """Extract one INFO subfield value (``;KEY=VALUE;``) without a full parse."""
    token = key + "="
    if info.startswith(token):
        start = len(token)
    else:
        j = info.find(";" + token)
        if j < 0:
            return None
        start = j + 1 + len(token)
    end = info.find(";", start)
    return info[start:end] if end >= 0 else info[start:]


def _gene_symbols(geneinfo: str | None) -> list[str]:
    """GENEINFO=SYM:ID|SYM2:ID2 → [SYM, SYM2]."""
    if not geneinfo:
        return []
    return [p.split(":", 1)[0].strip() for p in geneinfo.split("|") if p.split(":", 1)[0].strip()]


def _consequences(mc: str | None) -> str | None:
    """MC=SO:0001587|nonsense,SO:0001627|intron_variant → 'nonsense,intron_variant'."""
    if not mc:
        return None
    terms = [p.split("|", 1)[1] for p in mc.split(",") if "|" in p]
    return ",".join(terms) or None


def _clean(v: str | None) -> str | None:
    """ClinVar uses '_' for spaces in INFO; restore for human-facing fields."""
    return v.replace("_", " ") if v else v


def _source_fingerprint(vcf: Path) -> str:
    st = vcf.stat()
    return f"{vcf.name}:{st.st_size}:{int(st.st_mtime)}"


def import_clinvar_vcf(clinvar_vcf: str | Path, shared_path: str | Path | None = None,
                       *, genome_build: str = "GRCh37", force: bool = False) -> dict:
    """Import all ClinVar rows for one build into the shared evidence DB. Cached (no-op)
    on a repeat call with the same source fingerprint unless ``force``. Build-scoped:
    re-importing one build leaves other builds' rows intact."""
    vcf = Path(clinvar_vcf)
    if not vcf.exists():
        raise FileNotFoundError(vcf)
    fingerprint = _source_fingerprint(vcf)
    fp_key = f"clinvar_fingerprint_{genome_build}"

    con = conn.init_shared(shared_path)
    try:
        if not force and conn.get_meta(con, fp_key) == fingerprint:
            n = con.execute("SELECT count(*) AS c FROM clinvar_variants WHERE genome_build=?",
                            (genome_build,)).fetchone()["c"]
            return {"status": "cached", "build": genome_build, "rows": n, "source": str(vcf)}

        # build-scoped wipe
        con.execute("DELETE FROM clinvar_variants WHERE genome_build=?", (genome_build,))
        con.execute("DELETE FROM clinvar_variant_rsids WHERE genome_build=?", (genome_build,))
        con.execute("DELETE FROM clinvar_variant_genes WHERE genome_build=?", (genome_build,))
        con.execute("DROP INDEX IF EXISTS clinvar_variant_idx")
        con.execute("DROP INDEX IF EXISTS clinvar_variant_rsids_rsid_idx")
        con.execute("DROP INDEX IF EXISTS clinvar_variant_genes_gene_idx")
        con.commit()
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA cache_size=-131072")

        next_rowid = (con.execute("SELECT COALESCE(MAX(rowid),0) AS m FROM clinvar_variants")
                      .fetchone()["m"]) + 1
        rows: list[tuple] = []
        rsid_rows: list[tuple] = []
        gene_rows: list[tuple] = []
        scanned = inserted = with_rs = 0
        cur = con.cursor()

        def flush():
            if rows:
                cur.executemany(
                    "INSERT INTO clinvar_variants(rowid,chrom,pos,ref,alt,genome_build,clinvar_id,"
                    "allele_id,clinical_significance,review_status,conditions,gene_info,hgvs,mc) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            if rsid_rows:
                cur.executemany("INSERT OR IGNORE INTO clinvar_variant_rsids VALUES (?,?,?)", rsid_rows)
            if gene_rows:
                cur.executemany("INSERT INTO clinvar_variant_genes VALUES (?,?,?)", gene_rows)
            rows.clear(); rsid_rows.clear(); gene_rows.clear()

        with gzip.open(vcf, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                f = line.rstrip("\n").split("\t")
                if len(f) < 8:
                    continue
                chrom, pos, vid, ref, alt, info = f[0], f[1], f[2], f[3], f[4], f[7]
                try:
                    ipos = int(pos)
                except ValueError:
                    continue
                scanned += 1
                clnsig = _info_get(info, "CLNSIG")
                clnrev = _info_get(info, "CLNREVSTAT")
                clndn = _info_get(info, "CLNDN")
                clnhgvs = _info_get(info, "CLNHGVS")
                alleleid = _info_get(info, "ALLELEID")
                geneinfo = _info_get(info, "GENEINFO")
                genes = _gene_symbols(geneinfo)
                mc = _consequences(_info_get(info, "MC"))
                rs = _info_get(info, "RS")
                rsid = ("rs" + rs.split("|")[0].strip()) if rs else None
                if rsid:
                    with_rs += 1
                for a in alt.split(","):
                    rid = next_rowid
                    next_rowid += 1
                    rows.append((rid, chrom, ipos, ref, a, genome_build, vid, alleleid,
                                 _clean(clnsig), _clean(clnrev), _clean(clndn), geneinfo, clnhgvs, mc))
                    if rsid:
                        rsid_rows.append((rsid, rid, genome_build))
                    for g in genes:
                        gene_rows.append((g, rid, genome_build))
                    inserted += 1
                if len(rows) >= _BATCH:
                    flush()
        flush()
        con.commit()

        conn.set_meta(con, fp_key, fingerprint)
        conn.set_meta(con, f"clinvar_source_{genome_build}", str(vcf))
        conn.set_meta(con, f"clinvar_imported_at_{genome_build}", datetime.now(timezone.utc).isoformat())
        con.commit()  # close metadata txn before changing safety level
        con.execute("PRAGMA synchronous=NORMAL")
        conn.ensure_shared_indexes(con)
        return {"status": "imported", "build": genome_build, "scanned": scanned,
                "rows": inserted, "with_rsid": with_rs, "source": str(vcf)}
    finally:
        con.close()
