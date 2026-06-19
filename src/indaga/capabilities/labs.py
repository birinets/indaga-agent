"""Labs capability — the measurement_present leg of the multi-omic envelope.

Asking for an analyte that has no fact in the Active Health Index returns
``not_measured`` (absence is unknown, not normal) — the lab analogue of a no-call
genotype. ``labs.panel_coverage`` reports which analytes of a panel are present vs
never measured.

v1 note: "no fact for this analyte" = "not measured". A LOINC panel→analyte map
(distinguishing 'in panel but normal' from 'not in panel') is the later refinement
(plan §7 open question 1).
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..serialize import fact_to_dict
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..store import FactQuery, Scope, Surface

# A small default lipid/cardiometabolic panel — the v1 stand-in for a LOINC panel map.
DEFAULT_PANEL = (
    "total_cholesterol", "ldl_cholesterol", "hdl_cholesterol", "triglycerides",
    "apob", "lipoprotein_a", "hba1c", "fasting_glucose",
)


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subject_ctx(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "lab"}


def _labs_query(params: dict, context: Context) -> dict:
    scope = _scope(context)
    analyte = params.get("analyte") or params.get("name")
    if analyte:
        facts = context.store.get_facts(scope, FactQuery(names=(analyte,), domains=("lab",)))
        if not facts:
            env = E.not_measured(operation="labs.query", what=analyte, subject_context=_subject_ctx(scope))
            return {"analyte": analyte, "facts": [], "evidence_envelope": env}
        env = E.derive_envelope("labs.query", scope, facts, omic_scope="lab", query_scope={"analyte": analyte})
        return {"analyte": analyte, "facts": [fact_to_dict(f) for f in facts], "evidence_envelope": env}
    facts = context.store.get_facts(scope, FactQuery(domains=("lab",), flagged_only=bool(params.get("flagged_only"))))
    env = E.derive_envelope("labs.query", scope, facts, omic_scope="lab")
    return {"facts": [fact_to_dict(f) for f in facts], "count": len(facts), "evidence_envelope": env}


def _labs_panel_coverage(params: dict, context: Context) -> dict:
    scope = _scope(context)
    analytes = tuple(params.get("analytes") or DEFAULT_PANEL)
    present, missing = [], []
    for a in analytes:
        if context.store.get_facts(scope, FactQuery(names=(a,), domains=("lab",))):
            present.append(a)
        else:
            missing.append(a)
    obs = {"panel": list(analytes), "present": present, "missing": missing}
    if missing:
        env = E.not_measured(
            operation="labs.panel_coverage", what=", ".join(missing),
            subject_context=_subject_ctx(scope), observations=obs,
            reason="Some panel analytes were never measured; their absence is unknown, not normal.")
    else:
        env = E.evidence_present(operation="labs.panel_coverage", subject_context=_subject_ctx(scope), observations=obs)
    return {"present": present, "missing": missing, "evidence_envelope": env}


register(Operation("labs.query", _labs_query, capability="labs",
    description="Query a lab analyte (or all labs). An analyte with no fact returns 'not measured' "
                "(absence is unknown, not normal), never a false 'normal'.",
    input_schema={"type": "object", "properties": {
        "analyte": {"type": "string", "description": "normalized name, e.g. 'ldl_cholesterol' or 'apob'"},
        "flagged_only": {"type": "boolean"}}},
    skill="skills/labs/SKILL.md", produces=("facts", "evidence_envelope"),
    omic_scope="lab", discovery_role="entry_tool"))

register(Operation("labs.panel_coverage", _labs_panel_coverage, capability="labs",
    description="Which analytes of a panel are present vs never measured. Distinguishes 'not measured' "
                "(unknown) from 'measured and normal'.",
    input_schema={"type": "object", "properties": {
        "analytes": {"type": "array", "items": {"type": "string"}}}},
    skill="skills/labs/SKILL.md", produces=("evidence_envelope",),
    omic_scope="lab", discovery_role="focused_tool"))
