"""Export the flat pattern at 1:1 as SVG (print/plot) or DXF (CAD, cutters).

Each piece gets: cut line (with seam allowance, hem allowance on hemmed
edges), sewing line, dart legs, pleat fold/placement lines, fly line and
J-stitch, hem fold lines, notches where seams end, hardware marks, buttonhole
slits, zipper stops, grainline and a label. Graded sizes are exported by
grading every one of those points, so darts and pleats stay where they belong.
"""

import math
import os
import bpy
from bpy_extras.io_utils import ExportHelper

from . import features as ft
from .core import derive as dv
from .util import active_panels

STYLE = {
    "cut": ("#000000", 0.35, None), "sew": ("#7a7a7a", 0.2, "2,1.5"),
    "dart_leg": ("#c0392b", 0.3, None), "pleat_fold": ("#2c6fbb", 0.3, "4,2"),
    "pleat_inner": ("#2c6fbb", 0.25, "1,1.5"), "pleat_stitch": ("#2c6fbb", 0.25, None),
    "fly_fold": ("#8e44ad", 0.3, "4,2"), "fly_stitch": ("#d35400", 0.25, "1,1"),
    "hem_fold": ("#27ae60", 0.3, "4,2"), "mark": ("#000000", 0.25, None),
    "pocket_place": ("#e67e22", 0.3, "3,1.5"), "pocket_opening": ("#e67e22", 0.3, None),
    "grain": ("#000000", 0.25, None), "zip": ("#555555", 0.4, "0.8,0.8"),
}


def piece_geometry(context, panel, grade=None):
    """All export primitives for one panel, world XY metres. grade: (sx, sy, anchor) or None."""
    scene = context.scene
    d = ft.get_derived(panel)
    if d is None:
        return None
    hems = ft.hems_by_edge(panel)
    sa = ft.seam_allowance(panel, scene)
    pts = [p for p, _ in d.export]
    dists = [ft.hem_allowance(hems[e]) if e in hems else sa for _, e in d.export]
    cut = dv.offset_closed(pts, dists) if max(dists) > 0 else list(pts)
    g = {"name": panel.name, "cut": cut, "sew": d.sew_xy(), "lines": [], "circles": [], "segs": [], "texts": []}
    for line in d.lines:
        g["lines"].append((line["kind"], line["pts"]))
    for h in panel.fh_features.hems:
        if not ft.on(h, "hems", scene):
            continue
        chain, _ = d.chain(h.va, h.vb)
        if len(chain) >= 2:
            g["lines"].append(("hem_fold", chain))
            if h.fold == 'DOUBLE':
                g["lines"].append(("hem_fold", dv.offset_polyline(chain, -h.width)))
    # notches: where seams start/end on this panel, across the seam allowance
    for seam in scene.fh_seams:
        for obj, v0, v1 in ((seam.a_obj, seam.a_v0, seam.a_v1), (seam.b_obj, seam.b_v0, seam.b_v1)):
            if obj != panel:
                continue
            chain, _ = d.chain(v0, v1)
            if len(chain) < 2:
                continue
            for p, q in ((chain[0], chain[1]), (chain[-1], chain[-2])):
                t = dv.norm(dv.sub(q, p))
                out = (t[1], -t[0])                 # right of a CCW chain = outside
                g["segs"].append(("mark", p, dv.add(p, dv.mul(out, max(sa, 0.005) * 0.6))))
    for hw in panel.fh_features.hardware:
        if not ft.on(hw, ft.hw_category(hw), scene):
            continue
        if hw.kind == 'ZIPPER':
            path = ft.zipper_path(panel, hw)
            if len(path) >= 2:
                g["lines"].append(("zip", path))
                for p, q in ((path[0], path[1]), (path[-1], path[-2])):
                    t = dv.norm(dv.sub(q, p))
                    n = dv.left(t)
                    g["segs"].append(("mark", dv.add(p, dv.mul(n, -0.006)), dv.add(p, dv.mul(n, 0.006))))
            continue
        xy = ft.hardware_world(panel, hw)
        if hw.kind == 'BUTTONHOLE':
            c, s = math.cos(hw.angle), math.sin(hw.angle)
            L = hw.size / 2
            g["segs"].append(("mark", (xy[0] - L * c, xy[1] - L * s), (xy[0] + L * c, xy[1] + L * s)))
            for e in (-1, 1):
                ex, ey = xy[0] + e * L * c, xy[1] + e * L * s
                g["segs"].append(("mark", (ex + 0.002 * s, ey - 0.002 * c), (ex - 0.002 * s, ey + 0.002 * c)))
        else:
            r = hw.size / 2
            g["circles"].append(("mark", xy, r))
            g["segs"].append(("mark", (xy[0] - r * 1.4, xy[1]), (xy[0] + r * 1.4, xy[1])))
            g["segs"].append(("mark", (xy[0], xy[1] - r * 1.4), (xy[0], xy[1] + r * 1.4)))
    xs = [p[0] for p in g["sew"]]
    ys = [p[1] for p in g["sew"]]
    cx, cy, h = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(ys) - min(ys)
    g["segs"].append(("grain", (cx, cy - 0.3 * h), (cx, cy + 0.3 * h)))
    for sx in (-1, 1):
        g["segs"].append(("grain", (cx, cy + 0.3 * h), (cx + sx * 0.008, cy + 0.3 * h - 0.015)))
    g["texts"].append(((cx + 0.01, cy), panel.name, 0.008))
    if panel.get("fh_feature_of"):
        _, item = ft.owner_of(panel)
        cut_from = "pocketing" if item is not None and getattr(item, "bag", None) == panel else "self fabric"
        g["texts"].append(((cx + 0.01, cy - 0.012), f"Cut 1 {cut_from}", 0.005))
    if grade:
        sx_, sy_, (ax, ay) = grade
        f = lambda p: (ax + (p[0] - ax) * sx_, ay + (p[1] - ay) * sy_)
        g["cut"] = [f(p) for p in g["cut"]]
        g["sew"] = [f(p) for p in g["sew"]]
        g["lines"] = [(k, [f(p) for p in pts]) for k, pts in g["lines"]]
        g["circles"] = [(k, f(p), r) for k, p, r in g["circles"]]
        g["segs"] = [(k, f(a), f(b)) for k, a, b in g["segs"]]
        g["texts"] = [(f(p), t, s) for p, t, s in g["texts"]]
    return g


def collect(context, size_index=None):
    scene = context.scene
    sizes = scene.fh_sizes
    base = sizes[scene.fh_base_size] if len(sizes) else None
    size = sizes[size_index] if size_index is not None and len(sizes) else None
    out = []
    for panel in active_panels(scene):
        grade = None
        if size is not None and base is not None and size != base:
            from .grading import ratios, anchor_of
            d = ft.get_derived(panel)
            grade = (*ratios(panel, base, size), anchor_of(d.sew_xy()))
        g = piece_geometry(context, panel, grade)
        if g:
            if size is not None:
                g["texts"].append(((g["texts"][0][0][0], g["texts"][0][0][1] - 0.012), f"Size {size.name}", 0.006))
            out.append(g)
    return out


def _bounds(pieces):
    xs = [p[0] for g in pieces for p in g["cut"]]
    ys = [p[1] for g in pieces for p in g["cut"]]
    return min(xs), min(ys), max(xs), max(ys)


def write_svg(path, pieces, margin_mm=10):
    x0, y0, x1, y1 = _bounds(pieces)
    W = (x1 - x0) * 1000 + 2 * margin_mm
    H = (y1 - y0) * 1000 + 2 * margin_mm
    tx = lambda p: f"{(p[0] - x0) * 1000 + margin_mm:.2f},{(y1 - p[1]) * 1000 + margin_mm:.2f}"

    def stroke(kind):
        col, w, dash = STYLE[kind]
        return f'fill="none" stroke="{col}" stroke-width="{w}"' + (f' stroke-dasharray="{dash}"' if dash else "")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{H:.1f}mm" '
           f'viewBox="0 0 {W:.2f} {H:.2f}">',
           f'<!-- FashionHov pattern, 1:1 scale. Check the 10 cm test square after printing. -->',
           f'<rect x="{margin_mm / 2}" y="{margin_mm / 2}" width="100" height="100" {stroke("mark")}/>',
           f'<text x="{margin_mm / 2 + 2}" y="{margin_mm / 2 + 6}" font-size="4">10 cm test square</text>']
    for g in pieces:
        out.append(f'<g id="{g["name"]}">')
        out.append(f'<polygon points="{" ".join(tx(p) for p in g["cut"])}" {stroke("cut")}/>')
        out.append(f'<polygon points="{" ".join(tx(p) for p in g["sew"])}" {stroke("sew")}/>')
        for kind, pts in g["lines"]:
            out.append(f'<polyline points="{" ".join(tx(p) for p in pts)}" {stroke(kind)}/>')
        for kind, a, b in g["segs"]:
            out.append(f'<polyline points="{tx(a)} {tx(b)}" {stroke(kind)}/>')
        for kind, c, r in g["circles"]:
            x, y = tx(c).split(",")
            out.append(f'<circle cx="{x}" cy="{y}" r="{r * 1000:.2f}" {stroke(kind)}/>')
        for p, text, size in g["texts"]:
            x, y = tx(p).split(",")
            out.append(f'<text x="{x}" y="{y}" font-size="{size * 1000:.1f}" font-family="sans-serif">{text}</text>')
        out.append("</g>")
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def write_dxf(path, pieces):
    """Plain DXF R12 in millimetres; one layer per line type."""
    ent = []
    mm = lambda p: (p[0] * 1000, p[1] * 1000)

    def line(layer, a, b):
        a, b = mm(a), mm(b)
        ent.append(f"0\nLINE\n8\n{layer}\n10\n{a[0]:.3f}\n20\n{a[1]:.3f}\n30\n0\n11\n{b[0]:.3f}\n21\n{b[1]:.3f}\n31\n0")

    def poly(layer, pts, closed=False):
        seq = list(pts) + ([pts[0]] if closed else [])
        for a, b in zip(seq, seq[1:]):
            line(layer, a, b)
    for g in pieces:
        poly("CUT", g["cut"], True)
        poly("SEW", g["sew"], True)
        for kind, pts in g["lines"]:
            poly(kind.upper(), pts)
        for kind, a, b in g["segs"]:
            line(kind.upper(), a, b)
        for kind, c, r in g["circles"]:
            c = mm(c)
            ent.append(f"0\nCIRCLE\n8\nMARK\n10\n{c[0]:.3f}\n20\n{c[1]:.3f}\n30\n0\n40\n{r * 1000:.3f}")
        for p, text, size in g["texts"]:
            p = mm(p)
            ent.append(f"0\nTEXT\n8\nTEXT\n10\n{p[0]:.3f}\n20\n{p[1]:.3f}\n30\n0\n40\n{size * 1000:.2f}\n1\n{text}")
    with open(path, "w", encoding="ascii", errors="replace") as fh:
        fh.write("0\nSECTION\n2\nENTITIES\n" + "\n".join(ent) + "\n0\nENDSEC\n0\nEOF\n")


def _size_items(self, context):
    items = [('BASE', "Base (as drafted)", "")]
    if context and context.scene:
        items += [(str(i), s.name, "") for i, s in enumerate(context.scene.fh_sizes)]
    return items


class FH_OT_export_pattern(bpy.types.Operator, ExportHelper):
    """Export the flat pattern at real size (SVG to print, DXF for CAD / cutting machines)"""
    bl_idname = "fashionhov.export_pattern"
    bl_label = "Export Pattern"

    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(default="*.svg;*.dxf", options={'HIDDEN'})
    format: bpy.props.EnumProperty(name="Format", items=[('SVG', "SVG", "Print at 100% / plotter"),
                                                         ('DXF', "DXF", "CAD and cutting machines")])
    size: bpy.props.EnumProperty(name="Size", items=_size_items)
    all_sizes: bpy.props.BoolProperty(name="Every Size (one file each)")

    def check(self, context):
        ext = ".dxf" if self.format == 'DXF' else ".svg"
        if self.filename_ext != ext:
            self.filename_ext = ext
            self.filepath = os.path.splitext(self.filepath)[0] + ext
            return True
        return False

    def execute(self, context):
        sizes = context.scene.fh_sizes
        jobs = [(None, "")]
        if self.all_sizes and len(sizes):
            jobs = [(i, f"_{s.name}") for i, s in enumerate(sizes)]
        elif self.size != 'BASE':
            jobs = [(int(self.size), f"_{sizes[int(self.size)].name}")]
        root, ext = os.path.splitext(self.filepath)
        ext = ".dxf" if self.format == 'DXF' else ".svg"
        written = []
        for idx, suffix in jobs:
            pieces = collect(context, idx)
            if not pieces:
                self.report({'ERROR'}, "No panels to export")
                return {'CANCELLED'}
            path = root + suffix + ext
            (write_dxf if self.format == 'DXF' else write_svg)(path, pieces)
            written.append(os.path.basename(path))
        self.report({'INFO'}, "Exported " + ", ".join(written))
        return {'FINISHED'}


classes = (FH_OT_export_pattern,)
