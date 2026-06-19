"""Owned ancestry estimate — continental ancestry from the subject's imputed genome.

Indaga's ancestry stage reuses the **1000G-30x panel it already downloads for imputation**:
that panel carries per-superpopulation allele frequencies in INFO
(``AF_AFR/AMR/EAS/EUR/SAS_unrel``, from the 2,504 unrelated genomes). So ancestry needs no
extra reference — Indaga builds an **ancestry-informative-marker (AIM)** frequency table by
selecting high-Fst biallelic SNVs from the panel (cached once at
~/.indaga/reference/ancestry/aim_freqs.tsv), then assigns the subject's most likely
superpopulation by a **naive-Bayes likelihood** over the AIMs the subject carries (HWE
genotype probabilities under each population's allele frequency).

This is **nearest-superpopulation classification**, NOT admixture-fraction deconvolution
(that needs ADMIXTURE/RFMix + a labelled reference). The output says so honestly. stdlib +
bcftools (panel AF extraction) + the Active Genome Index.
"""

from __future__ import annotations

import itertools
import math
import subprocess
from pathlib import Path

from ..reference import manager as refmgr
from ..runtime import paths

SUPERPOPS = ("AFR", "AMR", "EAS", "EUR", "SAS")
_AUTOSOMES = [str(i) for i in range(1, 23)]
_EPS = 1e-6


def aim_reference_path() -> Path:
    return refmgr._resolve(Path("reference", "ancestry", "aim_freqs.tsv"))


def _norm_chrom(c: str) -> str:
    return c[3:] if c.lower().startswith("chr") else c


def build_aim_reference(*, prefilter_spread: float = 0.25, per_pair_per_chrom: int = 80,
                        force: bool = False) -> dict:
    """Build the AIM frequency table from the 1000G-30x panel, one-time + cached.

    Selection is **balanced per population-pair**: a single max−min spread filter is
    AFR-dominated (AFR is the most diverged superpopulation), so it under-represents the
    EUR/SAS/EAS/AMR distinctions and a European genome can mis-assign. Instead, for each of
    the 10 superpopulation pairs we keep the markers with the largest |ΔAF| for THAT pair
    (per chromosome), guaranteeing every continental distinction is represented."""
    out = aim_reference_path()
    if out.exists() and not force:
        n = sum(1 for _ in out.open()) - 1
        return {"status": "cached", "path": str(out), "markers": max(n, 0)}
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = "\t".join(f"%INFO/AF_{p}_unrel" for p in SUPERPOPS)
    pairs = list(itertools.combinations(range(len(SUPERPOPS)), 2))
    selected: dict[tuple[str, int], tuple] = {}
    chroms_used: list[str] = []
    for chrom in _AUTOSOMES:
        panel = refmgr.panel_chrom_path(chrom)
        if not panel.exists():
            continue
        chroms_used.append(chrom)
        cmd = ["bcftools", "query", "-i", 'TYPE="snp" && N_ALT=1',
               "-f", f"%CHROM\t%POS\t%REF\t%ALT\t{fields}\n", str(panel)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        cands: list[tuple] = []
        for line in proc.stdout.splitlines():
            f = line.split("\t")
            if len(f) < 4 + len(SUPERPOPS):
                continue
            try:
                afs = [float(x) for x in f[4:4 + len(SUPERPOPS)]]
            except ValueError:
                continue  # missing AF ('.') in some population
            if max(afs) - min(afs) < prefilter_spread:
                continue  # prune monomorphic-ish; keeps the pool small but pair-informative
            cands.append((_norm_chrom(f[0]), int(f[1]), f[2], f[3], afs))
        # for each population pair, keep the top markers by that pair's |ΔAF|
        for i, j in pairs:
            top = sorted(cands, key=lambda r: abs(r[4][i] - r[4][j]), reverse=True)[:per_pair_per_chrom]
            for r in top:
                selected[(r[0], r[1])] = r
    if not selected:
        return {"status": "failed", "reason": "no panel chromosomes present (run genome.impute first)"}
    rows = [(*key, r[2], r[3], *r[4]) for key, r in sorted(selected.items())]
    header = "chrom\tpos\tref\talt\t" + "\t".join(SUPERPOPS) + "\n"
    with out.open("w", encoding="utf-8") as fh:
        fh.write(header)
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    return {"status": "built", "path": str(out), "markers": len(rows), "chromosomes": chroms_used}


def _load_aims() -> dict[tuple[str, int], tuple[str, str, list[float]]]:
    out: dict[tuple[str, int], tuple[str, str, list[float]]] = {}
    p = aim_reference_path()
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        next(fh, None)  # header
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 4 + len(SUPERPOPS):
                continue
            out[(f[0], int(f[1]))] = (f[2], f[3], [float(x) for x in f[4:4 + len(SUPERPOPS)]])
    return out


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def estimate_ancestry(subject_id: str, *, build_if_missing: bool = False) -> dict:
    """Assign the subject's most likely continental superpopulation.

    Metric: **Pearson correlation** between the subject's ALT dosage and each
    superpopulation's expected dosage (2·AF) across the carried AIMs. This is deliberately
    NOT the per-marker HWE-product likelihood: that likelihood (and raw distance) is biased
    toward the population with the most intermediate allele frequencies — 1000G AMR, being
    recently admixed — which mis-assigns even clearly-European genomes. Correlation centers
    both vectors and measures profile *shape*, so it tracks ancestry robustly.

    Returns the assigned superpopulation, per-population `similarity` (the correlations — a
    relative genetic-similarity ranking, NOT admixture fractions), a margin-based
    `confidence`, and the marker count. ``build_if_missing`` triggers the AIM build first."""
    from ..genome.agi import AGIReader
    if not aim_reference_path().exists():
        if build_if_missing:
            rep = build_aim_reference()
            if rep.get("status") not in ("built", "cached"):
                return {"status": "no_reference", **rep}
        else:
            return {"status": "no_reference",
                    "reason": "AIM reference not built; run ancestry.estimate (it builds on first use)"}
    aims = _load_aims()
    agi = AGIReader.open(str(paths.active_genome_index_path(subject_id)))
    if agi is None:
        return {"status": "no_agi", "subject": subject_id}
    try:
        geno = agi.position_pgs_index()  # {(chrom,pos): (a1,a2,alt,af)}
    finally:
        agi.close()
    doses: list[float] = []
    exp: list[list[float]] = [[] for _ in SUPERPOPS]  # expected dosage 2·AF per population
    for key, (ref, alt, afs) in aims.items():
        g = geno.get(key)
        if g is None or g[2] != alt:   # not carried, or ALT mismatch (different variant)
            continue
        doses.append((g[0] == alt) + (g[1] == alt))
        for i in range(len(SUPERPOPS)):
            exp[i].append(2 * afs[i])
    n = len(doses)
    if n < 50:
        return {"status": "no_markers", "subject": subject_id, "n_markers": n}
    cors = {SUPERPOPS[i]: _pearson(doses, exp[i]) for i in range(len(SUPERPOPS))}
    ranked = sorted(SUPERPOPS, key=lambda k: cors[k], reverse=True)
    top, second = ranked[0], ranked[1]
    spread = cors[top] - cors[ranked[-1]]
    confidence = round((cors[top] - cors[second]) / spread, 3) if spread > 0 else 0.0
    return {"status": "ok", "subject": subject_id, "assigned_superpopulation": top,
            "confidence": confidence, "similarity": {k: round(cors[k], 4) for k in SUPERPOPS},
            "n_markers": n}
