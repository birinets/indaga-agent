"""Human Protein Atlas single-cell-type RNA — gene → per-cell-type expression (nCPM), for grounding (LOCAL).

The cell-type-resolution companion to the bulk-tissue ``expression`` module: parses the HPA single-cell TSV
(``Gene<TAB>Gene name<TAB>Cell type<TAB>nCPM``; ~3.1 M rows over ~80 cell types) into a cached SQLite indexed
by gene symbol, so a "which cell types express this gene" query is an indexed top-N lookup, not a ~120 MB
re-parse. Build-once, cached via a source fingerprint (the genemodel idiom). stdlib only.

Offline equivalent of the single-cell context Genomi pulls from live HPA/CellMarker APIs — same biology, the
gene-of-interest never leaves the device.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sc_expr (gene TEXT, cell_type TEXT, ncpm REAL);
CREATE INDEX IF NOT EXISTS sc_gene_idx ON sc_expr(gene);
"""


def celltype_db_path() -> Path:
    return refmgr._resolve(Path("resources", "hpa", "singlecell_expression.sqlite"))


def build_celltype_db(*, force: bool = False) -> dict:
    """Parse the HPA single-cell TSV into the cached SQLite. No-op if already built for the same source
    unless ``force``. Inserts in batches so the 3 M rows never all live in memory."""
    out = celltype_db_path()
    tsv = refmgr.ensure_hpa_singlecell(auto_install=False)  # read-only grounding: never download here
    if tsv is None:
        return {"status": "failed", "reason": "HPA single-cell TSV unavailable; run: indaga install hpa-single-cell"}
    st = tsv.stat()
    fingerprint = f"{tsv.name}:{st.st_size}:{int(st.st_mtime)}"
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(DISTINCT gene) FROM sc_expr").fetchone()[0]
                return {"status": "cached", "path": str(out), "genes": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM sc_expr")
        batch: list[tuple[str, str, float]] = []
        with open(tsv, encoding="utf-8", errors="replace") as fh:
            fh.readline()  # header: Gene \t Gene name \t Cell type \t nCPM
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
                    con.executemany("INSERT INTO sc_expr VALUES (?,?,?)", batch)
                    batch.clear()
        if batch:
            con.executemany("INSERT INTO sc_expr VALUES (?,?,?)", batch)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        n = con.execute("SELECT count(DISTINCT gene) FROM sc_expr").fetchone()[0]
        return {"status": "built", "path": str(out), "genes": n}
    finally:
        con.close()


class CellTypeExpression:
    """Read side of the HPA single-cell expression — top cell types for a gene, by nCPM."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, *, build_if_missing: bool = True) -> "CellTypeExpression | None":
        p = celltype_db_path()
        if not p.exists():
            if not build_if_missing or build_celltype_db().get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return cls(con)
        except sqlite3.Error:
            return None

    def top_cell_types(self, gene: str, *, limit: int = 10) -> list[dict]:
        """The ``limit`` cell types with the highest single-cell nCPM for ``gene`` (case-insensitive),
        highest first. Empty if the gene is not in the HPA single-cell table."""
        rows = self._con.execute(
            "SELECT cell_type, ncpm FROM sc_expr WHERE gene=? ORDER BY ncpm DESC, cell_type LIMIT ?",
            (gene.strip().upper(), int(limit))).fetchall()
        return [{"cell_type": r["cell_type"], "ncpm": round(r["ncpm"], 1)} for r in rows]

    def close(self) -> None:
        self._con.close()
