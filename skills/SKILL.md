---
name: indaga
description: Use this skill for personal multi-omic health questions — circadian/Biological Midnight, labs, glucose/CGM, wearable trends, and the synthesis across them. Indaga answers from the user's own Active Health Index, never from generic knowledge, and is honest about what it can and cannot claim.
---

# Indaga

Indaga is a local-first, multi-omic personal-health runtime. It answers questions
about ONE person's own data — genome (later), labs, wearables, CGM, and the derived
metrics built from them — by querying their persistent **Active Health Index**, and
it reports exactly how strong each answer is through a single **evidence envelope**.

It is the multi-omic sibling of a genome agent: the same three spines (a persistent
per-subject index, one honesty contract, a dispatcher + per-capability skills), but
across every modality instead of DNA alone.

## How to call Indaga

Call through the MCP server: `mcp__indaga-healthlake__<operation>` (or your host's
equivalent namespace). `tools/list` shows only the **base set**; every other tool is
reached through the `indaga.invoke` dispatcher after you load the matching capability skill.

## Core rules (the honesty contract)

Every Indaga result carries an `evidence_envelope`. **Read it before you answer.** It
is the single source of truth for what the result can support — there is no parallel
policy in prose.

- `finding_state` + `answer_readiness` tell you the strength:
  - `evidence_present` / `answer_supported` → you may state the finding (cite the fact).
  - `evidence_present` / `scoped_answer_only` → answer, but only within the stated scope.
  - `index_incomplete` / `needs_more_data` → the metric is still **calibrating** (e.g. a
    Biological Midnight before 14 valid nights). Do NOT state the value; explain it's calibrating.
  - `not_measured` / `needs_more_data` → the analyte/metric was never collected, or the
    sensor data is **stale**. **Absence here is UNKNOWN, never "normal".** Do not say "your X is fine".
  - `not_observed_in_consulted_scope` → nothing matched in scope; do not imply a clinical negative.
  - `not_assessed` / `cannot_answer_yet` → could not assess; request inputs or use another tool.
- **`negative_inference.allowed` is almost always `false`.** Only state "you don't have X" /
  "your X is normal" when an envelope explicitly allows negative inference. Zero results ≠ a negative.
- **Derive confidence dynamically** from the envelope (grade, coverage, caveats) — never a
  static default. Mention personal data use only when it materially shapes the answer.
- **n=1, always.** Every query is hard-scoped to the one subject; never mix people's data.
- Indaga is wellness decision-support, not diagnosis. Keep clinical language informational and
  recommend clinician review for medical decisions.

## Routing

`tools/list` returns only the base set:
- `indaga.*` (always direct-callable): `indaga.invoke`, `indaga.describe_context`,
  `indaga.list_capabilities`, `indaga.read_skill`, `indaga.install` (fetch reference libraries),
  `indaga.check_libraries` (what's installed), `indaga.check_background_job` (poll long jobs).
- each capability's **entry tool** (e.g. `clock.state`, `facts.query`, `labs.query`,
  `cgm.glycemic_summary`, `sources.list`, `context_pack.get`).

To use a non-base (focused) tool, load its capability skill, then call:

```
indaga.invoke({"tool": "<operation_name>", "params": {...}})
```

Discover capabilities + their skill paths with `indaga.list_capabilities`; fetch a skill's
markdown with `indaga.read_skill({"capability": "circadian"})`. Then call the smallest useful
tool, read its envelope, and continue until the answer is supported.

## Capabilities

- **genome** — DNA from the subject's own imputed genome: genotype + callability, ClinVar, P/LP screen (carrier/confidence-tiered), polygenic scores, **in-house PharmCAT PGx** (`pgx.summary` after `genome.pgx_run`), **GWAS-Catalog associations** (`gwas.associations`), **continental ancestry** (`ancestry.estimate`), and a **computed ACMG/AMP classification** (`acmg.classify`). Run the pipeline with `genome.impute` (background) → `genome.annotate`. `skills/genome/SKILL.md`
- **domains** — genome-domain lenses (methylation, hormones, immunity, gut, skin, sleep, longevity, athletic, …). `skills/domains/SKILL.md`
- **nutrigenomics** — interpreted food/nutrient genetics (lactose, caffeine, alcohol, MTHFR, iron, taste). `skills/nutrigenomics/SKILL.md`
- **circadian** — the Biological Clock / Biological Midnight (HR-nadir cosinor). `skills/circadian/SKILL.md`
- **labs** — lab analytes + panel coverage (measurement-present honesty). `skills/labs/SKILL.md`
- **metabolic** — CGM glycemic summary (freshness honesty). `skills/metabolic/SKILL.md`
- **health-index** — general facts / timeseries / context-pack / provenance / sources / corrections. `skills/health-index/SKILL.md`
- **synthesis** — fuse DNA × labs × PGS × CGM for a topic into one grounded answer (the multi-omic edge). `skills/synthesis/SKILL.md`
- **analyze** — the user's WHOLE multi-omic picture in one place: `analyze.report` (structured, evidence-graded sections) + `analyze.export` (a self-contained, offline `report.html`). Read-only; every section carries its honesty grade and degrades gracefully. `skills/analyze/SKILL.md`
- *(later: journal)*

## Multi-stream synthesis

When several capabilities can contribute orthogonal evidence to one question (e.g. glucose ×
genotype × recent sleep), combine them. A scope-limited single-capability result
(`not_measured`, `index_incomplete`, stale) is not a final answer when another capability can
still contribute — but never paper over a genuine gap; report it honestly.

## Answering

Lead with the answer. Name the data behind it when it materially shapes the result (the lab
draw, the wearable series, the date range). Pair every capability with its limit and every
number with its uncertainty. The honesty *is* the product.

**Two conventions govern every answer — read both:**
- `skills/conventions/evidence-envelope.md` — what an answer may *claim* (the data contract).
- `skills/output-rules.md` — how to *render* it (the delivery contract): lead with meaning;
  a predictor score (`am_class`/REVEL/SpliceAI/PGS) is never a diagnosis; exact-allele match before
  you alarm; translate `DR2`/typed-vs-imputed/ClinVar into plain terms; absence is per-omic; fuse
  streams. Apply it on top of every capability skill below.
