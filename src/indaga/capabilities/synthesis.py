"""Synthesis capability — the multi-omic fusion that a genomics-only agent cannot do.

`synthesis.multi_omic_question` gathers the evidence relevant to a topic ACROSS
capabilities — the user's genotype(s), their labs, their polygenic scores, their CGM
/ wearable series — into one fused, envelope-wrapped pack with honest limits, so the
host model can answer a cross-omic question grounded in all modalities at once
(e.g. "my diabetes risk" = TCF7L2 × T2D-PGS × CGM × glucose labs).

The agent does not write the narrative; it assembles the grounded, caveated evidence
and the guidance for how to fuse it honestly.
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..genome import evidence as gev
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..serialize import fact_to_dict, timeseries_to_dict
from ..store import Scope, Surface
from .genome import _variant_resolve
from .grounding import gene_context

# topic → relevant variants, labs, PGS keywords, timeseries metrics, name-keywords
_TOPICS: dict[str, dict] = {
    "diabetes": dict(
        rsids={"rs7903146": "TCF7L2"},
        labs={"fasting_glucose", "hba1c", "glucose", "triglycerides", "hdl_cholesterol"},
        pgs=("diabetes",), metrics=("glucose_mgdl",), kw=("glucose", "insulin", "diabet", "metabol")),
    "cardiovascular": dict(
        rsids={"rs429358": "APOE", "rs7412": "APOE"},
        labs={"ldl_cholesterol", "hdl_cholesterol", "total_cholesterol", "triglycerides",
              "apob", "lipoprotein_a"},
        pgs=("coronary", "cardio", "cholesterol", "heart", "ldl"), metrics=(),
        kw=("chol", "lipid", "cardio", "heart", "apob")),
    "methylation": dict(
        rsids={"rs1801133": "MTHFR", "rs1801131": "MTHFR"},
        labs={"homocysteine", "folate", "vitamin_b12", "b12"},
        pgs=(), metrics=(), kw=("methyl", "homocyst", "folate", "mthfr")),
}


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _match_topic(topic: str) -> dict:
    t = topic.lower()
    for key, prof in _TOPICS.items():
        if key in t or any(k in t for k in prof["kw"]):
            return prof
    return dict(rsids={}, labs=set(), pgs=((t,) if t else ()), metrics=("glucose_mgdl",), kw=((t,) if t else ()))


def _multi_omic_question(params: dict, context: Context) -> dict:
    scope = _scope(context)
    topic = (params.get("topic") or params.get("q") or "").strip()
    prof = _match_topic(topic)
    ud = context.user_dir or ""

    # proactively resolve the topic's key variants (writes them into the index)
    for rs in prof["rsids"]:
        try:
            _variant_resolve({"rsid": rs}, context)
        except Exception:
            pass

    # local grounding for the topic's key genes (read-only, download-free) — the mechanism the
    # fusion can cite (e.g. TCF7L2 → Wnt/β-catenin; MTHFR → folate metabolism). Omitted if absent.
    grounding = {}
    for gene in sorted({g for g in prof["rsids"].values() if g}):
        gc = gene_context(context, gene)
        if gc:
            grounding[gene] = gc

    facts = context.store.get_facts(scope)
    dna = [f for f in facts if f.domain == "genomic"]
    derived = [f for f in facts if f.domain in ("metabolic", "circadian", "wearable_summary")]

    def _lab_relevant(f) -> bool:
        if prof["labs"] and f.name in prof["labs"]:
            return True
        return any(k and k in f.name for k in prof["kw"])
    labs = [f for f in facts if f.domain == "lab" and (not topic or _lab_relevant(f))]

    pgs = [s for s in gev.pgs_scores(ud, context.subject_id)
           if any(k and k in str(s.get("trait_label", "")).lower() for k in prof["pgs"])][:6]

    ts = []
    for m in prof["metrics"]:
        t = context.store.get_timeseries(scope, m)
        if t.n:
            ts.append(timeseries_to_dict(t))

    claim_facts = labs + dna  # the graded facts that can ground claims
    env = E.derive_envelope("synthesis.multi_omic_question", scope, claim_facts,
                            omic_scope="multi", query_scope={"topic": topic or "general"})
    guidance = (
        "Fuse the modalities below for the topic: state what each says (genotype, labs, PGS, CGM), "
        "where they CONVERGE and where they DIVERGE, and the honest limits — stale CGM, not-on-chip "
        "variants (callability), directional/population-relative PGS, common-variant false alarms. "
        "Use the per-gene `grounding` (local Reactome pathways + HPA tissues) to explain the MECHANISM "
        "(e.g. TCF7L2 → Wnt/β-catenin signalling), never as a risk magnitude. "
        "Lead with the convergent picture; never convert a percentile or genotype into a diagnosis. "
        "Decision-support, reviewed with a clinician."
    )
    return {
        "topic": topic or "general",
        "dna": [fact_to_dict(f) for f in dna],
        "grounding": grounding,
        "labs": [fact_to_dict(f) for f in labs],
        "derived": [fact_to_dict(f) for f in derived],
        "polygenic_scores": [
            {"pgs_id": s.get("pgs_id"), "trait": s.get("trait_label"),
             "percentile": round(s["percentile"], 1) if s.get("percentile") is not None else None,
             "direction": s.get("direction")} for s in pgs],
        "timeseries": ts,
        "synthesis_guidance": guidance,
        "evidence_envelope": env,
    }


register(Operation("synthesis.multi_omic_question", _multi_omic_question, capability="synthesis",
    skill="skills/synthesis/SKILL.md",
    description="Fuse DNA + labs + polygenic scores + CGM/wearables for a topic (e.g. 'diabetes', "
                "'cardiovascular', 'methylation') into one grounded, caveated pack the host can answer "
                "from. The multi-omic synthesis a genomics-only agent cannot do.",
    input_schema={"type": "object", "properties": {"topic": {"type": "string"}, "q": {"type": "string"}}},
    produces=("evidence_envelope",), omic_scope="multi", discovery_role="entry_tool"))
