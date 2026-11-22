import bpy
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d


def mouse_to_plane(context, event, z=0.0):
    """World point where the mouse ray hits the horizontal plane at height z."""
    region, rv3d = context.region, context.region_data
    co = (event.mouse_region_x, event.mouse_region_y)
    origin = region_2d_to_origin_3d(region, rv3d, co)
    direction = region_2d_to_vector_3d(region, rv3d, co)
    if abs(direction.z) < 1e-9:
        return None
    t = (z - origin.z) / direction.z
    return origin + direction * t


def fmt_len(context, metres):
    s = context.scene.fh
    if s.units == 'IN':
        return f'{metres / 0.0254:.2f}"'
    return f"{metres * 100:.1f} cm"


def fmt_area(context, m2):
    s = context.scene.fh
    if s.units == 'IN':
        return f"{m2 / 0.0254 ** 2:.1f} sq in"
    return f"{m2 * 1e4:.0f} cm²"


def world_outline(obj):
    """Ordered world-space XY outline of a panel object (its first face, or its edge loop)."""
    mw = obj.matrix_world
    me = obj.data
    if obj.mode == 'EDIT':
        import bmesh
        bm = bmesh.from_edit_mesh(me)
        if bm.faces:
            return [tuple((mw @ v.co).xy) for v in bm.faces[0].verts]
        return [tuple((mw @ v.co).xy) for v in bm.verts]
    if me.polygons:
        return [tuple((mw @ me.vertices[i].co).xy) for i in me.polygons[0].vertices]
    return [tuple((mw @ v.co).xy) for v in me.vertices]


def panels(scene):
    return [o for o in scene.objects if o.get("fh_panel") and o.type == 'MESH']
