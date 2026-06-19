"""HGNC entity-canon — map any gene identifier to the approved HGNC symbol, for grounding (LOCAL).

Grounding lookups are keyed by gene SYMBOL, but a finding may carry an old / alias / Entrez / Ensembl name
(ClinVar and GWAS rows are not symbol-normalised). This parses the HGNC complete gene set
(``symbol``, ``alias_symbol``, ``prev_symbol``, ``entrez_id``, ``ensembl_gene_id``; ~43 K genes) into an
in-memory reverse index ``any-name → approved symbol``, so a grounding query for ``LOC387715`` or an old
symbol still resolves. Loaded once per process, cached by source fingerprint. stdlib only.

Offline equivalent of the entity canonicalisation Genomi does via Ensembl/NCBI/HGNC services.
"""

from __future__ import annotations

from ..reference import manager as refmgr

_CACHE: dict[str, "GeneSymbols"] = {}


class GeneSymbols:
    """Read side of the HGNC entity-canon — resolve any name/id to its approved symbol."""

    def __init__(self, name_to_approved: dict[str, str]) -> None:
        self._map = name_to_approved  # UPPER(any name/id) -> approved symbol

    @classmethod
    def open(cls) -> "GeneSymbols | None":
        path = refmgr.ensure_hgnc(auto_install=False)  # read-only grounding: never download here
        if path is None:
            return None
        st = path.stat()
        key = f"{path}:{st.st_size}:{int(st.st_mtime)}"
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        amap: dict[str, str] = {}
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                header = fh.readline().rstrip("\n").split("\t")
                idx = {name: i for i, name in enumerate(header)}
                si = idx.get("symbol")
                if si is None:
                    return None
                alias_cols = [idx.get(c) for c in ("alias_symbol", "prev_symbol")]
                id_cols = [idx.get(c) for c in ("entrez_id", "ensembl_gene_id")]
                for line in fh:
                    c = line.rstrip("\n").split("\t")
                    if si >= len(c) or not c[si].strip():
                        continue
                    approved = c[si].strip()
                    amap[approved.upper()] = approved          # approved symbol maps to itself (wins)
                    for col in alias_cols:                     # pipe-separated alias / previous symbols
                        if col is not None and col < len(c) and c[col]:
                            for a in c[col].split("|"):
                                a = a.strip().strip('"')
                                if a:
                                    amap.setdefault(a.upper(), approved)
                    for col in id_cols:                        # Entrez / Ensembl ids (for numeric keys)
                        if col is not None and col < len(c) and c[col].strip():
                            amap.setdefault(c[col].strip().upper(), approved)
        except OSError:
            return None
        gs = cls(amap)
        _CACHE[key] = gs
        return gs

    def canonical(self, name: str | None) -> str | None:
        """The approved HGNC symbol for ``name`` (an alias / previous symbol / Entrez or Ensembl id), or
        the input unchanged if it isn't recognised (best-effort — never raises, never drops a query)."""
        if not name:
            return name
        return self._map.get(name.strip().upper(), name)
