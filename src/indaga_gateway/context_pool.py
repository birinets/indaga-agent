"""In-process Context pool + single-threaded engine dispatch.

`build_context` opens the persistent Active Health Index (ingesting only on first-ever build); we build
it once per subject and reuse it. The catch: SQLite connections are **thread-affine** (a connection can
only be used on the thread that created it), and FastAPI runs sync endpoints across a threadpool — so a
cached store would blow up the moment a request lands on a different thread.

So every engine call (including the lazy `build_context`) runs on ONE dedicated worker thread via a
`max_workers=1` executor. That keeps the cached store on a single thread AND serializes access for free
— correct and far more than fast enough for a single-owner personal server. `Context.now` is refreshed
per call so audit timestamps and freshness checks reflect request time, not server start.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from indaga.interfaces.mcp import build_context
from indaga.operations import call_operation
from indaga.operations.model import Context
from indaga.store import Surface


class ContextPool:
    def __init__(self, user_dir: str) -> None:
        self._user_dir = user_dir
        self._by_subject: dict[str, Context] = {}
        # The single thread that owns every SQLite connection and runs every operation.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indaga-engine")

    # Runs ON the worker thread.
    def _context(self, subject_id: str) -> Context:
        ctx = self._by_subject.get(subject_id)
        if ctx is None:
            ctx = build_context(subject_id, self._user_dir, surface=Surface.APP)
            self._by_subject[subject_id] = ctx
        return ctx

    def _run(self, fn):
        """Execute fn on the single engine thread and block for its result."""
        return self._worker.submit(fn).result()

    def dispatch(self, subject_id: str, op_name: str, params: dict | None = None) -> dict:
        """Run one operation and return its raw result dict (evidence_envelope untouched)."""
        def work():
            ctx = self._context(subject_id)
            ctx.now = datetime.now(timezone.utc)
            return call_operation(op_name, params or {}, ctx)
        return self._run(work)

    def add_manual_lab(self, subject_id: str, analyte: str, value: float, *, unit: str | None = None,
                       observed_at: str | None = None, interpretation: str | None = None) -> dict:
        """Write a single user-entered lab value into the Healthlake and return labs.query for it.
        Manual entry is decision-grade (the user measured it) but flagged single-datapoint."""
        def work():
            from datetime import date as _date

            from indaga.store import Caveat, CaveatCode, EvidenceGrade, Fact, Scope, Severity

            ctx = self._context(subject_id)
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
        return self._run(work)

    def ingest_healthkit(self, subject_id: str, rows: list, *, metric: str = "heart_rate_bpm",
                         unit: str = "bpm", source: str = "apple_health") -> dict:
        """Ingest a HealthKit batch, recompute the deterministic clock from the extended series, and
        return the fresh clock.state (so the phone sees calibration advance immediately)."""
        def work():
            from indaga.connectors.wearables import ingest_hr_batch
            from indaga.spine import BiologicalClock
            from indaga.store import Scope

            ctx = self._context(subject_id)
            ctx.now = datetime.now(timezone.utc)
            report = ingest_hr_batch(ctx.store, subject_id, rows, metric=metric, unit=unit, source=source)
            scope = Scope(subject_id, surface=ctx.surface or Surface.APP)
            BiologicalClock().run(ctx.store, scope)  # refresh the Biological Midnight from new points
            clock = call_operation("clock.state", {}, ctx)
            return {"ingested": report, "clock": clock}
        return self._run(work)
