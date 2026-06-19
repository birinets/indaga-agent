"""Indaga home-dir layout (mirrors genomi/runtime/paths.py).

All persistent state lives under a single home dir:

    ~/.indaga/                          (INDAGA_HOME env, or XDG_DATA_HOME/indaga on Linux)
      registry.sqlite                   subjects, profiles, default subject, approvals
      shared-evidence.sqlite            cross-subject public reference evidence
      reference/                        downloaded reference libraries
      tools/                            managed binaries (pharmcat.jar, ...)
      <subject_slug>/
        active-health-index.sqlite      multi-omic facts/timeseries index
        active-genome-index.sqlite      genomic AGI (Phase 3)
        evidence.sqlite                 per-subject materialized evidence
        journal.sqlite                  investigation memory
        manifests/ source/ work/

The capability handlers never reference these paths — only the *local adapter*
does. Hosted/zero-knowledge adapters ignore this layout entirely. stdlib only.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def indaga_home() -> Path:
    env = os.environ.get("INDAGA_HOME")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and sys.platform.startswith("linux"):
        return Path(xdg).expanduser() / "indaga"
    return Path.home() / ".indaga"


def subject_slug(subject_id: str) -> str:
    slug = _SLUG_RE.sub("-", subject_id.strip().lower()).strip("-")
    return slug or "subject"


# -- least-privilege hardening ---------------------------------------------- #
# Personal genome/health data must not be world- or group-readable. Neither this nor the upstream
# genome agent chmod'd their SQLite/VCF stores, so they inherited the process umask (0644 files /
# 0755 dirs on a default umask) — readable by any other account on a shared host, backup, or volume.
# We chmod every personal-data file to 0600 and every personal-data dir to 0700 at creation.

def secure_dir(path: str | Path) -> Path:
    """mkdir -p the dir and lock it to 0700 (owner-only). Best-effort (no-op where chmod is moot)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def secure_file(path: str | Path) -> None:
    """Lock an existing personal-data file to 0600 (owner read/write only). Best-effort."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def secure_subject_tree(subject_id: str) -> None:
    """Harden an existing subject's on-disk store in place: 0700 dirs, 0600 files. Idempotent
    migration so stores written before least-privilege hardening (0644/0755) get locked down on
    the next context build."""
    base = subject_dir(subject_id)
    if not base.exists():
        return
    secure_dir(base)
    for p in base.rglob("*"):
        if p.is_dir():
            try:
                os.chmod(p, 0o700)
            except OSError:
                pass
        else:
            secure_file(p)


# -- home-level paths ------------------------------------------------------- #

def registry_path() -> Path:
    return indaga_home() / "registry.sqlite"


def shared_evidence_path() -> Path:
    return indaga_home() / "shared-evidence.sqlite"


def reference_dir() -> Path:
    return indaga_home() / "reference"


def resources_dir() -> Path:
    return indaga_home() / "resources"


def tools_dir() -> Path:
    return indaga_home() / "tools"


def gnomad_cache_path() -> Path:
    return indaga_home() / "gnomad_cache.json"


# -- per-subject paths ------------------------------------------------------ #

def subject_dir(subject_id: str) -> Path:
    return indaga_home() / subject_slug(subject_id)


def active_health_index_path(subject_id: str) -> Path:
    return subject_dir(subject_id) / "active-health-index.sqlite"


def active_genome_index_path(subject_id: str) -> Path:
    return subject_dir(subject_id) / "active-genome-index.sqlite"


def evidence_path(subject_id: str) -> Path:
    return subject_dir(subject_id) / "evidence.sqlite"


def journal_path(subject_id: str) -> Path:
    return subject_dir(subject_id) / "journal.sqlite"


def manifests_dir(subject_id: str) -> Path:
    return subject_dir(subject_id) / "manifests"


def source_dir(subject_id: str) -> Path:
    return subject_dir(subject_id) / "source"


def work_dir(subject_id: str) -> Path:
    return subject_dir(subject_id) / "work"


def ensure_subject_dirs(subject_id: str) -> Path:
    """Create the per-subject directory tree (owner-only 0700); return the subject dir."""
    secure_dir(indaga_home())  # lock the top-level home too (0700)
    base = subject_dir(subject_id)
    for d in (base, manifests_dir(subject_id), source_dir(subject_id), work_dir(subject_id)):
        secure_dir(d)
    reference_dir().mkdir(parents=True, exist_ok=True)
    tools_dir().mkdir(parents=True, exist_ok=True)
    return base
