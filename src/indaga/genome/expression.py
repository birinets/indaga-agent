"""Human Protein Atlas consensus tissue RNA — gene → per-tissue expression (nTPM), for grounding (LOCAL).

Parses the HPA consensus TSV (``Gene<TAB>Gene name<TAB>Tissue<TAB>nTPM``; ~1.0 M rows over 51 tissues /
20,162 genes) into a cached SQLite indexed by gene symbol, so a "where is this gene expressed" query is an
indexed top-N lookup rather than a ~40 MB re-parse. Built once, cached via a source fingerprint — the same
build-once idiom as the MANE ``genemodel``. stdlib only (sqlite3).

This is the offline equivalent of the tissue context Genomi pulls from the live HPA API: same biology, but
the gene-of-interest never leaves the device.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS expr (gene TEXT, tissue TEXT, ntpm REAL);
CREATE INDEX IF NOT EXISTS expr_gene_idx ON expr(gene);
"""


def expression_db_path() -> Path:
    return refmgr._resolve(Path("resources", "hpa", "tissue_expression.sqlite"))


def build_expression_db(*, force: bool = False) -> dict:
    """Parse the HPA consensus tissue TSV into the cached expression SQLite. No-op if already built for
    the same source unless ``force``. Inserts in batches so the 1 M rows never all live in memory."""
    out = expression_db_path()
    # read-only grounding: build from an already-installed TSV; never trigger a download
    tsv = refmgr.ensure_hpa_tissue(auto_install=False)
    if tsv is None:
        return {"status": "failed", "reason": "HPA tissue TSV unavailable; run: indaga install hpa-tissue-rna"}
    st = tsv.stat()
    fingerprint = f"{tsv.name}:{st.st_size}:{int(st.st_mtime)}"
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(DISTINCT gene) FROM expr").fetchone()[0]
                return {"status": "cached", "path": str(out), "genes": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM expr")
        batch: list[tuple[str, str, float]] = []
        with open(tsv, encoding="utf-8", errors="replace") as fh:
            fh.readline()  # header: Gene \t Gene name \t Tissue \t nTPM
            for line in fh:
                c = line.rstrip("\n").split("\t")
                if len(c) < 4 or not c[1]:
                    continue
                try:
                    val = float(c[3])
                except ValueError:
                    continue
                batch.append((c[1].upper(), c[2], val))
                if len(batch) >= 50_000:
                    con.executemany("INSERT INTO expr VALUES (?,?,?)", batch)
                    batch.clear()
        if batch:
            con.executemany("INSERT INTO expr VALUES (?,?,?)", batch)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        n = con.execute("SELECT count(DISTINCT gene) FROM expr").fetchone()[0]
        return {"status": "built", "path": str(out), "genes": n}
    finally:
        con.close()


class TissueExpression:
    """Read side of the HPA consensus tissue expression — top tissues for a gene, by nTPM."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, *, build_if_missing: bool = True) -> "TissueExpression | None":
        p = expression_db_path()
        if not p.exists():
            if not build_if_missing or build_expression_db().get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return cls(con)
        except sqlite3.Error:
            return None

    def top_tissues(self, gene: str, *, limit: int = 10) -> list[dict]:
        """The ``limit`` tissues with the highest consensus nTPM for ``gene`` (case-insensitive),
        highest first. Empty if the gene is not in the HPA consensus table."""
        rows = self._con.execute(
            "SELECT tissue, ntpm FROM expr WHERE gene=? ORDER BY ntpm DESC, tissue LIMIT ?",
            (gene.strip().upper(), int(limit))).fetchall()
        return [{"tissue": r["tissue"], "ntpm": round(r["ntpm"], 1)} for r in rows]

    def close(self) -> None:
        self._con.close()
