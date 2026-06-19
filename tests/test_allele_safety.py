"""P0 — the release-blocker allele-safety contract (ClinVar⋈AGI exact ref→alt matching).

Wraps the self-contained allele_safety_eval (temp DBs, no network/reference data) and adds direct
unit assertions on the _allele_carried mapping. The mapping assertion is the contract: a sample
``A>C`` must NOT match a ClinVar ``AA>C``.
"""

from indaga.eval.allele_safety_eval import run
from indaga.evidence.store.reader import _allele_carried


def test_allele_safety_eval_passes():
    assert run() == 0


def test_indel_does_not_match_chip_snp():
    # the headline release-blocker: chip SNP A/C must NOT carry ClinVar indel AA>C
    assert _allele_carried("AA", "C", "A", "C", None, None) is False


def test_exact_chip_snv_matches():
    assert _allele_carried("A", "T", "A", "T", None, None) is True


def test_imputed_exact_match():
    assert _allele_carried("C", "G", "C", "G", "C", "G") is True


def test_imputed_alt_mismatch_rejected():
    # AGI's own alt (A) differs from ClinVar's alt (T) → not carried
    assert _allele_carried("C", "T", "C", "A", "C", "A") is False


def test_chip_genotype_not_drawn_from_ref_alt_rejected():
    # genotype G/T is not a subset of {ref A, alt G} → a different variant, reject
    assert _allele_carried("A", "G", "G", "T", None, None) is False


def test_hom_alt_chip_snv_matches():
    assert _allele_carried("A", "G", "G", "G", None, None) is True
