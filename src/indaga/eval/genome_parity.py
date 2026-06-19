"""Genome annotation parity / correctness eval — Indaga's OWN pipeline (no external project).

Validates that Indaga's self-computed genome evidence reproduces the known-true findings
on a real subject, with the honesty contract intact:

  A. P/LP screen   — ESR1 rs9340799 is surfaced and REFUTED as common_likely_false_alarm
                     (gnomAD AF ≈ 0.31), and there are 0 confirmed-rare P/LP in the
                     priority panels (the reassuring headline).
  B. PGS math      — the analytic μ/σ/percentile port is exact on a synthetic score.
  C. Tool envelopes— variant.resolve / clinvar.findings / pgs.score / gwas.associations
                     return the right payloads + evidence envelopes (GWAS T2D surfaces
                     TCF7L2 rs7903146, ranked by -log10(p)).
  D. Libraries     — check_libraries reports ClinVar + PGS installed under ~/.indaga.

Run after a subject has been annotated (the first build_context annotate is the slow,
network step; this reuses the cached evidence store):

    PYTHONPATH=src python3 -m indaga.eval.genome_parity --subject demo \\
      --user-dir /path/to/users/demo
"""

from __future__ import annotations

import argparse
import math
import sys

from ..interfaces.mcp import build_context
from ..operations import call_operation
from ..operations.model import Context


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def _b_pgs_math() -> bool:
    from ..genome.pgs import compute_score
    specs = [(0.2, 0.5, 2), (0.3, -0.4, 1), (0.1, 0.8, 0), (0.4, 0.2, 2), (0.25, -0.6, 1),
             (0.5, 0.3, 0), (0.15, 0.9, 2), (0.35, -0.2, 1), (0.45, 0.5, 2), (0.2, 0.7, 0),
             (0.3, -0.5, 1), (0.4, 0.6, 2)]
    rows, pgs_index = [], {}
    for i, (af, w, dose) in enumerate(specs):
        rows.append((str(i), 1000 + i, "A", "G", w, af, None))  # af in the file row
        # pgs_index: (allele1, allele2, alt, panel_af) — af here None; the file af drives μ/var
        pgs_index[(str(i), 1000 + i)] = ({2: ("A", "A"), 1: ("A", "G"), 0: ("G", "G")}[dose] + ("G", None))
    r = compute_score(rows, pgs_index)
    raw = sum(w * d for (af, w, d) in specs)
    mu = sum(2 * af * w for (af, w, d) in specs)
    var = sum(2 * af * (1 - af) * w * w for (af, w, d) in specs)
    z = (raw - mu) / math.sqrt(var)
    pct = 100 * 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return (abs(r["raw_score"] - raw) < 1e-9 and abs(r["pop_mu"] - mu) < 1e-9
            and abs(r["percentile"] - pct) < 1e-9)


def run(subject: str, user_dir: str) -> int:
    ctx: Context = build_context(subject, user_dir)
    from ..genome import evidence as ev

    passed = 0
    total = 0

    # A. P/LP screen
    findings = ev.pl_findings(None, subject)
    esr1 = [f for f in findings if f.get("gene") == "ESR1"]
    a1 = bool(esr1) and all(f["classification"] == "common_likely_false_alarm" for f in esr1)
    priority_rare = [f for f in findings if f.get("classification") == "confirmed_rare" and f.get("panel") != "—"]
    print("A. P/LP screen (Indaga's own ClinVar position-join + gnomAD refutation)")
    total += 1; passed += _check("ESR1 surfaced and refuted as common_likely_false_alarm",
                                 a1, f"{[f.get('gnomad_af') for f in esr1]}")
    total += 1; passed += _check("0 confirmed-rare P/LP in priority panels", not priority_rare,
                                 f"{len(priority_rare)} found" if priority_rare else "clean")
    total += 1; passed += _check("screen produced findings", len(findings) > 0, f"{len(findings)} carried P/LP")

    # B. PGS math
    print("B. PGS analytic math")
    total += 1; passed += _check("synthetic μ/σ/percentile exact", _b_pgs_math())

    # C. tool envelopes
    print("C. tool envelopes")
    vr = call_operation("variant.resolve", {"rsid": "rs7903146"}, ctx)
    total += 1; passed += _check("variant.resolve rs7903146 → genotype + envelope",
                                 vr.get("genotype") is not None and "evidence_envelope" in vr,
                                 f"{vr.get('gene')} {vr.get('genotype')}")
    cf = call_operation("clinvar.findings", {}, ctx)
    total += 1; passed += _check("clinvar.findings → envelope", "evidence_envelope" in cf,
                                 f"{cf.get('n_candidates')} candidates, {cf.get('likely_real')} likely-real")
    ps = call_operation("pgs.score", {"trait": "diabetes"}, ctx)
    total += 1; passed += _check("pgs.score → envelope", "evidence_envelope" in ps,
                                 f"{ps.get('n_total')} scores")
    ga = call_operation("gwas.associations", {"trait": "type 2 diabetes", "limit": 5}, ctx)
    assoc = ga.get("associations", [])
    # the validated T2D hit (TCF7L2 rs7903146) must surface, strongest-first by -log10(p)
    t2d_ok = any(a.get("rsid") == "rs7903146" for a in assoc) and "evidence_envelope" in ga
    total += 1; passed += _check("gwas.associations T2D → TCF7L2 rs7903146", t2d_ok,
                                 f"{len(assoc)} hits, top={assoc[0].get('gene') if assoc else None}")
    # PGx: only checked when PharmCAT has been run (genome.pgx_run is a background job, not part
    # of annotate) — the RYR1 malignant-hyperthermia flag is the highest-actionability finding.
    if ev.pharmcat_available(subject):
        px = call_operation("pgx.summary", {}, ctx)
        dips = {d["gene"]: d for d in px.get("diplotypes", [])}
        ryr1 = dips.get("RYR1", {})
        cyp2c19 = dips.get("CYP2C19", {})
        # The PGx subset DR2-gates sub-threshold ALT calls to ./. : the genuine RYR1 MH het (DR2=1)
        # must survive, and CYP2C19 must call *2 (the three DR2=0 1|1 artifacts that forced a no-call
        # are gated out → clopidogrel guidance restored). NAT2's prior "Poor Metabolizer" came from
        # DR2=0/absent imputed positions (an over-claim) and is now an honest no-call until the PGx
        # chip-overlay lands (NAT2 is densely chip-typed but imputes to zero confidence).
        pgx_ok = ("Uncertain Susceptibility" in (ryr1.get("phenotype") or "")
                  and "*2" in (cyp2c19.get("diplotype") or ""))
        total += 1; passed += _check("pgx.summary → RYR1 MH flag + CYP2C19 *2 (DR2-gated)", pgx_ok,
                                     f"RYR1={ryr1.get('diplotype')}, CYP2C19={cyp2c19.get('diplotype')}, {len(dips)} called")
    else:
        _check("pgx.summary (skipped — run genome.pgx_run to enable)", True, "PharmCAT not yet run")
    # ancestry: only checked when the AIM reference is built (a one-time panel scan)
    from ..connectors.ancestry import aim_reference_path
    if aim_reference_path().exists():
        an = call_operation("ancestry.estimate", {}, ctx)
        # demo is European → EUR must be the top continental assignment, AFR the least similar
        sim = an.get("similarity", {})
        anc_ok = (an.get("assigned_superpopulation") == "EUR"
                  and (not sim or min(sim, key=sim.get) == "AFR"))
        total += 1; passed += _check("ancestry.estimate → EUR (European subject)", anc_ok,
                                     f"assigned={an.get('assigned_superpopulation')}, conf={an.get('confidence')}")
    else:
        _check("ancestry.estimate (skipped — AIM reference not built)", True, "run ancestry.estimate to build")

    # E. consequence annotator + REVEL (Phase E "deepen the engine")
    print("E. consequence annotator + REVEL")
    from ..genome.consequence import ConsequenceAnnotator
    ann = ConsequenceAnnotator.open()
    if ann is not None:
        # MTHFR A222V → missense (protein cross-validates AlphaMissense); a known BRCA2 nonsense → stop_gained
        mthfr = ann.annotate("1", 11796321, "G", "A")
        brca2 = ann.annotate("13", 32316470, "G", "T")
        ann.close()
        cons_ok = (mthfr and mthfr["consequence"] == "missense_variant" and mthfr["protein"] == "p.A222V"
                   and brca2 and brca2["consequence"] == "stop_gained")
        total += 1; passed += _check("consequence: MTHFR→missense(A222V), BRCA2→stop_gained", cons_ok,
                                     f"{mthfr and mthfr.get('protein')}, {brca2 and brca2.get('consequence')}")
    else:
        _check("consequence annotator (skipped — MANE/FASTA not installed)", True, "")
    from ..genome.predictors import Revel
    rv = Revel.open()
    if rv is not None:
        score = rv.lookup("1", 11796321, "G", "A")  # MTHFR A222V → REVEL damaging-leaning
        rv.close()
        total += 1; passed += _check("REVEL: MTHFR A222V scored", score is not None and score > 0.5,
                                     f"REVEL={score}")
    else:
        _check("REVEL (skipped — not installed)", True, "")
    # SpliceAI: validate availability + the delta-score→PP3 band mapping (NOT a TensorFlow run,
    # which is slow; the connector's scoring is exercised in its own test).
    from ..connectors import spliceai as spliceai_mod
    if spliceai_mod.available():
        sp_ok = (spliceai_mod.pp3(0.99) == ("PP3", "strong") and spliceai_mod.pp3(0.6) == ("PP3", "moderate")
                 and spliceai_mod.pp3(0.1) is None)
        total += 1; passed += _check("SpliceAI: available + delta-score→PP3 bands", sp_ok)
    else:
        _check("SpliceAI (skipped — TF venv not installed)", True, "")

    # D. libraries
    print("D. reference libraries (~/.indaga)")
    from ..reference import check_all
    libs = check_all()
    inst = set(libs["installed"])
    total += 1; passed += _check("ClinVar + PGS metadata installed",
                                 {"clinvar-grch38", "clinvar-grch37"} & inst and "pgs-catalog-metadata" in inst,
                                 f"installed: {sorted(inst)}")

    print(f"\n{passed}/{total} genome-parity checks passed.")
    return 0 if passed == total else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="genome_parity")
    p.add_argument("--subject", required=True)
    p.add_argument("--user-dir", required=True)
    args = p.parse_args(argv)
    return run(args.subject, args.user_dir)


if __name__ == "__main__":
    sys.exit(main())
