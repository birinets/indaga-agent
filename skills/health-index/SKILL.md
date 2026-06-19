---
name: health-index
description: General access to the user's Active Health Index — structured facts (labs/genomic/derived), high-frequency timeseries (HR, glucose), the AI context pack, provenance, connected sources, and the corrections ledger. Use for cross-domain queries, "what data do I have", "where did this number come from", or to assemble context for synthesis.
tools:
  - facts.query
  - sources.list
  - context_pack.get
  - timeseries.get
  - provenance.resolve
  - corrections.list
mutating: false
---

# Health-index — the queryable Active Health Index

> Apply `skills/output-rules.md` (the delivery contract): translate the vocabulary; absence is
> per-omic; never present a raw fact as a clinical conclusion.

The general-purpose query surface over the subject's multi-omic facts, timeseries, and
provenance. Prefer the domain capabilities (labs, circadian, metabolic) for domain questions;
use these for cross-domain access, provenance, and context assembly.

## Tools

- **`facts.query`** (entry) — structured facts with filters (`names`, `domains`, `flagged_only`,
  `min_evidence`, `limit`). Every fact is graded + caveat-wrapped; the envelope tells you whether
  the set supports a claim.
- **`sources.list`** (entry) — connected data sources + freshness ("what data do I have?").
- **`context_pack.get`** (entry) — the self-describing, source-backed pack (profile + facts +
  timeseries summaries + flagged + corrections + caveats + an evidence manifest). The right input
  for multi-domain synthesis.
- **`timeseries.get`** (focused) — a high-frequency series (`heart_rate_bpm`, `glucose_mgdl`)
  with summary stats; `include_points` for the raw series (large).
- **`provenance.resolve`** (focused) — where a `fact_id` came from (source file + locator). Use to
  cite a value precisely.
- **`corrections.list`** (focused) — superseded values and why (e.g. a chip-only score corrected by
  imputation). A corrected value must never be re-stated as current.

## The contract

Same envelope rules as everywhere: `evidence_present` to claim, `not_measured` /
`not_observed_in_consulted_scope` mean unknown not normal, `negative_inference.allowed` is
almost always `false`. Cite facts by `fact_id`; resolve provenance when a claim is load-bearing.
