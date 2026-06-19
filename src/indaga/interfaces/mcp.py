"""Indaga MCP server — stdio JSON-RPC over the operation registry.

Mirrors genomi/interfaces/mcp.py at the level Phase 1 needs: `initialize`,
`tools/list` (returns only the **base set** — progressive disclosure), `tools/call`
(dispatches via `call_operation`, non-base tools reached through `indaga.invoke`).
Dependency-free transport; the persistent Active Health Index is built once per
subject and reused (the persistence payoff — subsequent starts skip re-ingest).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..operations import base_operations, bootstrap, call_operation
from ..operations.model import Context, OperationError
from ..store import Scope, Surface
from ..store.sqlite_store import LocalSQLiteStore

# MCP protocol: prefer the current spec, but echo back a client's requested version when we support it
# (graceful negotiation) rather than hardcoding a single string.
PROTOCOL_VERSION = "2025-11-25"
_SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "indaga", "version": "0.1"}


def _negotiate_version(requested: str | None) -> str:
    """Return the requested protocol version if we support it, else our latest."""
    return requested if requested in _SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION


# -- store/context assembly ------------------------------------------------- #

def _ingest(store: LocalSQLiteStore, subject_id: str, user_dir: str, hr_limit: int) -> None:
    from ..connectors.silver_labs import ingest_silver_labs
    from ..connectors.wearables import ingest_glucose_summary, ingest_hr_series

    base = Path(user_dir)
    labs = base / "healthlake" / "silver" / "tables" / "observations.csv"
    if labs.exists():
        ingest_silver_labs(store, subject_id, str(labs))
    hr = base / "wearables" / "parsed" / "hr_series.json"
    if hr.exists():
        ingest_hr_series(store, subject_id, str(hr), limit=hr_limit)
    glu = base / "wearables" / "parsed" / "glucose.json"
    if glu.exists():
        ingest_glucose_summary(store, subject_id, str(glu))
    # Genome → build the Active Genome Index (LOCAL: Indaga's own imputed genome if available, else the
    # raw chip). Annotation (ClinVar P/LP screen + PGS) is NOT run here: it queries gnomAD and may
    # download ClinVar — network egress that must not happen implicitly at server startup before the
    # subject consents. It is the explicit, egress-declared `genome.annotate` tool; until it runs, the
    # genome evidence tools honestly report "not annotated yet". (An already-annotated subject keeps its
    # persisted evidence.sqlite, so this only affects a never-before-annotated subject.)
    from ..connectors.dna import ingest_genome
    if ingest_genome(store, subject_id, user_dir):
        print("[indaga] Active Genome Index built (local); run genome.annotate for the ClinVar/PGS "
              "screen (network egress — gnomAD/ClinVar).", file=sys.stderr)


def build_context(subject_id: str, user_dir: str, *, hr_limit: int = 20000,
                  surface: Surface = Surface.APP, rebuild: bool = False) -> Context:
    """Open the persistent Active Health Index for a subject; ingest + run the
    deterministic spine only on first build (or when ``rebuild``)."""
    bootstrap.load_all()
    from ..runtime import audit, paths
    paths.secure_subject_tree(subject_id)  # least-privilege: lock this subject's store (0600/0700)
    # the single authorized read path: minting a Context requires a grant. Locally the owner is
    # auto-authorized for their own on-disk subject (recorded for the audit trail); a hosted server
    # swaps LocalOwnerAuth for an authenticated AuthAdapter that can refuse.
    if not audit.LocalOwnerAuth().authorize(subject_id, surface=getattr(surface, "value", "app")):
        raise OperationError("not_authorized", f"not authorized for subject {subject_id!r}")
    store = LocalSQLiteStore.for_subject(subject_id)
    scope = Scope(subject_id, surface=surface)
    if rebuild or not store.list_sources(scope):
        _ingest(store, subject_id, user_dir, hr_limit)
        from ..spine import BiologicalClock, CGMMetabolic
        for service in (BiologicalClock(), CGMMetabolic()):
            try:
                service.run(store, scope)
            except Exception as exc:  # noqa: BLE001 — startup resilience
                print(f"[indaga] spine {service.name} skipped: {exc}", file=sys.stderr)
    return Context(subject_id=subject_id, store=store, surface=surface,
                   user_dir=user_dir, now=datetime.now(timezone.utc))


# -- JSON-RPC --------------------------------------------------------------- #

def _result(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


class IndagaMCPServer:
    def __init__(self, context: Context) -> None:
        self.context = context

    def handle(self, req: dict) -> dict | None:
        method = req.get("method")
        rid = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            return _result(rid, {
                "protocolVersion": _negotiate_version(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            })
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return _result(rid, {})
        if method == "tools/list":
            return _result(rid, {"tools": [op.tool_definition() for op in base_operations()]})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                result = call_operation(name, args, self.context)
            except OperationError as exc:
                return _result(rid, {"content": [{"type": "text", "text": json.dumps(exc.to_json())}],
                                     "structuredContent": exc.to_json(), "isError": True})
            except Exception as exc:  # noqa: BLE001
                return _result(rid, {"content": [{"type": "text", "text": f"tool error: {exc}"}], "isError": True})
            # MCP 2025-11-25: return the structured object as `structuredContent` (matching the tool's
            # outputSchema) alongside the text content (kept for clients that don't read structuredContent).
            return _result(rid, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result,
                "isError": False,
            })
        return _error(rid, -32601, f"unknown method: {method}")

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def serve_stdio(context: Context) -> None:
    IndagaMCPServer(context).run()
