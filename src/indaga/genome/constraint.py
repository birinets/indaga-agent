"""Gene LoF-constraint lookup (gnomAD) — the LoF-intolerance evidence for ACMG PVS1.

A gene where loss-of-function is depleted in the population (high pLI / low LOEUF) is
'LoF-intolerant' — a null variant there is more likely disease-causing (PVS1). Loaded once
from the gnomAD v4.1 constraint TSV (MANE-select transcript per gene), cached in-process.
"""

from __future__ import annotations

from ..reference import manager as refmgr

_cache: dict[str, tuple[float | None, float | None]] | None = None

# ACMG thresholds (common practice): pLI≥0.9 OR LOEUF<0.35 → LoF-intolerant.
PLI_INTOLERANT = 0.9
LOEUF_INTOLERANT = 0.35


def _f(x: str) -> float | None:
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _load() -> dict[str, tuple[float | None, float | None]]:
    global _cache
    if _cache is not None:
        return _cache
    out: dict[str, tuple[float | None, float | None]] = {}
    path = refmgr.ensure_constraint()
    if path is None:
        _cache = out
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        col = {name: i for i, name in enumerate(header)}
        gi, pli_i, loeuf_i = col.get("gene"), col.get("lof.pLI"), col.get("lof.oe_ci.upper")
        mane_i = col.get("mane_select")
        if gi is None:
            _cache = out
            return out
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) <= max(gi, pli_i or 0, loeuf_i or 0):
                continue
            gene = f[gi]
            if not gene:
                continue
            is_mane = (mane_i is not None and f[mane_i].lower() == "true")
            # prefer the MANE-select transcript; else keep the most-constrained (min LOEUF)
            pli = _f(f[pli_i]) if pli_i is not None else None
            loeuf = _f(f[loeuf_i]) if loeuf_i is not None else None
            cur = out.get(gene)
            if cur is None or is_mane or (loeuf is not None and (cur[1] is None or loeuf < cur[1])):
                out[gene] = (pli, loeuf)
    _cache = out
    return out


def constraint_for(gene: str | None) -> dict | None:
    """{pli, loeuf, lof_intolerant} for a gene symbol, or None if not in the table."""
    if not gene:
        return None
    d = _load()
    v = d.get(gene) or d.get(gene.upper())
    if v is None:
        return None
    pli, loeuf = v
    intolerant = (pli is not None and pli >= PLI_INTOLERANT) or \
                 (loeuf is not None and loeuf < LOEUF_INTOLERANT)
    return {"pli": pli, "loeuf": loeuf, "lof_intolerant": intolerant}
