"""Indaga operations — the Operation model, registry, and indaga.invoke dispatcher.

Mirrors genomi/operations: a flat registry of `Operation(name, handler, ...)`,
discovered via a catalog, with only a base set in MCP `tools/list` and everything
else reached through `indaga.invoke` after the agent loads the capability skill.
"""

from .model import Context, Operation, OperationError
from .registry import (
    all_operations,
    base_operations,
    call_operation,
    get_operation,
    register,
)

__all__ = [
    "Context",
    "Operation",
    "OperationError",
    "all_operations",
    "base_operations",
    "call_operation",
    "get_operation",
    "register",
]
