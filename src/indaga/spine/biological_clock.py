"""Biological Clock service (WS-1B.4) — the hero deterministic metric.

Reads the heart-rate series from the Healthlake (via the port), fits the validated
24-hour cosinor, and writes a ``biological_midnight`` derived `Fact` back — graded
and caveat-wrapped according to a state machine:

    EMPTY        no heart-rate data                  → INSUFFICIENT, BLOCK
    CALIBRATING  < 14 valid nights                   → D,  BLOCK (no nadir shown)
    LOW_QUALITY  ≥14 nights but weak cosinor fit     → C,  WARN  (nadir provisional)
    STALE        ≥14 nights, good fit, data old       → C,  WARN
    REAL         ≥14 nights, good fit, fresh          → B          (Biological Midnight)

The **14-valid-nights** rule (build plan / `_DECISIONS.md`) is enforced here: a
Biological Midnight is only ever presented as "real" past that threshold; before
it the fact carries a BLOCK ``CALIBRATING`` caveat so no surface can claim it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..store import (
    Caveat,
    CaveatCode,
    EvidenceGrade,
    Fact,
    HealthlakeStore,
    Provenance,
    Scope,
    Severity,
    TimeSeriesPoint,
)
from .base import SpineResult, write_back
from .cosinor import cosinor_fit, hh_mm

HR_METRIC = "heart_rate_bpm"
MIN_NIGHTS = 14
MIN_R2 = 0.40
STALE_DAYS = 7
NIGHT_HOURS = range(0, 6)
MIN_NIGHT_SAMPLES = 20


class ClockState(str, Enum):
    EMPTY = "empty"
    CALIBRATING = "calibrating"
    LOW_QUALITY = "low_quality"
    STALE = "stale"
    REAL = "real"


@dataclass(frozen=True, slots=True)
class ClockResult:
    state: ClockState
    valid_nights: int
    n_samples: int
    nadir_h: float | None = None
    r2: float | None = None
    amplitude_bpm: float | None = None
    mesor_bpm: float | None = None
    last_date: date | None = None


def count_valid_nights(points) -> int:
    by_night: dict[date, int] = {}
    for p in points:
        if p.t.hour in NIGHT_HOURS:
            by_night[p.t.date()] = by_night.get(p.t.date(), 0) + 1
    return sum(1 for c in by_night.values() if c >= MIN_NIGHT_SAMPLES)


def compute_clock(points, as_of: date | None = None) -> ClockResult:
    """Pure state-machine + cosinor over a list of `TimeSeriesPoint`."""
    if not points:
        return ClockResult(ClockState.EMPTY, 0, 0)
    nights = count_valid_nights(points)
    last_date = max(p.t.date() for p in points)
    as_of = as_of or last_date
    if nights < MIN_NIGHTS:
        return ClockResult(ClockState.CALIBRATING, nights, len(points), last_date=last_date)

    hours = [p.t.hour + p.t.minute / 60 + p.t.second / 3600 for p in points]
    values = [p.value for p in points]
    fit = cosinor_fit(hours, values, harmonics=(1, 2))
    if fit["r2"] < MIN_R2:
        state = ClockState.LOW_QUALITY
    elif (as_of - last_date).days > STALE_DAYS:
        state = ClockState.STALE
    else:
        state = ClockState.REAL
    return ClockResult(
        state, nights, len(points),
        nadir_h=fit["nadir_curve_h"], r2=fit["r2"],
        amplitude_bpm=fit["amplitude_bpm"], mesor_bpm=fit["mesor_bpm"], last_date=last_date,
    )


def _to_fact(subject_id: str, r: ClockResult) -> tuple[Fact, Provenance | None]:
    fid = f"derived_biological_midnight_{subject_id}"
    base = dict(
        fact_id=fid, subject_id=subject_id, domain="circadian",
        name="biological_midnight", display="Biological Midnight (HR nadir)",
        code_system="indaga", code="biological_midnight",
        provenance_id=f"prov_{fid}",
        attributes={
            "state": r.state.value, "valid_nights": r.valid_nights,
            "n_samples": r.n_samples, "r2": r.r2, "amplitude_bpm": r.amplitude_bpm,
            "mesor_bpm": r.mesor_bpm, "last_date": r.last_date.isoformat() if r.last_date else None,
            "method": "24-h cosinor on heart rate; nadir = trough of fitted curve",
        },
    )
    if r.state in (ClockState.EMPTY, ClockState.CALIBRATING):
        grade = EvidenceGrade.INSUFFICIENT if r.state is ClockState.EMPTY else EvidenceGrade.D
        text = ("No heart-rate data yet." if r.state is ClockState.EMPTY
                else f"{r.valid_nights}/{MIN_NIGHTS} valid nights — Biological Midnight not shown yet.")
        fact = Fact(**base, value_text=None, status="calibrating",
                    evidence_grade=grade,
                    caveats=(Caveat(CaveatCode.CALIBRATING, text, Severity.BLOCK),))
        return fact, None

    caveats: list[Caveat] = []
    if r.state is ClockState.LOW_QUALITY:
        grade = EvidenceGrade.C
        caveats.append(Caveat(CaveatCode.LOW_CONFIDENCE,
                              f"Cosinor fit is weak (R²={r.r2:.2f}); nadir is provisional.", Severity.WARN))
    elif r.state is ClockState.STALE:
        grade = EvidenceGrade.C
        caveats.append(Caveat(CaveatCode.STALE,
                              "Heart-rate data is older than 7 days; nadir may have drifted.", Severity.WARN))
    else:  # REAL
        grade = EvidenceGrade.B

    fact = Fact(
        **base, value_number=r.nadir_h, value_text=hh_mm(r.nadir_h),
        unit="clock_h", status="validated", evidence_grade=grade, caveats=tuple(caveats),
    )
    prov = Provenance(
        f"prov_{fid}", fid, "derived", None, f"apple_health:{HR_METRIC}",
        "pipeline/healthlake/spine/biological_clock.py",
        f"24h-cosinor r2={r.r2:.3f} n={r.n_samples} nights={r.valid_nights}",
        "spine:biological_clock", r.r2, "computed",
    )
    return fact, prov


class BiologicalClock:
    name = "biological_clock"

    def run(self, store: HealthlakeStore, scope: Scope, *, as_of: date | None = None) -> SpineResult:
        ts = store.get_timeseries(scope, HR_METRIC)
        result = compute_clock(list(ts.points), as_of=as_of)
        fact, prov = _to_fact(scope.subject_id, result)
        spine_result = SpineResult(
            service=self.name, state=result.state.value,
            facts=(fact,), provenance=(prov,) if prov else (),
            detail={"valid_nights": result.valid_nights, "nadir_h": result.nadir_h, "r2": result.r2},
        )
        write_back(store, scope, spine_result)
        return spine_result


# --------------------------------------------------------------------------- #
# Self-test: deterministic state-machine checks + a real-data run.
# --------------------------------------------------------------------------- #

def _synthetic(n_nights: int) -> list[TimeSeriesPoint]:
    """HR points with a clean circadian shape (peak ~15:00 → nadir ~03:00), 15-min
    cadence over n_nights days. Deterministic (no RNG)."""
    from datetime import datetime, timedelta, timezone

    import math
    pts = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for d in range(n_nights):
        for step in range(0, 24 * 60, 15):
            t = start + timedelta(days=d, minutes=step)
            h = t.hour + t.minute / 60
            v = 70 + 15 * math.cos(2 * math.pi * (h - 15) / 24)
            pts.append(TimeSeriesPoint(t, v))
    return pts


def _demo() -> int:
    failures = 0

    cal = compute_clock(_synthetic(5))
    print(f"synthetic 5 nights : state={cal.state.value} nights={cal.valid_nights} (expect calibrating)")
    failures += 0 if cal.state is ClockState.CALIBRATING else 1

    real = compute_clock(_synthetic(20))
    nadir = hh_mm(real.nadir_h) if real.nadir_h is not None else "—"
    print(f"synthetic 20 nights: state={real.state.value} nadir={nadir} r2={real.r2:.2f} "
          f"(expect real, nadir≈03:00)")
    failures += 0 if (real.state is ClockState.REAL and abs((real.nadir_h % 24) - 3.0) < 1.0) else 1

    # fact-shape + caveat checks
    f_cal, _ = _to_fact("x", cal)
    f_real, p_real = _to_fact("x", real)
    cal_blocked = any(c.severity is Severity.BLOCK and c.code is CaveatCode.CALIBRATING for c in f_cal.caveats)
    print(f"calibrating fact   : grade={f_cal.evidence_grade.value} value={f_cal.value_text} "
          f"BLOCK-calibrating={cal_blocked} claim_grade={f_cal.is_claim_grade}")
    failures += 0 if (cal_blocked and not f_cal.is_claim_grade) else 1
    print(f"real fact          : grade={f_real.evidence_grade.value} value={f_real.value_text} "
          f"claim_grade={f_real.is_claim_grade} prov={p_real is not None}")
    failures += 0 if (f_real.is_claim_grade and p_real is not None) else 1

    # NOTE: the deterministic synthetic checks above are the smoke-test. (A real-data run used to live
    # here but hardcoded a specific subject + a since-removed DuckDB store — use `indaga selftest
    # --subject <s> --user-dir <dir>` or `eval/genome_parity.py` for real-data validation instead.)
    print(f"\n{'OK' if failures == 0 else f'{failures} FAIL'} — state-machine checks")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_demo())
