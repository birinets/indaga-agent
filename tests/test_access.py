"""P2 — capability access control: per-session subject grant + per-read audit log (runtime/audit.py)."""

import pytest

from indaga.runtime import audit, paths


class _Op:
    def __init__(self, name="variant.resolve", egress=("gnomad",), mutating=False):
        self.name = name
        self.capability = "genome"
        self.privacy_scope = "genomic"
        self.data_access = ("genome",)
        self.external_io = egress
        self.mutating = mutating


class _Ctx:
    def __init__(self, subject):
        self.subject_id = subject
        self.surface = None
        self.now = None


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INDAGA_HOME", str(tmp_path))
    return tmp_path


def test_grant_roundtrip(home):
    paths.ensure_subject_dirs("alice")
    assert audit.is_granted("alice") is False
    audit.grant_local("alice", reason="test")
    assert audit.is_granted("alice") is True
    audit.revoke("alice")
    assert audit.is_granted("alice") is False


def test_local_owner_auth_grants_and_authorizes(home):
    paths.ensure_subject_dirs("alice")
    assert audit.LocalOwnerAuth().authorize("alice", surface="app") is True
    assert audit.is_granted("alice") is True


def test_grant_noop_without_store(home):
    # a subject with no on-disk store cannot be granted (nothing to authorize against)
    audit.grant_local("ghost")
    assert audit.is_granted("ghost") is False


def test_record_access_writes_audit_with_egress(home):
    paths.ensure_subject_dirs("alice")
    audit.record_access(_Ctx("alice"), _Op())
    recs = audit.read_audit("alice")
    assert len(recs) == 1
    r = recs[0]
    assert r["tool"] == "variant.resolve"
    assert r["privacy_scope"] == "genomic"
    assert r["data_access"] == ["genome"]
    assert r["external_io"] == ["gnomad"]  # the egress disclosure is captured in the trail
    assert r["mutating"] is False
    assert "ts" in r


def test_record_access_noop_for_in_memory_subject(home):
    # no on-disk store (e.g. an in-memory unit test) → not audited, no dir created just to log
    audit.record_access(_Ctx("demo"), _Op())
    assert audit.read_audit("demo") == []


def test_audit_is_append_only(home):
    paths.ensure_subject_dirs("alice")
    for _ in range(3):
        audit.record_access(_Ctx("alice"), _Op("genome.summary", egress=()))
    assert len(audit.read_audit("alice")) == 3
