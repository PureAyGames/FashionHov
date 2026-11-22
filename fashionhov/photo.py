"""Reference photo: import, then calibrate to real-world scale.

The photo is a subdivided grid whose UVs never change. A 3x3 homography
(stored on the object) maps "image space" (u * aspect, v) to world XY in
metres. Calibrating just replaces that matrix and moves the grid vertices,
which also removes camera perspective when 4 corners are used.
"""

import math
import bpy
import gpu
import blf
import numpy as np
from gpu_extras.batch import batch_for_shader
from bpy_extras.io_utils import ImportHelper
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from .core import homography as hg
from .util import mouse_to_plane, fmt_len, panels

GRID = 48


def get_h(obj):
    return np.array(obj["fh_H"], dtype=float).reshape(3, 3)


def image_space_grid(aspect):
    n = GRID
    uv = np.array([(i / n, j / n) for j in range(n + 1) for i in range(n + 1)])
    img = uv * np.array([aspect, 1.0])
    return uv, img


def rebuild_grid(obj):
    aspect = obj["fh_aspect"]
    _, img = image_space_grid(aspect)
    world = hg.apply(get_h(obj), img)
    me = obj.data
    co = np.zeros(len(me.vertices) * 3)
    co[0::3], co[1::3] = world[:, 0], world[:, 1]
    me.vertices.foreach_set("co", co)
    me.update()


def create_photo_object(context, image):
    w, h = image.size
    aspect = (w / h) if h else 1.0
    uv, img = image_space_grid(aspect)
    n = GRID
    verts = [(x, y, 0.0) for x, y in img]
    faces = [(j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i)
             for j in range(n) for i in range(n)]
    me = bpy.data.meshes.new(f"Photo {image.name}")
    me.from_pydata(verts, [], faces)
    layer = me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        layer.data[loop.index].uv = uv[loop.vertex_index]

    mat = bpy.data.materials.new(f"Photo {image.name}")
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 1.0
    nt.nodes.active = tex
    me.materials.append(mat)

    obj = bpy.data.objects.new(f"Photo {image.name}", me)
    obj["fh_photo"] = True
    obj["fh_aspect"] = aspect
    obj["fh_H"] = list(np.eye(3).ravel())
    obj.location.z = -0.001
    obj.hide_select = True
    context.scene.collection.objects.link(obj)
    context.scene.fh.photo = obj
    return obj


def set_mapping(obj, h_new, scene):
    """Replace the photo calibration and carry traced panels along with it."""
    h_old_inv = hg.invert(get_h(obj))
    for p in panels(scene):
        if p.get("fh_photo_name") != obj.name:
            continue
        mw = p.matrix_world
        mwi = mw.inverted()
        world = np.array([(mw @ v.co).xy for v in p.data.vertices])
        moved = hg.apply(h_new, hg.apply(h_old_inv, world))
        for v, (x, y) in zip(p.data.vertices, moved):
            v.co = mwi @ Vector((x, y, (mw @ v.co).z))
        p.data.update()
    obj["fh_H"] = list(np.asarray(h_new).ravel())
    rebuild_grid(obj)


def calibrate_two_points(obj, p0, p1, real_length, scene):
    """Uniform scale so the distance p0-p1 (world XY) equals real_length."""
    d = math.dist(p0, p1)
    if d < 1e-9:
        raise ValueError("points are on top of each other")
    s = real_length / d
    set_mapping(obj, hg.scale(s) @ get_h(obj), scene)


def calibrate_four_points(obj, pts, width, height, scene):
    """Perspective-correct + scale from 4 clicked corners of a known rectangle."""
    img_pts = hg.apply(hg.invert(get_h(obj)), np.array(pts))
    h, _ = hg.rectify_quad(img_pts, width, height)
    set_mapping(obj, h, scene)


class FH_OT_import_photo(bpy.types.Operator, ImportHelper):
    """Import a top-down photo of a garment laid flat, with a ruler, paper or card in shot for scale"""
    bl_idname = "fashionhov.import_photo"
    bl_label = "Import Reference Photo"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: bpy.props.StringProperty(default="*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.webp;*.heic", options={'HIDDEN'})

    def execute(self, context):
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
        except RuntimeError as e:
            self.report({'ERROR'}, f"Could not load image: {e}")
            return {'CANCELLED'}
        create_photo_object(context, image)
        _top_view(context)
        self.report({'INFO'}, "Photo imported. Now calibrate scale with 2 points or 4 corners.")
        return {'FINISHED'}


def _top_view(context):
    area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None) if context.screen else None
    if not area:
        return
    space = area.spaces.active
    space.shading.type = 'SOLID'
    space.shading.color_type = 'TEXTURE'
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_axis(type='TOP')
        space.region_3d.view_perspective = 'ORTHO'
        bpy.ops.view3d.view_all(center=False)


class FH_OT_calibrate(bpy.types.Operator):
    """Click points on the photo to set its real-world scale"""
    bl_idname = "fashionhov.calibrate"
    bl_label = "Calibrate Photo"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=[
        ('TWO', "2 Points", "Click both ends of a known length, e.g. a ruler"),
        ('FOUR', "4 Corners", "Click the 4 corners of paper/card; also fixes camera tilt")])

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D' and context.scene.fh.photo

    def invoke(self, context, event):
        self.pts = []
        self.cursor = None
        self.need = 2 if self.mode == 'TWO' else 4
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        self._status(context)
        return {'RUNNING_MODAL'}

    def _status(self, context):
        what = "ends of your known length" if self.need == 2 else "corners of the reference rectangle"
        context.workspace.status_text_set(
            f"Click the {what} ({len(self.pts)}/{self.need})  •  Backspace: undo point  •  "
            "Esc: cancel  •  Middle mouse / wheel: navigate")

    def _finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        context.workspace.status_text_set(None)
        context.area.tag_redraw()

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            p = mouse_to_plane(context, event)
            self.cursor = tuple(p.xy) if p else None
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS' and self.cursor:
            self.pts.append(self.cursor)
            self._status(context)
            if len(self.pts) == self.need:
                return self._apply(context)
        elif event.type == 'BACK_SPACE' and event.value == 'PRESS' and self.pts:
            self.pts.pop()
            self._status(context)
        elif event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _apply(self, context):
        self._finish(context)
        s = context.scene.fh
        try:
            if self.mode == 'TWO':
                calibrate_two_points(s.photo, self.pts[0], self.pts[1], s.ref_distance, context.scene)
            else:
                calibrate_four_points(s.photo, self.pts, s.ref_width, s.ref_height, context.scene)
        except (ValueError, np.linalg.LinAlgError) as e:
            self.report({'ERROR'}, f"Calibration failed: {e}")
            return {'CANCELLED'}
        _top_view(context)
        self.report({'INFO'}, "Photo calibrated to real scale")
        return {'FINISHED'}

    def _draw(self, context):
        pts = list(self.pts) + ([self.cursor] if self.cursor and len(self.pts) < self.need else [])
        region, rv3d = context.region, context.region_data
        px = [location_3d_to_region_2d(region, rv3d, Vector((x, y, 0))) for x, y in pts]
        px = [p for p in px if p]
        if not px:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        shader.uniform_float("color", (1.0, 0.35, 0.1, 1.0))
        loop = px + ([px[0]] if self.need == 4 and len(px) == 4 else [])
        if len(loop) > 1:
            batch_for_shader(shader, 'LINE_STRIP', {"pos": [tuple(p) for p in loop]}).draw(shader)
        gpu.state.point_size_set(9)
        batch_for_shader(shader, 'POINTS', {"pos": [tuple(p) for p in px]}).draw(shader)
        gpu.state.point_size_set(1)
        blf.size(0, 14)
        for i, p in enumerate(px):
            blf.position(0, p.x + 8, p.y + 8, 0)
            blf.draw(0, str(i + 1))
        gpu.state.blend_set('NONE')


classes = (FH_OT_import_photo, FH_OT_calibrate)
