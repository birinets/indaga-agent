"""Gene Ontology — gene → GO biological-process / molecular-function / cellular-component terms (LOCAL).

The open slice of MSigDB-C5 / KEGG-ontology value, from CC BY 4.0 Gene Ontology data: the human GOA
annotation file (GAF — gene symbol → GO id) joined to the ontology (go-basic OBO — GO id → readable name +
namespace), cached as a SQLite indexed by gene symbol. Build-once, cached via a source fingerprint (the
genemodel idiom). stdlib only (gzip + sqlite3). Offline equivalent of the process/function context Genomi
pulls from live GO/MSigDB services.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

# OBO namespace → GAF-style aspect code
_ASPECT = {"biological_process": "P", "molecular_function": "F", "cellular_component": "C"}
ASPECT_LABEL = {"P": "biological_process", "F": "molecular_function", "C": "cellular_component"}

# overly-generic GO terms suppressed from a compact grounding summary (roots + ubiquitous binders/locations)
_GENERIC = frozenset({
    "GO:0008150", "GO:0003674", "GO:0005575",  # the three ontology roots
    "GO:0005515", "GO:0005488",                # protein binding, binding
    "GO:0005737", "GO:0005829", "GO:0005634", "GO:0016020",  # cytoplasm, cytosol, nucleus, membrane
})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS go_annot (gene TEXT, go_id TEXT, name TEXT, aspect TEXT);
CREATE INDEX IF NOT EXISTS go_gene_idx ON go_annot(gene);
"""


def go_db_path() -> Path:
    return refmgr._resolve(Path("resources", "go", "go_terms.sqlite"))


def _parse_obo(obo_path: Path) -> dict[str, tuple[str, str]]:
    """GO id → (term name, aspect code), skipping obsolete terms. Robust to stanza order (flush on the
    next ``[...]`` header), so it doesn't depend on blank-line separators."""
    names: dict[str, tuple[str, str]] = {}
    cur: dict | None = None

    def _flush(c: dict | None) -> None:
        if c and c.get("id") and c.get("name") and not c.get("obs"):
            names[c["id"]] = (c["name"], _ASPECT.get(c.get("ns", ""), "?"))

    with open(obo_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("[") and line.endswith("]"):
                _flush(cur)
                cur = {} if line == "[Term]" else None
                continue
            if cur is None:
                continue
            if line.startswith("id: "):
                cur["id"] = line[4:].strip()
            elif line.startswith("name: "):
                cur["name"] = line[6:].strip()
            elif line.startswith("namespace: "):
                cur["ns"] = line[11:].strip()
            elif line.startswith("is_obsolete: true"):
                cur["obs"] = True
    _flush(cur)
    return names


def build_go_db(*, force: bool = False) -> dict:
    """Parse the GAF (annotations) + OBO (names) into the cached SQLite. No-op if already built for the
    same sources unless ``force``. Drops obsolete/unknown GO ids, NOT-qualified (negative) annotations,
    and a small set of ubiquitous generic terms; de-duplicates (gene, GO id)."""
    out = go_db_path()
    paths = refmgr.ensure_gene_ontology(auto_install=False)  # read-only grounding: never download here
    if paths is None:
        return {"status": "failed", "reason": "Gene Ontology unavailable; run: indaga install gene-ontology"}
    gaf, obo = paths
    sg, so = gaf.stat(), obo.stat()
    fingerprint = f"{gaf.name}:{sg.st_size}:{int(sg.st_mtime)}|{obo.name}:{so.st_size}:{int(so.st_mtime)}"
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(DISTINCT gene) FROM go_annot").fetchone()[0]
                return {"status": "cached", "path": str(out), "genes": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    go_names = _parse_obo(obo)
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM go_annot")
        seen: set[tuple[str, str]] = set()
        batch: list[tuple[str, str, str, str]] = []
        with gzip.open(gaf, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("!"):
                    continue
                c = line.rstrip("\n").split("\t")
                if len(c) < 9:
                    continue
                symbol, qualifier, go_id = c[2].strip(), c[3], c[4].strip()
                if not symbol or not go_id or go_id in _GENERIC:
                    continue
                if "NOT" in qualifier.split("|"):        # negative annotation ("NOT involved in")
                    continue
                nm = go_names.get(go_id)
                if nm is None:                            # obsolete / not in go-basic
                    continue
                key = (symbol.upper(), go_id)
                if key in seen:
                    continue
                seen.add(key)
                batch.append((symbol.upper(), go_id, nm[0], nm[1]))
                if len(batch) >= 50_000:
                    con.executemany("INSERT INTO go_annot VALUES (?,?,?,?)", batch)
                    batch.clear()
        if batch:
            con.executemany("INSERT INTO go_annot VALUES (?,?,?,?)", batch)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        n = con.execute("SELECT count(DISTINCT gene) FROM go_annot").fetchone()[0]
        return {"status": "built", "path": str(out), "genes": n, "terms": len(seen)}
    finally:
        con.close()


class GoTerms:
    """Read side of the GO annotations — the GO terms annotated to a gene, by aspect."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, *, build_if_missing: bool = True) -> "GoTerms | None":
        p = go_db_path()
        if not p.exists():
            if not build_if_missing or build_go_db().get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return cls(con)
        except sqlite3.Error:
            return None

    def terms_for_gene(self, gene: str, *, aspect: str | None = None, limit: int = 30) -> list[dict]:
        """GO terms annotated to ``gene`` (case-insensitive), optionally restricted to one aspect code
        ('P'/'F'/'C'), ordered by aspect then name. Empty if the gene has no GO annotation."""
        q = "SELECT go_id, name, aspect FROM go_annot WHERE gene=?"
        args: list = [gene.strip().upper()]
        if aspect:
            q += " AND aspect=?"
            args.append(aspect)
        q += " ORDER BY aspect, name LIMIT ?"
        args.append(int(limit))
        rows = self._con.execute(q, args).fetchall()
        return [{"go_id": r["go_id"], "name": r["name"], "aspect": r["aspect"],
                 "aspect_label": ASPECT_LABEL.get(r["aspect"], r["aspect"])} for r in rows]

    def close(self) -> None:
        self._con.close()
