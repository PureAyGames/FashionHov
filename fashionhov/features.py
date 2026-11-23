"""Panel features: darts, pleats, hems, hardware and zippers.

Stored as parameters on the panel object, never baked into its outline.
Every consumer (viewport, cloth mesh, sewing, export) asks get_derived(panel)
for the resulting geometry, so changing a pleat depth or moving a dart just
recomputes; nothing else you've done gets touched.

When a feature changes, the panel's cloth piece is rebuilt automatically
(debounced, so dragging a slider stays smooth).
"""

import bpy
from mathutils import Vector

from .core import derive as dv

HW_KINDS = [
    ('BUTTON_SHANK', "Jeans Button", "Shank (tack) button, like on a jeans waistband"),
    ('BUTTON', "Sew-on Button", "4-hole button"),
    ('RIVET', "Rivet", "Copper/brass rivet for pocket corners"),
    ('SNAP', "Snap", "Snap fastener"),
    ('GROMMET', "Grommet / Eyelet", "Metal ring for laces or drawcords"),
    ('BUTTONHOLE', "Buttonhole", "Stitched buttonhole (sized from the button size)"),
]
HW_SIZE = {'BUTTON_SHANK': 0.017, 'BUTTON': 0.015, 'RIVET': 0.009, 'SNAP': 0.012,
           'GROMMET': 0.010, 'BUTTONHOLE': 0.019}
FINISHES = [('BRASS', "Brass", ""), ('COPPER', "Copper", ""), ('NICKEL', "Nickel", ""),
            ('BLACK', "Black", ""), ('GUNMETAL', "Gunmetal", "")]
ZIP_STYLES = [('FLY', "Fly (jeans)", "Adds a fly extension to the panel automatically"),
              ('CENTERED', "Centred", "Zip in a seam, teeth hidden under both edges"),
              ('EXPOSED', "Exposed", "Teeth visible on the outside"),
              ('INVISIBLE', "Invisible", "Concealed zip; only the pull shows")]

_cache = {}
_pending = set()


def _changed(self, context):
    panel = self.id_data
    if isinstance(panel, bpy.types.Object):
        request_rebuild(panel)


def _len(name, d, lo=0.001, hi=1.0, desc=""):
    return bpy.props.FloatProperty(name=name, default=d, min=lo, max=hi, subtype='DISTANCE',
                                   unit='LENGTH', update=_changed, description=desc)


class FHDart(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty()
    va: bpy.props.IntProperty()
    vb: bpy.props.IntProperty()
    t: bpy.props.FloatProperty(name="Position", min=0.02, max=0.98, default=0.5, subtype='FACTOR', update=_changed)
    width: _len("Width", 0.025, 0.002, 0.2, "Dart intake at the edge")
    length: _len("Length", 0.10, 0.01, 0.6, "From the edge to the point")
    angle: bpy.props.FloatProperty(name="Angle", default=0.0, min=-60, max=60, update=_changed,
                                   description="Tilt from straight-in (degrees)")


class FHPleat(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty()
    va: bpy.props.IntProperty()
    vb: bpy.props.IntProperty()
    t: bpy.props.FloatProperty(name="Position", min=0.02, max=0.98, default=0.5, subtype='FACTOR', update=_changed)
    depth: _len("Depth", 0.02, 0.003, 0.15, "How deep the fold is. Intake = 2x depth (4x for box/inverted)")
    kind: bpy.props.EnumProperty(name="Type", update=_changed, items=[
        ('KNIFE', "Knife", "One fold"), ('BOX', "Box", "Two folds facing away"),
        ('INVERTED', "Inverted", "Two folds meeting on the outside")])
    stitch: _len("Stitched Down", 0.04, 0.0, 0.8, "How far the pleat is stitched closed from the edge")


class FHHem(bpy.types.PropertyGroup):
    va: bpy.props.IntProperty()
    vb: bpy.props.IntProperty()
    width: _len("Hem Width", 0.02, 0.003, 0.15, "Finished hem depth")
    fold: bpy.props.EnumProperty(name="Fold", update=_changed, items=[
        ('DOUBLE', "Double Fold", "Turned twice, raw edge hidden (jeans, chinos)"),
        ('SINGLE', "Single Fold", "Turned once (edge serged / pinked)"),
        ('ROLLED', "Rolled", "Tiny rolled hem (shirts, chiffon)")])
    turn: _len("Turn Under", 0.008, 0.002, 0.05, "Extra fabric turned under on a double fold")
    topstitch: bpy.props.EnumProperty(name="Topstitch", default='SINGLE', update=_changed, items=[
        ('NONE', "None", ""), ('SINGLE', "Single", ""), ('DOUBLE', "Double", "")])


class FHHardware(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty()
    kind: bpy.props.EnumProperty(name="Type", items=HW_KINDS + [('ZIPPER', "Zipper", "")], update=_changed)
    x: bpy.props.FloatProperty(update=_changed)    # panel-local, before pleat spreading
    y: bpy.props.FloatProperty(update=_changed)
    size: _len("Size", 0.017, 0.003, 0.08, "Diameter (buttons, rivets...) or length (buttonholes)")
    angle: bpy.props.FloatProperty(name="Angle", default=0.0, update=_changed, subtype='ANGLE')
    finish: bpy.props.EnumProperty(name="Finish", items=FINISHES, update=_changed)
    # zippers
    va: bpy.props.IntProperty()
    vb: bpy.props.IntProperty()
    start: _len("Start", 0.0, 0.0, 2.0, "Distance along the edge where the zip starts")
    length: _len("Zip Length", 0.17, 0.03, 1.5, "")
    style: bpy.props.EnumProperty(name="Style", items=ZIP_STYLES, update=_changed)
    fly_width: _len("Fly Width", 0.035, 0.015, 0.08, "How far the fly extension sticks out")
    pull_at_start: bpy.props.BoolProperty(name="Pull at Start", default=True, update=_changed)


class FHFeatures(bpy.types.PropertyGroup):
    darts: bpy.props.CollectionProperty(type=FHDart)
    pleats: bpy.props.CollectionProperty(type=FHPleat)
    hems: bpy.props.CollectionProperty(type=FHHem)
    hardware: bpy.props.CollectionProperty(type=FHHardware)
    next_id: bpy.props.IntProperty(default=1)
    seam_allowance: bpy.props.FloatProperty(
        name="Seam Allowance", default=-1.0, min=-1.0, max=0.1, subtype='DISTANCE', unit='LENGTH',
        update=_changed, description="-1 = use the project default")
    active_dart: bpy.props.IntProperty()
    active_pleat: bpy.props.IntProperty()
    active_hem: bpy.props.IntProperty()
    active_hw: bpy.props.IntProperty()


def new_id(panel):
    f = panel.fh_features
    i = f.next_id
    f.next_id += 1
    return i


# ---------- derived geometry ----------

def base_outline(panel):
    from .sewing import outline_vids
    return outline_vids(panel)


def _key(panel, base):
    f = panel.fh_features
    parts = [tuple(base)]
    for coll, fields in ((f.darts, ("id", "va", "vb", "t", "width", "length", "angle")),
                         (f.pleats, ("id", "va", "vb", "t", "depth", "kind", "stitch")),
                         (f.hardware, ("id", "kind", "va", "vb", "start", "length", "style", "fly_width"))):
        parts.append(tuple(tuple(getattr(x, k) for k in fields) for x in coll))
    return hash(tuple(parts))


def get_derived(panel):
    """Derived geometry of a panel in world XY (cached)."""
    base = base_outline(panel)
    if len(base) < 3:
        return None
    key = _key(panel, base)
    hit = _cache.get(panel.name)
    if hit and hit[0] == key:
        return hit[1]
    f = panel.fh_features
    vids = {v for v, _ in base}
    darts = [dict(id=d.id, va=d.va, vb=d.vb, t=d.t, width=d.width, length=d.length, angle=d.angle)
             for d in f.darts if d.va in vids and d.vb in vids]
    pleats = [dict(id=p.id, va=p.va, vb=p.vb, t=p.t, depth=p.depth, kind=p.kind, stitch=p.stitch)
              for p in f.pleats if p.va in vids and p.vb in vids]
    flies = [dict(id=h.id, va=h.va, vb=h.vb, start=h.start, length=h.length, width=h.fly_width)
             for h in f.hardware if h.kind == 'ZIPPER' and h.style == 'FLY' and h.va in vids and h.vb in vids]
    try:
        d = dv.derive(base, darts, pleats, flies)
    except Exception as e:          # never let a bad feature take down drawing
        print("FashionHov: feature error on", panel.name, e)
        d = dv.derive(base)
    _cache[panel.name] = (key, d)
    return d


def hardware_world(panel, hw):
    """World XY of a point hardware item, after pleat spreading."""
    p = panel.matrix_world @ Vector((hw.x, hw.y, 0))
    d = get_derived(panel)
    return d.map_point((p.x, p.y)) if d else (p.x, p.y)


def set_hardware_world(panel, hw, xy):
    d = get_derived(panel)
    base = d.unmap_point(xy) if d else xy
    local = panel.matrix_world.inverted() @ Vector((base[0], base[1], panel.matrix_world.translation.z))
    hw.x, hw.y = local.x, local.y


def zipper_path(panel, hw):
    """Sew-line points covered by a zipper, from start to start+length."""
    d = get_derived(panel)
    if not d:
        return []
    pts, jumps = d.chain(hw.va, hw.vb)
    if len(pts) < 2:
        return []
    out = []
    acc = 0.0
    a, b = hw.start, hw.start + hw.length
    out.append(dv.point_at_arc(pts, a)[0])
    for p, q in zip(pts, pts[1:]):
        L = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
        if a < acc + L < b:
            out.append(q)
        acc += L
    out.append(dv.point_at_arc(pts, b)[0])
    return out


def hems_by_edge(panel):
    """{base edge start vid: hem} for every base edge a hem covers."""
    base = base_outline(panel)
    ids = [v for v, _ in base]
    out = {}
    for h in panel.fh_features.hems:
        if h.va not in ids or h.vb not in ids:
            continue
        i, j = ids.index(h.va), ids.index(h.vb)
        while i != j:
            out[ids[i]] = h
            i = (i + 1) % len(ids)
    return out


def hem_allowance(h):
    if h.fold == 'DOUBLE':
        return h.width + h.turn
    if h.fold == 'ROLLED':
        return max(h.width, 0.003) * 2
    return h.width


def seam_allowance(panel, scene):
    sa = panel.fh_features.seam_allowance
    return sa if sa >= 0 else scene.fh_thread.seam_allowance


# ---------- auto rebuild ----------

def invalidate(panel):
    _cache.pop(panel.name, None)


def request_rebuild(panel):
    invalidate(panel)
    _pending.add(panel.name)
    if not bpy.app.timers.is_registered(_flush):
        bpy.app.timers.register(_flush, first_interval=0.35)


def _flush():
    flush_now(bpy.context)
    return None


def flush_now(context):
    from .cloth import build_cloth
    from . import details
    scene = context.scene
    names = list(_pending)
    _pending.clear()
    touched = False
    for name in names:
        panel = bpy.data.objects.get(name)
        if not panel:
            continue
        invalidate(panel)
        piece = next((o for o in scene.objects if o.get("fh_cloth_source") == name), None)
        if piece:
            build_cloth(context, panel, piece.get("fh_spacing", scene.fh.cloth_spacing))
            touched = True
    if touched and bpy.data.objects.get("FH Garment"):
        scene["fh_garment_stale"] = True
    try:
        details.rebuild(context)
    except Exception as e:
        print("FashionHov: details rebuild failed:", e)
    for area in (context.screen.areas if context.screen else []):
        area.tag_redraw()


classes = ()


def register():
    for c in (FHDart, FHPleat, FHHem, FHHardware, FHFeatures):
        bpy.utils.register_class(c)
    bpy.types.Object.fh_features = bpy.props.PointerProperty(type=FHFeatures)


def unregister():
    if bpy.app.timers.is_registered(_flush):
        bpy.app.timers.unregister(_flush)
    del bpy.types.Object.fh_features
    for c in reversed((FHDart, FHPleat, FHHem, FHHardware, FHFeatures)):
        bpy.utils.unregister_class(c)
