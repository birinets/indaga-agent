"""
HTML component helpers — the reusable building blocks every report section is
assembled from. Each function returns an HTML string. Chrome text is emitted
with ``data-i18n`` keys (see ``i18n.py``); data-derived text is emitted as-is
(English, per the v1 i18n scope).
"""
from __future__ import annotations

from . import i18n
from .i18n import COOPER_BAND_KEY
from .references import esc

# Band-gauge colour ramp (low → high fitness), works on dark + light.
GAUGE_RAMP = ["#e74c3c", "#e67e22", "#f1c40f", "#38d9a9", "#27ae60", "#3498db"]


def tx(key: str, tag: str = "span", cls: str | None = None, extra: str = "") -> str:
    """A chrome element carrying its i18n key + English fallback text."""
    c = f' class="{cls}"' if cls else ""
    return f'<{tag} data-i18n="{key}"{c}{extra}>{esc(i18n.t("en", key))}</{tag}>'


def section(sec_id: str, title_key: str, num: int, body_html: str,
            lede_key: str | None = None) -> str:
    lede = f'<p class="lede">{tx(lede_key)}</p>' if lede_key else ""
    return (
        f'<section id="{sec_id}">\n'
        f'  <h2 class="sec-title"><span class="num">{num:02d}</span>{tx(title_key)}</h2>\n'
        f'  {lede}{body_html}\n'
        f'</section>'
    )


def sub_title(key: str) -> str:
    return tx(key, tag="h3", cls="sub-title")


def kpi(label_key: str, value: object, unit: str | None = None,
        status: str = "neutral", sub: str | None = None) -> str:
    u = f' <span class="k-unit">{esc(unit)}</span>' if unit else ""
    s = f'<div class="k-sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="kpi {status}">'
        f'{tx(label_key, cls="k-label")}'
        f'<div class="k-value">{esc(value)}{u}</div>{s}</div>'
    )


def badge_text(text: str, kind: str = "neutral", i18n_key: str | None = None) -> str:
    if i18n_key:
        return tx(i18n_key, cls=f"badge {kind}")
    return f'<span class="badge {kind}">{esc(text)}</span>'


def callout(kind: str, head_key: str | None, body_html: str) -> str:
    head = f'<div class="c-head">{tx(head_key)}</div>' if head_key else ""
    return f'<div class="callout {kind}">{head}{body_html}</div>'


def grid(cards_html: list[str], cols: int = 4) -> str:
    return f'<div class="grid cols-{cols}">\n' + "\n".join(cards_html) + "\n</div>"


def table(header_keys: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th>{tx(k)}</th>" for k in header_keys)
    trs = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl-wrap"><table><thead><tr>{ths}</tr></thead><tbody>\n{trs}\n</tbody></table></div>'


def action_list(items: list[str]) -> str:
    lis = "\n".join(
        f'<li><span class="n">{i+1}</span><span>{esc(it)}</span></li>'
        for i, it in enumerate(items)
    )
    return f'<ul class="action-list">\n{lis}\n</ul>'


def bullet_list(items: list[str]) -> str:
    lis = "\n".join(f"<li>{esc(it)}</li>" for it in items)
    return f'<ul class="clean">\n{lis}\n</ul>'


def band_gauge(value: float, bands: list[dict], vmin: float, vmax: float,
               value_label: str) -> str:
    """Segmented band gauge with a marker at ``value`` (e.g. Cooper VO₂ norms)."""
    span = (vmax - vmin) or 1.0
    segs = []
    for i, b in enumerate(bands):
        lo = max(float(b["lo"]), vmin)
        hi = min(float(b["hi"]), vmax)
        if hi <= lo:
            continue
        w = (hi - lo) / span * 100
        color = b.get("color") or GAUGE_RAMP[i % len(GAUGE_RAMP)]
        key = b.get("key") or COOPER_BAND_KEY.get(b["label"])
        lab = tx(key) if key else esc(b["label"])
        segs.append(f'<div class="seg" style="width:{w:.2f}%;background:{color}">{lab}</div>')
    mark_pct = max(0.0, min(100.0, (float(value) - vmin) / span * 100))
    return (
        '<div class="gauge">'
        f'<div class="track">{"".join(segs)}</div>'
        f'<div class="scale"><div class="marker" style="left:{mark_pct:.2f}%">'
        f'<div class="pin"></div><div class="lab">{esc(value_label)}</div></div></div>'
        '</div>'
    )


def gene_table(genes: list[dict]) -> str:
    """Render an endurance/trait gene panel. Items: gene,label,genotype,plain,reading,tier."""
    rows = []
    for g in genes:
        kind, label_key = i18n.TIER_BADGE.get(g.get("tier", "neutral"),
                                              ("neutral", "lbl_neutral"))
        tier_badge = tx(label_key, cls=f"badge {kind}")
        gname = f'<strong>{esc(g.get("gene",""))}</strong>'
        variant = esc(g.get("label", ""))
        geno = f'<span class="mono">{esc(g.get("genotype",""))}</span>'
        if g.get("plain"):
            geno += f'<br><span style="color:var(--muted);font-size:.78rem">{esc(g["plain"])}</span>'
        interp = f'{tier_badge} {esc(g.get("reading",""))}'
        rows.append([gname, variant, geno, interp])
    return table(["gene", "variant", "genotype", "interpretation"], rows)


def blood_list_table(values: list[dict]) -> str:
    """Render a list of blood values [{name,value,unit,ref_range,flag}] (bundle list form)."""
    rows = []
    for b in values:
        flag = (b.get("flag") or "").upper()
        if flag == "HIGH":
            status = badge_text("", "alert", i18n_key="high_status")
        elif flag in ("WATCH", "LOW"):
            status = badge_text("", "watch", i18n_key="watch_status")
        else:  # GOOD, None
            status = badge_text("", "ok", i18n_key="normal")
        val = f'{esc(b.get("value"))} {esc(b.get("unit",""))}'.strip()
        rows.append([esc(b.get("name", "")), val, esc(b.get("ref_range", "—")), status])
    return table(["marker", "value", "reference_range", "status"], rows)


def blood_table(bloods: dict, markers: list[tuple[str, str]]) -> str:
    """Render selected blood markers. ``markers`` = [(key_in_bloods, display_name)]."""
    rows = []
    for key, name in markers:
        b = bloods.get(key)
        if b is None or not isinstance(b, dict) or b.get("value") is None:
            status = badge_text("", "neutral", i18n_key="missing_status")
            rows.append([esc(name), '<span style="color:var(--muted)">—</span>',
                         "—", status])
            continue
        val = f'{esc(b.get("value"))} {esc(b.get("unit",""))}'
        ref = esc(b.get("ref", "—"))
        flag = (b.get("flag") or "").upper()
        if flag in ("WATCH", "HIGH", "LOW", "H", "L"):
            status = badge_text("", "watch", i18n_key="watch_status")
        else:
            status = badge_text("", "ok", i18n_key="normal")
        rows.append([esc(name), val, ref, status])
    return table(["marker", "value", "reference_range", "status"], rows)
