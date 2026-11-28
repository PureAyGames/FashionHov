"""Quick-add pockets and fly shields that become real, editable panels.

A pocket is a detail ("modifier") on its parent panel AND a normal panel of
its own: Tab into it and reshape it like any other piece. It stays owned by
its detail, so switching the detail off hides the pocket everywhere (viewport,
simulation, thread, export) without deleting anything.

  Jeans back pocket / patch / coin : sits on the parent; sewn onto it along
      every edge except the opening in the simulation.
  Front scoop pocket : cuts a curved opening into the parent's paper pattern
      and makes facing + pocket bag pieces for cutting. (In the simulation the
      facing sits right behind the opening, so the front keeps its fabric.)
  Fly shield : made with a fly zipper; a pattern piece for cutting.
"""

import math
import bpy
from mathutils import Matrix, Vector

from . import features as ft
from .core import derive as dv
from .core import geometry as geo

PATCH_SHAPES = {
    #           top width, height, bottom width, point depth
    'JEANS': (0.140, 0.150, 0.135, 0.015),
    'PATCH': (0.160, 0.180, 0.160, 0.0),
    'COIN': (0.085, 0.070, 0.085, 0.0),
}
LABELS = {'JEANS': "Back Pocket", 'PATCH': "Pocket", 'COIN': "Coin Pocket", 'SCOOP': "Front Pocket"}


def _next_slot(scene):
    return max([o.get("fh_uv_slot", 0) for o in scene.objects] + [0]) + 1


# start offsets from the parent (outside +, inside -), in the real layer order
ROLE_BUMP = {'POCKET': 0.005, 'BAG_FRONT': -0.003, 'FACING': -0.006, 'BAG': -0.009, 'SHIELD': -0.004}


def _child_panel(context, parent, pts, name, item_id, role, layout=(0.0, 0.0)):
    """A real panel owned by a detail on `parent`.

    pts are where the piece sits ON the parent (its "home"). Inner pieces
    (facing, bag, fly shield) are then laid out beside the parent by `layout`
    so the pattern stays readable, but they still know their home: that's
    where they go in the simulation, whatever you do to the layout."""
    from .trace import create_panel
    child = create_panel(context, pts, name)
    child["fh_feature_of"] = parent.name
    child["fh_feature_id"] = item_id
    child["fh_uv_slot"] = _next_slot(context.scene)
    child["fh_role"] = role
    child["fh_auto_shape"] = [list(p) for p in pts]
    mw = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = mw
    context.view_layer.update()
    child["fh_home_local"] = list((parent.matrix_world.inverted() @ child.matrix_world).translation)
    child.matrix_world = Matrix.Translation((layout[0], layout[1], 0)) @ child.matrix_world
    child.fh_grade.girth = parent.fh_grade.girth
    child.fh_grade.length = parent.fh_grade.length
    mat = bpy.data.materials.get("FH Pocket") or bpy.data.materials.new("FH Pocket")
    mat.diffuse_color = (1.0, 0.75, 0.3, 0.35)
    child.data.materials.clear()
    child.data.materials.append(mat)
    context.view_layer.update()
    return child


def home_delta(child):
    """How far a child panel's layout position is from its home on the parent (world XY)."""
    if child.get("fh_role", "POCKET") == 'POCKET' or "fh_home_local" not in child or child.parent is None:
        return (0.0, 0.0)
    home = child.parent.matrix_world @ Vector(child["fh_home_local"])
    t = child.matrix_world.translation
    return (t.x - home.x, t.y - home.y)


def update_child_shape(context, child, new_pts):
    """Move a child panel to a freshly generated shape (in parent space), but leave
    alone every point you moved by hand since it was last generated."""
    from .sewing import ensure_vids
    last = [tuple(p) for p in child.get("fh_auto_shape", [])]
    new_pts = [tuple(p) for p in new_pts]
    dx, dy = home_delta(child)
    me = child.data
    mwi = child.matrix_world.inverted()
    z = child.matrix_world.translation.z
    attr = me.attributes.get("fh_vid")
    if len(last) != len(new_pts) or attr is None:
        me.clear_geometry()
        me.from_pydata([tuple(mwi @ Vector((x + dx, y + dy, z))) for x, y in new_pts], [],
                       [list(range(len(new_pts)))])
        child["fh_vid_next"] = 1
        ensure_vids(child)
    else:
        mw = child.matrix_world
        for i, v in enumerate(me.vertices):
            k = attr.data[i].value - 1          # generated points have vids 1..n in order
            if not 0 <= k < len(new_pts):
                continue                         # a point you added: yours
            w = mw @ v.co
            if math.dist((w.x - dx, w.y - dy), last[k]) < 1e-5:
                v.co = mwi @ Vector((new_pts[k][0] + dx, new_pts[k][1] + dy, z))
        me.update()
    child["fh_auto_shape"] = [list(p) for p in new_pts]
    ft.mark_ours(child)
    ft.invalidate(child)


def patch_outline(kind, center):
    """CCW outline, top edge first-to-last = opening. Starts top-left, goes down."""
    tw, h, bw, point = PATCH_SHAPES[kind]
    cx, cy = center
    top = cy + h / 2
    pts = [(cx - tw / 2, top), (cx - bw / 2, top - h)]
    if point > 0:
        pts.append((cx, top - h - point))
    pts += [(cx + bw / 2, top - h), (cx + tw / 2, top)]
    return pts


def add_patch_pocket(context, parent, center, kind='JEANS', rivets=None):
    f = parent.fh_features
    item = f.pockets.add()
    item.id = ft.new_id(parent)
    item.kind = kind
    pts = patch_outline(kind, center)
    child = _child_panel(context, parent, pts, f"{parent.name} {LABELS[kind]}", item.id, 'POCKET')
    item.piece = child
    # opening = last vertex -> first vertex; sewn = first -> last (vids 1..n)
    vids = [v for v, _ in ft.base_outline(child)]
    item.attach_va, item.attach_vb = vids[0], vids[-1]
    item.topstitch = 'DOUBLE' if kind == 'JEANS' else 'SINGLE'
    if rivets if rivets is not None else kind == 'JEANS':
        for corner in (pts[0], pts[-1]):
            hw = child.fh_features.hardware.add()
            hw.id, hw.kind, hw.size, hw.finish = ft.new_id(child), 'RIVET', ft.HW_SIZE['RIVET'], 'COPPER'
            inward = (0.006 if corner[0] < center[0] else -0.006, -0.006)
            ft.set_hardware_world(child, hw, (corner[0] + inward[0], corner[1] + inward[1]))
    ft.request_rebuild(parent)
    ft.request_rebuild(child)
    return item


def nearest_corner(panel, xy):
    base = ft.base_outline(panel)
    return min(base, key=lambda b: math.dist(b[1], xy))[0]


def scoop_shapes(parent, item):
    """Facing and bag outlines for a scoop pocket, from the parent as it is now."""
    d = ft.get_derived(parent)
    sc = next((x for x in d.scoops if x["id"] == item.id), None)
    if sc is None:
        return None, None
    i = d.index_of_vid(item.corner)
    c, A, B = sc["corner"], sc["A"], sc["B"]
    under = 0.035
    A2 = dv._arc_from(d, i, item.width + under, -1)
    B2 = dv._arc_from(d, i, item.depth + under, +1)
    inner = dv.offset_polyline(sc["ext"], under)
    facing = [A2, c, B2] + inner[::-1]
    item["fh_facing_attach"] = [list(p) for p in inner]
    # bag: hangs from the edge after the corner (usually the waist), down past the opening
    n_b = dv.left(dv.norm(dv.sub(B, c)))
    n_a = dv.left(dv.norm(dv.sub(c, A)))
    Bf = dv._arc_from(d, i, item.depth + 0.05, +1)
    Af = dv._arc_from(d, i, item.width + 0.06, -1)
    bag_depth = max(item.width, 0.1) + 0.12
    D, E = dv.add(Bf, dv.mul(n_b, bag_depth)), dv.add(Af, dv.mul(n_a, 0.05))
    bag = [Af, c, Bf, D, E]
    # front layer of the bag: sewn to the opening edge, so it stops at the curve
    bag_front = [Af] + list(sc["ext"]) + [Bf, D, E]
    item["fh_bag_front"] = [list(p) for p in bag_front]
    item["fh_bag_join"] = [list(p) for p in (Bf, D, E, Af)]       # the two bag layers sewn together here
    item["fh_opening"] = [list(p) for p in sc["ext"]]
    for poly in (facing, bag):
        if geo.signed_area(poly) < 0:
            poly.reverse()
    return facing, bag


def add_scoop_pocket(context, parent, corner_vid, rivets=True):
    f = parent.fh_features
    item = f.pockets.add()
    item.id = ft.new_id(parent)
    item.kind = 'SCOOP'
    item.corner = corner_vid
    item.in_sim = True
    ft.invalidate(parent)
    make_scoop_pieces(context, parent, item)
    if rivets:
        d = ft.get_derived(parent)
        sc = next(x for x in d.scoops if x["id"] == item.id)
        for end, other in ((sc["A"], sc["B"]), (sc["B"], sc["A"])):
            hw = f.hardware.add()
            hw.id, hw.kind, hw.size, hw.finish = ft.new_id(parent), 'RIVET', ft.HW_SIZE['RIVET'], 'COPPER'
            step = dv.mul(dv.norm(dv.sub(other, end)), 0.008)
            ft.set_hardware_world(parent, hw, dv.add(end, step))
    ft.request_rebuild(parent)
    return item


def _beside(parent):
    xs = [p[0] for _, p in ft.base_outline(parent)]
    return max(xs) - min(xs) + 0.08


def _bag_front_poly(item):
    pts = [tuple(p) for p in item["fh_bag_front"]]
    return pts if geo.signed_area(pts) > 0 else pts[::-1]


def make_scoop_pieces(context, parent, item):
    """(Re)make the facing and bag panels of a scoop pocket, laid out beside the parent."""
    for attr in ("facing", "bag", "bag_front"):
        old = getattr(item, attr)
        if old:
            delete_panel(old)
    facing, bag = scoop_shapes(parent, item)
    if facing is None:
        return
    dx = _beside(parent)
    ys = [p[1] for p in bag]
    item.facing = _child_panel(context, parent, facing, f"{parent.name} Pocket Facing", item.id,
                               'FACING', (dx, 0.0))
    item.facing["fh_attach_line"] = item["fh_facing_attach"]
    item.bag = _child_panel(context, parent, bag, f"{parent.name} Pocket Bag", item.id,
                            'BAG', (dx, -(max(ys) - min(ys)) - 0.05))
    item.bag["fh_cut_count"] = 2
    # The bag's front layer: same pocketing, sewn to the opening edge. It's the
    # same pattern piece (cut 2), so it is simulation-only and stays hidden.
    bf = _child_panel(context, parent, _bag_front_poly(item), f"{parent.name} Pocket Bag Front Layer", item.id,
                      'BAG_FRONT', (dx, -(max(ys) - min(ys)) - 0.05))
    bf["fh_sim_only"] = True
    bf["fh_attach_line"] = item["fh_opening"]
    item.bag_front = bf


def shield_shape(parent, zipper):
    """Fly shield where it sits: behind the fly extension, from just inside the
    centre-front line out under the fly. Returns (outline, attach line)."""
    path = ft.zipper_path(parent, zipper)
    if len(path) < 2:
        return None, None
    inner = dv.offset_polyline(path, 0.01)             # 1 cm inside CF: stitched here
    outer = dv.offset_polyline(path, -zipper.fly_width * 0.9)
    pts = inner + outer[::-1]
    if geo.signed_area(pts) < 0:
        pts.reverse()
    return pts, inner


def add_fly_shield(context, parent, zipper):
    """Fly shield piece for a fly zipper: pattern piece + sits behind the fly in the sim."""
    if zipper.child:
        delete_panel(zipper.child)
    ft.invalidate(parent)
    pts, attach = shield_shape(parent, zipper)
    if pts is None:
        return None
    dx = _beside(parent) + 0.02
    zipper.child = _child_panel(context, parent, pts, f"{parent.name} Fly Shield", zipper.id, 'SHIELD', (dx, 0.0))
    zipper.child["fh_attach_line"] = [list(p) for p in attach]
    return zipper.child


def regenerate(context, parent):
    """Keep facing / bag / fly shield matched to the parent's current opening and fly."""
    ft.invalidate(parent)
    for item in parent.fh_features.pockets:
        if item.kind != 'SCOOP' or not (item.facing or item.bag):
            continue
        facing, bag = scoop_shapes(parent, item)
        if facing is None:
            continue
        if item.facing:
            update_child_shape(context, item.facing, facing)
            item.facing["fh_attach_line"] = item["fh_facing_attach"]
        if item.bag:
            update_child_shape(context, item.bag, bag)
        if item.bag_front:
            update_child_shape(context, item.bag_front, _bag_front_poly(item))
            item.bag_front["fh_attach_line"] = item["fh_opening"]
    for z in parent.fh_features.hardware:
        if z.kind == 'ZIPPER' and z.style == 'FLY' and z.child:
            pts, attach = shield_shape(parent, z)
            if pts:
                update_child_shape(context, z.child, pts)
                z.child["fh_attach_line"] = [list(p) for p in attach]


def delete_panel(obj):
    """Remove a child panel and its cloth piece."""
    if obj is None:
        return
    for o in list(bpy.data.objects):
        if o.get("fh_cloth_source") == obj.name:
            me = o.data
            bpy.data.objects.remove(o)
            if me and me.users == 0:
                bpy.data.meshes.remove(me)
    me = obj.data
    bpy.data.objects.remove(obj)
    if me and me.users == 0:
        bpy.data.meshes.remove(me)


def delete_item_children(item):
    for attr in ("piece", "facing", "bag", "bag_front", "child"):
        o = getattr(item, attr, None)
        if o:
            delete_panel(o)


# ---------- operators ----------

class FH_OT_pocket_select(bpy.types.Operator):
    """Select this pocket's panel so you can reshape it (Tab into Edit Mode)"""
    bl_idname = "fashionhov.pocket_select"
    bl_label = "Edit Pocket Panel"

    name: bpy.props.StringProperty()

    def execute(self, context):
        o = bpy.data.objects.get(self.name)
        if not o:
            return {'CANCELLED'}
        for x in context.selected_objects:
            x.select_set(False)
        o.hide_set(False)
        o.select_set(True)
        context.view_layer.objects.active = o
        return {'FINISHED'}


class FH_OT_pocket_reset(bpy.types.Operator):
    """Regenerate this pocket's panels from its settings (throws away hand edits to them)"""
    bl_idname = "fashionhov.pocket_reset"
    bl_label = "Reset Pocket Shape"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        parent = context.active_object
        item = parent.fh_features.pockets[self.index]
        if item.kind == 'SCOOP':
            make_scoop_pieces(context, parent, item)
        elif item.piece:
            c = item.piece
            pts = [p for _, p in ft.base_outline(c)]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            new = patch_outline(item.kind, (cx, cy))
            me = c.data
            mwi = c.matrix_world.inverted()
            if len(me.vertices) == len(new):
                for v, (x, y) in zip(me.vertices, new):
                    v.co = mwi @ Vector((x, y, c.matrix_world.translation.z))
                me.update()
            ft.request_rebuild(c)
        ft.request_rebuild(parent)
        return {'FINISHED'}


classes = (FH_OT_pocket_select, FH_OT_pocket_reset)
