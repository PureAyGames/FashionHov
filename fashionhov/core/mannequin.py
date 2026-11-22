"""Parametric dress form built straight from body measurements.

This is the fallback avatar when MPFB isn't installed: a tailor's form
with legs, arms and head, whose cross-sections are ellipses sized so a
tape around them reads the measurement you entered.
"""

import math
import numpy as np

SEG = 40

DEFAULTS = dict(height=1.78, chest=1.00, waist=0.84, hips=0.98, neck=0.39,
                thigh=0.57, inseam=0.81, shoulders=0.46)


def ellipse_axes(circumference, ratio):
    """Semi-axes (a, b=a*ratio) of an ellipse with the given perimeter (Ramanujan)."""
    r = ratio
    k = math.pi * (3 * (1 + r) - math.sqrt((3 + r) * (1 + 3 * r)))
    a = circumference / k
    return a, a * r


def _ring(cx, cy, z, a, b, seg=SEG, front_flat=0.0):
    t = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    x = cx + a * np.cos(t)
    y = cy + b * np.sin(t)
    if front_flat:
        y = np.where(y < cy, cy + (y - cy) * (1 - front_flat), y)
    return np.column_stack([x, y, np.full(seg, z)])


def _loft(rings, cap_bottom=True, cap_top=True):
    """Tube through rings (each (SEG,3)), closed with fan caps. Returns verts, tris."""
    seg = len(rings[0])
    verts = list(np.vstack(rings))
    tris = []
    for i in range(len(rings) - 1):
        o, n = i * seg, (i + 1) * seg
        for j in range(seg):
            a, b = o + j, o + (j + 1) % seg
            c, d = n + (j + 1) % seg, n + j
            tris += [(a, b, c), (a, c, d)]
    if cap_bottom:
        ci = len(verts)
        verts.append(rings[0].mean(axis=0))
        tris += [(ci, (j + 1) % seg, j) for j in range(seg)]
    if cap_top:
        ci = len(verts)
        verts.append(rings[-1].mean(axis=0))
        o = (len(rings) - 1) * seg
        tris += [(ci, o + j, o + (j + 1) % seg) for j in range(seg)]
    return np.array(verts), np.array(tris)


def _tube_along(p0, p1, radii, seg=24):
    """Round tube from p0 to p1 with radii sampled evenly along it."""
    p0, p1 = np.array(p0, float), np.array(p1, float)
    d = p1 - p0
    d /= np.linalg.norm(d)
    u = np.cross(d, [0, 1, 0])
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(d, [1, 0, 0])
    u /= np.linalg.norm(u)
    w = np.cross(d, u)
    t = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    rings = []
    for i, r in enumerate(radii):
        c = p0 + (p1 - p0) * i / (len(radii) - 1)
        rings.append(c + r * (np.outer(np.cos(t), u) + np.outer(np.sin(t), w)))
    return _loft(rings)


def build(m=None):
    """Return (verts, tris) of a dress form for measurement dict m (metres)."""
    p = dict(DEFAULTS)
    p.update(m or {})
    H = p["height"]
    crotch = p["inseam"]
    hip_z = crotch + 0.045 * H
    waist_z = 0.615 * H
    chest_z = 0.725 * H
    armpit_z = 0.745 * H
    shoulder_z = 0.815 * H
    neck_z = 0.86 * H
    chin_z = 0.875 * H

    hip_a, hip_b = ellipse_axes(p["hips"], 0.72)
    w_a, w_b = ellipse_axes(p["waist"], 0.78)
    c_a, c_b = ellipse_axes(p["chest"], 0.70)
    n_a, n_b = ellipse_axes(p["neck"], 0.95)
    sh_a = p["shoulders"] / 2 - 0.045
    parts = []

    # Torso from crotch to neck, a smooth stack of ellipses.
    levels = [
        (crotch + 0.004, hip_a * 0.92, hip_b * 0.88),
        (hip_z, hip_a, hip_b),
        ((hip_z + waist_z) / 2, (hip_a + w_a) / 2, (hip_b + w_b) / 2),
        (waist_z, w_a, w_b),
        ((waist_z + chest_z) / 2, (w_a + c_a) / 2, (w_b + c_b) / 2),
        (chest_z, c_a, c_b),
        (armpit_z, c_a * 0.98, c_b * 0.97),
        ((armpit_z + shoulder_z) / 2, max(c_a, sh_a) * 0.98, c_b * 0.85),
        (shoulder_z, sh_a, c_b * 0.6),
        (shoulder_z + 0.012 * H, n_a * 1.6, n_b * 1.3),
        (neck_z - 0.01 * H, n_a, n_b),
        (chin_z, n_a, n_b),
    ]
    parts.append(_loft([_ring(0, 0, z, a, b) for z, a, b in levels]))

    # Head.
    hr = (H - chin_z) / 2.04
    t = np.linspace(0.05, math.pi - 0.05, 12)
    head_rings = [_ring(0, -0.01, chin_z + hr * (1 - math.cos(a)) * 1.02, hr * 0.8 * math.sin(a), hr * math.sin(a))
                  for a in t]
    parts.append(_loft(head_rings))

    # Legs: thigh at top, tapering to the ankle.
    t_r = p["thigh"] / (2 * math.pi)
    leg_x = max(hip_a * 0.48, t_r * 1.03)
    for s in (-1, 1):
        x = s * leg_x
        parts.append(_tube_along((x * 0.9, 0.0, 0.03 * H), (x, 0.0, crotch + 0.03 * H),
                                 [t_r * 0.36, t_r * 0.52, t_r * 0.6, t_r * 0.66, t_r * 0.82, t_r, t_r * 1.02]))
        # foot
        parts.append(_tube_along((x * 0.9, 0.03, 0.035), (x * 0.9, -0.19, 0.03),
                                 [0.03, 0.035, 0.034, 0.025]))

    # Arms hanging in an A-pose, 35° off vertical.
    arm_len = 0.44 * H
    ang = math.radians(35)
    for s in (-1, 1):
        top = np.array([s * (p["shoulders"] / 2 - 0.06), 0.0, shoulder_z - 0.02 * H])
        bot = top + arm_len * np.array([s * math.sin(ang), 0.0, -math.cos(ang)])
        parts.append(_tube_along(top, bot, [0.052, 0.048, 0.04, 0.033, 0.027, 0.032]))

    verts, tris, off = [], [], 0
    for v, f in parts:
        verts.append(v)
        tris.append(f + off)
        off += len(v)
    return np.vstack(verts), np.vstack(tris)
