"""The operation registry + dispatch (mirrors genomi/operations/registry/table.py).

Capability modules `register(Operation(...))` at import time; `bootstrap.load_all`
imports them. `tools/list` shows only `base_operations()`; everything else is
reached via `indaga.invoke` → `call_operation`.
"""

from __future__ import annotations

from ._schema import validate_params
from .model import Context, Operation, OperationError

_REGISTRY: dict[str, Operation] = {}


def register(op: Operation) -> None:
    _REGISTRY[op.name] = op


def get_operation(name: str) -> Operation:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise OperationError("unknown_tool", f"Unknown operation: {name}") from exc


def all_operations() -> list[Operation]:
    return list(_REGISTRY.values())


def base_operations() -> list[Operation]:
    """Operations exposed directly in MCP tools/list — the base/admin set plus
    each capability's entry tool. Everything else is invoke-only."""
    return [
        op for op in _REGISTRY.values()
        if op.capability == "indaga" or op.discovery_role in ("base", "entry_tool")
    ]


def call_operation(name: str, params: dict | None, context: Context) -> dict:
    op = get_operation(name)
    # Dispatch-time contract: validate params against the operation's input_schema BEFORE running the
    # handler, so a malformed call becomes a typed OperationError('invalid_params', ...) the caller can
    # act on — not a handler crash or a silently-wrong answer.
    validate_params(op.input_schema, params, op.name)
    # Accountability: append this access (tool + data domains + egress + mutating) to the subject's
    # append-only audit log. Best-effort; never blocks the call.
    from ..runtime import audit, observability
    audit.record_access(context, op)
    # Observability: time the dispatch + record a span (ok|error) for per-tool latency/error metrics.
    with observability.operation_span(context, op):
        return op.handler(params or {}, context)
