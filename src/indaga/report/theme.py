"""
Shared visual design system for HeathProject HTML reports.

One source of truth for the look of every report. The CSS uses CSS custom
properties (variables) so the same component classes render in dark or light
mode by flipping the ``data-theme`` attribute on <html>. No build step, no
external stylesheet — ``BASE_CSS`` is inlined into each self-contained report
by ``page.py``.

Palette is descended from the project's existing dark dashboards (see the
eosinophilia / blood dashboards) and extended with a matching light theme.
"""
from __future__ import annotations

# Tier accent colours, reused by Python helpers (components.py) so the
# semantic colour of a finding is decided in exactly one place.
TIER_COLORS = {
    "alert": "var(--red)",     # tier-a / act now
    "watch": "var(--orange)",  # tier-b / monitor
    "ok": "var(--green)",      # reassuring
    "info": "var(--blue)",     # neutral / informational
    "neutral": "var(--muted)",
}

BASE_CSS = """
/* ============================================================= *
 *  HeathProject report design system — dark (default) + light   *
 * ============================================================= */
:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --surface2: #222636;
  --border: #2e3347;
  --text: #e8eaf0;
  --muted: #8a90a6;
  --accent: #4dabf7;

  --red: #e74c3c;       --red-dim: rgba(231,76,60,0.13);    --red-border: rgba(231,76,60,0.38);
  --orange: #e67e22;    --orange-dim: rgba(230,126,34,0.13);--orange-border: rgba(230,126,34,0.38);
  --green: #27ae60;     --green-dim: rgba(39,174,96,0.13);  --green-border: rgba(39,174,96,0.38);
  --blue: #3498db;      --blue-dim: rgba(52,152,219,0.12);  --blue-border: rgba(52,152,219,0.34);
  --yellow: #f1c40f;    --yellow-dim: rgba(241,196,15,0.12);
  --purple: #b197fc;    --teal: #38d9a9;

  --shadow: 0 4px 24px rgba(0,0,0,0.40);
  --radius: 10px;
  --maxw: 1180px;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
}
html[data-theme="light"] {
  --bg: #f4f6fa;
  --surface: #ffffff;
  --surface2: #eef1f7;
  --border: #d8dde8;
  --text: #1c2230;
  --muted: #5e6781;
  --red: #d63b2c;       --red-dim: rgba(214,59,44,0.10);    --red-border: rgba(214,59,44,0.30);
  --orange: #c8741a;    --orange-dim: rgba(200,116,26,0.10);--orange-border: rgba(200,116,26,0.30);
  --green: #1e8e54;     --green-dim: rgba(30,142,84,0.10);  --green-border: rgba(30,142,84,0.30);
  --blue: #2b7bbf;      --blue-dim: rgba(43,123,191,0.09);  --blue-border: rgba(43,123,191,0.28);
  --yellow: #b8930a;    --yellow-dim: rgba(184,147,10,0.12);
  --shadow: 0 2px 10px rgba(16,24,40,0.10);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  font-size: 14.5px;
  line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── HEADER ── */
.app-header {
  background: linear-gradient(135deg, var(--surface) 0%, var(--bg) 100%);
  border-bottom: 2px solid var(--blue);
  padding: 26px 40px 22px;
  position: sticky; top: 0; z-index: 50;
}
.app-header .h-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
.app-header h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.3px; }
.app-header .subtitle { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }
.meta-bar { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.meta-pill {
  background: var(--surface2); border: 1px solid var(--border); border-radius: 20px;
  padding: 4px 13px; font-size: 0.75rem; color: var(--muted);
}
.meta-pill strong { color: var(--text); font-weight: 600; }

/* ── CONTROLS (theme + language) ── */
.controls { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.controls button, .controls select {
  background: var(--surface2); color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; padding: 7px 12px; font-size: 0.8rem; cursor: pointer;
  font-family: inherit; transition: border-color .15s, background .15s;
}
.controls button:hover, .controls select:hover { border-color: var(--accent); }
.controls .seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.controls .seg button { border: none; border-radius: 0; padding: 7px 11px; background: var(--surface2); }
.controls .seg button.active { background: var(--blue); color: #fff; }

/* ── LAYOUT ── */
.layout { max-width: var(--maxw); margin: 0 auto; display: grid; grid-template-columns: 220px 1fr; gap: 32px; padding: 28px 40px 90px; }
@media (max-width: 880px) { .layout { grid-template-columns: 1fr; } .toc { display: none; } }

/* ── TOC SIDEBAR ── */
.toc { position: sticky; top: 120px; align-self: start; max-height: calc(100vh - 140px); overflow-y: auto; }
.toc-title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.8px; color: var(--muted); margin-bottom: 10px; }
.toc a {
  display: block; color: var(--muted); padding: 6px 10px; border-radius: 6px;
  font-size: 0.83rem; border-left: 2px solid transparent; margin-bottom: 1px;
}
.toc a:hover { color: var(--text); background: var(--surface); text-decoration: none; }
.toc a.active { color: var(--accent); border-left-color: var(--accent); background: var(--surface); }

/* ── SECTIONS ── */
main { min-width: 0; }
section { margin-bottom: 44px; scroll-margin-top: 130px; }
.sec-title {
  font-size: 1.32rem; font-weight: 700; display: flex; align-items: center; gap: 11px;
  border-bottom: 2px solid var(--border); padding-bottom: 11px; margin-bottom: 20px;
}
.sec-title .num { background: var(--blue); color: #fff; border-radius: 6px; padding: 2px 9px; font-size: 0.8rem; font-weight: 700; }
.sub-title { font-size: 1.02rem; font-weight: 700; color: var(--accent); margin: 26px 0 12px; }
.lede { color: var(--muted); font-size: 0.92rem; margin-bottom: 18px; }
p { margin: 10px 0; }

/* ── CARDS ── */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow); }
.card + .card { margin-top: 16px; }
.grid { display: grid; gap: 14px; }
.grid.cols-2 { grid-template-columns: repeat(2, 1fr); }
.grid.cols-3 { grid-template-columns: repeat(3, 1fr); }
.grid.cols-4 { grid-template-columns: repeat(4, 1fr); }
@media (max-width: 720px) { .grid.cols-2, .grid.cols-3, .grid.cols-4 { grid-template-columns: 1fr 1fr; } }
@media (max-width: 460px) { .grid.cols-2, .grid.cols-3, .grid.cols-4 { grid-template-columns: 1fr; } }

/* ── KPI ── */
.kpi { background: var(--surface); border: 1px solid var(--border); border-top: 3px solid var(--muted); border-radius: var(--radius); padding: 15px 16px; }
.kpi.ok { border-top-color: var(--green); }
.kpi.watch { border-top-color: var(--orange); }
.kpi.alert { border-top-color: var(--red); }
.kpi.info { border-top-color: var(--blue); }
.kpi .k-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); }
.kpi .k-value { font-size: 1.7rem; font-weight: 700; line-height: 1.15; margin: 4px 0 2px; }
.kpi .k-unit { font-size: 0.82rem; color: var(--muted); font-weight: 500; }
.kpi .k-sub { font-size: 0.78rem; color: var(--muted); margin-top: 3px; }

/* ── BADGES ── */
.badge { display: inline-block; font-size: 0.7rem; font-weight: 700; padding: 2px 9px; border-radius: 20px; letter-spacing: 0.3px; }
.badge.alert { background: var(--red-dim); color: var(--red); border: 1px solid var(--red-border); }
.badge.watch { background: var(--orange-dim); color: var(--orange); border: 1px solid var(--orange-border); }
.badge.ok { background: var(--green-dim); color: var(--green); border: 1px solid var(--green-border); }
.badge.info { background: var(--blue-dim); color: var(--blue); border: 1px solid var(--blue-border); }
.badge.neutral { background: var(--surface2); color: var(--muted); border: 1px solid var(--border); }

/* ── CALLOUTS ── */
.callout { border-radius: 8px; padding: 14px 18px; margin: 14px 0; font-size: 0.88rem; }
.callout.alert { background: var(--red-dim); border-left: 3px solid var(--red); }
.callout.watch { background: var(--orange-dim); border-left: 3px solid var(--orange); }
.callout.ok { background: var(--green-dim); border-left: 3px solid var(--green); }
.callout.info { background: var(--blue-dim); border-left: 3px solid var(--blue); }
.callout .c-head { font-weight: 700; margin-bottom: 4px; }
.callout.alert .c-head { color: var(--red); }
.callout.watch .c-head { color: var(--orange); }
.callout.ok .c-head { color: var(--green); }
.callout.info .c-head { color: var(--blue); }

/* ── TABLES ── */
.tbl-wrap { overflow-x: auto; margin: 14px 0; border: 1px solid var(--border); border-radius: var(--radius); }
table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
th { background: var(--surface2); color: var(--muted); padding: 9px 13px; text-align: left; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.4px; }
td { padding: 9px 13px; border-top: 1px solid var(--border); }
tbody tr:hover { background: var(--surface2); }
td.mono, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }

/* ── BAND GAUGE (e.g. Cooper VO2 norms) ── */
.gauge { margin: 14px 0 8px; }
.gauge .track { display: flex; height: 26px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
.gauge .seg { display: flex; align-items: center; justify-content: center; font-size: 0.66rem; color: #fff; font-weight: 600; opacity: 0.88; white-space: nowrap; }
.gauge .scale { position: relative; height: 20px; margin-top: 2px; }
.gauge .marker { position: absolute; transform: translateX(-50%); top: 0; }
.gauge .marker .pin { width: 2px; height: 9px; background: var(--text); margin: 0 auto; }
.gauge .marker .lab { font-size: 0.72rem; font-weight: 700; white-space: nowrap; }
.gauge-legend { font-size: 0.76rem; color: var(--muted); margin-top: 6px; }

/* ── CHARTS ── */
.chart-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; margin: 14px 0; }
.chart-wrap canvas { max-height: 320px; }
.chart-title { font-size: 0.9rem; font-weight: 700; margin-bottom: 10px; }

/* ── LISTS ── */
ul.clean, ol.clean { margin: 10px 0 10px 4px; padding-left: 20px; }
ul.clean li, ol.clean li { margin: 6px 0; }
.action-list { list-style: none; padding: 0; }
.action-list li { display: flex; gap: 10px; padding: 10px 0; border-top: 1px solid var(--border); }
.action-list li:first-child { border-top: none; }
.action-list .n { flex-shrink: 0; width: 22px; height: 22px; border-radius: 50%; background: var(--red); color: #fff; font-size: 0.74rem; font-weight: 700; display: flex; align-items: center; justify-content: center; }

/* ── REFERENCES / CITATIONS ── */
.cite { font-size: 0.7em; vertical-align: super; line-height: 0; }
.cite a { color: var(--accent); font-weight: 700; padding: 0 1px; }
.refs-list { list-style: none; counter-reset: ref; padding: 0; font-size: 0.83rem; }
.refs-list li { counter-increment: ref; padding: 9px 0 9px 34px; position: relative; border-top: 1px solid var(--border); color: var(--muted); }
.refs-list li:first-child { border-top: none; }
.refs-list li::before { content: "[" counter(ref) "]"; position: absolute; left: 0; color: var(--accent); font-weight: 700; }
.refs-list li .r-title { color: var(--text); }
.refs-list li:target { background: var(--blue-dim); border-radius: 6px; }

/* ── CHAT STUB ── */
.chat-fab { position: fixed; right: 22px; bottom: 22px; z-index: 60; background: var(--blue); color: #fff; border: none; border-radius: 26px; padding: 12px 18px; font-size: 0.85rem; font-weight: 600; cursor: pointer; box-shadow: var(--shadow); font-family: inherit; }
.chat-panel { position: fixed; right: 22px; bottom: 76px; z-index: 60; width: 340px; max-width: calc(100vw - 44px); background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow); display: none; }
.chat-panel.open { display: block; }
.chat-panel .c-hd { padding: 13px 16px; border-bottom: 1px solid var(--border); font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
.chat-panel .c-body { padding: 16px; font-size: 0.85rem; color: var(--muted); }
.chat-panel .c-soon { display: inline-block; background: var(--surface2); border: 1px solid var(--border); border-radius: 20px; padding: 2px 10px; font-size: 0.7rem; color: var(--muted); margin-bottom: 10px; }

/* ── FOOTER / DISCLAIMER ── */
.disclaimer { max-width: var(--maxw); margin: 0 auto; padding: 22px 40px 60px; color: var(--muted); font-size: 0.78rem; border-top: 1px solid var(--border); }

/* ── PRINT (so a report still PDFs cleanly) ── */
@media print {
  .controls, .toc, .chat-fab, .chat-panel { display: none !important; }
  .layout { grid-template-columns: 1fr; }
  body { background: #fff; color: #000; font-size: 11px; }
  .card, .kpi, .chart-wrap { box-shadow: none; break-inside: avoid; }
  section { break-inside: avoid; }
}
"""
