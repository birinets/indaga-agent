"""Apple Health / wearable connectors — parsed series → port timeseries + facts.

Consumes the parsed outputs of ``parse_apple_health.py``:
  * ``hr_series.json``  → {unit, n, date_range, series:[[iso_ts, bpm, source], ...]}
                          → a `TimeSeries` of heart-rate points.
  * ``glucose.json``    → session-level CGM summary (no inline per-reading points;
                          those arrive via the export path) → a summary `Fact` +
                          the CGM source registration.

Adapter-agnostic: writes through the port.
"""

from __future__ import annotations

import json
from datetime import date

from ..store import (
    Caveat,
    CaveatCode,
    EvidenceGrade,
    Fact,
    HealthlakeStore,
    Scope,
    Severity,
    SourceRef,
    TimeSeries,
    TimeSeriesPoint,
)
from ..store.codec import parse_dt


def ingest_hr_series(
    store: HealthlakeStore,
    subject_id: str,
    path: str,
    *,
    metric: str = "heart_rate_bpm",
    limit: int | None = None,
    since: date | None = None,
) -> int:
    """Ingest a heart-rate point series. ``limit`` keeps the most recent N points
    (the full series can be ~500k); ``since`` filters by date. Returns points written."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    unit = d.get("unit", "bpm")
    src: str | None = None
    pts: list[TimeSeriesPoint] = []
    for row in d.get("series", []):
        t = parse_dt(row[0])
        if t is None:
            continue
        if since is not None and t.date() < since:
            continue
        if src is None and len(row) > 2:
            src = row[2]
        pts.append(TimeSeriesPoint(t, float(row[1])))
    pts.sort(key=lambda p: p.t)
    if limit is not None and len(pts) > limit:
        pts = pts[-limit:]

    scope = Scope(subject_id)
    store.append_timeseries(
        scope, TimeSeries(subject_id, metric, unit, tuple(pts), {}, (), src or "apple_health")
    )
    rng = d.get("date_range", {})
    store.register_source(scope, SourceRef(
        source_file_id=f"apple_health:{metric}",
        label=f"Apple Health {metric} ({rng.get('first', '?')}..{rng.get('last', '?')})",
        kind="apple_health",
        document_count=int(d.get("n", len(pts))),
    ))
    return len(pts)


def ingest_glucose_summary(store: HealthlakeStore, subject_id: str, path: str) -> int:
    """Register the CGM source + write a session-level summary fact.

    The per-reading glucose series is not in ``glucose.json`` (it carries session
    metadata only); point ingestion comes from the Apple Health export path. This
    keeps the CGM source visible in the Healthlake inventory meanwhile. Returns 1.
    """
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    scope = Scope(subject_id)
    rng = d.get("date_range", {})
    store.register_source(scope, SourceRef(
        source_file_id="cgm:dexcom",
        label=f"{d.get('source', 'CGM')} "
              f"({d.get('n_sessions', '?')} sessions, {d.get('n_readings', '?')} readings)",
        kind="cgm",
        document_count=int(d.get("n_readings", 0)),
    ))
    fid = f"cgm_summary_{subject_id}"
    store.upsert_facts(scope, [Fact(
        fact_id=fid, subject_id=subject_id, domain="wearable_summary",
        name="cgm_readings_total", display="CGM readings (total)",
        value_number=float(d.get("n_readings", 0)), unit=d.get("unit"),
        evidence_grade=EvidenceGrade.B,
        caveats=(Caveat(
            CaveatCode.SINGLE_DATAPOINT,
            "Session-level CGM summary; the per-reading series is ingested via the export path.",
            Severity.INFO,
        ),),
        attributes={
            "source": d.get("source"), "n_sessions": d.get("n_sessions"),
            "first": rng.get("first"), "last": rng.get("last"),
        },
    )])
    return 1
