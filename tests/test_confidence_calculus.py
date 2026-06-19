"""P2 Layer-B — the confidence calculus grades P/LP findings so only directly-typed, well-reviewed
findings are decision-grade; common/imputed ones are explicitly below claim-grade."""

from indaga.evidence.confidence_calculus import grade_pl_finding
from indaga.store import CaveatCode, EvidenceGrade


def _grade(**finding):
    return grade_pl_finding(finding)


def test_common_refuted_is_below_claim_grade():
    grade, caveats = _grade(classification="common_likely_false_alarm", directly_typed=True, review_stars=3)
    assert grade is EvidenceGrade.D
    assert not grade.meets(EvidenceGrade.C)  # not claim-grade
    assert any(c.code is CaveatCode.REFUTED for c in caveats)


def test_directly_typed_strong_review_is_decision_grade():
    grade, _ = _grade(classification="confirmed_rare", directly_typed=True, review_stars=3,
                      confidence="directly_typed")
    assert grade is EvidenceGrade.B
    assert grade.meets(EvidenceGrade.C)


def test_directly_typed_weak_review_is_scoped_c():
    grade, caveats = _grade(classification="confirmed_rare", directly_typed=True, review_stars=1,
                            confidence="directly_typed_low_review")
    assert grade is EvidenceGrade.C
    assert any(c.code is CaveatCode.LOW_CONFIDENCE for c in caveats)


def test_imputed_unconfirmed_is_below_claim_grade():
    grade, caveats = _grade(classification="not_in_gnomad", directly_typed=False,
                            confidence="imputed_unconfirmed")
    assert grade is EvidenceGrade.D
    assert not grade.meets(EvidenceGrade.C)
    codes = {c.code for c in caveats}
    assert CaveatCode.IMPUTED in codes and CaveatCode.LOW_IMPUTATION_QUALITY in codes


def test_imputed_known_is_c_with_imputed_caveat():
    grade, caveats = _grade(classification="confirmed_rare", directly_typed=False, confidence="imputed")
    assert grade is EvidenceGrade.C
    assert any(c.code is CaveatCode.IMPUTED for c in caveats)


def test_low_dr2_downgrades_imputed_to_d():
    # an explicit low DR2 marks even an otherwise-OK imputed finding as a likely artifact
    grade, caveats = grade_pl_finding(
        {"classification": "confirmed_rare", "directly_typed": False, "confidence": "imputed"}, dr2=0.1)
    assert grade is EvidenceGrade.D
    assert any(c.code is CaveatCode.LOW_IMPUTATION_QUALITY for c in caveats)
