"""Gateway settings — resolved once from the environment.

A personal server serves exactly one owner/subject. `INDAGA_USER_DIR` only matters on a never-built
subject (it is the ingest source dir); once the Active Health Index exists, ingest is skipped and the
store under ~/.indaga/<subject> is reused.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    subject: str
    user_dir: str
    host: str
    port: int
    allow_insecure: bool  # dev-only: skip device-token auth (never set on a reachable server)

    @classmethod
    def from_env(cls) -> "Settings":
        from indaga.runtime import paths

        subject = os.environ.get("INDAGA_SUBJECT", "demo")
        # default user_dir = the subject's own store dir; harmless because ingest is skipped once built.
        user_dir = os.environ.get("INDAGA_USER_DIR") or str(paths.subject_dir(subject))
        host = os.environ.get("INDAGA_GATEWAY_HOST", "127.0.0.1")
        port = int(os.environ.get("INDAGA_GATEWAY_PORT", "8765"))
        allow_insecure = os.environ.get("INDAGA_GATEWAY_ALLOW_INSECURE", "") == "1"
        return cls(subject=subject, user_dir=user_dir, host=host, port=port, allow_insecure=allow_insecure)
