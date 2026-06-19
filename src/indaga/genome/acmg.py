"""Automated ACMG/AMP variant classification (Phase C) — the differentiator.

Genomi and OpenCRAVAT LOOK UP ClinVar's classification; this COMPUTES one, from ACMG/AMP
2015 (Richards et al.) criteria combined per the published rules into a 5-tier call
(Pathogenic / Likely pathogenic / VUS / Likely benign / Benign), each with the criteria
that fired. Then it reports the computed tier ALONGSIDE ClinVar's, so agreement/divergence
is explicit.

v1 is MISSENSE-focused and uses the criteria computable from Indaga's owned evidence:
  • PM2  — absent / ultra-rare in gnomAD            (frequency)
  • BA1  — ≥5% in gnomAD (stand-alone benign)       (frequency)
  • BS1  — ≥1% in gnomAD (too common for the disorder)
  • PP3  — AlphaMissense supports pathogenic (Supporting/Moderate/Strong)
  • BP4  — AlphaMissense supports benign
NOT computed (need consequence annotation / segregation / functional data — honest gaps):
  PVS1 (LoF), PS1/PM5 (same/adjacent codon), PS3/BS3 (functional), PP1/BS4 (segregation),
  PM1 (hotspot), PP2/BP1 (gene-level). So a Pathogenic call requires strong predictor +
  rarity; most novel missense correctly land at VUS — which is the honest ACMG reality.
"""

from __future__ import annotations

# Frequency thresholds (generic; a per-gene/disorder model is a future refinement)
_BA1 = 0.05        # stand-alone benign
_BS1 = 0.01        # strong benign (too common)
_PM2 = 0.0001      # ultra-rare / absent → moderate pathogenic

TIERS = ("Pathogenic", "Likely pathogenic", "Uncertain significance",
         "Likely benign", "Benign")


# Loss-of-function molecular consequences (ClinVar MC terms) → PVS1-eligible.
_LOF_TERMS = {
    "nonsense", "stop_gained", "frameshift_variant", "splice_donor_variant",
    "splice_acceptor_variant", "start_lost", "stop_lost", "initiator_codon_variant",
}


def _pvs1(consequence: str | None, gene_constraint: dict | None,
          established_lof_gene: bool = False) -> tuple[str, str] | None:
    """PVS1 (null variant): a LoF consequence where LoF is a disease mechanism. Very-strong
    when the gene is population-constrained (pLI≥0.9 / LOEUF<0.35) OR is an established LoF-
    disease gene (e.g. BRCA2 — late-onset tumour-suppressors have only moderate population
    constraint yet LoF is causal); strong otherwise (ClinGen-style downgrade)."""
    if not consequence:
        return None
    if not (set(t.strip() for t in consequence.lower().split(",")) & _LOF_TERMS):
        return None
    constrained = bool(gene_constraint and gene_constraint.get("lof_intolerant"))
    if constrained or established_lof_gene:
        return ("PVS1", "very_strong")
    return ("PVS1", "strong")


def _frequency_criterion(gnomad_af: float | None) -> tuple[str, str] | None:
    if gnomad_af is None:
        return ("PM2", "moderate")        # absent from gnomAD → ultra-rare
    if gnomad_af >= _BA1:
        return ("BA1", "standalone")
    if gnomad_af >= _BS1:
        return ("BS1", "strong")
    if gnomad_af < _PM2:
        return ("PM2", "moderate")
    return None                            # intermediate frequency → no criterion


def combine(criteria: list[tuple[str, str]]) -> tuple[str, str]:
    """Combine ACMG criteria → (tier, rationale) per Richards 2015 Table 5 (subset)."""
    P = {"PS": 0, "PM": 0, "PP": 0}
    B = {"BS": 0, "BP": 0}
    ba1 = False
    pvs = 0
    p_level = {"strong": "PS", "moderate": "PM", "supporting": "PP"}
    for code, strength in criteria:
        if code == "BA1":
            ba1 = True
        elif code == "PVS1":
            if strength == "very_strong":
                pvs += 1
            else:                                        # downgraded PVS1 → strong
                P["PS"] += 1
        elif code.startswith("B"):                       # BS1 / BP4
            B["BS" if strength in ("strong", "moderate") else "BP"] += 1
        elif code == "PM2":
            P["PM"] += 1
        else:                                            # PP3 (+ future PS*/PM*/PP*)
            P[p_level.get(strength, "PP")] += 1

    # --- benign side ---
    if ba1:
        return ("Benign", "BA1 stand-alone (common in population)")
    if B["BS"] >= 2:
        return ("Benign", "≥2 strong benign")
    if B["BS"] >= 1 and B["BP"] >= 1:
        return ("Likely benign", "1 strong + 1 supporting benign")
    if B["BP"] >= 2:
        return ("Likely benign", "≥2 supporting benign")
    # --- pathogenic side (PVS1 rules first) ---
    if pvs >= 1:
        if P["PS"] >= 1 or P["PM"] >= 2 or (P["PM"] >= 1 and P["PP"] >= 1) or P["PP"] >= 2:
            return ("Pathogenic", "1 PVS1 + supporting evidence")
        if P["PM"] >= 1:
            return ("Likely pathogenic", "1 PVS1 + 1 moderate")
        return ("Likely pathogenic", "1 PVS1 (LoF in a constrained gene)")
    if P["PS"] >= 2:
        return ("Pathogenic", "≥2 strong")
    if P["PS"] >= 1 and P["PM"] >= 3:
        return ("Pathogenic", "1 strong + ≥3 moderate")
    if P["PS"] >= 1 and 1 <= P["PM"] <= 2:
        return ("Likely pathogenic", "1 strong + 1-2 moderate")
    if P["PS"] >= 1 and P["PP"] >= 2:
        return ("Likely pathogenic", "1 strong + ≥2 supporting")
    if P["PM"] >= 3:
        return ("Likely pathogenic", "≥3 moderate")
    if P["PM"] >= 2 and P["PP"] >= 2:
        return ("Likely pathogenic", "2 moderate + ≥2 supporting")
    if P["PM"] >= 1 and P["PP"] >= 4:
        return ("Likely pathogenic", "1 moderate + ≥4 supporting")
    has_p = any(P.values())
    has_b = B["BS"] or B["BP"]
    if has_p and has_b:
        return ("Uncertain significance", "conflicting pathogenic + benign evidence")
    return ("Uncertain significance", "insufficient criteria to reach a call")


def classify(*, gnomad_af: float | None, am_pathogenicity: float | None = None,
             am_class: str | None = None, am_pp3_bp4: tuple[str, str] | None = None,
             consequence: str | None = None, gene_constraint: dict | None = None,
             established_lof_gene: bool = False, clinvar_sig: str | None = None) -> dict:
    """Compute an ACMG/AMP tier from the available evidence. Combines PVS1 (LoF consequence
    in a LoF-intolerant gene), PM2/BA1/BS1 (frequency), and PP3/BP4 (AlphaMissense)."""
    criteria: list[tuple[str, str]] = []
    pvs1 = _pvs1(consequence, gene_constraint, established_lof_gene)
    if pvs1:
        criteria.append(pvs1)
    freq = _frequency_criterion(gnomad_af)
    if freq:
        criteria.append(freq)
    if am_pp3_bp4:
        criteria.append(am_pp3_bp4)
    tier, rationale = combine(criteria)
    return {
        "acmg_tier": tier,
        "acmg_criteria": [f"{c}_{s}" for c, s in criteria],
        "rationale": rationale,
        "consequence": consequence,
        "clinvar_sig": clinvar_sig,
        "concordant_with_clinvar": _concordant(tier, clinvar_sig),
        "scope": "computes PVS1 (LoF+constraint) + PM2/BA1/BS1 (frequency) + PP3/BP4 (AlphaMissense). "
                 "Not computed: PS1/PS3/PP1/PM1/PM5 — need codon/functional/segregation data.",
    }


def _concordant(tier: str, clinvar_sig: str | None) -> bool | None:
    if not clinvar_sig:
        return None
    cs = clinvar_sig.lower()
    path = "pathogenic" in cs and "conflicting" not in cs
    benign = "benign" in cs
    if path:
        return tier in ("Pathogenic", "Likely pathogenic")
    if benign:
        return tier in ("Benign", "Likely benign")
    return None  # VUS / drug-response / risk-allele in ClinVar — no clean comparison
