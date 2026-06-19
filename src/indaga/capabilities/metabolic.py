"""Metabolic/CGM capability — the freshness leg of the multi-omic envelope.

If a per-reading glucose series is present, computes GMI/TIR via the spine. If only
a session summary is present (the current data shape) and the last reading is stale,
it returns ``not_measured`` for *current* glucose with a ``freshness`` requirement —
an old sensor read can't be claimed as your present control (the CGM analogue of
genomic callability).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from ..evidence import envelope as E
from ..serialize import fact_to_dict
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..spine import CGMMetabolic
from ..store import FactQuery, Scope, Surface

STALE_DAYS = 90


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subject_ctx(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "cgm"}


def _cgm_glycemic_summary(params: dict, context: Context) -> dict:
    scope = _scope(context)
    store = context.store
    now = context.now or datetime(2026, 6, 12, tzinfo=timezone.utc)

    # Path 1: real per-reading series present -> compute GMI/TIR via the spine.
    ts = store.get_timeseries(scope, "glucose_mgdl")
    if ts.n > 0:
        CGMMetabolic().run(store, scope)
        facts = store.get_facts(scope, FactQuery(names=("gmi_estimate",)))
        env = E.derive_envelope("cgm.glycemic_summary", scope, facts, omic_scope="cgm")
        return {"facts": [fact_to_dict(f) for f in facts], "evidence_envelope": env}

    # Path 2: only a session summary exists.
    summ = store.get_facts(scope, FactQuery(names=("cgm_readings_total",)))
    if not summ:
        env = E.not_measured(operation="cgm.glycemic_summary", what="cgm_glucose",
                             subject_context=_subject_ctx(scope))
        return {"evidence_envelope": env}

    fact = summ[0]
    attrs = fact.attributes or {}
    last = attrs.get("last")
    days = None
    if last:
        try:
            days = (now.date() - date.fromisoformat(last)).days
        except ValueError:
            days = None

    if days is not None and days > STALE_DAYS:
        env = E.not_measured(
            operation="cgm.glycemic_summary",
            what=f"current glucose (last CGM reading {last}, {days} days ago)",
            requires=(E.REQ_FRESHNESS, E.REQ_MEASUREMENT_PRESENT),
            reason=f"CGM data is {days} days old; current glucose control is unknown, not normal.",
            subject_context=_subject_ctx(scope),
            observations={"last_reading": last, "first_reading": attrs.get("first"),
                          "days_since": days, "n_readings": fact.value_number, "stale": True})
        return {"historical_summary": fact_to_dict(fact), "evidence_envelope": env}

    # Fresh-ish summary but no per-reading points: report what we have, scoped.
    env = E.evidence_present(
        operation="cgm.glycemic_summary", answer_readiness=E.SCOPED_ANSWER_ONLY,
        subject_context=_subject_ctx(scope),
        observations={"n_readings": fact.value_number, "note": "summary only; per-reading series not ingested"})
    return {"historical_summary": fact_to_dict(fact), "evidence_envelope": env}


register(Operation("cgm.glycemic_summary", _cgm_glycemic_summary, capability="metabolic",
    description="Glycemic summary (GMI / time-in-range) from the CGM series. Withholds a current-glucose "
                "claim when the sensor data is stale (freshness).",
    input_schema={"type": "object", "properties": {}},
    skill="skills/metabolic/SKILL.md", produces=("evidence_envelope",),
    omic_scope="cgm", discovery_role="entry_tool"))
