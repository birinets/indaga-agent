"""In-process Context pool + serialized dispatch.

`build_context` opens the persistent Active Health Index (ingesting only on first-ever build); we build
it once per subject and reuse it. SQLite connections are not safe to share across threads, and FastAPI
runs sync work in a threadpool, so we serialize every `call_operation` under one lock — correct and
more than fast enough for a single-owner personal server. `Context.now` is refreshed per call so audit
timestamps and freshness checks reflect the request time, not server start.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from indaga.interfaces.mcp import build_context
from indaga.operations import call_operation
from indaga.operations.model import Context
from indaga.store import Surface


class ContextPool:
    def __init__(self, user_dir: str) -> None:
        self._user_dir = user_dir
        self._build_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._by_subject: dict[str, Context] = {}

    def _context(self, subject_id: str) -> Context:
        with self._build_lock:
            ctx = self._by_subject.get(subject_id)
            if ctx is None:
                ctx = build_context(subject_id, self._user_dir, surface=Surface.APP)
                self._by_subject[subject_id] = ctx
            return ctx

    def dispatch(self, subject_id: str, op_name: str, params: dict | None = None) -> dict:
        """Run one operation and return its raw result dict (evidence_envelope untouched)."""
        ctx = self._context(subject_id)
        with self._dispatch_lock:
            ctx.now = datetime.now(timezone.utc)
            return call_operation(op_name, params or {}, ctx)

    def add_manual_lab(self, subject_id: str, analyte: str, value: float, *, unit: str | None = None,
                       observed_at: str | None = None, interpretation: str | None = None) -> dict:
        """Write a single user-entered lab value into the Healthlake and return labs.query for it.
        Manual entry is decision-grade (the user measured it) but flagged single-datapoint."""
        from datetime import date as _date

        from indaga.store import Caveat, CaveatCode, EvidenceGrade, Fact, Scope, Severity

        ctx = self._context(subject_id)
        with self._dispatch_lock:
            ctx.now = datetime.now(timezone.utc)
            name = analyte.strip().lower().replace(" ", "_")
            obs = _date.fromisoformat(observed_at) if observed_at else ctx.now.date()
            fid = f"lab_manual_{name}_{obs.isoformat()}"
            fact = Fact(
                fact_id=fid, subject_id=subject_id, domain="lab",
                name=name, display=analyte.strip(),
                value_number=float(value), unit=unit, observed_at=obs,
                interpretation=interpretation, evidence_grade=EvidenceGrade.B, status="validated",
                caveats=(Caveat(CaveatCode.SINGLE_DATAPOINT, "Manually entered by the user.", Severity.INFO),),
                provenance_id=None,
            )
            ctx.store.upsert_facts(Scope(subject_id, surface=ctx.surface or Surface.APP), [fact])
            return call_operation("labs.query", {"analyte": name}, ctx)

    def ingest_healthkit(self, subject_id: str, rows: list, *, metric: str = "heart_rate_bpm",
                         unit: str = "bpm", source: str = "apple_health") -> dict:
        """Ingest a HealthKit batch, recompute the deterministic clock from the extended series, and
        return the fresh clock.state (so the phone sees calibration advance immediately)."""
        from indaga.connectors.wearables import ingest_hr_batch
        from indaga.spine import BiologicalClock
        from indaga.store import Scope

        ctx = self._context(subject_id)
        with self._dispatch_lock:
            ctx.now = datetime.now(timezone.utc)
            report = ingest_hr_batch(ctx.store, subject_id, rows, metric=metric, unit=unit, source=source)
            scope = Scope(subject_id, surface=ctx.surface or Surface.APP)
            BiologicalClock().run(ctx.store, scope)  # refresh the Biological Midnight from new points
            clock = call_operation("clock.state", {}, ctx)
        return {"ingested": report, "clock": clock}
