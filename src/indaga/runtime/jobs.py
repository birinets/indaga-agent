"""Durable background-job runner for long operations (imputation, annotate, PGx, ancestry).

A genome imputation runs for many minutes — too long for a synchronous MCP call. An agent instead
starts it as a background job (returns a job_id) and polls ``indaga.check_background_job``. Jobs are
detached subprocesses; the per-job meta JSON under ``~/.indaga/<subject>/jobs/`` is the DURABLE journal
— it survives a server restart, records the lifecycle (``started_at`` → ``finished``/``failed``/
``exited`` + ``finished_at`` + ``returncode``, written by ``_job_runner`` on the child's exit), and
carries the exact command so a job is RESUMABLE: the wrapped operations (impute/annotate/pgx/ancestry)
are idempotent + rebuild-safe, so resume == re-launch via ``retry_job`` (or just re-invoking the tool).
stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import paths


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _src_root() -> str:
    # this file = <src>/indaga/runtime/jobs.py → parents[2] = <src>
    return str(Path(__file__).resolve().parents[2])


def _jobs_dir(subject_id: str) -> Path:
    d = paths.subject_dir(subject_id) / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def start_cli_job(subject_id: str, cli_args: list[str], label: str) -> dict:
    """Spawn `python -m indaga.interfaces.cli <cli_args>` detached, wrapped by _job_runner so the
    job records a STRUCTURED terminal status (exit-code based) on completion. Returns {job_id, ...}."""
    jid = uuid.uuid4().hex[:8]
    jdir = _jobs_dir(subject_id)
    log = jdir / f"{jid}.log"
    meta = jdir / f"{jid}.json"
    env = {**os.environ, "PYTHONPATH": _src_root()}
    fh = open(log, "wb")
    cmd = [sys.executable, "-m", "indaga.interfaces.cli", *cli_args]
    runner = [sys.executable, "-m", "indaga.runtime._job_runner", str(meta), *cmd]
    # Write the meta BEFORE spawning so the runner's terminal write (status=finished/failed) is never
    # clobbered by a late parent write; the runner read-merges, so adding the pid after is safe.
    meta.write_text(json.dumps({"job_id": jid, "pid": None, "label": label, "cmd": cmd,
                                "log": str(log), "status": "running", "started_at": _now_iso()}),
                    encoding="utf-8")
    p = subprocess.Popen(runner, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         start_new_session=True)  # detach from the MCP server's session
    try:  # merge the pid in without overwriting a possibly-already-written terminal status
        rec = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {"job_id": jid, "label": label, "cmd": cmd, "log": str(log)}
    rec["pid"] = p.pid
    rec.setdefault("status", "running")
    meta.write_text(json.dumps(rec), encoding="utf-8")
    return {"job_id": jid, "status": "running", "label": label}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _state(rec: dict) -> tuple[str, bool]:
    """Resolve (status, running) from a job journal record. Authoritative status comes from the meta
    (written by _job_runner on the child's EXIT: finished/failed + returncode) — never from grepping
    the log. A process that is gone with no terminal status recorded crashed/was killed → 'exited'."""
    running = _alive(rec["pid"]) if rec.get("pid") else False
    status = rec.get("status", "running")
    if status in ("finished", "failed"):
        running = False  # terminal: ignore a lingering zombie pid (detached child not yet reaped)
    elif status == "running" and not running:
        status = "exited"
    return status, running


def _duration_s(rec: dict) -> float | None:
    """Elapsed seconds: started_at → finished_at (or now, while running). None if not started."""
    started = rec.get("started_at")
    if not started:
        return None
    try:
        start = datetime.fromisoformat(started)
        end = datetime.fromisoformat(rec["finished_at"]) if rec.get("finished_at") else datetime.now(timezone.utc)
        return round((end - start).total_seconds(), 1)
    except (ValueError, TypeError):
        return None


def job_status(subject_id: str, job_id: str, *, tail: int = 12) -> dict:
    meta = _jobs_dir(subject_id) / f"{job_id}.json"
    if not meta.exists():
        return {"job_id": job_id, "status": "unknown"}
    rec = json.loads(meta.read_text(encoding="utf-8"))
    log_tail = ""
    try:
        lines = Path(rec["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = "\n".join(lines[-tail:])
    except OSError:
        pass
    status, running = _state(rec)
    return {"job_id": job_id, "label": rec.get("label"), "status": status, "running": running,
            "returncode": rec.get("returncode"), "started_at": rec.get("started_at"),
            "finished_at": rec.get("finished_at"), "duration_s": _duration_s(rec), "log_tail": log_tail}


def list_jobs(subject_id: str) -> list[dict]:
    out = []
    for meta in sorted(_jobs_dir(subject_id).glob("*.json")):
        try:
            rec = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status, running = _state(rec)
        out.append({"job_id": rec.get("job_id"), "label": rec.get("label"), "status": status,
                    "running": running, "started_at": rec.get("started_at"),
                    "duration_s": _duration_s(rec)})
    return out


def retry_job(subject_id: str, job_id: str) -> dict:
    """Re-launch a job from its durable journal (resume == re-run, since the wrapped operations are
    idempotent + rebuild-safe). Recovers the original CLI args from the recorded command and starts a
    fresh job; returns the new job descriptor."""
    meta = _jobs_dir(subject_id) / f"{job_id}.json"
    if not meta.exists():
        return {"job_id": job_id, "status": "unknown"}
    rec = json.loads(meta.read_text(encoding="utf-8"))
    cmd = rec.get("cmd") or []
    marker = "indaga.interfaces.cli"
    cli_args = cmd[cmd.index(marker) + 1:] if marker in cmd else []
    if not cli_args:
        return {"job_id": job_id, "status": "cannot_retry", "reason": "no recorded CLI args to re-run"}
    label = rec.get("label") or "job"
    label = label if "(retry)" in label else f"{label} (retry)"
    return start_cli_job(subject_id, cli_args, label)
