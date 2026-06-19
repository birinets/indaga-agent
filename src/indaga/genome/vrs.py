"""Owned, offline VRS-style allele normalization + identity — the durable allele join key.

The release-blocking bug was a position-only ClinVar join; the fix (see ``evidence/store/reader.py``
``_allele_carried`` + ``eval/allele_safety_eval``) added exact (ref,alt) matching. But two VALID
encodings of the SAME variant at one position differ byte-for-byte — a different anchor-base length, or
a repeat-region shift — so a raw string match can still MISS a true carrier. This module canonicalises an
allele so the comparison is representation-stable:

  1. **parsimonious trimming** — vt / Tan-2015 "minimal representation": trim the shared suffix, then the
     shared prefix (advancing the position). A SNV is returned unchanged, so it never loosens SNV matching.
  2. **optional left-alignment** against a reference (fully-justified) for repeat-region indels — only when
     the caller supplies a reference-base lookup (kept OUT of the position-keyed join, which is FASTA-free).
  3. a deterministic **GA4GH-style digest** (truncated SHA-512, base64url) over the normalised allele, as a
     compact stable identity / provenance key.

Honesty: this is NOT seqrepo-backed, so the id is ``indaga:VA.<digest>`` — a local VRS-STYLE identity, not
a canonical ``ga4gh:VA.`` computed over a sequence digest. The digest ALGORITHM mirrors GA4GH (sha512t24,
base64url) so it is stable and collision-resistant. stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable

RefBase = Callable[[str, int], "str | None"]  # (chrom, 1-based pos) -> base, or None if unavailable


def trim_alleles(pos: int, ref: str | None, alt: str | None) -> tuple[int, str, str]:
    """Minimal representation (vt / Tan-2015): trim the shared suffix, then the shared prefix (each
    trimmed prefix base advances ``pos``). May yield an empty ref or alt (a pure deletion/insertion).
    A SNV is returned unchanged. Inputs are upper-cased."""
    ref = (ref or "").upper()
    alt = (alt or "").upper()
    pos = int(pos)
    while ref and alt and ref[-1] == alt[-1]:        # shared suffix
        ref, alt = ref[:-1], alt[:-1]
    while ref and alt and ref[0] == alt[0]:          # shared prefix (advances the position)
        ref, alt, pos = ref[1:], alt[1:], pos + 1
    return pos, ref, alt


def left_align(chrom: str, pos: int, ref: str | None, alt: str | None,
               ref_base: RefBase) -> tuple[int, str, str]:
    """Fully-justified (left-shifted) normalisation of a pure indel against a reference. ``ref_base``
    returns the 1-based reference base at (chrom, pos), or None if unavailable. Non-indels (SNV/MNV —
    both ref and alt non-empty after trimming) are returned trimmed but un-shifted."""
    p, r, a = trim_alleles(pos, ref, alt)
    if (r and a) or (not r and not a):               # SNV/MNV, or empty — left-alignment N/A
        return p, r, a
    indel = r or a                                   # the deleted (r) or inserted (a) sequence
    while p > 1:                                      # roll left over a repeat
        prev = ref_base(chrom, p - 1)
        if not prev or prev.upper() != indel[-1]:
            break
        indel = prev.upper() + indel[:-1]
        p -= 1
    return (p, indel, "") if r else (p, "", indel)


def normalize(chrom: str, pos: int, ref: str | None, alt: str | None, *,
              ref_base: RefBase | None = None) -> tuple[str, int, str, str]:
    """Canonical (chrom, pos, ref, alt): minimal representation, plus left-alignment when a reference
    base lookup is supplied. ``chrom`` is normalised to its bare form ('chr1' → '1')."""
    c = chrom[3:] if isinstance(chrom, str) and chrom.lower().startswith("chr") else chrom
    p, r, a = (left_align(c, pos, ref, alt, ref_base) if ref_base is not None
               else trim_alleles(pos, ref, alt))
    return c, p, r, a


def same_allele(ref1: str | None, alt1: str | None, ref2: str | None, alt2: str | None) -> bool:
    """True iff two (ref,alt) encodings at the SAME position are the same variant under minimal
    representation. Position-free (the caller has already position-joined): only the trim OFFSET and the
    trimmed (ref,alt) must agree, so different anchor lengths at one locus collapse to one identity. A
    SNV comparison is exact (trim is identity), so this never loosens SNV matching."""
    if ref1 is None or alt1 is None or ref2 is None or alt2 is None:
        return False
    return trim_alleles(0, ref1, alt1) == trim_alleles(0, ref2, alt2)


def allele_id(build: str, chrom: str, pos: int, ref: str | None, alt: str | None, *,
              ref_base: RefBase | None = None) -> str:
    """A deterministic, representation-stable allele identity (``indaga:VA.<digest>``) over the
    normalised allele. The digest is GA4GH-style: base64url(sha512(serialised)[:24])."""
    c, p, r, a = normalize(chrom, pos, ref, alt, ref_base=ref_base)
    blob = f"{build}\t{c}\t{p}\t{r}\t{a}".encode()
    digest = base64.urlsafe_b64encode(hashlib.sha512(blob).digest()[:24]).decode().rstrip("=")
    return f"indaga:VA.{digest}"
