---
name: metabolic
description: CGM / glucose summaries (GMI, time-in-range) from the user's Active Health Index, with the freshness honesty rule — stale sensor data cannot be claimed as current glucose control. Use for glucose, CGM, Dexcom, GMI / estimated A1c, time-in-range, "how's my blood sugar", "my latest CGM".
tools:
  - cgm.glycemic_summary
mutating: false
---

# Metabolic — CGM glycemic summary

> Apply `skills/output-rules.md` (the delivery contract): stale CGM is *not measured*, never
> "normal" — freshness gates the answer.

Summarizes continuous-glucose data (estimated GMI, time-in-range) from the subject's index.

## When to use

The user asks about glucose, CGM/Dexcom, GMI / estimated A1c, time-in-range, glycemic
variability, or "how is my blood sugar".

## The contract — freshness is honesty

A glucose summary is only about the *current* user if the sensor data is recent. If the last
CGM reading is stale (older than its useful window), Indaga returns `not_measured` for
*current* glucose with `requires: [freshness]` — **an old sensor read is not your present
control.** The historical summary is surfaced as context, never as a current claim.

| situation | envelope | what to say |
|---|---|---|
| recent per-reading series | `evidence_present` (grade from days of wear) | state GMI / TIR, cite the wear window |
| only a session summary, fresh | `evidence_present` / `scoped_answer_only` | report counts; full GMI needs the per-reading series |
| sensor data stale (e.g. >90 days) | `not_measured` + `requires:[freshness]` | "Your CGM data is N days old — current glucose control is unknown, not normal." |
| no CGM at all | `not_measured` | never collected |

`negative_inference.allowed` is `false`.

## Tools

- **`cgm.glycemic_summary`** (entry) — GMI / TIR when fresh per-reading data exists; otherwise
  an honest freshness/summary state. Reads the glucose series or the CGM session summary fact.

## Interpretation

- When fresh: lead with GMI (and its prediabetes/normal band) and time-in-range; name the wear window.
- When stale: say plainly that the data is old and you can't claim current control; offer the
  historical context and suggest a fresh CGM stint if they want a current read.
- GMI is an estimate (Bergenstal 2018: 3.31 + 0.02392 × mean glucose mg/dL), not a lab A1c.
