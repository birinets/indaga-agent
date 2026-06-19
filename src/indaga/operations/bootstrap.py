"""Populate the operation registry by importing the admin + capability modules.

Import side effects register the operations. Call ``load_all()`` once at server /
CLI startup before listing or dispatching tools.
"""

from __future__ import annotations

_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    from . import admin  # noqa: F401 — registers indaga.*
    from ..capabilities import (  # noqa: F401 — import side effects register the ops
        analyze,
        clock,
        domains,
        genome,
        grounding,
        health_index,
        journal,
        labs,
        metabolic,
        nutrigenomics,
        synthesis,
    )
    from . import annotations  # consent/egress matrix — enrich after every op is registered
    annotations.apply()
    _loaded = True
