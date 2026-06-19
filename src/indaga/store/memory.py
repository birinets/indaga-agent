"""InMemoryStore — the reference adapter for the Healthlake port.

Not for production. It exists so that:
  * the port has at least one working implementation (the package compiles + runs),
  * the conformance suite (conformance.py) has something to exercise,
  * the Engine / MCP server can be developed and unit-tested against real types
    before the LocalDuckDB adapter (WS-1B.1) lands.

It enforces the load-bearing invariant — every read is hard-scoped to one
subject — exactly as a real adapter must.

stdlib only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ._query import fact_passes, in_window, summarize_points
from .port import HealthlakeStore
from .types import (
    Caveat,
    CaveatCode,
    ContextPack,
    Correction,
    Fact,
    FactQuery,
    Provenance,
    Scope,
    Severity,
    SourceRef,
    TimeSeries,
    TimeSeriesPoint,
)

_SCHEMA_VERSION = "healthlake-port/0.1"


class InMemoryStore(HealthlakeStore):
    """A dict-backed store keyed by subject_id. Pure Python, no persistence."""

    def __init__(self, *, generated_at: datetime | None = None) -> None:
        # generated_at is injectable so tests/conformance stay deterministic
        # (the port forbids hidden clock reads in deterministic contexts).
        self._facts: dict[str, list[Fact]] = {}
        self._series: dict[tuple[str, str], list[TimeSeriesPoint]] = {}
        self._series_meta: dict[tuple[str, str], TimeSeries] = {}
        self._provenance: dict[str, Provenance] = {}
        self._corrections: dict[str, list[Correction]] = {}
        self._sources: dict[str, dict[str, SourceRef]] = {}
        self._profile: dict[str, dict] = {}
        self._now = generated_at or datetime(2026, 1, 1, tzinfo=timezone.utc)

    # -- helpers --------------------------------------------------------------
    def set_profile(self, subject_id: str, profile: dict) -> None:
        self._profile[subject_id] = dict(profile)

    # -- HealthlakeWriter -----------------------------------------------------
    def upsert_facts(self, scope: Scope, facts: list[Fact]) -> int:
        bucket = self._facts.setdefault(scope.subject_id, [])
        by_id = {f.fact_id: i for i, f in enumerate(bucket)}
        written = 0
        for f in facts:
            if f.subject_id != scope.subject_id:
                raise ValueError(
                    f"refusing to write fact for {f.subject_id!r} under scope "
                    f"{scope.subject_id!r} (subject isolation)"
                )
            if f.fact_id in by_id:
                bucket[by_id[f.fact_id]] = f
            else:
                by_id[f.fact_id] = len(bucket)
                bucket.append(f)
            written += 1
        return written

    def append_timeseries(self, scope: Scope, series: TimeSeries) -> int:
        if series.subject_id != scope.subject_id:
            raise ValueError("timeseries subject mismatch (subject isolation)")
        key = (scope.subject_id, series.metric)
        self._series.setdefault(key, []).extend(series.points)
        self._series_meta[key] = series
        return len(series.points)

    def attach_provenance(self, scope: Scope, provenance: Provenance) -> None:
        owned = {f.fact_id for f in self._facts.get(scope.subject_id, [])}
        if provenance.target_id not in owned:
            raise ValueError(
                f"refusing provenance for unowned target {provenance.target_id!r} "
                f"under scope {scope.subject_id!r} (subject isolation)"
            )
        self._provenance[provenance.target_id] = provenance

    def record_correction(self, scope: Scope, correction: Correction) -> None:
        self._corrections.setdefault(scope.subject_id, []).append(correction)

    def register_source(self, scope: Scope, source: SourceRef) -> None:
        self._sources.setdefault(scope.subject_id, {})[source.source_file_id] = source

    # -- HealthlakeReader -----------------------------------------------------
    def get_facts(self, scope: Scope, query: FactQuery | None = None) -> list[Fact]:
        q = query or FactQuery()
        out = [f for f in self._facts.get(scope.subject_id, []) if fact_passes(f, scope, q)]
        if q.limit is not None:
            out = out[: q.limit]
        return out

    def get_timeseries(self, scope: Scope, metric, since=None, until=None, resolution=None) -> TimeSeries:
        key = (scope.subject_id, metric)
        pts = sorted((p for p in self._series.get(key, []) if in_window(p.t, since, until)), key=lambda p: p.t)
        meta = self._series_meta.get(key)
        caveats: tuple[Caveat, ...] = ()
        if len(pts) <= 1:
            caveats = (Caveat(CaveatCode.SINGLE_DATAPOINT, "Not enough points for a trend.", Severity.WARN),)
        return TimeSeries(
            scope.subject_id, metric,
            meta.unit if meta else None,
            tuple(pts), summarize_points(pts), caveats,
            meta.source if meta else None,
        )

    def get_provenance(self, scope: Scope, target_id: str) -> Provenance | None:
        # Resolve only if the target belongs to this subject (isolation).
        owned = {f.fact_id for f in self._facts.get(scope.subject_id, [])}
        if target_id not in owned:
            return None
        return self._provenance.get(target_id)

    def get_corrections(self, scope: Scope) -> list[Correction]:
        return list(self._corrections.get(scope.subject_id, []))

    def list_sources(self, scope: Scope) -> list[SourceRef]:
        return list(self._sources.get(scope.subject_id, {}).values())

    def get_context_pack(self, scope: Scope) -> ContextPack:
        facts = self.get_facts(scope)
        flagged = [f for f in facts if f.interpretation not in (None, "normal")]
        manifest: dict[str, int] = {}
        for f in facts:
            manifest[f.evidence_grade.value] = manifest.get(f.evidence_grade.value, 0) + 1
        pack_caveats: list[Caveat] = []
        if not facts:
            pack_caveats.append(
                Caveat(CaveatCode.OUT_OF_PANEL, "No facts in scope; absence is not a negative finding.", Severity.WARN)
            )
        guidance = (
            "Use only the facts below; cite each by fact_id. Honour every caveat. "
            "Grade-D / INSUFFICIENT facts may not ground a medical-impact claim. "
            "If a question needs a fact not present, say so — do not infer it."
        )
        return ContextPack(
            schema_version=_SCHEMA_VERSION,
            generated_at=self._now,
            subject_id=scope.subject_id,
            surface=scope.surface,
            profile=self._profile.get(scope.subject_id, {}),
            facts=tuple(facts),
            timeseries_summaries=tuple(
                self._series_meta[k] for k in self._series_meta if k[0] == scope.subject_id
            ),
            flagged=tuple(flagged),
            corrections=tuple(self.get_corrections(scope)),
            caveats=tuple(pack_caveats),
            query_guidance=guidance,
            evidence_manifest=manifest,
        )

    def health_check(self) -> bool:
        return True
