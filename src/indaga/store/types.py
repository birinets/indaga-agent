"""Typed return objects for the storage-agnostic Healthlake port (WS-0.2).

These types are the *contract* every consumer (the Indaga Engine, the indaga-mcp
server, the genome engine) sees. They are deliberately free of any storage detail:
no DB handles, no SQL, no file paths-as-API. A concrete backend (LocalDuckDB now;
HostedVault / ZeroKnowledge later) is an adapter that returns these objects.

Grounded in the real Healthlake silver schema (see
``users/<u>/healthlake/silver/tables/observations.csv``) plus two additions the
build plan requires: an explicit ``EvidenceGrade`` and a ``Caveat`` wrapper that
travels with every fact so an external model (Surface 2) receives the limits, not
just the numbers.

stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------- #
# Evidence + caveats — the cite-or-refuse substrate
# --------------------------------------------------------------------------- #

class EvidenceGrade(Enum):
    """Ordinal strength of the evidence behind a fact.

    The store is responsible for grading *accurately*. The downstream Critic
    (Engine, Surface 1) decides whether a given grade is strong enough to make a
    medical-impact claim or must refuse. Surface 2 (bring-your-own-AI) receives
    the grade verbatim and is trusted to honour it.
    """

    A = "A"  # clinically validated / directly measured (e.g. a LOINC-coded lab value)
    B = "B"  # strong: well-replicated, high-quality source (e.g. TOPMed R2>=0.8 variant + ClinVar P/LP)
    C = "C"  # moderate: single good source or imputed-but-decent
    D = "D"  # weak / exploratory: low imputation quality, single PGS, directional only
    INSUFFICIENT = "INSUFFICIENT"  # not enough to support any claim — consumer must refuse

    @property
    def rank(self) -> int:
        return {"A": 4, "B": 3, "C": 2, "D": 1, "INSUFFICIENT": 0}[self.value]

    def meets(self, floor: "EvidenceGrade") -> bool:
        """True if this grade is at least as strong as ``floor``."""
        return self.rank >= floor.rank


class Severity(Enum):
    INFO = "info"    # context the model should mention
    WARN = "warn"    # the model must hedge / qualify any claim using this fact
    BLOCK = "block"  # this fact must NOT ground a medical-impact claim on its own


class CaveatCode(Enum):
    """Closed vocabulary of why a fact is limited. Keep this enumerable so the
    Critic and the MCP caveat-wrapper can reason about caveats, not just display
    them."""

    IMPUTED = "imputed"                          # statistically inferred, not directly typed
    LOW_IMPUTATION_QUALITY = "low_imputation_quality"  # R2 below clinical threshold
    LOW_CONFIDENCE = "low_confidence"            # extraction/normalization confidence < 1.0
    REFUTED = "refuted"                          # cross-validation contradicted this (e.g. chip false-positive)
    SINGLE_DATAPOINT = "single_datapoint"        # no trend; n=1 in time
    STALE = "stale"                              # data older than its useful window
    UNIT_UNVERIFIED = "unit_unverified"          # original unit preserved but UCUM mapping uncertain
    NORMALIZATION_UNCERTAIN = "normalization_uncertain"  # name/code mapping is a candidate, not confirmed
    REFERENCE_RANGE_MISSING = "reference_range_missing"  # no lab reference interval available
    CALIBRATING = "calibrating"                  # derived metric not yet at its data-minimum (e.g. <14 nights)
    OUT_OF_PANEL = "out_of_panel"                # outside the screened panel; absence != negative


@dataclass(frozen=True, slots=True)
class Caveat:
    code: CaveatCode
    text: str                 # human-readable, model-readable; ships in the payload
    severity: Severity = Severity.WARN


# --------------------------------------------------------------------------- #
# Provenance — already first-class in the silver layer
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a fact came from. Grounded in silver/tables/provenance.csv."""

    provenance_id: str
    target_id: str
    target_type: str            # "observation" | "timeseries" | "variant" | ...
    source_document_id: str | None
    source_file_id: str | None  # e.g. "sha256:...."
    source_path: str | None     # repo-relative or vault-relative locator, never an absolute host path
    source_locator: str | None  # e.g. "$.tests[1]" or "chr19:44908822"
    extraction_method: str | None
    confidence: float | None
    status: str | None          # "validated" | "candidate" | "review" | ...


# --------------------------------------------------------------------------- #
# Fact — the unit of structured truth (lab, genomic, derived)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Fact:
    """One structured, provenance-stamped fact.

    Covers labs (value_number + unit + reference range), genomic variants
    (value_text = genotype/achange, attributes carry rsid/hugo/clinvar_sig), and
    derived metrics (e.g. a computed Biological Midnight). The ``attributes`` bag
    holds domain-specific extras without forcing a subtype per domain.
    """

    fact_id: str
    subject_id: str
    domain: str                       # "lab" | "genomic" | "wearable_summary" | "metabolic" | ...
    name: str                         # normalized name, e.g. "ldl_cholesterol"
    display: str | None = None        # human label, e.g. "LDL Cholesterol"

    value_number: float | None = None
    value_text: str | None = None     # genotype, category, or raw string value
    value_raw: str | None = None
    unit: str | None = None           # UCUM where known

    observed_at: date | datetime | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str | None = None
    interpretation: str | None = None  # "high" | "low" | "watch" | "normal" | None

    code_system: str | None = None    # "LOINC" | "ClinVar" | "PGS" | ...
    code: str | None = None

    evidence_grade: EvidenceGrade = EvidenceGrade.C
    confidence: float | None = None   # extraction/normalization confidence 0..1
    status: str = "validated"

    caveats: tuple[Caveat, ...] = ()
    provenance_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    # -- invariants the wrapper layer relies on -------------------------------
    @property
    def has_blocking_caveat(self) -> bool:
        return any(c.severity is Severity.BLOCK for c in self.caveats)

    @property
    def is_claim_grade(self) -> bool:
        """May this fact, on its own, ground a medical-impact claim?"""
        return self.evidence_grade.meets(EvidenceGrade.C) and not self.has_blocking_caveat

    def with_caveats(self, *caveats: Caveat) -> "Fact":
        return replace(self, caveats=self.caveats + tuple(caveats))


# --------------------------------------------------------------------------- #
# Time series — the high-frequency hot-store surface (CGM, HR, sleep)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class TimeSeriesPoint:
    t: datetime
    value: float


@dataclass(frozen=True, slots=True)
class TimeSeries:
    subject_id: str
    metric: str                 # "glucose_mgdl" | "heart_rate_bpm" | "sleep_stage" | ...
    unit: str | None
    points: tuple[TimeSeriesPoint, ...] = ()
    summary: dict[str, float] = field(default_factory=dict)  # mean/min/max/cv/n/...
    caveats: tuple[Caveat, ...] = ()
    source: str | None = None   # e.g. "apple_health:dexcom_g7"

    @property
    def n(self) -> int:
        return len(self.points)


# --------------------------------------------------------------------------- #
# Corrections registry — the source-of-truth ledger the Critic loads each run
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Correction:
    entity_kind: str            # "fact" | "pgs" | "variant_call" | ...
    entity_id: str
    current_value: str
    prior_value: str
    why: str
    t_invalidated: datetime
    source: str


# --------------------------------------------------------------------------- #
# Sources, scope, queries, and the AI-ready context pack
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class SourceRef:
    source_file_id: str
    label: str
    kind: str                   # "apple_health" | "dna_chip" | "lab_pdf" | "cgm" | "manual"
    ingested_at: datetime | None = None
    document_count: int = 0


class Surface(Enum):
    """Which surface is asking. Lets an adapter/wrapper tune evidence floors and
    caveat verbosity without changing the data itself."""

    APP = "app"          # Surface 1: Critic-gated; full internal detail
    BYO_AI = "byo_ai"    # Surface 2: caveats verbose + mandatory; "data not interpretation"
    HARNESS = "harness"  # Surface 3: genome-only, reproducibility-focused


@dataclass(frozen=True, slots=True)
class Scope:
    """The non-negotiable access boundary. Every read is hard-scoped to ONE
    subject — the n=1 isolation invariant. An adapter MUST NOT return any fact
    whose subject_id != scope.subject_id."""

    subject_id: str
    surface: Surface = Surface.APP
    domains: tuple[str, ...] = ()        # empty = all permitted domains
    since: date | datetime | None = None
    until: date | datetime | None = None
    include_genomics: bool = True        # Surface-2 may forbid raw genomic egress


@dataclass(frozen=True, slots=True)
class FactQuery:
    names: tuple[str, ...] = ()          # normalized names to filter to
    codes: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    flagged_only: bool = False           # interpretation != normal
    min_evidence: EvidenceGrade = EvidenceGrade.INSUFFICIENT
    min_confidence: float = 0.0
    status: tuple[str, ...] = ()         # e.g. ("validated",)
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class ContextPack:
    """The headline AI-ready slice for a scope. Maps to gold/llm/context_pack.json
    but adds the evidence_manifest + pack-level caveats so any consumer (especially
    an external model) gets a self-describing, source-backed bundle."""

    schema_version: str
    generated_at: datetime
    subject_id: str
    surface: Surface
    profile: dict[str, Any]
    facts: tuple[Fact, ...]
    timeseries_summaries: tuple[TimeSeries, ...]
    flagged: tuple[Fact, ...]
    corrections: tuple[Correction, ...]
    caveats: tuple[Caveat, ...]                 # pack-level limits ("CGM-off for 40 days", ...)
    query_guidance: str                          # how a model should use this pack honestly
    evidence_manifest: dict[str, int]            # grade -> count, for at-a-glance trust
