"""The storage-agnostic Healthlake port (WS-0.2 keystone).

This is the single interface every consumer talks to. It names NO storage
technology — no DuckDB, no SQLite, no Postgres, no file paths-as-API. Concrete
backends implement it as adapters:

    LocalDuckDBStore     (WS-1B.1 — now: SQLite hot + DuckDB/Parquet, local-first)
    HostedVaultStore     (Phase 4 — encrypted cloud vault, OAuth)
    ZeroKnowledgeStore   (Phase 4 — blind host, user-held keys)
    InMemoryStore        (reference adapter, this package — tests + conformance)

The storage-agnostic rule: swapping the adapter changes WHERE data lives and HOW
it is secured, with zero changes to the Engine, the MCP server, or the genome
engine. That is what keeps the local-vs-hosted-vs-zero-knowledge decision open.

Read and write are separate Protocols on purpose:
  * ``HealthlakeReader`` — what the Engine / MCP server / genome tools consume.
  * ``HealthlakeWriter`` — what the ingestion connectors produce into.
  * ``HealthlakeStore`` — both, for adapters that do everything.

stdlib only (typing.Protocol).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from .types import (
    ContextPack,
    Correction,
    Fact,
    FactQuery,
    Provenance,
    Scope,
    SourceRef,
    TimeSeries,
)


@runtime_checkable
class HealthlakeReader(Protocol):
    """Read side. Every method takes a ``Scope`` and MUST hard-enforce
    ``scope.subject_id`` — never return another subject's data (the n=1 invariant
    the conformance suite checks)."""

    def get_facts(self, scope: Scope, query: FactQuery | None = None) -> list[Fact]:
        """Structured facts (labs, genomic, derived) matching the query, scoped to
        one subject. Every returned Fact carries its ``evidence_grade`` and any
        ``caveats`` — never a bare number."""
        ...

    def get_timeseries(
        self,
        scope: Scope,
        metric: str,
        since: date | datetime | None = None,
        until: date | datetime | None = None,
        resolution: str | None = None,
    ) -> TimeSeries:
        """A high-frequency series (CGM/HR/sleep) with summary stats, scoped to
        one subject. ``resolution`` is an adapter hint ("raw"|"hourly"|"daily")."""
        ...

    def get_provenance(self, scope: Scope, target_id: str) -> Provenance | None:
        """Resolve the provenance for a fact/timeseries/variant. Used by the
        Tier-2 grounding check: every claim must trace to a record."""
        ...

    def get_corrections(self, scope: Scope) -> list[Correction]:
        """The corrections ledger for this subject — loaded by the Critic every
        run so a superseded value can never resurface as current."""
        ...

    def list_sources(self, scope: Scope) -> list[SourceRef]:
        """What's connected and when it last synced (drives the Healthlake
        inventory screen + data-freshness/staleness logic)."""
        ...

    def get_context_pack(self, scope: Scope) -> ContextPack:
        """The headline AI-ready slice for the scope: profile + facts +
        timeseries summaries + flagged items + corrections + pack-level caveats +
        an evidence manifest. This is the primary payload the MCP server wraps and
        the Engine grounds on. It is self-describing and source-backed."""
        ...


@runtime_checkable
class HealthlakeWriter(Protocol):
    """Write side. What the ingestion connectors (WS-1B.2) produce into. Writes
    are also scoped: an adapter MUST stamp/validate ``subject_id`` on every fact."""

    def upsert_facts(self, scope: Scope, facts: list[Fact]) -> int:
        """Insert or update facts for one subject. Returns the count written.
        Implementations MUST preserve provenance and MUST NOT silently coerce
        uncertain values (low-confidence facts keep their caveats)."""
        ...

    def append_timeseries(self, scope: Scope, series: TimeSeries) -> int:
        """Append points to a high-frequency series. Returns points written."""
        ...

    def attach_provenance(self, scope: Scope, provenance: Provenance) -> None:
        """Store/replace the provenance for a target owned by this subject.
        Connectors call this alongside ``upsert_facts`` so ``get_provenance`` can
        resolve. An adapter MUST refuse provenance whose target is not owned by
        ``scope.subject_id`` (isolation)."""
        ...

    def record_correction(self, scope: Scope, correction: Correction) -> None:
        """Append to the corrections ledger (append-only; never mutate history)."""
        ...

    def register_source(self, scope: Scope, source: SourceRef) -> None:
        """Record/refresh a connected data source for the inventory + freshness."""
        ...


@runtime_checkable
class HealthlakeStore(HealthlakeReader, HealthlakeWriter, Protocol):
    """Full read+write store. The adapter type the app wires up. Splitting the
    two Protocols above lets a read-only surface (e.g. a hardened external MCP
    endpoint) depend on ``HealthlakeReader`` alone and statically forbid writes."""

    def health_check(self) -> bool:
        """Cheap liveness probe for the backend (connection open, schema present)."""
        ...
