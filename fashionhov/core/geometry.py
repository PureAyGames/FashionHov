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


def hex_fill(poly, spacing):
    """Interior points on a hexagonal lattice (gives near-equilateral triangles)."""
    x0, y0, x1, y1 = bbox(poly)
    dy = spacing * math.sqrt(3) / 2
    pts = []
    row = 0
    y = y0 + dy / 2
    while y < y1:
        x = x0 + (spacing / 2 if row % 2 else 0.0)
        while x < x1:
            p = (x, y)
            if point_in_polygon(p, poly) and dist_to_polygon(p, poly) > spacing * 0.5:
                pts.append(p)
            x += spacing
        y += dy
        row += 1
    return pts


def snap_angle(origin, p, step_deg=45.0):
    """Snap p so the segment origin->p lies on a multiple of step_deg."""
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return p
    step = math.radians(step_deg)
    ang = round(math.atan2(dy, dx) / step) * step
    return origin[0] + length * math.cos(ang), origin[1] + length * math.sin(ang)
