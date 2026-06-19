"""Deterministic spine (WS-1B.4).

Deterministic services that read inputs from the Healthlake through the port and
write derived `Fact`s (graded, caveat-wrapped, provenance-stamped) back. The
science is computed here and is right or wrong independent of any model — the LLM
synthesizes the derived facts, it never adjudicates them.

  * BiologicalClock  — 24-h cosinor HR nadir + the 14-night state machine (live).
  * CGMMetabolic     — estimated GMI / time-in-range from a glucose series (live
                       once per-reading points are ingested).
  * PolygenicScores  — pass-through of PGS facts (pending the WS-1A genome engine).
"""

from __future__ import annotations

from .base import SpineResult, SpineService, write_back
from .biological_clock import BiologicalClock, ClockState, compute_clock
from .cgm import CGMMetabolic
from .pgs import PolygenicScores

__all__ = [
    "SpineService",
    "SpineResult",
    "write_back",
    "BiologicalClock",
    "ClockState",
    "compute_clock",
    "CGMMetabolic",
    "PolygenicScores",
]
