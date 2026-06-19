"""Investigation journal — append-only per-subject working memory (local, deterministic ts)."""

from datetime import datetime

import pytest

from indaga.capabilities.journal import _journal_append, _journal_read, _journal_summary
from indaga.operations.model import Context
from indaga.store import Surface
from indaga.store.memory import InMemoryStore


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INDAGA_HOME", str(tmp_path))
    return tmp_path


def _ctx(subject="demo", *, ts="2026-06-16T10:00:00+00:00"):
    return Context(subject_id=subject, store=InMemoryStore(), surface=Surface.APP,
                   now=datetime.fromisoformat(ts))


def test_append_then_read_roundtrip(home):
    a = _journal_append({"kind": "ruled_out", "text": "AGS9/RNU7-1 ruled out — phasing is CIS",
                         "gene": "RNU7-1", "refs": {"method": "read-based phasing"}}, _ctx())
    assert a["ok"] and a["entry_id"] == 1 and a["kind"] == "ruled_out"
    r = _journal_read({}, _ctx())
    assert r["n"] == 1
    e = r["entries"][0]
    assert e["kind"] == "ruled_out" and e["gene"] == "RNU7-1"
    assert e["refs"]["method"] == "read-based phasing" and "refs_json" not in e
    assert e["ts"] == "2026-06-16T10:00:00+00:00"  # injected ts is deterministic


def test_unknown_kind_coerced_to_note(home):
    _journal_append({"kind": "speculation", "text": "maybe check ferritin"}, _ctx())
    assert _journal_read({"kind": "note"}, _ctx())["n"] == 1


def test_text_required(home):
    out = _journal_append({"kind": "note", "text": "   "}, _ctx())
    assert out["ok"] is False and "text" in out["error"]


def test_filters_by_kind_and_gene(home):
    c = _ctx()
    _journal_append({"kind": "question", "text": "LDL driver?", "gene": "LDLR"}, c)
    _journal_append({"kind": "conclusion", "text": "polygenic, not FH", "gene": "LDLR"}, c)
    _journal_append({"kind": "question", "text": "alcohol tolerance?", "gene": "ADH1B"}, c)
    assert _journal_read({"kind": "question"}, c)["n"] == 2
    assert _journal_read({"gene": "ldlr"}, c)["n"] == 2  # case-insensitive
    assert _journal_read({"kind": "question", "gene": "ADH1B"}, c)["n"] == 1


def test_summary_groups_by_kind(home):
    c = _ctx()
    _journal_append({"kind": "question", "text": "q1"}, c)
    _journal_append({"kind": "ruled_out", "text": "r1"}, c)
    _journal_append({"kind": "next_step", "text": "measure ferritin"}, c)
    s = _journal_summary({}, c)
    assert s["total"] == 3 and s["counts_by_kind"]["ruled_out"] == 1
    assert s["next_steps"][0]["text"] == "measure ferritin"
    assert len(s["questions"]) == 1


def test_persists_across_reopen_and_is_subject_scoped(home):
    _journal_append({"kind": "note", "text": "demo note"}, _ctx("demo"))
    _journal_append({"kind": "note", "text": "demo2 note"}, _ctx("demo2"))
    # a fresh handler call re-opens the on-disk store → persistence
    assert _journal_read({}, _ctx("demo"))["n"] == 1
    assert _journal_read({}, _ctx("demo2"))["n"] == 1  # separate subject file, not mixed
    assert _journal_read({}, _ctx("demo"))["entries"][0]["text"] == "demo note"
