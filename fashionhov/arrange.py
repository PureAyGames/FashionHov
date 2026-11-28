"""Place cloth pieces around the avatar, then sew + simulate them as one garment.

Placement wraps each flat piece around a vertical cylinder fitted to the
body at that height (torso, or one leg), the same idea as the arrangement
points in Style3D / Marvelous, but picked from a simple list.
"""

import math
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import fabric, sewing
from .core import bodymeasure

PLACES = [
    ('NONE', "Not Placed", "Leave the piece flat on the pattern table"),
    ('FRONT', "Body Front", ""), ('BACK', "Body Back", ""),
    ('LEFT', "Body Left Side", "Wearer's left"), ('RIGHT', "Body Right Side", "Wearer's right"),
    ('L_LEG_FRONT', "Left Leg Front", ""), ('L_LEG_BACK', "Left Leg Back", ""),
    ('R_LEG_FRONT', "Right Leg Front", ""), ('R_LEG_BACK', "Right Leg Back", ""),
]
ANGLE = {'FRONT': -90, 'BACK': 90, 'LEFT': 0, 'RIGHT': 180,
         'L_LEG_FRONT': -90, 'L_LEG_BACK': 90, 'R_LEG_FRONT': -90, 'R_LEG_BACK': 90}
GARMENT = "FH Garment"
SIM_FRAMES = 150


class FHPlace(bpy.types.PropertyGroup):
    where: bpy.props.EnumProperty(name="Place", items=PLACES)
    top: bpy.props.FloatProperty(
        name="Top Height", default=0.0, subtype='DISTANCE', unit='LENGTH',
        description="Height of the piece's top edge on the avatar. 0 = automatic "
                    "(neck base for body pieces, waist for leg pieces)")
    gap: bpy.props.FloatProperty(name="Gap", default=0.04, min=0.005, max=0.3,
                                 subtype='DISTANCE', unit='LENGTH',
                                 description="How far from the body the piece starts")
    mirror: bpy.props.BoolProperty(name="Mirror", description="Flip the piece left-right when placing")


# ---------- body cylinders ----------

def body_slicer(context, avatar):
    from .avatar import mesh_arrays
    v, t = mesh_arrays(context, avatar)
    return bodymeasure.Body(v, t)


def axis_and_radius(body, z, where):
    loops = body.loops_at(z)
    if not loops:
        return body.c, 0.15
    if 'LEG' in where:
        side = 1 if where.startswith('L_') else -1      # wearer's left = +X
        legs = [l for l in loops if side * (l[:, 0].mean() - body.c[0]) > 0.01]
        loop = max(legs, key=bodymeasure.area) if legs else max(loops, key=bodymeasure.area)
        axis = loop.mean(axis=0)
    else:
        loop = body.center_loop(z)
        if loop is None:
            loop = max(loops, key=bodymeasure.area)
        axis = body.c
    r = float(np.linalg.norm(loop - axis, axis=1).max())
    return np.array(axis), r


def auto_top(avatar, where):
    m = avatar.get("fh_measured", {})
    if 'LEG' in where:
        return m.get("z_waist", 0.6 * m.get("height", 1.75))
    return m.get("z_neck_base", 0.83 * m.get("height", 1.75))


def piece_pattern_xy(piece, home=False):
    """(pattern xy per vertex, raw UV per vertex) of a cloth piece. home=True gives
    the position where the piece sits on its parent (inner pieces are laid out
    beside the parent on the pattern table)."""
    me = piece.data
    uv = me.uv_layers.get("Pattern")
    raw = np.zeros((len(me.vertices), 2))
    for loop in me.loops:
        raw[loop.vertex_index] = uv.data[loop.index].uv
    xy = raw - np.array(piece.get("fh_uv_off", (0.0, 0.0)))
    if home:
        xy = xy - np.array(piece.get("fh_home_delta", (0.0, 0.0)))
    return xy, raw


def piece_of(scene, panel):
    return next((o for o in scene.objects if o.get("fh_cloth_source") == panel.name), None)


def wrap_piece(context, piece, panel, avatar, body=None):
    """Move a flat cloth piece's vertices onto its cylinder around the avatar.
    Pocket pieces use their parent panel's placement, so they land exactly where
    they sit on the pattern, just outside the parent."""
    from .features import owner_of
    from .pockets import ROLE_BUMP
    bump = 0.0
    frame_panel = panel
    if panel.get("fh_feature_of"):
        parent, _ = owner_of(panel)
        if parent is None:
            return False
        frame_panel, bump = parent, ROLE_BUMP.get(panel.get("fh_role", "POCKET"), 0.005)
    pl = frame_panel.fh_place
    if pl.where == 'NONE':
        return False
    frame_piece = piece if frame_panel == panel else piece_of(context.scene, frame_panel)
    if frame_piece is None:
        return False
    body = body or body_slicer(context, avatar)
    me = piece.data
    pxy, raw = piece_pattern_xy(piece, home=True)
    fxy, _ = piece_pattern_xy(frame_piece, home=True) if frame_piece != piece else (pxy, raw)
    x0, y0 = fxy.min(axis=0)
    x1, y1 = fxy.max(axis=0)
    cx = (x0 + x1) / 2
    floor = avatar.get("fh_measured", {}).get("z_floor", avatar.matrix_world.translation.z)
    top = floor + pl.top if pl.top > 0 else auto_top(avatar, pl.where)
    zmid = top - (y1 - y0) / 2
    axis, r = axis_and_radius(body, zmid, pl.where)
    R = r + pl.gap + bump
    th0 = math.radians(ANGLE[pl.where])
    u = pxy[:, 0] - cx
    if pl.mirror:
        u = -u
    th = th0 + u / R
    # Pleat intake starts tucked slightly inward so it folds to the inside.
    Rv = np.full(len(pxy), R)
    from .core.geometry import point_in_polygon
    for poly in piece.get("fh_intake", []):
        poly = [tuple(p) for p in poly]
        inside = np.array([point_in_polygon(tuple(p), poly) for p in raw])
        Rv[inside] -= min(0.01, pl.gap * 0.5)
    world = np.column_stack([axis[0] + Rv * np.cos(th), axis[1] + Rv * np.sin(th), top - (y1 - pxy[:, 1])])
    piece.matrix_world = Matrix.Identity(4)
    for v, p in zip(me.vertices, world):
        v.co = Vector(p)
    me.update()
    piece["fh_placed"] = True
    return True


# ---------- garment assembly ----------

def boundary_on_chain(piece, chain_pts, tol=0.002, world=True):
    """Vertices of a piece lying on a 2D pattern chain (outline or internal line, e.g.
    the line under a fly), sorted along it. Returns [(vertex_index, t)], t = 0..1
    sewn arc position (jump segments count as zero length)."""
    me = piece.data
    uv = me.uv_layers.get("Pattern")
    pxy = {}
    for loop in me.loops:
        pxy[loop.vertex_index] = tuple(uv.data[loop.index].uv)
    if world:   # chain given in pattern (world) space: move it into this piece's UV slot
        ox, oy = piece.get("fh_uv_off", (0.0, 0.0))
        chain_pts = sewing.Poly([(x + ox, y + oy) for x, y in chain_pts], getattr(chain_pts, "jumps", ()))
    xs = [p[0] for p in chain_pts]
    ys = [p[1] for p in chain_pts]
    x0, x1, y0, y1 = min(xs) - tol, max(xs) + tol, min(ys) - tol, max(ys) + tol
    cand = [i for i, p in pxy.items() if x0 <= p[0] <= x1 and y0 <= p[1] <= y1]
    params = sewing.arc_params(chain_pts)
    out = []
    for i in cand:
        p = pxy[i]
        best = None
        for k, (a, b) in enumerate(zip(chain_pts, chain_pts[1:])):
            d = _seg_dist(p, a, b)
            if best is None or d[0] < best[0]:
                best = (d[0], params[k] + d[1] * (params[k + 1] - params[k]))
        if best and best[0] < tol:
            out.append((i, best[1]))
    out.sort(key=lambda x: x[1])
    return out


def _seg_dist(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.dist(p, (ax + t * dx, ay + t * dy)), t


def match_sides(side_a, side_b):
    """Pair up two sorted [(idx, t)] lists so every vertex gets a partner."""
    pairs = set()
    if not side_a or not side_b:
        return pairs
    tb = [t for _, t in side_b]
    ta = [t for _, t in side_a]
    for i, t in side_a:
        j = min(range(len(tb)), key=lambda k: abs(tb[k] - t))
        pairs.add((i, side_b[j][0]))
    for j, t in side_b:
        i = min(range(len(ta)), key=lambda k: abs(ta[k] - t))
        pairs.add((side_a[i][0], j))
    return pairs


def pieces_for(scene, simulated_only=True):
    from .features import panel_simulated
    out = []
    for o in scene.objects:
        if not o.get("fh_cloth_source") or o.type != 'MESH' or o.name == GARMENT:
            continue
        src = bpy.data.objects.get(o["fh_cloth_source"])
        if src is None or (simulated_only and not panel_simulated(src, scene)):
            continue
        out.append(o)
    return out


def build_garment(context):
    scene = context.scene
    pieces = pieces_for(scene)
    if not pieces:
        raise ValueError("no cloth pieces; build cloth meshes from your panels first")
    by_panel = {p["fh_cloth_source"]: p for p in pieces}

    verts, faces, offset, vgroups = [], [], {}, {}
    for p in pieces:
        offset[p.name] = len(verts)
        mw = p.matrix_world
        verts += [tuple(mw @ v.co) for v in p.data.vertices]
        faces += [[i + offset[p.name] for i in f.vertices] for f in p.data.polygons]
        vgroups[p.name] = range(offset[p.name], len(verts))

    def layers_on(panel, chain_pts):
        """Every simulated layer lying on a panel's seam line: the panel itself plus
        inner pieces (pocket facing, bag) whose edges sit on that line. That's what
        makes real 3- and 4-layer seams (front + facing + bag + back)."""
        out = []
        piece = by_panel.get(panel.name)
        if piece:
            out += [(i + offset[piece.name], t) for i, t in boundary_on_chain(piece, chain_pts)]
        for p in pieces:
            src = bpy.data.objects.get(p["fh_cloth_source"])
            if not src or src.get("fh_feature_of") != panel.name or \
                    src.get("fh_role") not in ('FACING', 'BAG', 'BAG_FRONT'):
                continue
            dx, dy = p.get("fh_home_delta", (0.0, 0.0))
            moved = sewing.Poly([(x + dx, y + dy) for x, y in chain_pts], getattr(chain_pts, "jumps", ()))
            out += [(i + offset[p.name], t) for i, t in boundary_on_chain(p, moved)]
        out.sort(key=lambda x: x[1])
        return out

    sew_edges = []
    seam_verts = {}
    for seam in scene.fh_seams:
        if not sewing.seam_ok(seam):
            continue
        a, b = sewing.seam_chains(seam)
        if seam.a_obj.name not in by_panel or seam.b_obj.name not in by_panel:
            continue
        sa = layers_on(seam.a_obj, a)
        sb = layers_on(seam.b_obj, b)
        if seam.flip:
            sb = [(i, 1.0 - t) for i, t in sb][::-1]
        pairs = match_sides(sa, sb)
        for layer in seam.layers:           # extra layers you added by hand
            if layer.obj is None or layer.obj.name not in by_panel:
                continue
            ch = sewing.chain(layer.obj, layer.v0, layer.v1)
            sl = layers_on(layer.obj, ch)
            if layer.flip:
                sl = [(i, 1.0 - t) for i, t in sl][::-1]
            pairs |= match_sides(sa, sl)
        sew_edges += [e for e in pairs if e[0] != e[1]]
        seam_verts[str(seam.number)] = {"a": [i for i, _ in sa], "b": [i for i, _ in sb]}

    # Internal seams: dart legs closed, pleats tacked.
    for p in pieces:
        for a, b in p.get("fh_sews", []):
            a = [tuple(x) for x in a]
            b = [tuple(x) for x in b]
            sa = [(i + offset[p.name], t) for i, t in boundary_on_chain(p, a, world=False)]
            sb = [(i + offset[p.name], t) for i, t in boundary_on_chain(p, b, world=False)]
            sew_edges += [e for e in match_sides(sa, sb) if e[0] != e[1]]

    # Child pieces stitched onto a surface at the same spot (in home position):
    #   patch pockets    -> parent, along every edge but the opening
    #   bag front layer  -> parent's pocket opening edge, and to the bag's
    #                       back layer along the bag's bottom / inner edges
    #   pocket facing    -> bag (back layer) along its inner edge
    #   fly shield       -> parent, along its line just inside centre front
    from mathutils.kdtree import KDTree
    from .features import owner_of, get_derived

    def surface(piece):
        xy, _ = piece_pattern_xy(piece, home=True)
        kd = KDTree(len(xy))
        for i, (x, y) in enumerate(xy):
            kd.insert((x, y, 0.0), i)
        kd.balance()
        return kd

    for p in pieces:
        panel = bpy.data.objects.get(p["fh_cloth_source"])
        if not panel or not panel.get("fh_feature_of"):
            continue
        parent, item = owner_of(panel)
        ppiece = by_panel.get(parent.name) if parent else None
        if not ppiece or item is None:
            continue
        role = panel.get("fh_role", "POCKET")
        target = ppiece
        if role == 'POCKET':
            d = get_derived(panel)
            chain_pts, jumps = d.chain(item.attach_va, item.attach_vb)
            if len(chain_pts) < 2:
                continue
            mine = boundary_on_chain(p, sewing.Poly(chain_pts, jumps))
        elif role in ('FACING', 'SHIELD', 'BAG_FRONT') and panel.get("fh_attach_line"):
            if role == 'FACING' and item.bag and item.bag.name in by_panel:
                target = by_panel[item.bag.name]
            dx, dy = p.get("fh_home_delta", (0.0, 0.0))
            line = [(x + dx, y + dy) for x, y in panel["fh_attach_line"]]
            mine = boundary_on_chain(p, line, tol=0.003)
        else:
            continue
        jobs = [(mine, target)]
        if role == 'BAG_FRONT' and item.bag and item.bag.name in by_panel and "fh_bag_join" in item:
            dx, dy = p.get("fh_home_delta", (0.0, 0.0))
            join = [(x + dx, y + dy) for x, y in item["fh_bag_join"]]
            jobs.append((boundary_on_chain(p, join, tol=0.003), by_panel[item.bag.name]))
        cxy, _ = piece_pattern_xy(p, home=True)
        for verts_, tgt in jobs:
            kd = surface(tgt)
            for i, _ in verts_:
                _, j, dist = kd.find((cxy[i][0], cxy[i][1], 0.0))
                if dist < 0.012:
                    sew_edges.append((i + offset[p.name], j + offset[tgt.name]))

    me = bpy.data.meshes.new(GARMENT)
    me.from_pydata(verts, sew_edges, faces)
    # carry pattern UVs over
    uv = me.uv_layers.new(name="Pattern")
    li = 0
    for p in pieces:
        src = p.data.uv_layers.get("Pattern")
        for poly in p.data.polygons:
            for k in poly.loop_indices:
                uv.data[li].uv = src.data[k].uv
                li += 1
    for poly in me.polygons:
        poly.use_smooth = True

    old = bpy.data.objects.get(GARMENT)
    if old:
        bpy.data.objects.remove(old)
    obj = bpy.data.objects.new(GARMENT, me)
    scene.collection.objects.link(obj)
    for name, rng in vgroups.items():
        g = obj.vertex_groups.new(name=name)
        g.add(list(rng), 1.0, 'REPLACE')
    obj["fh_garment"] = True
    obj["fh_seam_verts"] = seam_verts
    obj["fh_pieces"] = [p.name for p in pieces]

    # Fabric: area-weighted mix of the pieces (one cloth sim = one fabric).
    areas = [sum(f.area for f in p.data.polygons) for p in pieces]
    tot = sum(areas) or 1
    mix = lambda k: sum(getattr(p.fh_fabric, k) * a for p, a in zip(pieces, areas)) / tot
    big = pieces[areas.index(max(areas))]
    fabric.copy_fabric(big.fh_fabric, obj.fh_fabric)
    obj.fh_fabric.gsm, obj.fh_fabric.drape, obj.fh_fabric.stretch = mix("gsm"), mix("drape"), mix("stretch")

    mod = fabric.ensure_cloth(obj)
    mod.show_viewport = mod.show_render = True
    # Real fabric is ~1 mm thick. Thin collision padding lets 3-4 layers (front,
    # pocket bag, facing) stack against the body without squeezing through each other.
    cs = mod.collision_settings
    cs.distance_min = 0.0015
    cs.self_distance_min = 0.001
    cs.collision_quality = 5
    st = mod.settings
    st.quality = 10
    st.use_sewing_springs = True
    st.sewing_force_max = 50.0
    st.use_internal_springs = False
    st.shrink_min = 0.0
    mod.point_cache.frame_start = 1
    mod.point_cache.frame_end = SIM_FRAMES
    # Sew first with gravity off (pieces pull together), then let it hang.
    ew = st.effector_weights
    for frame, g in ((1, 0.0), (35, 0.0), (55, 1.0)):
        ew.gravity = g
        ew.keyframe_insert("gravity", frame=frame)
    for p in pieces:
        p.hide_set(True)
    scene.frame_start, scene.frame_end = 1, SIM_FRAMES
    scene.frame_set(1)
    scene["fh_garment_stale"] = False
    try:
        from . import details
        details.rebuild(context)
    except Exception as e:
        print("FashionHov: details rebuild failed:", e)
    return obj


def remove_garment(context):
    obj = bpy.data.objects.get(GARMENT)
    if obj:
        for name in obj.get("fh_pieces", []):
            p = bpy.data.objects.get(name)
            if p:
                p.hide_set(False)
        me = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(me)
        try:
            from . import details
            details.rebuild(context)
        except Exception as e:
            print("FashionHov: details rebuild failed:", e)


# ---------- operators ----------

class FH_OT_arrange(bpy.types.Operator):
    """Wrap every placed cloth piece around the avatar (set each panel's Place first)"""
    bl_idname = "fashionhov.arrange"
    bl_label = "Arrange Pieces on Avatar"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.fh_body.avatar is not None and context.mode == 'OBJECT'

    def execute(self, context):
        avatar = context.scene.fh_body.avatar
        try:
            body = body_slicer(context, avatar)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        n = 0
        ps = pieces_for(context.scene)
        ps.sort(key=lambda o: bool(bpy.data.objects[o["fh_cloth_source"]].get("fh_feature_of")))
        # (pockets, facings and shields are placed with their parent's frame)
        for piece in ps:          # parents before their pockets
            panel = bpy.data.objects.get(piece["fh_cloth_source"])
            if panel and wrap_piece(context, piece, panel, avatar, body):
                n += 1
        if n == 0:
            self.report({'WARNING'}, "No pieces placed: select a panel and set its Place")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Placed {n} piece(s). Sew in 2D or 3D, then Simulate")
        return {'FINISHED'}


class FH_OT_simulate(bpy.types.Operator):
    """Join the pieces, sew the seams and drape the garment on the avatar"""
    bl_idname = "fashionhov.simulate"
    bl_label = "Sew & Simulate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            obj = build_garment(context)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        n = \
            sum(1 for e in obj.data.edges if e.is_loose)
        if context.window and not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        self.report({'INFO'}, f"Sewing {n} stitches. Watch it drape; Fit Map when it settles")
        return {'FINISHED'}


class FH_OT_unsew(bpy.types.Operator):
    """Delete the simulated garment and go back to the separate pieces"""
    bl_idname = "fashionhov.unsew"
    bl_label = "Back to Pieces"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.window and context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        remove_garment(context)
        return {'FINISHED'}


classes = (FH_OT_arrange, FH_OT_simulate, FH_OT_unsew)


def register():
    bpy.utils.register_class(FHPlace)
    bpy.types.Object.fh_place = bpy.props.PointerProperty(type=FHPlace)


def unregister():
    del bpy.types.Object.fh_place
    bpy.utils.unregister_class(FHPlace)
