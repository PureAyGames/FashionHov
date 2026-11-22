"""Measure a body mesh like a tailor with a tape measure.

Works on any standing body mesh (Z up, feet on the floor, arms down / A-pose,
roughly centred on X=0). Circumferences are the convex hull of the horizontal
cross-section, which is what a tape pulled snug around the body measures
(it bridges hollows instead of following them).
"""

import numpy as np

STEP = 0.0025          # slice spacing in metres
BODY_DENSITY = 1000.0  # kg/m³; real bodies are ~985-1060 depending on body fat


# ---------- slicing ----------

def slice_loops(verts, tris, z):
    """Cross-section loops of a triangle mesh at height z, as (N,2) arrays."""
    zs = verts[:, 2] - z
    zs = np.where(zs == 0, 1e-9, zs)
    tz = zs[tris]
    above = tz > 0
    cnt = above.sum(axis=1)
    hit = tris[(cnt == 1) | (cnt == 2)]
    if len(hit) == 0:
        return []
    # Each crossing triangle gives one segment between two crossing edges.
    edges = {}
    nbr = {}
    for tri in hit:
        pts = []
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            if (zs[a] > 0) != (zs[b] > 0):
                key = (a, b) if a < b else (b, a)
                if key not in edges:
                    t = zs[a] / (zs[a] - zs[b])
                    edges[key] = verts[a, :2] + t * (verts[b, :2] - verts[a, :2])
                pts.append(key)
        if len(pts) == 2:
            nbr.setdefault(pts[0], []).append(pts[1])
            nbr.setdefault(pts[1], []).append(pts[0])
    loops = []
    seen = set()
    for start in nbr:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [k for k in nbr[cur] if k != prev and k not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        if len(loop) >= 3:
            loops.append(np.array([edges[k] for k in loop]))
    return loops


# ---------- 2D helpers ----------

def convex_hull(pts):
    p = sorted(map(tuple, pts))
    if len(p) < 3:
        return np.array(p)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def closed_length(pts):
    return float(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).sum())


def tape(loop):
    """Snug tape-measure length around a cross-section."""
    return closed_length(convex_hull(loop))


def contains(loop, p):
    x, y = p
    xs, ys = loop[:, 0], loop[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (yn > y)
    with np.errstate(divide='ignore', invalid='ignore'):
        xi = xs + (y - ys) * (xn - xs) / (yn - ys)
    return bool(np.count_nonzero(cond & (x < xi)) % 2)


def gap(a, b):
    """Rough distance between two loops (min vertex-vertex distance)."""
    d = a[:, None, :] - b[None, :, :]
    return float(np.sqrt((d ** 2).sum(-1)).min())


def width(loop):
    return float(loop[:, 0].max() - loop[:, 0].min())


# ---------- volume ----------

def area(loop):
    x, y = loop[:, 0], loop[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def volume(verts, tris, step=0.005):
    """Stack of cross-section areas. Robust to holes and flipped normals."""
    z0, z1 = verts[:, 2].min(), verts[:, 2].max()
    total = 0.0
    for z in np.arange(z0 + step / 2, z1, step):
        total += sum(area(l) for l in slice_loops(verts, tris, z)) * step
    return total


# ---------- the measurer ----------

class Body:
    def __init__(self, verts, tris):
        self.v = np.asarray(verts, dtype=float)
        self.t = np.asarray(tris, dtype=np.int64)
        self.z0 = float(self.v[:, 2].min())
        self.z1 = float(self.v[:, 2].max())
        self.h = self.z1 - self.z0
        mid = self.loops_at(self.z0 + 0.6 * self.h)
        torso = max(mid, key=lambda l: len(l)) if mid else np.zeros((1, 2))
        self.c = torso.mean(axis=0)

    def loops_at(self, z):
        return slice_loops(self.v, self.t, z)

    def center_loop(self, z):
        """The torso cross-section: contains the body's centre line AND is centred on it
        (so overlapping thighs don't count)."""
        ok = [l for l in self.loops_at(z)
              if contains(l, self.c) and abs(l[:, 0].mean() - self.c[0]) < 0.035]
        return max(ok, key=area) if ok else None

    def zrange(self, a, b):
        return np.arange(a, b, STEP)

    def measure(self, with_mass=True):
        h, z0 = self.h, self.z0
        out = {"height": h}
        loops = {}

        # Crotch: lowest height where the centre line is inside the body.
        crotch = None
        for z in self.zrange(z0 + 0.30 * h, z0 + 0.60 * h):
            if self.center_loop(z) is not None:
                crotch = z
                break
        if crotch is None:
            raise ValueError("couldn't find the crotch; is this a standing body?")
        out["inseam"] = crotch - z0

        def band(a, b, pick):
            best = None
            for z in self.zrange(a, b):
                loop = self.center_loop(z)
                if loop is None:
                    continue
                v = tape(loop)
                if best is None or pick(v, best[0]):
                    best = (v, z, loop)
            return best

        hips = band(crotch + 0.005, crotch + 0.13 * h, lambda v, b: v > b)
        out["hips"], loops["hips"] = hips[0], (hips[1], hips[2])

        # Armpit: going up, the arms join the torso (merged loop gets much wider,
        # or a separate arm loop touches it).
        armpit = None
        prev_w = None
        for z in self.zrange(hips[1] + 0.05 * h, z0 + 0.85 * h):
            loop = self.center_loop(z)
            if loop is None:
                continue
            w = width(loop)
            others = [l for l in self.loops_at(z) if l is not loop and not contains(loop, l.mean(axis=0))]
            touching = any(gap(loop, o) < 0.006 for o in others if len(o) > 2)
            if (prev_w and w > prev_w * 1.2) or touching:
                armpit = z
                break
            prev_w = w
        if armpit is None:
            armpit = z0 + 0.74 * h

        waist = band(hips[1] + 0.02 * h, armpit - 0.06 * h, lambda v, b: v < b)
        out["waist"], loops["waist"] = waist[0], (waist[1], waist[2])
        chest = band(waist[1] + 0.02 * h, armpit - 0.005, lambda v, b: v > b)
        out["chest"], loops["chest"] = chest[0], (chest[1], chest[2])

        # Neck base: going up from the armpit, the body narrows to just the neck.
        chest_w = width(chest[2])
        neck_base = None
        for z in self.zrange(armpit, z0 + 0.95 * h):
            near = [l for l in self.loops_at(z) if abs(l.mean(axis=0)[0] - self.c[0]) < 0.35]
            if near and max(width(l) for l in near) < 0.5 * chest_w:
                neck_base = z
                break

        # Shoulders: point to point, measured 60% of the way from armpit to neck base,
        # where the shoulder slope meets the top of the arm.
        top = neck_base if neck_base is not None else armpit + 0.08 * h
        sh_z = armpit + 0.6 * (top - armpit)
        near = [l for l in self.loops_at(sh_z) if abs(l.mean(axis=0)[0] - self.c[0]) < 0.35]
        if near:
            allpts = np.vstack(near)
            out["shoulders"] = float(allpts[:, 0].max() - allpts[:, 0].min())
            loops["shoulders"] = (sh_z, allpts[[allpts[:, 0].argmin(), allpts[:, 0].argmax()]])
        if neck_base is not None:
            neck = band(neck_base, neck_base + 0.045 * h, lambda v, b: v < b)
            if neck:
                out["neck"], loops["neck"] = neck[0], (neck[1], neck[2])

        # Thigh: the leg loop just under the crotch, on the +X side.
        best = None
        for z in self.zrange(crotch - 0.06 * h, crotch - 0.008):
            legs = [l for l in self.loops_at(z) if 0.0 < l.mean(axis=0)[0] - self.c[0] < 0.2]
            if not legs:
                continue
            leg = max(legs, key=lambda l: tape(l))
            v = tape(leg)
            if best is None or v > best[0]:
                best = (v, z, leg)
        if best:
            out["thigh"], loops["thigh"] = best[0], (best[1], best[2])

        if with_mass:
            vol = volume(self.v, self.t)
            out["volume"] = vol
            out["mass"] = vol * BODY_DENSITY
        # Landmark heights (world z), used to place garment pieces.
        out["z_floor"] = z0
        out["z_crotch"] = crotch
        out["z_hips"] = hips[1]
        out["z_waist"] = waist[1]
        out["z_chest"] = chest[1]
        out["z_armpit"] = armpit
        out["z_neck_base"] = neck_base if neck_base is not None else armpit + 0.08 * h
        self.loops = loops
        return out


def measure(verts, tris, with_mass=True):
    b = Body(verts, tris)
    m = b.measure(with_mass)
    return m, b.loops
