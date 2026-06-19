"""Gene-disease validity — gene → graded disease associations (GenCC + ClinGen), for grounding (LOCAL).

The industry-standard replacement for hand-curated panels: GenCC aggregates 18 curators (ClinGen, Orphanet,
PanelApp, Labcorp/Invitae, G2P…) into one validity vocabulary; ClinGen adds native GCEP curations. Each
gene-disease assertion is GRADED (Definitive → Strong → Moderate → Limited → Disputed → Refuted) with a mode
of inheritance and a MONDO disease id. Parsed into a cached SQLite indexed by gene; queries aggregate to the
BEST validity per disease across sources. Build-once, cached by source fingerprint. stdlib only.

Licenses: GenCC submissions are **CC0**; ClinGen is free under its terms. Both downloaded locally → grounding
stays zero-egress (unlike querying OMIM/OpenTargets/HPO live, which leaks the gene of interest).
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

# canonical classification → numeric rank (higher = stronger validity)
_RANK = {
    "Definitive": 6, "Strong": 5, "Moderate": 4, "Supportive": 4, "Limited": 3,
    "Animal Model Only": 2, "No Known": 1, "Disputed": 0, "Refuted": -1,
}


def _canon_class(s: str | None) -> str:
    s = (s or "").strip()
    low = s.lower()
    if low.startswith("disputed"):
        return "Disputed"
    if low.startswith("refuted"):
        return "Refuted"
    if "no known" in low:
        return "No Known"
    return s or "Unknown"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS gene_disease (
  gene TEXT, disease TEXT, mondo TEXT, classification TEXT, rank INTEGER, moi TEXT, source TEXT
);
CREATE INDEX IF NOT EXISTS gd_gene_idx ON gene_disease(gene);
"""


def gene_disease_db_path() -> Path:
    return refmgr._resolve(Path("resources", "gene_disease", "gene_disease.sqlite"))


def _csv_rows(f, **kw):  # csv.reader honoring RFC-4180 quoted fields (GenCC notes embed tabs/newlines)
    return csv.reader(f, **kw)


def build_gene_disease_db(*, force: bool = False) -> dict:
    """Parse GenCC (TSV) + ClinGen (CSV) into the cached SQLite. Builds from whichever source(s) are
    present (at least one). No-op if already built for the same sources unless ``force``."""
    out = gene_disease_db_path()
    gencc, clingen = refmgr.ensure_gene_disease(auto_install=False)  # read-only grounding: no download
    if gencc is None and clingen is None:
        return {"status": "failed",
                "reason": "gene-disease validity unavailable; run: indaga install gene-disease-validity"}

    def _fp(p: Path | None) -> str:
        if p is None:
            return "-"
        st = p.stat()
        return f"{p.name}:{st.st_size}:{int(st.st_mtime)}"
    fingerprint = f"{_fp(gencc)}|{_fp(clingen)}"
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(DISTINCT gene) FROM gene_disease").fetchone()[0]
                return {"status": "cached", "path": str(out), "genes": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM gene_disease")
        batch: list[tuple] = []

        def _flush(force_flush: bool = False) -> None:
            if batch and (force_flush or len(batch) >= 20_000):
                con.executemany("INSERT INTO gene_disease VALUES (?,?,?,?,?,?,?)", batch)
                batch.clear()

        if gencc is not None:
            with open(gencc, newline="", encoding="utf-8", errors="replace") as fh:
                rdr = csv.DictReader(fh, delimiter="\t")
                for r in rdr:
                    gene = (r.get("gene_symbol") or "").strip()
                    if not gene:
                        continue
                    cls = _canon_class(r.get("classification_title"))
                    batch.append((gene.upper(), (r.get("disease_title") or "").strip(),
                                  (r.get("disease_curie") or "").strip(), cls, _RANK.get(cls, 1),
                                  (r.get("moi_title") or "").strip(),
                                  "GenCC:" + (r.get("submitter_title") or "?").strip()))
                    _flush()
        if clingen is not None:
            with open(clingen, newline="", encoding="utf-8", errors="replace") as fh:
                for c in _csv_rows(fh):
                    # data rows have an HGNC id in col 1; banner / separator / header rows do not
                    if len(c) < 7 or not c[1].startswith("HGNC:"):
                        continue
                    cls = _canon_class(c[6])
                    batch.append((c[0].strip().upper(), c[2].strip(), c[3].strip(), cls,
                                  _RANK.get(cls, 1), c[4].strip(), "ClinGen"))
                    _flush()
        _flush(force_flush=True)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        n = con.execute("SELECT count(DISTINCT gene) FROM gene_disease").fetchone()[0]
        m = con.execute("SELECT count(*) FROM gene_disease").fetchone()[0]
        return {"status": "built", "path": str(out), "genes": n, "assertions": m}
    finally:
        con.close()


class GeneDisease:
    """Read side — the graded disease associations for a gene, best-validity-per-disease across sources."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, *, build_if_missing: bool = True) -> "GeneDisease | None":
        p = gene_disease_db_path()
        if not p.exists():
            if not build_if_missing or build_gene_disease_db().get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return cls(con)
        except sqlite3.Error:
            return None

    def for_gene(self, gene: str, *, min_rank: int | None = None, limit: int = 40) -> list[dict]:
        """Diseases associated with ``gene`` (case-insensitive), aggregated to the BEST classification per
        disease across all sources, strongest first. ``min_rank`` filters (e.g. 3 = Limited+; 4 = Moderate+).
        Each entry lists the contributing sources."""
        rows = self._con.execute(
            "SELECT disease, mondo, classification, rank, moi, source FROM gene_disease WHERE gene=?",
            (gene.strip().upper(),)).fetchall()
        agg: dict[str, dict] = {}
        for r in rows:
            key = (r["mondo"] or r["disease"]).lower()
            cur = agg.get(key)
            if cur is None:
                agg[key] = {"disease": r["disease"], "mondo": r["mondo"],
                            "classification": r["classification"], "rank": r["rank"],
                            "moi": r["moi"], "sources": {r["source"]}}
            else:
                cur["sources"].add(r["source"])
                if r["rank"] > cur["rank"]:
                    cur.update(classification=r["classification"], rank=r["rank"],
                               moi=r["moi"], disease=r["disease"])
        out = []
        for v in agg.values():
            if min_rank is not None and v["rank"] < min_rank:
                continue
            out.append({"disease": v["disease"], "mondo": v["mondo"],
                        "classification": v["classification"], "moi": v["moi"],
                        "sources": sorted(v["sources"]), "n_sources": len(v["sources"])})
        out.sort(key=lambda d: (-_RANK.get(d["classification"], 1), d["disease"]))
        return out[:limit]

    def close(self) -> None:
        self._con.close()
