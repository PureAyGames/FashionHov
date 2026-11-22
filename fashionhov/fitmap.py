"""Fit maps on the draped garment.

STRAIN: how much the fabric is stretched compared to the flat pattern.
        green = relaxed, yellow -> red = pulling tight, blue = bunched up.
EASE:   gap between garment and body. red = skin tight, green = a few cm,
        blue = loose / far from the body.
"""

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

STRAIN_ATTR = "FH Strain"
EASE_ATTR = "FH Ease"


def _ramp(x, stops):
    """x in data units; stops = [(value, (r,g,b))]."""
    vals = np.array([s[0] for s in stops])
    cols = np.array([s[1] for s in stops])
    return np.column_stack([np.interp(x, vals, cols[:, k]) for k in range(3)])


STRAIN_STOPS = [(-0.06, (0.1, 0.3, 1.0)), (-0.01, (0.2, 0.8, 0.3)), (0.01, (0.2, 0.8, 0.3)),
                (0.05, (1.0, 0.9, 0.1)), (0.10, (1.0, 0.15, 0.1))]
EASE_STOPS = [(0.0, (1.0, 0.15, 0.1)), (0.008, (1.0, 0.8, 0.1)), (0.025, (0.2, 0.8, 0.3)),
              (0.06, (0.2, 0.6, 1.0)), (0.12, (0.15, 0.2, 0.9))]


def evaluated_coords(context, obj):
    dg = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(obj.matrix_world)
    return co @ mw[:3, :3].T + mw[:3, 3]


def strain(obj, co):
    """Per-vertex average edge stretch vs. the rest (pattern) lengths, as a fraction."""
    me = obj.data
    uv = me.uv_layers.get("Pattern")
    rest_xy = np.zeros((len(me.vertices), 2))
    for loop in me.loops:
        rest_xy[loop.vertex_index] = uv.data[loop.index].uv
    acc = np.zeros(len(me.vertices))
    cnt = np.zeros(len(me.vertices))
    for e in me.edges:
        if e.is_loose:          # sewing threads, not fabric
            continue
        a, b = e.vertices
        rest = np.linalg.norm(rest_xy[a] - rest_xy[b])
        if rest < 1e-6:
            continue
        s = np.linalg.norm(co[a] - co[b]) / rest - 1.0
        acc[[a, b]] += s
        cnt[[a, b]] += 1
    return np.divide(acc, cnt, out=np.zeros_like(acc), where=cnt > 0)


def ease(context, co, avatar):
    from .avatar import mesh_arrays
    v, t = mesh_arrays(context, avatar)
    bvh = BVHTree.FromPolygons(v.tolist(), t.tolist())
    out = np.zeros(len(co))
    for i, p in enumerate(co):
        hit = bvh.find_nearest(p)
        out[i] = hit[3] if hit[0] is not None else 1.0
    return out


def write_colors(obj, name, rgb):
    me = obj.data
    attr = me.color_attributes.get(name) or me.color_attributes.new(name, 'FLOAT_COLOR', 'POINT')
    rgba = np.column_stack([rgb, np.ones(len(rgb))]).ravel()
    attr.data.foreach_set("color", rgba)
    me.color_attributes.active_color = attr
    me.update()


def summary(values, kind):
    if kind == 'STRAIN':
        return {"max_stretch": float(values.max()), "tight_share": float((values > 0.05).mean())}
    return {"min_ease": float(values.min()), "skin_tight_share": float((values < 0.008).mean())}


class FH_OT_fit_map(bpy.types.Operator):
    """Colour the garment by fit at the current frame. Strain = stretched/tight areas; Ease = room between garment and body"""
    bl_idname = "fashionhov.fit_map"
    bl_label = "Fit Map"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=[('STRAIN', "Strain", "Where the fabric is pulled tight"),
                                        ('EASE', "Ease", "How close the garment sits to the body")])

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get("FH Garment") is not None

    def execute(self, context):
        g = bpy.data.objects["FH Garment"]
        co = evaluated_coords(context, g)
        if self.kind == 'STRAIN':
            vals = strain(g, co)
            write_colors(g, STRAIN_ATTR, _ramp(vals, STRAIN_STOPS))
            s = summary(vals, 'STRAIN')
            msg = f"Max stretch {s['max_stretch'] * 100:.0f}%, {s['tight_share'] * 100:.0f}% of the garment pulled tight"
        else:
            avatar = context.scene.fh_body.avatar
            if not avatar:
                self.report({'ERROR'}, "No avatar")
                return {'CANCELLED'}
            vals = ease(context, co, avatar)
            write_colors(g, EASE_ATTR, _ramp(vals, EASE_STOPS))
            s = summary(vals, 'EASE')
            msg = f"{s['skin_tight_share'] * 100:.0f}% of the garment is skin-tight (<8 mm)"
        g["fh_fit"] = {self.kind: s}
        if context.screen:
            for a in context.screen.areas:
                if a.type == 'VIEW_3D':
                    sh = a.spaces.active.shading
                    sh.type = 'SOLID'
                    sh.color_type = 'VERTEX'
        self.report({'INFO'}, msg)
        return {'FINISHED'}


classes = (FH_OT_fit_map,)
