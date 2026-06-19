"""Health-index capability — the general intake/query tools over the Active Health Index.

The six tools from the prototype MCP server (facts/timeseries/context_pack/provenance/
sources/corrections), re-homed onto the dispatcher and emitting the new typed
``EvidenceEnvelope`` instead of the old ``{ok, refusal}`` shape. This is the
tool-parity piece that lets us re-point a host to the new server.
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..serialize import (
    contextpack_to_dict,
    correction_to_dict,
    fact_to_dict,
    provenance_to_dict,
    sourceref_to_dict,
    timeseries_to_dict,
)
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..store import EvidenceGrade, FactQuery, Scope, Surface
from ..store.codec import parse_dateish


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subject_ctx(scope: Scope, omic: str = "multi") -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": omic}


def _facts_query(params: dict, context: Context) -> dict:
    scope = _scope(context)
    q = FactQuery(
        names=tuple(params.get("names") or ()),
        domains=tuple(params.get("domains") or ()),
        flagged_only=bool(params.get("flagged_only", False)),
        min_evidence=EvidenceGrade(params["min_evidence"]) if params.get("min_evidence") else EvidenceGrade.INSUFFICIENT,
        limit=params.get("limit"),
    )
    facts = context.store.get_facts(scope, q)
    env = E.derive_envelope("facts.query", scope, facts, query_scope=params, omic_scope="multi")
    return {"facts": [fact_to_dict(f) for f in facts], "count": len(facts), "evidence_envelope": env}


def _timeseries_get(params: dict, context: Context) -> dict:
    scope = _scope(context)
    metric = params.get("metric")
    ts = context.store.get_timeseries(
        scope, metric, since=parse_dateish(params.get("since")), until=parse_dateish(params.get("until")))
    if ts.n > 0:
        env = E.evidence_present(
            operation="timeseries.get", answer_readiness=E.SCOPED_ANSWER_ONLY,
            subject_context=_subject_ctx(scope, "wearable"),
            observations={"metric": metric, "n": ts.n, "summary": ts.summary},
            query_scope={"metric": metric})
    else:
        env = E.not_measured(operation="timeseries.get", what=metric,
                             subject_context=_subject_ctx(scope, "wearable"))
    return {"timeseries": timeseries_to_dict(ts, include_points=bool(params.get("include_points"))),
            "evidence_envelope": env}


def _context_pack_get(params: dict, context: Context) -> dict:
    scope = _scope(context)
    cp = context.store.get_context_pack(scope)
    env = E.derive_envelope("context_pack.get", scope, list(cp.facts), omic_scope="multi")
    return {"context_pack": contextpack_to_dict(cp), "evidence_envelope": env}


def _provenance_resolve(params: dict, context: Context) -> dict:
    scope = _scope(context)
    target = params.get("target_id")
    prov = context.store.get_provenance(scope, target)
    if prov is None:
        env = E.not_assessed(operation="provenance.resolve",
                             reason=f"No provenance for {target!r} in this subject's record.",
                             subject_context=_subject_ctx(scope))
        return {"provenance": None, "evidence_envelope": env}
    env = E.evidence_present(operation="provenance.resolve",
                             subject_context=_subject_ctx(scope),
                             observations={"resolved": target})
    return {"provenance": provenance_to_dict(prov), "evidence_envelope": env}


def _sources_list(params: dict, context: Context) -> dict:
    scope = _scope(context)
    sources = context.store.list_sources(scope)
    if sources:
        env = E.evidence_present(operation="sources.list", subject_context=_subject_ctx(scope),
                                 observations={"source_count": len(sources)})
    else:
        env = E.empty_consulted_scope(operation="sources.list", subject_context=_subject_ctx(scope))
    return {"sources": [sourceref_to_dict(s) for s in sources], "count": len(sources),
            "evidence_envelope": env}


def _corrections_list(params: dict, context: Context) -> dict:
    scope = _scope(context)
    corrections = context.store.get_corrections(scope)
    env = E.evidence_present(operation="corrections.list", subject_context=_subject_ctx(scope),
                             observations={"correction_count": len(corrections)})
    return {"corrections": [correction_to_dict(c) for c in corrections], "count": len(corrections),
            "evidence_envelope": env}


_CAP = "health-index"
_SKILL = "skills/health-index/SKILL.md"

register(Operation("facts.query", _facts_query, capability=_CAP, skill=_SKILL,
    description="Query structured health facts (labs, genomic, derived) for the subject; graded + caveat-wrapped.",
    input_schema={"type": "object", "properties": {
        "names": {"type": "array", "items": {"type": "string"}},
        "domains": {"type": "array", "items": {"type": "string"}},
        "flagged_only": {"type": "boolean"},
        "min_evidence": {"type": "string", "enum": ["A", "B", "C", "D", "INSUFFICIENT"]},
        "limit": {"type": "integer"}}},
    produces=("facts", "evidence_envelope"), discovery_role="entry_tool"))

register(Operation("sources.list", _sources_list, capability=_CAP, skill=_SKILL,
    description="List the subject's connected data sources and freshness.",
    input_schema={"type": "object", "properties": {}},
    produces=("sources", "evidence_envelope"), discovery_role="entry_tool"))

register(Operation("context_pack.get", _context_pack_get, capability=_CAP, skill=_SKILL,
    description="The self-describing, source-backed AI context pack: profile + facts + timeseries summaries + caveats.",
    input_schema={"type": "object", "properties": {}},
    produces=("context_pack", "evidence_envelope"), discovery_role="entry_tool"))

register(Operation("timeseries.get", _timeseries_get, capability=_CAP, skill=_SKILL,
    description="A high-frequency series (e.g. heart_rate_bpm) with summary stats.",
    input_schema={"type": "object", "properties": {
        "metric": {"type": "string"}, "since": {"type": "string"}, "until": {"type": "string"},
        "include_points": {"type": "boolean"}}, "required": ["metric"]},
    produces=("timeseries", "evidence_envelope"), discovery_role="focused_tool"))

register(Operation("provenance.resolve", _provenance_resolve, capability=_CAP, skill=_SKILL,
    description="Resolve the provenance (source file + locator) for a fact_id.",
    input_schema={"type": "object", "properties": {"target_id": {"type": "string"}}, "required": ["target_id"]},
    produces=("provenance", "evidence_envelope"), discovery_role="focused_tool"))

register(Operation("corrections.list", _corrections_list, capability=_CAP, skill=_SKILL,
    description="The subject's corrections ledger (superseded values and why).",
    input_schema={"type": "object", "properties": {}},
    produces=("corrections", "evidence_envelope"), discovery_role="focused_tool"))
