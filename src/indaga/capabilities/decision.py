"""Decision capability — the single highest-leverage daily action ("Today").

This is the engine side of the PRD's "one decision, not twenty insights" doctrine. It is deliberately
NOT an LLM: the deterministic spine adjudicates (AGENTS.md principle 3). The flow is:

  1. Fan out to existing entry tools (clock.state, cgm.glycemic_summary, …) for THIS subject.
  2. Score a fixed candidate set of chrono-metabolic actions. A candidate is ELIGIBLE only when its
     *required* legs are `evidence_present` — i.e. the finding it leans on is decision-grade. Optional
     "enriching" legs (e.g. a fresh CGM) strengthen the wording but never gate eligibility.
  3. Pick the highest-leverage eligible candidate; the decision carries the envelope of its WEAKEST
     required leg (so the client's confidence chip is mechanically that leg's strength — never invented).
  4. If nothing is eligible, return an honest "nothing urgent" decision whose envelope reflects WHY
     (calibrating clock → index_incomplete; otherwise not_assessed). We never manufacture urgency.

The verb-first sentence is only *phrased* downstream (the gateway's LLM pass); this handler returns the
structured decision + a deterministic default template so the surface is usable with no model at all.
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..operations import call_operation
from ..operations.model import Context, Operation
from ..operations.registry import register

# answer-readiness / finding-state strength, for picking the weakest leg deterministically.
_READINESS_RANK = {
    E.ANSWER_SUPPORTED: 4, E.SCOPED_ANSWER_ONLY: 3, E.NEEDS_CLINICAL_CONFIRMATION: 2,
    E.NEEDS_MORE_DATA: 1, E.NEEDS_INDEX_BUILD: 1, E.NEEDS_USER_INSTALL: 1, E.CANNOT_ANSWER_YET: 0,
}
_FINDING_RANK = {
    E.EVIDENCE_PRESENT: 4, E.TRUE_NEGATIVE_SUPPORTED: 3, E.NOT_OBSERVED_IN_CONSULTED_SCOPE: 2,
    E.NOT_MEASURED: 1, E.INDEX_INCOMPLETE: 1, E.NOT_ASSESSED: 0, E.BLOCKED_MISSING_LIBRARY: 0,
}


def _leg_strength(env: dict) -> tuple[int, int]:
    return (_FINDING_RANK.get(env.get("finding_state"), 0),
            _READINESS_RANK.get(env.get("answer_readiness"), 0))


def _gather_leg(context: Context, op_name: str) -> dict:
    """Run one entry op and capture its result + envelope (the building block for candidates)."""
    result = call_operation(op_name, {}, context)
    return {"op": op_name, "result": result, "envelope": result.get("evidence_envelope", {})}


def _is_present(leg: dict) -> bool:
    return leg["envelope"].get("finding_state") == E.EVIDENCE_PRESENT


def _fmt_clock(hours: float) -> str:
    hours %= 24.0
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = (h + 1) % 24, 0
    return f"{h:02d}:{m:02d}"


# -- candidate builders ----------------------------------------------------- #
# Each: (id, kind, leverage, required_ops, enriching_ops, build(legs)->dict|None). Higher leverage wins.

def _build_eating_window(legs: dict) -> dict | None:
    clock = legs.get("clock.state")
    if not clock or not _is_present(clock):
        return None
    fact = clock["result"].get("fact") or {}
    midnight = fact.get("value_number")
    if midnight is None:
        return None
    # Heuristic anchor (clearly labelled, not a clinical formula): close the eating window well before
    # the circadian nadir — default 8 h before Biological Midnight — to bias eating earlier in the phase.
    offset_h = 8.0
    window_close = _fmt_clock(midnight - offset_h)
    cgm = legs.get("cgm.glycemic_summary")
    cgm_fresh = bool(cgm and _is_present(cgm))
    supporting = (f"Anchored to your Biological Midnight ({clock['result'].get('biological_midnight')}) "
                  f"from {fact.get('attributes', {}).get('valid_nights')} nights of heart-rate data.")
    if cgm_fresh:
        supporting += " Your recent glucose supports tightening late-evening intake."
    return {
        "action_template": "Finish eating by about {window_close} tonight.",
        "params": {"window_close": window_close, "biological_midnight": clock["result"].get("biological_midnight"),
                   "offset_hours": offset_h, "cgm_enriched": cgm_fresh},
        "supporting": supporting,
        "heuristic": "eating-window close = Biological Midnight − 8 h (chrono-metabolic alignment; provisional)",
    }


def _build_morning_light(legs: dict) -> dict | None:
    clock = legs.get("clock.state")
    if not clock or not _is_present(clock):
        return None
    fact = clock["result"].get("fact") or {}
    midnight = fact.get("value_number")
    if midnight is None:
        return None
    # Light shortly after the nadir advances/stabilises phase; anchor ~2.5 h after Biological Midnight.
    light_time = _fmt_clock(midnight + 2.5)
    return {
        "action_template": "Get bright light within ~30 min of {light_time} to anchor your clock.",
        "params": {"light_time": light_time, "biological_midnight": clock["result"].get("biological_midnight")},
        "supporting": f"Light just after your Biological Midnight ({clock['result'].get('biological_midnight')}) "
                      "stabilises circadian phase.",
        "heuristic": "morning-light anchor = Biological Midnight + 2.5 h (phase stabilisation; provisional)",
    }


_CANDIDATES = [
    {"id": "eating_window_alignment", "kind": "chrono_metabolic", "leverage": 90,
     "required": ("clock.state",), "enriching": ("cgm.glycemic_summary",), "build": _build_eating_window},
    {"id": "morning_light_anchor", "kind": "circadian", "leverage": 60,
     "required": ("clock.state",), "enriching": (), "build": _build_morning_light},
]

# the ops we always gather (union of all candidate legs) — one place to extend as candidates grow.
_GATHER_OPS = ("clock.state", "cgm.glycemic_summary")


def _decision_envelope(operation: str, context: Context, weakest_leg_env: dict, *,
                       observations: dict, notes: list[str]) -> dict:
    """Re-stamp the weakest required leg's envelope as the decision's own — preserving its state,
    readiness and negative_inference so the chip is exactly that leg's strength."""
    subject_context = {"uses_personal_data": True, "subject_id": context.subject_id, "omic_scope": "derived"}
    return E.envelope(
        operation=operation,
        finding_state=weakest_leg_env.get("finding_state", E.NOT_ASSESSED),
        answer_readiness=weakest_leg_env.get("answer_readiness", E.CANNOT_ANSWER_YET),
        negative_inference=weakest_leg_env.get("negative_inference"),
        subject_context=subject_context,
        observations=observations,
        notes=notes,
    )


def _decision_today(params: dict, context: Context) -> dict:
    legs = {op: _gather_leg(context, op) for op in _GATHER_OPS}

    # evaluate every candidate's eligibility (required legs all evidence_present)
    evaluated = []
    for cand in _CANDIDATES:
        req_legs = [legs[o] for o in cand["required"] if o in legs]
        eligible = bool(req_legs) and all(_is_present(leg) for leg in req_legs)
        built = cand["build"](legs) if eligible else None
        evaluated.append({
            "id": cand["id"], "kind": cand["kind"], "leverage": cand["leverage"],
            "eligible": eligible and built is not None,
            "required": list(cand["required"]),
            "required_states": {leg["op"]: leg["envelope"].get("finding_state") for leg in req_legs},
            "built": built,
        })

    eligible = sorted((c for c in evaluated if c["eligible"]), key=lambda c: c["leverage"], reverse=True)

    if eligible:
        chosen = eligible[0]
        cand = next(c for c in _CANDIDATES if c["id"] == chosen["id"])
        # weakest REQUIRED leg drives the chip (enriching legs never weaken a decision)
        req_envs = [legs[o]["envelope"] for o in cand["required"]]
        weakest = min(req_envs, key=_leg_strength)
        legs_summary = [{"op": o, "role": "required",
                         "finding_state": legs[o]["envelope"].get("finding_state"),
                         "answer_readiness": legs[o]["envelope"].get("answer_readiness")}
                        for o in cand["required"]] + \
                       [{"op": o, "role": "enriching",
                         "finding_state": legs[o]["envelope"].get("finding_state"),
                         "answer_readiness": legs[o]["envelope"].get("answer_readiness")}
                        for o in cand["enriching"] if o in legs]
        built = chosen["built"]
        decision = {
            "candidate_id": chosen["id"], "kind": chosen["kind"],
            "action_template": built["action_template"], "params": built["params"],
            "supporting": built["supporting"], "heuristic": built["heuristic"],
            "legs": legs_summary,
        }
        env = _decision_envelope(
            "decision.today", context, weakest,
            observations={"chosen_candidate": chosen["id"], "eligible_candidates": [c["id"] for c in eligible],
                          "weakest_required_leg": weakest.get("operation"),
                          "candidate_count": len(_CANDIDATES)},
            notes=[f"Decision-support only; phrasing to be finalised by the assistant. {built['heuristic']}"],
        )
        return {"decision": decision, "candidates": evaluated, "evidence_envelope": env}

    # --- honest fallback: nothing high-leverage is decision-grade today ----- #
    clock_env = legs["clock.state"]["envelope"]
    blocking = clock_env  # the wedge's gating leg
    decision = {
        "candidate_id": None, "kind": "none",
        "action_template": "Nothing urgent — your system looks steady. {detail}",
        "params": {"detail": _fallback_detail(blocking)},
        "supporting": _fallback_detail(blocking),
        "heuristic": None, "legs": [{"op": "clock.state", "role": "required",
                                     "finding_state": blocking.get("finding_state"),
                                     "answer_readiness": blocking.get("answer_readiness")}],
    }
    env = _decision_envelope(
        "decision.today", context, blocking,
        observations={"chosen_candidate": None, "eligible_candidates": [],
                      "reason": "no candidate's required legs are decision-grade"},
        notes=["No high-leverage action is decision-grade today; not manufacturing urgency."],
    )
    return {"decision": decision, "candidates": evaluated, "evidence_envelope": env}


def _fallback_detail(clock_env: dict) -> str:
    state = clock_env.get("finding_state")
    if state == E.INDEX_INCOMPLETE:
        return "Your Biological Clock is still calibrating — your daily chrono-metabolic action unlocks once it's ready."
    return "Here's nothing you must act on right now; connect more data to surface higher-leverage actions."


register(Operation(
    "decision.today", _decision_today, capability="decision",
    description="The single highest-leverage daily action. Deterministic candidate ranker over the "
                "chrono-metabolic wedge; a candidate fires only when its required findings are "
                "decision-grade, and the decision carries the envelope of its weakest required leg.",
    input_schema={"type": "object", "properties": {}},
    skill="skills/decision/SKILL.md",
    produces=("daily_decision", "evidence_envelope"),
    omic_scope="derived", discovery_role="entry_tool",
))
