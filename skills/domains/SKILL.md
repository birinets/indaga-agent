---
name: domains
description: Genome-domain lenses — the user's variants in a curated gene panel for a wellness domain (methylation, hormones, immunity, gut, skin, sleep, longevity, athletic, mood/focus, senses, hereditary-cancer, metabolic, cardiovascular). Use for "my methylation genes", "my detox/COMT", "hormone genetics", "skin/aging genes", "athletic/muscle genes", or any domain-scoped DNA question.
tools:
  - domains.list
  - domains.get
mutating: false
---

# Domains — genome lenses per wellness area

Each domain is a curated gene panel + the subject's annotated variants in it + the relevant labs +
recommended missing tests (computed on imputed data). Use these for domain-scoped DNA questions;
use `genome.variant.resolve` for a single rsID and `synthesis` to fuse a domain's DNA with labs/CGM.

## Tools

- **`domains.list`** (entry) — the available lenses with panel + variant counts.
- **`domains.get`** (entry) — `{"domain": "methylation"}` → the panel genes, the subject's variants
  (rsID, gene, ClinVar significance, AlphaMissense, and the genotype from the chip), the relevant
  labs, and recommended missing tests.

## How to answer

> Apply `skills/output-rules.md` (the delivery contract) — esp. *suppress the benign dump*,
> *a predictor `am_class` is never a diagnosis* (MTHFR C677T is common → not pathogenic), and *fuse
> the genetics with measured labs*.
- **Lead with the *notable* variants** (`notable_variants`), not the long benign list — most ClinVar
  rows in a panel are benign/common and should not alarm.
- A "risk factor"/"susceptibility"/"uncertain" class is association, not a diagnosis.
- **Pair the genetics with the user's measured labs** in the same bundle (e.g. methylation genes ×
  homocysteine/folate; hormone genes × the hormone panel; iron genes × ferritin) — and flag the
  `missing_tests_recommended` when the relevant lab is absent. That pairing is the point.
- Carrier/pathogenic and hereditary-cancer findings are decision-support — recommend clinical genetics review.
