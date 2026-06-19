"""Minimal stdlib JSON-Schema validation for dispatch-time parameter checking.

Indaga is stdlib-only (AGENTS.md), so rather than pull in `jsonschema` this validates exactly the
JSON-Schema subset our `Operation.input_schema` declarations actually use:
``type`` (object/string/integer/number/boolean/array/null), ``properties``, ``required``, ``enum``,
``items``. It is the dispatch-time gate (``operations.registry.call_operation``) that turns a malformed
tool call into a typed ``OperationError('invalid_params', ...)`` — a structured rejection an agent can
act on — instead of a handler crash or a silently-wrong answer. Unknown keys are allowed (handlers
ignore extras); full JSON-Schema 2020-12 compliance is the P2 MCP-2025-11-25 upgrade.
"""

from __future__ import annotations

from typing import Any

from .model import OperationError

_PY_TYPE = {"string": str, "object": dict, "array": list, "boolean": bool, "null": type(None)}


def _type_ok(jtype: str, value: Any) -> bool:
    # integer/number must exclude bool (bool is an int subclass in Python).
    if jtype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if jtype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    pytype = _PY_TYPE.get(jtype)
    return True if pytype is None else isinstance(value, pytype)


def _validate(schema: dict, value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        return
    jtype = schema.get("type")
    if jtype and not _type_ok(jtype, value):
        errors.append(f"{path}: expected {jtype}, got {type(value).__name__}")
        return  # a type mismatch makes deeper checks meaningless
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
        return
    if isinstance(value, dict) and (jtype == "object" or "properties" in schema or "required" in schema):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}.{req}: required")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                _validate(sub, value[key], f"{path}.{key}", errors)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, element in enumerate(value):
            _validate(schema["items"], element, f"{path}[{i}]", errors)


def validate_params(schema: dict | None, params: dict | None, op_name: str) -> None:
    """Raise ``OperationError('invalid_params', ...)`` when ``params`` violate the operation's
    ``input_schema``. An empty/None schema validates trivially; None params is treated as ``{}``."""
    if not schema:
        return
    errors: list[str] = []
    _validate(schema, {} if params is None else params, op_name, errors)
    if errors:
        raise OperationError("invalid_params", "; ".join(errors[:8]))
