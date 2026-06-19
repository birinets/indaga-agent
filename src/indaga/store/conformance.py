"""Conformance suite for any HealthlakeStore adapter (WS-0.2).

Every adapter — InMemoryStore now, LocalDuckDBStore (WS-1B.1), and later the
hosted/zero-knowledge vaults — must pass this. It encodes the invariants the
Engine, the MCP server, and the BYO-AI surface all rely on. It is intentionally
backend-agnostic: it takes a *factory* that returns a fresh, seeded store.

Run directly:
    python3 -m indaga.store.conformance

stdlib only (no test framework dependency).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable

from .port import HealthlakeReader, HealthlakeStore, HealthlakeWriter
from .types import (
    Caveat,
    CaveatCode,
    Correction,
    EvidenceGrade,
    Fact,
    FactQuery,
    Provenance,
    Scope,
    Severity,
    SourceRef,
    Surface,
    TimeSeries,
    TimeSeriesPoint,
)

StoreFactory = Callable[[], HealthlakeStore]


# --------------------------------------------------------------------------- #
# A shared, deterministic seed: two subjects, so isolation is testable.
# --------------------------------------------------------------------------- #

def seed(store: HealthlakeStore) -> None:
    a = Scope("alice")
    b = Scope("bob")

    ldl = Fact(
        fact_id="obs_alice_ldl",
        subject_id="alice",
        domain="lab",
        name="ldl_cholesterol",
        display="LDL Cholesterol",
        value_number=5.13,
        unit="mmol/L",
        observed_at=date(2026, 4, 24),
        reference_high=2.50,
        interpretation="high",
        code_system="LOINC",
        code="13457-7",
        evidence_grade=EvidenceGrade.A,
        confidence=1.0,
        provenance_id="prov_alice_ldl",
    )
    imputed = Fact(
        fact_id="obs_alice_pgs",
        subject_id="alice",
        domain="genomic",
        name="t2d_prs",
        display="Type-2 Diabetes PRS",
        value_number=0.23,
        evidence_grade=EvidenceGrade.D,
        confidence=0.6,
        caveats=(Caveat(CaveatCode.IMPUTED, "Imputed; directional only.", Severity.WARN),),
    )
    bob_secret = Fact(
        fact_id="obs_bob_ldl",
        subject_id="bob",
        domain="lab",
        name="ldl_cholesterol",
        value_number=2.0,
        unit="mmol/L",
        evidence_grade=EvidenceGrade.A,
    )

    store.upsert_facts(a, [ldl, imputed])
    store.upsert_facts(b, [bob_secret])
    # Provenance is attached through the port (works for any adapter), after the
    # fact it targets exists — adapters must enforce ownership on attach.
    store.attach_provenance(
        a,
        Provenance(
            "prov_alice_ldl", "obs_alice_ldl", "observation",
            "doc_x", "sha256:abc", "bloods/2026-04-24.json", "$.tests[1]",
            "validated_structured_json", 1.0, "validated",
        ),
    )
    store.append_timeseries(
        a,
        TimeSeries(
            "alice", "glucose_mgdl", "mg/dL",
            (TimeSeriesPoint(datetime(2026, 4, 1, 8, tzinfo=timezone.utc), 104.0),
             TimeSeriesPoint(datetime(2026, 4, 1, 9, tzinfo=timezone.utc), 131.0)),
        ),
    )
    store.record_correction(
        a,
        Correction("pgs", "t2d_prs", "23rd pct", "96th pct",
                   "TOPMed imputation corrected chip-only score",
                   datetime(2026, 5, 10, tzinfo=timezone.utc), "topmed_v2"),
    )
    store.register_source(a, SourceRef("sha256:abc", "Bloods 2026-04-24", "lab_pdf"))


# --------------------------------------------------------------------------- #
# Checks. Each returns (name, ok, detail).
# --------------------------------------------------------------------------- #

def _check(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, bool(ok), detail)


def run_conformance(factory: StoreFactory) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    store = factory()
    seed(store)
    alice, bob = Scope("alice"), Scope("bob")

    # 1. Adapter actually implements the port.
    results.append(_check(
        "implements HealthlakeStore (read+write)",
        isinstance(store, HealthlakeReader) and isinstance(store, HealthlakeWriter)
        and isinstance(store, HealthlakeStore),
    ))

    # 2. Subject isolation — the load-bearing invariant.
    alice_facts = store.get_facts(alice)
    leaked = [f for f in alice_facts if f.subject_id != "alice"]
    results.append(_check("scope isolation: no foreign facts returned", not leaked,
                          f"leaked={[f.fact_id for f in leaked]}"))

    bob_facts = store.get_facts(bob)
    results.append(_check("scope isolation: bob sees only bob",
                          all(f.subject_id == "bob" for f in bob_facts) and bob_facts))

    # 3. Provenance resolves for an owned fact, and refuses a foreign one.
    p_own = store.get_provenance(alice, "obs_alice_ldl")
    p_foreign = store.get_provenance(alice, "obs_bob_ldl")
    results.append(_check("provenance resolvable for owned fact", p_own is not None))
    results.append(_check("provenance refused across subjects", p_foreign is None))

    # 3b. attach_provenance refuses a target the subject does not own (write-path isolation).
    foreign_attach_refused = False
    try:
        store.attach_provenance(
            alice,
            Provenance("p_x", "obs_bob_ldl", "observation",
                       None, None, None, None, None, None, None),
        )
    except Exception:
        foreign_attach_refused = True
    results.append(_check("attach_provenance refuses foreign target", foreign_attach_refused))

    # 4. Every fact carries an evidence grade.
    graded = all(isinstance(f.evidence_grade, EvidenceGrade) for f in alice_facts)
    results.append(_check("every fact has an evidence grade", graded))

    # 5. Caveats present on a limited fact (the imputed PGS).
    pgs = next((f for f in alice_facts if f.name == "t2d_prs"), None)
    results.append(_check("imputed fact carries a caveat", bool(pgs and pgs.caveats)))

    # 6. claim-grade gating: an INSUFFICIENT/blocked fact is not claim-grade.
    blocked = Fact("x", "alice", "genomic", "weak", evidence_grade=EvidenceGrade.INSUFFICIENT)
    results.append(_check("INSUFFICIENT fact is not claim-grade", not blocked.is_claim_grade))
    results.append(_check("Grade-A lab IS claim-grade", next(f for f in alice_facts if f.name == "ldl_cholesterol").is_claim_grade))

    # 7. FactQuery filters: flagged_only and min_evidence.
    flagged = store.get_facts(alice, FactQuery(flagged_only=True))
    results.append(_check("flagged_only returns only abnormal facts",
                          flagged and all(f.interpretation not in (None, "normal") for f in flagged)))
    strong = store.get_facts(alice, FactQuery(min_evidence=EvidenceGrade.B))
    results.append(_check("min_evidence floor excludes weak facts",
                          all(f.evidence_grade.meets(EvidenceGrade.B) for f in strong)))

    # 8. Time series summary + scope.
    ts = store.get_timeseries(alice, "glucose_mgdl")
    results.append(_check("timeseries returns points + summary",
                          ts.n == 2 and ts.summary.get("mean") == 117.5))
    ts_bob = store.get_timeseries(bob, "glucose_mgdl")
    results.append(_check("timeseries scoped (bob has none)", ts_bob.n == 0))

    # 9. Corrections ledger loads for the Critic.
    corr = store.get_corrections(alice)
    results.append(_check("corrections ledger non-empty for alice", len(corr) == 1))

    # 10. Context pack is self-describing + subject-correct + manifest matches.
    pack = store.get_context_pack(alice)
    manifest_total = sum(pack.evidence_manifest.values())
    results.append(_check("context pack subject matches scope", pack.subject_id == "alice"))
    results.append(_check("context pack evidence_manifest counts all facts",
                          manifest_total == len(pack.facts)))
    results.append(_check("context pack carries query guidance", bool(pack.query_guidance)))
    results.append(_check("context pack honours surface", pack.surface is Surface.APP))

    # 11. genomics egress toggle (Surface-2 may forbid raw genomic facts).
    no_dna = store.get_facts(Scope("alice", surface=Surface.BYO_AI, include_genomics=False))
    results.append(_check("include_genomics=False suppresses genomic facts",
                          all(f.domain != "genomic" for f in no_dna)))

    return results


def main() -> int:
    from .memory import InMemoryStore

    results = run_conformance(lambda: InMemoryStore())
    width = max(len(n) for n, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        flag = "PASS" if ok else "FAIL"
        line = f"[{flag}] {name.ljust(width)}"
        if not ok and detail:
            line += f"  -- {detail}"
        print(line)
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
