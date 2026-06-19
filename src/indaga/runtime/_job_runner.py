"""Detached-job wrapper that records STRUCTURED completion in the job's meta JSON.

The old ``job_status`` inferred success by string-matching the log tail for ``'"status": "imputed"'``
/ ``"checks passed"`` — a self-confirming signal (a coincidental substring, or a marker printed
before a later crash, both read as success; and the background-job poller would even report the
genome-parity eval "finished" by grepping the very string it prints). This wrapper runs the real
CLI command and, when the child EXITS, writes ``status`` (finished/failed) + ``returncode`` +
``finished_at`` to the meta file — an authoritative, exit-code-based signal, not a log grep.

Spawned by ``runtime.jobs.start_cli_job`` as::

    python -m indaga.runtime._job_runner <meta.json> <cmd> [args...]

stdlib only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _record(meta_path: Path, **updates) -> None:
    try:
        rec = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    rec.update(updates)
    try:
        meta_path.write_text(json.dumps(rec), encoding="utf-8")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    meta_path = Path(argv[0])
    cmd = argv[1:]
    rc = 1
    try:
        rc = subprocess.call(cmd)  # stdout/stderr inherit the runner's (→ the job log)
    except Exception as exc:  # noqa: BLE001 — record any spawn failure as a failed job
        _record(meta_path, status="failed", returncode=rc, error=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat())
        return rc
    _record(meta_path, status="finished" if rc == 0 else "failed", returncode=rc,
            finished_at=datetime.now(timezone.utc).isoformat())
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
