"""Non-destructive pattern features -> derived panel geometry.

The panel outline you draw is never modified. Darts, pleats and zipper
flies are stored as parameters, and this module computes, every time:

  sew      the sewing line (net shape). Pleats are spread in, dart legs are
           inserted. Segments that disappear when sewn (dart opening, pleat
           intake) are flagged as "jumps" so seams treat them as zero length.
  cut      the simulation outline: sew line + dart wedge cut out + fly
           extension.
  export   the pattern piece outline for printing/cutting: like cut, but
           darts drawn as legs (not cut out). Seam allowance is added later
           per edge.
  lines    internal markings: pleat fold/placement lines, dart legs, the
           centre-front line under a fly, the fly J-stitch.
  sews     internal seams for the simulation: dart legs to each other,
           pleat tacks.

Everything is pure Python on (x, y) tuples in metres, so it is unit tested
without Blender.
"""

import math

# ---------- small vector helpers ----------

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def mul(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def norm(a):
    L = math.hypot(*a)
    return (a[0] / L, a[1] / L) if L else (0.0, 0.0)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def left(v):
    """Rotate 90° CCW: for a CCW outline this points into the panel."""
    return (-v[1], v[0])


def rot(v, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


class Pt:
    """An outline point with a tag saying where it came from."""
    __slots__ = ("xy", "vid", "tag", "marks")

    def __init__(self, xy, vid=None, tag=None):
        self.xy = (float(xy[0]), float(xy[1]))
        self.vid = vid
        self.tag = tag
        self.marks = set()

    def __repr__(self):
        return f"Pt({self.xy[0]:.3f},{self.xy[1]:.3f},{self.vid},{self.tag})"


# ---------- polyline helpers ----------

def polyline_len(pts, jumps=()):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if i not in jumps)


def offset_polyline(pts, d):
    """Offset an open polyline to its left by d (negative = right), mitred."""
    n = len(pts)
    if n < 2:
        return list(pts)
    out = []
    for i in range(n):
        if i == 0:
            nrm = left(norm(sub(pts[1], pts[0])))
        elif i == n - 1:
            nrm = left(norm(sub(pts[-1], pts[-2])))
        else:
            n1 = left(norm(sub(pts[i], pts[i - 1])))
            n2 = left(norm(sub(pts[i + 1], pts[i])))
            m = norm(add(n1, n2))
            c = dot(m, n1)
            nrm = mul(m, 1.0 / max(c, 0.3))
        out.append(add(pts[i], mul(nrm, d)))
    return out


def offset_closed(pts, dists):
    """Grow a CCW polygon outward; edge i (pts[i]->pts[i+1]) moves out by dists[i]."""
    n = len(pts)
    lines = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        out = mul(left(norm(sub(b, a))), -dists[i])
        lines.append((add(a, out), add(b, out)))
    res = []
    cap = 3 * max(dists) if dists else 0
    for i in range(n):
        (p1, p2), (p3, p4) = lines[i - 1], lines[i]
        d1, d2 = sub(p2, p1), sub(p4, p3)
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-12:
            res.append(p3)
            continue
        t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
        q = add(p1, mul(d1, t))
        if math.dist(q, pts[i]) > cap:          # very sharp corner: bevel
            q = add(pts[i], mul(norm(sub(q, pts[i])), cap))
        res.append(q)
    return res


def point_at_arc(pts, s):
    """(point, segment index) at arc length s along polyline pts."""
    acc = 0.0
    for i in range(len(pts) - 1):
        L = math.dist(pts[i], pts[i + 1])
        if s <= acc + L or i == len(pts) - 2:
            t = 0.0 if L == 0 else min(max((s - acc) / L, 0.0), 1.0)
            return lerp(pts[i], pts[i + 1], t), i
        acc += L
    return pts[-1], len(pts) - 2


def bezier(p0, p1, p2, n=6):
    return [add(add(mul(p0, (1 - t) ** 2), mul(p1, 2 * (1 - t) * t)), mul(p2, t * t))
            for t in (k / n for k in range(1, n))]


# ---------- the derivation ----------

class Derived:
    def __init__(self):
        self.sew = []          # [Pt] closed, CCW
        self.jumps = set()     # indices i: segment sew[i] -> sew[i+1] has zero sewn length
        self.cut = []          # [(x, y)]
        self.export = []       # [(xy, base_edge_vid)]
        self.lines = []        # [{"kind", "pts", "id"}]
        self.sews = []         # [(ptsA, ptsB)] internal seams for the sim
        self.intake = []       # [polygon] pleat fabric that folds inward
        self.shifts = []       # [(P, tdir, amount)] pleat spreads, in order

    # point mapping through the pleat spreads
    def map_point(self, p):
        for P, t, amt in self.shifts:
            if dot(sub(p, P), t) > 0:
                p = add(p, mul(t, amt))
        return p

    def unmap_point(self, p):
        for P, t, amt in reversed(self.shifts):
            s = dot(sub(p, P), t)
            if s > amt:
                p = sub(p, mul(t, amt))
            elif s > 0:
                p = sub(p, mul(t, s))
        return p

    def sew_xy(self):
        return [p.xy for p in self.sew]

    def index_of_vid(self, vid):
        for i, p in enumerate(self.sew):
            if p.vid == vid:
                return i
        return None

    def chain(self, v0, v1):
        """Sew-line points from vid v0 forward to vid v1, with local jump indices."""
        i, j = self.index_of_vid(v0), self.index_of_vid(v1)
        if i is None or j is None or i == j:
            return [], set()
        n = len(self.sew)
        pts, jumps = [self.sew[i].xy], set()
        k = 0
        while i != j:
            if i in self.jumps:
                jumps.add(k)
            i = (i + 1) % n
            pts.append(self.sew[i].xy)
            k += 1
        return pts, jumps

    def edge_of(self, idx):
        """Base edge vid that sew point idx lies on (the last base vertex before it)."""
        n = len(self.sew)
        for k in range(n):
            p = self.sew[(idx - k) % n]
            if p.vid is not None:
                return p.vid
        return None


def _edge_frame(base, va, vb):
    ids = [v for v, _ in base]
    a = base[ids.index(va)][1]
    b = base[ids.index(vb)][1]
    t = norm(sub(b, a))
    return a, b, t, left(t)


def _apply_pleat(d, pl, base):
    a, b, tdir, ndir = _edge_frame(base, pl["va"], pl["vb"])
    P = d.map_point(lerp(a, b, pl["t"]))
    depth = pl["depth"]
    kind = pl.get("kind", "KNIFE")
    intake = 4 * depth if kind in ("BOX", "INVERTED") else 2 * depth
    pts = d.sew
    n = len(pts)
    s = [dot(sub(p.xy, P), tdir) for p in pts]
    new, crossings = [], []
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        si, sq = s[i], s[(i + 1) % n]
        new.append(p)
        if (si <= 0 < sq) or (sq <= 0 < si):
            u = si / (si - sq)
            x = lerp(p.xy, q.xy, u)
            first, second = (Pt(x, None, ("pleat", pl["id"], "L")),
                             Pt(add(x, mul(tdir, intake)), None, ("pleat", pl["id"], "R")))
            if si > 0:          # walking from + side back to - side
                first, second = second, first
            new += [first, second]
            crossings.append((len(new) - 2, x))
    for p in new:
        if p.tag is None or p.tag[0] != "pleat" or p.tag[1] != pl["id"]:
            if dot(sub(p.xy, P), tdir) > 1e-12:
                p.xy = add(p.xy, mul(tdir, intake))
    # jumps: the new intake segments; existing jumps must be re-indexed
    old_jump_pts = {id(pts[i]) for i in d.jumps}
    d.sew = new
    d.jumps = {i for i, p in enumerate(new) if id(p) in old_jump_pts}
    for idx, _ in crossings:
        d.jumps.add(idx)
    d.shifts.append((P, tdir, intake))
    # markings + tacks
    if len(crossings) >= 2:
        start = min(crossings, key=lambda c: math.dist(c[1], P))[1]
        far = max(crossings, key=lambda c: math.dist(c[1], P))[1]
        steps = 4 if intake == 4 * depth else 2
        for k in range(steps + 1):
            off = mul(tdir, depth * k)
            kind_line = "pleat_fold" if k in (0, steps) else "pleat_inner"
            d.lines.append({"kind": kind_line, "id": pl["id"], "pts": [add(start, off), add(far, off)]})
        down = norm(sub(far, start))
        stitch = max(pl.get("stitch", 0.0), 0.003)
        a0, b0 = start, add(start, mul(tdir, intake))
        d.sews.append(([a0, add(a0, mul(down, stitch))], [b0, add(b0, mul(down, stitch))]))
        d.intake.append([start, add(start, mul(tdir, intake)), add(far, mul(tdir, intake)), far])
        if stitch > 0.004:
            d.lines.append({"kind": "pleat_stitch", "id": pl["id"],
                            "pts": [add(a0, mul(down, stitch)), add(b0, mul(down, stitch))]})


def _insert_at(d, i, frac, pt):
    """Insert pt on sew segment i (between sew[i] and sew[i+1]) and keep jump indices right."""
    d.sew.insert(i + 1, pt)
    d.jumps = {j + 1 if j > i else j for j in d.jumps}
    return i + 1


def _locate(d, xy):
    """Sew segment index and fraction closest to xy."""
    best = None
    n = len(d.sew)
    for i in range(n):
        a, b = d.sew[i].xy, d.sew[(i + 1) % n].xy
        ab = sub(b, a)
        L2 = dot(ab, ab)
        t = 0.0 if L2 == 0 else min(max(dot(sub(xy, a), ab) / L2, 0.0), 1.0)
        dist = math.dist(xy, lerp(a, b, t))
        if best is None or dist < best[0]:
            best = (dist, i, t)
    return best[1], best[2]


def _split_at(d, xy, tag):
    """Make sure there's a sew point at xy (reusing an existing one) and mark it with tag."""
    i, t = _locate(d, xy)
    n = len(d.sew)
    a, b = d.sew[i].xy, d.sew[(i + 1) % n].xy
    L = math.dist(a, b)
    if t * L <= 1e-6:
        k = i
    elif (1 - t) * L <= 1e-6:
        k = (i + 1) % n
    else:
        k = _insert_at(d, i, t, Pt(lerp(a, b, t), None, tag))
    d.sew[k].marks.add(tag)
    return k


def _apply_dart(d, dt, base):
    a, b, tdir, ndir = _edge_frame(base, dt["va"], dt["vb"])
    P = d.map_point(lerp(a, b, dt["t"]))
    w = dt["width"]
    i1 = _split_at(d, sub(P, mul(tdir, w / 2)), ("dart", dt["id"], "leg1"))
    i2 = _split_at(d, add(P, mul(tdir, w / 2)), ("dart", dt["id"], "leg2"))
    leg1, leg2 = ("dart", dt["id"], "leg1"), ("dart", dt["id"], "leg2")
    i1 = next(k for k, p in enumerate(d.sew) if leg1 in p.marks)
    i2 = next(k for k, p in enumerate(d.sew) if leg2 in p.marks)
    # drop anything strictly between the legs (it is inside the dart opening)
    n = len(d.sew)
    k = (i1 + 1) % n
    drop = []
    while k != i2:
        drop.append(d.sew[k])
        k = (k + 1) % n
    if drop:
        keep_jumps = {id(d.sew[j]) for j in d.jumps}
        d.sew = [p for p in d.sew if p not in drop]
        d.jumps = {j for j, p in enumerate(d.sew) if id(p) in keep_jumps}
        i1 = next(k for k, p in enumerate(d.sew) if leg1 in p.marks)
    d.jumps.add(i1)
    l1 = d.sew[i1].xy
    l2 = d.sew[(i1 + 1) % len(d.sew)].xy
    apex = add(P, mul(rot(ndir, dt.get("angle", 0.0)), dt["length"]))
    d.lines.append({"kind": "dart_leg", "id": dt["id"], "pts": [l1, apex]})
    d.lines.append({"kind": "dart_leg", "id": dt["id"], "pts": [l2, apex]})
    d.sews.append(([l1, apex], [l2, apex]))
    return apex


def _apply_fly(d, fl):
    i, j = d.index_of_vid(fl["va"]), d.index_of_vid(fl["vb"])
    if i is None or j is None:
        return None
    chain_pts, _ = d.chain(fl["va"], fl["vb"])
    total = polyline_len(chain_pts)
    s0 = min(max(fl.get("start", 0.0), 0.0), total)
    s1 = min(s0 + fl["length"], total)
    w = fl["width"]
    s2 = min(s1 + w, total)
    p0, _ = point_at_arc(chain_pts, s0)
    p2, _ = point_at_arc(chain_pts, s2)
    _split_at(d, p0, ("fly", fl["id"], "start"))
    _split_at(d, p2, ("fly", fl["id"], "end"))
    # section of the sew line covered by the fly
    seg = [p0]
    acc = 0.0
    for a, b in zip(chain_pts, chain_pts[1:]):
        L = math.dist(a, b)
        if s0 < acc + L <= s1:
            seg.append(b)
        acc += L
    p1, _ = point_at_arc(chain_pts, s1)
    if math.dist(seg[-1], p1) > 1e-6:
        seg.append(p1)
    ext = offset_polyline(seg, -w)                     # outward (right of a CCW outline)
    bottom_dir = norm(sub(seg[-1], seg[-2])) if len(seg) > 1 else (0, -1)
    curve = bezier(ext[-1], add(ext[-1], mul(bottom_dir, w * 0.9)), p2)
    jstitch_in = offset_polyline(seg, w * 0.75)
    jcurve = bezier(jstitch_in[-1], add(jstitch_in[-1], mul(bottom_dir, w * 0.7)),
                    point_at_arc(chain_pts, min(s1 + w * 0.75, total))[0])
    d.lines.append({"kind": "fly_fold", "id": fl["id"], "pts": seg + [p2]})
    return {"id": fl["id"], "ext": [p0] + ext + curve + [p2], "jstitch": jstitch_in + jcurve, "seg": seg}


def derive(base, darts=(), pleats=(), flies=()):
    """base: [(vid, (x, y))] CCW. Returns Derived."""
    d = Derived()
    d.sew = [Pt(xy, vid) for vid, xy in base]
    for pl in sorted(pleats, key=lambda p: (p["va"], -p["t"])):
        _apply_pleat(d, pl, base)
    apexes = {}
    for dt in darts:
        apexes[dt["id"]] = _apply_dart(d, dt, base)
    fl_out = [f for f in (_apply_fly(d, fl) for fl in flies) if f]
    d.flies = fl_out
    for f in fl_out:
        d.lines.append({"kind": "fly_stitch", "id": f["id"], "pts": f["jstitch"]})

    # cut / export outlines: walk the sew line, add dart apexes (cut only) and fly extensions
    n = len(d.sew)
    fly_start = {f["id"]: f for f in fl_out}
    cut, export = [], []
    i = 0
    skipping = None
    edge_vid = d.edge_of(0)
    while i < n:
        p = d.sew[i]
        if p.vid is not None:
            edge_vid = p.vid
        if skipping:
            if ("fly", skipping, "end") in p.marks:
                skipping = None
            else:
                i += 1
                continue
        start = next((m for m in p.marks if m[0] == "fly" and m[2] == "start" and m[1] in fly_start), None)
        if start:
            for q in fly_start[start[1]]["ext"][:-1]:
                cut.append(q)
                export.append((q, edge_vid))
            skipping = start[1]
            i += 1
            continue
        cut.append(p.xy)
        export.append((p.xy, edge_vid))
        for m in p.marks:
            if m[0] == "dart" and m[2] == "leg1":
                cut.append(apexes[m[1]])
        i += 1
    d.cut = cut
    d.export = export
    return d
