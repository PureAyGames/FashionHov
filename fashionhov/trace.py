"""Trace a pattern panel by clicking around its outline on the photo."""

import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector

from .core import geometry as geo
from .util import mouse_to_plane, fmt_len

PANEL_Z = 0.0
CLOSE_PX = 14


def create_panel(context, points, name="Panel", photo=None):
    """Make a flat panel object (one n-gon) from world XY points."""
    pts = list(points)
    if geo.signed_area(pts) < 0:
        pts.reverse()
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x - cx, y - cy, 0.0) for x, y in pts], [], [list(range(len(pts)))])
    obj = bpy.data.objects.new(name, me)
    obj.matrix_world = Matrix.Translation((cx, cy, PANEL_Z))
    obj["fh_panel"] = True
    if photo:
        obj["fh_photo_name"] = photo.name
    mat = bpy.data.materials.get("FH Panel") or bpy.data.materials.new("FH Panel")
    mat.diffuse_color = (0.2, 0.6, 1.0, 0.35)
    me.materials.append(mat)
    obj.show_wire = True
    obj.show_in_front = True
    context.scene.collection.objects.link(obj)
    from .sewing import ensure_vids
    ensure_vids(obj)
    return obj


class FH_OT_trace_panel(bpy.types.Operator):
    """Click around a garment piece on the photo to trace it as a pattern panel"""
    bl_idname = "fashionhov.trace_panel"
    bl_label = "Trace Panel"
    bl_options = {'REGISTER', 'UNDO'}

    panel_name: bpy.props.StringProperty(name="Name", default="Panel")

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D' and context.mode == 'OBJECT'

    def invoke(self, context, event):
        self.pts = []
        self.cursor = None
        self.snap = False
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(
            "Click: add point  •  Click first point / Enter: finish  •  Hold Ctrl: snap to 45°  •  "
            "Backspace: undo point  •  Esc: cancel  •  Middle mouse / wheel: navigate")
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        context.workspace.status_text_set(None)
        context.area.tag_redraw()

    def _px(self, context, p):
        return location_3d_to_region_2d(context.region, context.region_data, Vector((p[0], p[1], PANEL_Z)))

    def _near_first(self, context, event):
        if len(self.pts) < 3:
            return False
        first = self._px(context, self.pts[0])
        return first and (first - Vector((event.mouse_region_x, event.mouse_region_y))).length < CLOSE_PX

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            p = mouse_to_plane(context, event, PANEL_Z)
            if p:
                c = tuple(p.xy)
                if event.ctrl and self.pts:
                    c = geo.snap_angle(self.pts[-1], c)
                self.cursor = c
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS' and self.cursor:
            if self._near_first(context, event):
                return self._done(context)
            self.pts.append(self.cursor)
        elif event.type == 'BACK_SPACE' and event.value == 'PRESS' and self.pts:
            self.pts.pop()
        elif event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'} and event.value == 'PRESS':
            return self._done(context)
        elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._cleanup(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _done(self, context):
        self._cleanup(context)
        if len(self.pts) < 3:
            self.report({'WARNING'}, "A panel needs at least 3 points")
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        obj = create_panel(context, self.pts, self.panel_name, context.scene.fh.photo)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}

    def _draw(self, context):
        pts = list(self.pts) + ([self.cursor] if self.cursor else [])
        px = [self._px(context, p) for p in pts]
        if None in px or not px:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        shader.uniform_float("color", (0.2, 0.7, 1.0, 1.0))
        if len(px) > 1:
            batch_for_shader(shader, 'LINE_STRIP', {"pos": [tuple(p) for p in px]}).draw(shader)
        gpu.state.point_size_set(8)
        batch_for_shader(shader, 'POINTS', {"pos": [tuple(p) for p in px[:len(self.pts)]]}).draw(shader)
        gpu.state.point_size_set(1)
        blf.size(0, 13)
        blf.color(0, 1, 1, 1, 1)
        for a, b, pa, pb in zip(pts, pts[1:], px, px[1:]):
            mid = (pa + pb) / 2
            blf.position(0, mid.x + 6, mid.y + 6, 0)
            blf.draw(0, fmt_len(context, ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5))
        if len(pts) > 1:
            total = sum(geo.edge_lengths(pts, closed=False))
            blf.position(0, px[-1].x + 14, px[-1].y - 18, 0)
            blf.draw(0, f"total {fmt_len(context, total)}")
        gpu.state.blend_set('NONE')


classes = (FH_OT_trace_panel,)
