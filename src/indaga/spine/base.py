"""Deterministic spine — service base (WS-1B.4).

A spine service is a deterministic computation that READS inputs from the
Healthlake through the port and WRITES its derived results back as `Fact`s
(graded, caveat-wrapped, with provenance pointing at the computation). The
Engine and the MCP server then consume the derived facts like any other —
the spine is "the science", the LLM never adjudicates it.

Every service returns a `SpineResult`; ``write_back`` persists it through the port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..store import Fact, HealthlakeStore, Provenance, Scope


@dataclass(frozen=True, slots=True)
class SpineResult:
    service: str
    state: str                       # service-specific state machine value
    facts: tuple[Fact, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    detail: dict = field(default_factory=dict)


def write_back(store: HealthlakeStore, scope: Scope, result: SpineResult) -> int:
    """Persist a service's derived facts + provenance through the port. Returns
    the number of facts written."""
    if result.facts:
        store.upsert_facts(scope, list(result.facts))
    for p in result.provenance:
        store.attach_provenance(scope, p)
    return len(result.facts)


class SpineService(Protocol):
    name: str

    def run(self, store: HealthlakeStore, scope: Scope, **kw) -> SpineResult:
        """Compute, write derived facts back through the port, return the result."""
        ...
