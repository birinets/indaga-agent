"""The investigation journal — persistent, per-subject working memory for an analysis (LOCAL).

A genomic/health investigation runs across many turns and sessions: questions asked, variants examined,
hypotheses raised, things RULED OUT, conclusions reached. Without a record, a later session re-derives what
was already settled. The journal is that record — an append-only, timestamped case-file under the subject's
secured store (``~/.indaga/<subject>/journal.sqlite``, 0600).

It is deliberately SEPARATE from the ``HealthlakeStore`` health-fact port: journal entries are *operational*
investigation notes (the agent's reasoning trail), not graded n=1 health facts, so they don't belong in the
evidence-bearing fact model. Still strictly one-subject (the file lives in that subject's tree). stdlib only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import paths

# the kinds of entry an investigation accumulates
KINDS = ("question", "finding", "hypothesis", "ruled_out", "conclusion", "next_step", "note")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,            -- ISO-8601 timestamp (injected by the caller for determinism)
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  gene TEXT, rsid TEXT, tool TEXT,
  refs_json TEXT               -- optional JSON blob of extra references (allele_id, pmids, …)
);
CREATE INDEX IF NOT EXISTS j_kind_idx ON entries(kind);
CREATE INDEX IF NOT EXISTS j_gene_idx ON entries(gene);
"""


class Journal:
    """Append-only investigation log for one subject."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    @classmethod
    def open(cls, subject_id: str) -> "Journal":
        paths.secure_dir(paths.subject_dir(subject_id))
        p = paths.journal_path(subject_id)
        fresh = not Path(p).exists()
        con = sqlite3.connect(str(p))
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        con.commit()
        if fresh:
            paths.secure_file(p)  # lock 0600 on creation (least-privilege)
        return cls(con)

    def append(self, kind: str, text: str, *, ts: str, gene: str | None = None,
               rsid: str | None = None, tool: str | None = None, refs_json: str | None = None) -> int:
        """Record an entry; returns its id. ``kind`` is coerced into the known vocabulary (else 'note');
        ``ts`` is supplied by the caller (injectable) so the store stays deterministic in tests."""
        k = kind if kind in KINDS else "note"
        cur = self._con.execute(
            "INSERT INTO entries (ts, kind, text, gene, rsid, tool, refs_json) VALUES (?,?,?,?,?,?,?)",
            (ts, k, text, gene, rsid, tool, refs_json))
        self._con.commit()
        return int(cur.lastrowid)

    def entries(self, *, kind: str | None = None, gene: str | None = None,
                limit: int = 100, newest_first: bool = True) -> list[dict]:
        """Read the log, optionally filtered by kind and/or gene (case-insensitive)."""
        q = "SELECT id, ts, kind, text, gene, rsid, tool, refs_json FROM entries"
        clauses, args = [], []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if gene:
            clauses.append("UPPER(gene) = ?")
            args.append(gene.strip().upper())
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += f" ORDER BY id {'DESC' if newest_first else 'ASC'} LIMIT ?"
        args.append(int(limit))
        return [dict(r) for r in self._con.execute(q, args).fetchall()]

    def counts_by_kind(self) -> dict[str, int]:
        rows = self._con.execute("SELECT kind, COUNT(*) c FROM entries GROUP BY kind").fetchall()
        return {r["kind"]: r["c"] for r in rows}

    def close(self) -> None:
        self._con.close()
