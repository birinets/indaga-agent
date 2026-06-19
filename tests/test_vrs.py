"""VRS-style allele normalization + identity (owned, offline) — the durable allele join key."""

from indaga.genome import vrs


# --- parsimonious trimming (minimal representation) ------------------------- #

def test_snv_is_unchanged():
    assert vrs.trim_alleles(100, "A", "T") == (100, "A", "T")


def test_trim_shared_suffix_then_prefix_deletion():
    # AGG>AG and AG>A are the SAME single-base deletion → identical minimal form
    assert vrs.trim_alleles(100, "AGG", "AG") == vrs.trim_alleles(100, "AG", "A")
    assert vrs.trim_alleles(100, "AG", "A") == (101, "G", "")


def test_trim_insertion():
    # CA>CAA is an insertion of A; minimal form drops the shared anchor
    assert vrs.trim_alleles(100, "CA", "CAA") == (101, "", "A")


def test_trim_mnv_keeps_both_sides():
    # AGT>ACT is a single SNV embedded in shared flanks → G>C at the middle position
    assert vrs.trim_alleles(100, "AGT", "ACT") == (101, "G", "C")


def test_trim_uppercases():
    assert vrs.trim_alleles(5, "ag", "a") == (6, "G", "")


# --- same_allele: representation-stable identity at one position ------------- #

def test_same_allele_snv_exact():
    assert vrs.same_allele("A", "G", "A", "G") is True
    assert vrs.same_allele("A", "G", "A", "T") is False  # different SNV — never collapses


def test_same_allele_indel_different_anchor_matches():
    # ClinVar 'CA>C' vs an imputed 'CAA>CA' at the same locus = the same deletion
    assert vrs.same_allele("CAA", "CA", "CA", "C") is True


def test_same_allele_different_indel_rejected():
    # a deletion of A vs a deletion of T at the same locus are NOT the same variant
    assert vrs.same_allele("CT", "C", "CA", "C") is False


def test_same_allele_none_is_false():
    assert vrs.same_allele(None, "G", "A", "G") is False


# --- left-alignment against a reference ------------------------------------- #

def test_left_align_shifts_indel_in_a_repeat():
    # reference ...A A A A A... ; a deletion of one A should left-shift to the run's start
    seq = {2: "A", 3: "A", 4: "A", 5: "A", 6: "A"}

    def ref_base(_chrom, p):
        return seq.get(p)

    # an 'AA>A' deletion encoded at pos 5 left-aligns to the first A of the run (pos 2/3 boundary)
    p, r, a = vrs.left_align("1", 5, "AA", "A", ref_base)
    assert a == "" and r == "A" and p < 5  # shifted left


def test_left_align_snv_unchanged():
    assert vrs.left_align("1", 100, "A", "T", lambda c, p: "G") == (100, "A", "T")


# --- allele identity digest ------------------------------------------------- #

def test_allele_id_is_stable_and_representation_invariant():
    a = vrs.allele_id("GRCh38", "chr1", 100, "AG", "A")
    b = vrs.allele_id("GRCh38", "1", 100, "AGG", "AG")  # same deletion, different anchor + chr-prefix
    assert a == b and a.startswith("indaga:VA.")


def test_allele_id_distinguishes_different_variants():
    assert vrs.allele_id("GRCh38", "1", 100, "A", "G") != vrs.allele_id("GRCh38", "1", 100, "A", "T")


def test_allele_id_build_namespaced():
    assert vrs.allele_id("GRCh37", "1", 100, "A", "G") != vrs.allele_id("GRCh38", "1", 100, "A", "G")
