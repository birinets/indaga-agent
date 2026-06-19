---
name: synthesis
description: Multi-omic synthesis — fuse the user's DNA, labs, polygenic scores, and CGM/wearable data for one topic into a single grounded answer (e.g. "my diabetes risk" = TCF7L2 genotype × T2D polygenic score × CGM × glucose labs). Use whenever a question spans modalities, or asks for the "big picture", "overall risk", or "what does all my data say about X".
tools:
  - synthesis.multi_omic_question
mutating: false
---

# Synthesis — the multi-omic fusion

> Apply `skills/output-rules.md` (the delivery contract): *fuse, don't silo* — name what each stream
> contributes and pair genetics with the user's measured values.

This is what makes Indaga more than a genome agent: it answers a question by combining ALL of the
user's modalities at once, grounded and caveated. A genomics-only or labs-only tool sees one slice;
synthesis sees the convergence.

## When to use

The question spans modalities or asks for the whole picture: "what's my diabetes risk?", "should I
worry about my heart?", "what does all my data say about my metabolism?", "overall, what stands out?".

## Tool

- **`synthesis.multi_omic_question`** (entry) — `{"topic": "diabetes"}` → a fused pack:
  - `dna` — relevant genotypes (resolved from the Active Genome Index, with ClinVar),
  - `labs` — relevant lab facts,
  - `polygenic_scores` — relevant PGS percentiles,
  - `timeseries` / `derived` — relevant CGM / wearable / circadian metrics,
  - `synthesis_guidance` + an `evidence_envelope`.
  Known topics (diabetes, cardiovascular, methylation) pull the right variants/labs/scores; any other
  topic falls back to keyword matching.

## How to answer

1. **Lead with the convergent picture.** Say where the modalities AGREE (e.g. "your TCF7L2 risk
   genotype AND a 90th-percentile T2D polygenic score AND your CGM all point the same way").
2. **Name divergence and gaps honestly.** Where modalities disagree, or data is missing/stale, say so
   — a stale CGM can't speak to current control; a not-on-chip variant is unknown; a normal lab is
   reassuring only for what was measured.
3. **Never convert a genotype or percentile into a diagnosis.** PGS is population-relative and
   directional; a risk allele is association, not destiny. Pair genetics with the user's ACTUAL
   measured biology — that pairing is the whole point.
4. Decision-support, to be reviewed with a clinician.
