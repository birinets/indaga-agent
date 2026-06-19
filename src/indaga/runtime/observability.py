"""Operation-level observability — a structured span (timing + status) over every tool dispatch.

The architecture review graded observability the WEAKEST axis (F for both repos): no traces, no metrics.
This wraps `operations.call_operation` in a span recording, with OpenTelemetry semantic-convention field
names, ``{trace_id, span_id, name, capability, subject, duration_ms, status, error_type}`` — so per-tool
latency and error rates are observable. Three best-effort sinks (none ever breaks a tool call):

  * an in-process ring buffer (`recent_spans` / `metrics_summary`) for live introspection,
  * a per-subject append-only ``~/.indaga/<subject>/traces.jsonl`` (local; written only when the store
    exists, so in-memory test subjects don't create files),
  * the OpenTelemetry SDK when installed AND ``INDAGA_OTEL=1`` (the ``otel`` optional extra) — a real
    exporter then forwards spans; otherwise the structured JSONL IS the trace.

Timing uses a monotonic clock and lives at the DISPATCH layer — never in the deterministic spine/store
(the span's duration is not part of any tool result, so eval reproducibility is unaffected).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from . import paths

_RING: deque[dict] = deque(maxlen=512)


def _new_id(n: int = 16) -> str:
    return uuid.uuid4().hex[:n]


@contextmanager
def operation_span(context: Any, op: Any):
    """Time a tool dispatch and record a span on exit (ok | error). Re-raises any handler exception
    after recording it — observability is transparent to control flow."""
    subject = getattr(context, "subject_id", None)
    trace_id, span_id = _new_id(32), _new_id(16)
    start = time.monotonic()
    status, error_type = "ok", None
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — record then re-raise; we don't swallow
        status, error_type = "error", type(exc).__name__
        raise
    finally:
        span = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id, "span_id": span_id,
            "name": getattr(op, "name", None), "capability": getattr(op, "capability", None),
            "subject": subject,
            "duration_ms": round((time.monotonic() - start) * 1000, 2),
            "status": status, "error_type": error_type,
        }
        _emit(span)


def _emit(span: dict) -> None:
    _RING.append(span)
    try:
        subject = span.get("subject")
        if subject and paths.subject_dir(subject).exists():
            p = paths.subject_dir(subject) / "traces.jsonl"
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(span) + "\n")
            paths.secure_file(p)
    except Exception:  # noqa: BLE001 — a trace must never break a tool call
        pass
    _emit_otel(span)


def _emit_otel(span: dict) -> None:
    """Forward to the OpenTelemetry SDK when present + enabled. No-op otherwise (the JSONL is the trace)."""
    if os.environ.get("INDAGA_OTEL") != "1":
        return
    try:
        from opentelemetry import trace  # optional dep (the `otel` extra)
        s = trace.get_tracer("indaga").start_span(span["name"] or "operation")
        s.set_attribute("indaga.capability", span["capability"] or "")
        s.set_attribute("indaga.status", span["status"])
        s.set_attribute("indaga.duration_ms", span["duration_ms"])
        if span["error_type"]:
            s.set_attribute("indaga.error_type", span["error_type"])
        s.end()
    except Exception:  # noqa: BLE001
        pass


def recent_spans(limit: int = 50) -> list[dict]:
    """The most recent spans from the in-process ring buffer (newest last)."""
    return list(_RING)[-limit:]


def metrics_summary() -> dict[str, dict]:
    """Per-tool aggregates over the ring buffer: call count, error count, avg + max duration (ms)."""
    agg: dict[str, dict] = {}
    for s in _RING:
        a = agg.setdefault(s["name"], {"calls": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0})
        a["calls"] += 1
        a["errors"] += 1 if s["status"] == "error" else 0
        a["total_ms"] += s["duration_ms"]
        a["max_ms"] = max(a["max_ms"], s["duration_ms"])
    return {
        name: {"calls": a["calls"], "errors": a["errors"],
               "avg_ms": round(a["total_ms"] / a["calls"], 2) if a["calls"] else 0.0,
               "max_ms": a["max_ms"]}
        for name, a in agg.items()
    }
