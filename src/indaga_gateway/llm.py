"""Optional Claude narration for Ask — OFF by default (local-first).

When `INDAGA_LLM_ENABLED=1` AND an Anthropic key is configured, `/v1/ask` narrates the grounded
evidence with Claude instead of the deterministic summary. This is **network egress**: the question +
grounded evidence (personal health facts) are sent to Anthropic. So it is opt-in, disclosed to the
client (`narrated_by` in the final SSE event), and documented in the README. The deterministic floor
(`ask.summarize`) keeps Ask fully local and envelope-honest by default; the LLM only re-phrases WITHIN
the envelope — it never upgrades confidence, invents facts, or states a clinical negative.

Uses the official Anthropic SDK (model default `claude-opus-4-8`, overridable via `INDAGA_LLM_MODEL`;
`ANTHROPIC_BASE_URL` is honoured by the SDK for an Anthropic-compatible self-hosted endpoint).
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = """You are Indaga's Ask narrator. Phrase grounded personal-health evidence in 2–4 plain sentences.

The evidence envelope governs exactly what you may say — never exceed it:
- finding_state = not_measured → say it is unknown / never measured. NEVER "normal", "fine", or "good".
- finding_state = index_incomplete → say it is still calibrating; do not quote a value.
- finding_state = not_observed_in_consulted_scope → say nothing was found in what was checked; this is NOT a clinical negative.
- negative_inference.allowed is almost always false → never say "you don't have X" or "your X is normal" unless it is explicitly allowed.
- Decision-support, not diagnosis — suggest discussing medical decisions with a clinician.
- Use ONLY the provided evidence. Never invent numbers, ranges, or facts. Mention the source once.
- No preamble, no sign-off. Output only the answer."""


def is_enabled() -> bool:
    """True only when explicitly opted in AND a key is present (default OFF = fully local)."""
    return os.environ.get("INDAGA_LLM_ENABLED") == "1" and bool(_api_key())


def model() -> str:
    return os.environ.get("INDAGA_LLM_MODEL", DEFAULT_MODEL)


def _api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("INDAGA_ANTHROPIC_API_KEY")


def _evidence(op: str, result: dict, fallback_summary: str) -> str:
    """The compact, grounded payload the model may use — only what the op returned."""
    env = result.get("evidence_envelope", {})
    payload = {
        "routed_op": op,
        "grounded_summary": fallback_summary,
        "evidence_envelope": {k: env.get(k) for k in
                              ("finding_state", "answer_readiness", "negative_inference", "observations")},
        "facts": result.get("facts") or result.get("fact"),
        "decision": result.get("decision"),
        "present": result.get("present"),
        "missing": result.get("missing"),
    }
    return json.dumps({k: v for k, v in payload.items() if v is not None}, default=str)[:6000]


def narrate_stream(question: str, op: str, result: dict, fallback_summary: str):
    """Yield answer text chunks. Any failure (SDK missing, no key, API error) falls back to the
    deterministic summary — Ask never breaks, and never silently drops to a weaker answer."""
    try:
        import anthropic
    except Exception:
        yield fallback_summary
        return
    user = (f"User question: {question}\n\n"
            f"Grounded evidence (the ONLY facts you may use):\n{_evidence(op, result, fallback_summary)}")
    try:
        client = anthropic.Anthropic(api_key=_api_key())
        with client.messages.stream(
            model=model(),
            max_tokens=400,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},  # snappy phrasing; correctness is the envelope's job
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            produced = False
            for text in stream.text_stream:
                produced = True
                yield text
            if not produced:
                yield fallback_summary
    except Exception:
        yield fallback_summary
