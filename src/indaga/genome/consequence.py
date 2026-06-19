"""Molecular-consequence annotator — a lightweight, owned VEP for the variants ClinVar
doesn't carry, so the ACMG engine can compute PVS1 (null variant) on NOVEL findings.

Given a variant (chrom, pos, ref, alt) and the MANE Select transcript model + GRCh38 FASTA,
it returns an SO-style consequence term:
  • CDS SNV  → translate the reference codon and the alt codon → stop_gained / stop_lost /
    start_lost / missense_variant / synonymous_variant
  • CDS indel→ frameshift_variant (length % 3 ≠ 0) or inframe_indel
  • exon-boundary ±1/2 (intron side) → splice_donor_variant / splice_acceptor_variant
  • otherwise → intron_variant / UTR / None (no coding transcript here)

The LoF terms it emits match ``acmg._LOF_TERMS``, so PVS1 fires for novel nonsense/
frameshift/splice variants in constrained or established-LoF genes — the differentiator
(Genomi/OpenCRAVAT only look ClinVar up; they can't classify a variant ClinVar lacks).
Strand-aware; codons spanning an exon junction are handled by walking the CDS. pysam + stdlib.
"""

from __future__ import annotations

from ..reference import manager as refmgr
from .genemodel import GeneModel

_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C", "N": "N"}
_CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L", "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M", "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S", "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T", "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*", "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K", "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W", "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R", "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def _revcomp(s: str) -> str:
    return "".join(_COMPLEMENT.get(b, "N") for b in reversed(s))


def _coding_index(cds: list[tuple[int, int]], strand: str, pos: int) -> int | None:
    """0-based index of a genomic position within the concatenated CDS, in translation order."""
    if strand == "+":
        before = 0
        for s, e in cds:                      # cds is sorted ascending
            if s <= pos <= e:
                return before + (pos - s)
            before += e - s + 1
    else:
        before = 0
        for s, e in reversed(cds):            # translation runs high→low coord
            if s <= pos <= e:
                return before + (e - pos)
            before += e - s + 1
    return None


def _genomic_at(cds: list[tuple[int, int]], strand: str, idx: int) -> int | None:
    """Genomic position of a coding index (inverse of _coding_index)."""
    if strand == "+":
        before = 0
        for s, e in cds:
            length = e - s + 1
            if idx < before + length:
                return s + (idx - before)
            before += length
    else:
        before = 0
        for s, e in reversed(cds):
            length = e - s + 1
            if idx < before + length:
                return e - (idx - before)
            before += length
    return None


class ConsequenceAnnotator:
    def __init__(self, gm: GeneModel, fasta) -> None:
        self._gm = gm
        self._fa = fasta

    @classmethod
    def open(cls) -> "ConsequenceAnnotator | None":
        gm = GeneModel.open()
        if gm is None:
            return None
        fa_path = refmgr.ensure_reference_fasta()
        if fa_path is None:
            gm.close()
            return None
        try:
            import pysam
            fa = pysam.FastaFile(str(fa_path))
        except Exception:  # noqa: BLE001
            gm.close()
            return None
        return cls(gm, fa)

    def _base(self, chrom: str, pos: int) -> str:
        c = chrom if str(chrom).startswith("chr") else f"chr{chrom}"
        try:
            return (self._fa.fetch(c, pos - 1, pos) or "N").upper()
        except (KeyError, ValueError):
            return "N"

    def _codon(self, cds, strand, codon_start_idx: int, chrom: str) -> str:
        bases = []
        for k in range(3):
            g = _genomic_at(cds, strand, codon_start_idx + k)
            if g is None:
                return ""
            b = self._base(chrom, g)
            bases.append(_COMPLEMENT.get(b, "N") if strand == "-" else b)
        return "".join(bases)

    def _splice(self, exons: list[tuple[int, int]], strand: str, pos: int) -> str | None:
        """Canonical splice dinucleotide hit? ±1/2 into an intron from an exon boundary."""
        ex = sorted(exons)
        for i in range(len(ex) - 1):
            intron_s, intron_e = ex[i][1] + 1, ex[i + 1][0] - 1
            if intron_e < intron_s:
                continue
            left = intron_s <= pos <= intron_s + 1          # 5' dinucleotide of the intron
            right = intron_e - 1 <= pos <= intron_e          # 3' dinucleotide of the intron
            if left or right:
                # + strand: intron 5'=donor, 3'=acceptor;  - strand: reversed
                donor = left if strand == "+" else right
                return "splice_donor_variant" if donor else "splice_acceptor_variant"
        return None

    def annotate(self, chrom: str, pos: int, ref: str, alt: str) -> dict | None:
        """{consequence, gene, transcript_id, protein} for a variant, or None if no MANE
        coding transcript spans it. ``consequence`` uses SO terms (LoF ones match acmg)."""
        t = self._gm.transcript_at(chrom, pos)
        if t is None:
            return None
        cds, exons, strand = t["cds"], t["exons"], t["strand"]
        # an indel's reference span is pos..pos+len(ref)-1; check CDS OVERLAP, not just the
        # anchor base (a deletion's anchor can sit just outside the CDS it removes).
        v_lo, v_hi = pos, pos + len(ref) - 1
        in_cds = any(not (v_hi < s or v_lo > e) for s, e in cds)
        is_snv = len(ref) == 1 and len(alt) == 1 and ref != alt
        base = {"gene": t["gene"], "transcript_id": t["transcript_id"], "protein": None}

        if in_cds:
            if not is_snv:
                cons = "frameshift_variant" if (len(alt) - len(ref)) % 3 != 0 else "inframe_indel"
                return {**base, "consequence": cons}
            idx = _coding_index(cds, strand, pos)
            if idx is None:
                return {**base, "consequence": "coding_variant"}
            codon_start = (idx // 3) * 3
            ref_codon = self._codon(cds, strand, codon_start, t["chrom"])
            if len(ref_codon) != 3:
                return {**base, "consequence": "coding_variant"}
            off = idx - codon_start
            alt_base = _COMPLEMENT.get(alt, "N") if strand == "-" else alt
            alt_codon = ref_codon[:off] + alt_base + ref_codon[off + 1:]
            ref_aa = _CODON_TABLE.get(ref_codon, "X")
            alt_aa = _CODON_TABLE.get(alt_codon, "X")
            protein = f"p.{ref_aa}{idx // 3 + 1}{alt_aa}"
            if ref_aa == alt_aa:
                cons = "synonymous_variant"
            elif alt_aa == "*":
                cons = "stop_gained"
            elif ref_aa == "*":
                cons = "stop_lost"
            elif idx < 3:                        # first codon (Met) altered
                cons = "start_lost"
            else:
                cons = "missense_variant"
            return {**base, "consequence": cons, "protein": protein}

        # not in CDS: canonical splice site? else exonic-UTR / intron
        sp = self._splice(exons, strand, pos)
        if sp:
            return {**base, "consequence": sp}
        in_exon = any(s <= pos <= e for s, e in exons)
        return {**base, "consequence": "exon_noncoding_variant" if in_exon else "intron_variant"}

    def close(self) -> None:
        self._gm.close()
        try:
            self._fa.close()
        except Exception:  # noqa: BLE001
            pass


def consequence_for(chrom: str, pos: int, ref: str, alt: str) -> str | None:
    """Convenience one-shot: the SO consequence term (or None). Opens/closes the annotator —
    for many variants, open a ConsequenceAnnotator once and reuse it."""
    ann = ConsequenceAnnotator.open()
    if ann is None:
        return None
    try:
        r = ann.annotate(chrom, pos, ref, alt)
        return r["consequence"] if r else None
    finally:
        ann.close()
