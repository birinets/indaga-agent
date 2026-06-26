"""FastAPI app — the REST contract the iOS app talks to.

Sprint 0 surface:
  GET  /healthz                 liveness (no auth)
  POST /v1/pair                 redeem a pairing code → device token (the code is the auth)
  GET  /v1/today/strip          the daily-loop tokens; each carries its evidence_envelope VERBATIM

Every protected route depends on a valid device token bound to the configured subject. The gateway
never reshapes or recomputes the evidence_envelope — it embeds each operation's result dict unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

import json

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import ask as ask_mod
from . import auth
from . import clinical
from . import llm
from .config import Settings
from .context_pool import ContextPool
from .phrasing import phrase_decision


class PairRequest(BaseModel):
    code: str
    label: str = "iphone"


class PairResponse(BaseModel):
    device_token: str
    subject: str


class HealthKitBatch(BaseModel):
    metric: str = "heart_rate_bpm"
    unit: str = "bpm"
    source: str = "apple_health"
    points: list  # rows of [iso_ts, bpm, source?]


class ActionDoneRequest(BaseModel):
    action_id: str
    note: str | None = None


class AskRequest(BaseModel):
    question: str


class ManualLab(BaseModel):
    analyte: str
    value: float
    unit: str | None = None
    observed_at: str | None = None  # ISO date; defaults to today
    interpretation: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    pool = ContextPool(settings.user_dir)
    app = FastAPI(title="Indaga Gateway", version="0.1.0",
                  description="Thin local REST surface over indaga-agent (single-owner).")
    app.state.settings = settings
    app.state.pool = pool

    def require_device(authorization: str | None = Header(default=None)) -> str:
        """Authenticate the bearer device token; return the authorized subject id."""
        if settings.allow_insecure:
            return settings.subject
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if not auth.verify_token(settings.subject, token):
            raise HTTPException(status_code=401, detail="invalid device token")
        return settings.subject

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "subject": settings.subject}

    @app.post("/v1/pair", response_model=PairResponse)
    def pair(req: PairRequest) -> PairResponse:
        token = auth.redeem_pairing_code(settings.subject, req.code, label=req.label)
        if token is None:
            raise HTTPException(status_code=401, detail="invalid or expired pairing code")
        return PairResponse(device_token=token, subject=settings.subject)

    @app.get("/v1/today")
    def today(subject: str = Depends(require_device)) -> dict:
        """The single prioritised decision. The verb-first text is phrased here (deterministic default);
        the evidence_envelope is passed through VERBATIM so the client maps the confidence chip itself —
        the gateway never computes a second confidence signal."""
        res = pool.dispatch(subject, "decision.today")
        dec = res["decision"]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "decision": {
                "action_id": dec.get("candidate_id") or "nothing_urgent",
                "text": phrase_decision(dec),
                "supporting": dec.get("supporting"),
                "kind": dec.get("kind"),
                "heuristic": dec.get("heuristic"),
                "params": dec.get("params"),
                "legs": dec.get("legs"),
            },
            "candidates": res.get("candidates"),
            "evidence_envelope": res["evidence_envelope"],
        }

    @app.get("/v1/today/strip")
    def today_strip(subject: str = Depends(require_device)) -> dict:
        """The daily-loop strip. Each token embeds the operation's full result dict (including the
        evidence_envelope) verbatim, so the client maps confidence mechanically. Sleep & energy tokens
        are net-new (no connector yet) and are intentionally omitted rather than faked."""
        tokens = [
            {"key": "biological_midnight", "title": "Biological Midnight", "op": "clock.state",
             "result": pool.dispatch(subject, "clock.state")},
            {"key": "glucose", "title": "Glucose", "op": "cgm.glycemic_summary",
             "result": pool.dispatch(subject, "cgm.glycemic_summary")},
        ]
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "tokens": tokens}

    @app.get("/v1/why/{action_id}")
    def why(action_id: str, subject: str = Depends(require_device)) -> dict:
        """The evidence trail behind the current decision: each leg's full op result (with its envelope
        verbatim), so the app's Why sheet renders provenance + 'what we don't know' directly."""
        res = pool.dispatch(subject, "decision.today")
        dec = res["decision"]
        current = dec.get("candidate_id") or "nothing_urgent"
        if action_id not in (current, "current"):
            raise HTTPException(status_code=404, detail=f"no current decision with action_id {action_id!r}")
        provenance = [{"op": leg["op"], "role": leg["role"], "result": pool.dispatch(subject, leg["op"])}
                      for leg in (dec.get("legs") or [])]
        return {
            "action_id": current,
            "decision_text": phrase_decision(dec),
            "supporting": dec.get("supporting"),
            "heuristic": dec.get("heuristic"),
            "provenance": provenance,
            "evidence_envelope": res["evidence_envelope"],
        }

    @app.get("/v1/body")
    def body(subject: str = Depends(require_device)) -> dict:
        """The living biological model: graded report sections + lab panel coverage
        (known / calibrating / never-measured). Envelopes pass through verbatim."""
        return {
            "report": pool.dispatch(subject, "analyze.report"),
            "coverage": pool.dispatch(subject, "labs.panel_coverage"),
        }

    @app.get("/v1/sources")
    def sources(subject: str = Depends(require_device)) -> dict:
        return pool.dispatch(subject, "sources.list")

    @app.get("/v1/visit-prep")
    def visit_prep(subject: str = Depends(require_device)) -> dict:
        """Clinician-ready handoff: today's action + what to raise + labs to order + genome-derived
        medication flags + PGx blind-spots. The genome/PGx angle is Indaga's edge over labs-only apps."""
        return clinical.visit_prep(pool, subject)

    @app.get("/v1/explain/{analyte}")
    def explain(analyte: str, subject: str = Depends(require_device)) -> dict:
        """Explain one lab result at exactly the envelope's strength (never-measured → 'unknown')."""
        result = pool.dispatch(subject, "labs.query", {"analyte": analyte})
        return {
            "analyte": analyte,
            "explanation": ask_mod.summarize("labs.query", result),
            "facts": result.get("facts", []),
            "evidence_envelope": result.get("evidence_envelope", {}),
        }

    @app.post("/v1/labs")
    def add_lab(req: ManualLab, subject: str = Depends(require_device)) -> dict:
        """Manually add a lab value to the Healthlake (PDF OCR is a later path)."""
        return pool.add_manual_lab(subject, req.analyte, req.value, unit=req.unit,
                                   observed_at=req.observed_at, interpretation=req.interpretation)

    @app.post("/v1/ingest/healthkit")
    def ingest_healthkit(batch: HealthKitBatch, subject: str = Depends(require_device)) -> dict:
        """Push a HealthKit batch (HR points). Ingests idempotently, recomputes the Biological Clock,
        returns the fresh clock.state so calibration progress ('n/14') updates live."""
        return pool.ingest_healthkit(subject, batch.points, metric=batch.metric,
                                     unit=batch.unit, source=batch.source)

    @app.post("/v1/ask")
    def ask(req: AskRequest, subject: str = Depends(require_device)) -> StreamingResponse:
        """Conversational query. Routes to one real op, answers at exactly the envelope's strength, and
        streams the answer over SSE; the final event carries the evidence_envelope verbatim + source
        footnotes. Dispatch happens up-front so failures surface as HTTP, not mid-stream."""
        op, params = ask_mod.route(req.question)
        result = pool.dispatch(subject, op, params)
        deterministic = ask_mod.summarize(op, result)
        env = result.get("evidence_envelope", {})
        use_llm = llm.is_enabled()
        # disclosure: tell the client whether the answer left the device (cloud narration) or stayed local
        narrated_by = f"{llm.model()} (cloud)" if use_llm else "local (deterministic)"

        def gen():
            if use_llm:
                for chunk in llm.narrate_stream(req.question, op, result, deterministic):
                    yield f"data: {json.dumps({'delta': chunk})}\n\n"
            else:
                for word in deterministic.split(" "):
                    yield f"data: {json.dumps({'delta': word + ' '})}\n\n"
            yield "data: " + json.dumps({
                "done": True,
                "routed_op": op,
                "narrated_by": narrated_by,
                "evidence_envelope": env,
                "citations": [{"op": op, "finding_state": env.get("finding_state"),
                               "answer_readiness": env.get("answer_readiness")}],
            }) + "\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/actions/done")
    def action_done(req: ActionDoneRequest, subject: str = Depends(require_device)) -> dict:
        """The Act→Learn loop: log that the user acted on a decision (journal note + structured ref)."""
        return pool.dispatch(subject, "journal.append", {
            "kind": "note",
            "text": req.note or f"Marked done: {req.action_id}",
            "tool": "decision.today",
            "refs": {"action_id": req.action_id, "status": "done"},
        })

    return app
