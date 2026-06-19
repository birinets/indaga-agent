"""In-silico pathogenicity predictors (Phase B) — owned reference libraries.

The predicted-impact evidence that ClinVar/gnomAD lookups don't provide, and the input
the ACMG/AMP classifier (Phase C) needs for the PP3 (supports pathogenic) / BP4 (supports
benign) criteria. v1 ships AlphaMissense (state-of-art missense pathogenicity, DeepMind);
REVEL/CADD/SpliceAI are registered for later.

AlphaMissense covers every possible missense substitution genome-wide (~71M), so it's
queried by genomic position via a tabix index (pysam) rather than loaded into memory.
GRCh38 only (matches the imputed genome). stdlib + pysam.
"""

from __future__ import annotations

from ..reference import manager as refmgr

# ClinGen-style strength bands for AlphaMissense pathogenicity (am_pathogenicity ∈ [0,1]).
# Conservative; used to set PP3 / BP4 strength in the ACMG engine.
_AM_PP3_STRONG = 0.99
_AM_PP3_MODERATE = 0.95
_AM_BP4_STRONG = 0.05
_AM_BP4_MODERATE = 0.10


class AlphaMissense:
    """Position-keyed AlphaMissense reader (tabix). Returns missense pathogenicity + class."""

    def __init__(self, bgz_path: str) -> None:
        import pysam
        self._tb = pysam.TabixFile(bgz_path)

    @classmethod
    def open(cls) -> "AlphaMissense | None":
        bgz = refmgr.ensure_alphamissense()
        if bgz is None:
            return None
        try:
            return cls(str(bgz))
        except Exception:  # noqa: BLE001 — missing index / pysam issue
            return None

    def lookup(self, chrom: str, pos: int, ref: str, alt: str) -> dict | None:
        """{am_pathogenicity, am_class, protein_variant} for a missense SNV, or None
        (not a missense / not covered). chrom may be bare ('1') or 'chr1'."""
        c = str(chrom)
        c = c if c.startswith("chr") else f"chr{c}"
        try:
            for row in self._tb.fetch(c, int(pos) - 1, int(pos)):
                f = row.split("\t")
                if len(f) >= 10 and f[2] == ref and f[3] == alt:
                    return {"am_pathogenicity": float(f[8]), "am_class": f[9],
                            "protein_variant": f[7]}
        except (ValueError, OSError):
            return None
        return None

    @staticmethod
    def pp3_bp4(am_pathogenicity: float | None, am_class: str | None) -> tuple[str, str] | None:
        """Map an AlphaMissense score to an ACMG (criterion, strength) — PP3 (pathogenic-
        supporting) or BP4 (benign-supporting), at Supporting/Moderate/Strong. None if ambiguous."""
        if am_pathogenicity is None:
            return None
        if am_class == "likely_pathogenic":
            if am_pathogenicity >= _AM_PP3_STRONG:
                return ("PP3", "strong")
            if am_pathogenicity >= _AM_PP3_MODERATE:
                return ("PP3", "moderate")
            return ("PP3", "supporting")
        if am_class == "likely_benign":
            if am_pathogenicity <= _AM_BP4_STRONG:
                return ("BP4", "strong")
            if am_pathogenicity <= _AM_BP4_MODERATE:
                return ("BP4", "moderate")
            return ("BP4", "supporting")
        return None  # ambiguous

    def close(self) -> None:
        self._tb.close()


class Revel:
    """Position-keyed REVEL reader (tabix). A second, independent ensemble missense score —
    used for concordance with AlphaMissense, and as a PP3/BP4 fallback for the (rare) missense
    AlphaMissense doesn't cover. Thresholds are the ClinGen/Pejaver-2022 calibration."""

    # Pejaver et al. 2022 calibrated REVEL → ACMG strength
    _PP3_STRONG, _PP3_MOD, _PP3_SUP = 0.932, 0.773, 0.644
    _BP4_SUP, _BP4_MOD, _BP4_STRONG = 0.290, 0.183, 0.016

    def __init__(self, bgz_path: str) -> None:
        import pysam
        self._tb = pysam.TabixFile(bgz_path)

    @classmethod
    def open(cls) -> "Revel | None":
        bgz = refmgr.ensure_revel()
        if bgz is None:
            return None
        try:
            return cls(str(bgz))
        except Exception:  # noqa: BLE001
            return None

    def lookup(self, chrom: str, pos: int, ref: str, alt: str) -> float | None:
        """REVEL score ∈ [0,1] for a missense SNV, or None. chrom bare or 'chr…' (REVEL is bare)."""
        c = str(chrom)
        c = c[3:] if c.startswith("chr") else c
        try:
            for row in self._tb.fetch(c, int(pos) - 1, int(pos)):
                f = row.split("\t")
                if len(f) >= 5 and f[2] == ref and f[3] == alt:
                    try:
                        return float(f[4])
                    except ValueError:
                        return None
        except (ValueError, OSError):
            return None
        return None

    @classmethod
    def pp3_bp4(cls, score: float | None) -> tuple[str, str] | None:
        if score is None:
            return None
        if score >= cls._PP3_STRONG:
            return ("PP3", "strong")
        if score >= cls._PP3_MOD:
            return ("PP3", "moderate")
        if score >= cls._PP3_SUP:
            return ("PP3", "supporting")
        if score <= cls._BP4_STRONG:
            return ("BP4", "strong")
        if score <= cls._BP4_MOD:
            return ("BP4", "moderate")
        if score <= cls._BP4_SUP:
            return ("BP4", "supporting")
        return None  # intermediate → no criterion

    def close(self) -> None:
        self._tb.close()
