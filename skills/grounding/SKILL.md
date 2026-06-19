---
name: grounding
description: Analytical grounding — the biological-context layer that makes a genomic finding meaningful. Turn a locus/gene into its gene-model feature (exon/intron, coding/UTR, distance-to-TSS), regulatory element (ENCODE cCRE), pathway membership (Reactome), and tissue + single-cell expression (HPA). All LOCAL — no external lookup, no locus-interest egress. Use to answer "what does this gene/variant do / where does it sit / why does it matter".
tools:
  - grounding.gene
  - grounding.region
  - grounding.regulatory
  - grounding.pathways
  - grounding.go
  - grounding.gene_disease
  - grounding.diagnostic_panels
  - grounding.expression
  - grounding.celltype
mutating: false
---

# Grounding — local-first interpretation depth

> Apply `skills/output-rules.md`: ground a finding in context, but never convert context into a clinical
> claim; this is decision-support, n=1.

Grounding adds the biological *context* around a finding — the layer that turns "you carry rs7903146"
into "rs7903146 sits in an intron of TCF7L2, a Wnt-signalling transcription factor in pancreatic β-cells".
Unlike a genome-only lookup, it is **fully local**: every answer comes from downloaded reference data, so
no third party learns which gene/locus the subject asked about (`externalIO` is empty).

Every reference is **downloaded** (read-only — grounding never auto-installs; if a library is missing the tool
returns `not_measured` with the `indaga install …` hint). Gene names are **entity-canonicalised** to the
approved HGNC symbol first (alias / previous / Entrez / Ensembl id all resolve), so a finding carrying an old
or alias name still grounds.

## Tools

- **`grounding.gene`** (entry, composite) — one call returns **region + regulatory + pathways + expression**
  for a gene (or a locus → its gene): gene-model feature + overlapping cCRE (when a locus is given), Reactome
  pathway memberships, and top HPA tissues. Each section keeps its **own evidence state**, so a missing
  library degrades only that section, never the whole answer. This is the single convenience entry Genomi
  lacks — start here for "tell me about this gene/variant", then reach for a focused tool to go deeper.
- **`grounding.region`** (entry) — ground a locus in the MANE coding-transcript model: which gene it falls
  in, **exon vs intron**, **coding (CDS) vs untranslated**, strand, and **distance to the TSS**. Accepts an
  `rsid` (resolved on the subject's genome) or explicit `chrom`+`pos`. `coding_exon` means a protein-coding
  position; `intergenic`/`intron` mean the variant is regulatory-or-nothing in the consulted model.
- **`grounding.regulatory`** — ground a locus in the **ENCODE cCRE** registry: does it overlap a candidate
  *cis*-regulatory element — promoter-like (PLS), enhancer-like (pELS/dELS), CTCF/insulator, or
  chromatin-accessible? **Fills `grounding.region`'s blind spot:** the MANE model only sees coding
  transcripts, so it calls a non-coding variant "intron/intergenic" — `regulatory` tells you if that
  non-coding position is actually a regulatory element (e.g. rs7903146 → TCF7L2 *distal enhancer*).
- **`grounding.pathways`** — pathway memberships for a gene from the local **Reactome** gene sets (the
  offline equivalent of Genomi's live Reactome lookup). Accepts a `gene` symbol directly, or an
  `rsid`/`chrom`+`pos` that it resolves to the gene first (composes with `grounding.region`). Returns
  `{id, name}` per pathway; an empty list with `empty_consulted_scope` means the gene is in no Reactome
  pathway (an absence within Reactome, not "no function").
- **`grounding.go`** — Gene Ontology terms for a gene: **biological-process**, **molecular-function**,
  **cellular-component** (the open process/function vocabulary — the slice of MSigDB-C5 / KEGG that's freely
  licensable). Optional `aspect` (process/function/component) filter. Generic root/binding/location terms are
  suppressed. Complements `pathways`: GO is the *function/process* vocabulary, Reactome the *reaction map*
  (e.g. MTHFR → GO "methylenetetrahydrofolate reductase activity, FAD binding"; TCF7L2 → GO "glucose
  homeostasis, Wnt signaling, fat cell differentiation").
- **`grounding.gene_disease`** — graded **gene→disease validity** from the local **GenCC + ClinGen**
  backbone (Definitive → Strong → Moderate → Limited, + mode of inheritance + MONDO id), best classification
  per disease, strongest first. The **industry-standard, citable** replacement for a hand-curated panel.
  Optional `min_classification` (definitive/strong/moderate/limited/`all`). Validity grades the
  *gene-disease relationship*, **not** the subject's variant — a Definitive gene still needs a pathogenic
  variant to matter. (GenCC aggregates ClinGen/Orphanet/PanelApp/…; both downloaded → zero egress.)
- **`grounding.diagnostic_panels`** — which **green (diagnostic-grade) Genomics England PanelApp** panels a
  gene appears in — the disease-specific *diagnostic* view (e.g. LDLR → "Familial hypercholesterolaemia";
  MYH7 → HCM + DCM panels). Complements `gene_disease` (validity) and the ACMG SF actionable list. Green =
  enough evidence to use diagnostically for that disorder (gene-level). PanelApp data is **non-commercial**
  licence (personal/research use).
- **`grounding.expression`** — top tissues for a gene by **HPA** consensus RNA (nTPM), highest first.
  Accepts a `gene` symbol directly, or an `rsid`/`chrom`+`pos` it resolves to the gene first; optional
  `limit` (default 10, max 51). Answers "where is this gene expressed" — e.g. TCF7L2 is broadly expressed,
  MTHFR highest in epididymis/bone-marrow/heart. Bulk-tissue RNA, not cell-resolution or protein.
- **`grounding.celltype`** — top **cell types** for a gene by **HPA single-cell** RNA (nCPM) — the
  single-cell-resolution companion to `grounding.expression` (e.g. TCF7L2 → colonocytes/adipocytes rather
  than just "broadly expressed"). Same gene/locus inputs; still bulk-of-a-cell-type RNA, not protein.

## Interpretation

- A **coding-exon** variant can change the protein (pair with `variant.resolve` / `acmg.classify`); an
  **intron**/**intergenic** variant is non-coding — its effect, if any, is regulatory (splicing, enhancer)
  and needs different evidence (`splice.assess`), not a missense predictor.
- Grounding is **context, not a verdict**: being in a pathway or a coding exon is not pathogenicity.
- **Pathway breadth varies.** Reactome is hierarchical — a gene in a top-level set like *Metabolism* is
  not specifically implicated; prefer the **most specific** (deepest) pathway names when explaining a
  finding. Membership connects a variant's gene to a mechanism; it does not weight the variant.
- **Expression is bulk-tissue context, not specificity or protein.** A high nTPM tissue is *where* the
  transcript is abundant; many genes are broadly expressed at low levels, so presence in a tissue is not
  evidence of specificity, and RNA ≠ protein abundance. Use it to connect a finding to plausible tissue
  biology (e.g. a β-cell/intestinal gene for a metabolic variant), not to assert a mechanism.
- The model is **MANE Select coding transcripts** — non-coding genes and alternative transcripts are out of
  scope, so `intergenic` means "not in a MANE coding transcript", not "no gene here".
- **Region + regulatory together** characterise a locus: `region` says coding/intron/intergenic; for a
  non-coding hit, `regulatory` says whether it's a promoter/enhancer/CTCF element. A candidate cCRE is
  *biochemical evidence of regulatory potential* — not proof THIS variant alters it. An absence of cCRE is
  "not a registered regulatory element", not "no function".
