"""Verb-first phrasing of a decision.

The deterministic default — the capability's own template filled with its params — ships first and is
always correct. A future LLM pass (Claude, Sprint 4) may *refine wording* but MUST NOT change the action
or its numeric anchor: phrasing is a presentation nicety, not a correctness step. That is exactly why
the deterministic default is the floor and the model is optional on top.
"""

from __future__ import annotations


def phrase_decision(decision: dict) -> str:
    template = decision.get("action_template") or ""
    params = decision.get("params") or {}
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template
