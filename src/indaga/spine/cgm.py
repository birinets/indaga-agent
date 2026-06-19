"""CGM metabolic service (WS-1B.4 scaffold).

Computes glycemic summaries (estimated GMI, time-in-range) from a ``glucose_mgdl``
time series and writes them back as derived `Fact`s. It is a *real* service —
it just needs the per-reading series, which currently arrives via the Apple Health
export path (``glucose.json`` carries only session summaries). Until points are
present it reports ``awaiting_series`` honestly rather than fabricating a value.

GMI%% = 3.31 + 0.02392 × mean glucose(mg/dL)  (Bergenstal et al. 2018).
"""

from __future__ import annotations

from ..store import (
    Caveat,
    CaveatCode,
    EvidenceGrade,
    Fact,
    HealthlakeStore,
    Provenance,
    Scope,
    Severity,
)
from .base import SpineResult, write_back

GLUCOSE_METRIC = "glucose_mgdl"
TIR_LOW, TIR_HIGH = 70.0, 180.0


def _gmi_percent(mean_mgdl: float) -> float:
    return 3.31 + 0.02392 * mean_mgdl


class CGMMetabolic:
    name = "cgm_metabolic"

    def run(self, store: HealthlakeStore, scope: Scope, **kw) -> SpineResult:
        ts = store.get_timeseries(scope, GLUCOSE_METRIC)
        if ts.n == 0:
            return SpineResult(self.name, state="awaiting_series",
                               detail={"note": "no glucose_mgdl points; ingest via the export path"})

        vals = [p.value for p in ts.points]
        mean = sum(vals) / len(vals)
        gmi = _gmi_percent(mean)
        tir = 100.0 * sum(TIR_LOW <= v <= TIR_HIGH for v in vals) / len(vals)
        days = len({p.t.date() for p in ts.points})
        grade = EvidenceGrade.B if days >= 14 else EvidenceGrade.C
        caveats = () if days >= 14 else (
            Caveat(CaveatCode.SINGLE_DATAPOINT, f"Only {days} days of CGM wear; GMI is provisional.", Severity.WARN),
        )

        fid = f"derived_gmi_{scope.subject_id}"
        fact = Fact(
            fact_id=fid, subject_id=scope.subject_id, domain="metabolic",
            name="gmi_estimate", display="Glucose Management Indicator (est.)",
            value_number=round(gmi, 2), unit="%", code_system="indaga", code="gmi_estimate",
            evidence_grade=grade, caveats=caveats, provenance_id=f"prov_{fid}",
            attributes={"mean_glucose_mgdl": round(mean, 1), "tir_70_180_pct": round(tir, 1),
                        "n_readings": ts.n, "days": days},
        )
        prov = Provenance(f"prov_{fid}", fid, "derived", None, "cgm:dexcom",
                          "pipeline/healthlake/spine/cgm.py",
                          f"GMI=3.31+0.02392*mean; mean={mean:.1f} n={ts.n} days={days}",
                          "spine:cgm_metabolic", None, "computed")
        result = SpineResult(self.name, state="computed", facts=(fact,), provenance=(prov,),
                             detail={"gmi": round(gmi, 2), "tir": round(tir, 1), "days": days})
        write_back(store, scope, result)
        return result
