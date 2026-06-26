"""Ask — conversational query, routed to real ops and answered at EXACTLY the envelope's strength.

Deterministic floor (shipped + verifiable): keyword routing → one indaga op → an envelope-honest
summary (a never-measured analyte returns "unknown, not normal", a calibrating metric returns progress,
never a value). The LLM narration pass (Claude) is a documented upgrade that may re-word the summary and
chain multiple ops, but it must keep the answer within the envelope and footnote its sources — it never
upgrades confidence. Because the floor honors the contract, Ask is correct with or without the model.
"""

from __future__ import annotations

_CLOCK_KW = ("biological midnight", "midnight", "body clock", "circadian", "chronotype", "nadir", "clock")
_CGM_KW = ("glucose", "sugar", "cgm", "glycemic", "glycaemic", "blood sugar")
_COVERAGE_KW = ("what labs", "which labs", "missing", "never measured", "not measured", "coverage", "panel", "gaps")
_DECISION_KW = ("what should i do", "what do i do", "my decision", "today's action", "highest-leverage", "one thing")
# specific analytes the user may name (keyword → canonical analyte)
_ANALYTES = {
    "ldl": "ldl_cholesterol", "cholesterol": "ldl_cholesterol", "apob": "apob", "apo b": "apob",
    "hba1c": "hba1c", "a1c": "hba1c", "hdl": "hdl_cholesterol", "triglyceride": "triglycerides",
    "alt": "alt", "ast": "ast", "crp": "crp", "ferritin": "ferritin", "tsh": "tsh",
}


def route(question: str) -> tuple[str, dict]:
    """Map a free-text question to one op + params. Order matters: coverage/analyte before generic CGM."""
    q = question.lower()
    if any(k in q for k in _CLOCK_KW):
        return "clock.state", {}
    if any(k in q for k in _COVERAGE_KW):
        return "labs.panel_coverage", {}
    for kw, analyte in _ANALYTES.items():
        if kw in q:
            return "labs.query", {"analyte": analyte}
    if any(k in q for k in _CGM_KW):
        return "cgm.glycemic_summary", {}
    if any(k in q for k in _DECISION_KW):
        return "decision.today", {}
    return "context_pack.get", {}


def summarize(op: str, result: dict) -> str:
    """A grounded, envelope-honest sentence. The envelope governs what may be said."""
    env = result.get("evidence_envelope", {})
    fs = env.get("finding_state")
    obs = env.get("observations") or {}

    # panel coverage answers with the actual present/missing lists (its envelope is not_measured, but
    # the useful answer is the gap list, not the generic line).
    if op == "labs.panel_coverage":
        missing = result.get("missing") or []
        present = result.get("present") or []
        if missing:
            shown = ", ".join(missing[:6])
            return (f"You're missing {len(missing)} of the standard panel — {shown}"
                    f"{' …' if len(missing) > 6 else ''}. Each is unknown until measured, not assumed normal. "
                    f"You do have {len(present)} measured.")
        return f"Your standard panel looks complete — {len(present)} analytes measured."

    if fs == "not_measured":
        what = obs.get("not_measured") or result.get("analyte") or "that"
        return f"{what} isn't measured for you — so it's unknown, not normal. The honest next step is to measure it."
    if fs == "index_incomplete":
        n = obs.get("valid_nights")
        prog = f" ({n}/14 nights)" if n is not None else ""
        return f"That's still calibrating{prog} — I won't quote a value until it's ready."
    if fs == "not_observed_in_consulted_scope":
        return "Nothing turned up in what I looked at — but that's an empty scope, not a clinical negative."

    # evidence_present → state it, per op
    if op == "clock.state":
        return (f"Your Biological Midnight is {result.get('biological_midnight')} "
                f"(from {result.get('valid_nights')} nights of heart-rate data).")
    if op == "labs.query":
        facts = result.get("facts") or []
        if facts:
            f = facts[0]
            unit = f.get("unit") or ""
            interp = f.get("interpretation")
            tail = f" ({interp})" if interp else ""
            return f"Your {f.get('display') or result.get('analyte')} is {f.get('value_number')} {unit}{tail}.".replace("  ", " ")
    if op == "decision.today":
        dec = result.get("decision") or {}
        return dec.get("supporting") or "Here's today's highest-leverage action."
    if op == "cgm.glycemic_summary":
        return "Here's your glycemic summary within the data I have."
    return "Here's what your Healthlake shows on that."
