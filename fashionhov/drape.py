"""Hand drape test: a fabric swatch falls over a hand so you can match the
drape slider to how a real fabric looks draped over your own hand."""

import math
import bpy
from mathutils import Euler, Matrix, Vector

from . import fabric
from .cloth import triangulate_panel

TEST_SCENE = "FashionHov Drape Test"
SURFACE = 0.52          # metaball visible radius / element radius (isolated capsule)
FRAMES = 120
HOLD_RADIUS = 0.015

# (x offset, length, radius) for index..pinky at average adult size; right hand, palm up.
FINGERS = [(0.026, 0.075, 0.0085), (0.008, 0.082, 0.0088), (-0.010, 0.077, 0.0083), (-0.027, 0.062, 0.0075)]
PHALANX = (0.45, 0.30, 0.25)
SPREAD = (-6, 0, 5, 11)          # degrees, fingers fan out a little
POSES = {
    #        finger joint bends (deg)  thumb bends
    'FLAT': ((4, 4, 2), (5, 5)),
    'FIST': ((85, 100, 65), (35, 50)),
    'UP':   ((4, 4, 2), (5, 5)),     # flat hand turned fingers-up
}


def _capsule(mb, a, b, r_surface):
    a, b = Vector(a), Vector(b)
    d = b - a
    el = mb.elements.new(type='CAPSULE')
    el.co = (a + b) / 2
    el.radius = r_surface / SURFACE
    el.size_x = d.length / 2
    el.rotation = Vector((1, 0, 0)).rotation_difference(d.normalized())
    return el


def _chain(mb, start, direction, lengths, bends, radius, curl_axis):
    p = Vector(start)
    d = Vector(direction).normalized()
    r = radius
    for length, bend in zip(lengths, bends):
        d = Matrix.Rotation(math.radians(bend), 3, curl_axis) @ d
        q = p + d * length
        _capsule(mb, p, q, r)
        p = q
        r *= 0.9
    return p


def build_hand(context, pose='FLAT', scale=1.0, name="FH Hand"):
    mb = bpy.data.metaballs.new(name)
    mb.resolution = mb.render_resolution = 0.003
    mb.threshold = 0.6
    finger_bends, thumb_bends = POSES[pose]

    # Palm: metacarpals blended into a slab, plus wrist and forearm.
    for x, _, _ in FINGERS:
        _capsule(mb, (x * 0.95, -0.045, 0), (x, 0.045, 0), 0.0135)
    _capsule(mb, (0, -0.05, 0), (0, -0.20, -0.005), 0.026)

    for (x, length, r), spread in zip(FINGERS, SPREAD):
        d = Matrix.Rotation(math.radians(spread), 3, 'Z') @ Vector((0, 1, 0))
        axis = d.cross(Vector((0, 0, 1))).normalized()   # bend toward +Z (palm up)
        _chain(mb, (x, 0.05, 0), d, [length * f for f in PHALANX], finger_bends, r, axis)

    td = Vector((math.cos(math.radians(50)), math.sin(math.radians(50)), 0.15))
    taxis = Vector((-0.6, 0.6, 1.0)).normalized()
    _chain(mb, (0.032, -0.035, 0), td, [0.045, 0.034, 0.028], (0,) + thumb_bends, 0.011, taxis)

    tmp = bpy.data.objects.new(name + "_mb", mb)
    context.scene.collection.objects.link(tmp)
    dg = context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.metaballs.remove(mb)

    xf = Matrix.Scale(scale, 4)
    if pose == 'UP':
        xf = xf @ Matrix.Rotation(math.radians(90), 4, 'X')
    me.transform(xf)
    for p in me.polygons:
        p.use_smooth = True

    obj = bpy.data.objects.new(name, me)
    context.scene.collection.objects.link(obj)
    obj["fh_hand"] = True
    obj.modifiers.new("Collision", 'COLLISION')
    obj.collision.thickness_outer = 0.002
    obj.collision.cloth_friction = 40.0
    obj.collision.damping = 1.0
    return obj


def build_swatch(context, hand, width, height, spacing, fabric_src, name="FH Swatch"):
    rect = [(-width / 2, -height / 2), (width / 2, -height / 2), (width / 2, height / 2), (-width / 2, height / 2)]
    verts, faces = triangulate_panel(rect, spacing)
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, 0) for x, y in verts], [], faces)
    obj = bpy.data.objects.new(name, me)
    context.scene.collection.objects.link(obj)

    zs = [v.co.z for v in hand.data.vertices]
    top = max(zs)
    # Centre over the palm for flat/fist, over the fingertips for fingers-up.
    if hand.get("fh_pose") == 'UP':
        tip = max(hand.data.vertices, key=lambda v: v.co.z).co
        cx, cy = tip.x, tip.y
    else:
        cx, cy = 0.0, 0.0    # palm centre
    obj.matrix_world = Matrix.Translation((cx, cy, top + 0.006))
    obj["fh_swatch"] = True
    fabric.copy_fabric(fabric_src, obj.fh_fabric)
    mod = fabric.ensure_cloth(obj)
    mod.point_cache.frame_start = 1
    mod.point_cache.frame_end = FRAMES
    mod.collision_settings.friction = 40.0
    # Hold the centre like your thumb would, so stiff fabric can't slide off.
    hold = obj.vertex_groups.new(name="FH Hold")
    hold.add([v.index for v in me.vertices if v.co.xy.length < HOLD_RADIUS], 1.0, 'REPLACE')
    mod.settings.vertex_group_mass = hold.name
    return obj


def rebuild(context, test_scene, fabric_src=None):
    """(Re)build hand + swatch in the drape test scene with its current settings.

    The fabric comes from fabric_src if given, otherwise from the swatch
    already in the scene, so tweaks survive a pose / size change.
    """
    s = test_scene.fh
    old_swatch = next((o for o in test_scene.objects if o.get("fh_swatch")), None)
    carrier = s.fabric
    if fabric_src is not None:
        fabric.copy_fabric(fabric_src, carrier)
    elif old_swatch:
        fabric.copy_fabric(old_swatch.fh_fabric, carrier)
    for o in list(test_scene.objects):
        if o.get("fh_swatch") or o.get("fh_hand"):
            me = o.data
            bpy.data.objects.remove(o)
            if me and me.users == 0:
                bpy.data.meshes.remove(me)

    with context.temp_override(scene=test_scene):
        ctx = bpy.context
        hand = build_hand(ctx, s.hand_pose, s.hand_scale)
        hand["fh_pose"] = s.hand_pose
        swatch = build_swatch(ctx, hand, s.swatch_width, s.swatch_height, s.swatch_detail, carrier)
    test_scene.frame_start, test_scene.frame_end = 1, FRAMES
    test_scene.frame_set(1)
    return hand, swatch


def get_or_make_test_scene(context):
    sc = bpy.data.scenes.get(TEST_SCENE)
    if sc is None:
        sc = bpy.data.scenes.new(TEST_SCENE)
        src_units = context.scene.unit_settings
        sc.unit_settings.system = src_units.system
        sc.unit_settings.length_unit = src_units.length_unit
        sc.fh.units = context.scene.fh.units
    return sc


class FH_OT_drape_test(bpy.types.Operator):
    """Open a scene with a hand and a fabric swatch to see how this fabric drapes"""
    bl_idname = "fashionhov.drape_test"
    bl_label = "Hand Drape Test"

    def execute(self, context):
        origin = context.scene
        obj = context.active_object
        src = obj.fh_fabric if obj and obj.modifiers.get("FH Cloth") else origin.fh.fabric
        sc = get_or_make_test_scene(context)
        sc.fh.drape_return_scene = origin.name
        sc.fh.drape_source = obj.name if obj and obj.modifiers.get("FH Cloth") else ""
        hand, swatch = rebuild(context, sc, src)
        if context.window:
            context.window.scene = sc
            for o in sc.objects:
                o.select_set(False)
            swatch.select_set(True)
            sc.view_layers[0].objects.active = swatch
            _frame_view(context, hand)
            bpy.ops.screen.animation_play()
        return {'FINISHED'}


def _frame_view(context, hand):
    area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
    if not area:
        return
    space = area.spaces.active
    space.shading.type = 'SOLID'
    space.shading.color_type = 'MATERIAL'
    r3d = space.region_3d
    r3d.view_perspective = 'PERSP'
    r3d.view_location = (0, 0, 0.02)
    r3d.view_rotation = Euler((math.radians(62), 0, math.radians(25))).to_quaternion()
    r3d.view_distance = 0.55


class FH_OT_drape_rebuild(bpy.types.Operator):
    """Rebuild the hand and swatch with the new pose / size, keep the fabric, and replay"""
    bl_idname = "fashionhov.drape_rebuild"
    bl_label = "Rebuild & Replay"

    @classmethod
    def poll(cls, context):
        return context.scene.name == TEST_SCENE

    def execute(self, context):
        rebuild(context, context.scene)
        if context.window and not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        return {'FINISHED'}


class FH_OT_drape_replay(bpy.types.Operator):
    """Drop the swatch again"""
    bl_idname = "fashionhov.drape_replay"
    bl_label = "Replay"

    def execute(self, context):
        context.scene.frame_set(1)
        if context.window and not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()
        return {'FINISHED'}


class FH_OT_drape_done(bpy.types.Operator):
    """Go back to your project. Optionally copy the tuned fabric to the garment piece you came from"""
    bl_idname = "fashionhov.drape_done"
    bl_label = "Done"

    apply: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return context.scene.name == TEST_SCENE

    def execute(self, context):
        sc = context.scene
        swatch = next((o for o in sc.objects if o.get("fh_swatch")), None)
        back = bpy.data.scenes.get(sc.fh.drape_return_scene)
        if context.window and context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        if self.apply and swatch and back:
            target = back.objects.get(sc.fh.drape_source)
            dst = target.fh_fabric if target else back.fh.fabric
            fabric.copy_fabric(swatch.fh_fabric, dst)
            if target:
                fabric.apply_to_object(target)
            self.report({'INFO'}, f"Fabric copied to {target.name if target else 'default fabric'}")
        if back and context.window:
            context.window.scene = back
        return {'FINISHED'}


classes = (FH_OT_drape_test, FH_OT_drape_rebuild, FH_OT_drape_replay, FH_OT_drape_done)
