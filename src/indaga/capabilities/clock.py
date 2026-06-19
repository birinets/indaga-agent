"""Circadian capability — the Biological Clock (Phase-1 vertical slice).

Handlers run the validated cosinor state machine (`spine/biological_clock.py`) over
the heart-rate series in the Active Health Index and return a typed evidence
envelope: the Biological Midnight is only surfaced when the clock is CALIBRATED
(≥14 valid nights). Below that, the envelope is `index_incomplete` / `needs_more_data`
and the nadir is withheld — calibration is the wearable analogue of genomic callability.
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..serialize import fact_to_dict
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..spine import BiologicalClock
from ..store import FactQuery, Scope, Surface

CLOCK_FACT = "biological_midnight"


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _ensure_clock_fact(store, scope: Scope):
    facts = store.get_facts(scope, FactQuery(names=(CLOCK_FACT,)))
    if facts:
        return facts[0]
    # Not computed yet — run the deterministic spine, which writes it back.
    BiologicalClock().run(store, scope)
    facts = store.get_facts(scope, FactQuery(names=(CLOCK_FACT,)))
    return facts[0] if facts else None


def _clock_state(params: dict, context: Context) -> dict:
    scope = _scope(context)
    fact = _ensure_clock_fact(context.store, scope)
    facts = [fact] if fact else []
    env = E.derive_envelope(
        "clock.state", scope, facts, omic_scope="derived",
        query_scope={"metric": CLOCK_FACT},
    )
    payload: dict = {"evidence_envelope": env}
    if fact:
        attrs = fact.attributes or {}
        payload["state"] = attrs.get("state")
        payload["valid_nights"] = attrs.get("valid_nights")
        payload["fact"] = fact_to_dict(fact)
        # Only surface the actual Biological Midnight when the clock supports a claim.
        if env["finding_state"] == E.EVIDENCE_PRESENT:
            payload["biological_midnight"] = fact.value_text
    return payload


def _clock_biological_midnight(params: dict, context: Context) -> dict:
    """Focused tool: the Midnight value, withheld unless the clock is calibrated."""
    result = _clock_state(params, context)
    env = result["evidence_envelope"]
    if env["finding_state"] != E.EVIDENCE_PRESENT:
        result["biological_midnight"] = None
    return result


register(Operation(
    "clock.state", _clock_state, capability="circadian",
    description="The Biological Clock state and Biological Midnight (HR-nadir). Honest about "
                "calibration: withholds the Midnight until ≥14 valid nights.",
    input_schema={"type": "object", "properties": {}},
    skill="skills/circadian/SKILL.md",
    produces=("biological_midnight_fact", "evidence_envelope"),
    omic_scope="derived", discovery_role="entry_tool",
))

register(Operation(
    "clock.biological_midnight", _clock_biological_midnight, capability="circadian",
    description="The Biological Midnight clock time (HR nadir), returned only when the clock is "
                "calibrated (≥14 valid nights); otherwise the calibration state.",
    input_schema={"type": "object", "properties": {}},
    skill="skills/circadian/SKILL.md",
    produces=("biological_midnight_fact", "evidence_envelope"),
    omic_scope="derived", discovery_role="focused_tool",
))
