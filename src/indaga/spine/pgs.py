"""Polygenic-score service (WS-1B.4 scaffold — depends on WS-1A genome engine).

When the open genome engine lands, it writes genomic `Fact`s (per-trait PGS
percentiles) into the Healthlake via the DNA connector. This service then passes
them through as graded circadian/metabolic/risk facts and applies the project's
percentile-correction discipline (e.g. the TOPMed-vs-chip corrections recorded in
the corrections ledger).

Until then it reports ``pending_genome_engine`` — it does NOT invent scores.
"""

from __future__ import annotations

from ..store import EvidenceGrade, FactQuery, HealthlakeStore, Scope
from .base import SpineResult


class PolygenicScores:
    name = "polygenic_scores"

    def run(self, store: HealthlakeStore, scope: Scope, **kw) -> SpineResult:
        # PGS facts (if any) are written by the genome engine under domain "genomic".
        pgs = store.get_facts(scope, FactQuery(domains=("genomic",), codes=()))
        pgs = [f for f in pgs if f.code_system == "PGS"]
        if not pgs:
            return SpineResult(self.name, state="pending_genome_engine",
                               detail={"note": "no PGS facts; awaiting genome engine (WS-1A) + DNA connector"})
        # Pass-through: the genome engine already grades/caveats these; surface a summary.
        weakest = min((f.evidence_grade for f in pgs), key=lambda g: g.rank, default=EvidenceGrade.C)
        return SpineResult(self.name, state="present", facts=tuple(pgs),
                           detail={"n_scores": len(pgs), "weakest_grade": weakest.value})
