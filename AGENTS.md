# AGENTS.md — developing Indaga-agent

Guidelines for working **on** Indaga-agent (not host-runtime instructions — those live in
`skills/SKILL.md`). The design mirrors a genome agent's three spines, generalized to multi-omic.

## Principles

1. **One honesty contract, everywhere.** Every capability result reports answer-readiness through
   the `EvidenceEnvelope` (`src/indaga/evidence/envelope.py`) and nowhere else — no parallel prose
   policy, no second typed structure. Need a new facet? Extend the envelope.
2. **Absence is never "normal".** `negative_inference.allowed` defaults to `false`. A genuine "you
   don't have X" requires its requirements satisfied (callability / measurement_present / calibrated
   / freshness / library_coverage …). This is the product's reason to exist; do not weaken it.
3. **The deterministic spine is right or wrong independent of any model.** Science (the 24-h cosinor,
   CGM math, PGS) lives in `src/indaga/spine/`. The LLM synthesizes and explains; it never adjudicates.
4. **The storage-agnostic port is load-bearing.** Capability handlers talk to `HealthlakeStore`
   (`store/port.py`), never to a `.sqlite` path. New backends are adapters that pass
   `store/conformance.py`. This is what keeps local-vs-hosted-vs-zero-knowledge open.
5. **Facts in, envelope out.** `Fact.evidence_grade` + `Fact.caveats` are the inputs; `derive_envelope`
   is the bridge to the typed output. Don't hand-build envelopes when `derive_envelope` fits.
6. **Progressive disclosure.** Only base + entry tools appear in `tools/list`; focused tools are
   reached via `indaga.invoke` after reading the capability `SKILL.md`. Keep capability skills the
   single place that documents a capability's tools and interpretation rules.
7. **n=1, always.** Every read is hard-scoped to one subject. Adapters enforce it; the conformance
   suite checks it. Never add a path that can return another subject's data.
8. **Verb-based, distinct tool names** (`clock.state`, `labs.panel_coverage`). No aliases.

## Adding a capability

1. Implement handlers `fn(params, context) -> dict` in `src/indaga/capabilities/<cap>.py`; each returns
   a payload with an `evidence_envelope` (use `derive_envelope` or a typed constructor).
2. `register(Operation(...))` each tool with `capability`, `skill`, `discovery_role`
   (`entry_tool`/`focused_tool`), and `omic_scope`.
3. Add `from ..capabilities import <cap>` to `operations/bootstrap.py`.
4. Write `skills/<cap>/SKILL.md` (frontmatter `name/description/tools/mutating` + body of triggers,
   contract, tools, interpretation).
5. Add envelope-state assertions to `src/indaga/eval/envelope_eval.py`.

## Tests / gates

```bash
PYTHONPATH=src python3 -m indaga.store.conformance     # port conformance (all adapters)
PYTHONPATH=src python3 -m indaga.eval.envelope_eval    # the honesty regression gate
PYTHONPATH=src python3 -m indaga.interfaces.cli selftest --subject <s> --user-dir <dir>
```

## Determinism

The cosinor + state machines must be deterministic. Don't introduce wall-clock or RNG into the
spine or store paths; `generated_at` / `now` are injectable so evals stay reproducible.
