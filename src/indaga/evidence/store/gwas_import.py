"""Import the GWAS Catalog associations TSV into the shared evidence DB.

The EBI GWAS Catalog ships ~600k curated trait/disease associations as a zipped TSV
(``gwas-catalog-associations_ontology-annotated-full``). We import the
(position, rsID)-keyed subset needed to answer "what traits are associated with the
variants this subject carries". Catalog positions are **GRCh38** (its current build),
matching the imputed AGI — so the screen position-joins cleanly against it. Build-once,
cached via a source fingerprint. stdlib only (zipfile + sqlite3).

Only single-locus associations are imported: rows whose ``CHR_POS`` is one integer.
SNP×SNP-interaction / haplotype rows (``;``- or ``x``-joined positions) are skipped —
they have no single genomic coordinate to join the subject's genotype against.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import connection as conn

_BATCH = 50_000
_VALID_CHROM = {str(i) for i in range(1, 23)} | {"X", "Y", "MT"}

# Header names we depend on (the catalog occasionally reorders columns, so we map by
# name rather than hard-coding indexes).
_COLS = {
    "pmid": "PUBMEDID",
    "trait": "DISEASE/TRAIT",
    "chrom": "CHR_ID",
    "pos": "CHR_POS",
    "gene": "MAPPED_GENE",
    "rsid": "SNPS",
    "pval": "P-VALUE",
    "mlog": "PVALUE_MLOG",
    "or_beta": "OR or BETA",
}


def _source_fingerprint(path: Path) -> str:
    st = path.stat()
    return f"{path.name}:{st.st_size}:{int(st.st_mtime)}"


def _clean_chrom(raw: str) -> str | None:
    c = raw.strip()
    c = c[3:] if c.lower().startswith("chr") else c
    if c == "23":
        c = "X"
    elif c == "24":
        c = "Y"
    return c if c in _VALID_CHROM else None


def _clean_rsid(raw: str) -> str | None:
    """SNPS may be 'rs7903146', 'rs1 x rs2', 'rs1; rs2' or a chr:pos — keep the first rsID."""
    s = raw.strip()
    if not s:
        return None
    for sep in (";", "x", ",", " "):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    return s or None


def _to_float(raw: str) -> float | None:
    s = raw.strip()
    if not s:
        return None
    try:
        return float(s)         # handles scientific notation, e.g. '5E-8'
    except ValueError:
        return None


def import_gwas_catalog(zip_path: str | Path, shared_path: str | Path | None = None,
                        *, force: bool = False) -> dict:
    """Import the zipped GWAS Catalog TSV into ``shared-evidence.sqlite``. Cached (no-op)
    on a repeat call with the same source fingerprint unless ``force``."""
    zp = Path(zip_path)
    if not zp.exists():
        raise FileNotFoundError(zp)
    fingerprint = _source_fingerprint(zp)

    con = conn.init_shared(shared_path)
    try:
        if not force and conn.get_meta(con, "gwas_fingerprint") == fingerprint:
            n = con.execute("SELECT count(*) AS c FROM gwas_associations").fetchone()["c"]
            return {"status": "cached", "rows": n, "source": str(zp)}

        con.execute("DELETE FROM gwas_associations")
        con.execute("DROP INDEX IF EXISTS gwas_assoc_pos_idx")
        con.execute("DROP INDEX IF EXISTS gwas_assoc_rsid_idx")
        con.commit()
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA cache_size=-131072")

        zf = zipfile.ZipFile(zp)
        member = next((m for m in zf.namelist() if m.lower().endswith(".tsv")), zf.namelist()[0])
        rows: list[tuple] = []
        scanned = inserted = skipped = 0
        cur = con.cursor()

        def flush():
            if rows:
                cur.executemany(
                    "INSERT INTO gwas_associations(chrom,pos,rsid,trait,gene,or_beta,pval,mlog,pmid) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", rows)
            rows.clear()

        with zf.open(member) as raw:
            header = raw.readline().decode("utf-8", "replace").rstrip("\r\n").split("\t")
            idx = {key: header.index(name) for key, name in _COLS.items() if name in header}
            missing = [name for key, name in _COLS.items() if key not in idx]
            if missing:
                raise ValueError(f"GWAS Catalog header missing columns: {missing}")
            ci, pi = idx["chrom"], idx["pos"]
            for line in raw:
                f = line.decode("utf-8", "replace").rstrip("\r\n").split("\t")
                if len(f) <= pi:
                    continue
                scanned += 1
                chrom = _clean_chrom(f[ci])
                pos_raw = f[pi].strip()
                mlog = _to_float(f[idx["mlog"]])  # -log10(p): underflow-safe significance key
                if chrom is None or not pos_raw.isdigit() or not mlog or mlog <= 0:
                    skipped += 1               # multi-locus / unmapped / no significance
                    continue
                rows.append((
                    chrom, int(pos_raw), _clean_rsid(f[idx["rsid"]]),
                    f[idx["trait"]].strip() or None, f[idx["gene"]].strip() or None,
                    f[idx["or_beta"]].strip() or None, _to_float(f[idx["pval"]]), mlog,
                    f[idx["pmid"]].strip() or None,
                ))
                inserted += 1
                if len(rows) >= _BATCH:
                    flush()
        flush()
        con.commit()

        conn.set_meta(con, "gwas_fingerprint", fingerprint)
        conn.set_meta(con, "gwas_source", str(zp))
        conn.set_meta(con, "gwas_imported_at", datetime.now(timezone.utc).isoformat())
        con.commit()  # close metadata txn before changing safety level
        con.execute("PRAGMA synchronous=NORMAL")
        conn.ensure_shared_indexes(con)
        return {"status": "imported", "scanned": scanned, "rows": inserted,
                "skipped_multilocus": skipped, "source": str(zp)}
    finally:
        con.close()
