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
from mathutils import Vector

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


def _child_panel(context, parent, pts, name, item_id, sim):
    """A real panel owned by a detail on `parent`."""
    from .trace import create_panel
    child = create_panel(context, pts, name)
    child["fh_feature_of"] = parent.name
    child["fh_feature_id"] = item_id
    child["fh_uv_slot"] = _next_slot(context.scene)
    child["fh_sim"] = sim
    mw = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    child.matrix_world = mw
    child.fh_grade.girth = parent.fh_grade.girth
    child.fh_grade.length = parent.fh_grade.length
    mat = bpy.data.materials.get("FH Pocket") or bpy.data.materials.new("FH Pocket")
    mat.diffuse_color = (1.0, 0.75, 0.3, 0.35)
    child.data.materials.clear()
    child.data.materials.append(mat)
    context.view_layer.update()
    return child


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
    child = _child_panel(context, parent, pts, f"{parent.name} {LABELS[kind]}", item.id, True)
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
    # bag: hangs from the edge after the corner (usually the waist), down past the opening
    n_b = dv.left(dv.norm(dv.sub(B, c)))
    n_a = dv.left(dv.norm(dv.sub(c, A)))
    Bf = dv._arc_from(d, i, item.depth + 0.05, +1)
    Af = dv._arc_from(d, i, item.width + 0.06, -1)
    bag_depth = max(item.width, 0.1) + 0.12
    bag = [Af, c, Bf, dv.add(Bf, dv.mul(n_b, bag_depth)), dv.add(Af, dv.mul(n_a, 0.05))]
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
    item.in_sim = False
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


def make_scoop_pieces(context, parent, item):
    """(Re)make the facing and bag panels of a scoop pocket, laid out beside the parent."""
    for attr in ("facing", "bag"):
        old = getattr(item, attr)
        if old:
            delete_panel(old)
    facing, bag = scoop_shapes(parent, item)
    if facing is None:
        return
    dx = _beside(parent)
    shift = lambda pts, dy: [(x + dx, y + dy) for x, y in pts]
    ys = [p[1] for p in bag]
    item.facing = _child_panel(context, parent, shift(facing, 0.0), f"{parent.name} Pocket Facing", item.id, False)
    item.bag = _child_panel(context, parent, shift(bag, -(max(ys) - min(ys)) - 0.05),
                            f"{parent.name} Pocket Bag", item.id, False)


def add_fly_shield(context, parent, zipper):
    """Fly shield pattern piece for a fly zipper, laid out beside the parent."""
    if zipper.child:
        delete_panel(zipper.child)
    w, L = 2 * zipper.fly_width, zipper.length + 0.03
    path = ft.zipper_path(parent, zipper)
    if not path:
        return None
    x0 = max(p[0] for _, p in ft.base_outline(parent)) + 0.08
    y1 = max(p[1] for p in path)
    pts = [(x0, y1), (x0, y1 - L + w / 2), (x0 + w / 2, y1 - L), (x0 + w, y1 - L + w / 2), (x0 + w, y1)]
    if geo.signed_area(pts) < 0:
        pts.reverse()
    zipper.child = _child_panel(context, parent, pts, f"{parent.name} Fly Shield", zipper.id, False)
    return zipper.child


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
    for attr in ("piece", "facing", "bag", "child"):
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
