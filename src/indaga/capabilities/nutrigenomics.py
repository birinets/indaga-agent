"""Nutrigenomics capability — interpreted single-marker food/nutrient genetics.

Resolves a curated nutrigenetic panel (lactose, caffeine, alcohol, folate, vitamin
B12/A, iron, appetite, bitter taste) from the Active Genome Index and interprets each
genotype in plain English. Markers not on the chip are `not_measured` (callability).
Scope guard: NO diet prescriptions or supplement dosing — single-marker associations
are modest and probabilistic, paired with the user's actual labs where possible.
"""

from __future__ import annotations

from ..evidence import envelope as E
from ..genome.agi import AGIReader, open_chip_agi
from ..genome.panels import NUTRIGENETIC_MARKERS
from ..operations.model import Context, Operation
from ..operations.registry import register
from ..runtime import paths
from ..store import Scope, Surface


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subj(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "genomic"}


def _nutri_markers(params: dict, context: Context) -> dict:
    scope = _scope(context)
    agi = AGIReader.open(str(paths.active_genome_index_path(context.subject_id)))
    if agi is None:
        return {"evidence_envelope": E.not_assessed(
            operation="nutrigenomics.markers", reason="Active Genome Index not built.",
            subject_context=_subj(scope))}
    cat = (params.get("category") or "").lower()
    comp = {"A": "T", "T": "A", "C": "G", "G": "C"}
    # Directly-typed chip fallback: imputation can LOSE a typed common SNP (it returns DR2=0 and
    # is dropped from the imputed AGI — verified for CYP1A2/HFE/ALDH2/ADH1B/FTO/LCT). A marker the
    # imputed genome can't call is re-checked on the raw chip, where it's a direct measurement.
    # Built + cached once; None when there's no usable chip → imputed-only (never a wrong call).
    chip = open_chip_agi(context.subject_id, context.user_dir)
    rows, not_probed, uncertain = [], [], []
    for m in NUTRIGENETIC_MARKERS:
        if cat and m["category"] != cat:
            continue
        v = agi.lookup_rsid(m["rsid"])
        typed = bool(v.typed) if v is not None else False   # overlaid chip hard-call baked into the main AGI
        if v is None or not v.callable:
            cv = chip.lookup_rsid(m["rsid"]) if chip else None
            if cv is not None and cv.callable:
                v, typed = cv, True
            else:
                not_probed.append({"rsid": m["rsid"], "gene": m["gene"], "trait": m["trait"]})
                continue
        a, b = m["alleles"].split("/")
        pair = {a, b}
        obs = {c for c in v.genotype if c in "ACGT"}
        # allele-consistency guard: refuse to interpret a genotype whose alleles don't
        # match the marker's forward-strand pair, or where the panel effect allele is off-pair.
        if not obs <= pair or m["effect_allele"] not in pair:
            uncertain.append({"rsid": m["rsid"], "gene": m["gene"], "trait": m["trait"],
                              "genotype": v.genotype, "expected_alleles": m["alleles"],
                              "reason": "genotype alleles do not match the expected forward-strand pair"})
            continue
        n = v.genotype.count(m["effect_allele"])
        palindromic = pair == {comp[a], comp[b]}  # A/T or C/G — strand-sensitive
        interp = m["interp"].get(n, "")
        if palindromic:
            interp += "  [A/T or C/G site — strand-sensitive; confirm before acting]"
        rows.append({
            "rsid": m["rsid"], "gene": m["gene"], "category": m["category"], "trait": m["trait"],
            "genotype": v.genotype, "zygosity": v.zygosity, "effect_alleles": n,
            "strand_sensitive": palindromic, "interpretation": interp,
            # rung-1 honesty metadata (conservative-interpretation layer)
            "evidence_tier": m.get("evidence_tier"), "relevant_lab": m.get("relevant_lab"),
            "debunks": m.get("debunks", []), "source": m.get("source"),
            "genotype_source": "chip_directly_typed" if typed else "imputed",
        })
    env = E.evidence_present(
        operation="nutrigenomics.markers", answer_readiness=E.SCOPED_ANSWER_ONLY,
        subject_context=_subj(scope),
        observations={"interpreted": len(rows), "not_on_chip": len(not_probed), "uncertain": len(uncertain)})
    return {
        "markers": rows, "not_on_chip": not_probed, "uncertain": uncertain,
        "note": "Single-marker nutrigenetics — modest, probabilistic effects, NOT a diet prescription "
                "or supplement dosing. Each marker carries evidence_tier, the relevant_lab to measure, "
                "explicit debunks (popular-but-unsupported claims to disown), and a source citation — "
                "surface the debunks and pair with the user's measured labs before acting.",
        "evidence_envelope": env,
    }


register(Operation("nutrigenomics.markers", _nutri_markers, capability="nutrigenomics",
    skill="skills/nutrigenomics/SKILL.md",
    description="Interpreted nutrigenetic markers from the chip: lactose tolerance, caffeine + alcohol "
                "metabolism, folate (MTHFR), B12/vitamin-A, iron (HFE), appetite (FTO), bitter taste. "
                "Filter by category. Modest single-marker effects, never a diet prescription.",
    input_schema={"type": "object", "properties": {
        "category": {"type": "string", "enum": ["food-tolerance", "nutrient-metabolism",
                                                 "eating-behavior", "taste", "sensitivity"]}}},
    produces=("evidence_envelope",), omic_scope="genomic", discovery_role="entry_tool"))
