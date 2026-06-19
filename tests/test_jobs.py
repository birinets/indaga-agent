"""P2 — durable resumable job state machine (runtime/jobs.py): lifecycle, duration, retry."""

import json
import types
from datetime import datetime, timedelta, timezone

import pytest

from indaga.runtime import jobs


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INDAGA_HOME", str(tmp_path))
    # don't actually spawn a subprocess; the lifecycle logic is what's under test
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: types.SimpleNamespace(pid=424242))
    return tmp_path


def test_start_job_records_lifecycle(home):
    rep = jobs.start_cli_job("alice", ["annotate", "--subject", "alice"], "annotate")
    st = jobs.job_status("alice", rep["job_id"])
    assert st["started_at"]
    assert st["duration_s"] is not None and st["duration_s"] >= 0
    assert st["status"] in ("running", "exited")  # fake pid not alive → exited
    meta = json.loads((jobs._jobs_dir("alice") / f"{rep['job_id']}.json").read_text())
    assert meta["cmd"][-3:] == ["annotate", "--subject", "alice"]


def test_job_status_reports_duration(home):
    jd = jobs._jobs_dir("alice")
    start = datetime(2026, 6, 16, 10, 0, 0, tzinfo=timezone.utc)
    fin = start + timedelta(seconds=42)
    (jd / "j1.json").write_text(json.dumps({
        "job_id": "j1", "pid": 1, "label": "impute", "cmd": ["x"], "log": str(jd / "j1.log"),
        "status": "finished", "returncode": 0,
        "started_at": start.isoformat(), "finished_at": fin.isoformat()}))
    st = jobs.job_status("alice", "j1")
    assert st["status"] == "finished"
    assert st["running"] is False
    assert abs(st["duration_s"] - 42.0) < 0.2
    assert st["returncode"] == 0


def test_running_but_dead_pid_is_exited(home):
    jd = jobs._jobs_dir("alice")
    (jd / "j2.json").write_text(json.dumps({
        "job_id": "j2", "pid": 424242, "label": "x", "cmd": ["x"], "log": str(jd / "j2.log"),
        "status": "running", "started_at": jobs._now_iso()}))
    assert jobs.job_status("alice", "j2")["status"] == "exited"


def test_retry_respawns_same_command(home):
    rep = jobs.start_cli_job("alice", ["impute", "--subject", "alice"], "impute")
    new = jobs.retry_job("alice", rep["job_id"])
    assert new["job_id"] != rep["job_id"]
    old_meta = json.loads((jobs._jobs_dir("alice") / f"{rep['job_id']}.json").read_text())
    new_meta = json.loads((jobs._jobs_dir("alice") / f"{new['job_id']}.json").read_text())
    assert new_meta["cmd"] == old_meta["cmd"]
    assert "(retry)" in new_meta["label"]


def test_retry_unknown_job(home):
    assert jobs.retry_job("alice", "nope")["status"] == "unknown"


def test_list_jobs_enriched(home):
    jobs.start_cli_job("alice", ["annotate"], "a")
    listing = jobs.list_jobs("alice")
    assert listing
    row = listing[0]
    assert {"status", "started_at", "duration_s", "running"} <= set(row)
