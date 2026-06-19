"""Storage-agnostic Healthlake port (WS-0.2).

The single interface every consumer (Indaga Engine, indaga-mcp server, genome
engine) talks to. Concrete backends are adapters; swapping one changes WHERE data
lives and HOW it is secured, with zero upstream changes. See
``docs/healthlake-port-spec.md`` for the narrative spec.
"""

from __future__ import annotations

from .port import HealthlakeReader, HealthlakeStore, HealthlakeWriter
from .types import (
    Caveat,
    CaveatCode,
    ContextPack,
    Correction,
    EvidenceGrade,
    Fact,
    FactQuery,
    Provenance,
    Scope,
    Severity,
    SourceRef,
    Surface,
    TimeSeries,
    TimeSeriesPoint,
)

__all__ = [
    # ports
    "HealthlakeReader",
    "HealthlakeWriter",
    "HealthlakeStore",
    # types
    "Caveat",
    "CaveatCode",
    "ContextPack",
    "Correction",
    "EvidenceGrade",
    "Fact",
    "FactQuery",
    "Provenance",
    "Scope",
    "Severity",
    "SourceRef",
    "Surface",
    "TimeSeries",
    "TimeSeriesPoint",
]
