---
name: nutrigenomics
description: Interpreted food & nutrient genetics from the chip — lactose tolerance, caffeine + alcohol metabolism, folate (MTHFR), vitamin B12/A, iron (HFE), appetite (FTO), bitter taste. Use for "can I digest dairy", "am I a fast/slow caffeine metabolizer", "alcohol flush", "MTHFR/folate", "iron genes", "why do I crave / taste X". Refuses diet prescriptions and supplement dosing.
tools:
  - nutrigenomics.markers
mutating: false
---

# Nutrigenomics — interpreted single-marker food/nutrient genetics

> Apply `skills/output-rules.md` (the delivery contract): single-marker effects are modest — never a
> diagnosis or a prescription; an `am_class` on a common variant (MTHFR C677T) is not pathogenic.

Resolves a curated nutrigenetic panel from the Active Genome Index and gives each genotype a
plain-English meaning (the interpreted layer the domain bundles don't provide).

## The contract — modest, probabilistic, never a prescription

Single-marker nutrigenetic effects are **modest and probabilistic**, not deterministic. Stay in scope:
**no diet prescriptions, no supplement dosing, no weight-loss prediction.** A marker not on the chip is
`not_measured` (unknown), never "you're fine". Always pair with the user's **actual labs** — the genotype
suggests a tendency; the lab measures reality (e.g. HFE iron genes × ferritin; MTHFR × homocysteine).

## Tool

- **`nutrigenomics.markers`** (entry) — all interpreted markers (or filter by `category`:
  food-tolerance / nutrient-metabolism / eating-behavior / taste / sensitivity). Returns genotype,
  effect-allele count, and the interpretation per marker, plus which markers weren't on the chip.

## How to answer

- State the trait + the user's genotype + what it means (e.g. "CYP1A2 — you carry the slow-metabolizer
  genotype, so caffeine lingers; consider an earlier cut-off").
- Pair with labs/measured data where relevant; recommend the measurement when it's missing.
- Keep it directional and non-prescriptive; suggest clinician/dietitian review for anything actionable.
