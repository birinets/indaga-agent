"""The single answer-readiness contract — multi-omic (mirrors genomi/evidence/envelope.py).

Every Indaga capability result reports its answer-readiness, scope, and
negative-inference rules through ONE typed envelope and nowhere else. Genomi's
insight — *zero ClinVar candidates ≠ "no genetic risk" because the region may not
be callable* — is generalized here across modalities:

  - genomic  : absence is real only if the region is callable + genotype-supported
  - lab      : absence is real only if the analyte was actually MEASURED (panel)
  - circadian: a Biological Midnight is real only if the clock is CALIBRATED (≥14 nights)
  - cgm      : a glycemic stat is real only if the sensor data is FRESH

Our ``Fact.evidence_grade`` / ``Fact.caveats`` are the *inputs*; this envelope is
the *output shape*. ``derive_envelope`` is the bridge every handler may run.

stdlib only.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..store import CaveatCode, EvidenceGrade, Fact, Scope

# --- finding states (Genomi's 6 + multi-omic additions) -------------------- #

EVIDENCE_PRESENT = "evidence_present"
NOT_OBSERVED_IN_CONSULTED_SCOPE = "not_observed_in_consulted_scope"
NOT_MEASURED = "not_measured"                 # NEW: the metric/analyte was never collected
NOT_ASSESSED = "not_assessed"
BLOCKED_MISSING_LIBRARY = "blocked_missing_library"
INDEX_INCOMPLETE = "index_incomplete"         # AGI building OR derived metric calibrating (<14 nights)
TRUE_NEGATIVE_SUPPORTED = "true_negative_supported"

FINDING_STATES = (
    EVIDENCE_PRESENT, NOT_OBSERVED_IN_CONSULTED_SCOPE, NOT_MEASURED, NOT_ASSESSED,
    BLOCKED_MISSING_LIBRARY, INDEX_INCOMPLETE, TRUE_NEGATIVE_SUPPORTED,
)

# --- answer readiness ------------------------------------------------------ #

ANSWER_SUPPORTED = "answer_supported"
SCOPED_ANSWER_ONLY = "scoped_answer_only"
CANNOT_ANSWER_YET = "cannot_answer_yet"
NEEDS_USER_INSTALL = "needs_user_install"
NEEDS_INDEX_BUILD = "needs_index_build"
NEEDS_MORE_DATA = "needs_more_data"           # NEW: not enough collected yet (e.g. <14 nights)
NEEDS_CLINICAL_CONFIRMATION = "needs_clinical_confirmation"

ANSWER_READINESS_STATES = (
    ANSWER_SUPPORTED, SCOPED_ANSWER_ONLY, CANNOT_ANSWER_YET, NEEDS_USER_INSTALL,
    NEEDS_INDEX_BUILD, NEEDS_MORE_DATA, NEEDS_CLINICAL_CONFIRMATION,
)

# --- negative-inference requirements (Genomi's 5 + 3 multi-omic analogues) -- #

REQ_CALLABILITY = "callability"                # genomic: region covered/callable
REQ_LIBRARY_COVERAGE = "library_coverage"
REQ_GENOTYPE_SUPPORT = "genotype_support"
REQ_CLINICAL_CONFIRMATION = "clinical_confirmation"
REQ_SCOPE_ALIGNMENT = "scope_alignment"
REQ_MEASUREMENT_PRESENT = "measurement_present"  # NEW: the lab/metric was actually collected
REQ_CALIBRATED = "calibrated"                    # NEW: derived metric past its data-minimum
REQ_FRESHNESS = "freshness"                      # NEW: data not stale beyond its useful window
REQ_PANEL_ALIGNMENT = "panel_alignment"          # NEW: the panel actually covers the asked analyte

NEGATIVE_INFERENCE_REQUIREMENTS = (
    REQ_CALLABILITY, REQ_LIBRARY_COVERAGE, REQ_GENOTYPE_SUPPORT, REQ_CLINICAL_CONFIRMATION,
    REQ_SCOPE_ALIGNMENT, REQ_MEASUREMENT_PRESENT, REQ_CALIBRATED, REQ_FRESHNESS, REQ_PANEL_ALIGNMENT,
)


# --- envelope -------------------------------------------------------------- #

@dataclass(frozen=True)
class EvidenceEnvelope:
    operation: str
    query_scope: dict[str, Any]
    subject_context: dict[str, Any]
    coverage: dict[str, Any]
    observations: dict[str, Any]
    finding_state: str
    answer_readiness: str
    negative_inference: dict[str, Any]
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "headline": f"{self.operation}: {self.finding_state} · {self.answer_readiness}",
            "finding_state": self.finding_state,
            "answer_readiness": self.answer_readiness,
            "guidance": list(self.guidance),
            "negative_inference": self.negative_inference,
            "next_actions": list(self.next_actions),
            "subject_context": self.subject_context,
            "coverage": self.coverage,
            "observations": self.observations,
            "query_scope": self.query_scope,
            "notes": list(self.notes),
        }


def _subject_context(*, subject_id: str | None = None, uses_personal_data: bool = True,
                     omic_scope: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"uses_personal_data": bool(uses_personal_data)}
    if subject_id is not None:
        payload["subject_id"] = subject_id
    if omic_scope is not None:
        payload["omic_scope"] = omic_scope
    return payload


def _coverage(*, consulted_sources: Iterable[str] | None = None,
             unavailable_sources: Iterable[str] | None = None,
             index_state: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "consulted_sources": list(consulted_sources or ()),
        "unavailable_sources": list(unavailable_sources or ()),
    }
    if index_state is not None:
        payload["index_state"] = index_state
    return payload


def _negative_inference(*, allowed: bool, requires: Iterable[str] = (),
                        satisfied: Iterable[str] = (), reason: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "allowed": bool(allowed),
        "requires": [r for r in requires if r in NEGATIVE_INFERENCE_REQUIREMENTS],
        "satisfied": [s for s in satisfied if s in NEGATIVE_INFERENCE_REQUIREMENTS],
    }
    if reason:
        payload["reason"] = reason
    return payload


def envelope(*, operation: str, finding_state: str, answer_readiness: str,
             query_scope: dict | None = None, subject_context: dict | None = None,
             coverage: dict | None = None, observations: dict | None = None,
             negative_inference: dict | None = None, next_actions: Iterable[dict] | None = None,
             notes: Iterable[str] | None = None, guidance: Iterable[str] | None = None) -> dict[str, Any]:
    env = EvidenceEnvelope(
        operation=operation,
        query_scope=dict(query_scope or {}),
        subject_context=dict(subject_context or _subject_context()),
        coverage=dict(coverage or _coverage()),
        observations=dict(observations or {}),
        finding_state=finding_state,
        answer_readiness=answer_readiness,
        negative_inference=dict(negative_inference or _negative_inference(allowed=False, reason="default")),
        next_actions=list(next_actions or ()),
        notes=list(notes or ()),
        guidance=list(guidance or ()),
    )
    validate(env)
    payload = env.to_dict()
    if not payload["guidance"]:
        payload["guidance"] = render_guidance(payload)
    return payload


# --- typed constructors ---------------------------------------------------- #

def evidence_present(*, operation: str, answer_readiness: str = ANSWER_SUPPORTED, **kw) -> dict[str, Any]:
    """At least one decision-grade fact is present in the consulted scope."""
    return envelope(
        operation=operation, finding_state=EVIDENCE_PRESENT, answer_readiness=answer_readiness,
        negative_inference=_negative_inference(
            allowed=False, reason="evidence_present — positive findings present; negative inference not applicable"),
        **kw,
    )


def empty_consulted_scope(*, operation: str,
                          requires_for_true_negative: Iterable[str] = (REQ_PANEL_ALIGNMENT, REQ_SCOPE_ALIGNMENT),
                          **kw) -> dict[str, Any]:
    """The consulted scope returned nothing, but absence is NOT a true negative."""
    kw.setdefault("observations", {"observation_count": 0})
    return envelope(
        operation=operation, finding_state=NOT_OBSERVED_IN_CONSULTED_SCOPE,
        answer_readiness=SCOPED_ANSWER_ONLY,
        negative_inference=_negative_inference(
            allowed=False, requires=requires_for_true_negative,
            reason="Zero observations in the consulted scope is not a true negative; do not state 'normal' or 'no risk'."),
        **kw,
    )


def not_measured(*, operation: str, what: str,
                 requires: Iterable[str] = (REQ_MEASUREMENT_PRESENT,),
                 reason: str | None = None, **kw) -> dict[str, Any]:
    """The asked-for analyte/metric isn't currently measured (the lab/wearable
    analogue of a no-call genotype). Use ``requires=[REQ_FRESHNESS, ...]`` for the
    stale-sensor case. Absence here means 'unknown', never 'normal'."""
    kw.setdefault("observations", {"observation_count": 0, "not_measured": what})
    actions = list(kw.pop("next_actions", []) or [])
    actions.append({"action": "order_or_upload", "what": what})
    return envelope(
        operation=operation, finding_state=NOT_MEASURED, answer_readiness=NEEDS_MORE_DATA,
        negative_inference=_negative_inference(
            allowed=False, requires=requires,
            reason=reason or f"{what!r} was never measured; its absence is unknown, not normal."),
        next_actions=actions, **kw,
    )


def index_incomplete(*, operation: str, requires: Iterable[str] = (REQ_CALIBRATED,),
                     reason: str | None = None, **kw) -> dict[str, Any]:
    """A derived index isn't ready: a genomic AGI still building, OR a derived
    metric still calibrating (e.g. Biological Midnight before 14 valid nights)."""
    kw.setdefault("observations", {"observation_count": 0})
    return envelope(
        operation=operation, finding_state=INDEX_INCOMPLETE, answer_readiness=NEEDS_MORE_DATA,
        negative_inference=_negative_inference(
            allowed=False, requires=requires,
            reason=reason or "The index is not yet complete; partial state cannot be interpreted."),
        **kw,
    )


def not_assessed(*, operation: str, reason: str, **kw) -> dict[str, Any]:
    """Could not assess (missing inputs, scope mismatch) — distinct from 'found nothing'."""
    kw.setdefault("observations", {"observation_count": 0})
    notes = [reason, *list(kw.pop("notes", []) or [])]
    return envelope(
        operation=operation, finding_state=NOT_ASSESSED, answer_readiness=CANNOT_ANSWER_YET,
        negative_inference=_negative_inference(allowed=False, requires=[REQ_SCOPE_ALIGNMENT],
                                               reason=f"Not assessed: {reason}"),
        notes=notes, **kw,
    )


def true_negative_supported(*, operation: str, satisfied: Iterable[str],
                            answer_readiness: str = SCOPED_ANSWER_ONLY, **kw) -> dict[str, Any]:
    """A genuine 'you don't have this' — only when callability + library coverage +
    genotype support (genomic baseline) are all satisfied. Validator enforces it."""
    required = (REQ_CALLABILITY, REQ_LIBRARY_COVERAGE, REQ_GENOTYPE_SUPPORT, REQ_SCOPE_ALIGNMENT)
    kw.setdefault("observations", {"observation_count": 0})
    return envelope(
        operation=operation, finding_state=TRUE_NEGATIVE_SUPPORTED, answer_readiness=answer_readiness,
        negative_inference=_negative_inference(
            allowed=True, requires=required, satisfied=satisfied,
            reason="True-negative claim is supported by satisfied requirements."),
        **kw,
    )


# --- validation ------------------------------------------------------------ #

class EnvelopeValidationError(ValueError):
    pass


def validate(env: EvidenceEnvelope | dict[str, Any]) -> None:
    payload = env.to_dict() if isinstance(env, EvidenceEnvelope) else env
    finding = payload.get("finding_state")
    readiness = payload.get("answer_readiness")
    if finding not in FINDING_STATES:
        raise EnvelopeValidationError(f"unknown finding_state: {finding!r}")
    if readiness not in ANSWER_READINESS_STATES:
        raise EnvelopeValidationError(f"unknown answer_readiness: {readiness!r}")
    ni = payload.get("negative_inference") or {}
    if not isinstance(ni, dict) or "allowed" not in ni:
        raise EnvelopeValidationError("negative_inference must include 'allowed'")
    for entry in payload.get("guidance") or []:
        if not isinstance(entry, str) or not entry or any(c.isspace() for c in entry):
            raise EnvelopeValidationError(f"guidance entries must be non-empty typed codes, got: {entry!r}")

    # cross-state invariants
    if finding == EVIDENCE_PRESENT and readiness in {NEEDS_USER_INSTALL, NEEDS_INDEX_BUILD, NEEDS_MORE_DATA, CANNOT_ANSWER_YET}:
        raise EnvelopeValidationError(f"evidence_present incompatible with answer_readiness={readiness}")
    if finding == BLOCKED_MISSING_LIBRARY and readiness != NEEDS_USER_INSTALL:
        raise EnvelopeValidationError("blocked_missing_library requires needs_user_install")
    if finding == INDEX_INCOMPLETE and readiness not in {NEEDS_INDEX_BUILD, NEEDS_MORE_DATA}:
        raise EnvelopeValidationError("index_incomplete requires needs_index_build or needs_more_data")
    if finding == NOT_MEASURED and ni.get("allowed"):
        raise EnvelopeValidationError("not_measured must not allow negative inference")
    if finding == NOT_OBSERVED_IN_CONSULTED_SCOPE and ni.get("allowed"):
        raise EnvelopeValidationError("not_observed_in_consulted_scope must not allow negative inference")
    if finding == TRUE_NEGATIVE_SUPPORTED:
        if not ni.get("allowed"):
            raise EnvelopeValidationError("true_negative_supported must allow negative inference")
        satisfied = set(ni.get("satisfied") or [])
        missing = set(ni.get("requires") or []) - satisfied
        if missing:
            raise EnvelopeValidationError(f"true_negative_supported missing satisfied: {sorted(missing)}")
        baseline = {REQ_CALLABILITY, REQ_LIBRARY_COVERAGE, REQ_GENOTYPE_SUPPORT}
        if not baseline.issubset(satisfied):
            raise EnvelopeValidationError(
                "true_negative_supported requires callability, library_coverage, genotype_support satisfied")


# --- guidance renderer ----------------------------------------------------- #

_GUIDANCE_TEMPLATES = {
    (EVIDENCE_PRESENT, ANSWER_SUPPORTED): "evidence_present:decision_grade_within_consulted_scope",
    (EVIDENCE_PRESENT, SCOPED_ANSWER_ONLY): "evidence_present:answer_only_within_consulted_scope",
    (EVIDENCE_PRESENT, NEEDS_CLINICAL_CONFIRMATION): "evidence_present:requires_clinical_confirmation",
    (NOT_OBSERVED_IN_CONSULTED_SCOPE, SCOPED_ANSWER_ONLY): "not_observed_in_consulted_scope:do_not_imply_clinical_negative",
    (NOT_MEASURED, NEEDS_MORE_DATA): "not_measured:absence_is_unknown_not_normal",
    (INDEX_INCOMPLETE, NEEDS_MORE_DATA): "index_incomplete:wait_for_more_data_before_claiming",
    (INDEX_INCOMPLETE, NEEDS_INDEX_BUILD): "index_incomplete:wait_or_poll_background_build",
    (NOT_ASSESSED, CANNOT_ANSWER_YET): "not_assessed:request_missing_inputs_or_use_different_tool",
    (BLOCKED_MISSING_LIBRARY, NEEDS_USER_INSTALL): "blocked_missing_library:ask_user_to_install",
    (TRUE_NEGATIVE_SUPPORTED, SCOPED_ANSWER_ONLY): "true_negative_supported:state_scope_explicitly",
}


def render_guidance(payload: dict[str, Any]) -> list[str]:
    finding = payload.get("finding_state")
    readiness = payload.get("answer_readiness")
    codes = [_GUIDANCE_TEMPLATES.get((finding, readiness), f"{finding}:{readiness}")]
    if not (payload.get("negative_inference") or {}).get("allowed"):
        codes.append("negative_inference_disallowed:do_not_state_clinical_negative")
    return codes


# --- the bridge: Fact grade/caveats → envelope (the contract floor) --------- #

def derive_envelope(operation: str, scope: Scope, facts: list[Fact], *,
                    query_scope: dict | None = None, consulted_sources: Iterable[str] | None = None,
                    omic_scope: str | None = None) -> dict[str, Any]:
    """The floor every handler may run. Reads our `Fact.is_claim_grade` /
    `caveats` / `EvidenceGrade.rank` and emits the right typed envelope."""
    claim = [f for f in facts if f.is_claim_grade]
    codes = {c.code for f in facts for c in f.caveats}
    weakest = min((f.evidence_grade for f in facts), key=lambda g: g.rank, default=None)
    obs = {
        "observation_count": len(facts),
        "claim_grade_count": len(claim),
        "weakest_grade": weakest.value if weakest else None,
        "facts": [f.fact_id for f in facts],
    }
    ctx = _subject_context(subject_id=scope.subject_id, omic_scope=omic_scope)
    cov = _coverage(consulted_sources=consulted_sources or [f.code_system for f in facts if f.code_system])
    common = dict(query_scope=query_scope or {}, subject_context=ctx, coverage=cov, observations=obs)

    # A derived metric still calibrating (clock <14 nights) → not ready, no claim.
    if CaveatCode.CALIBRATING in codes and not claim:
        return index_incomplete(operation=operation, requires=[REQ_CALIBRATED],
                                 reason="Derived metric is still calibrating; not enough data to claim it yet.",
                                 **common)
    # Asked-for thing is outside the screened panel → absence is not a negative.
    if CaveatCode.OUT_OF_PANEL in codes and not claim:
        return empty_consulted_scope(operation=operation, **common)
    if claim:
        weakest_claim = min((f.evidence_grade for f in claim), key=lambda g: g.rank)
        readiness = ANSWER_SUPPORTED if weakest_claim.rank >= EvidenceGrade.B.rank else SCOPED_ANSWER_ONLY
        return evidence_present(operation=operation, answer_readiness=readiness, **common)
    if facts:  # present but none claim-grade
        return not_assessed(operation=operation,
                            reason="All matching facts are below claim-grade.", **common)
    return empty_consulted_scope(operation=operation, **common)
