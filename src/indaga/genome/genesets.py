"""Reactome pathway gene sets — gene → pathway memberships for analytical grounding (LOCAL).

Parses the Reactome GMT (gene-symbol gene sets, one pathway per line:
``<pathway_name>\\t<R-HSA-stable-id>\\t<gene>\\t<gene>...``) into an in-memory reverse index
gene→pathways. The collection is small (~2,800 pathways / ~1 MB), so it is loaded once per process
and cached by a source fingerprint — no SQLite build step (unlike the range-queried gene model).

This is the offline equivalent of the kind of context Genomi pulls from the live Reactome API: same
biology, but the gene-of-interest never leaves the device. stdlib only.
"""

from __future__ import annotations

from ..reference import manager as refmgr

# process-level cache, keyed by source fingerprint (path:size:mtime)
_CACHE: dict[str, "GeneSets"] = {}


class GeneSets:
    """Read side of the Reactome pathway gene sets — a reverse index from gene symbol to the
    pathways that contain it. Symbols are matched case-insensitively (stored upper-cased)."""

    def __init__(self, by_gene: dict[str, list[tuple[str, str]]], n_sets: int) -> None:
        self._by_gene = by_gene  # UPPER(symbol) -> [(pathway_name, pathway_id), ...]
        self.n_sets = n_sets

    @classmethod
    def open(cls) -> "GeneSets | None":
        # read-only grounding: use an already-installed GMT; never trigger a download
        gmt = refmgr.ensure_reactome_gmt(auto_install=False)
        if gmt is None:
            return None
        st = gmt.stat()
        key = f"{gmt}:{st.st_size}:{int(st.st_mtime)}"
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        by_gene: dict[str, list[tuple[str, str]]] = {}
        n_sets = 0
        try:
            with gmt.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) < 3:
                        continue  # need a name, an id, and at least one gene
                    name, pid = cols[0], cols[1]
                    n_sets += 1
                    for g in cols[2:]:
                        g = g.strip()
                        if g:
                            by_gene.setdefault(g.upper(), []).append((name, pid))
        except OSError:
            return None
        gs = cls(by_gene, n_sets)
        _CACHE[key] = gs
        return gs

    def pathways_for_gene(self, gene: str) -> list[dict]:
        """Pathways whose gene set contains ``gene`` (case-insensitive), as ``{id, name}`` dicts,
        in file order. Empty if the gene is in no Reactome pathway."""
        return [{"id": pid, "name": name}
                for name, pid in self._by_gene.get(gene.strip().upper(), [])]
