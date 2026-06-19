"""Polygenic score computation (ported from HeathProject pipeline/05_pgs_compute.py).

For each curated PGS Catalog score: parse the harmonized GRCh38 weight file, match
the subject's genotypes by position, sum effect-allele dosage × weight, and turn the
raw score into a population percentile analytically (μ = Σ2pβ, σ² = Σ2p(1-p)β², then
z → normal CDF). Identical math to HeathProject; the only change is that genotypes
come from Indaga's own AGI (allele-based effect dosage) and weights from the
downloaded ``pgs-weights`` library. stdlib only (math.erf for the CDF; no scipy).
"""

from __future__ import annotations

import gzip
import math

from ..reference import manager as refmgr

# Curated PGS list (pgs_id, category, trait_label, direction, note) — verbatim from
# HeathProject's PGS_CATALOG (microarray-friendly, trait labels verified vs PGS Catalog).
PGS_CATALOG: list[tuple[str, str, str, str, str]] = [
    ("PGS000010", "Cardiometabolic", "Coronary heart disease (GRS27)", "high=more risk", "Mega 2015 — 27-SNP"),
    ("PGS000011", "Cardiometabolic", "Coronary artery disease (GRS50)", "high=more risk", "Khera 2016 — 50-SNP"),
    ("PGS000031", "Cardiometabolic", "Type 2 diabetes (GRSt 62)", "high=more risk", "62-SNP"),
    ("PGS000804", "Cardiometabolic", "Type 2 diabetes (GRS582 multi)", "high=more risk", "582-SNP multi-ancestry"),
    ("PGS000061", "Cardiometabolic", "LDL cholesterol", "high=higher LDL", "37 SNPs"),
    ("PGS000065", "Cardiometabolic", "LDL cholesterol (GRS103)", "high=higher LDL", "103 SNPs"),
    ("PGS000060", "Cardiometabolic", "HDL cholesterol", "high=higher HDL", "46 SNPs"),
    ("PGS000064", "Cardiometabolic", "HDL cholesterol (GRS120)", "high=higher HDL", "120 SNPs"),
    ("PGS000063", "Cardiometabolic", "Triglycerides", "high=higher TG", "32 SNPs"),
    ("PGS000066", "Cardiometabolic", "Triglycerides (GRS101)", "high=higher TG", "101 SNPs"),
    ("PGS000062", "Cardiometabolic", "Total cholesterol", "high=higher TC", "52 SNPs"),
    ("PGS000311", "Cardiometabolic", "Total cholesterol (GRS234)", "high=higher TC", "234 SNPs"),
    ("PGS000034", "Cardiometabolic", "Body mass index (BMI)", "high=higher BMI", "97 SNPs"),
    ("PGS002275", "Cardiometabolic", "Systolic blood pressure", "high=higher SBP", "425 SNPs"),
    ("PGS002734", "Cardiometabolic", "Systolic blood pressure (GRS362)", "high=higher SBP", "362 SNPs"),
    ("PGS000302", "Cardiometabolic", "Diastolic blood pressure", "high=higher DBP", "962 SNPs"),
    ("PGS002748", "Body composition", "Height", "high=taller", "251 SNPs"),
    ("PGS000297", "Body composition", "Height (GRS3290)", "high=taller", "3290 SNPs"),
    ("PGS000842", "Body composition", "Waist-hip ratio", "high=more central adiposity", "39 SNPs"),
    ("PGS005315", "Body composition", "Appendicular lean mass", "high=more lean mass", "630 SNPs"),
    ("PGS001125", "Lifestyle", "Coffee consumption (instant)", "high=consumes more", "432 SNPs"),
    ("PGS001123", "Lifestyle", "Coffee consumption", "high=consumes more", "48 SNPs"),
    ("PGS002616", "Lifestyle", "Smoking status / initiation", "high=more likely smoker", "201 SNPs"),
    ("PGS003067", "Lifestyle", "Smoking initiation (UKB)", "high=more likely smoker", "244 SNPs"),
    ("PGS002586", "Sleep", "Chronotype (morningness)", "high=more morning person", "255 SNPs"),
    ("PGS000336", "Sleep", "Chronotype (GRS313)", "high=more morning person", "313 SNPs"),
    ("PGS003321", "Sleep", "Insomnia", "high=more insomnia", "148 SNPs"),
    ("PGS003764", "Sleep", "Sleep duration (PRS78)", "high=longer sleep", "78 SNPs"),
    ("PGS002587", "Cognition", "College education / attainment", "high=more attainment", "514 SNPs"),
    ("PGS002610", "Personality", "Neuroticism", "high=more neurotic", "196 SNPs"),
    ("PGS000025", "Disease susceptibility", "Alzheimer's disease (GRS19)", "high=more risk", "19 SNPs incl. APOE"),
    ("PGS000026", "Disease susceptibility", "Alzheimer's disease (GRS33)", "high=more risk", "33 SNPs"),
    ("PGS000334", "Disease susceptibility", "Late-onset AD (GRS22)", "high=more risk", "22 SNPs"),
    ("PGS000053", "Disease susceptibility", "Late-onset AD (NIA-LOAD)", "high=more risk", "21 SNPs"),
    ("PGS000767", "Disease susceptibility", "Major depressive disorder", "high=more risk", "14 SNPs"),
    ("PGS001281", "Disease susceptibility", "Migraine", "high=more risk", "25 SNPs"),
    ("PGS001282", "Disease susceptibility", "Migraine (time-to-event)", "high=more risk", "329 SNPs"),
    ("PGS001312", "Disease susceptibility", "Psoriasis", "high=more risk", "204 SNPs"),
    ("PGS001313", "Disease susceptibility", "Psoriasis (time-to-event)", "high=more risk", "578 SNPs"),
    ("PGS003486", "Disease susceptibility", "Atopic eczema", "high=more risk", "71 SNPs"),
    ("PGS003459", "Disease susceptibility", "Atopic eczema/disease", "high=more risk", "170 SNPs"),
    ("PGS000030", "Disease susceptibility", "Prostate cancer", "high=more risk", "147 SNPs"),
    ("PGS000662", "Disease susceptibility", "Prostate cancer (GRS269)", "high=more risk", "269 SNPs"),
]

_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}


def revcomp(a: str) -> str:
    return "".join(_COMPLEMENT.get(b, "N") for b in reversed(a))


def parse_scoring_file(path: str):
    """Yield (chrom, pos, effect_allele, other_allele, weight, af, rsid) — verbatim
    column resolution from HeathProject (hm_chr/chr_name, hm_pos/chr_position, …)."""
    with gzip.open(path, "rt") as f:
        header = None
        for line in f:
            if line.startswith("#"):
                continue
            header = line.rstrip("\n").split("\t")
            break
        if header is None:
            return
        col = {name: i for i, name in enumerate(header)}

        def pick(*names):
            for n in names:
                if n in col:
                    return col[n]
            return None

        ic = pick("hm_chr", "chr_name")
        ip = pick("hm_pos", "chr_position")
        ie = pick("effect_allele")
        io_ = pick("other_allele", "hm_inferOtherAllele")
        iw = pick("effect_weight")
        ia = pick("allelefrequency_effect", "hm_freq", "allelefrequency_effect_European")
        ir = pick("rsID", "hm_rsID")
        if ic is None or ip is None or ie is None or iw is None:
            return
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(ic, ip, ie, iw):
                continue
            try:
                chrom = parts[ic].replace("chr", "")
                if parts[ip] in ("", ".", "NA") or chrom in ("", ".", "NA"):
                    continue
                pos = int(parts[ip])
                ea = parts[ie].upper()
                oa = parts[io_].upper() if io_ is not None and parts[io_] not in ("", ".", "NA") else None
                w = float(parts[iw])
                af = None
                if ia is not None and parts[ia] not in ("", ".", "NA"):
                    try:
                        af = float(parts[ia])
                    except ValueError:
                        af = None
                rsid = parts[ir] if ir is not None and parts[ir] not in ("", ".", "NA") else None
                yield (chrom, pos, ea, oa, w, af, rsid)
            except (ValueError, IndexError):
                continue


def _effect_dosage(ea: str, oa: str | None, a1: str, a2: str):
    """Count of the effect allele in the genotype {a1,a2}, trying forward strand then
    reverse-complement. Returns (dosage, strand_flipped) or None if it can't orient."""
    # forward strand: at least one genotype allele matches a score allele
    if a1 == ea or a2 == ea or (oa is not None and (a1 == oa or a2 == oa)):
        return (int(a1 == ea) + int(a2 == ea), False)
    re_, ro = revcomp(ea), (revcomp(oa) if oa else None)
    if a1 == re_ or a2 == re_ or (ro is not None and (a1 == ro or a2 == ro)):
        return (int(a1 == re_) + int(a2 == re_), True)
    return None


def _effect_af(ea: str, alt: str | None, af_alt: float | None) -> float | None:
    """Orient the variant's ALT-allele frequency (panel AF) to the effect allele.
    af_alt = P(alt); effect allele is alt (fwd/revcomp) → af_alt, else (it's the ref) → 1-af_alt."""
    if af_alt is None or alt is None:
        return None
    if ea == alt or revcomp(ea) == alt:
        return af_alt
    return 1.0 - af_alt


def compute_score(rows, pgs_index: dict, *, rsid_index: dict | None = None) -> dict:
    """rows: (chrom,pos,ea,oa,w,af_file,rsid). pgs_index: {(chrom,pos): (a1,a2,alt,af)} from
    the AGI (genotype + ALT + panel AF). raw/μ/var are accumulated over the SAME variant set
    (matched AND AF-known) — no extrapolation, so percentiles are COVERAGE-correct on imputed data.
    Caveat: σ²=Σ2p(1-p)β² assumes the score's variants are in LINKAGE EQUILIBRIUM (independent);
    for LD-correlated scores it underestimates variance, so percentiles are over-dispersed (pushed
    toward the extremes). AF source: the weight file's own AF if present, else the genome's panel AF (oriented)."""
    raw = mu = var = 0.0
    n_total = n_matched = n_used = n_flip = n_amb = 0
    for chrom, pos, ea, oa, w, af_file, rsid in rows:
        n_total += 1
        hit = pgs_index.get((chrom, pos))
        if hit is None and rsid_index is not None and rsid:
            hit = rsid_index.get(rsid)
        if hit is None:
            continue
        a1, a2, alt, af_panel = hit
        d = _effect_dosage(ea, oa, a1, a2)
        if d is None:
            n_amb += 1
            continue
        dosage, flipped = d
        if flipped:
            n_flip += 1
        n_matched += 1
        eaf = af_file if (af_file is not None and 0 < af_file < 1) else _effect_af(ea, alt, af_panel)
        if eaf is None or not (0 < eaf < 1):
            continue  # no population baseline → can't contribute to the percentile
        raw += dosage * w
        mu += 2.0 * eaf * w
        var += 2.0 * eaf * (1 - eaf) * (w ** 2)
        n_used += 1

    coverage = n_matched / n_total if n_total else 0.0
    z = pct = pop_mu = pop_sd = None
    if n_used >= max(10, 0.3 * n_total) and var > 0:
        sd = math.sqrt(var)
        z = (raw - mu) / sd
        pct = 100.0 * (0.5 * (1 + math.erf(z / math.sqrt(2))))
        pop_mu, pop_sd = mu, sd

    return {
        "raw_score": raw, "n_total": n_total, "n_matched": n_matched, "coverage": coverage,
        "n_strand_flipped": n_flip, "n_ambiguous_skipped": n_amb,
        "af_coverage": (n_used / n_total if n_total else 0.0), "n_af_from_gnomad": 0,
        "z_score": z, "percentile": pct, "pop_mu": pop_mu, "pop_sd": pop_sd,
    }


def run_pgs(agi, gnomad=None, *, score_ids: list[str] | None = None,
            build: str = "GRCh38") -> list[dict]:
    """Compute every curated PGS for the subject's AGI. AF comes from the genome's own
    panel AF (stored in the AGI), so this is offline + reliable — no gnomAD round-trips
    (the ``gnomad`` arg is accepted for API compatibility but unused). Weights are fetched
    from the ``pgs-weights`` library on demand. One result dict per score."""
    pgs_index = agi.position_pgs_index()
    wanted = set(score_ids) if score_ids else None
    results: list[dict] = []
    seen: set[str] = set()
    for pgs_id, category, trait_label, direction, note in PGS_CATALOG:
        if pgs_id in seen or (wanted is not None and pgs_id not in wanted):
            continue
        seen.add(pgs_id)
        path = refmgr.ensure_pgs_weight(pgs_id, build)
        base = {"pgs_id": pgs_id, "category": category, "trait_label": trait_label,
                "direction": direction, "note": note}
        if path is None:
            results.append({**base, "error": "weight file unavailable"})
            continue
        rows = list(parse_scoring_file(str(path)))
        if not rows:
            results.append({**base, "error": "no parseable rows"})
            continue
        res = compute_score(rows, pgs_index)
        results.append({**base, **res})
    return results
