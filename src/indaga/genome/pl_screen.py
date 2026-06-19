"""High-penetrance P/LP screen (ported from HeathProject pipeline/_pl_screen_core.py).

Finds the ClinVar Pathogenic/Likely-pathogenic variants the subject CARRIES
(genome-wide), then applies the honest gnomAD allele-frequency refutation: a
"pathogenic" variant that is actually common in the population is a likely
false alarm, not a real high-penetrance risk. Priority-panel membership is an
annotation, not a filter (ESR1's panel='—' is genome-wide).

Identical science to HeathProject; the only changes are (a) candidates come from
Indaga's own ClinVar evidence store via a ClinVar⋈AGI carrier join, and (b) the
gnomAD lookup is GRCh37 (gnomad_r2_1) to match the chip's build. No pandas.
"""

from __future__ import annotations

# --- Priority panels (single source of truth; verbatim from _pl_screen_core.py) ---
HEREDITARY_CANCER = {
    "BRCA1", "BRCA2", "PALB2", "ATM", "CHEK2", "TP53",
    "MLH1", "MSH2", "MSH6", "PMS2", "EPCAM",
    "RAD51C", "RAD51D", "BARD1", "BRIP1",
    "APC", "MUTYH", "STK11", "CDH1", "PTEN", "VHL",
    "NBN", "NF1", "NF2", "RB1", "RET", "MEN1",
}
FH_GENES = {"LDLR", "APOB", "PCSK9", "LDLRAP1", "ABCG5", "ABCG8", "APOE"}
CARDIO_HIGH_PEN = {
    "MYH7", "MYBPC3", "TNNT2", "TNNI3", "LMNA",
    "KCNQ1", "KCNH2", "SCN5A", "RYR2", "DSP", "DSG2", "PKP2",
}
THROMBOPHILIA = {"F5", "F2", "PROC", "PROS1", "SERPINC1"}
INTERFERONOPATHY = {
    "RNU7-1", "RNU4-2",
    "ADAR", "TREX1", "SAMHD1", "RNASEH2A", "RNASEH2B", "RNASEH2C", "IFIH1", "LSM11",
}
PRIORITY_PANELS = {
    "Hereditary Cancer": HEREDITARY_CANCER,
    "Familial Hypercholesterolaemia": FH_GENES,
    "Inherited Cardiac": CARDIO_HIGH_PEN,
    "Thrombophilia": THROMBOPHILIA,
    "Interferonopathy": INTERFERONOPATHY,
}
# Established loss-of-function disease genes (the priority panels) — PVS1-eligible even when
# population constraint (pLI/LOEUF) is moderate (true for late-onset tumour-suppressors like BRCA2).
PRIORITY_GENES = HEREDITARY_CANCER | FH_GENES | CARDIO_HIGH_PEN | THROMBOPHILIA | INTERFERONOPATHY

RARE_AF_THRESHOLD = 0.01


def _panel_for_gene(gene: str | None) -> str:
    """Panel label for a finding. ACMG SF v3.3 (the recognized medically-actionable / return-of-results
    standard) is authoritative; genes outside SF fall back to Indaga's bespoke priority sets (the
    interferonopathy + thrombophilia panels aren't in ACMG SF but are kept as additional context)."""
    from .acmg_sf import SF_VERSION, sf_info
    sf = sf_info(gene)
    if sf:
        return f"ACMG SF {SF_VERSION}: {sf['category']}"
    if not gene:
        return "—"
    for name, members in PRIORITY_PANELS.items():
        if gene in members:
            return name
    return "—"


def _panel_annotations(gene: str | None) -> dict:
    """Structured standard-panel annotations for a finding: ACMG SF v3.3 (medically-actionable
    secondary finding) + ACMG 2021 carrier screening (reproductive carrier gene). All-None when the
    gene is on neither list."""
    from .acmg_carrier import carrier_info
    from .acmg_sf import sf_info
    sf = sf_info(gene)
    car = carrier_info(gene)
    return {"acmg_sf": bool(sf),
            "acmg_sf_category": sf["category"] if sf else None,
            "acmg_sf_disorder": sf["disorder"] if sf else None,
            "acmg_sf_inheritance": sf["inheritance"] if sf else None,
            "acmg_carrier": bool(car),
            "acmg_carrier_condition": car["condition"] if car else None,
            "acmg_carrier_inheritance": car["inheritance"] if car else None}


def _review_stars(review: str | None) -> int:
    """ClinVar review status → star rating (0-4). A 1★ single-submitter 'Pathogenic' is far
    weaker evidence than a 3★ expert-panel one — used to gate 'confident' findings."""
    r = (review or "").lower()
    if "practice guideline" in r:
        return 4
    if "expert panel" in r:
        return 3
    if "multiple submitters" in r and "no conflict" in r:
        return 2
    if "single submitter" in r or "conflicting" in r:
        return 1
    return 0  # no assertion criteria / no classification


def _classify(af, error) -> str:
    """Verbatim from HeathProject: error → api_error; no AF → not_in_gnomad;
    <1% → confirmed_rare; else common_likely_false_alarm."""
    if error:
        return "api_error"
    if af is None:
        return "not_in_gnomad"
    if af < RARE_AF_THRESHOLD:
        return "confirmed_rare"
    return "common_likely_false_alarm"


def _am_candidates(reader, agi_path: str, gnomad, existing: set) -> list[dict]:
    """Scan priority-panel gene regions for the subject's carried AlphaMissense-pathogenic
    missense SNVs that ClinVar doesn't already flag P/LP — predictor-driven candidates."""
    from .agi import AGIReader
    from .genemodel import GeneModel
    from .inheritance import carrier_status
    from .predictors import AlphaMissense
    am = AlphaMissense.open()
    agi = AGIReader.open(agi_path)
    if am is None or agi is None:
        return []
    gm = GeneModel.open()  # restrict the scan to coding exons (CDS); None → scan the full region
    out: list[dict] = []
    seen: set = set()
    try:
        for gene in PRIORITY_GENES:
            region = reader.gene_region(gene, build="GRCh38")
            if not region:
                continue
            chrom, lo, hi = region
            if hi - lo > 5_000_000:
                continue  # implausible span guard
            cds = gm.cds_intervals(gene) if gm else []
            for vc in agi.region_calls(chrom, lo, hi):
                if cds and not any(s <= vc["pos"] <= e for s, e in cds):
                    continue  # outside the coding sequence — AlphaMissense doesn't apply
                ref, alt = vc.get("ref"), vc.get("alt")
                if not (ref and alt and len(ref) == 1 and len(alt) == 1 and ref != alt):
                    continue
                if alt not in (vc.get("allele1"), vc.get("allele2")):
                    continue  # not carried
                key = (chrom, vc["pos"], ref, alt)
                if key in existing or key in seen:
                    continue
                amr = am.lookup(chrom, vc["pos"], ref, alt)
                if not amr or amr.get("am_class") != "likely_pathogenic":
                    continue
                seen.add(key)
                g = gnomad.fetch(chrom, vc["pos"], ref, alt)
                af = g.get("af")
                zyg = vc.get("zygosity")
                cs = carrier_status(gene, zyg)
                typed = bool((vc.get("rsid") or "").startswith("rs"))
                out.append({
                    "rsid": vc.get("rsid") if typed else None, "gene": gene,
                    "panel": _panel_for_gene(gene), **_panel_annotations(gene),
                    "chrom": chrom, "pos": vc["pos"],
                    "ref": ref, "alt": alt, "achange": amr.get("protein_variant"),
                    "candidate_reason": "AlphaMissense pathogenic (priority panel)",
                    "clinvar_sig": None, "clinvar_disease": None, "clinvar_review": None,
                    "gnomad_af": af, "gnomad_source": g.get("source"),
                    "classification": _classify(af, g.get("error")),
                    "zygosity": zyg, "inheritance": cs["inheritance"], "carrier_status": cs["code"],
                    "interpretation": cs["label"], "directly_typed": typed,
                    "confidence": "alphamissense_predicted", "review_stars": 0,
                })
    finally:
        am.close()
        agi.close()
        if gm:
            gm.close()
    return out


def run_pl_screen(reader, agi_path: str, gnomad, *, build: str = "GRCh37") -> list[dict]:
    """Return the P/LP findings for the subject in the pl_findings.json record shape,
    each annotated with zygosity + carrier-vs-at-risk interpretation (inheritance-aware)."""
    from .inheritance import carrier_status
    carriers = reader.clinvar_pl_carriers(agi_path, build=build)
    findings: list[dict] = []
    for c in carriers:
        g = gnomad.fetch(c["chrom"], c["pos"], c["ref"], c["alt"])
        af = g.get("af")
        classification = _classify(af, g.get("error"))
        zyg = c.get("zygosity")
        cs = carrier_status(c.get("gene"), zyg)
        typed = bool(c.get("directly_typed"))
        stars = _review_stars(c.get("clinvar_review"))
        # Confidence combines genotyping certainty (typed vs imputed) with ClinVar evidence
        # strength (stars). Only a directly-typed call with ≥2★ review is "confident"; a typed
        # 1★ single-submitter call, or any imputed-not-in-gnomAD call, needs confirmation.
        if typed and stars >= 2:
            confidence = "directly_typed"
        elif typed:
            confidence = "directly_typed_low_review"   # weak ClinVar evidence (1★) — confirm
        elif classification in ("not_in_gnomad", "api_error"):
            confidence = "imputed_unconfirmed"         # likely imputation artifact — confirm
        else:
            confidence = "imputed"
        findings.append({
            "rsid": c.get("rsid"),
            "gene": c.get("gene"),
            "panel": _panel_for_gene(c.get("gene")),
            **_panel_annotations(c.get("gene")),
            "chrom": c["chrom"], "pos": c["pos"], "ref": c["ref"], "alt": c["alt"],
            "achange": None,
            "candidate_reason": "ClinVar P/LP",
            "clinvar_sig": c.get("clinvar_sig"),
            "clinvar_disease": c.get("clinvar_disease"),
            "clinvar_review": c.get("clinvar_review"),
            "gnomad_af": af,
            "gnomad_source": g.get("source"),
            "classification": classification,
            "zygosity": zyg,
            "inheritance": cs["inheritance"],
            "carrier_status": cs["code"],
            "interpretation": cs["label"],
            "directly_typed": typed,
            "confidence": confidence,
            "review_stars": stars,
        })
    # AlphaMissense-pathogenic missense in priority-panel genes that ClinVar doesn't flag P/LP
    # — the predictor-driven candidates (GRCh38 only; AlphaMissense is GRCh38).
    if build == "GRCh38":
        existing = {(f["chrom"], f["pos"], f["ref"], f["alt"]) for f in findings}
        findings += _am_candidates(reader, agi_path, gnomad, existing)
    gnomad.save()
    # rare/real first, then ACMG-SF-actionable, then panel, then gene — stable, useful ordering
    order = {"confirmed_rare": 0, "not_in_gnomad": 1, "api_error": 2, "common_likely_false_alarm": 3}
    findings.sort(key=lambda f: (order.get(f["classification"], 9), not f.get("acmg_sf"),
                                 f["panel"] == "—", f.get("gene") or ""))
    return findings
