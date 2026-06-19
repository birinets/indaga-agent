"""Analyze — the user-facing multi-omic report (Indaga's synthesis surface).

Turns everything the engine computes into ONE honest, evidence-graded artifact. Two tools
over a shared gather+build core:
  • ``analyze.report``  — structured, evidence-graded sections (agent-native; the LLM narrates).
  • ``analyze.export``  — a self-contained, offline ``report.html`` (the deliberate file-writing
    exception; lands under ~/.indaga/<subject>/reports/ like a job artifact).

The data does NOT come mainly from the HealthlakeStore facts (genome-only subjects hold ~1 fact) —
it comes from CALLING the other capability handlers (genome + multi-omic) via ``call_operation`` with
the same Context, each returning a dict + an ``evidence_envelope``. Every section maps its envelope to
an honest tier, so a not-yet-computed source renders as "not computed / order this / calibrating",
never blank. The report is read-only: it never triggers imputation / annotation / PGx / ancestry
builds or the slow SpliceAI — it reports what's already computed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..evidence import envelope as E
from ..operations.model import Context, Operation
from ..operations.registry import call_operation, register
from ..report import charts, i18n, page
from ..report import components as C
from ..report.references import RefCollector, esc
from ..runtime import paths
from ..store import Scope, Surface
from .grounding import gene_context

_CAP = "analyze"
_SKILL = "skills/analyze/SKILL.md"
_GROUND_MAX = 12  # cap genes grounded per section (read-only; keeps the report fast)


def _scope(context: Context) -> Scope:
    return Scope(context.subject_id, surface=context.surface or Surface.APP)


def _subj(scope: Scope) -> dict:
    return {"subject_id": scope.subject_id, "uses_personal_data": True, "omic_scope": "multi"}


# -- envelope → report tier (the honesty bridge) ---------------------------- #

def _state(out: dict) -> str:
    return ((out or {}).get("evidence_envelope") or {}).get("finding_state") or ""


def _tier(out: dict, interpretation: str | None = None) -> str:
    """Map a section's evidence envelope (+ optional finding interpretation) to a visual tier."""
    fs = _state(out)
    if fs == E.EVIDENCE_PRESENT:
        low = (interpretation or "").lower()
        if any(k in low for k in ("alert", "high", "pathogenic", "at_risk", "at-risk")):
            return "alert"
        if any(k in low for k in ("watch", "intermediate", "low", "poor", "needs")):
            return "watch"
        if any(k in low for k in ("ok", "normal", "benign", "reassur")):
            return "ok"
        return "info"
    if fs == E.INDEX_INCOMPLETE:
        return "info"
    return "neutral"          # not_measured / not_assessed / not_observed / blocked


def _degraded(out: dict, what: str, next_action: str | None = None) -> str:
    """A non-blank block for a section whose source isn't computed/measured yet."""
    fs = _state(out)
    if fs == E.NOT_MEASURED:
        msg = f"{what} is not in this genome / not measured — unknown, not a negative."
    elif fs == E.INDEX_INCOMPLETE:
        msg = f"{what} is still calibrating — not enough data yet."
    elif fs == E.NOT_OBSERVED_IN_CONSULTED_SCOPE:
        msg = f"Nothing matched for {what} in the consulted scope — not a clean negative."
    else:
        msg = f"{what} has not been computed yet."
    if next_action:
        msg += f" Next: {next_action}."
    return C.callout("neutral", None, f"<p>{esc(msg)}</p>")


# -- ClinVar / variant helpers ---------------------------------------------- #

def _sig_tier(sig: str | None, am_class: str | None = None, classification: str | None = None) -> str:
    s = (sig or "").lower()
    cl = (classification or "").lower()
    if "common_likely_false_alarm" in cl:
        return "ok"
    if "pathogenic" in s and "conflicting" not in s and "non-pathogenic" not in s:
        return "alert" if "likely" not in s else "watch"
    if am_class == "likely_pathogenic":
        return "watch"
    if "benign" in s:
        return "ok"
    return "neutral"


def _variant_rows(variants: list[dict]) -> list[dict]:
    rows = []
    for v in variants:
        reading = v.get("clinvar_sig") or (v.get("am_class") or "").replace("_", " ") or "—"
        rows.append({"gene": v.get("gene") or "—", "label": v.get("rsid") or "",
                     "genotype": v.get("genotype") or "—", "reading": reading,
                     "tier": _sig_tier(v.get("clinvar_sig"), v.get("am_class"))})
    return rows


# =========================== gather ======================================= #

# domain-lens stem → section i18n key, in display order (generic builder renders all)
_DOMAIN_ORDER = [
    ("cardiovascular", "sec_cardio"), ("methylation", "sec_methylation"),
    ("metabolic", "sec_metabolic"), ("athletic", "sec_athletic"), ("gut", "sec_gut"),
    ("immunity", "sec_immunity"), ("hormones", "sec_hormones"), ("skin", "sec_skin"),
    ("senses", "sec_senses"), ("mood_focus", "sec_mood"), ("longevity", "sec_longevity"),
    ("sleep", "sec_sleep"), ("dirty_genes", "sec_dirty"),
]


def _gather(context: Context) -> dict:
    """Call the other capabilities' handlers (read-only) and collect their outputs."""
    def call(name, params=None):
        try:
            return call_operation(name, params or {}, context)
        except Exception as exc:  # noqa: BLE001 — a missing source must not break the report
            return {"evidence_envelope": E.not_assessed(
                operation=name, reason=f"{type(exc).__name__}: {exc}",
                subject_context={"subject_id": context.subject_id})}

    g = {
        "summary": call("genome.summary"),
        "clinvar": call("clinvar.findings"),
        "pgs": call("pgs.score"),
        "pgx": call("pgx.summary"),
        "gwas": call("gwas.associations", {"limit": 12}),
        "ancestry": call("ancestry.estimate"),
        "nutri": call("nutrigenomics.markers"),
        "labs": call("labs.query"),
        "clock": call("clock.state"),
        "cgm": call("cgm.glycemic_summary"),
        "domains": {},
    }
    avail = {d["domain"] for d in (call("domains.list").get("domains") or [])}
    for dom, _key in _DOMAIN_ORDER:
        if dom in avail:
            g["domains"][dom] = call("domains.get", {"domain": dom})

    # Enrich headline genomic findings with local grounding context (read-only, download-free;
    # silently omitted if the grounding libraries aren't installed). Prioritise confirmed-rare and
    # hereditary-cancer ClinVar findings; GWAS associations are already rank-ordered.
    def _cv_prio(f):
        panel = (f.get("panel") or "").lower()
        return (f.get("classification") != "confirmed_rare",
                not (panel.startswith("hered") or "cancer" in panel))
    _ground_findings(context, g["clinvar"].get("findings"), prioritize=_cv_prio)
    _ground_findings(context, g["gwas"].get("associations"))
    return g


def _ground_findings(context: Context, findings, *, key: str = "gene", prioritize=None) -> None:
    """Attach a compact `grounding` dict in-place to up to _GROUND_MAX findings (additive; agent-native).
    Order by ``prioritize`` first so the most clinically salient genes get grounded under the cap."""
    items = list(findings or [])
    if prioritize is not None:
        items = sorted(items, key=prioritize)
    for f in items[:_GROUND_MAX]:
        gc = gene_context(context, f.get(key))
        if gc:
            f["grounding"] = gc


def _grounding_note(items, *, key: str = "gene") -> str:
    """A compact English 'biological context' callout for findings that carry grounding (else '').
    De-duplicated by gene. Section-body prose is English by design (only UI chrome is i18n'd)."""
    lines, seen = [], set()
    for f in items or []:
        gc, gene = f.get("grounding"), (f.get(key) or "")
        if not gc or not gene or gene in seen:
            continue
        seen.add(gene)
        bits = []
        if gc.get("disease"):
            d = gc["disease"]
            bits.append(f"gene-disease: <strong>{esc(d['classification'])}</strong> — {esc(d['name'])}")
        if gc.get("panels"):
            bits.append("diagnostic panel: " + ", ".join(esc(p) for p in gc["panels"]))
        if gc.get("pathways"):
            bits.append("pathways: " + ", ".join(esc(p) for p in gc["pathways"]))
        if gc.get("tissues"):
            bits.append("highest expression: " + ", ".join(esc(t) for t in gc["tissues"]))
        if bits:
            lines.append(f"<li><strong>{esc(gene)}</strong> — " + "; ".join(bits) + "</li>")
    if not lines:
        return ""
    return C.callout("info", None,
        "<p><strong>Clinical & biological context</strong> (local GenCC/ClinGen validity + PanelApp + "
        "Reactome + HPA — context, not a verdict):</p><ul>" + "".join(lines) + "</ul>")


# =========================== section builders ============================== #
# Each returns (section_dict, html, chart_init_list). section_dict is the structured payload.

def _wrap(key, title_key, num, tier, body, findings, env, summary=None):
    sec = {"key": key, "title": i18n.t("en", title_key), "tier": tier,
           "summary": summary, "findings": findings, "evidence_envelope": env}
    return sec, C.section(key, title_key, num, body), []


def _b_overview(g, num, refs):
    cv, pgs, pgx, anc = g["clinvar"], g["pgs"], g["pgx"], g["ancestry"]
    finds = cv.get("findings") or []
    at_risk = [f for f in finds if f.get("classification") == "confirmed_rare"]
    # ACMG SF v3.3 medically-actionable secondary findings (real, not common false alarms) lead the report;
    # ACMG-2021 carrier-screening genes are surfaced separately (reproductive, usually unaffected).
    sf_actionable = [f for f in at_risk if f.get("acmg_sf")]
    carriers = [f for f in finds if f.get("acmg_carrier")
                and f.get("classification") in ("confirmed_rare", "not_in_gnomad")]
    diplos = pgx.get("diplotypes") or []
    alerts = [d for d in diplos if "uncertain" in (str(d.get("phenotype")) or "").lower()
              or "poor" in (str(d.get("phenotype")) or "").lower()]
    kpis = [
        C.kpi("headline_findings", cv.get("confident_at_risk", 0), status="info"),
        C.kpi("sec_pgs", pgs.get("n_total", 0), status="neutral"),
        C.kpi("sec_pharma", f"{len([d for d in diplos if d.get('diplotype')])}", status="neutral"),
        C.kpi("sec_ancestry", anc.get("assigned_superpopulation") or "—", status="neutral"),
    ]
    actions = []
    for f in sf_actionable[:5]:   # lead with the recognized return-of-results standard
        actions.append(f"ACMG SF (medically actionable): {f.get('gene')} {f.get('clinvar_sig')} — "
                       f"{f.get('acmg_sf_disorder') or 'actionable disorder'}. Discuss return-of-results "
                       "with a clinician.")
    for f in [x for x in at_risk if not x.get("acmg_sf")][:5]:
        actions.append(f"Review {f.get('gene')} {f.get('clinvar_sig')} ({f.get('interpretation') or 'finding'}) with a clinician.")
    for f in carriers[:4]:
        actions.append(f"Carrier (reproductive): {f.get('gene')} — {f.get('acmg_carrier_condition') or 'AR/XL condition'} "
                       "(carrier, usually unaffected; relevant for family planning).")
    for d in alerts[:4]:
        actions.append(f"PGx: {d.get('gene')} {d.get('diplotype')} → {d.get('phenotype')} — flag before prescribing.")
    body = C.grid(kpis, cols=4)
    if actions:
        body += C.sub_title("priority_actions") + C.action_list(actions)
    findings = {"confident_at_risk": cv.get("confident_at_risk", 0),
                "acmg_sf_actionable": len(sf_actionable), "acmg_carriers": len(carriers),
                "pgs_scores": pgs.get("n_total", 0),
                "pgx_called": len([d for d in diplos if d.get("diplotype")]),
                "ancestry": anc.get("assigned_superpopulation")}
    env = E.evidence_present(operation="analyze.overview", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             observations=findings)
    return _wrap("overview", "sec_overview", num, "info", body, findings, env)


def _b_cancer(g, num, refs):
    cv = g["clinvar"]
    finds = cv.get("findings") or []
    cancer = [f for f in finds if (f.get("panel") or "").lower().startswith("hered")
              or "cancer" in (f.get("panel") or "").lower()]
    rows = [{"gene": f.get("gene"), "label": f.get("rsid") or "", "genotype": f.get("zygosity") or "—",
             "reading": f"{f.get('clinvar_sig')} · {f.get('interpretation') or ''}"
                        + (f" · ⚑ ACMG SF: {f.get('acmg_sf_disorder')}" if f.get("acmg_sf") else ""),
             "tier": _sig_tier(f.get("clinvar_sig"), classification=f.get("classification"))} for f in cancer]
    body = C.gene_table(rows) if rows else _degraded(cv, "hereditary-cancer P/LP variants")
    body += C.callout("info", None, "<p>Most ClinVar 'pathogenic' calls on a dense panel are common "
                      "variants wrongly flagged — those are refuted here. Lead with confirmed, rare findings; "
                      "imputed findings want orthogonal (Sanger/clinical) confirmation.</p>")
    body += _grounding_note(cancer)
    tier = "alert" if any(r["tier"] == "alert" for r in rows) else _tier(cv)
    return _wrap("cancer", "sec_cancer", num, tier, body, {"variants": cancer}, cv["evidence_envelope"])


def _b_pgs(g, num, refs):
    pgs = g["pgs"]
    scores = pgs.get("scores") or []
    rows = []
    for s in scores[:30]:
        pct = s.get("percentile")
        rows.append([esc(s.get("trait_label") or s.get("pgs_id") or "—"),
                     f"{pct:.0f}th" if isinstance(pct, (int, float)) else "—",
                     esc(s.get("confidence") or "—"), esc(s.get("direction") or "")])
    body = (C.table(["trait", "percentile", "confidence", "interpretation"], rows) if rows
            else _degraded(pgs, "polygenic scores", "run genome.annotate"))
    body += C.callout("info", None, "<p>Percentiles are population-relative and directional, not a "
                      "diagnosis. A 'low' confidence reflects local-imputation coverage (regresses toward "
                      "the 50th — it UNDERSTATES, it isn't a true low score).</p>")
    return _wrap("pgs", "sec_pgs", num, _tier(pgs), body, {"scores": scores}, pgs["evidence_envelope"])


def _b_pgx(g, num, refs):
    pgx = g["pgx"]
    diplos = pgx.get("diplotypes") or []
    rows = []
    for d in diplos:
        ph = str(d.get("phenotype") or "")
        tier = "watch" if any(k in ph.lower() for k in ("poor", "uncertain", "intermediate")) else "ok"
        rows.append([f'<strong>{esc(d.get("gene"))}</strong>', f'<span class="mono">{esc(d.get("diplotype"))}</span>',
                     f'{C.badge_text(ph, tier)} {esc(ph)}', esc(d.get("function") or "")])
    body = (C.table(["gene", "diplotype", "phenotype", "interpretation"], rows) if rows
            else _degraded(pgx, "pharmacogenomic diplotypes", "run genome.pgx_run"))
    blind = pgx.get("blind_spots") or []
    if blind:
        body += C.callout("watch", None, f"<p><strong>Blind spots</strong> (array/imputation can't call): "
                          f"{esc(', '.join(blind))} — a clinical PGx panel is needed before prescribing drugs they govern.</p>")
    return _wrap("pharma", "sec_pharma", num, _tier(pgx), body, {"diplotypes": diplos, "blind_spots": blind},
                 pgx["evidence_envelope"])


def _b_gwas(g, num, refs):
    gw = g["gwas"]
    assoc = gw.get("associations") or []
    rows = [[esc(a.get("trait")), esc(a.get("rsid") or ""), esc(a.get("genotype") or "—"),
             (f"~1e-{a['neg_log10_p']:.0f}" if isinstance(a.get("neg_log10_p"), (int, float)) else "—"),
             esc(a.get("gene") or "")] for a in assoc[:12]]
    body = (C.table(["trait", "variant", "genotype", "value", "gene"], rows) if rows
            else _degraded(gw, "GWAS trait associations"))
    body += C.callout("info", None, "<p>Association is not causation; effect sizes are population-level "
                      "and small for common variants. Original-study ancestry affects transferability.</p>")
    body += _grounding_note(assoc[:12])
    return _wrap("gwas", "sec_gwas", num, _tier(gw), body, {"associations": assoc}, gw["evidence_envelope"])


def _b_ancestry(g, num, refs):
    anc = g["ancestry"]
    sim = anc.get("similarity") or {}
    chart_init = []
    body = ""
    if sim:
        body += C.grid([C.kpi("population", anc.get("assigned_superpopulation") or "—", status="info"),
                        C.kpi("confidence", f"{anc.get('confidence')}", status="neutral"),
                        C.kpi("sec_genome", anc.get("n_markers") or "—", sub="AIM markers", status="neutral")], cols=3)
        chtml, cjs = charts.bar_chart("ancSim", "similarity", list(sim.keys()),
                                      [{"label": "r", "data": [round(v, 3) for v in sim.values()], "color": "#4dabf7"}])
        body += chtml
        chart_init.append(cjs)
    else:
        body = _degraded(anc, "genetic ancestry")
    body += C.callout("info", None, "<p>Continental ASSIGNMENT by ancestry-informative-marker similarity, "
                      "not admixture deconvolution; 'similarity' is a relative ranking, not genome fractions.</p>")
    sec = {"key": "ancestry", "title": i18n.t("en", "sec_ancestry"), "tier": _tier(anc),
           "summary": anc.get("assigned_superpopulation"), "findings": anc, "evidence_envelope": anc["evidence_envelope"]}
    return sec, C.section("ancestry", "sec_ancestry", num, body), chart_init


def _b_nutri(g, num, refs):
    nu = g["nutri"]
    markers = nu.get("markers") or []
    rows = [{"gene": m.get("gene"), "label": m.get("trait") or m.get("rsid") or "",
             "genotype": m.get("genotype") or "—", "reading": m.get("interpretation") or "",
             "tier": "info"} for m in markers]
    body = C.gene_table(rows) if rows else _degraded(nu, "nutrigenomic markers")
    return _wrap("nutrigenomics", "sec_nutrigenomics", num, _tier(nu), body, {"markers": markers},
                 nu["evidence_envelope"])


def _b_labs(g, num, refs):
    lb = g["labs"]
    facts = lb.get("facts") or []
    vals = []
    for f in facts:
        interp = (f.get("interpretation") or "").lower()
        flag = "HIGH" if interp in ("high", "above") else ("WATCH" if interp in ("low", "below", "watch") else "GOOD")
        ref = "—"
        if f.get("reference_low") is not None or f.get("reference_high") is not None:
            ref = f"{f.get('reference_low','')}–{f.get('reference_high','')}"
        vals.append({"name": f.get("display") or f.get("name"),
                     "value": f.get("value_number") if f.get("value_number") is not None else f.get("value_text"),
                     "unit": f.get("unit") or "", "ref_range": ref, "flag": flag})
    body = (C.blood_list_table(vals) if vals
            else _degraded(lb, "blood labs", "upload lab results or order a panel"))
    tier = "info" if vals else _tier(lb)
    return _wrap("labs", "sec_labs", num, tier, body, {"analytes": len(vals)}, lb["evidence_envelope"])


def _b_circadian(g, num, refs):
    ck = g["clock"]
    body = ""
    mid = ck.get("biological_midnight")
    if _state(ck) == E.EVIDENCE_PRESENT and mid:
        body = C.grid([C.kpi("sec_circadian", mid, sub=f"{ck.get('valid_nights','?')} valid nights", status="ok")], cols=3)
    else:
        body = _degraded(ck, "Biological Midnight", "wear a tracker for 14 nights to calibrate")
    return _wrap("circadian", "sec_circadian", num, _tier(ck), body,
                 {"biological_midnight": mid, "state": ck.get("state")}, ck["evidence_envelope"])


def _b_cgm(g, num, refs):
    cm = g["cgm"]
    hs = cm.get("historical_summary")
    if _state(cm) == E.EVIDENCE_PRESENT and hs:
        body = C.callout("info", None, f"<p>{esc(hs.get('display') or hs.get('name') or 'CGM summary')}: "
                         f"<strong>{esc(hs.get('value_number') if hs.get('value_number') is not None else hs.get('value_text'))} "
                         f"{esc(hs.get('unit') or '')}</strong></p>")
    else:
        body = _degraded(cm, "continuous glucose (CGM)", "connect a Dexcom/Libre export")
    return _wrap("cgm", "sec_cgm", num, _tier(cm), body, {"summary": hs}, cm["evidence_envelope"])


def _b_domain(dom, title_key, out, num, refs):
    notable = out.get("notable_variants") or out.get("variants") or []
    rows = _variant_rows(notable[:15])
    body = C.gene_table(rows) if rows else _degraded(out, f"{dom} panel variants")
    miss = out.get("missing_tests_recommended") or []
    if miss:
        body += C.callout("info", None, f"<p><strong>Suggested tests:</strong> {esc(', '.join(map(str, miss)))}</p>")
    tier = "alert" if any(r["tier"] == "alert" for r in rows) else ("watch" if any(r["tier"] == "watch" for r in rows) else _tier(out))
    return _wrap(f"dom_{dom}", title_key, num, tier, body, {"notable_variants": notable[:15]},
                 out["evidence_envelope"])


# =========================== assembly ===================================== #

def _build_sections(context: Context) -> tuple[list, str, list, list, RefCollector]:
    g = _gather(context)
    refs = RefCollector()
    builders = [
        lambda n: _b_overview(g, n, refs),
        lambda n: _b_cancer(g, n, refs),
        lambda n: _b_pgs(g, n, refs),
        lambda n: _b_pgx(g, n, refs),
        lambda n: _b_gwas(g, n, refs),
        lambda n: _b_ancestry(g, n, refs),
        lambda n: _b_nutri(g, n, refs),
    ]
    for dom, key in _DOMAIN_ORDER:
        if dom in g["domains"]:
            builders.append(lambda n, d=dom, k=key: _b_domain(d, k, g["domains"][d], n, refs))
    builders += [
        lambda n: _b_labs(g, n, refs),
        lambda n: _b_circadian(g, n, refs),
        lambda n: _b_cgm(g, n, refs),
    ]
    sections, html_parts, toc, chart_init = [], [], [], []
    for i, build in enumerate(builders, start=1):
        sec, html, charts_js = build(i)
        sections.append(sec)
        html_parts.append(html)
        toc.append((sec["key"], _title_key_for(sec["key"])))
        chart_init += charts_js
    return sections, "\n".join(html_parts), toc, chart_init, refs


_KEY_TO_TITLE = {"overview": "sec_overview", "cancer": "sec_cancer", "pgs": "sec_pgs", "pharma": "sec_pharma",
                 "gwas": "sec_gwas", "ancestry": "sec_ancestry", "nutrigenomics": "sec_nutrigenomics",
                 "labs": "sec_labs", "circadian": "sec_circadian", "cgm": "sec_cgm"}


def _title_key_for(key: str) -> str:
    if key in _KEY_TO_TITLE:
        return _KEY_TO_TITLE[key]
    if key.startswith("dom_"):
        return dict(_DOMAIN_ORDER).get(key[4:], "sec_genome")
    return "sec_genome"


def _report_envelope(sections: list, scope: Scope) -> dict:
    present = sum(1 for s in sections if _state(s) == E.EVIDENCE_PRESENT)
    return E.evidence_present(
        operation="analyze.report", answer_readiness=E.SCOPED_ANSWER_ONLY, subject_context=_subj(scope),
        observations={"sections": len(sections), "evidence_present": present,
                      "not_measured": sum(1 for s in sections if _state(s) == E.NOT_MEASURED)})


# =========================== handlers ===================================== #

def _analyze_report(params: dict, context: Context) -> dict:
    """Structured, evidence-graded report sections (agent-native; the LLM narrates from these)."""
    scope = _scope(context)
    sections, _html, _toc, _ci, _refs = _build_sections(context)
    # strip the internal html from the structured payload (keep only data + envelope per section)
    clean = [{"key": s["key"], "title": s["title"], "tier": s["tier"],
              "summary": s.get("summary"), "findings": s.get("findings"),
              "evidence_envelope": s["evidence_envelope"]} for s in sections]
    return {"report_id": f"{scope.subject_id}-analyze", "subject": scope.subject_id,
            "sections": clean, "n_sections": len(clean),
            "note": "Each section carries its own evidence_envelope — read it before stating a finding. "
                    "A not_measured section is UNKNOWN, never 'normal'. Decision support, not diagnosis.",
            "evidence_envelope": _report_envelope(sections, scope)}


def _analyze_export(params: dict, context: Context) -> dict:
    """Write a self-contained, offline report.html (dark/light, EN/RU/NL, inlined Chart.js)."""
    scope = _scope(context)
    lang = (params.get("lang") or "en").lower()
    if lang not in i18n.LANGS:
        lang = "en"
    sections, body_html, toc, chart_init, refs = _build_sections(context)
    stamp = (context.now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    html = page.build_report(
        name=scope.subject_id.capitalize(), subtitle=f"Indaga · generated {stamp}",
        meta=[("subject", scope.subject_id)], toc=toc, body_sections=body_html,
        chart_init=chart_init, refs=refs, default_lang=lang)
    out_dir = paths.subject_dir(scope.subject_id) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.html"
    out_path.write_text(html, encoding="utf-8")
    env = E.evidence_present(operation="analyze.export", answer_readiness=E.SCOPED_ANSWER_ONLY,
                             subject_context=_subj(scope),
                             observations={"sections": len(sections), "bytes": len(html)})
    return {"report_path": str(out_path), "n_sections": len(sections), "bytes": len(html), "lang": lang,
            "note": "A single self-contained HTML file — open it in any browser, fully offline. "
                    "Each section preserves its evidence grade; not_measured ≠ normal.",
            "evidence_envelope": env}


register(Operation("analyze.report", _analyze_report, capability=_CAP, skill=_SKILL,
    description="The user's whole multi-omic picture as structured, evidence-graded sections — genome "
                "(ClinVar/ACMG/PGS/PGx/GWAS/ancestry/nutrigenomics + domain lenses) fused with labs, "
                "circadian + CGM. Each section carries its own evidence envelope; not-yet-computed "
                "sources degrade honestly. Read-only (never runs heavy jobs).",
    input_schema={"type": "object", "properties": {}},
    produces=("evidence_envelope",), omic_scope="multi", discovery_role="entry_tool"))

register(Operation("analyze.export", _analyze_export, capability=_CAP, skill=_SKILL,
    description="Write a self-contained, offline report.html (dark/light, EN/RU/NL, inlined charts) of "
                "the user's whole picture to ~/.indaga/<subject>/reports/. Returns the file path. "
                "'lang' selects the chrome language (en/ru/nl).",
    input_schema={"type": "object", "properties": {"lang": {"type": "string", "enum": ["en", "ru", "nl"]}}},
    produces=("evidence_envelope",), omic_scope="multi", discovery_role="focused_tool", mutating=True))
