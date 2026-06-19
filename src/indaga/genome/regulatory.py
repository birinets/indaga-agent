"""ENCODE SCREEN candidate cis-Regulatory Elements (cCREs) — locus → regulatory element, for grounding.

Fills ``grounding.region``'s blind spot: the MANE gene model only sees coding transcripts, so it labels a
non-coding variant "intron" / "intergenic" with no idea whether it sits in a *regulatory* element. This
parses the ENCODE GRCh38 cCRE BED (``chrom start end accession accession cCRE-class``; ~2.3 M elements:
promoter-like / enhancer-like / CTCF / chromatin-accessible) into a cached SQLite with an interval index,
so a point lookup returns the overlapping element(s). Build-once, cached via a source fingerprint. BED is
0-based half-open; queries take a 1-based genomic position. stdlib only.

Offline equivalent of the regulatory-region context Genomi pulls from live ENCODE/GENCODE APIs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

# readable labels for the SCREEN V4 cCRE classes
CCRE_LABELS = {
    "PLS": "promoter-like signature",
    "pELS": "proximal enhancer-like signature",
    "dELS": "distal enhancer-like signature",
    "CA-CTCF": "chromatin-accessible + CTCF-bound (insulator-like)",
    "CA-TF": "chromatin-accessible + TF-bound",
    "CA-H3K4me3": "chromatin-accessible + H3K4me3 (promoter-proximal)",
    "CA": "chromatin-accessible only",
    "TF": "TF-bound only",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ccre (chrom TEXT, start INTEGER, end INTEGER, ccre_class TEXT);
CREATE INDEX IF NOT EXISTS ccre_pos_idx ON ccre(chrom, start, end);
"""


def _norm_chrom(c: str) -> str:
    c = str(c).strip()
    return c[3:] if c.lower().startswith("chr") else c


def regulatory_db_path() -> Path:
    return refmgr._resolve(Path("resources", "encode", "ccre.sqlite"))


def build_regulatory_db(*, force: bool = False) -> dict:
    """Parse the ENCODE cCRE BED into the cached SQLite. No-op if already built for the same source unless
    ``force``. Records the longest element so a point query can be bounded to a small index range."""
    out = regulatory_db_path()
    bed = refmgr.ensure_encode_ccre(auto_install=False)  # read-only grounding: never download here
    if bed is None:
        return {"status": "failed", "reason": "ENCODE cCRE BED unavailable; run: indaga install encode-ccre"}
    st = bed.stat()
    fingerprint = f"{bed.name}:{st.st_size}:{int(st.st_mtime)}"
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(*) FROM ccre").fetchone()[0]
                return {"status": "cached", "path": str(out), "elements": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM ccre")
        batch: list[tuple[str, int, int, str]] = []
        max_len = 0
        with open(bed, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                c = line.rstrip("\n").split("\t")
                if len(c) < 6:
                    continue
                try:
                    start, end = int(c[1]), int(c[2])
                except ValueError:
                    continue
                max_len = max(max_len, end - start)
                batch.append((_norm_chrom(c[0]), start, end, c[5]))
                if len(batch) >= 50_000:
                    con.executemany("INSERT INTO ccre VALUES (?,?,?,?)", batch)
                    batch.clear()
        if batch:
            con.executemany("INSERT INTO ccre VALUES (?,?,?,?)", batch)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('max_len', ?)", (str(max_len),))
        con.commit()
        n = con.execute("SELECT count(*) FROM ccre").fetchone()[0]
        return {"status": "built", "path": str(out), "elements": n, "max_len": max_len}
    finally:
        con.close()


class RegulatoryElements:
    """Read side of the ENCODE cCRE registry — the regulatory element(s) overlapping a locus."""

    def __init__(self, con: sqlite3.Connection, max_len: int) -> None:
        self._con = con
        self._max_len = max_len

    @classmethod
    def open(cls, *, build_if_missing: bool = True) -> "RegulatoryElements | None":
        p = regulatory_db_path()
        if not p.exists():
            if not build_if_missing or build_regulatory_db().get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT value FROM meta WHERE key='max_len'").fetchone()
            return cls(con, int(row[0]) if row else 5000)
        except sqlite3.Error:
            return None

    def at(self, chrom: str, pos: int) -> list[dict]:
        """cCRE(s) overlapping a 1-based genomic position. BED is 0-based half-open [start,end), so a
        1-based pos overlaps iff ``start < pos <= end``. The start range is bounded by the longest element
        so the index seek stays small."""
        c = _norm_chrom(chrom)
        p = int(pos)
        rows = self._con.execute(
            "SELECT ccre_class, start, end FROM ccre "
            "WHERE chrom=? AND start>=? AND start<? AND end>=? ORDER BY start",
            (c, p - self._max_len - 1, p, p)).fetchall()
        out = []
        for r in rows:
            out.append({"ccre_class": r["ccre_class"],
                        "label": CCRE_LABELS.get(r["ccre_class"], r["ccre_class"]),
                        "start": r["start"], "end": r["end"]})
        return out

    def close(self) -> None:
        self._con.close()
