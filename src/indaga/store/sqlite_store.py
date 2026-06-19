"""LocalSQLiteStore — the persistent local adapter (Indaga re-architecture).

The canonical local backend for the port, mirroring Genomi's storage model: one
SQLite file per subject (``~/.indaga/<slug>/active-health-index.sqlite``), so the
store survives restarts and a ``shared-evidence.sqlite`` can be ATTACH-blended in
later. Ported from ``LocalDuckDBStore`` — same SQL, stdlib ``sqlite3`` (no dep),
which is the engine the rebuild plan resolved on.

DoD: passes ``run_conformance(lambda: LocalSQLiteStore())``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..runtime import paths
from ._query import fact_passes, in_window, summarize_points
from .codec import (
    dump_caveats as _dump_caveats,
    iso as _iso,
    load_caveats as _load_caveats,
    parse_dateish as _parse_dateish,
    parse_dt as _parse_dt,
)
from .port import HealthlakeStore
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
    TimeSeries,
    TimeSeriesPoint,
)

_SCHEMA_VERSION = "active-health-index/0.1"

_FACT_COLS = [
    "fact_id", "subject_id", "domain", "name", "display", "value_number",
    "value_text", "value_raw", "unit", "observed_at", "reference_low",
    "reference_high", "reference_text", "interpretation", "code_system", "code",
    "evidence_grade", "confidence", "status", "provenance_id", "caveats_json",
    "attributes_json",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
  fact_id TEXT, subject_id TEXT, domain TEXT, name TEXT,
  display TEXT, value_number REAL, value_text TEXT, value_raw TEXT,
  unit TEXT, observed_at TEXT, reference_low REAL, reference_high REAL,
  reference_text TEXT, interpretation TEXT, code_system TEXT, code TEXT,
  evidence_grade TEXT, confidence REAL, status TEXT, provenance_id TEXT,
  caveats_json TEXT, attributes_json TEXT
);
CREATE INDEX IF NOT EXISTS facts_subject_idx ON facts(subject_id, name);
CREATE TABLE IF NOT EXISTS provenance (
  provenance_id TEXT, target_id TEXT, subject_id TEXT, target_type TEXT,
  source_document_id TEXT, source_file_id TEXT, source_path TEXT,
  source_locator TEXT, extraction_method TEXT, confidence REAL, status TEXT
);
CREATE INDEX IF NOT EXISTS provenance_target_idx ON provenance(target_id, subject_id);
CREATE TABLE IF NOT EXISTS timeseries_points (
  subject_id TEXT, metric TEXT, t_iso TEXT, value REAL
);
CREATE INDEX IF NOT EXISTS timeseries_idx ON timeseries_points(subject_id, metric);
CREATE TABLE IF NOT EXISTS series_meta (
  subject_id TEXT, metric TEXT, unit TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS corrections (
  subject_id TEXT, entity_kind TEXT, entity_id TEXT, current_value TEXT,
  prior_value TEXT, why TEXT, t_invalidated TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS sources (
  subject_id TEXT, source_file_id TEXT, label TEXT, kind TEXT,
  ingested_at TEXT, document_count INTEGER
);
CREATE TABLE IF NOT EXISTS profiles (
  subject_id TEXT, profile_json TEXT
);
"""


class LocalSQLiteStore(HealthlakeStore):
    def __init__(self, db_path: str = ":memory:", *, generated_at: datetime | None = None) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(db_path)
        if db_path != ":memory:":
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
        self._now = generated_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._con.executescript(_SCHEMA)

    @classmethod
    def for_subject(cls, subject_id: str, *, generated_at: datetime | None = None) -> "LocalSQLiteStore":
        """Open (creating if needed) the persistent Active Health Index for a subject."""
        paths.ensure_subject_dirs(subject_id)
        return cls(str(paths.active_health_index_path(subject_id)), generated_at=generated_at)

    def close(self) -> None:
        self._con.close()

    # -- helpers --------------------------------------------------------------
    def set_profile(self, subject_id: str, profile: dict) -> None:
        self._con.execute("DELETE FROM profiles WHERE subject_id = ?", [subject_id])
        self._con.execute("INSERT INTO profiles VALUES (?, ?)", [subject_id, json.dumps(profile)])
        self._con.commit()

    def _owns(self, subject_id: str, fact_id: str) -> bool:
        return self._con.execute(
            "SELECT 1 FROM facts WHERE fact_id = ? AND subject_id = ? LIMIT 1",
            [fact_id, subject_id],
        ).fetchone() is not None

    def _fact_to_row(self, f: Fact) -> list:
        return [
            f.fact_id, f.subject_id, f.domain, f.name, f.display, f.value_number,
            f.value_text, f.value_raw, f.unit, _iso(f.observed_at), f.reference_low,
            f.reference_high, f.reference_text, f.interpretation, f.code_system, f.code,
            f.evidence_grade.value, f.confidence, f.status, f.provenance_id,
            _dump_caveats(f.caveats), json.dumps(f.attributes or {}),
        ]

    def _row_to_fact(self, d: dict) -> Fact:
        return Fact(
            fact_id=d["fact_id"], subject_id=d["subject_id"], domain=d["domain"],
            name=d["name"], display=d["display"], value_number=d["value_number"],
            value_text=d["value_text"], value_raw=d["value_raw"], unit=d["unit"],
            observed_at=_parse_dateish(d["observed_at"]),
            reference_low=d["reference_low"], reference_high=d["reference_high"],
            reference_text=d["reference_text"], interpretation=d["interpretation"],
            code_system=d["code_system"], code=d["code"],
            evidence_grade=EvidenceGrade(d["evidence_grade"]),
            confidence=d["confidence"], status=d["status"],
            caveats=_load_caveats(d["caveats_json"]), provenance_id=d["provenance_id"],
            attributes=json.loads(d["attributes_json"]) if d["attributes_json"] else {},
        )

    # -- HealthlakeWriter -----------------------------------------------------
    def upsert_facts(self, scope: Scope, facts: list[Fact]) -> int:
        placeholders = ",".join(["?"] * len(_FACT_COLS))
        cols = ",".join(_FACT_COLS)
        for f in facts:
            if f.subject_id != scope.subject_id:
                raise ValueError(
                    f"refusing to write fact for {f.subject_id!r} under scope "
                    f"{scope.subject_id!r} (subject isolation)"
                )
            self._con.execute(
                "DELETE FROM facts WHERE fact_id = ? AND subject_id = ?",
                [f.fact_id, f.subject_id],
            )
            self._con.execute(
                f"INSERT INTO facts ({cols}) VALUES ({placeholders})",
                self._fact_to_row(f),
            )
        self._con.commit()
        return len(facts)

    def append_timeseries(self, scope: Scope, series: TimeSeries) -> int:
        if series.subject_id != scope.subject_id:
            raise ValueError("timeseries subject mismatch (subject isolation)")
        self._con.execute(
            "DELETE FROM series_meta WHERE subject_id = ? AND metric = ?",
            [series.subject_id, series.metric],
        )
        self._con.execute(
            "INSERT INTO series_meta VALUES (?, ?, ?, ?)",
            [series.subject_id, series.metric, series.unit, series.source],
        )
        if series.points:
            self._con.executemany(
                "INSERT INTO timeseries_points VALUES (?, ?, ?, ?)",
                [(series.subject_id, series.metric, p.t.isoformat(), p.value) for p in series.points],
            )
        self._con.commit()
        return len(series.points)

    def attach_provenance(self, scope: Scope, provenance: Provenance) -> None:
        if not self._owns(scope.subject_id, provenance.target_id):
            raise ValueError(
                f"refusing provenance for unowned target {provenance.target_id!r} "
                f"under scope {scope.subject_id!r} (subject isolation)"
            )
        self._con.execute(
            "DELETE FROM provenance WHERE target_id = ? AND subject_id = ?",
            [provenance.target_id, scope.subject_id],
        )
        self._con.execute(
            "INSERT INTO provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                provenance.provenance_id, provenance.target_id, scope.subject_id,
                provenance.target_type, provenance.source_document_id,
                provenance.source_file_id, provenance.source_path,
                provenance.source_locator, provenance.extraction_method,
                provenance.confidence, provenance.status,
            ],
        )
        self._con.commit()

    def record_correction(self, scope: Scope, correction: Correction) -> None:
        self._con.execute(
            "INSERT INTO corrections VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                scope.subject_id, correction.entity_kind, correction.entity_id,
                correction.current_value, correction.prior_value, correction.why,
                correction.t_invalidated.isoformat(), correction.source,
            ],
        )
        self._con.commit()

    def register_source(self, scope: Scope, source: SourceRef) -> None:
        self._con.execute(
            "DELETE FROM sources WHERE subject_id = ? AND source_file_id = ?",
            [scope.subject_id, source.source_file_id],
        )
        self._con.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
            [scope.subject_id, source.source_file_id, source.label, source.kind,
             _iso(source.ingested_at), source.document_count],
        )
        self._con.commit()

    # -- HealthlakeReader -----------------------------------------------------
    def get_facts(self, scope: Scope, query: FactQuery | None = None) -> list[Fact]:
        res = self._con.execute("SELECT * FROM facts WHERE subject_id = ?", [scope.subject_id])
        cols = [d[0] for d in res.description]
        facts = [self._row_to_fact(dict(zip(cols, row))) for row in res.fetchall()]
        q = query or FactQuery()
        out = [f for f in facts if fact_passes(f, scope, q)]
        if q.limit is not None:
            out = out[: q.limit]
        return out

    def get_timeseries(self, scope: Scope, metric, since=None, until=None, resolution=None) -> TimeSeries:
        rows = self._con.execute(
            "SELECT t_iso, value FROM timeseries_points WHERE subject_id = ? AND metric = ?",
            [scope.subject_id, metric],
        ).fetchall()
        pts = sorted(
            (TimeSeriesPoint(_parse_dt(t), v) for t, v in rows if in_window(_parse_dt(t), since, until)),
            key=lambda p: p.t,
        )
        meta = self._con.execute(
            "SELECT unit, source FROM series_meta WHERE subject_id = ? AND metric = ?",
            [scope.subject_id, metric],
        ).fetchone()
        unit, source = (meta[0], meta[1]) if meta else (None, None)
        caveats: tuple[Caveat, ...] = ()
        if len(pts) <= 1:
            caveats = (Caveat(CaveatCode.SINGLE_DATAPOINT, "Not enough points for a trend.", Severity.WARN),)
        return TimeSeries(scope.subject_id, metric, unit, tuple(pts), summarize_points(pts), caveats, source)

    def get_provenance(self, scope: Scope, target_id: str) -> Provenance | None:
        if not self._owns(scope.subject_id, target_id):
            return None
        row = self._con.execute(
            "SELECT provenance_id, target_id, target_type, source_document_id, source_file_id, "
            "source_path, source_locator, extraction_method, confidence, status "
            "FROM provenance WHERE target_id = ? AND subject_id = ?",
            [target_id, scope.subject_id],
        ).fetchone()
        return Provenance(*row) if row else None

    def get_corrections(self, scope: Scope) -> list[Correction]:
        rows = self._con.execute(
            "SELECT entity_kind, entity_id, current_value, prior_value, why, t_invalidated, source "
            "FROM corrections WHERE subject_id = ?",
            [scope.subject_id],
        ).fetchall()
        return [
            Correction(ek, eid, cv, pv, why, datetime.fromisoformat(ti), src)
            for (ek, eid, cv, pv, why, ti, src) in rows
        ]

    def list_sources(self, scope: Scope) -> list[SourceRef]:
        rows = self._con.execute(
            "SELECT source_file_id, label, kind, ingested_at, document_count "
            "FROM sources WHERE subject_id = ?",
            [scope.subject_id],
        ).fetchall()
        return [SourceRef(sfid, label, kind, _parse_dt(ia), dc) for (sfid, label, kind, ia, dc) in rows]

    def get_context_pack(self, scope: Scope) -> ContextPack:
        facts = self.get_facts(scope)
        flagged = [f for f in facts if f.interpretation not in (None, "normal")]
        manifest: dict[str, int] = {}
        for f in facts:
            manifest[f.evidence_grade.value] = manifest.get(f.evidence_grade.value, 0) + 1
        pack_caveats: list[Caveat] = []
        if not facts:
            pack_caveats.append(
                Caveat(CaveatCode.OUT_OF_PANEL, "No facts in scope; absence is not a negative finding.", Severity.WARN)
            )
        metrics = [r[0] for r in self._con.execute(
            "SELECT DISTINCT metric FROM series_meta WHERE subject_id = ?", [scope.subject_id]
        ).fetchall()]
        prow = self._con.execute(
            "SELECT profile_json FROM profiles WHERE subject_id = ?", [scope.subject_id]
        ).fetchone()
        guidance = (
            "Use only the facts below; cite each by fact_id. Honour every caveat. "
            "Grade-D / INSUFFICIENT facts may not ground a medical-impact claim. "
            "If a question needs a fact not present, say so — do not infer it."
        )
        return ContextPack(
            schema_version=_SCHEMA_VERSION,
            generated_at=self._now,
            subject_id=scope.subject_id,
            surface=scope.surface,
            profile=json.loads(prow[0]) if prow else {},
            facts=tuple(facts),
            timeseries_summaries=tuple(self.get_timeseries(scope, m) for m in metrics),
            flagged=tuple(flagged),
            corrections=tuple(self.get_corrections(scope)),
            caveats=tuple(pack_caveats),
            query_guidance=guidance,
            evidence_manifest=manifest,
        )

    def health_check(self) -> bool:
        try:
            return self._con.execute("SELECT 1").fetchone() == (1,)
        except Exception:
            return False


if __name__ == "__main__":
    from .conformance import run_conformance

    results = run_conformance(lambda: LocalSQLiteStore())
    failed = sum(1 for _, ok, _ in results if not ok)
    for name, ok, detail in results:
        if not ok:
            print(f"[FAIL] {name}  -- {detail}")
    print(f"{len(results) - failed}/{len(results)} checks passed (LocalSQLiteStore)")
    raise SystemExit(1 if failed else 0)
