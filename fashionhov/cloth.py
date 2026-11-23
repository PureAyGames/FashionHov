"""Turn a 2D pattern panel into a simulation-ready cloth mesh with real fabric weight."""

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import delaunay_2d_cdt

from .core import geometry as geo
from . import fabric
from .util import world_outline


def triangulate_panel(outline, spacing, lines=()):
    """Even triangle mesh filling the outline, with optional internal lines
    (pleat folds, fly line...) built in as mesh edges. Returns (verts_xy, faces)."""
    pts = list(outline)
    if geo.signed_area(pts) < 0:
        pts.reverse()
    boundary = geo.resample_outline(pts, spacing)
    inner = [geo.resample_polyline(list(l), spacing) for l in lines if len(l) >= 2]
    interior = geo.hex_fill(boundary, spacing, inner)
    coords = [Vector(p) for p in boundary]
    n = len(boundary)
    edges = [(i, (i + 1) % n) for i in range(n)]
    for l in inner:
        start = len(coords)
        coords += [Vector(p) for p in l]
        edges += [(start + k, start + k + 1) for k in range(len(l) - 1)]
    coords += [Vector(p) for p in interior]
    verts, _, faces, *_ = delaunay_2d_cdt(coords, edges, [list(range(n))], 1, spacing * 1e-3)
    return [tuple(v) for v in verts], faces


PIECES = "FH Pieces"
CONSTRAINT_LINES = ("pleat_fold", "pleat_inner", "fly_fold", "pleat_stitch")


def pieces_collection(scene):
    col = bpy.data.collections.get(PIECES)
    if col is None:
        col = bpy.data.collections.new(PIECES)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def build_cloth(context, panel, spacing, fabric_src=None):
    """Create (or rebuild) '<panel>_cloth' from the panel with all its features applied
    (pleats spread, dart wedges cut, fly extension added)."""
    from .features import get_derived
    d = get_derived(panel)
    outline = d.cut if d else world_outline(panel)
    lines = [l["pts"] for l in d.lines if l["kind"] in CONSTRAINT_LINES] if d else []
    for a, b in (d.sews if d else []):
        lines += [a, b]
    verts, faces = triangulate_panel(outline, spacing, lines)
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
        pieces_collection(context.scene).objects.link(obj)
        fabric.copy_fabric(fabric_src or context.scene.fh.fabric, obj.fh_fabric)
    obj.matrix_world = Matrix.Translation((0, 0, z + 0.001))
    obj["fh_cloth_source"] = panel.name
    obj["fh_spacing"] = spacing
    # internal seams (dart legs, pleat tacks) and pleat intake, in pattern space
    obj["fh_sews"] = [[list(map(list, a)), list(map(list, b))] for a, b in (d.sews if d else [])]
    obj["fh_intake"] = [list(map(list, poly)) for poly in (d.intake if d else [])]
    # Pieces carry the fabric but don't simulate on their own; the sewn
    # garment does (see arrange.py). Keeps the timeline from dropping them.
    mod = fabric.ensure_cloth(obj)
    mod.show_viewport = mod.show_render = False
    if obj.get("fh_placed"):
        avatar = context.scene.fh_body.avatar
        if avatar:
            from .arrange import wrap_piece
            wrap_piece(context, obj, panel, avatar)
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
