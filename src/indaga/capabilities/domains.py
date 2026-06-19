"""Domains capability — surface the pre-computed domain panels (genome lenses).

Indaga curates a gene panel per wellness domain and produces a bundle
per domain with the user's annotated variants in those genes + the relevant labs +
recommended missing tests. Rather than re-author panels, Indaga surfaces these
validated bundles as ~15 genome-domain lenses (methylation, hormones, immunity,
gut, skin, sleep, longevity, athletic, mood/focus, senses, hereditary-cancer, …),
enriched with the genotype from the Active Genome Index.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..evidence import envelope as E
from ..genome.agi import AGIReader
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..runtime import paths
from ..store import Scope, Surface

# bundles that are wearable/time-series, not genome-domain lenses
_NON_GENOME = {"cgm", "vilpa", "vo2", "recovery"}
_SIG_RANK = {"pathogenic": 0, "likely_pathogenic": 1, "risk factor": 2, "drug response": 3,
             "association": 4, "uncertain": 5, "likely_benign": 8, "benign": 9}


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subj(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "genomic"}


def _bundles_dir(context: Context) -> Path:
    return Path(context.user_dir or "") / "bundles"


def _load_bundle(context: Context, domain: str) -> dict | None:
    p = _bundles_dir(context) / f"{domain}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _sig_key(sig: str | None) -> int:
    return _SIG_RANK.get((sig or "").lower(), 6)


def _domains_list(params: dict, context: Context) -> dict:
    bd = _bundles_dir(context)
    out = []
    if bd.exists():
        for p in sorted(bd.glob("*.json")):
            dom = p.stem
            if dom in _NON_GENOME:
                continue
            try:
                b = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if not b.get("dna_variants") and not b.get("panel_genes"):
                continue
            out.append({"domain": dom, "title": b.get("title", dom),
                        "panel_genes": len(b.get("panel_genes", [])),
                        "variants": len(b.get("dna_variants", []))})
    env = (E.evidence_present(operation="domains.list", subject_context=_subj(_scope(context)),
                              observations={"domains": len(out)}) if out
           else E.not_measured(operation="domains.list", what="domain panels",
                               subject_context=_subj(_scope(context))))
    return {"domains": out, "evidence_envelope": env}


def _domains_get(params: dict, context: Context) -> dict:
    scope = _scope(context)
    domain = (params.get("domain") or "").strip().lower()
    b = _load_bundle(context, domain)
    if b is None:
        return {"evidence_envelope": E.not_assessed(
            operation="domains.get", reason=f"no domain bundle for {domain!r}; use domains.list",
            subject_context=_subj(scope))}

    agi = AGIReader.open(str(paths.active_genome_index_path(context.subject_id)))
    variants = []
    for v in b.get("dna_variants", []):
        rs = v.get("rsid")
        call = agi.lookup_rsid(rs) if (agi and rs) else None
        variants.append({
            "rsid": rs, "gene": v.get("hugo"),
            "clinvar_sig": v.get("clinvar.sig"),
            "clinvar_disease": v.get("clinvar.disease_names"),
            "am_class": v.get("alphamissense.am_class"),
            "revel": v.get("revel.score"),
            "genotype": call.genotype if call else None,
            "zygosity": call.zygosity if call else None,
            "on_chip": bool(call and call.callable),
        })
    # most clinically interesting first; cap the dump
    variants.sort(key=lambda x: (_sig_key(x["clinvar_sig"]), x["gene"] or ""))
    notable = [x for x in variants if _sig_key(x["clinvar_sig"]) <= 5]

    env = E.evidence_present(
        operation="domains.get", answer_readiness=E.SCOPED_ANSWER_ONLY, subject_context=_subj(scope),
        observations={"domain": domain, "variants": len(variants), "notable": len(notable)})
    return {
        "domain": domain, "title": b.get("title", domain),
        "panel_genes": b.get("panel_genes", []),
        "variants": variants[:25],
        "notable_variants": notable[:15],
        "blood_values_relevant": b.get("blood_values_relevant", []),
        "missing_tests_recommended": b.get("missing_tests_recommended", []),
        "family_history": b.get("user_family_history"),
        "note": "Curated domain panel with the subject's variants (genotype from the chip) + relevant "
                "labs. Most ClinVar findings on a panel are benign/common; lead with the notable ones, "
                "and pair genetics with the user's measured labs.",
        "evidence_envelope": env,
    }


register(Operation("domains.list", _domains_list, capability="domains", skill="skills/domains/SKILL.md",
    description="List the available genome-domain lenses (methylation, hormones, immunity, gut, skin, "
                "sleep, longevity, athletic, mood/focus, senses, hereditary-cancer, …) with panel + variant counts.",
    input_schema={"type": "object", "properties": {}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="entry_tool"))

register(Operation("domains.get", _domains_get, capability="domains", skill="skills/domains/SKILL.md",
    description="A domain genome-lens: its curated gene panel, the subject's variants (genotype + ClinVar), "
                "relevant labs, and recommended missing tests. e.g. {'domain':'methylation'}.",
    input_schema={"type": "object", "properties": {"domain": {"type": "string"}}, "required": ["domain"]},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="entry_tool"))
