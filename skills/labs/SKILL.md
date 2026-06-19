---
name: labs
description: Blood-lab analytes from the user's Active Health Index, with the measurement-present honesty rule — an analyte that was never measured returns "not measured" (unknown), never a false "normal". Use for cholesterol/LDL/HDL, triglycerides, ApoB, HbA1c, glucose, and "what's my <lab>", "is my <lab> normal", "what labs am I missing".
tools:
  - labs.query
  - labs.panel_coverage
mutating: false
---

# Labs

> Apply `skills/output-rules.md` (the delivery contract): *"measured & normal" ≠ "never measured"*;
> absence is per-omic; a stale value is not a current one.

Answers lab questions from the subject's stored, LOINC-coded, provenance-stamped lab facts.

## When to use

The user asks about a blood lab (LDL, ApoB, HbA1c, triglycerides, …), whether a lab is
normal, trends, or which labs they're missing.

## The contract — "measured & normal" ≠ "never measured"

This is the lab analogue of genomic callability. If an analyte has **no fact** in the index,
the answer is `not_measured` — **absence is UNKNOWN, not normal.** Never tell the user a lab
is fine when it was simply never drawn.

| situation | envelope | what to say |
|---|---|---|
| analyte present, Grade A/B | `evidence_present` / `answer_supported` | state the value + flag (high/normal), cite the draw |
| analyte present, low grade | `evidence_present` / `scoped_answer_only` | report it, qualified |
| analyte never measured | `not_measured` / `needs_more_data` | "X was never measured — unknown, not normal. Consider ordering it." |

`negative_inference.allowed` is `false`: zero results never means "you don't have a problem".

## Tools

- **`labs.query`** (entry) — one analyte (`{"analyte": "apob"}`) or all labs. A missing analyte
  returns `not_measured`. With no analyte, returns the lab panel (use `flagged_only` for abnormals).
- **`labs.panel_coverage`** (focused) — which analytes of a panel are present vs never measured.
  Use to answer "what should I add to my next blood test?" honestly. (v1 uses a default
  cardiometabolic panel; a full LOINC panel map is a later refinement.)

## Interpretation

- Lead with the measured value and its flag; cite the source draw (provenance is available via
  `provenance.resolve`).
- For a missing analyte, recommend ordering it rather than reassuring — and never substitute a
  related lab as if it were the asked-for one.
- Keep clinical language informational; recommend clinician review for medical decisions.
