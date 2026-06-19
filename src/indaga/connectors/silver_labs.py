"""Silver labs connector — the existing Healthlake silver layer → port facts.

Reads ``users/<u>/healthlake/silver/tables/observations.csv`` (the canonical,
LOINC-coded, provenance-stamped lab facts) and writes them through the port as
graded, caveat-wrapped `Fact`s + their `Provenance`. Adapter-agnostic: stdlib csv,
no DuckDB, no storage assumptions.

The grading rule lives here (it is silver-format knowledge, not storage):
  * measured + validated structured extraction + confidence 1.0 → Grade A
  * else confidence ≥0.8 → B, ≥0.5 → C, else D
  * candidate code mapping → NORMALIZATION_UNCERTAIN (info)
  * no reference interval → REFERENCE_RANGE_MISSING (info)
  * confidence <1.0 → LOW_CONFIDENCE (warn)
"""

from __future__ import annotations

import csv

from ..store import (
    Caveat,
    CaveatCode,
    EvidenceGrade,
    Fact,
    HealthlakeStore,
    Provenance,
    Scope,
    Severity,
)
from ..store.codec import num, parse_dateish


def _grade(row: dict) -> tuple[EvidenceGrade, tuple[Caveat, ...]]:
    conf = num(row.get("confidence")) or 0.0
    status = (row.get("status") or "").lower()
    method = (row.get("extraction_method") or "").lower()
    caveats: list[Caveat] = []
    if (row.get("code_confidence") or "").lower() == "candidate":
        caveats.append(Caveat(CaveatCode.NORMALIZATION_UNCERTAIN,
                              "Code mapping is a candidate, not confirmed.", Severity.INFO))
    if not (row.get("reference_low") or row.get("reference_high") or row.get("reference_text")):
        caveats.append(Caveat(CaveatCode.REFERENCE_RANGE_MISSING,
                              "No reference interval available.", Severity.INFO))
    if conf < 1.0:
        caveats.append(Caveat(CaveatCode.LOW_CONFIDENCE,
                              "Extraction confidence below 1.0.", Severity.WARN))
    if "validated_structured" in method and conf >= 1.0 and status == "validated":
        grade = EvidenceGrade.A
    elif conf >= 0.8:
        grade = EvidenceGrade.B
    elif conf >= 0.5:
        grade = EvidenceGrade.C
    else:
        grade = EvidenceGrade.D
    return grade, tuple(caveats)


def _row_to_fact(subject_id: str, r: dict) -> tuple[Fact, Provenance]:
    grade, caveats = _grade(r)
    fid = r["observation_id"]
    fact = Fact(
        fact_id=fid, subject_id=subject_id,
        domain=r.get("domain") or "lab",
        name=r.get("name_normalized") or r.get("name_original") or fid,
        display=r.get("name_original"),
        value_number=num(r.get("value_number")), value_raw=r.get("value_raw") or None,
        unit=(r.get("unit_ucum") or r.get("unit_raw")) or None,
        observed_at=parse_dateish(r.get("observed_at")),
        reference_low=num(r.get("reference_low")), reference_high=num(r.get("reference_high")),
        reference_text=r.get("reference_text") or None,
        interpretation=r.get("interpretation") or None,
        code_system=r.get("code_system") or None, code=r.get("code") or None,
        evidence_grade=grade, confidence=num(r.get("confidence")),
        status=r.get("status") or "validated",
        caveats=caveats, provenance_id=f"prov_{fid}",
    )
    prov = Provenance(
        f"prov_{fid}", fid, "observation", r.get("source_document_id") or None,
        r.get("source_file_id") or None, r.get("source_path") or None,
        r.get("source_locator") or None, r.get("extraction_method") or None,
        num(r.get("confidence")), r.get("status") or None,
    )
    return fact, prov


def ingest_silver_labs(store: HealthlakeStore, subject_id: str, csv_path: str) -> int:
    """Load silver observations for one subject into the store. Returns fact count."""
    scope = Scope(subject_id)
    facts: list[Fact] = []
    provs: list[Provenance] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("subject_id") != subject_id:
                continue  # subject isolation at the source boundary
            f, p = _row_to_fact(subject_id, r)
            facts.append(f)
            provs.append(p)
    store.upsert_facts(scope, facts)
    for p in provs:
        store.attach_provenance(scope, p)
    return len(facts)
