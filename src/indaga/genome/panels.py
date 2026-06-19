"""Curated single-marker panels (interpreted nutrigenetics).

Well-established nutrigenetic markers with a genotype → plain-English interpretation —
the *interpreted* layer the domain bundles don't provide.

Correctness: each marker carries its forward-(+)-strand allele pair (``alleles``) and
the forward effect allele. MyHeritage reports genotypes on the forward strand, so the
capability validates that the observed alleles match the expected pair and that the
effect allele is one of them — otherwise it refuses to interpret (no silently-wrong
call). Effects are modest and probabilistic — never deterministic, never a prescription.
"""

from __future__ import annotations

# rsid, gene, category, trait, alleles (forward pair), effect_allele (forward),
# interp keyed by effect-allele copies (0/1/2).
# Rung-1 honesty metadata (matches a conservative genome agent's per-marker bar):
#   evidence_tier  — established | probable | emerging (literal; never inflate)
#   relevant_lab   — the single measurement that should accompany the marker (genotype ≠ diagnosis)
#   debunks        — popular but unsupported claims to disown explicitly (anti-overreach)
#   source         — a resolvable citation (guideline body / primary study / ClinVar)
NUTRIGENETIC_MARKERS: list[dict] = [
    {"rsid": "rs4988235", "gene": "MCM6/LCT", "category": "food-tolerance",
     "trait": "Lactose tolerance", "alleles": "A/G", "effect_allele": "A",
     "evidence_tier": "established",
     "relevant_lab": "(none routine) — hydrogen breath test if symptomatic",
     "debunks": ["A persistence genotype doesn't guarantee zero symptoms (secondary/transient intolerance still occurs)",
                 "Lactose non-persistence is not a dairy (casein/whey) allergy"],
     "source": "Enattah 2002 Nat Genet; ClinVar", "interp": {
        2: "Lactase-persistent — you most likely digest lactose well into adulthood.",
        1: "Likely lactase-persistent (one persistence allele) — usually tolerate dairy.",
        0: "Lactase non-persistent genotype — adult lactose intolerance is more likely; symptoms vary."}},
    {"rsid": "rs671", "gene": "ALDH2", "category": "food-tolerance",
     "trait": "Alcohol flush (acetaldehyde clearance)", "alleles": "A/G", "effect_allele": "A",
     "evidence_tier": "established",
     "relevant_lab": "(none) — flushing/acetaldehyde response is the readout",
     "debunks": ["'Asian-flush' antihistamines mask the flush but do NOT reduce the acetaldehyde-driven cancer risk — limit alcohol instead",
                 "The deficiency allele is common in East-Asian ancestry and rare in Europeans"],
     "source": "Brooks 2009 PLoS Med; PharmGKB ALDH2", "interp": {
        2: "ALDH2-deficient — strong alcohol flush; much higher acetaldehyde and cancer risk with alcohol.",
        1: "Partial ALDH2 deficiency — alcohol flush and raised acetaldehyde; alcohol best limited.",
        0: "Normal ALDH2 — no genetic flush response (mostly relevant in East-Asian ancestry)."}},
    {"rsid": "rs1229984", "gene": "ADH1B", "category": "nutrient-metabolism",
     "trait": "Alcohol metabolism speed", "alleles": "C/T", "effect_allele": "T",
     "evidence_tier": "established",
     "relevant_lab": "(none)",
     "debunks": ["The fast allele lowers alcohol-dependence risk but is not a 'safe to drink more' signal"],
     "source": "Bierut 2012 Mol Psychiatry; PharmGKB ADH1B", "interp": {
        2: "Fast ethanol→acetaldehyde — often unpleasant with alcohol; protective against heavy drinking.",
        1: "Faster-than-average alcohol metabolism (one fast allele).",
        0: "Typical alcohol metabolism rate."}},
    {"rsid": "rs762551", "gene": "CYP1A2", "category": "nutrient-metabolism",
     "trait": "Caffeine metabolism", "alleles": "A/C", "effect_allele": "A",
     "evidence_tier": "probable",
     "relevant_lab": "(none routine) — blood-pressure / sleep response to caffeine is the readout",
     "debunks": ["Slow-metabolizer status doesn't mandate zero caffeine — it informs timing/dose",
                 "The coffee→heart-attack-by-genotype link is contested across cohorts"],
     "source": "Cornelis 2006 JAMA; PharmGKB CYP1A2", "interp": {
        2: "Fast caffeine metabolizer (*1A/*1A) — caffeine clears quickly.",
        1: "Intermediate caffeine metabolizer.",
        0: "Slow caffeine metabolizer — caffeine lingers; higher intakes more likely to affect sleep/BP."}},
    {"rsid": "rs5751876", "gene": "ADORA2A", "category": "sensitivity",
     "trait": "Caffeine sensitivity / anxiety", "alleles": "C/T", "effect_allele": "T",
     "evidence_tier": "probable",
     "relevant_lab": "(none) — subjective jitter/sleep is the readout",
     "debunks": ["Does not predict a clinical anxiety disorder"],
     "source": "Childs 2008 Neuropsychopharmacology; Rogers 2010", "interp": {
        2: "Higher caffeine-induced anxiety/jitteriness and sleep disruption.",
        1: "Somewhat increased caffeine sensitivity.",
        0: "Lower genetic caffeine sensitivity."}},
    {"rsid": "rs9939609", "gene": "FTO", "category": "eating-behavior",
     "trait": "Appetite / obesity predisposition", "alleles": "A/T", "effect_allele": "A",
     "evidence_tier": "established",
     "relevant_lab": "(none) — BMI, waist circumference, food intake",
     "debunks": ["FTO is not a 'fat gene' that sets your weight — the per-allele effect is ~1 kg and physical activity blunts it (Kilpeläinen 2011)",
                 "Genotype does not prescribe a specific diet"],
     "source": "Frayling 2007 Science; Kilpeläinen 2011 PLoS Med", "interp": {
        2: "Higher genetic predisposition to appetite/adiposity — responds well to protein/satiety + activity.",
        1: "Modestly increased appetite/adiposity predisposition.",
        0: "Lower-risk FTO genotype for appetite/adiposity."}},
    {"rsid": "rs1801133", "gene": "MTHFR", "category": "nutrient-metabolism",
     "trait": "Folate metabolism (C677T)", "alleles": "A/G", "effect_allele": "A",
     "evidence_tier": "established",
     "relevant_lab": "homocysteine (+ serum folate, B12)",
     "debunks": ["MTHFR is not a general 'detoxification' gene",
                 "Do NOT avoid folic acid on genotype alone — CDC: people with MTHFR variants process folic acid normally",
                 "Methylfolate-only dosing based on genotype alone is not RCT-supported"],
     "source": "CDC MTHFR & folic acid guidance; ClinVar VCV000003520", "interp": {
        2: "Reduced MTHFR activity (~30%) — higher homocysteine tendency; prioritize folate-rich foods/riboflavin.",
        1: "Mildly reduced MTHFR activity — usually benign with adequate folate.",
        0: "Normal MTHFR C677T activity."}},
    {"rsid": "rs602662", "gene": "FUT2", "category": "nutrient-metabolism",
     "trait": "Vitamin B12 status (secretor)", "alleles": "A/G", "effect_allele": "A",
     "evidence_tier": "probable",
     "relevant_lab": "serum B12 / active-B12 (holotranscobalamin)",
     "debunks": ["Secretor status shifts B12 and the gut microbiome but is not a B12-deficiency diagnosis",
                 "Does not dictate which probiotic to take"],
     "source": "Hazra 2008 Nat Genet; Tanaka 2009", "interp": {
        2: "Non-secretor — tends to higher serum B12 but altered gut-microbiome interaction.",
        1: "Intermediate secretor status.",
        0: "Secretor — typical B12 handling."}},
    {"rsid": "rs12934922", "gene": "BCMO1", "category": "nutrient-metabolism",
     "trait": "Beta-carotene → vitamin A conversion", "alleles": "A/T", "effect_allele": "A",
     "evidence_tier": "probable",
     "relevant_lab": "serum retinol if deficiency is suspected",
     "debunks": ["Reduced conversion is not vitamin-A deficiency on a mixed diet",
                 "Not a reason to megadose preformed vitamin A (retinol toxicity is real)"],
     "source": "Leung 2009 FASEB J", "interp": {
        2: "Reduced conversion of plant beta-carotene to retinol — preformed vitamin A (eggs/dairy/fish) matters more.",
        1: "Somewhat reduced beta-carotene conversion.",
        0: "Efficient beta-carotene conversion."}},
    {"rsid": "rs713598", "gene": "TAS2R38", "category": "taste",
     "trait": "Bitter taste (PTC/PROP)", "alleles": "C/G", "effect_allele": "C",
     "evidence_tier": "established",
     "relevant_lab": "(none) — taste phenotype",
     "debunks": ["Bitter-taster status is a taste-perception trait, not a disease risk or a diet prescription"],
     "source": "Kim 2003 Science; Bufe 2005 Curr Biol", "interp": {
        2: "Bitter 'super-taster' — brassicas/coffee taste more bitter; may eat fewer bitter vegetables.",
        1: "Intermediate bitter taster.",
        0: "Bitter non-taster — bitter foods taste milder."}},
    {"rsid": "rs1800562", "gene": "HFE", "category": "nutrient-metabolism",
     "trait": "Iron overload (C282Y)", "alleles": "A/G", "effect_allele": "A",
     "evidence_tier": "established",
     "relevant_lab": "ferritin + transferrin saturation",
     "debunks": ["Genotype is not a diagnosis — iron studies decide",
                 "Heterozygotes (carriers) rarely develop clinical iron overload"],
     "source": "EASL haemochromatosis guideline; ClinVar VCV000000009", "interp": {
        2: "C282Y homozygous — hereditary haemochromatosis risk; check ferritin/transferrin saturation.",
        1: "C282Y carrier — usually fine; relevant with a second HFE variant or high ferritin.",
        0: "No HFE C282Y."}},
    {"rsid": "rs1799945", "gene": "HFE", "category": "nutrient-metabolism",
     "trait": "Iron handling (H63D)", "alleles": "C/G", "effect_allele": "G",
     "evidence_tier": "established",
     "relevant_lab": "ferritin + transferrin saturation",
     "debunks": ["H63D alone rarely causes iron overload — it matters mainly as a compound heterozygote with C282Y"],
     "source": "EASL haemochromatosis guideline; ClinVar", "interp": {
        2: "H63D homozygous — mild iron-loading tendency; check iron studies.",
        1: "H63D carrier — minor effect alone; matters most paired with C282Y.",
        0: "No HFE H63D."}},
    {"rsid": "rs4680", "gene": "COMT", "category": "sensitivity",
     "trait": "Catecholamine/dopamine clearance (Val158Met)", "alleles": "A/G", "effect_allele": "A",
     "evidence_tier": "probable",
     "relevant_lab": "(none routine)",
     "debunks": ["The 'warrior/worrier' label is a pop-sci oversimplification — the cognition/stress effect is small and context-dependent",
                 "COMT does not predict a psychiatric diagnosis and does not justify a 'methylation' supplement protocol"],
     "source": "Egan 2001 PNAS; Mier 2010 Mol Psychiatry (meta-analysis)", "interp": {
        2: "Slow COMT (Met/Met) — slower catecholamine clearance; steadier baseline dopamine but more stress-reactive ('worrier'). Effect is small.",
        1: "Intermediate COMT activity (Val/Met).",
        0: "Fast COMT (Val/Val) — rapid catecholamine clearance ('warrior'). Effect is small."}},
]
