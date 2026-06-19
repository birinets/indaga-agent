"""Indaga evidence layer — the multi-omic answer-readiness envelope."""

from .envelope import (
    EvidenceEnvelope,
    EnvelopeValidationError,
    derive_envelope,
    evidence_present,
    empty_consulted_scope,
    index_incomplete,
    not_assessed,
    not_measured,
    validate,
)

# NOTE: the generic ``envelope()`` constructor is intentionally NOT re-exported
# here — that would shadow the ``evidence.envelope`` submodule. Import it from
# ``.envelope`` directly if a handler needs the low-level constructor.

__all__ = [
    "EvidenceEnvelope",
    "EnvelopeValidationError",
    "derive_envelope",
    "evidence_present",
    "empty_consulted_scope",
    "index_incomplete",
    "not_assessed",
    "not_measured",
    "validate",
]
