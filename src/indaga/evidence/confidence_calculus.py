"""The confidence calculus — source quality → EvidenceGrade + caveats.

The deterministic bridge between *how a finding was observed* (directly-typed vs imputed, ClinVar
review strength, gnomAD refutation) and the graded `Fact` the honesty envelope consumes. The
architecture review's #1 deeper finding was that the P/LP screen emits raw dicts that NEVER become
graded Facts — so the highest-stakes genome findings bypass the Fact/`derive_envelope` contract and
the synthesis layer can't ground on them honestly. This module is where that grading lives.

Grading (so only a directly-typed, well-reviewed finding is decision-grade; an imputed or
population-common one is explicitly below claim-grade):

  common_likely_false_alarm            → D + REFUTED                 (common variant; not a real risk)
  directly-typed, ClinVar review ≥2★   → B                          (decision-grade)
  directly-typed, weak review (<2★)    → C + LOW_CONFIDENCE          (confirm before acting)
  imputed, not in gnomAD / api error   → D + IMPUTED + LOW_IMPUTATION_QUALITY  (likely artifact)
  imputed, otherwise                   → C + IMPUTED                 (real but inferred)

`EvidenceGrade.is_claim_grade` is "≥ C and no blocking caveat", so the D-graded findings are below
claim-grade — they appear, but cannot on their own ground a decision-grade claim. Pure + deterministic
(no wall-clock / RNG), matching the spine contract.
"""

from __future__ import annotations

from ..store import Caveat, CaveatCode, EvidenceGrade, Severity

# imputation-quality (DR2) thresholds, kept here so the calculus owns the confidence policy.
DR2_LOW = 0.8  # below this, an imputed call is low-confidence at a clinical position


def grade_pl_finding(finding: dict, *, dr2: float | None = None) -> tuple[EvidenceGrade, tuple[Caveat, ...]]:
    """Grade one P/LP screen finding. ``dr2`` (imputation R², when known) sharpens the imputed case;
    absent, the screen's own directly_typed / classification / review_stars signals are used."""
    classification = finding.get("classification")
    confidence = finding.get("confidence")
    directly_typed = bool(finding.get("directly_typed"))
    stars = finding.get("review_stars") or 0
    caveats: list[Caveat] = []

    # population-common "pathogenic" call → refuted, not decision-grade (regardless of typing).
    if classification == "common_likely_false_alarm":
        caveats.append(Caveat(
            CaveatCode.REFUTED,
            "Common in the population (high gnomAD allele frequency) — a likely false-positive "
            "'pathogenic' call, not a real high-penetrance risk.", Severity.WARN))
        return EvidenceGrade.D, tuple(caveats)

    if not directly_typed:
        caveats.append(Caveat(
            CaveatCode.IMPUTED,
            "Genotype is imputed (statistically inferred from the reference panel), not directly "
            "typed — probabilistic; confirm a high-stakes call with a targeted assay.", Severity.INFO))
        low_dr2 = dr2 is not None and dr2 < DR2_LOW
        if low_dr2 or classification in ("not_in_gnomad", "api_error") or confidence == "imputed_unconfirmed":
            caveats.append(Caveat(
                CaveatCode.LOW_IMPUTATION_QUALITY,
                "Imputed and unconfirmed (low DR2 or absent from gnomAD) — likely an imputation "
                "artifact; needs orthogonal confirmation (e.g. Sanger) before acting.", Severity.WARN))
            return EvidenceGrade.D, tuple(caveats)
        return EvidenceGrade.C, tuple(caveats)

    # directly typed: strength gated by ClinVar review status.
    if stars >= 2:
        return EvidenceGrade.B, tuple(caveats)
    caveats.append(Caveat(
        CaveatCode.LOW_CONFIDENCE,
        "Directly typed but weak ClinVar review (<2★ / single submitter) — confirm before acting.",
        Severity.WARN))
    return EvidenceGrade.C, tuple(caveats)
