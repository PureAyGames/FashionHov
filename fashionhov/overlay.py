"""Viewport drawing.

* Panel edge lengths + width x height labels (2D pattern).
* Seams, drawn in the SAME colour with the SAME number everywhere they
  exist: on the flat panels, on the 3D pieces and on the sewn garment.
  In 2D, thin threads connect the matching points of the two edges.
* Tape-measure lines on the avatar where it was measured.
"""

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from .core import geometry as geo
from .util import fmt_len, world_outline, panels
from . import sewing

_handles = []
MAX_LABELLED_EDGES = 60
_cache = {}


def _lines(coords, color, width, strip=True, loop=False):
    if len(coords) < 2:
        return
    sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    region = bpy.context.region
    sh.uniform_float("viewportSize", (region.width, region.height))
    sh.uniform_float("lineWidth", width)
    sh.uniform_float("color", color)
    pts = list(coords) + ([coords[0]] if loop else [])
    batch_for_shader(sh, 'LINE_STRIP' if strip else 'LINES', {"pos": pts}).draw(sh)


def _piece_for(panel):
    for o in bpy.context.scene.objects:
        if o.get("fh_cloth_source") == panel.name and o.visible_get():
            return o
    return None


def _piece_side(piece, chain_pts):
    from .arrange import boundary_on_chain
    key = (piece.name, len(piece.data.vertices), tuple(map(tuple, chain_pts)))
    if key not in _cache:
        if len(_cache) > 256:
            _cache.clear()
        _cache[key] = [i for i, _ in boundary_on_chain(piece, chain_pts)]
    mw = piece.matrix_world
    verts = piece.data.vertices
    return [tuple(mw @ verts[i].co) for i in _cache[key]]


def _garment_sides(seam):
    g = bpy.data.objects.get("FH Garment")
    if not g or not g.visible_get():
        return []
    sv = g.get("fh_seam_verts", {}).get(str(seam.number))
    if not sv:
        return []
    ev = g.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    mw = g.matrix_world
    out = []
    for side in ("a", "b"):
        idx = [i for i in sv[side] if i < len(ev.vertices)]
        out.append([tuple(mw @ ev.vertices[i].co) for i in idx])
    return out


def seam_geometry(seam):
    """[(polyline_3d, is_2d)] for every place this seam is shown, plus 2D threads."""
    a, b = sewing.seam_chains(seam)
    if len(a) < 2 or len(b) < 2:
        return [], []
    za = seam.a_obj.matrix_world.translation.z + 0.002
    zb = seam.b_obj.matrix_world.translation.z + 0.002
    shapes = [([(x, y, za) for x, y in a], True), ([(x, y, zb) for x, y in b], True)]
    threads = []
    if seam.a_obj.visible_get() and seam.b_obj.visible_get():
        n = 7
        sa = sewing.sample(a, n)
        sb = sewing.sample(b, n)
        if seam.flip:
            sb = sb[::-1]
        for p, q in zip(sa, sb):
            threads += [(p[0], p[1], za), (q[0], q[1], zb)]
    for panel, ch in ((seam.a_obj, a), (seam.b_obj, b)):
        piece = _piece_for(panel)
        if piece:
            shapes.append((_piece_side(piece, ch), False))
    for side in _garment_sides(seam):
        shapes.append((side, False))
    return shapes, threads


def draw_view():
    scene = bpy.context.scene
    if not getattr(scene, "fh", None):
        return
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    for seam in scene.fh_seams:
        shapes, threads = seam_geometry(seam)
        col = tuple(seam.color)
        for pts, _ in shapes:
            _lines(pts, col, 5.0)
        if threads:
            _lines(threads, (col[0], col[1], col[2], 0.5), 1.5, strip=False)
    body = getattr(scene, "fh_body", None)
    if body and body.avatar and scene.fh.show_measurements and body.avatar.visible_get():
        from .avatar import TAPES
        from .core.bodymeasure import convex_hull
        for key, (z, pts) in TAPES.get(body.avatar.name, {}).items():
            hull = pts if key == "shoulders" else convex_hull(pts)
            _lines([(x, y, z) for x, y in hull], (1, 0.85, 0.2, 0.9), 2.0, loop=key != "shoulders")
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _label(region, rv3d, p3, text, color=(1, 1, 1, 1), size=12, dx=4, dy=4):
    p = location_3d_to_region_2d(region, rv3d, Vector(p3))
    if p:
        blf.size(0, size)
        blf.color(0, *color)
        blf.position(0, p.x + dx, p.y + dy, 0)
        blf.draw(0, text)


def draw_pixel():
    context = bpy.context
    scene = context.scene
    if not getattr(scene, "fh", None):
        return
    region, rv3d = context.region, context.region_data
    if not rv3d:
        return
    if scene.fh.show_measurements:
        for obj in panels(scene):
            if not obj.visible_get():
                continue
            pts = world_outline(obj)
            if len(pts) < 2:
                continue
            z = obj.matrix_world.translation.z
            if len(pts) <= MAX_LABELLED_EDGES:
                n = len(pts)
                for i in range(n):
                    a, b = pts[i], pts[(i + 1) % n]
                    _label(region, rv3d, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, z),
                           fmt_len(context, geo.edge_lengths([a, b], closed=False)[0]), (1.0, 0.95, 0.6, 1.0))
            x0, y0, x1, y1 = geo.bbox(pts)
            _label(region, rv3d, ((x0 + x1) / 2, y1, z),
                   f"{obj.name}: {fmt_len(context, x1 - x0)} W × {fmt_len(context, y1 - y0)} H",
                   (0.5, 0.85, 1.0, 1.0), 12, -40, 14)
    for seam in scene.fh_seams:
        shapes, _ = seam_geometry(seam)
        for pts, _ in shapes:
            if pts:
                mid = pts[len(pts) // 2]
                _label(region, rv3d, mid, f"#{seam.number}", tuple(seam.color), 15, 6, 6)
    body = getattr(scene, "fh_body", None)
    if body and body.avatar and scene.fh.show_measurements and body.avatar.visible_get():
        from .avatar import TAPES, LABELS
        m = body.avatar.get("fh_measured", {})
        for key, (z, pts) in TAPES.get(body.avatar.name, {}).items():
            front = min(pts, key=lambda p: p[1]) if key != "shoulders" else pts[1]
            _label(region, rv3d, (front[0], front[1], z),
                   f"{LABELS.get(key, key)} {fmt_len(context, m.get(key, 0))}", (1, 0.85, 0.2, 1), 12, 8, 0)


def register():
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_view, (), 'WINDOW', 'POST_VIEW'))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_pixel, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    for h in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
    _handles.clear()
