"""Seams: pairs of panel edges that get sewn together.

A seam is stored once and drawn everywhere it applies, with the same colour
and number: on the flat 2D panels AND on the 3D cloth pieces. You can create
it from either side:
  * 2D: Tab into Edit Mode on one or two panels, select the two edge runs, Sew.
  * 3D: same thing on the cloth pieces arranged around the avatar.

Seam ends are tied to panel vertices through a persistent integer id
("fh_vid"), so adding points to a panel later doesn't break existing seams.
"""

import colorsys
import math
import bpy
import bmesh

from .core import geometry as geo

VID = "fh_vid"


# ---------- persistent vertex ids ----------

def ensure_vids_bm(obj, bm):
    layer = bm.verts.layers.int.get(VID) or bm.verts.layers.int.new(VID)
    nxt = obj.get("fh_vid_next", 1)
    seen = set()
    for v in bm.verts:
        if v[layer] <= 0 or v[layer] in seen:
            v[layer] = nxt
            nxt += 1
        seen.add(v[layer])
    obj["fh_vid_next"] = nxt
    return layer


def ensure_vids(obj):
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        ensure_vids_bm(obj, bm)
        bmesh.update_edit_mesh(obj.data)
        return
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    ensure_vids_bm(obj, bm)
    bm.to_mesh(obj.data)
    bm.free()


def outline_vids(obj):
    """Panel outline as [(vid, world_xy)] in loop (counter-clockwise) order."""
    mw = obj.matrix_world
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        layer = bm.verts.layers.int.get(VID)
        if not bm.faces or layer is None:
            return []
        return [(v[layer], tuple((mw @ v.co).xy)) for v in bm.faces[0].verts]
    me = obj.data
    attr = me.attributes.get(VID)
    if not me.polygons or attr is None:
        return []
    return [(attr.data[i].value, tuple((mw @ me.vertices[i].co).xy)) for i in me.polygons[0].vertices]


class Poly(list):
    """A polyline whose segments listed in .jumps have zero sewn length
    (a closed dart opening, folded pleat intake)."""

    def __init__(self, pts=(), jumps=()):
        super().__init__(pts)
        self.jumps = set(jumps)


def chain(obj, v0, v1):
    """Sewing-line points (world XY) from vid v0 forward (CCW) to vid v1, after
    darts and pleats are applied."""
    from .features import get_derived
    d = get_derived(obj)
    if d is None:
        return Poly()
    pts, jumps = d.chain(v0, v1)
    return Poly(pts, jumps)


def polyline_length(pts):
    j = getattr(pts, "jumps", ())
    return sum(math.dist(a, b) for i, (a, b) in enumerate(zip(pts, pts[1:])) if i not in j)


# ---------- seam data ----------

def _details_changed(context):
    from . import details
    details.request(context)


def _palette(i):
    r, g, b = colorsys.hsv_to_rgb((i * 0.618034) % 1.0, 0.75, 1.0)
    return (r, g, b, 1.0)


class FHSeamLayer(bpy.types.PropertyGroup):
    """An extra layer sewn into a seam (e.g. a lining, a facing, a label)."""
    obj: bpy.props.PointerProperty(type=bpy.types.Object)
    v0: bpy.props.IntProperty()
    v1: bpy.props.IntProperty()
    flip: bpy.props.BoolProperty(name="Flip", default=False,
                                 description="Run this layer the other way along the seam")


class FHSeam(bpy.types.PropertyGroup):
    number: bpy.props.IntProperty()
    layers: bpy.props.CollectionProperty(type=FHSeamLayer)
    color: bpy.props.FloatVectorProperty(subtype='COLOR', size=4, min=0, max=1, default=(1, 0.5, 0, 1))
    a_obj: bpy.props.PointerProperty(type=bpy.types.Object)
    a_v0: bpy.props.IntProperty()
    a_v1: bpy.props.IntProperty()
    b_obj: bpy.props.PointerProperty(type=bpy.types.Object)
    b_v0: bpy.props.IntProperty()
    b_v1: bpy.props.IntProperty()
    topstitch: bpy.props.EnumProperty(
        name="Topstitch", default='NONE', update=lambda s, c: _details_changed(c), items=[
            ('NONE', "None", ""), ('SINGLE', "Single", ""), ('DOUBLE', "Double", "Two rows, like jeans")])
    ts_side: bpy.props.EnumProperty(
        name="Side", default='A', update=lambda s, c: _details_changed(c),
        items=[('A', "First Piece", "Seam allowance pressed toward the first piece"),
               ('B', "Second Piece", ""), ('BOTH', "Both", "Stitch on both sides")])
    ts_dist: bpy.props.FloatProperty(name="From Seam", default=0.002, min=0.0005, max=0.03, subtype='DISTANCE',
                                     unit='LENGTH', update=lambda s, c: _details_changed(c))
    ts_gap: bpy.props.FloatProperty(name="Row Gap", default=0.0064, min=0.002, max=0.03, subtype='DISTANCE',
                                    unit='LENGTH', update=lambda s, c: _details_changed(c))
    flip: bpy.props.BoolProperty(
        name="Flip", default=True,
        description="Which way the two edges line up. Most seams join edges running in opposite "
                    "directions; flip if the stitch lines cross over each other")


def seam_chains(seam):
    a = chain(seam.a_obj, seam.a_v0, seam.a_v1) if seam.a_obj else []
    b = chain(seam.b_obj, seam.b_v0, seam.b_v1) if seam.b_obj else []
    return a, b


def seam_ok(seam):
    a, b = seam_chains(seam)
    return len(a) >= 2 and len(b) >= 2


def add_seam(scene, a, b):
    """a, b = (panel_obj, start_vid, end_vid)."""
    s = scene.fh_seams.add()
    s.number = max([x.number for x in scene.fh_seams] + [0]) + 1
    s.color = _palette(s.number)
    s.a_obj, s.a_v0, s.a_v1 = a
    s.b_obj, s.b_v0, s.b_v1 = b
    return s


def arc_params(pts):
    """Cumulative sewn arc length of each point, normalised to 0..1."""
    j = getattr(pts, "jumps", ())
    acc = [0.0]
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        acc.append(acc[-1] + (0.0 if i in j else math.dist(a, b)))
    total = acc[-1] or 1.0
    return [x / total for x in acc]


def point_at(pts, t):
    """Point at normalised arc length t along polyline pts."""
    ps = arc_params(pts)
    for i in range(len(pts) - 1):
        if t <= ps[i + 1] or i == len(pts) - 2:
            span = ps[i + 1] - ps[i]
            u = 0.0 if span == 0 else min(max((t - ps[i]) / span, 0.0), 1.0)
            a, b = pts[i], pts[i + 1]
            return tuple(a[k] + (b[k] - a[k]) * u for k in range(len(a)))
    return pts[-1]


def sample(pts, n):
    """n points evenly spaced by sewn arc length."""
    return [point_at(pts, k / (n - 1)) for k in range(n)] if n > 1 else [pts[0]]


# ---------- finding selected edge runs ----------

def runs_in_panel(obj):
    """Selected outline edge runs of a panel in Edit Mode, as (start_vid, end_vid)."""
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    layer = ensure_vids_bm(obj, bm)
    bmesh.update_edit_mesh(obj.data)
    if not bm.faces:
        return []
    loop = bm.faces[0].verts[:]
    n = len(loop)
    sel = []
    for i in range(n):
        e = bm.edges.get((loop[i], loop[(i + 1) % n]))
        sel.append(bool(e and e.select))
    if all(sel):
        return [(loop[0][layer], loop[0][layer])]   # whole outline; caller rejects
    if not any(sel):
        return []
    start = sel.index(False) + 1          # begin scanning right after an unselected edge
    runs, cur = [], None
    for k in range(n):
        i = (start + k) % n
        if sel[i]:
            if cur is None:
                cur = i
        elif cur is not None:
            runs.append((cur, i))         # edges cur..i-1 -> verts cur..i
            cur = None
    if cur is not None:
        runs.append((cur, (start + n) % n))
    return [(loop[a][layer], loop[b][layer]) for a, b in runs]


def runs_in_piece(obj):
    """Selected boundary edge runs on a 3D cloth piece, mapped back to its panel's vids."""
    panel = bpy.data.objects.get(obj.get("fh_cloth_source", ""))
    if panel is None:
        return []
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.get("Pattern")
    if uv is None:
        return []
    bnd = [e for e in bm.edges if e.select and e.is_boundary]
    if not bnd:
        return []
    # pattern xy of each vertex (UV holds pattern coords in metres, + slot offset)
    ox, oy = obj.get("fh_uv_off", (0.0, 0.0))
    pxy = {}
    for f in bm.faces:
        for l in f.loops:
            pxy[l.vert] = (l[uv].uv[0] - ox, l[uv].uv[1] - oy)
    # connected runs
    adj = {}
    for e in bnd:
        a, b = e.verts
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen, runs = set(), []
    for v in adj:
        if v in seen:
            continue
        comp, stack = [], [v]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack += adj[x]
        ends = [x for x in comp if len(adj[x]) == 1]
        if len(ends) != 2:
            continue
        mid = comp[len(comp) // 2]
        runs.append((pxy[ends[0]], pxy[ends[1]], pxy[mid]))

    from .features import get_derived
    d = get_derived(panel)
    # pieces' pattern UVs are in derived (pleat-spread) space; seam ends live on base vids
    sew = [(p.vid, p.xy) for p in d.sew if p.vid is not None]
    ids = [v for v, _ in sew]
    pts = [p for _, p in sew]
    out = []
    for e0, e1, mid in runs:
        i0 = min(range(len(pts)), key=lambda i: math.dist(pts[i], e0))
        i1 = min(range(len(pts)), key=lambda i: math.dist(pts[i], e1))
        if i0 == i1:
            continue
        fwd = chain(panel, ids[i0], ids[i1])
        on_fwd = min(geo.dist_to_segment(mid, a, b) for a, b in zip(fwd, fwd[1:])) < 0.005
        out.append((panel, ids[i0], ids[i1]) if on_fwd else (panel, ids[i1], ids[i0]))
    return out


# ---------- operators ----------

class FH_OT_sew(bpy.types.Operator):
    """Sew two selected edge runs together. Works in 2D (panels) or 3D (cloth pieces): in Edit Mode, select two runs of outline edges, on one or two pieces, then Sew"""
    bl_idname = "fashionhov.sew"
    bl_label = "Sew Selected Edges"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        runs = []
        for obj in context.objects_in_mode:
            if obj.get("fh_panel"):
                runs += [(obj, a, b) for a, b in runs_in_panel(obj) if a != b]
            elif obj.get("fh_cloth_source"):
                runs += runs_in_piece(obj)
        if len(runs) != 2:
            self.report({'WARNING'}, f"Select exactly 2 runs of outline edges (found {len(runs)}). "
                                     "Ctrl+click in Edit Mode selects a run between two points")
            return {'CANCELLED'}
        s = add_seam(context.scene, runs[0], runs[1])
        a, b = seam_chains(s)
        la, lb = polyline_length(a), polyline_length(b)
        from .util import fmt_len
        msg = f"Seam #{s.number}: {fmt_len(context, la)} ↔ {fmt_len(context, lb)}"
        if abs(la - lb) > 0.01:
            msg += f"  (differ by {fmt_len(context, abs(la - lb))}: the longer side will be eased in)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class FH_OT_seam_add_layer(bpy.types.Operator):
    """Sew another layer into the selected seam: in Edit Mode, select one run of edges on another
    panel or piece (lining, facing, label...) and press this"""
    bl_idname = "fashionhov.seam_add_layer"
    bl_label = "Add Layer to Seam"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sc = context.scene
        return context.mode == 'EDIT_MESH' and 0 <= sc.fh_seam_index < len(sc.fh_seams)

    def execute(self, context):
        runs = []
        for obj in context.objects_in_mode:
            if obj.get("fh_panel"):
                runs += [(obj, a, b) for a, b in runs_in_panel(obj) if a != b]
            elif obj.get("fh_cloth_source"):
                runs += runs_in_piece(obj)
        if len(runs) != 1:
            self.report({'WARNING'}, f"Select exactly 1 run of edges (found {len(runs)})")
            return {'CANCELLED'}
        seam = context.scene.fh_seams[context.scene.fh_seam_index]
        layer = seam.layers.add()
        layer.obj, layer.v0, layer.v1 = runs[0]
        self.report({'INFO'}, f"Seam #{seam.number} now sews {2 + len(seam.layers)} layers")
        return {'FINISHED'}


class FH_OT_seam_remove(bpy.types.Operator):
    """Delete this seam"""
    bl_idname = "fashionhov.seam_remove"
    bl_label = "Remove Seam"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        context.scene.fh_seams.remove(self.index)
        return {'FINISHED'}


class FH_UL_seams(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        from .util import fmt_len
        row = layout.row(align=True)
        row.prop(item, "color", text="", emboss=True)
        if not seam_ok(item):
            row.label(text=f"#{item.number} broken (panel changed?)", icon='ERROR')
        else:
            a, b = seam_chains(item)
            extra = f" +{len(item.layers)} layer{'s' if len(item.layers) > 1 else ''}" if len(item.layers) else ""
            row.label(text=f"#{item.number} {item.a_obj.name} ↔ {item.b_obj.name}{extra}  "
                           f"{fmt_len(context, polyline_length(a))}/{fmt_len(context, polyline_length(b))}")
        row.prop(item, "flip", text="", icon='ARROW_LEFTRIGHT')
        row.operator("fashionhov.seam_remove", text="", icon='X').index = index


classes = (FH_OT_sew, FH_OT_seam_add_layer, FH_OT_seam_remove, FH_UL_seams)


def register():
    bpy.utils.register_class(FHSeamLayer)
    bpy.utils.register_class(FHSeam)
    bpy.types.Scene.fh_seams = bpy.props.CollectionProperty(type=FHSeam)
    bpy.types.Scene.fh_seam_index = bpy.props.IntProperty()


def unregister():
    del bpy.types.Scene.fh_seam_index
    del bpy.types.Scene.fh_seams
    bpy.utils.unregister_class(FHSeam)
    bpy.utils.unregister_class(FHSeamLayer)
