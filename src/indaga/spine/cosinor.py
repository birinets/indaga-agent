"""24-hour cosinor fit — the validated HRP method, vendored for the spine.

Ported verbatim from ``compute_hr_nadir_cosinor.py::cosinor_fit`` (the All-of-Us /
npj Digital Medicine 2025 full-24h recipe). Kept here so the product spine does not
import a loose root-level analysis script. **This is the shared home going forward;**
``06j_hrp_cosinor.py`` remains the canonical *report*, and its result and this one
must agree — if the method is improved, change it in one place.

stdlib + numpy.
"""

from __future__ import annotations

import math

import numpy as np


def cosinor_fit(hours, values, harmonics=(1,)) -> dict:
    """Least-squares fit  y = M + Σ_k [ a_k cos(2π k t / 24) + b_k sin(2π k t / 24) ].

    Returns mesor, per-harmonic amplitude/acrophase, R², the nadir (trough of the
    fitted curve), and a callable ``predict(t_hours)``.
    """
    hours = np.asarray(hours, float)
    y = np.asarray(values, float)
    cols = [np.ones_like(hours)]
    for k in harmonics:
        w = 2 * math.pi * k / 24.0
        cols.append(np.cos(w * hours))
        cols.append(np.sin(w * hours))
    X = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ beta
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    mesor = float(beta[0])
    comps = {}
    idx = 1
    for k in harmonics:
        a, b = float(beta[idx]), float(beta[idx + 1])
        idx += 2
        amp = math.hypot(a, b)
        acro = (math.atan2(b, a) * 24.0 / (2 * math.pi * k)) % (24.0 / k)
        comps[k] = {"amplitude": amp, "acrophase_h": acro}

    def predict(t):
        t = np.asarray(t, float)
        out = np.full_like(t, beta[0], dtype=float)
        j = 1
        for k in harmonics:
            w = 2 * math.pi * k / 24.0
            out = out + beta[j] * np.cos(w * t) + beta[j + 1] * np.sin(w * t)
            j += 2
        return out

    grid = np.arange(0, 24, 1 / 60)  # 1-min resolution
    pv = predict(grid)
    nadir_h = float(grid[int(np.argmin(pv))])
    peak_h = float(grid[int(np.argmax(pv))])
    hrp_h = (comps[1]["acrophase_h"] - 6.0) % 24.0

    return {
        "mesor_bpm": mesor,
        "amplitude_bpm": comps[1]["amplitude"],
        "acrophase_peak_h": comps[1]["acrophase_h"],
        "nadir_analytic_h": (comps[1]["acrophase_h"] + 12.0) % 24.0,
        "nadir_curve_h": nadir_h,
        "peak_curve_h": peak_h,
        "hrp_h": hrp_h,
        "r2": r2,
        "n": int(len(y)),
    }


def hh_mm(h: float) -> str:
    h = h % 24
    m = int(round(h * 60))
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"
