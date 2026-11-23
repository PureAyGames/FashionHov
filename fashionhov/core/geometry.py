"""2D polygon helpers for pattern panels (units: metres)."""

import math


def edge_lengths(points, closed=True):
    n = len(points)
    count = n if closed else n - 1
    return [math.dist(points[i], points[(i + 1) % n]) for i in range(count)]


def perimeter(points):
    return sum(edge_lengths(points))


def signed_area(points):
    n = len(points)
    return 0.5 * sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
                     for i in range(n))


def area(points):
    return abs(signed_area(points))


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_polygon(p, poly):
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def dist_to_segment(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def dist_to_polygon(p, poly):
    n = len(poly)
    return min(dist_to_segment(p, poly[i], poly[(i + 1) % n]) for i in range(n))


def resample_outline(points, spacing):
    """Subdivide each edge so no segment is longer than spacing; corners kept."""
    out = []
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        steps = max(1, math.ceil(math.dist(a, b) / spacing))
        for s in range(steps):
            t = s / steps
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _seg_dists(P, segs):
    """Min distance from each point in P (N,2) to a set of segments (M,2,2)."""
    import numpy as np
    if len(segs) == 0:
        return np.full(len(P), np.inf)
    A, B = segs[:, 0], segs[:, 1]
    AB = B - A
    L2 = np.maximum((AB ** 2).sum(1), 1e-18)
    best = np.full(len(P), np.inf)
    for k in range(0, len(segs), 256):          # chunk to keep memory small
        a, ab, l2 = A[k:k + 256], AB[k:k + 256], L2[k:k + 256]
        t = np.clip(((P[:, None, :] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
        q = a[None] + t[..., None] * ab[None]
        best = np.minimum(best, np.sqrt(((P[:, None, :] - q) ** 2).sum(-1)).min(1))
    return best


def hex_fill(poly, spacing, lines=()):
    """Interior points on a hexagonal lattice (gives near-equilateral triangles),
    kept away from the outline and from any internal constraint lines."""
    import numpy as np
    x0, y0, x1, y1 = bbox(poly)
    dy = spacing * math.sqrt(3) / 2
    ys = np.arange(y0 + dy / 2, y1, dy)
    pts = []
    for r, y in enumerate(ys):
        xs = np.arange(x0 + (spacing / 2 if r % 2 else 0.0), x1, spacing)
        pts.append(np.column_stack([xs, np.full(len(xs), y)]))
    if not pts:
        return []
    P = np.vstack(pts)
    poly_a = np.asarray(poly, float)
    xs, ys_ = poly_a[:, 0], poly_a[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys_, -1)
    inside = np.zeros(len(P), bool)
    for i in range(len(poly_a)):
        cond = (ys_[i] > P[:, 1]) != (yn[i] > P[:, 1])
        with np.errstate(divide='ignore', invalid='ignore'):
            xi = xs[i] + (P[:, 1] - ys_[i]) * (xn[i] - xs[i]) / (yn[i] - ys_[i])
        inside ^= cond & (P[:, 0] < xi)
    P = P[inside]
    segs = [[poly_a[i], poly_a[(i + 1) % len(poly_a)]] for i in range(len(poly_a))]
    for line in lines:
        segs += [[line[i], line[i + 1]] for i in range(len(line) - 1)]
    d = _seg_dists(P, np.asarray(segs, float))
    return [tuple(p) for p in P[d > spacing * 0.5]]


def resample_polyline(points, spacing):
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        steps = max(1, math.ceil(math.dist(a, b) / spacing))
        for s in range(1, steps + 1):
            t = s / steps
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def snap_angle(origin, p, step_deg=45.0):
    """Snap p so the segment origin->p lies on a multiple of step_deg."""
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return p
    step = math.radians(step_deg)
    ang = round(math.atan2(dy, dx) / step) * step
    return origin[0] + length * math.cos(ang), origin[1] + length * math.sin(ang)
