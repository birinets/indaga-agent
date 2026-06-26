"""Indaga Gateway — the thin, local, single-owner HTTP surface over indaga-agent.

The phone never speaks MCP and never touches the Active Health Index directly. It speaks a small REST
contract to THIS gateway, which runs on the *owner's own machine* (next to the agent), mints an
authorized `Context` via indaga's `build_context`, dispatches to `call_operation` IN-PROCESS, and
passes the `evidence_envelope` through to the client VERBATIM.

Design rules (mirror AGENTS.md):
  * No business logic and no second confidence model — the envelope is rendered, never re-derived.
  * Reuse indaga's grant + per-read audit (every `call_operation` already records access).
  * n=1: a device token is bound to exactly one subject; the gateway only ever serves that subject.

This is the "hosted AuthAdapter" seam the agent anticipated, kept honest for a personal server:
authentication happens at the HTTP edge (device token), then the local owner's own Context is minted.
"""

from .app import create_app
from .config import Settings

__all__ = ["create_app", "Settings"]
