"""Base admin operations: the indaga.* tools (always in tools/list).

`indaga.invoke` is the dispatcher; `indaga.describe_context` reports the subject's
connected sources + available capabilities (mirrors genomi.describe_context).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .model import Context, Operation, OperationError
from .registry import all_operations, call_operation, register

# skills/ lives at the repo root (Indaga-agent/skills/); override with INDAGA_SKILLS.
# __file__ = <repo>/src/indaga/operations/admin.py → parents[3] = <repo>.
import os as _os

_SKILLS_ROOT = Path(
    _os.environ.get("INDAGA_SKILLS") or (Path(__file__).resolve().parents[3] / "skills")
).resolve()


def _indaga_invoke(params: dict, context: Context) -> dict:
    tool = params.get("tool")
    inner = params.get("params") or {}
    if not isinstance(tool, str) or "." not in tool:
        raise OperationError("invalid_tool", "indaga.invoke requires a 'tool' name like 'clock.state'")
    result = call_operation(tool, inner, context)
    if isinstance(result, dict):
        return {"dispatched_tool": tool, **result}
    return {"dispatched_tool": tool, "result": result}


def _indaga_describe_context(params: dict, context: Context) -> dict:
    from ..store import Scope

    scope = Scope(context.subject_id, surface=context.surface) if context.surface else Scope(context.subject_id)
    store = context.store
    return {
        "subject_id": context.subject_id,
        "sources": [s.label for s in store.list_sources(scope)],
        "fact_count": len(store.get_facts(scope)),
        "capabilities": sorted({op.capability for op in all_operations()}),
    }


def _indaga_list_capabilities(params: dict, context: Context) -> dict:
    caps: dict[str, dict] = defaultdict(lambda: {"skill": None, "tools": []})
    for op in all_operations():
        entry = caps[op.capability]
        entry["tools"].append({
            "name": op.name, "discovery_role": op.discovery_role,
            "omic_scope": op.omic_scope, "description": op.description,
        })
        if op.skill:
            entry["skill"] = op.skill
    return {"root_skill": "skills/SKILL.md", "capabilities": dict(caps)}


def _indaga_check_libraries(params: dict, context: Context) -> dict:
    from ..reference import check_all
    return check_all()


def _indaga_install(params: dict, context: Context) -> dict:
    from ..reference import install
    ids = params.get("libraries")
    force = bool(params.get("force"))
    return install(ids, force=force)


def _indaga_check_background_job(params: dict, context: Context) -> dict:
    from ..runtime import jobs
    jid = params.get("job_id")
    if jid:
        return jobs.job_status(context.subject_id, jid)
    return {"jobs": jobs.list_jobs(context.subject_id)}


def _indaga_access_log(params: dict, context: Context) -> dict:
    from ..runtime import audit
    limit = int(params.get("limit", 50))
    return {"subject_id": context.subject_id, "granted": audit.is_granted(context.subject_id),
            "access_log": audit.read_audit(context.subject_id, limit=limit)}


def _indaga_read_skill(params: dict, context: Context) -> dict:
    rel = params.get("skill_path")
    cap = params.get("capability")
    if not rel:
        rel = f"skills/{cap}/SKILL.md" if cap else "skills/SKILL.md"
    target = (_SKILLS_ROOT.parent / rel).resolve()
    if not str(target).startswith(str(_SKILLS_ROOT)):
        raise OperationError("invalid_skill_path", f"refusing path outside skills/: {rel!r}")
    if not target.exists():
        raise OperationError("skill_not_found", f"no skill at {rel!r}")
    return {"skill_path": rel, "content": target.read_text(encoding="utf-8")}


register(Operation(
    "indaga.list_capabilities", _indaga_list_capabilities, capability="indaga",
    description="List Indaga capabilities, their tools, and skill paths. Start here to discover what to load.",
    input_schema={"type": "object", "properties": {}},
    discovery_role="base",
))

register(Operation(
    "indaga.read_skill", _indaga_read_skill, capability="indaga",
    description="Fetch a capability's SKILL.md (or the root skill) so you can learn its focused tools "
                "before calling them via indaga.invoke.",
    input_schema={"type": "object", "properties": {
        "capability": {"type": "string", "description": "e.g. 'circadian', 'labs', 'metabolic'"},
        "skill_path": {"type": "string", "description": "explicit path under skills/ (optional)"}}},
    discovery_role="base",
))


register(Operation(
    "indaga.invoke", _indaga_invoke, capability="indaga",
    description="Dispatch any non-base capability tool by qualified name (after reading its skill).",
    input_schema={
        "type": "object",
        "properties": {"tool": {"type": "string"}, "params": {"type": "object"}},
        "required": ["tool"],
    },
    discovery_role="base",
))

register(Operation(
    "indaga.describe_context", _indaga_describe_context, capability="indaga",
    description="Describe the current subject: connected data sources, fact count, available capabilities.",
    input_schema={"type": "object", "properties": {}},
    discovery_role="base",
))

register(Operation(
    "indaga.check_libraries", _indaga_check_libraries, capability="indaga",
    description="Report which reference libraries (ClinVar, gnomAD, PGS, …) are installed under "
                "~/.indaga, what's missing, and the install command for each missing one.",
    input_schema={"type": "object", "properties": {}},
    discovery_role="base",
))

register(Operation(
    "indaga.install", _indaga_install, capability="indaga",
    description="Download reference libraries into ~/.indaga. Omit 'libraries' to install the "
                "phase-A core (ClinVar + PGS metadata). 'force' re-fetches installed libraries.",
    input_schema={"type": "object", "properties": {
        "libraries": {"type": "array", "items": {"type": "string"},
                      "description": "library ids, e.g. ['clinvar-grch38','pgs-catalog-metadata']"},
        "force": {"type": "boolean"}}},
    discovery_role="base",
    mutating=True,
))

register(Operation(
    "indaga.check_background_job", _indaga_check_background_job, capability="indaga",
    description="Poll a long-running background job (e.g. genome.impute) by job_id, or list "
                "the subject's jobs. Returns status + a log tail.",
    input_schema={"type": "object", "properties": {"job_id": {"type": "string"}}},
    discovery_role="base",
))

register(Operation(
    "indaga.access_log", _indaga_access_log, capability="indaga",
    description="The subject's capability-access audit trail: each tool call recorded with the data "
                "domains it read, the network egress it performed, and whether it mutated state — plus "
                "the session-grant status. The accountability record for what touched the genome.",
    input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}},
    discovery_role="base",
))
