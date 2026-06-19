"""Shared, pure query predicates used by every adapter.

Keeping the filtering logic in one place means InMemoryStore and LocalDuckDBStore
(and future adapters) apply *identical* semantics — the conformance suite then
proves the equivalence rather than each adapter re-implementing it and drifting.

stdlib only.
"""

from __future__ import annotations

from .types import Fact, FactQuery, Scope, TimeSeriesPoint


def in_window(when, since, until) -> bool:
    """Inclusive time-window test. ``None`` bounds are open. Callers are
    responsible for passing comparable types (date-vs-date or datetime-vs-datetime)."""
    if when is None:
        return True
    if since is not None and when < since:
        return False
    if until is not None and when > until:
        return False
    return True


def fact_passes(f: Fact, scope: Scope, q: FactQuery) -> bool:
    """The single source of truth for whether a fact is visible under a scope+query."""
    # scope-level filters (access boundary + topical narrowing)
    if scope.domains and f.domain not in scope.domains:
        return False
    if not scope.include_genomics and f.domain == "genomic":
        return False
    if not in_window(f.observed_at, scope.since, scope.until):
        return False
    # query-level filters
    if q.domains and f.domain not in q.domains:
        return False
    if q.names and f.name not in q.names:
        return False
    if q.codes and (f.code or "") not in q.codes:
        return False
    if q.status and f.status not in q.status:
        return False
    if q.flagged_only and (f.interpretation in (None, "normal")):
        return False
    if not f.evidence_grade.meets(q.min_evidence):
        return False
    if (f.confidence or 0.0) < q.min_confidence:
        return False
    return True


def summarize_points(points: list[TimeSeriesPoint]) -> dict[str, float]:
    """Summary stats for a time series. Same output for every adapter."""
    if not points:
        return {}
    vals = [p.value for p in points]
    return {
        "n": float(len(vals)),
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
    }
