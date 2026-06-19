# Convention — the evidence envelope

Every Indaga-agent capability result carries one `evidence_envelope`. It is the single source of
truth for how strong the answer is. Read it before you answer; never invent a parallel verdict in prose.

## Fields

- `finding_state` — what was found:
  - `evidence_present` — at least one decision-grade fact in scope.
  - `not_observed_in_consulted_scope` — looked, found nothing in scope (NOT a negative).
  - `not_measured` — the analyte/metric was never collected, or the sensor data is stale (UNKNOWN).
  - `index_incomplete` — a derived metric is still calibrating (e.g. Biological Midnight < 14 nights),
    or a genomic index is still building.
  - `blocked_missing_library` — a reference library needed to answer isn't installed.
  - `not_assessed` — could not assess (missing inputs / scope mismatch).
  - `true_negative_supported` — a genuine "you don't have this", with its requirements satisfied.
- `answer_readiness` — `answer_supported` · `scoped_answer_only` · `cannot_answer_yet` ·
  `needs_user_install` · `needs_index_build` · `needs_more_data` · `needs_clinical_confirmation`.
- `negative_inference` — `{allowed, requires[], satisfied[]}`. **`allowed` is almost always false.**
  Only state "you don't have X" / "your X is normal" when an envelope explicitly allows it.
  Requirement tokens: `callability`, `genotype_support`, `library_coverage` (genomic);
  `measurement_present`, `panel_alignment`, `calibrated`, `freshness` (multi-omic); `scope_alignment`,
  `clinical_confirmation`.
- `coverage`, `observations`, `next_actions`, `guidance` (typed codes), `notes`.

## How to answer per state

| finding_state / answer_readiness | what you may say |
|---|---|
| evidence_present / answer_supported | State the finding; cite the fact_id / source. |
| evidence_present / scoped_answer_only | Answer, but only within the stated scope; qualify it. |
| index_incomplete / needs_more_data | Do NOT state the value. Explain it's calibrating + the progress. |
| not_measured / needs_more_data | "X is not measured — unknown, not normal." Suggest collecting it. |
| not_observed_in_consulted_scope | Nothing matched in scope; do not imply a clinical negative. |
| not_assessed / cannot_answer_yet | Ask for the missing input or use another capability. |
| true_negative_supported | A real negative — state it with its scope. |

The honesty IS the product. A confident wrong "your X is fine" is the failure mode this contract exists to prevent.
