"""analyze-report eval — the user-facing report is graded + self-contained + honest.

Checks (subject-agnostic; run per user):
  A. analyze.report returns the expected section set, each carrying a valid evidence_envelope.
  B. Honest degradation — every section's tier is consistent with its finding_state (a
     not_measured/not_observed section is 'neutral', never dressed up as a finding).
  C. analyze.export writes a SINGLE self-contained, OFFLINE report.html — inlined <style> +
     Chart.js + i18n catalog, ≥10 <section> blocks, and ZERO external http(s) src/href.

    PYTHONPATH=src python3 -m indaga.eval.analyze_eval --subject demo --user-dir /abs/users/demo
"""

from __future__ import annotations

import argparse
import re
import sys

from ..genome.expression import expression_db_path
from ..interfaces.mcp import build_context
from ..operations import call_operation
from ..reference import manager as refmgr


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def run(subject: str, user_dir: str) -> int:
    ctx = build_context(subject, user_dir)
    passed = total = 0

    # A. structured report — graded sections
    rep = call_operation("analyze.report", {}, ctx)
    secs = rep.get("sections") or []
    graded = [s for s in secs if (s.get("evidence_envelope") or {}).get("finding_state")]
    print("A. analyze.report — structured, graded sections")
    total += 1; passed += _check("report returns sections, each with an evidence_envelope",
                                 len(secs) >= 10 and len(graded) == len(secs),
                                 f"{len(secs)} sections, {len(graded)} graded")
    keys = {s["key"] for s in secs}
    total += 1; passed += _check("core sections present (overview/pgs/pharma/ancestry/labs)",
                                 {"overview", "pgs", "pharma", "ancestry", "labs"} <= keys,
                                 f"{sorted(keys)[:6]}…")

    # B. tier ↔ finding_state honesty
    bad = [s for s in secs if (s["evidence_envelope"] or {}).get("finding_state") in
           ("not_measured", "not_observed_in_consulted_scope", "not_assessed") and s["tier"] != "neutral"]
    print("B. honest degradation")
    total += 1; passed += _check("not_measured/not_observed sections are tier 'neutral' (not dressed up)",
                                 not bad, f"{[s['key'] for s in bad]}" if bad else "clean")

    # C. self-contained offline HTML
    print("C. analyze.export — self-contained offline HTML")
    ex = call_operation("analyze.export", {}, ctx)
    path = ex.get("report_path")
    html = ""
    try:
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
    except OSError:
        pass
    n_sections = html.count("<section id=")
    external = len(re.findall(r'(?:src|href)="https?://', html))
    self_contained = (html.startswith("<!DOCTYPE html>") and "<style>" in html
                      and "__I18N__" in html and external == 0 and n_sections >= 10)
    total += 1; passed += _check("report.html is single, offline, self-contained",
                                 self_contained, f"{len(html)} bytes, {n_sections} sections, {external} external URLs")

    # D. analytical grounding wired into genomic findings (read-only; conditional on installed refs)
    print("D. analytical grounding (local Reactome/HPA) on genomic findings")
    by_key = {s["key"]: s for s in secs}
    gwas = (by_key.get("gwas", {}).get("findings", {}) or {}).get("associations", []) or []
    cancer = (by_key.get("cancer", {}).get("findings", {}) or {}).get("variants", []) or []
    grounded = [f for f in (gwas + cancer) if isinstance(f, dict) and f.get("grounding")]
    refs_installed = (refmgr.reactome_gmt_path().exists() or refmgr.hpa_tissue_tsv_path().exists()
                      or expression_db_path().exists())
    if refs_installed:
        ok = bool(grounded) and all(g["grounding"].get("pathways") or g["grounding"].get("tissues")
                                    for g in grounded)
        total += 1; passed += _check("grounded findings carry Reactome pathways / HPA tissues",
                                     ok, f"{len(grounded)}/{len(gwas) + len(cancer)} findings grounded")
    else:
        total += 1; passed += _check("grounding refs absent → report builds with no grounding (graceful)",
                                     not grounded, "skipped: install reactome-pathways / hpa-tissue-rna to exercise")

    print(f"\n{passed}/{total} analyze checks passed.")
    return 0 if passed == total else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="analyze_eval")
    p.add_argument("--subject", required=True)
    p.add_argument("--user-dir", required=True)
    args = p.parse_args(argv)
    return run(args.subject, args.user_dir)


if __name__ == "__main__":
    sys.exit(main())
