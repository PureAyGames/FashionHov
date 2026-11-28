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
    @staticmethod
    def _amount(shift, p):
        P, t, n, amt, taper = shift
        if taper <= 0:
            return amt
        h = dot(sub(p, P), n)          # depth into the panel; unchanged by the spread
        return amt * min(max(1.0 - h / taper, 0.0), 1.0)

    def map_point(self, p):
        for sh in self.shifts:
            if dot(sub(p, sh[0]), sh[1]) > 0:
                p = add(p, mul(sh[1], self._amount(sh, p)))
        return p

    def unmap_point(self, p):
        for sh in reversed(self.shifts):
            P, t = sh[0], sh[1]
            s = dot(sub(p, P), t)
            a = self._amount(sh, p)
            if s > a:
                p = sub(p, mul(t, a))
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
    """Slash and spread. taper = 0: the spread runs the full length of the panel.
    taper > 0: the pleat pivots to nothing at that depth (like trouser front pleats)."""
    a, b, tdir, ndir = _edge_frame(base, pl["va"], pl["vb"])
    P = d.map_point(lerp(a, b, pl["t"]))
    depth = pl["depth"]
    kind = pl.get("kind", "KNIFE")
    intake = 4 * depth if kind in ("BOX", "INVERTED") else 2 * depth
    taper = max(pl.get("taper", 0.0), 0.0)
    shift = (P, tdir, ndir, intake, taper)
    amount = lambda x: Derived._amount(shift, x)
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
            amt = amount(x)
            if amt < 1e-7:              # beyond the taper's pivot: nothing to open here
                continue
            first, second = (Pt(x, None, ("pleat", pl["id"], "L")),
                             Pt(add(x, mul(tdir, amt)), None, ("pleat", pl["id"], "R")))
            if si > 0:                  # walking from + side back to - side
                first, second = second, first
            new += [first, second]
            crossings.append((len(new) - 2, x))
    for p in new:
        if p.tag is None or p.tag[0] != "pleat" or p.tag[1] != pl["id"]:
            if dot(sub(p.xy, P), tdir) > 1e-12:
                p.xy = add(p.xy, mul(tdir, amount(p.xy)))
    old_jump_pts = {id(pts[i]) for i in d.jumps}
    d.sew = new
    d.jumps = {i for i, p in enumerate(new) if id(p) in old_jump_pts}
    for idx, _ in crossings:
        d.jumps.add(idx)
    d.shifts.append(shift)
    if not crossings:
        return
    start = min(crossings, key=lambda c: math.dist(c[1], P))[1]
    # far end of the pleat lines: the opposite crossing, or the taper's pivot point
    far_cross = [c[1] for c in crossings if math.dist(c[1], start) > 1e-9]
    ray_far = None
    for i in range(n):
        p0, p1 = pts[i].xy, pts[(i + 1) % n].xy
        if (dot(sub(p0, P), tdir) <= 0 < dot(sub(p1, P), tdir)) or (dot(sub(p1, P), tdir) <= 0 < dot(sub(p0, P), tdir)):
            si_, sq_ = dot(sub(p0, P), tdir), dot(sub(p1, P), tdir)
            x = lerp(p0, p1, si_ / (si_ - sq_))
            if math.dist(x, start) > 1e-9:
                ray_far = x
    far = far_cross[0] if far_cross else ray_far
    if far is None:
        return
    down = norm(sub(far, start))
    full = math.dist(start, far)
    tapered = 0 < taper < full
    end = add(start, mul(down, taper)) if tapered else far
    steps = 4 if intake == 4 * depth else 2
    for k in range(steps + 1):
        off = mul(tdir, depth * k)
        kind_line = "pleat_fold" if k in (0, steps) else "pleat_inner"
        d.lines.append({"kind": kind_line, "id": pl["id"],
                        "pts": [add(start, off), end if tapered else add(far, off)]})
    stitch = min(max(pl.get("stitch", 0.0), 0.003), (taper if tapered else full) * 0.9)
    a0, b0 = start, add(start, mul(tdir, intake))
    b_dir = norm(sub(end, b0)) if tapered else down
    d.sews.append(([a0, add(a0, mul(down, stitch))], [b0, add(b0, mul(b_dir, stitch))]))
    d.intake.append([start, b0, end] if tapered else [start, b0, add(far, mul(tdir, intake)), far])
    if stitch > 0.004:
        d.lines.append({"kind": "pleat_stitch", "id": pl["id"],
                        "pts": [add(a0, mul(down, stitch)), add(b0, mul(b_dir, stitch))]})


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


def _apply_inner_dart(d, dt):
    """Fisheye (double-ended) dart fully inside the panel: a diamond whose two
    sides get sewn together. Cut out for the simulation, drawn as legs on paper."""
    c = d.map_point(dt["c"])
    u = rot((0.0, 1.0), dt.get("angle", 0.0))
    w = (u[1], -u[0])
    top = add(c, mul(u, dt["up"]))
    bot = sub(c, mul(u, dt["down"]))
    lft = sub(c, mul(w, dt["width"] / 2))
    rgt = add(c, mul(w, dt["width"] / 2))
    d.holes.append([top, lft, bot, rgt])
    for a, b in ((top, lft), (lft, bot), (top, rgt), (rgt, bot)):
        d.lines.append({"kind": "dart_leg", "id": dt["id"], "pts": [a, b]})
    d.sews.append(([top, lft, bot], [top, rgt, bot]))


def _arc_from(d, i, dist, step):
    """Walk the sew line from index i by dist (step=+1 forward, -1 backward): xy."""
    n = len(d.sew)
    acc, k = 0.0, i
    while True:
        j = (k + step) % n
        L = math.dist(d.sew[k].xy, d.sew[j].xy)
        if acc + L >= dist or j == i:
            t = 0.0 if L == 0 else min((dist - acc) / L, 1.0)
            return lerp(d.sew[k].xy, d.sew[j].xy, t)
        acc += L
        k = j


def _apply_scoop(d, sc):
    """Front scoop pocket opening at a corner: the panel is cut along a curve
    (pattern, export and simulation; the facing piece sits behind it).
    Returns the replacement curve."""
    i = d.index_of_vid(sc["corner"])
    if i is None:
        return None
    c = d.sew[i].xy
    A = _arc_from(d, i, sc["width"], -1)
    B = _arc_from(d, i, sc["depth"], +1)
    mid = lerp(A, B, 0.5)
    ctrl = add(mid, mul(sub(mid, c), sc.get("curve", 0.35)))
    curve = [A] + bezier(A, ctrl, B, 10) + [B]
    _split_at(d, A, ("scoop", sc["id"], "start"))
    _split_at(d, B, ("scoop", sc["id"], "end"))
    d.lines.append({"kind": "pocket_opening", "id": sc["id"], "pts": curve})
    return {"id": sc["id"], "ext": curve, "corner": c, "A": A, "B": B}


def _walk(d, excursions, apexes):
    """Build an outline from the sew line, replacing each excursion span
    (start mark -> end mark) with its points; optionally adding dart apexes."""
    n = len(d.sew)
    starts = {}
    ends = {}
    for kind, ex in excursions:
        si = next((k for k, p in enumerate(d.sew) if (kind, ex["id"], "start") in p.marks), None)
        ei = next((k for k, p in enumerate(d.sew) if (kind, ex["id"], "end") in p.marks), None)
        if si is not None and ei is not None:
            starts[si] = (ei, ex["ext"])
            ends[ei] = si
    # start somewhere that isn't inside an excursion
    inside = set()
    for si, (ei, _) in starts.items():
        k = (si + 1) % n
        while k != ei:
            inside.add(k)
            k = (k + 1) % n
    s0 = next((k for k in range(n) if k not in inside and k not in ends), 0)
    out = []
    edge_vid = d.edge_of(s0)
    k, steps = s0, 0
    while steps < n:
        p = d.sew[k]
        if p.vid is not None:
            edge_vid = p.vid
        if k in starts:
            ei, pts = starts[k]
            for q in pts[:-1]:
                out.append((q, edge_vid))
            jump = (ei - k) % n
            k, steps = ei, steps + jump
            continue
        out.append((p.xy, edge_vid))
        if apexes is not None:
            for m in p.marks:
                if m[0] == "dart" and m[2] == "leg1":
                    out.append((apexes[m[1]], edge_vid))
        k, steps = (k + 1) % n, steps + 1
    return out


def derive(base, darts=(), pleats=(), flies=(), inner_darts=(), scoops=()):
    """base: [(vid, (x, y))] CCW. Returns Derived."""
    d = Derived()
    d.holes = []
    d.sew = [Pt(xy, vid) for vid, xy in base]
    for pl in sorted(pleats, key=lambda p: (p["va"], -p["t"])):
        _apply_pleat(d, pl, base)
    apexes = {}
    for dt in darts:
        apexes[dt["id"]] = _apply_dart(d, dt, base)
    for dt in inner_darts:
        _apply_inner_dart(d, dt)
    fl_out = [f for f in (_apply_fly(d, fl) for fl in flies) if f]
    sc_out = [x for x in (_apply_scoop(d, sc) for sc in scoops) if x]
    d.flies, d.scoops = fl_out, sc_out
    for f in fl_out:
        d.lines.append({"kind": "fly_stitch", "id": f["id"], "pts": f["jstitch"]})
    # simulation outline: fly extensions, scoop openings, dart wedges cut out
    d.cut = [p for p, _ in _walk(d, [("fly", f) for f in fl_out] + [("scoop", x) for x in sc_out], apexes)]
    # paper pattern outline: fly extensions + scoop curves, darts drawn as legs
    d.export = _walk(d, [("fly", f) for f in fl_out] + [("scoop", x) for x in sc_out], None)
    return d
