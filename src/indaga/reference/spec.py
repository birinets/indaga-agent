"""The unified data-source model for Indaga's reference-library registry.

Every external reference Indaga uses — a downloadable library (ClinVar VCF, PGS
weights), a live public API (gnomAD), a per-key cache (PGS scoring file by id) —
is ONE ``LibrarySpec`` in the registry (see ``registry.py``). The spec is the
single source of truth: id, where the bytes come from, where they land, how to
tell whether it is installed and current. The downloader (see ``manager.py``)
reads these specs; there is no per-module download code.

Mirrors ``genomi/runtime/libraries/spec.py`` (trimmed to what Indaga uses).
Paths here are RELATIVE to ``indaga_home()``; the manager resolves them against
the live home dir so tests can relocate it. stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Kind(str, Enum):
    """What sort of source this is; decides install / status / freshness behavior."""

    OFFLINE = "offline"          # downloaded + cached under indaga_home()
    ONLINE = "online"            # live public API; never cached offline
    PARAMETERIZED = "parameterized"  # per-key cache, e.g. a PGS scoring file by pgs_id
    DERIVED = "derived"          # built locally from other libraries (no direct download)
    MANUAL = "manual"            # user must supply the file (no public URL)


class Transform(str, Enum):
    """Post-download processing applied before a source counts as installed."""

    NONE = "none"                # store the bytes as-is
    GUNZIP_FAIDX = "gunzip_faidx"  # decompress a .fa.gz, then build the .fai index (Phase E)


class Freshness(str, Enum):
    """How the manager decides whether an installed source is current."""

    HTTP_VALIDATORS = "http_validators"  # conditional GET via stored ETag/Last-Modified
    PINNED_SHA = "pinned_sha"            # version+sha256 pinned in the registry
    LIVE = "live"                        # online API; only reachability is checked
    MANUAL = "manual"                    # user-supplied; nothing upstream to check


@dataclass(frozen=True)
class Source:
    """Where a source's bytes (or endpoint) come from. Fields used depend on Kind.

    - OFFLINE: ``urls`` (one per target), optional ``sha256`` / ``version`` pin.
    - PARAMETERIZED: ``url_template`` with ``{key}`` (and ``{build}``) placeholders.
    - ONLINE: ``api_base`` (used for the reachability probe only).
    """

    urls: tuple[str, ...] = ()
    url_template: str | None = None
    api_base: str | None = None
    sha256: str | None = None
    version: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class LibrarySpec:
    """One entry in the registry — the single source of truth for a reference source."""

    id: str
    title: str
    helps: str
    kind: Kind
    size_class: str = ""                 # human size, e.g. "~190 MB"; "online" for live APIs
    purposes: tuple[str, ...] = ()       # install purposes (e.g. "chip-core", "predictors")
    phase: str = "A"                     # roadmap phase this lands in (A=v1, B/C/D/E later)
    source: Source = field(default_factory=Source)
    transform: Transform = Transform.NONE
    freshness: Freshness = Freshness.HTTP_VALIDATORS
    # Paths RELATIVE to indaga_home(), resolved by the manager.
    targets: tuple[Path, ...] = ()       # where downloaded bytes land (one per source url)
    required_paths: tuple[Path, ...] = ()  # existence proves "installed" (offline/derived/manual)

    @property
    def is_offline(self) -> bool:
        return self.kind in (Kind.OFFLINE, Kind.DERIVED, Kind.MANUAL, Kind.PARAMETERIZED)

    @property
    def is_online(self) -> bool:
        return self.kind is Kind.ONLINE

    @property
    def downloadable(self) -> bool:
        """Has concrete URLs the manager can fetch right now (not parameterized/online/manual)."""
        return self.kind is Kind.OFFLINE and bool(self.source.urls)
