"""
Interactive chart builders on top of the vendored Chart.js (assets/).

Each builder returns ``(html, init_js)``: the HTML drops a <canvas> into the
page, and the init JS (collected and run after Chart.js loads) instantiates the
chart. Axis/grid/legend colours use a theme-neutral grey that reads on both the
dark and light palette, so charts don't need to be re-rendered on theme switch.
"""
from __future__ import annotations

import json

from . import components

PALETTE = ["#4dabf7", "#e67e22", "#27ae60", "#b197fc", "#f1c40f", "#38d9a9"]

# Colours that read on both themes.
_AXIS = "#8a90a6"
_GRID = "rgba(120,128,150,0.18)"

_COMMON_OPTS = {
    "responsive": True,
    "maintainAspectRatio": False,
    "interaction": {"mode": "index", "intersect": False},
    "plugins": {"legend": {"labels": {"color": _AXIS, "boxWidth": 12, "usePointStyle": True}}},
    "scales": {
        "x": {"ticks": {"color": _AXIS}, "grid": {"color": _GRID}},
        "y": {"ticks": {"color": _AXIS}, "grid": {"color": _GRID}},
    },
}


def line_chart(canvas_id: str, title_key: str, labels: list,
               datasets: list[dict]) -> tuple[str, str]:
    """``datasets`` items: {label, data, color?}."""
    ds = []
    for i, d in enumerate(datasets):
        color = d.get("color") or PALETTE[i % len(PALETTE)]
        ds.append({
            "label": d["label"],
            "data": d["data"],
            "borderColor": color,
            "backgroundColor": color,
            "tension": 0.3,
            "pointRadius": 3,
            "borderWidth": 2,
            "fill": False,
        })
    config = {"type": "line", "data": {"labels": labels, "datasets": ds}, "options": _COMMON_OPTS}
    return _block(canvas_id, title_key, config)


def bar_chart(canvas_id: str, title_key: str, labels: list,
              datasets: list[dict]) -> tuple[str, str]:
    ds = []
    for i, d in enumerate(datasets):
        color = d.get("color") or PALETTE[i % len(PALETTE)]
        ds.append({"label": d["label"], "data": d["data"], "backgroundColor": color,
                   "borderRadius": 4})
    config = {"type": "bar", "data": {"labels": labels, "datasets": ds}, "options": _COMMON_OPTS}
    return _block(canvas_id, title_key, config)


def _block(canvas_id: str, title_key: str, config: dict) -> tuple[str, str]:
    title = components.tx(title_key, cls="chart-title")
    html = (
        f'<div class="chart-wrap">{title}'
        f'<div style="height:300px"><canvas id="{canvas_id}"></canvas></div></div>'
    )
    init_js = (
        f'  new Chart(document.getElementById("{canvas_id}"), '
        f'{json.dumps(config, ensure_ascii=False)});'
    )
    return html, init_js
