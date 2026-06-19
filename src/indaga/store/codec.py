"""Shared (de)serialization helpers for the Healthlake store + connectors.

Dates are stored as ISO strings, enums/caveats as JSON. Kept in one place so the
DuckDB adapter and the ingestion connectors encode/decode facts identically.

stdlib only.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from .types import Caveat, CaveatCode, Severity


def iso(v) -> str | None:
    return v.isoformat() if v is not None else None


def parse_dt(s) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def parse_dateish(s):
    """Parse an ISO string back to a ``date`` (len 10) or ``datetime``."""
    if not s:
        return None
    return date.fromisoformat(s) if len(s) == 10 else datetime.fromisoformat(s)


def num(x) -> float | None:
    if x is None or x == "" or x == "NA":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def dump_caveats(caveats) -> str:
    return json.dumps([
        {"code": c.code.value, "text": c.text, "severity": c.severity.value}
        for c in caveats
    ])


def load_caveats(s) -> tuple[Caveat, ...]:
    if not s:
        return ()
    return tuple(
        Caveat(CaveatCode(d["code"]), d["text"], Severity(d["severity"]))
        for d in json.loads(s)
    )
