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
        for attr in ("piece", "facing", "bag", "bag_front", "child"):
            child = getattr(self, attr, None)
            if child:
                request_rebuild(child)


def _len(name, d, lo=0.001, hi=1.0, desc=""):
    return bpy.props.FloatProperty(name=name, default=d, min=lo, max=hi, subtype='DISTANCE',
                                   unit='LENGTH', update=_changed, description=desc)


def _en(desc="Turn this detail off without deleting it"):
    return bpy.props.BoolProperty(name="On", default=True, update=_changed, description=desc)


class FHDart(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty()
    enabled: _en()
    mode: bpy.props.EnumProperty(name="Type", update=_changed, items=[
        ('EDGE', "Edge Dart", "Starts at an edge"),
        ('INNER', "Fisheye Dart", "Inside the panel, pointed at both ends")])
    x: bpy.props.FloatProperty(update=_changed)    # fisheye centre, panel-local
    y: bpy.props.FloatProperty(update=_changed)
    down: bpy.props.FloatProperty(name="Lower Length", default=0.08, min=0.01, max=0.6, subtype='DISTANCE',
                                  unit='LENGTH', update=_changed, description="Fisheye: centre to bottom point")
    va: bpy.props.IntProperty()
    vb: bpy.props.IntProperty()
    t: bpy.props.FloatProperty(name="Position", min=0.02, max=0.98, default=0.5, subtype='FACTOR', update=_changed)
    width: _len("Width", 0.025, 0.002, 0.2, "Dart intake at the edge")
    length: _len("Length", 0.10, 0.01, 0.6, "From the edge to the point")
    angle: bpy.props.FloatProperty(name="Angle", default=0.0, min=-60, max=60, update=_changed,
                                   description="Tilt from straight-in (degrees)")


class FHPleat(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty()
    enabled: _en()
    taper: bpy.props.FloatProperty(
        name="Taper To", default=0.0, min=0.0, max=2.0, subtype='DISTANCE', unit='LENGTH', update=_changed,
        description="0 = pleat runs the full length. Otherwise it narrows to nothing this far from the edge "
                    "(like trouser front pleats)")
    va: bpy.props.IntProperty()
    vb: bpy.props.IntProperty()
    t: bpy.props.FloatProperty(name="Position", min=0.02, max=0.98, default=0.5, subtype='FACTOR', update=_changed)
    depth: _len("Depth", 0.02, 0.003, 0.15, "How deep the fold is. Intake = 2x depth (4x for box/inverted)")
    kind: bpy.props.EnumProperty(name="Type", update=_changed, items=[
        ('KNIFE', "Knife", "One fold"), ('BOX', "Box", "Two folds facing away"),
        ('INVERTED', "Inverted", "Two folds meeting on the outside")])
    stitch: _len("Stitched Down", 0.04, 0.0, 0.8, "How far the pleat is stitched closed from the edge")


class FHHem(bpy.types.PropertyGroup):
    enabled: _en()
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
    enabled: _en()
    child: bpy.props.PointerProperty(type=bpy.types.Object, description="Fly shield piece made for this zipper")
    shield_sim: bpy.props.BoolProperty(name="Simulate Shield", default=True, update=_changed,
                                       description="Put the fly shield behind the fly in the simulation")
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


POCKET_KINDS = [
    ('JEANS', "Jeans Back Pocket", "Pointed patch pocket, double topstitch, rivets"),
    ('PATCH', "Patch Pocket", "Square patch pocket"),
    ('COIN', "Coin Pocket", "Small patch pocket"),
    ('SCOOP', "Front Scoop Pocket", "Jeans/chino front pocket: curved opening + facing + bag pieces"),
]


class FHPocket(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty()
    enabled: _en()
    kind: bpy.props.EnumProperty(name="Type", items=POCKET_KINDS)
    piece: bpy.props.PointerProperty(type=bpy.types.Object, description="The pocket panel (edit it like any panel)")
    facing: bpy.props.PointerProperty(type=bpy.types.Object, description="Scoop: facing / yoke panel")
    bag: bpy.props.PointerProperty(type=bpy.types.Object, description="Scoop: pocket bag panel")
    bag_front: bpy.props.PointerProperty(type=bpy.types.Object,
                                         description="Scoop: front layer of the bag (simulation only)")
    attach_va: bpy.props.IntProperty()
    attach_vb: bpy.props.IntProperty()
    in_sim: bpy.props.BoolProperty(name="Simulate", default=True, update=_changed,
                                   description="Include this pocket (and its facing / bag) in the simulation. "
                                               "Turn off for faster fit checks")
    topstitch: bpy.props.EnumProperty(name="Topstitch", default='DOUBLE', update=_changed, items=[
        ('NONE', "None", ""), ('SINGLE', "Single", ""), ('DOUBLE', "Double", "")])
    # scoop
    corner: bpy.props.IntProperty()
    width: _len("Opening A", 0.11, 0.02, 0.4, "Opening length along the edge before the corner")
    depth: _len("Opening B", 0.07, 0.02, 0.4, "Opening length along the edge after the corner")
    curve: bpy.props.FloatProperty(name="Curve", default=0.35, min=-0.5, max=1.5, update=_changed,
                                   description="0 = straight slant, higher = deeper scoop")


def _show_changed(self, context):
    refresh_all(context)


class FHShow(bpy.types.PropertyGroup):
    """Scene-wide modifier toggles: hide a whole category without deleting anything."""
    darts: bpy.props.BoolProperty(name="Darts", default=True, update=_show_changed)
    pleats: bpy.props.BoolProperty(name="Pleats", default=True, update=_show_changed)
    hems: bpy.props.BoolProperty(name="Hems", default=True, update=_show_changed)
    zippers: bpy.props.BoolProperty(name="Zippers", default=True, update=_show_changed)
    hardware: bpy.props.BoolProperty(name="Hardware", default=True, update=_show_changed)
    pockets: bpy.props.BoolProperty(name="Pockets", default=True, update=_show_changed)


class FHFeatures(bpy.types.PropertyGroup):
    pockets: bpy.props.CollectionProperty(type=FHPocket)
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


def show(scene):
    return getattr(scene, "fh_show", None)


def on(item, category, scene=None):
    """Is this feature active (its own toggle AND its category toggle)?"""
    sh = show(scene or bpy.context.scene)
    return bool(item.enabled) and (sh is None or getattr(sh, category))


def hw_category(hw):
    return "zippers" if hw.kind == 'ZIPPER' else "hardware"


def owner_of(panel):
    """(parent panel, feature item) for a child panel made by a pocket / fly, else (None, None)."""
    parent = bpy.data.objects.get(panel.get("fh_feature_of", "")) if panel.get("fh_feature_of") else None
    if parent is None:
        return None, None
    fid = panel.get("fh_feature_id")
    for x in parent.fh_features.pockets:
        if x.id == fid:
            return parent, x
    for x in parent.fh_features.hardware:
        if x.id == fid:
            return parent, x
    return parent, None


def panel_active(panel, scene=None):
    """False for child panels whose pocket / zipper is switched off (or deleted)."""
    if not panel.get("fh_feature_of"):
        return True
    parent, item = owner_of(panel)
    if parent is None or item is None:
        return False
    cat = "pockets" if hasattr(item, "attach_va") else hw_category(item)
    return on(item, cat, scene) and panel_active(parent, scene)


def panel_simulated(panel, scene=None):
    if not panel_active(panel, scene):
        return False
    if not panel.get("fh_feature_of"):
        return True
    _, item = owner_of(panel)
    if item is None:
        return False
    if hasattr(item, "attach_va"):
        return bool(item.in_sim)
    return bool(getattr(item, "shield_sim", False))


def uv_offset(panel):
    """Child panels sit on top of their parent in pattern space, so their cloth UVs
    are moved to their own slot (100 m apart) to keep surface lookups unambiguous."""
    return (100.0 * panel.get("fh_uv_slot", 0), 0.0)


def _key(panel, base):
    f = panel.fh_features
    sh = show(bpy.context.scene)
    parts = [tuple(base), tuple(getattr(sh, k) for k in ("darts", "pleats", "zippers", "pockets")) if sh else ()]
    for coll, fields in ((f.darts, ("id", "enabled", "mode", "va", "vb", "t", "width", "length", "angle",
                                    "x", "y", "down")),
                         (f.pleats, ("id", "enabled", "va", "vb", "t", "depth", "kind", "stitch", "taper")),
                         (f.hardware, ("id", "enabled", "kind", "va", "vb", "start", "length", "style", "fly_width")),
                         (f.pockets, ("id", "enabled", "kind", "corner", "width", "depth", "curve"))):
        parts.append(tuple(tuple(getattr(x, k) for k in fields) for x in coll))
    for x in f.pockets:
        if x.piece and x.kind != 'SCOOP':
            parts.append((tuple(x.piece.matrix_world.translation), tuple(base_outline(x.piece))))
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
    sc = bpy.context.scene
    vids = {v for v, _ in base}
    mw = panel.matrix_world
    darts = [dict(id=d.id, va=d.va, vb=d.vb, t=d.t, width=d.width, length=d.length, angle=d.angle)
             for d in f.darts if d.mode == 'EDGE' and on(d, "darts", sc) and d.va in vids and d.vb in vids]
    inner = [dict(id=d.id, c=tuple((mw @ Vector((d.x, d.y, 0))).xy), width=d.width, up=d.length,
                  down=d.down, angle=d.angle)
             for d in f.darts if d.mode == 'INNER' and on(d, "darts", sc)]
    pleats = [dict(id=p.id, va=p.va, vb=p.vb, t=p.t, depth=p.depth, kind=p.kind, stitch=p.stitch, taper=p.taper)
              for p in f.pleats if on(p, "pleats", sc) and p.va in vids and p.vb in vids]
    flies = [dict(id=h.id, va=h.va, vb=h.vb, start=h.start, length=h.length, width=h.fly_width)
             for h in f.hardware if h.kind == 'ZIPPER' and h.style == 'FLY' and on(h, "zippers", sc)
             and h.va in vids and h.vb in vids]
    scoops = [dict(id=x.id, corner=x.corner, width=x.width, depth=x.depth, curve=x.curve)
              for x in f.pockets if x.kind == 'SCOOP' and on(x, "pockets", sc) and x.corner in vids]
    try:
        d = dv.derive(base, darts, pleats, flies, inner, scoops)
    except Exception as e:          # never let a bad feature take down drawing
        print("FashionHov: feature error on", panel.name, e)
        d = dv.derive(base)
    # where patch pockets sit on this panel: drawn on the pattern, and built into
    # the cloth mesh so the pocket has vertices to be sewn onto
    for x in f.pockets:
        if x.kind != 'SCOOP' and x.piece and on(x, "pockets", sc):
            child = base_outline(x.piece)
            if len(child) >= 3:
                pts = [p for _, p in child]
                d.lines.append({"kind": "pocket_place", "id": x.id, "pts": pts + [pts[0]]})
    _cache[panel.name] = (key, d)
    return d


def set_local_point(panel, item, xy):
    """Store a world XY (as seen, after pleat spreading) into item.x / item.y."""
    set_hardware_world(panel, item, xy)


def local_point_world(panel, item):
    return hardware_world(panel, item)


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
        if not on(h, "hems") or h.va not in ids or h.vb not in ids:
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

def sync_children(scene):
    """Hide child panels (and their cloth pieces) whose pocket / zipper is switched off."""
    for o in scene.objects:
        src = o
        if o.get("fh_cloth_source"):
            src = bpy.data.objects.get(o["fh_cloth_source"])
            if src is None:
                continue
        if not src.get("fh_feature_of"):
            continue
        hide = not panel_active(src, scene)
        if o.get("fh_cloth_source"):
            hide = hide or not panel_simulated(src, scene)
        elif src.get("fh_sim_only"):
            hide = True                  # simulation-only layer: not part of the paper pattern
        try:
            if o.hide_get() != hide:
                o.hide_set(hide)
        except RuntimeError:
            pass


def refresh_all(context):
    from .util import panels
    for p in panels(context.scene):
        request_rebuild(p)

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
    from . import pockets
    for name in list(names):          # parents first: keep facing / bag / shield matched to them
        panel = bpy.data.objects.get(name)
        if panel and not panel.get("fh_feature_of"):
            before = {o.name for o in scene.objects if o.get("fh_feature_of") == name}
            pockets.regenerate(context, panel)
            names += [n for n in before if n not in names]
    sync_children(scene)
    for name in names:
        panel = bpy.data.objects.get(name)
        if not panel:
            continue
        invalidate(panel)
        piece = next((o for o in scene.objects if o.get("fh_cloth_source") == name), None)
        if piece is None and panel.get("fh_feature_of") and panel_simulated(panel, scene):
            parent = bpy.data.objects.get(panel["fh_feature_of"])
            ppiece = next((o for o in scene.objects if o.get("fh_cloth_source") == parent.name), None) if parent else None
            if ppiece:   # parent already has cloth: give the new pocket cloth too
                build_cloth(context, panel, ppiece.get("fh_spacing", scene.fh.cloth_spacing))
                touched = True
                continue
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


_ours = set()      # meshes we just changed ourselves (don't react to our own edits)


def mark_ours(obj):
    _ours.add(obj.name)


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    """You reshaped or moved a panel: re-derive it, rebuild its cloth and keep its
    pocket facing / bag / fly shield matched. No button needed."""
    for u in depsgraph.updates:
        obj = u.id.original if hasattr(u.id, "original") else u.id
        if not isinstance(obj, bpy.types.Object) or not obj.get("fh_panel") or obj.get("fh_graded_of"):
            continue
        if not (u.is_updated_geometry or u.is_updated_transform):
            continue
        if obj.name in _ours:
            _ours.discard(obj.name)
            continue
        request_rebuild(obj)


_CLASSES = (FHDart, FHPleat, FHHem, FHHardware, FHPocket, FHShow, FHFeatures)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.fh_features = bpy.props.PointerProperty(type=FHFeatures)
    bpy.types.Scene.fh_show = bpy.props.PointerProperty(type=FHShow)
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if bpy.app.timers.is_registered(_flush):
        bpy.app.timers.unregister(_flush)
    del bpy.types.Scene.fh_show
    del bpy.types.Object.fh_features
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
