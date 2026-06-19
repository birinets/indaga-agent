---
name: journal
description: The persistent investigation journal — local, per-subject working memory for an analysis. Record questions, findings, hypotheses, ruled-out items, conclusions, and next steps so a later turn or session resumes instead of re-deriving. Use to log what you concluded/ruled out, and to recall "where were we" at the start of a session.
tools:
  - journal.append
  - journal.read
  - journal.summary
mutating: false
---

# Journal — persistent investigation memory

> Apply `skills/output-rules.md`: the journal is the agent's **reasoning trail**, not clinical fact. Entries
> are operational memory (n=1), never a substitute for a graded finding or a clinician.

A genomic/health investigation runs across many turns and sessions. Without a record, a later session
re-derives what was already settled — re-asks ruled-out questions, re-checks closed variants. The journal is
an **append-only, per-subject case-file** (stored locally at `~/.indaga/<subject>/journal.sqlite`, 0600) so
the analysis has continuity.

## When to use

- **At the start of a session:** `journal.summary` (or `journal.read`) to recall the open questions,
  hypotheses, what's been ruled out, and the planned next steps.
- **As you work:** `journal.append` to record a conclusion, a ruled-out hypothesis, or a next step — anything
  a future session would otherwise have to reconstruct.

## Tools

- **`journal.append`** — record one entry. `text` (required) + a `kind`:
  `question` · `finding` · `hypothesis` · `ruled_out` · `conclusion` · `next_step` · `note` (unknown → `note`).
  Optional `gene` / `rsid` / `tool` tags and a free-form `refs` object (e.g. `allele_id`, PMIDs). The only
  mutating tool here.
- **`journal.read`** — the log, newest first; filter by `kind` and/or `gene`, `limit` (≤500).
- **`journal.summary`** — a "where are we" digest: counts by kind + the most recent questions, hypotheses,
  ruled-out items, conclusions, and next steps.

## Interpretation

- **Record decisions, not raw data.** The journal complements the evidence stores; it captures *reasoning*
  (why a variant was set aside, what to check next) — not genotypes or labs (those live in the genome/health
  stores and are re-queried).
- **`ruled_out` is the highest-value kind** — it's what stops a later session from re-litigating settled
  ground. Be specific about *why* (the evidence that ruled it out).
- Strictly **one subject** — the journal lives in that subject's secured tree; it never mixes subjects.
