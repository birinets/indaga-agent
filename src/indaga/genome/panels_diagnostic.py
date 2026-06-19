"""Genomics England PanelApp — diagnostic gene panels (green genes per disorder), for grounding (LOCAL).

The best-in-class *disease-specific* diagnostic tier: PanelApp curates signed-off gene panels per disorder
with a traffic-light rating; **green = diagnostic-grade** (sufficient evidence to use diagnostically). Indaga
ships a curated set of the high-value signed-off panels (cardiomyopathy/arrhythmia/aortopathy, hereditary
cancer, FH, thrombophilia, amyloidosis), parses their green genes from the downloaded panel JSONs into a
cached SQLite, and answers "which diagnostic panels is this gene green in". Build-once, cached by source
fingerprint. stdlib only (json + sqlite3).

LICENCE: PanelApp's data licence is informal (good-faith, liability disclaimer) — fine for personal/research
use; **commercial redistribution needs Genomics England sign-off** (flagged on the LibrarySpec). Downloaded
locally → grounding stays zero-egress.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..reference import manager as refmgr

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS panel (panel_id INTEGER PRIMARY KEY, name TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS panel_gene (panel_id INTEGER, gene TEXT, moi TEXT);
CREATE INDEX IF NOT EXISTS pg_gene_idx ON panel_gene(gene);
"""


def diagnostic_db_path() -> Path:
    return refmgr._resolve(Path("resources", "panelapp", "diagnostic_panels.sqlite"))


def build_diagnostic_panels_db(*, force: bool = False) -> dict:
    """Parse the downloaded PanelApp panel JSONs (green genes only) into the cached SQLite. No-op if
    already built for the same sources unless ``force``."""
    out = diagnostic_db_path()
    d = refmgr.ensure_panelapp(auto_install=False)  # read-only grounding: never download here
    if d is None:
        return {"status": "failed", "reason": "PanelApp panels unavailable; run: indaga install panelapp-green"}
    jsons = sorted(p for p in d.glob("*.json"))
    if not jsons:
        return {"status": "failed", "reason": "no PanelApp panel JSONs present"}
    fingerprint = "|".join(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}" for p in jsons)
    if out.exists() and not force:
        con = sqlite3.connect(str(out))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                n = con.execute("SELECT count(*) FROM panel").fetchone()[0]
                return {"status": "cached", "path": str(out), "panels": n}
        except sqlite3.Error:
            pass
        finally:
            con.close()

    con = sqlite3.connect(str(out))
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM panel")
        con.execute("DELETE FROM panel_gene")
        n_panels = n_green = 0
        for jp in jsons:
            try:
                doc = json.loads(jp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pid = doc.get("id")
            if pid is None:
                continue
            con.execute("INSERT OR REPLACE INTO panel VALUES (?,?,?)",
                        (int(pid), (doc.get("name") or "").strip(), str(doc.get("version") or "")))
            n_panels += 1
            rows = []
            for g in doc.get("genes") or []:
                if str(g.get("confidence_level")) != "3":           # green = diagnostic-grade only
                    continue
                sym = ((g.get("gene_data") or {}).get("gene_symbol") or "").strip()
                if not sym:
                    continue
                rows.append((int(pid), sym.upper(), (g.get("mode_of_inheritance") or "").strip()))
            con.executemany("INSERT INTO panel_gene VALUES (?,?,?)", rows)
            n_green += len(rows)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        return {"status": "built", "path": str(out), "panels": n_panels, "green_genes": n_green}
    finally:
        con.close()


class DiagnosticPanels:
    """Read side — the green (diagnostic-grade) PanelApp panels a gene appears in."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, *, build_if_missing: bool = True) -> "DiagnosticPanels | None":
        p = diagnostic_db_path()
        if not p.exists():
            if not build_if_missing or build_diagnostic_panels_db().get("status") not in ("built", "cached"):
                return None
        try:
            con = sqlite3.connect(str(p))
            con.row_factory = sqlite3.Row
            return cls(con)
        except sqlite3.Error:
            return None

    def panels_for_gene(self, gene: str) -> list[dict]:
        """The diagnostic panels in which ``gene`` is a green (diagnostic-grade) gene."""
        rows = self._con.execute(
            "SELECT p.panel_id, p.name, p.version, g.moi FROM panel_gene g "
            "JOIN panel p ON p.panel_id = g.panel_id WHERE g.gene=? ORDER BY p.name",
            (gene.strip().upper(),)).fetchall()
        return [{"panel": r["name"], "panel_id": r["panel_id"], "version": r["version"],
                 "inheritance": r["moi"] or None} for r in rows]

    def close(self) -> None:
        self._con.close()
