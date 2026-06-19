"""
report_kit — shared design system for Indaga HTML reports.

Public surface:
    from report_kit import build_report, RefCollector, components as C, charts, i18n
"""
from __future__ import annotations

from . import charts, components, i18n, references, theme
from .page import build_report
from .references import REGISTRY, RefCollector, Reference

__all__ = [
    "build_report", "RefCollector", "Reference", "REGISTRY",
    "charts", "components", "i18n", "references", "theme",
]
