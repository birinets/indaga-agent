"""Journal capability — the persistent investigation memory (Genomi's journal layer, owned + local).

An analysis spans many turns/sessions; the journal records its REASONING TRAIL — questions asked, findings,
hypotheses, things ruled out, conclusions, next steps — so a later session resumes instead of re-deriving.
Three tools over the per-subject ``runtime.journal.Journal`` store (``~/.indaga/<subject>/journal.sqlite``,
0600):

  - ``journal.append``  — record one entry (the only mutating tool here)
  - ``journal.read``    — read the log (filter by kind / gene)
  - ``journal.summary`` — a "where are we" digest grouped by kind

These are OPERATIONAL results (the agent's working memory), not n=1 health findings, so — like the admin
``indaga.*`` tools — they return plain operational payloads and do NOT carry an ``evidence_envelope``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..operations.model import Context, Operation
from ..operations.registry import register
from ..runtime.journal import KINDS, Journal

_CAP = "journal"
_SKILL = "skills/journal/SKILL.md"


def _now_iso(context: Context) -> str:
    return (context.now or datetime.now(timezone.utc)).isoformat()


def _journal_append(params: dict, context: Context) -> dict:
    """Record one investigation entry. Returns the new id + running counts by kind."""
    text = (params.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text is required", "kinds": list(KINDS)}
    kind = (params.get("kind") or "note").strip().lower()
    refs = params.get("refs")
    j = Journal.open(context.subject_id)
    try:
        eid = j.append(
            kind, text, ts=_now_iso(context),
            gene=(params.get("gene") or None), rsid=(params.get("rsid") or None),
            tool=(params.get("tool") or None),
            refs_json=json.dumps(refs) if refs is not None else None)
        counts = j.counts_by_kind()
    finally:
        j.close()
    return {"ok": True, "entry_id": eid, "kind": kind if kind in KINDS else "note",
            "subject_id": context.subject_id, "counts_by_kind": counts,
            "note": "Recorded in the local investigation journal — operational memory, not a clinical fact."}


def _decode(entries: list[dict]) -> list[dict]:
    for e in entries:
        if e.get("refs_json"):
            try:
                e["refs"] = json.loads(e["refs_json"])
            except (ValueError, TypeError):
                pass
        e.pop("refs_json", None)
    return entries


def _journal_read(params: dict, context: Context) -> dict:
    """Read the journal (newest first), optionally filtered by ``kind`` and/or ``gene``."""
    j = Journal.open(context.subject_id)
    try:
        entries = _decode(j.entries(
            kind=(params.get("kind") or None), gene=(params.get("gene") or None),
            limit=max(1, min(int(params.get("limit") or 50), 500))))
        counts = j.counts_by_kind()
    finally:
        j.close()
    return {"subject_id": context.subject_id, "n": len(entries), "counts_by_kind": counts,
            "entries": entries,
            "note": "Investigation journal (newest first) — operational memory for this subject; n=1."}


def _journal_summary(params: dict, context: Context) -> dict:
    """A 'where are we' digest: counts + the most recent few of each kind that matters for resuming."""
    j = Journal.open(context.subject_id)
    try:
        counts = j.counts_by_kind()

        def recent(kind: str, n: int = 5) -> list[dict]:
            return [{k: e[k] for k in ("id", "ts", "text", "gene")}
                    for e in j.entries(kind=kind, limit=n)]

        out = {
            "subject_id": context.subject_id,
            "total": sum(counts.values()),
            "counts_by_kind": counts,
            "questions": recent("question"),
            "hypotheses": recent("hypothesis"),
            "ruled_out": recent("ruled_out"),
            "conclusions": recent("conclusion"),
            "next_steps": recent("next_step"),
            "note": "Investigation digest — resume here: what was asked, ruled out, concluded, and what's "
                    "next. Operational memory, not clinical facts; n=1.",
        }
    finally:
        j.close()
    return out


register(Operation("journal.append", _journal_append, capability=_CAP, skill=_SKILL,
    description="Record one entry in the subject's persistent investigation journal — a question, finding, "
                "hypothesis, ruled_out, conclusion, next_step, or note. Local, append-only working memory so "
                "a later session resumes instead of re-deriving.",
    input_schema={"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
        "gene": {"type": "string"}, "rsid": {"type": "string"}, "tool": {"type": "string"},
        "refs": {"type": "object"}}},
    discovery_role="entry_tool"))


register(Operation("journal.read", _journal_read, capability=_CAP, skill=_SKILL,
    description="Read the subject's investigation journal (newest first), optionally filtered by `kind` "
                "(question/finding/hypothesis/ruled_out/conclusion/next_step/note) and/or `gene`.",
    input_schema={"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(KINDS)}, "gene": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500}}},
    discovery_role="entry_tool"))


register(Operation("journal.summary", _journal_summary, capability=_CAP, skill=_SKILL,
    description="A 'where are we' digest of the investigation journal — counts by kind plus the most recent "
                "questions, hypotheses, ruled-out items, conclusions, and next steps. Start here to resume.",
    input_schema={"type": "object", "properties": {}},
    discovery_role="focused_tool"))
