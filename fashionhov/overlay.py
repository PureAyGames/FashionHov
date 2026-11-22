"""Viewport labels: every panel edge length plus overall width x height."""

import bpy
import blf
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from .core import geometry as geo
from .util import fmt_len, world_outline, panels

_handle = None
MAX_LABELLED_EDGES = 60


def draw(context=None):
    context = bpy.context
    scene = context.scene
    if not getattr(scene, "fh", None) or not scene.fh.show_measurements:
        return
    region, rv3d = context.region, context.region_data
    if not rv3d:
        return
    blf.size(0, 12)
    for obj in panels(scene):
        if not obj.visible_get():
            continue
        pts = world_outline(obj)
        if len(pts) < 2:
            continue
        z = obj.matrix_world.translation.z
        to_px = lambda p: location_3d_to_region_2d(region, rv3d, Vector((p[0], p[1], z)))
        if len(pts) <= MAX_LABELLED_EDGES:
            blf.color(0, 1.0, 0.95, 0.6, 1.0)
            n = len(pts)
            for i in range(n):
                a, b = pts[i], pts[(i + 1) % n]
                mid = to_px(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
                if mid:
                    blf.position(0, mid.x + 4, mid.y + 4, 0)
                    blf.draw(0, fmt_len(context, geo.edge_lengths([a, b], closed=False)[0]))
        x0, y0, x1, y1 = geo.bbox(pts)
        top = to_px(((x0 + x1) / 2, y1))
        if top:
            blf.color(0, 0.5, 0.85, 1.0, 1.0)
            label = f"{obj.name}: {fmt_len(context, x1 - x0)} W × {fmt_len(context, y1 - y0)} H"
            w, _ = blf.dimensions(0, label)
            blf.position(0, top.x - w / 2, top.y + 14, 0)
            blf.draw(0, label)


def register():
    global _handle
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _handle
    if _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
