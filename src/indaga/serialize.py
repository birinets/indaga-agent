"""JSON serializers for the port types (Fact / TimeSeries / Provenance / ...).

Pure projections of the store dataclasses into JSON-safe dicts. Used by the
capability handlers to put facts into tool payloads. The evidence *envelope* is a
separate concern (``indaga.evidence.envelope``); this module is only serialization.
"""

from __future__ import annotations

from .store import Caveat, ContextPack, Correction, Fact, Provenance, SourceRef, TimeSeries
from .store.codec import iso


def caveat_to_dict(c: Caveat) -> dict:
    return {"code": c.code.value, "text": c.text, "severity": c.severity.value}


def fact_to_dict(f: Fact) -> dict:
    return {
        "fact_id": f.fact_id, "domain": f.domain, "name": f.name, "display": f.display,
        "value_number": f.value_number, "value_text": f.value_text, "value_raw": f.value_raw,
        "unit": f.unit, "observed_at": iso(f.observed_at),
        "reference_low": f.reference_low, "reference_high": f.reference_high,
        "reference_text": f.reference_text, "interpretation": f.interpretation,
        "code_system": f.code_system, "code": f.code,
        "evidence_grade": f.evidence_grade.value, "confidence": f.confidence,
        "status": f.status, "provenance_id": f.provenance_id,
        "caveats": [caveat_to_dict(c) for c in f.caveats], "attributes": f.attributes,
    }


def timeseries_to_dict(ts: TimeSeries, *, include_points: bool = False) -> dict:
    d = {
        "metric": ts.metric, "unit": ts.unit, "n": ts.n, "summary": ts.summary,
        "source": ts.source, "caveats": [caveat_to_dict(c) for c in ts.caveats],
    }
    if include_points:
        d["points"] = [[p.t.isoformat(), p.value] for p in ts.points]
    return d


def provenance_to_dict(p: Provenance) -> dict:
    return {
        "provenance_id": p.provenance_id, "target_id": p.target_id, "target_type": p.target_type,
        "source_document_id": p.source_document_id, "source_file_id": p.source_file_id,
        "source_path": p.source_path, "source_locator": p.source_locator,
        "extraction_method": p.extraction_method, "confidence": p.confidence, "status": p.status,
    }


def correction_to_dict(c: Correction) -> dict:
    return {
        "entity_kind": c.entity_kind, "entity_id": c.entity_id,
        "current_value": c.current_value, "prior_value": c.prior_value,
        "why": c.why, "t_invalidated": iso(c.t_invalidated), "source": c.source,
    }


def sourceref_to_dict(s: SourceRef) -> dict:
    return {
        "source_file_id": s.source_file_id, "label": s.label, "kind": s.kind,
        "ingested_at": iso(s.ingested_at), "document_count": s.document_count,
    }


def contextpack_to_dict(cp: ContextPack) -> dict:
    return {
        "schema_version": cp.schema_version, "generated_at": iso(cp.generated_at),
        "profile": cp.profile,
        "facts": [fact_to_dict(f) for f in cp.facts],
        "timeseries_summaries": [timeseries_to_dict(t) for t in cp.timeseries_summaries],
        "flagged": [fact_to_dict(f) for f in cp.flagged],
        "corrections": [correction_to_dict(c) for c in cp.corrections],
        "caveats": [caveat_to_dict(c) for c in cp.caveats],
        "query_guidance": cp.query_guidance, "evidence_manifest": cp.evidence_manifest,
    }
