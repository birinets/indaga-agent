---
name: genome
description: DNA analysis from the user's own genome — imputed on-device (Beagle), annotated in-house (ClinVar P/LP screen, polygenic scores), with a COMPUTED ACMG/AMP classification (not just a ClinVar lookup) and callability honesty. Use for genotype at an rsID, gene variants, APOE/TCF7L2/MTHFR/BRCA, ClinVar significance, carrier-vs-at-risk screen, pharmacogenomics, polygenic scores, and variant pathogenicity classification.
tools:
  - variant.resolve
  - genome.summary
  - clinvar.findings
  - acmg.classify
  - splice.assess
  - pgs.score
  - pgx.summary
  - gwas.associations
  - ancestry.estimate
  - genome.impute
  - genome.annotate
  - genome.pgx_run
mutating: false
---

# Genome

Indaga owns the whole genome pipeline, fully on-device: a consumer chip is **imputed** to a dense
GRCh38 genome (Beagle + 1000G-30x panel — the genome never leaves the machine), parsed into a
queryable **Active Genome Index**, and **annotated in-house** — ClinVar significance (position-join),
a high-penetrance P/LP screen, polygenic scores, and a **computed ACMG/AMP classification**. Nothing
is borrowed from another project; everything is from the user's own data + Indaga's downloaded references.

## When to use
Genotype at an rsID; a gene's variants; APOE / TCF7L2 / MTHFR / BRCA etc.; "am I a carrier of X?";
ClinVar pathogenic findings; **how pathogenic is this variant (ACMG)**; pharmacogenomics; polygenic
risk percentiles; GWAS trait associations.

## The processing flow (for a new/unprocessed genome)
1. `indaga.install` — fetch reference libraries (ClinVar, gnomAD, AlphaMissense, panels) into ~/.indaga.
2. `genome.impute` — extend the chip to a GRCh38 genome. **Long-running → background job**; poll
   `indaga.check_background_job` until done.
3. `genome.annotate` — build the index + P/LP screen + polygenic scores (+ GWAS associations).
4. `genome.pgx_run` *(optional)* — in-house PharmCAT for pharmacogenomics. **Background job** (first run
   also fetches a reference FASTA); poll, then query `pgx.summary`.
Then query with the tools below. (On a typical session the genome is already processed; check
`genome.summary` / `indaga.describe_context` first.)

## The contract — callability is honesty (the core rule)
**A variant not in the subject's genome (not chip-typed and not confidently imputed) is `not_measured`
— UNKNOWN, never "you don't have it".** This is the genomic leg of the envelope
(`requires:[callability, genotype_support]`). E.g. **APOE rs429358 is not on the GSA chip** → "do I
carry APOE ε4?" is "not measured — unknown", not "no".

| situation | envelope | what to say |
|---|---|---|
| variant present (typed/imputed), called | `evidence_present` | genotype + zygosity; ClinVar; the COMPUTED ACMG tier; cite the source |
| variant not in genome / no-call | `not_measured` + `requires:[callability,…]` | "Not in this genome — unknown, not absent." |
| common variant flagged 'pathogenic' | `REFUTED` caveat | do NOT alarm — likely false positive (high population frequency) |

`negative_inference.allowed` is `false` unless callability + genotype support are satisfied.

## Tools
- **`variant.resolve`** (entry) — `{"rsid":"rs7903146"}` → genotype + zygosity, ClinVar significance,
  callability, AlphaMissense + **REVEL** (a second ensemble missense opinion, with AlphaMissense
  concordance), and a **computed ACMG/AMP tier** (vs ClinVar). Writes the variant into the Active Health
  Index so it fuses with labs/CGM.
- **`acmg.classify`** (focused) — the ACMG/AMP call for a variant: **PVS1** (LoF in a constrained or
  established LoF-disease gene) + **PM2/BA1/BS1** (frequency) + **PP3/BP4** (AlphaMissense; REVEL fills in
  where AM doesn't cover), combined per Richards 2015 → Pathogenic / Likely-pathogenic / VUS /
  Likely-benign / Benign, with the criteria that fired and ClinVar concordance. Indaga COMPUTES this; it
  is not a lookup. **PVS1 fires on NOVEL variants too** — an owned MANE-transcript consequence annotator
  (genome/consequence.py) calls nonsense/frameshift/splice on any variant, so a LoF ClinVar has never seen
  still classifies (the differentiator vs Genomi/OpenCRAVAT, which can only look ClinVar up). Still not
  computed: PS1/PM5/segregation/functional → most novel missense correctly land at VUS.
- **`splice.assess`** (focused) — **SpliceAI** splice-impact prediction for a variant: delta scores
  (acceptor/donor × gain/loss, 0–1; `ds_max` = splice-altering probability, ≥0.5 likely, ≥0.8
  high-confidence) + a splice-aware ACMG tier. Catches splice-altering variants AlphaMissense (missense-only)
  and the canonical ±1/2 rule both miss — deep-intronic cryptic sites, exonic-splice, even synonymous.
  Indaga runs the model **on-device** (no 30 GB precomputed download). **SLOW (a TensorFlow cold start,
  ~15 s)** → call when splicing is the question, not for every variant; `variant.resolve` does NOT run it.
- **`clinvar.findings`** (focused) — the carried P/LP screen, tiered honestly: `confident_at_risk` vs
  `needs_confirmation` (imputed-not-in-gnomAD, or 1★ single-submitter ClinVar) vs `carrier_only`
  (recessive heterozygote — family-planning relevance, NOT personal risk) vs common-refuted. Includes
  AlphaMissense-pathogenic missense candidates ClinVar doesn't flag. Lead with `confident_at_risk`.
- **`pgs.score`** (focused) — polygenic percentiles (imputed). **Read `confidence`/`coverage`**: a
  'low' (<50% of variants recovered) score regresses toward 50th and UNDERSTATES risk — coverage-limited,
  not a true low score. Directional, not a diagnosis.
- **`pgx.summary`** (focused) — pharmacogenomic diplotypes computed **in-house** (PharmCAT CPIC
  star-alleles on the imputed genome): per-gene `diplotype` + `phenotype` (e.g. NAT2 \*6/\*6 Poor
  Metabolizer; RYR1 c.6178G>T → Uncertain Susceptibility = the malignant-hyperthermia flag) +
  `activity_score`. `blind_spots` lists genes imputation can't confidently resolve (CYP2D6/CYP2C19/HLA
  — for drugs they govern, a clinical PGx panel is needed before prescribing). Run with `genome.pgx_run`
  (background) first; until then it reports `not_measured`.
- **`ancestry.estimate`** (focused) — most likely continental superpopulation (1000G AFR/AMR/EAS/EUR/SAS)
  by ancestry-informative-marker (AIM) likelihood against the imputation panel's per-population allele
  frequencies. Returns `assigned_superpopulation` + `confidence` + per-pop `proportions` (normalized
  likelihoods). This is continental **assignment, NOT admixture-fraction deconvolution** (that needs
  ADMIXTURE/RFMix) — don't report the proportions as genome ancestry fractions, and it doesn't capture
  recent admixture or self-identified identity. Builds its AIM reference once (background) on first use.
- **`gwas.associations`** (focused) — GWAS-Catalog trait/disease associations at loci the subject
  carries, ranked by **−log10(p)** (`neg_log10_p`; the raw `pval` underflows float64 to 0 for the most
  significant hits, so it is display-only). Position-joins the GRCh38 catalog against the imputed AGI
  (a GRCh37-only chip won't match — reports `not_measured`). Filter by `trait`. **Association ≠ causation**;
  effect sizes (OR/beta) are population-level and small for common variants; an empty trait search is
  `not_observed_in_consulted_scope` (the catalog is trait-curated + incomplete), never a clean negative.
- **`genome.summary`** (entry) — index stats + what's available. **`genome.impute`/`genome.annotate`**
  (focused, mutating) — run the pipeline (see flow above).

## Interpretation
> Follow `skills/output-rules.md` (the delivery contract) on top of these — esp. *a predictor
> score is never a diagnosis*, *exact-allele match before you alarm*, and *translate the vocabulary*.
- Lead with the genotype + the COMPUTED ACMG tier; show it next to ClinVar (agreement is reassuring;
  divergence is informative). A common variant is ACMG-Benign (BA1) regardless of a high predictor score.
- ACMG = **Mendelian pathogenicity**, distinct from **polygenic risk**: a common T2D risk allele is
  ACMG-Benign *and* a PGS signal — different lenses, both valid.
- `needs_confirmation` findings (imputed rare, or weak ClinVar review) want orthogonal confirmation
  (Sanger/clinical) before acting — say so; don't assert.
- Pair genetic risk with the user's actual labs/CGM when relevant (TCF7L2 × real glucose) — the moat.
- Everything here is decision-support, not diagnosis; recommend clinician review for medical decisions.
