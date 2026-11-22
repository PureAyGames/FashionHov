"""Fit body-shape knobs to tape measurements (bounded Levenberg-Marquardt).

Each knob is a slider (name, lo, hi). evaluate(knobs) -> measurements.
Residuals are in centimetres (mass: 1 kg counts like 1 cm) so all
measurements are comparable.
"""

import numpy as np

SCALE = {"mass": 1.0}   # everything else is metres -> x100 = cm


def _residuals(meas, targets, weights):
    r = []
    for k, t in targets.items():
        if k not in meas:
            r.append(0.0)
            continue
        s = SCALE.get(k, 100.0)
        r.append((meas[k] - t) * s * weights.get(k, 1.0))
    return np.array(r)


def fit(knobs, x0, evaluate, targets, weights=None, iters=6, progress=None, tol_cm=0.3):
    """knobs: list of (name, lo, hi). Returns (x dict, measurements, rms cm)."""
    weights = weights or {}
    names = [k[0] for k in knobs]
    lo = np.array([k[1] for k in knobs], float)
    hi = np.array([k[2] for k in knobs], float)
    x = np.clip(np.array([x0[n] for n in names], float), lo, hi)
    as_dict = lambda v: dict(zip(names, v))

    meas = evaluate(as_dict(x))
    r = _residuals(meas, targets, weights)
    lam = 1e-2
    calls = 1
    for it in range(iters):
        if np.sqrt(np.mean(r ** 2)) < tol_cm:
            break
        J = np.zeros((len(r), len(x)))
        for j in range(len(x)):
            h = (hi[j] - lo[j]) * 0.03
            xj = x.copy()
            xj[j] = xj[j] + h if xj[j] + h <= hi[j] else xj[j] - h
            dj = xj[j] - x[j]
            J[:, j] = (_residuals(evaluate(as_dict(xj)), targets, weights) - r) / dj
            calls += 1
            if progress:
                progress(it, j)
        A = J.T @ J
        g = J.T @ r
        improved = False
        for _ in range(4):
            step = -np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), g)
            xn = np.clip(x + step, lo, hi)
            mn = evaluate(as_dict(xn))
            calls += 1
            rn = _residuals(mn, targets, weights)
            if (rn ** 2).sum() < (r ** 2).sum():
                x, meas, r = xn, mn, rn
                lam = max(lam / 3, 1e-4)
                improved = True
                break
            lam *= 5
        if not improved:
            break
    return as_dict(x), meas, float(np.sqrt(np.mean(r ** 2))), calls
