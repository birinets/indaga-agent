"""MANE Select transcript model — the gene/exon/CDS coordinates Indaga's consequence
annotator needs to call molecular impact on NOVEL variants (the ones ClinVar doesn't carry).

Parses the MANE Select GFF (one clinically-canonical transcript per gene, GRCh38) into a
cached SQLite: per transcript, its strand + sorted exon and CDS intervals. From this the
consequence annotator derives reading frame (translate a codon → nonsense/missense) and
splice sites (exon-boundary ±1/2), and the P/LP screen restricts its AlphaMissense scan to
coding exons. stdlib only (gzip + sqlite3). Built once, cached via a source fingerprint.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

_CANON = {f"chr{c}" for c in [*(str(i) for i in range(1, 23)), "X", "Y"]}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS transcripts (
  transcript_id TEXT PRIMARY KEY, gene TEXT, chrom TEXT, strand TEXT,
  tx_start INTEGER, tx_end INTEGER, cds_json TEXT, exon_json TEXT
);
CREATE INDEX IF NOT EXISTS tx_region_idx ON transcripts(chrom, tx_start, tx_end);
CREATE INDEX IF NOT EXISTS tx_gene_idx ON transcripts(gene);
"""


def gene_model_db_path() -> Path:
    return refmgr._resolve(Path("resources", "mane", "gene_model.sqlite"))


def _norm_chrom(c: str) -> str:
    return c[3:] if c.lower().startswith("chr") else c


def _attrs(col9: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in col9.rstrip(";").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def build_gene_model(*, force: bool = False, auto_install: bool = True) -> dict:
    """Parse the MANE GFF into the cached transcript SQLite. No-op if already built for the
    same source unless ``force``. ``auto_install=False`` builds from an already-downloaded GFF but
    never triggers a download (the read-only grounding path)."""
    out = gene_model_db_path()
    gff = refmgr.ensure_mane(auto_install=auto_install)
    if gff is None:
        return {"status": "failed", "reason": "MANE GFF unavailable; run: indaga install mane-select"}
    st = gff.stat()
    fingerprint = f"{gff.name}:{st.st_size}:{int(st.st_mtime)}"
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(*) FROM transcripts").fetchone()[0]
                return {"status": "cached", "path": str(out), "transcripts": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    txs: dict[str, dict] = {}
    with gzip.open(gff, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) < 9 or c[0] not in _CANON:
                continue
            ftype, start, end, strand = c[2], int(c[3]), int(c[4]), c[6]
            a = _attrs(c[8])
            tid = a.get("transcript_id")
            if ftype == "transcript" and tid:
                txs[tid] = {"gene": a.get("gene_name"), "chrom": _norm_chrom(c[0]), "strand": strand,
                            "tx": (start, end), "cds": [], "exon": []}
            elif ftype == "exon" and tid in txs:
                txs[tid]["exon"].append((start, end))
            elif ftype == "CDS" and tid in txs:
                txs[tid]["cds"].append((start, end))

    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM transcripts")
        rows = []
        for tid, t in txs.items():
            if not t["cds"]:
                continue  # non-coding MANE entry — no consequence calling
            cds = sorted(t["cds"]); exon = sorted(t["exon"])
            rows.append((tid, t["gene"], t["chrom"], t["strand"], t["tx"][0], t["tx"][1],
                         json.dumps(cds), json.dumps(exon)))
        con.executemany("INSERT OR REPLACE INTO transcripts VALUES (?,?,?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        return {"status": "built", "path": str(out), "transcripts": len(rows)}
    finally:
        con.close()


class GeneModel:
    """Read side of the MANE transcript model (coding transcripts only)."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, *, build_if_missing: bool = True, auto_install: bool = True) -> "GeneModel | None":
        p = gene_model_db_path()
        if not p.exists():
            if not build_if_missing or \
                    build_gene_model(auto_install=auto_install).get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return cls(con)
        except sqlite3.Error:
            return None

    def transcript_at(self, chrom: str, pos: int) -> dict | None:
        """The coding transcript spanning (chrom, pos) — strand + CDS + exon intervals.
        chrom may be bare ('1') or 'chr1'. Returns the first/only MANE transcript there."""
        c = _norm_chrom(chrom)
        row = self._con.execute(
            "SELECT * FROM transcripts WHERE chrom=? AND tx_start<=? AND tx_end>=? "
            "ORDER BY (tx_end - tx_start) LIMIT 1", (c, int(pos), int(pos))).fetchone()
        if row is None:
            return None
        return {"transcript_id": row["transcript_id"], "gene": row["gene"], "chrom": row["chrom"],
                "strand": row["strand"], "cds": [tuple(x) for x in json.loads(row["cds_json"])],
                "exons": [tuple(x) for x in json.loads(row["exon_json"])]}

    def cds_intervals(self, gene: str) -> list[tuple[int, int]]:
        """Merged CDS intervals for a gene (its MANE transcript) — used to restrict scans to
        coding exons. Empty if the gene isn't a coding MANE transcript."""
        row = self._con.execute(
            "SELECT chrom, cds_json FROM transcripts WHERE gene=? LIMIT 1", (gene,)).fetchone()
        return [tuple(x) for x in json.loads(row["cds_json"])] if row else []

    def gene_chrom(self, gene: str) -> str | None:
        row = self._con.execute("SELECT chrom FROM transcripts WHERE gene=? LIMIT 1", (gene,)).fetchone()
        return row["chrom"] if row else None

    def close(self) -> None:
        self._con.close()
