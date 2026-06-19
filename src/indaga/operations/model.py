"""Operation model + execution context (mirrors genomi/operations/registry/model.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


class OperationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_json(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message}


@dataclass
class Context:
    """Per-call execution context handed to every operation handler."""

    subject_id: str
    store: Any                       # HealthlakeStore (the Active Health Index)
    surface: Any = None              # store.Surface
    user_dir: str | None = None
    now: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[dict, Context], dict]

# MCP 2025-11-25 lets a tool advertise an outputSchema; the result then carries structuredContent that
# satisfies it. Every Indaga handler returns a JSON object that (almost always) includes the typed
# evidence_envelope — a permissive default that advertises that shape without over-claiming (properties
# are optional in JSON Schema, so the admin tools that return other shapes still validate).
_DEFAULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_envelope": {
            "type": "object",
            "description": "Answer-readiness envelope: finding_state, answer_readiness, "
                           "negative_inference, coverage, observations.",
        }
    },
}


@dataclass(frozen=True)
class Operation:
    name: str                        # "<namespace>.<verb>", e.g. "clock.state"
    handler: Handler
    capability: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    skill: str | None = None
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    privacy_scope: str | None = None
    operation_scope: str = "read"    # read | write
    mutating: bool = False
    data_access: tuple[str, ...] = ()
    external_io: tuple[str, ...] = ()
    discovery_role: str = "focused_tool"   # base | entry_tool | focused_tool
    omic_scope: str = "multi"        # genomic | lab | wearable | cgm | derived | multi

    def tool_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema or {"type": "object", "properties": {}},
            "outputSchema": self.output_schema or _DEFAULT_OUTPUT_SCHEMA,
            "annotations": {
                "capability": self.capability,
                "skill": self.skill,
                "requires": list(self.requires),
                "produces": list(self.produces),
                "privacyScope": self.privacy_scope,
                "operationScope": self.operation_scope,
                "mutating": self.mutating,
                "dataAccess": list(self.data_access),
                "externalIO": list(self.external_io),
                "discoveryRole": self.discovery_role,
                "omicScope": self.omic_scope,
            },
        }
