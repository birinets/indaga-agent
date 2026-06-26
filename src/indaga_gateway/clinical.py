"""Clinical-handoff workflows — compose existing engine ops into a clinician-ready packet.

"Visit Prep" mirrors the workflow Welna leads with, but adds the angle Welna structurally can't: the
**pharmacogenomic** medication flags from the user's own genome (PharmCAT diplotypes), plus the honest
PGx blind-spots (genes that can't be called). Everything is decision-support, not diagnosis, and every
section keeps its evidence envelope so the clinician sees how strong each item is.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .phrasing import phrase_decision

_ABNORMAL = {"high", "low", "abnormal", "critical", "elevated", "positive"}


def _is_actionable_pgx(phenotype: str | None) -> bool:
    """Flag any diplotype whose phenotype isn't plainly normal — worth a clinician's eye."""
    if not phenotype:
        return False
    return "normal" not in phenotype.lower()


def visit_prep(pool, subject: str) -> dict:
    """A clinician-ready summary: today's action, what's worth raising, gaps to order, and
    genome-derived medication flags. Composes decision.today + analyze.report + labs.panel_coverage
    + pgx.summary; envelopes pass through verbatim."""
    decision = pool.dispatch(subject, "decision.today")
    report = pool.dispatch(subject, "analyze.report")
    coverage = pool.dispatch(subject, "labs.panel_coverage")
    labs = pool.dispatch(subject, "facts.query", {"domains": ["lab"]})
    try:
        pgx = pool.dispatch(subject, "pgx.summary")
    except Exception:
        pgx = {}

    raise_with_doctor: list[dict] = []
    # 1) measured labs flagged out-of-range (the LDL / ALT story) — these are evidence_present facts
    for f in (labs.get("facts") or []):
        interp = (f.get("interpretation") or "").lower()
        if interp in _ABNORMAL:
            unit = f.get("unit") or ""
            raise_with_doctor.append({
                "source": "lab", "area": f.get("display") or f.get("name"), "tier": "watch",
                "detail": f"{f.get('value_number')} {unit} ({interp})".replace("  ", " ").strip(),
                "observed_at": f.get("observed_at"),
            })
    # 2) genome/report sections graded alert/watch (carry their own envelope)
    for s in report.get("sections", []):
        if s.get("tier") in ("alert", "watch"):
            raise_with_doctor.append({
                "source": "genome_report", "area": s.get("title") or s.get("key"),
                "tier": s.get("tier"), "detail": s.get("summary"),
                "evidence_envelope": s.get("evidence_envelope"),
            })

    # genome medication flags = non-normal PharmCAT phenotypes (the Indaga-only angle)
    med_flags = [
        {"gene": d.get("gene"), "phenotype": d.get("phenotype"),
         "function": d.get("function"), "coverage": d.get("coverage")}
        for d in (pgx.get("diplotypes") or [])
        if _is_actionable_pgx(d.get("phenotype"))
    ]

    dec = decision.get("decision", {})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "todays_decision": {
            "text": phrase_decision(dec) if dec.get("action_template") else None,
            "evidence_envelope": decision.get("evidence_envelope"),
        },
        "raise_with_doctor": raise_with_doctor,
        "labs_to_consider_ordering": coverage.get("missing", []),
        "pharmacogenomic_flags": med_flags,
        "pgx_blind_spots": pgx.get("blind_spots", []),
        "disclaimer": ("Decision-support, not a diagnosis. Bring this to your clinician — medical "
                       "decisions are theirs. Pharmacogenomic flags are genome-derived and may need "
                       "confirmatory testing."),
        "evidence_envelope": decision.get("evidence_envelope", {}),
    }
