---
name: decision
description: The single highest-leverage daily action ("Today"). Use for "what should I do today", "my one decision", "highest-leverage action right now", the morning chrono-metabolic nudge. Deterministic ranker over existing findings; honest when nothing is decision-grade.
tools:
  - decision.today
mutating: false
---

# Decision — the one daily action

> Apply `skills/output-rules.md` and `skills/conventions/evidence-envelope.md`. The decision's
> confidence chip is the envelope of its **weakest required leg** — render it, never re-derive it.

Implements the PRD's doctrine: **one decision, not twenty insights**. The home surface shows a single
prioritised action — not a dashboard.

## When to use

The user (or the Today surface) asks for the single most useful thing to do right now, the morning
chrono-metabolic nudge, or "what's my one decision today?".

## The contract — eligibility is honesty

`decision.today` fans out to existing entry tools (currently `clock.state`, `cgm.glycemic_summary`) and
scores a fixed candidate set. A candidate is **eligible only when its *required* legs are
`evidence_present`** — decision-grade. Optional *enriching* legs (e.g. a fresh CGM) only strengthen the
wording; they never gate eligibility and never weaken the chip.

| situation | decision | envelope (→ chip) |
|---|---|---|
| a candidate's required legs are decision-grade | the highest-leverage eligible action | the **weakest required leg's** envelope (e.g. `evidence_present`/`answer_supported` → High) |
| clock still calibrating (<14 nights) | honest "nothing urgent — clock calibrating" | `index_incomplete` / `needs_more_data` → Calibrating |
| no candidate decision-grade for another reason | honest "nothing you must act on" | `not_assessed` / `cannot_answer_yet` → Neutral |

We **never manufacture urgency**: if nothing is decision-grade, the card says so.

## Tools

- **`decision.today`** (entry) — returns `{decision, candidates, evidence_envelope}`.
  - `decision.action_template` + `decision.params` — a deterministic, verb-first default (usable with
    no model). The assistant/gateway may *re-phrase* it, but must not change the action or its anchor.
  - `decision.legs` — the findings the action leans on (required vs enriching) with their states.
  - `candidates` — every candidate with its eligibility + required-leg states (the audit trail of why
    this action and not another).

## Interpretation

- The numeric anchors are **provisional chrono-metabolic heuristics** (e.g. eating-window close =
  Biological Midnight − 8 h), explicitly labelled in `decision.heuristic`. They are decision-support,
  not clinical prescriptions.
- Phrase the action in the user's voice if you like, but keep the verb and the anchor exactly as given,
  and keep the confidence chip equal to the returned envelope.
