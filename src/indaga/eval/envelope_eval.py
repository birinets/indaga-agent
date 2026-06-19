"""Envelope-state eval (Phase 1) — the regression gate for the honesty contract.

Asserts that capability handlers + ``derive_envelope`` emit the correct typed
``finding_state`` / ``answer_readiness`` / ``negative_inference`` across the
multi-omic cases the rebuild plan calls out. Deterministic (synthetic data, no
model calls).

Run:  python3 -m indaga.eval.envelope_eval
"""

from __future__ import annotations

from datetime import date

from datetime import datetime, timezone

from ..capabilities.clock import _clock_state
from ..capabilities.labs import _labs_panel_coverage
from ..capabilities.metabolic import _cgm_glycemic_summary
from ..evidence import envelope as E
from ..operations.model import Context
from ..spine.biological_clock import _synthetic
from ..store import EvidenceGrade, Fact, Scope, Surface, TimeSeries
from ..store.sqlite_store import LocalSQLiteStore


def _clock_ctx(n_nights: int) -> Context:
    s = LocalSQLiteStore()
    s.append_timeseries(
        Scope("demo"),
        TimeSeries("demo", "heart_rate_bpm", "bpm", tuple(_synthetic(n_nights)), {}, (), "synthetic"),
    )
    return Context(subject_id="demo", store=s, surface=Surface.APP)


def _lab_ctx(names: tuple[str, ...]) -> Context:
    s = LocalSQLiteStore()
    s.upsert_facts(Scope("demo"), [
        Fact(f"obs_{n}", "demo", "lab", n, n, value_number=4.0, evidence_grade=EvidenceGrade.A)
        for n in names
    ])
    return Context(subject_id="demo", store=s, surface=Surface.APP)


def _stale_cgm_ctx() -> Context:
    s = LocalSQLiteStore()
    s.upsert_facts(Scope("demo"), [
        Fact("cgm_summary_demo", "demo", "wearable_summary", "cgm_readings_total", "CGM total",
             value_number=8508.0, evidence_grade=EvidenceGrade.B,
             attributes={"first": "2024-01-01", "last": "2024-06-01"})
    ])
    return Context(subject_id="demo", store=s, surface=Surface.APP, now=datetime(2026, 6, 12, tzinfo=timezone.utc))


def _check(name, ok, detail=""):
    return (name, bool(ok), detail)


def run() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    # 1. REAL clock (>=14 nights) -> evidence_present + answer_supported + Midnight present
    r = _clock_state({}, _clock_ctx(20))
    e = r["evidence_envelope"]
    out.append(_check(
        "clock real -> evidence_present/answer_supported, Midnight surfaced, neg-inf disallowed",
        e["finding_state"] == E.EVIDENCE_PRESENT and e["answer_readiness"] == E.ANSWER_SUPPORTED
        and r.get("biological_midnight") and not e["negative_inference"]["allowed"],
        f"{e['finding_state']}/{e['answer_readiness']} midnight={r.get('biological_midnight')}",
    ))

    # 2. CALIBRATING clock (<14 nights) -> index_incomplete + needs_more_data + Midnight WITHHELD
    c = _clock_state({}, _clock_ctx(5))
    ce = c["evidence_envelope"]
    out.append(_check(
        "clock calibrating -> index_incomplete/needs_more_data, Midnight withheld, requires=[calibrated]",
        ce["finding_state"] == E.INDEX_INCOMPLETE and ce["answer_readiness"] == E.NEEDS_MORE_DATA
        and c.get("biological_midnight") is None
        and "calibrated" in ce["negative_inference"]["requires"]
        and not ce["negative_inference"]["allowed"],
        f"{ce['finding_state']}/{ce['answer_readiness']} midnight={c.get('biological_midnight')}",
    ))

    # 3. MEASURED lab (Grade-A LDL) -> evidence_present
    sc = Scope("demo")
    ldl = Fact("obs_ldl", "demo", "lab", "ldl_cholesterol", "LDL", value_number=5.13,
               unit="mmol/L", observed_at=date(2026, 4, 24), interpretation="high",
               evidence_grade=EvidenceGrade.A)
    le = E.derive_envelope("labs.query", sc, [ldl], omic_scope="lab")
    out.append(_check(
        "lab measured (Grade-A) -> evidence_present",
        le["finding_state"] == E.EVIDENCE_PRESENT,
        le["finding_state"],
    ))

    # 4. NEVER-MEASURED analyte (ApoB) -> not_measured, NOT 'normal'
    ne = E.not_measured(operation="labs.query", what="apob", subject_context={"subject_id": "demo"})
    out.append(_check(
        "lab never measured (ApoB) -> not_measured/needs_more_data, absence is unknown not normal",
        ne["finding_state"] == E.NOT_MEASURED and ne["answer_readiness"] == E.NEEDS_MORE_DATA
        and not ne["negative_inference"]["allowed"]
        and ne["guidance"][0] == "not_measured:absence_is_unknown_not_normal",
        ne["finding_state"],
    ))

    # 5. Empty scope -> not_observed_in_consulted_scope, neg-inf disallowed (no false 'normal')
    ee = E.derive_envelope("labs.query", sc, [], omic_scope="lab")
    out.append(_check(
        "empty scope -> not_observed_in_consulted_scope, neg-inf disallowed",
        ee["finding_state"] == E.NOT_OBSERVED_IN_CONSULTED_SCOPE and not ee["negative_inference"]["allowed"],
        ee["finding_state"],
    ))

    # 6. Panel coverage -> not_measured when panel analytes are missing (ApoB present-vs-missing)
    pc = _labs_panel_coverage({}, _lab_ctx(("total_cholesterol", "ldl_cholesterol")))
    pe = pc["evidence_envelope"]
    out.append(_check(
        "lab panel coverage -> not_measured for missing analytes (ApoB), measured ones in 'present'",
        pe["finding_state"] == E.NOT_MEASURED and "apob" in pc["missing"] and "ldl_cholesterol" in pc["present"],
        f"present={pc['present']} missing={pc['missing']}",
    ))

    # 7. Stale CGM -> not_measured for current glucose + requires freshness (no false 'normal')
    fr = _cgm_glycemic_summary({}, _stale_cgm_ctx())
    fe = fr["evidence_envelope"]
    out.append(_check(
        "cgm stale -> not_measured + requires freshness, neg-inf disallowed (no current-glucose claim)",
        fe["finding_state"] == E.NOT_MEASURED and "freshness" in fe["negative_inference"]["requires"]
        and not fe["negative_inference"]["allowed"],
        f"{fe['finding_state']} requires={fe['negative_inference']['requires']}",
    ))

    return out


def main() -> int:
    results = run()
    width = max(len(n) for n, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        flag = "PASS" if ok else "FAIL"
        line = f"[{flag}] {name.ljust(width)}"
        if not ok and detail:
            line += f"  -- got: {detail}"
        print(line)
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} envelope-state checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
