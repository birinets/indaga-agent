"""Evidence-store connections + the ATTACH-blend (mirrors genomi/evidence/store/connection.py).

A subject read opens the per-subject ``evidence.sqlite`` and ATTACHes the shared
``shared-evidence.sqlite`` as ``shared`` — one connection sees both, so a ClinVar
lookup (shared) and a P/LP finding (subject) join in one SQL. The shared DB is the
heavy, cross-subject reference; the subject DB is small and private. stdlib only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ...runtime import paths
from . import schema

SHARED_ALIAS = "shared"


def _connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    # personal evidence: lock the DB + its WAL/SHM sidecars to owner-only (0600).
    for f in (p, Path(f"{p}-wal"), Path(f"{p}-shm")):
        if f.exists():
            paths.secure_file(f)
    return con


def init_shared(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (creating) the shared evidence DB with its schema ensured."""
    con = _connect(path or paths.shared_evidence_path())
    con.executescript(schema.SHARED_SCHEMA)
    try:  # migrate: ClinVar molecular-consequence column added after first release
        con.execute("ALTER TABLE clinvar_variants ADD COLUMN mc TEXT")
    except sqlite3.OperationalError:
        pass  # already present
    try:  # migrate: GWAS -log10(p) column (the underflow-safe significance key)
        con.execute("ALTER TABLE gwas_associations ADD COLUMN mlog REAL")
    except sqlite3.OperationalError:
        pass  # already present
    con.commit()
    return con


def ensure_shared_indexes(con: sqlite3.Connection) -> None:
    for ddl in schema.SHARED_INDEXES:
        con.execute(ddl)
    con.commit()


# columns added to pl_findings after its first release — ALTER-migrated so existing
# evidence DBs (and their PGS results) are preserved across upgrades.
_PL_MIGRATION_COLUMNS = (
    ("zygosity", "TEXT"), ("inheritance", "TEXT"),
    ("carrier_status", "TEXT"), ("interpretation", "TEXT"),
    ("directly_typed", "INTEGER"), ("confidence", "TEXT"), ("review_stars", "INTEGER"),
)


def init_subject(path: str | Path, *, shared_path: str | Path | None = None) -> sqlite3.Connection:
    """Open (creating) a subject evidence DB; record the shared-DB pointer for ATTACH.
    Idempotently migrates pl_findings to add later columns."""
    con = _connect(path)
    con.executescript(schema.SUBJECT_SCHEMA)
    for col, typ in _PL_MIGRATION_COLUMNS:
        try:
            con.execute(f"ALTER TABLE pl_findings ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # column already exists
    set_meta(con, "shared_evidence_db", str(shared_path or paths.shared_evidence_path()))
    con.commit()
    return con


def open_reader(subject_path: str | Path, *, attach_shared: bool = True) -> sqlite3.Connection | None:
    """Open a subject evidence DB read-side, ATTACHing the shared DB if available.

    Returns None if the subject DB does not exist yet (caller falls back).
    """
    p = Path(subject_path)
    if not p.exists():
        return None
    con = _connect(p)
    if attach_shared:
        shared = get_meta(con, "shared_evidence_db") or str(paths.shared_evidence_path())
        if Path(shared).exists():
            con.execute(f"ATTACH DATABASE ? AS {SHARED_ALIAS}", (str(Path(shared).resolve()),))
    return con


# -- metadata helpers ------------------------------------------------------- #

def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(con: sqlite3.Connection, key: str, value) -> None:
    con.execute(
        "INSERT INTO metadata(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, None if value is None else str(value)),
    )


def has_shared_clinvar(con: sqlite3.Connection) -> bool:
    """True when the attached shared DB has a populated ClinVar table."""
    try:
        row = con.execute(f"SELECT 1 FROM {SHARED_ALIAS}.clinvar_variants LIMIT 1").fetchone()
        return row is not None
    except sqlite3.Error:
        return False
