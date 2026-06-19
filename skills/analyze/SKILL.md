---
name: analyze
description: The user's whole multi-omic picture in one place — a structured, evidence-graded report fusing the genome engine (ClinVar/ACMG/PGS/PGx/GWAS/ancestry/nutrigenomics + domain lenses) with labs, circadian, and CGM. Use to summarise everything Indaga knows about a person, or to produce a shareable HTML report. Every section carries its own honesty grade; not-yet-computed sources degrade honestly, never blank.
tools:
  - analyze.report
  - analyze.export
mutating: false
---

# Analyze

> Apply `skills/output-rules.md` (the delivery contract): lead with the few real findings and
> *suppress the benign/candidate dumps*; a `confirmed_rare` candidate is not a diagnosis; exact-allele
> match before you alarm.

`analyze` is Indaga's **synthesis surface** — it turns everything the engine computes into one
honest, evidence-graded picture. It does not re-derive anything: it CALLS the other capabilities'
handlers (genome + multi-omic) and assembles their results, each with its evidence envelope intact.
It is **read-only** — it reports what's already computed and never triggers imputation, annotation,
PharmCAT, ancestry builds, or the slow SpliceAI.

## When to use
"Summarise my health / my genome", "give me the full picture", "what does my data say overall",
"make me a report I can open / share with my doctor", "what should I act on first".

## The two tools
- **`analyze.report`** (entry) — the whole picture as **structured, graded sections**:
  `{sections:[{key, title, tier, summary, findings, evidence_envelope}], …}`. Agent-native — YOU
  narrate from it. One section per area: overview · hereditary cancer · polygenic scores ·
  pharmacogenomics · GWAS · ancestry · nutrigenomics · the genome domain lenses (cardio, methylation,
  metabolic, athletic, gut, immunity, hormones, skin, senses, mood, longevity, sleep, …) · blood
  panel · circadian · CGM.
- **`analyze.export`** (focused, mutating) — writes a **single self-contained, offline `report.html`**
  (dark/light, EN/RU/NL chrome, inlined Chart.js, citations) to `~/.indaga/<subject>/reports/` and
  returns the path. `{"lang":"en|ru|nl"}` picks the UI language. Open it in any browser, fully offline.

## The contract — read each section's envelope (the core rule)
**Every section carries its own `evidence_envelope`. Read it before you state that section's
finding.** The report maps the envelope to a visual `tier`, but the envelope is the source of truth:
- `evidence_present` → state the finding (tier ok/info/watch/alert by its own interpretation).
- `not_measured` / `not_observed_in_consulted_scope` → tier `neutral`; the data isn't there. **This is
  UNKNOWN, never "normal"/"no risk"** — surface it as "not measured — order/connect X", don't skip it.
- `index_incomplete` → tier `info`; the metric is still calibrating (e.g. Biological Midnight before
  14 nights) — say it's calibrating, don't state a value.
A genome-only subject (no labs/CGM/wearable) still gets a full report — the genome sections are rich
and the multi-omic sections degrade honestly to `neutral` with a next action. Lead with the rich,
confident sections (the genome depth); never imply a `neutral` section is a clean negative.

## Interpretation
- Lead with the **Overview** (headline at-risk findings + priority actions + top PGS + PGx alerts +
  ancestry), then go deep where the user asks.
- Pair genetics with the user's measured labs/CGM when both exist (the multi-omic moat) — e.g. the
  metabolic/cardio sections fuse PGS + TCF7L2/lipid genetics with the actual lipid/glucose labs.
- PGS percentiles are directional + population-relative; a `low` confidence means coverage-limited
  (understated), not a true low score. ACMG/ClinVar findings are Mendelian, distinct from PGS.
- `analyze` is decision-support, not diagnosis — recommend clinician review for clinical decisions.
