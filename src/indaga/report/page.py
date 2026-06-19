"""
Assembles one fully self-contained HTML report.

Everything is inlined — the design-system CSS, the vendored Chart.js, the i18n
catalog, the data, and the charts — so the output is a single file the user can
double-click, read fully offline, and hand to a clinician. The page ships a tiny
vanilla-JS runtime for: dark/light theme toggle, EN/RU/NL chrome switching,
TOC scroll-spy, and a (stubbed) "ask your data" chat panel. Preferences persist
in localStorage.
"""
from __future__ import annotations

from pathlib import Path

from . import components, i18n
from .references import RefCollector, esc

_ASSETS = Path(__file__).resolve().parent / "assets"


def _chartjs() -> str:
    f = _ASSETS / "chart.umd.min.js"
    return f.read_text(encoding="utf-8") if f.exists() else "/* chart.js missing */"


def _meta_pills(meta: list[tuple[str, str]]) -> str:
    out = []
    for label_key, value in meta:
        out.append(f'<span class="meta-pill">{components.tx(label_key)}: '
                   f'<strong>{esc(value)}</strong></span>')
    return '<div class="meta-bar">' + "".join(out) + "</div>"


def _toc(entries: list[tuple[str, str]]) -> str:
    links = "\n".join(
        f'    <a href="#{sid}" data-toc="{sid}" data-i18n="{tkey}">{esc(i18n.t("en", tkey))}</a>'
        for sid, tkey in entries
    )
    return (f'<aside class="toc"><div class="toc-title" data-i18n="toc">'
            f'{esc(i18n.t("en","toc"))}</div>\n{links}\n</aside>')


def _controls() -> str:
    langs = "".join(
        f'<button data-lang="{code}">{i18n.LANG_NAMES[code]}</button>'
        for code in i18n.LANGS
    )
    return (
        '<div class="controls">'
        '<button id="themeBtn" title="Theme">◐ <span data-i18n="toggle_theme">Theme</span></button>'
        f'<div class="seg" role="group" aria-label="language">{langs}</div>'
        '</div>'
    )


def _chat() -> str:
    return (
        '<button class="chat-fab" id="chatFab"><span data-i18n="ask_data">Ask about your data</span></button>'
        '<div class="chat-panel" id="chatPanel">'
        '<div class="c-hd"><span data-i18n="chat_title">Ask your data</span>'
        '<button id="chatClose" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:1.1rem">×</button></div>'
        '<div class="c-body"><span class="c-soon" data-i18n="coming_soon">Coming soon</span>'
        '<div data-i18n="chat_desc">' + esc(i18n.t("en", "chat_desc")) + '</div></div>'
        '</div>'
    )


def _runtime_js(default_lang: str, chart_init: list[str]) -> str:
    charts = "\n".join(chart_init)
    return f"""
const I18N = window.__I18N__;
function applyLang(lang){{
  if(!I18N[lang]) lang = 'en';
  document.documentElement.lang = lang;
  const dict = I18N[lang];
  document.querySelectorAll('[data-i18n]').forEach(function(el){{
    const k = el.getAttribute('data-i18n');
    if(dict[k] != null) el.textContent = dict[k];
  }});
  document.querySelectorAll('[data-lang]').forEach(function(b){{
    b.classList.toggle('active', b.getAttribute('data-lang') === lang);
  }});
  const name = document.body.getAttribute('data-name') || '';
  document.title = name ? (name + ' — ' + dict['health_report']) : dict['health_report'];
  localStorage.setItem('heath_lang', lang);
}}
function applyTheme(t){{
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('heath_theme', t);
}}
applyTheme(localStorage.getItem('heath_theme') || 'dark');
document.getElementById('themeBtn').addEventListener('click', function(){{
  applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
}});
document.querySelectorAll('[data-lang]').forEach(function(b){{
  b.addEventListener('click', function(){{ applyLang(b.getAttribute('data-lang')); }});
}});
const fab = document.getElementById('chatFab'), panel = document.getElementById('chatPanel');
fab.addEventListener('click', function(){{ panel.classList.toggle('open'); }});
document.getElementById('chatClose').addEventListener('click', function(){{ panel.classList.remove('open'); }});
// TOC scroll-spy
const spy = new IntersectionObserver(function(entries){{
  entries.forEach(function(e){{
    if(e.isIntersecting){{
      document.querySelectorAll('.toc a').forEach(function(a){{
        a.classList.toggle('active', a.getAttribute('data-toc') === e.target.id);
      }});
    }}
  }});
}}, {{rootMargin: '-120px 0px -70% 0px'}});
document.querySelectorAll('main section').forEach(function(s){{ spy.observe(s); }});
// charts
try {{
{charts}
}} catch(err) {{ console.error('chart init failed', err); }}
// initial language (chrome only; data prose stays English)
applyLang(localStorage.getItem('heath_lang') || '{default_lang}');
"""


def build_report(*, name: str, subtitle: str, meta: list[tuple[str, str]],
                 toc: list[tuple[str, str]], body_sections: str,
                 chart_init: list[str], refs: RefCollector,
                 default_lang: str = "en") -> str:
    """Return the complete self-contained HTML document as a string."""
    from . import theme as theme_mod

    toc_entries = list(toc)
    bib = refs.bibliography_html()
    refs_section = ""
    if bib:
        toc_entries.append(("references", "references"))
        refs_section = components.section(
            "references", "references", len(toc) + 1, bib
        )

    head = f"""<!DOCTYPE html>
<html lang="{default_lang}" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(name)} — {esc(i18n.t(default_lang, "health_report"))}</title>
<style>{theme_mod.BASE_CSS}</style>
</head>"""

    body = f"""
<body data-name="{esc(name)}">
<header class="app-header">
  <div class="h-top">
    <div>
      <h1>{esc(name)} — {components.tx("health_report")}</h1>
      <div class="subtitle">{esc(subtitle)}</div>
    </div>
    {_controls()}
  </div>
  {_meta_pills(meta)}
</header>

<div class="layout">
  {_toc(toc_entries)}
  <main>
    {body_sections}
    {refs_section}
  </main>
</div>

<div class="disclaimer" data-i18n="disclaimer">{esc(i18n.t(default_lang, "disclaimer"))}</div>

{_chat()}

<script>{_chartjs()}</script>
<script>window.__I18N__ = {i18n.js_catalog()};</script>
<script>{_runtime_js(default_lang, chart_init)}</script>
</body>
</html>"""
    return head + body
