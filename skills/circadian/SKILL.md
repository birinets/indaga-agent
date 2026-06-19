---
name: circadian
description: The Biological Clock — the user's Biological Midnight (heart-rate nadir) computed by a validated 24-hour cosinor, with honest calibration gating. Use for "when is my biological midnight", "my body clock", HR nadir, circadian phase, light/meal/sleep timing anchored to the nadir.
tools:
  - clock.state
  - clock.biological_midnight
mutating: false
---

# Circadian — the Biological Clock

> Apply `skills/output-rules.md` (the delivery contract): a calibrating metric (<14 valid nights) has
> no value to state — say it's calibrating, don't quote a midnight.

Computes the **Biological Midnight** (the trough of the daily heart-rate rhythm) from the
wearable HR series via the All-of-Us / npj Digital Medicine 2025 full-24-hour cosinor. This
is the validated method — never estimate the nadir as "the lowest heart rate of the night".

## When to use

The user asks about their Biological Midnight, HR nadir, circadian phase, body clock,
chronotype-from-heart-rate, or when to time light / meals / wind-down.

## The contract — calibration is honesty

A Biological Midnight is only real after **≥14 valid sleep/HR nights**. The state machine:

| state | meaning | envelope |
|---|---|---|
| `real` | ≥14 nights, good cosinor fit (R²≥0.4), fresh | `evidence_present` / `answer_supported` — state the Midnight |
| `low_quality` | ≥14 nights but weak fit | `evidence_present` / `scoped_answer_only` — provisional |
| `stale` | good fit but data old | `evidence_present` / `scoped_answer_only` |
| `calibrating` | <14 valid nights | `index_incomplete` / `needs_more_data` — **do NOT state a Midnight**; report progress |
| `empty` | no HR data | `index_incomplete` — no clock yet |

`calibrating` is the wearable analogue of genomic callability: not enough signal to claim the
phase yet. `negative_inference.allowed` is always `false` for the clock.

## Tools

- **`clock.state`** (entry) — the full state: `state`, `valid_nights`, and the Biological
  Midnight *only when calibrated*. Start here.
- **`clock.biological_midnight`** (focused) — just the clock time, returned only when the
  clock is `real`/calibrated; otherwise the calibration state with the value withheld.

## Interpretation

- When `real`: state the Midnight (e.g. "≈03:46"), and anchor timing advice to it — morning
  light shortly after the nadir, dim light ~2-3 h before the user's habitual sleep, etc.
- When `calibrating`: say how many of 14 nights are in, and that the Midnight will appear once
  enough valid nights accumulate. Never invent a time.
- The Midnight is a wearable-derived proxy for circadian phase, not a clinical measurement.
