"""P2 — operation observability: a span (timing + status) per tool dispatch (runtime/observability.py)."""

import pytest

from indaga.runtime import observability


class _Op:
    name = "genome.summary"
    capability = "genome"


class _Ctx:
    subject_id = None  # no on-disk store → ring + metrics only, no traces.jsonl


def test_span_records_ok_with_duration():
    with observability.operation_span(_Ctx(), _Op()):
        pass
    s = observability.recent_spans(1)[-1]
    assert s["name"] == "genome.summary"
    assert s["capability"] == "genome"
    assert s["status"] == "ok"
    assert s["error_type"] is None
    assert s["duration_ms"] >= 0
    assert s["trace_id"] and s["span_id"]


def test_span_records_error_and_reraises():
    with pytest.raises(ValueError):
        with observability.operation_span(_Ctx(), _Op()):
            raise ValueError("boom")
    s = observability.recent_spans(1)[-1]
    assert s["status"] == "error"
    assert s["error_type"] == "ValueError"


def test_metrics_summary_aggregates_calls_and_errors():
    for _ in range(3):
        with observability.operation_span(_Ctx(), _Op()):
            pass
    m = observability.metrics_summary()
    assert "genome.summary" in m
    entry = m["genome.summary"]
    assert entry["calls"] >= 3
    assert entry["errors"] >= 1  # the error span above is in the same ring
    assert entry["avg_ms"] >= 0
