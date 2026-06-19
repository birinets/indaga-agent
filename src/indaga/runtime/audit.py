"""Capability access control — a per-session subject GRANT + a per-read AUDIT log.

The architecture review's gap: Indaga accepted an arbitrary ``--subject`` with NO authorization and NO
access trail (Genomi has a single sanctioned reader but still no per-read audit). This adds both, at the
two right seams:

  * the GRANT is the single authorized read path — minting a `Context` for a subject requires a grant
    (`build_context` calls `grant_local` for the local owner; a hosted server swaps in an `AuthAdapter`
    that authenticates + authorizes). Holding a Context therefore means "authorized for this subject".
  * the AUDIT records every operation dispatch (`call_operation`) to the subject's append-only
    ``~/.indaga/<subject>/audit.jsonl`` — what tool, which data domains, what network egress, mutating? —
    reusing the consent/egress annotations populated in P1.2. So there is an accountability trail of what
    touched the genome and what left the machine.

Local-first + best-effort: a subject with no on-disk store (e.g. an in-memory unit test) is not audited
(we never create a directory just to log), and auditing must NEVER break a tool call.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from . import paths


def _grant_path(subject_id: str):
    return paths.subject_dir(subject_id) / "access-grant.json"


def _audit_path(subject_id: str):
    return paths.subject_dir(subject_id) / "audit.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- session grant ---------------------------------------------------------- #

def grant_local(subject_id: str, *, surface: str = "app", reason: str = "local owner (auto)") -> None:
    """Record a session grant for the LOCAL owner's own subject (idempotent). A hosted adapter
    replaces this with an authenticated grant (see AuthAdapter). No-op if the subject has no store
    on disk yet (nothing to authorize against)."""
    d = paths.subject_dir(subject_id)
    if not d.exists() or _grant_path(subject_id).exists():
        return
    paths.secure_dir(d)
    p = _grant_path(subject_id)
    p.write_text(json.dumps({"subject_id": subject_id, "surface": surface, "reason": reason,
                             "granted_at": _now_iso()}), encoding="utf-8")
    paths.secure_file(p)


def is_granted(subject_id: str) -> bool:
    return _grant_path(subject_id).exists()


def revoke(subject_id: str) -> None:
    _grant_path(subject_id).unlink(missing_ok=True)


@runtime_checkable
class AuthAdapter(Protocol):
    """The hosted extension point: a server swaps the local-owner grant for an authenticated check
    (OAuth/RBAC). ``authorize`` decides whether the caller may mint a Context for ``subject_id``."""

    def authorize(self, subject_id: str, *, surface: str) -> bool: ...


class LocalOwnerAuth:
    """Default adapter: the local owner is authorized for their own on-disk subjects; the grant is
    recorded for the audit trail."""

    def authorize(self, subject_id: str, *, surface: str = "app") -> bool:
        grant_local(subject_id, surface=surface)
        return True


# -- per-read audit log ----------------------------------------------------- #

def record_access(context: Any, op: Any) -> None:
    """Append one access record to the subject's append-only audit log. Best-effort + local-only:
    skips subjects with no on-disk store, and never raises into the caller."""
    try:
        subject = getattr(context, "subject_id", None)
        if not subject or not paths.subject_dir(subject).exists():
            return
        now = getattr(context, "now", None)
        rec = {
            "ts": now.isoformat() if now else _now_iso(),
            "subject": subject,
            "tool": op.name,
            "capability": op.capability,
            "surface": getattr(getattr(context, "surface", None), "value", None),
            "privacy_scope": op.privacy_scope,
            "data_access": list(op.data_access),
            "external_io": list(op.external_io),  # network egress (gnomad / reference_download)
            "mutating": op.mutating,
        }
        p = _audit_path(subject)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        paths.secure_file(p)
    except Exception:  # noqa: BLE001 — auditing must never break a tool call
        pass


def read_audit(subject_id: str, *, limit: int = 50) -> list[dict]:
    """The most recent ``limit`` audit records for a subject (newest last), or [] if none."""
    p = _audit_path(subject_id)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
