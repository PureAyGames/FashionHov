"""Thread and hardware you can see, riding on the cloth as it simulates.

Everything is laid out in *pattern space* (the flat panel coordinates the
cloth UVs use), then a geometry-nodes modifier looks each point up on the
garment (or on the separate pieces) with Sample UV Surface. So topstitching,
rivets, buttons and zipper teeth follow every wrinkle, and changing a seam or
moving a button only rewrites this one small object.
"""

import math
import bmesh
import bpy

from .core import derive as dv
from . import features as ft

OBJ = "FH Details"
LIB = "FH Hardware Library"
TREE = "FH Details"
LIB_KINDS = ['BUTTON_SHANK', 'BUTTON', 'RIVET', 'SNAP', 'GROMMET', 'PULL']
FIN = [f[0] for f in ft.FINISHES]
FIN_RGB = {'BRASS': (0.78, 0.57, 0.11), 'COPPER': (0.72, 0.42, 0.2), 'NICKEL': (0.8, 0.8, 0.78),
           'BLACK': (0.03, 0.03, 0.03), 'GUNMETAL': (0.2, 0.21, 0.23)}
KIND_THREAD, KIND_TEETH, KIND_HW = 0, 1, 2

THREAD_PRESETS = {
    'GOLD': ((0.76, 0.5, 0.15, 1), "Denim Gold"), 'COPPER': ((0.65, 0.3, 0.12, 1), "Copper"),
    'WHITE': ((0.92, 0.92, 0.9, 1), "White"), 'BLACK': ((0.03, 0.03, 0.03, 1), "Black"),
    'MATCH': ((0.2, 0.25, 0.4, 1), "Tonal (navy)"),
}


def _upd(self, context):
    request(context)


class FHThread(bpy.types.PropertyGroup):
    visible: bpy.props.BoolProperty(name="Show Thread", default=True, update=_upd)
    show_hardware: bpy.props.BoolProperty(name="Show Hardware", default=True, update=_upd)
    color: bpy.props.FloatVectorProperty(name="Thread Colour", subtype='COLOR', size=4, min=0, max=1,
                                         default=(0.76, 0.5, 0.15, 1), update=_upd)
    thickness: bpy.props.FloatProperty(name="Thickness", default=0.0007, min=0.0002, max=0.003,
                                       subtype='DISTANCE', unit='LENGTH', update=_upd,
                                       description="Topstitch thread is thicker than seam thread; ~0.7 mm for denim")
    stitch_length: bpy.props.FloatProperty(name="Stitch Length", default=0.0032, min=0.001, max=0.012,
                                           subtype='DISTANCE', unit='LENGTH', update=_upd,
                                           description="About 8 stitches per inch = 3.2 mm")
    seam_allowance: bpy.props.FloatProperty(name="Seam Allowance", default=0.01, min=0.0, max=0.05,
                                            subtype='DISTANCE', unit='LENGTH',
                                            description="Default added outside every edge when exporting")


class FH_OT_thread_preset(bpy.types.Operator):
    """Set the thread colour"""
    bl_idname = "fashionhov.thread_preset"
    bl_label = "Thread Colour"
    preset: bpy.props.EnumProperty(items=[(k, v[1], "") for k, v in THREAD_PRESETS.items()])

    def execute(self, context):
        context.scene.fh_thread.color = THREAD_PRESETS[self.preset][0]
        return {'FINISHED'}


# ---------- pattern-space paths ----------

def dashes(pts, stitch, gap_frac=0.25):
    """Split a polyline into stitch dashes: list of (a, b)."""
    out = []
    if len(pts) < 2:
        return out
    total = dv.polyline_len(pts)
    s = 0.0
    on = stitch * (1 - gap_frac)
    while s + on <= total + 1e-9:
        a, _ = dv.point_at_arc(pts, s)
        b, _ = dv.point_at_arc(pts, s + on)
        out.append((a, b))
        s += stitch
    return out


def collect(scene):
    """Thread polylines, solid thread polylines, zipper teeth and hardware points."""
    from .util import panels
    from . import sewing
    th = scene.fh_thread
    thread, solid, teeth, points = [], [], [], []
    for panel in panels(scene):
        if panel.get("fh_graded_of"):
            continue
        d = ft.get_derived(panel)
        if d is None:
            continue
        f = panel.fh_features
        for h in f.hems:
            pts, _ = d.chain(h.va, h.vb)
            if len(pts) < 2 or h.topstitch == 'NONE':
                continue
            base = max(h.width - 0.003, 0.0015)
            rows = [base] if h.topstitch == 'SINGLE' else [base, max(base - 0.0064, 0.0015)]
            thread += [dv.offset_polyline(pts, r) for r in rows]
        for line in d.lines:
            if line["kind"] == "fly_stitch":
                thread.append(line["pts"])
                thread.append(dv.offset_polyline(line["pts"], -0.0064))
                end = line["pts"][-1]
                solid.append([(end[0] - 0.004, end[1]), (end[0] + 0.004, end[1])])   # bartack
        for k, (a, b) in enumerate(d.sews[:len(f.pleats)]):
            thread.append(dv.offset_polyline(a, -0.0015))
        for hw in f.hardware:
            if hw.kind == 'ZIPPER':
                path = ft.zipper_path(panel, hw)
                if len(path) < 2:
                    continue
                if hw.style == 'EXPOSED':
                    teeth.append(path)
                if hw.style != 'FLY':
                    tip = path[0] if hw.pull_at_start else path[-1]
                    points.append((tip, LIB_KINDS.index('PULL') * len(FIN) + FIN.index(hw.finish), 1.0))
                continue
            xy = ft.hardware_world(panel, hw)
            if hw.kind == 'BUTTONHOLE':
                c, s_ = math.cos(hw.angle), math.sin(hw.angle)
                L, W = hw.size / 2, 0.0016
                rect = [(-L, -W), (L, -W), (L, W), (-L, W), (-L, -W)]
                solid.append([(xy[0] + x * c - y * s_, xy[1] + x * s_ + y * c) for x, y in rect])
                continue
            idx = LIB_KINDS.index(hw.kind) * len(FIN) + FIN.index(hw.finish)
            points.append((xy, idx, hw.size / ft.HW_SIZE[hw.kind]))
    for seam in scene.fh_seams:
        if seam.topstitch == 'NONE' or not sewing.seam_ok(seam):
            continue
        sides = {'A': [seam.a_obj], 'B': [seam.b_obj], 'BOTH': [seam.a_obj, seam.b_obj]}[seam.ts_side]
        for panel in sides:
            v0, v1 = (seam.a_v0, seam.a_v1) if panel == seam.a_obj else (seam.b_v0, seam.b_v1)
            d = ft.get_derived(panel)
            pts, _ = d.chain(v0, v1)
            rows = [seam.ts_dist] + ([seam.ts_dist + seam.ts_gap] if seam.topstitch == 'DOUBLE' else [])
            thread += [dv.offset_polyline(pts, r) for r in rows]
    if not th.visible:
        thread, solid = [], []
    if not th.show_hardware:
        points, teeth = [], []
    return thread, solid, teeth, points


def build_mesh(scene, me):
    thread, solid, teeth, points = collect(scene)
    th = scene.fh_thread
    verts, edges, kind, hw, scale = [], [], [], [], []

    def add_edge(a, b, k):
        i = len(verts)
        verts.extend([(a[0], a[1], 0.0), (b[0], b[1], 0.0)])
        edges.append((i, i + 1))
        kind.extend([k, k])
        hw.extend([0, 0])
        scale.extend([1.0, 1.0])

    for pl in thread:
        for a, b in dashes(pl, th.stitch_length):
            add_edge(a, b, KIND_THREAD)
    for pl in solid:
        for a, b in zip(pl, pl[1:]):
            add_edge(a, b, KIND_THREAD)
    for pl in teeth:
        for a, b in zip(pl, pl[1:]):
            add_edge(a, b, KIND_TEETH)
    for xy, idx, sc in points:
        verts.append((xy[0], xy[1], 0.0))
        kind.append(KIND_HW)
        hw.append(idx)
        scale.append(sc)
    me.clear_geometry()
    me.from_pydata(verts, edges, [])
    for name, typ, vals in (("fh_kind", 'INT', kind), ("fh_hw", 'INT', hw), ("fh_scale", 'FLOAT', scale)):
        a = me.attributes.get(name) or me.attributes.new(name, typ, 'POINT')
        if vals:
            a.data.foreach_set("value", vals)
    me.update()
    return len(edges), len(points)


# ---------- materials + hardware library ----------

def _mat(name, rgb, metal=0.0, rough=0.5):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb[:3], 1)
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
    m.diffuse_color = (*rgb[:3], 1)
    m.metallic = metal
    m.roughness = rough
    return m


def _cyl(bm, r, h, z=0.0, seg=24):
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=h)
    bmesh.ops.translate(bm, verts=res["verts"], vec=(0, 0, z + h / 2))


def _dome(bm, r, h, z=0.0):
    res = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=10, radius=r)
    for v in res["verts"]:
        v.co.z = z + max(v.co.z, 0) * (h / r)


def _torus(bm, R, r, seg=24, rseg=8):
    rings = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        ring = []
        for j in range(rseg):
            b = 2 * math.pi * j / rseg
            ring.append(bm.verts.new(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a),
                                      r + r * math.sin(b))))
        rings.append(ring)
    for i in range(seg):
        for j in range(rseg):
            bm.faces.new((rings[i][j], rings[(i + 1) % seg][j], rings[(i + 1) % seg][(j + 1) % rseg],
                          rings[i][(j + 1) % rseg]))


def _build_kind(bm, kind):
    if kind == 'BUTTON_SHANK':
        _cyl(bm, 0.0085, 0.0015)
        _dome(bm, 0.0072, 0.0022, 0.0015)
    elif kind == 'BUTTON':
        _cyl(bm, 0.0075, 0.0025)
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            res = bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.0009, radius2=0.0009, depth=0.0006)
            bmesh.ops.translate(bm, verts=res["verts"], vec=(dx * 0.0018, dy * 0.0018, 0.0026))
    elif kind == 'RIVET':
        _dome(bm, 0.0045, 0.0022)
    elif kind == 'SNAP':
        _cyl(bm, 0.006, 0.0018)
        _dome(bm, 0.004, 0.0012, 0.0018)
    elif kind == 'GROMMET':
        _torus(bm, 0.004, 0.0011)
    elif kind == 'PULL':
        res = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(0.006, 0.018, 0.0015), verts=res["verts"])
        bmesh.ops.translate(bm, verts=res["verts"], vec=(0, -0.009, 0.001))


def library(scene):
    col = bpy.data.collections.get(LIB)
    if col and len(col.objects) == len(LIB_KINDS) * len(FIN):
        return col
    if col is None:
        col = bpy.data.collections.new(LIB)
    for o in list(col.objects):
        bpy.data.objects.remove(o)
    for ki, kind in enumerate(LIB_KINDS):
        for fi, fin in enumerate(FIN):
            idx = ki * len(FIN) + fi
            bm = bmesh.new()
            _build_kind(bm, kind)
            me = bpy.data.meshes.new(f"FH_HW_{idx:03d}_{kind}_{fin}")
            bm.to_mesh(me)
            bm.free()
            for p in me.polygons:
                p.use_smooth = True
            me.materials.append(_mat(f"FH Metal {fin}", FIN_RGB[fin], 1.0 if fin != 'BLACK' else 0.0, 0.35))
            o = bpy.data.objects.new(me.name, me)
            col.objects.link(o)
    return col


def _link_hidden(scene, col):
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    for lc in scene.view_layers[0].layer_collection.children:
        if lc.collection == col:
            lc.exclude = True


# ---------- geometry nodes ----------

def _int_ab(c):
    """The A/B integer inputs of a Compare node (static or dynamic socket layouts)."""
    ints = [s for s in c.inputs if s.type == 'INT']
    return (ints[0], ints[1]) if len(ints) >= 2 else (c.inputs[0], c.inputs[1])

def node_tree(source_kind, source, lib, thread_mat, teeth_mat, radius):
    t = bpy.data.node_groups.get(TREE)
    if t is None:
        t = bpy.data.node_groups.new(TREE, 'GeometryNodeTree')
        t.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        t.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, L = t.nodes, t.links
    N.clear()
    gin = N.new("NodeGroupInput")
    gout = N.new("NodeGroupOutput")

    if source_kind == 'OBJECT':
        src = N.new("GeometryNodeObjectInfo")
        src.transform_space = 'RELATIVE'
        src.inputs["Object"].default_value = source
        surface = src.outputs["Geometry"]
    else:
        src = N.new("GeometryNodeCollectionInfo")
        src.transform_space = 'RELATIVE'
        src.inputs["Collection"].default_value = source
        real = N.new("GeometryNodeRealizeInstances")
        L.new(src.outputs["Instances"], real.inputs["Geometry"])
        surface = real.outputs["Geometry"]

    uv = N.new("GeometryNodeInputNamedAttribute")
    uv.data_type = 'FLOAT_VECTOR'
    uv.inputs["Name"].default_value = "Pattern"
    pos = N.new("GeometryNodeInputPosition")
    nrm = N.new("GeometryNodeInputNormal")

    def sample(field):
        s = N.new("GeometryNodeSampleUVSurface")
        s.data_type = 'FLOAT_VECTOR'
        L.new(surface, s.inputs["Mesh"])
        L.new(field, s.inputs["Value"])
        L.new(uv.outputs["Attribute"], s.inputs["UV Map"])
        L.new(pos.outputs["Position"], s.inputs["Sample UV"])
        return s.outputs["Value"]

    spos, snrm = sample(pos.outputs["Position"]), sample(nrm.outputs["Normal"])
    lift = N.new("ShaderNodeVectorMath")
    lift.operation = 'SCALE'
    L.new(snrm, lift.inputs[0])
    lift.inputs["Scale"].default_value = radius * 0.8 + 0.0004
    setp = N.new("GeometryNodeSetPosition")
    L.new(gin.outputs[0], setp.inputs["Geometry"])
    L.new(spos, setp.inputs["Position"])
    L.new(lift.outputs[0], setp.inputs["Offset"])

    kind = N.new("GeometryNodeInputNamedAttribute")
    kind.data_type = 'INT'
    kind.inputs["Name"].default_value = "fh_kind"
    join = N.new("GeometryNodeJoinGeometry")

    def pick(k):
        c = N.new("FunctionNodeCompare")
        c.data_type = 'INT'
        c.operation = 'EQUAL'
        a, b = _int_ab(c)
        L.new(kind.outputs["Attribute"], a)
        b.default_value = k
        sep = N.new("GeometryNodeSeparateGeometry")
        sep.domain = 'POINT'
        L.new(setp.outputs["Geometry"], sep.inputs["Geometry"])
        L.new(c.outputs["Result"], sep.inputs["Selection"])
        return sep.outputs["Selection"]

    for k, r, mat in ((KIND_THREAD, radius, thread_mat), (KIND_TEETH, 0.0022, teeth_mat)):
        m2c = N.new("GeometryNodeMeshToCurve")
        L.new(pick(k), m2c.inputs["Mesh"])
        circ = N.new("GeometryNodeCurvePrimitiveCircle")
        circ.inputs["Resolution"].default_value = 5
        circ.inputs["Radius"].default_value = r
        c2m = N.new("GeometryNodeCurveToMesh")
        L.new(m2c.outputs["Curve"], c2m.inputs["Curve"])
        L.new(circ.outputs["Curve"], c2m.inputs["Profile Curve"])
        c2m.inputs["Fill Caps"].default_value = True
        sm = N.new("GeometryNodeSetMaterial")
        sm.inputs["Material"].default_value = mat
        L.new(c2m.outputs["Mesh"], sm.inputs["Geometry"])
        L.new(sm.outputs["Geometry"], join.inputs["Geometry"])

    # hardware: instance library items on the points, standing on the surface normal
    coll = N.new("GeometryNodeCollectionInfo")
    coll.transform_space = 'ORIGINAL'
    coll.inputs["Collection"].default_value = lib
    coll.inputs["Separate Children"].default_value = True
    coll.inputs["Reset Children"].default_value = True
    hwi = N.new("GeometryNodeInputNamedAttribute")
    hwi.data_type = 'INT'
    hwi.inputs["Name"].default_value = "fh_hw"
    hws = N.new("GeometryNodeInputNamedAttribute")
    hws.data_type = 'FLOAT'
    hws.inputs["Name"].default_value = "fh_scale"
    align = N.new("FunctionNodeAlignRotationToVector")
    align.axis = 'Z'
    L.new(snrm, align.inputs["Vector"])
    iop = N.new("GeometryNodeInstanceOnPoints")
    # sample the normal on the *unmoved* points: put hardware right on the surface
    setp2 = N.new("GeometryNodeSetPosition")
    L.new(gin.outputs[0], setp2.inputs["Geometry"])
    L.new(spos, setp2.inputs["Position"])
    c = N.new("FunctionNodeCompare")
    c.data_type = 'INT'
    c.operation = 'EQUAL'
    a, b = _int_ab(c)
    L.new(kind.outputs["Attribute"], a)
    b.default_value = KIND_HW
    sep = N.new("GeometryNodeSeparateGeometry")
    sep.domain = 'POINT'
    L.new(setp2.outputs["Geometry"], sep.inputs["Geometry"])
    L.new(c.outputs["Result"], sep.inputs["Selection"])
    L.new(sep.outputs["Selection"], iop.inputs["Points"])
    L.new(coll.outputs["Instances"], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    L.new(hwi.outputs["Attribute"], iop.inputs["Instance Index"])
    L.new(align.outputs["Rotation"], iop.inputs["Rotation"])
    L.new(hws.outputs["Attribute"], iop.inputs["Scale"])
    real = N.new("GeometryNodeRealizeInstances")
    L.new(iop.outputs["Instances"], real.inputs["Geometry"])
    L.new(real.outputs["Geometry"], join.inputs["Geometry"])
    L.new(join.outputs["Geometry"], gout.inputs[0])
    return t


def rebuild(context):
    scene = context.scene
    if not hasattr(scene, "fh_thread"):
        return None
    from .cloth import PIECES
    garment = bpy.data.objects.get("FH Garment")
    pieces = bpy.data.collections.get(PIECES)
    if not garment and not pieces:
        return None
    obj = bpy.data.objects.get(OBJ)
    if obj is None:
        obj = bpy.data.objects.new(OBJ, bpy.data.meshes.new(OBJ))
        scene.collection.objects.link(obj)
    n_edges, n_pts = build_mesh(scene, obj.data)
    lib = library(scene)
    _link_hidden(scene, lib)
    th = scene.fh_thread
    thread_mat = _mat("FH Thread", th.color, 0.0, 0.7)
    zips = [h for p in scene.objects if p.get("fh_panel") for h in p.fh_features.hardware if h.kind == 'ZIPPER']
    teeth_mat = _mat("FH Zipper Teeth", FIN_RGB[zips[0].finish] if zips else FIN_RGB['NICKEL'], 1.0, 0.3)
    src = ('OBJECT', garment) if garment else ('COLLECTION', pieces)
    tree = node_tree(src[0], src[1], lib, thread_mat, teeth_mat, th.thickness / 2)
    mod = obj.modifiers.get("FH Details") or obj.modifiers.new("FH Details", 'NODES')
    mod.node_group = tree
    obj.hide_select = True
    return obj, n_edges, n_pts


def request(context):
    """Debounced rebuild (UI sliders)."""
    if not bpy.app.timers.is_registered(_later):
        bpy.app.timers.register(_later, first_interval=0.25)


def _later():
    try:
        rebuild(bpy.context)
    except Exception as e:
        print("FashionHov: details rebuild failed:", e)
    return None


class FH_OT_rebuild_details(bpy.types.Operator):
    """Rebuild thread and hardware visuals"""
    bl_idname = "fashionhov.rebuild_details"
    bl_label = "Refresh Thread & Hardware"

    def execute(self, context):
        rebuild(context)
        return {'FINISHED'}


classes = (FH_OT_thread_preset, FH_OT_rebuild_details)


def register():
    bpy.utils.register_class(FHThread)
    bpy.types.Scene.fh_thread = bpy.props.PointerProperty(type=FHThread)


def unregister():
    if bpy.app.timers.is_registered(_later):
        bpy.app.timers.unregister(_later)
    del bpy.types.Scene.fh_thread
    bpy.utils.unregister_class(FHThread)
