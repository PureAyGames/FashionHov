"""Turn a 2D pattern panel into a simulation-ready cloth mesh with real fabric weight."""

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import delaunay_2d_cdt

from .core import geometry as geo
from . import fabric
from .util import world_outline


def triangulate_panel(outline, spacing):
    """Even triangle mesh filling the outline. Returns (verts_xy, faces)."""
    pts = list(outline)
    if geo.signed_area(pts) < 0:
        pts.reverse()
    boundary = geo.resample_outline(pts, spacing)
    interior = geo.hex_fill(boundary, spacing)
    coords = [Vector(p) for p in boundary + interior]
    n = len(boundary)
    edges = [(i, (i + 1) % n) for i in range(n)]
    verts, _, faces, *_ = delaunay_2d_cdt(coords, edges, [list(range(n))], 1, spacing * 1e-3)
    return [tuple(v) for v in verts], faces


def build_cloth(context, panel, spacing, fabric_src=None):
    """Create (or rebuild) '<panel>_cloth' next to the editable 2D panel."""
    outline = world_outline(panel)
    verts, faces = triangulate_panel(outline, spacing)
    z = panel.matrix_world.translation.z
    name = f"{panel.name}_cloth"
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x, y, 0.0) for x, y in verts], [], faces)
    # UVs = pattern space in metres, so a 1x1 texture tile = 1 m of fabric.
    uv = me.uv_layers.new(name="Pattern")
    for loop in me.loops:
        x, y = verts[loop.vertex_index]
        uv.data[loop.index].uv = (x, y)
    old = bpy.data.objects.get(name)
    if old and old.get("fh_cloth_source") == panel.name:
        old_me = old.data
        old.data = me
        bpy.data.meshes.remove(old_me)
        obj = old   # keeps its own (possibly tweaked) fabric
    else:
        obj = bpy.data.objects.new(name, me)
        context.scene.collection.objects.link(obj)
        fabric.copy_fabric(fabric_src or context.scene.fh.fabric, obj.fh_fabric)
    obj.matrix_world = Matrix.Translation((0, 0, z + 0.001))
    obj["fh_cloth_source"] = panel.name
    # Pieces carry the fabric but don't simulate on their own; the sewn
    # garment does (see arrange.py). Keeps the timeline from dropping them.
    mod = fabric.ensure_cloth(obj)
    mod.show_viewport = mod.show_render = False
    return obj


class FH_OT_build_cloth(bpy.types.Operator):
    """Make a simulation-ready cloth mesh from the selected panels, using the chosen fabric"""
    bl_idname = "fashionhov.build_cloth"
    bl_label = "Build Cloth Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.get("fh_panel") for o in context.selected_objects) and context.mode == 'OBJECT'

    def execute(self, context):
        s = context.scene.fh
        built = 0
        for panel in [o for o in context.selected_objects if o.get("fh_panel")]:
            if len(world_outline(panel)) < 3:
                continue
            build_cloth(context, panel, s.cloth_spacing)
            built += 1
        self.report({'INFO'}, f"Built {built} cloth mesh(es)")
        return {'FINISHED'}


classes = (FH_OT_build_cloth,)
