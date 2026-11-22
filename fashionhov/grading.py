"""Size grading: one base pattern -> every size, plus a size chart.

Proportional grading: each panel scales across by the size's girth ratio
(chest, waist or hips, picked per panel) and lengthwise by its height or
inseam ratio. Real graders tune individual points; this gets you a solid
starting nest you can tweak by hand in Edit Mode.
"""

import bpy

from . import sewing
from .core import geometry as geo
from .util import world_outline, panels, fmt_len

IN = 0.0254
# Mid-range US men's body measurements (inches): brands vary, so edit freely.
STANDARD_MENS = [
    ("S", 37.0, 30.0, 36.0, 69.0, 31.0),
    ("M", 39.5, 32.5, 38.5, 70.0, 32.0),
    ("L", 42.0, 35.5, 41.0, 71.0, 32.0),
    ("XL", 45.0, 38.5, 44.0, 72.0, 32.5),
    ("XXL", 48.5, 42.0, 47.0, 72.0, 32.5),
]
SIZE_COLORS = [(0.2, 0.5, 1, 1), (0.2, 0.8, 0.3, 1), (1, 0.8, 0.1, 1), (1, 0.45, 0.1, 1),
               (0.9, 0.15, 0.2, 1), (0.7, 0.3, 0.9, 1)]


def _len(name, d):
    return bpy.props.FloatProperty(name=name, default=d, min=0.05, max=3, subtype='DISTANCE', unit='LENGTH')


class FHSize(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(default="M")
    chest: _len("Chest", 1.0)
    waist: _len("Waist", 0.83)
    hips: _len("Hips", 0.98)
    height: _len("Height", 1.78)
    inseam: _len("Inseam", 0.81)


class FHGrade(bpy.types.PropertyGroup):
    girth: bpy.props.EnumProperty(
        name="Width follows", items=[('CHEST', "Chest", ""), ('WAIST', "Waist", ""),
                                     ('HIPS', "Hips", ""), ('NONE', "Don't grade", "")])
    length: bpy.props.EnumProperty(
        name="Length follows", items=[('HEIGHT', "Height", ""), ('INSEAM', "Inseam", ""),
                                      ('NONE', "Don't grade", "")])


def ratios(panel, base, size):
    g = panel.fh_grade
    sx = getattr(size, g.girth.lower()) / getattr(base, g.girth.lower()) if g.girth != 'NONE' else 1.0
    sy = getattr(size, g.length.lower()) / getattr(base, g.length.lower()) if g.length != 'NONE' else 1.0
    return sx, sy


def grade_points(pts, anchor, sx, sy):
    ax, ay = anchor
    return [(ax + (x - ax) * sx, ay + (y - ay) * sy) for x, y in pts]


def anchor_of(pts):
    x0, y0, x1, y1 = geo.bbox(pts)
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def clear_graded(scene):
    for o in list(scene.objects):
        if o.get("fh_graded_of"):
            me = o.data
            bpy.data.objects.remove(o)
            if me.users == 0:
                bpy.data.meshes.remove(me)
    root = bpy.data.collections.get("FH Sizes")
    if root:
        for c in list(root.children):
            bpy.data.collections.remove(c)


def grade(context):
    scene = context.scene
    sizes = scene.fh_sizes
    base = sizes[scene.fh_base_size]
    clear_graded(scene)
    root = bpy.data.collections.get("FH Sizes") or bpy.data.collections.new("FH Sizes")
    if root.name not in scene.collection.children:
        scene.collection.children.link(root)
    made = 0
    for si, size in enumerate(sizes):
        if si == scene.fh_base_size:
            continue
        col = bpy.data.collections.new(f"Size {size.name}")
        root.children.link(col)
        mat = bpy.data.materials.get(f"FH Size {size.name}") or bpy.data.materials.new(f"FH Size {size.name}")
        mat.diffuse_color = SIZE_COLORS[si % len(SIZE_COLORS)]
        for panel in panels(scene):
            if panel.get("fh_graded_of"):
                continue
            pts = world_outline(panel)
            if len(pts) < 3:
                continue
            sx, sy = ratios(panel, base, size)
            g = grade_points(pts, anchor_of(pts), sx, sy)
            me = bpy.data.meshes.new(f"{panel.name} [{size.name}]")
            me.from_pydata([(x, y, 0.0) for x, y in g], [(i, (i + 1) % len(g)) for i in range(len(g))], [])
            me.materials.append(mat)
            o = bpy.data.objects.new(me.name, me)
            o["fh_graded_of"] = panel.name
            o["fh_size"] = size.name
            o.color = mat.diffuse_color
            o.show_in_front = True
            col.objects.link(o)
            made += 1
    return made


def chart(context):
    """Size chart as aligned text + CSV, in the scene's units."""
    scene = context.scene
    sizes = list(scene.fh_sizes)
    base = sizes[scene.fh_base_size]
    f = lambda m: fmt_len(context, m)
    rows = [("BODY", [""] * len(sizes))]
    for key in ("chest", "waist", "hips", "height", "inseam"):
        rows.append((key.capitalize(), [f(getattr(s, key)) for s in sizes]))
    rows.append(("PATTERN", [""] * len(sizes)))
    base_panels = [p for p in panels(scene) if not p.get("fh_graded_of") and len(world_outline(p)) >= 3]
    for p in base_panels:
        pts = world_outline(p)
        for label, fn in (("width", lambda q: geo.bbox(q)[2] - geo.bbox(q)[0]),
                          ("length", lambda q: geo.bbox(q)[3] - geo.bbox(q)[1])):
            vals = []
            for s in sizes:
                sx, sy = ratios(p, base, s)
                vals.append(f(fn(grade_points(pts, anchor_of(pts), sx, sy))))
            rows.append((f"{p.name} {label}", vals))
    for seam in scene.fh_seams:
        if not sewing.seam_ok(seam):
            continue
        a, b = sewing.seam_chains(seam)
        vals = []
        for s in sizes:
            sa = grade_points(a, anchor_of(world_outline(seam.a_obj)), *ratios(seam.a_obj, base, s))
            sb = grade_points(b, anchor_of(world_outline(seam.b_obj)), *ratios(seam.b_obj, base, s))
            vals.append(f"{f(sewing.polyline_length(sa))}/{f(sewing.polyline_length(sb))}")
        rows.append((f"Seam #{seam.number} ({seam.a_obj.name}/{seam.b_obj.name})", vals))

    head = ["", *[s.name + (" (base)" if i == scene.fh_base_size else "") for i, s in enumerate(sizes)]]
    table = [head] + [[r[0], *r[1]] for r in rows]
    widths = [max(len(str(row[c])) for row in table) for c in range(len(head))]
    text = "\n".join("  ".join(str(c).ljust(w) for c, w in zip(row, widths)) for row in table)
    csv = "\n".join(",".join(f'"{c}"' for c in row) for row in table)
    for name, body in (("FH Size Chart", text), ("FH Size Chart.csv", csv)):
        t = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        t.clear()
        t.write(body + "\n")
    return text


class FH_OT_add_standard_sizes(bpy.types.Operator):
    """Fill the size table with typical US men's body measurements S-XXL (brands vary; edit them)"""
    bl_idname = "fashionhov.add_standard_sizes"
    bl_label = "Standard Men's Sizes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sizes = context.scene.fh_sizes
        sizes.clear()
        for name, ch, wa, hi, he, ins in STANDARD_MENS:
            s = sizes.add()
            s.name, s.chest, s.waist, s.hips, s.height, s.inseam = name, ch * IN, wa * IN, hi * IN, he * IN, ins * IN
        context.scene.fh_base_size = 1
        return {'FINISHED'}


class FH_OT_size_from_body(bpy.types.Operator):
    """Add a size made from your own measurements (the Body panel)"""
    bl_idname = "fashionhov.size_from_body"
    bl_label = "Add My Size"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        b = context.scene.fh_body
        s = context.scene.fh_sizes.add()
        s.name = "Me"
        for k in ("chest", "waist", "hips", "height", "inseam"):
            setattr(s, k, getattr(b, k))
        return {'FINISHED'}


class FH_OT_size_remove(bpy.types.Operator):
    bl_idname = "fashionhov.size_remove"
    bl_label = "Remove Size"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        if len(sc.fh_sizes):
            sc.fh_sizes.remove(sc.fh_size_index)
            sc.fh_size_index = max(0, sc.fh_size_index - 1)
            sc.fh_base_size = min(sc.fh_base_size, max(0, len(sc.fh_sizes) - 1))
        return {'FINISHED'}


class FH_OT_grade(bpy.types.Operator):
    """Make graded copies of every panel for every size (shown as a nest) and write the size chart"""
    bl_idname = "fashionhov.grade"
    bl_label = "Grade All Sizes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.fh_sizes) >= 2

    def execute(self, context):
        n = grade(context)
        chart(context)
        self.report({'INFO'}, f"Made {n} graded panels. Size chart: Text Editor > 'FH Size Chart'")
        return {'FINISHED'}


class FH_OT_fit_avatar_to_size(bpy.types.Operator):
    """Reshape the avatar to the selected size's body measurements, to check how the garment fits that size"""
    bl_idname = "fashionhov.fit_avatar_to_size"
    bl_label = "Avatar → This Size"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sc = context.scene
        return sc.fh_body.avatar is not None and len(sc.fh_sizes) > 0

    def execute(self, context):
        sc = context.scene
        s = sc.fh_sizes[sc.fh_size_index]
        b = sc.fh_body
        for k in ("chest", "waist", "hips", "height", "inseam"):
            setattr(b, k, getattr(s, k))
            setattr(b, "use_" + k, True)
        b.use_mass = False
        return bpy.ops.fashionhov.fit_avatar()


class FH_UL_sizes(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        base = index == context.scene.fh_base_size
        row.prop(item, "name", text="", emboss=False, icon='PINNED' if base else 'DOT')
        row.label(text=f"{fmt_len(context, item.chest)} / {fmt_len(context, item.waist)} / {fmt_len(context, item.hips)}")


classes = (FH_OT_add_standard_sizes, FH_OT_size_from_body, FH_OT_size_remove, FH_OT_grade,
           FH_OT_fit_avatar_to_size, FH_UL_sizes)


def register():
    bpy.utils.register_class(FHSize)
    bpy.utils.register_class(FHGrade)
    bpy.types.Scene.fh_sizes = bpy.props.CollectionProperty(type=FHSize)
    bpy.types.Scene.fh_size_index = bpy.props.IntProperty()
    bpy.types.Scene.fh_base_size = bpy.props.IntProperty(
        name="Base Size", description="The size your pattern was drafted in (row number, from 0)", min=0)
    bpy.types.Object.fh_grade = bpy.props.PointerProperty(type=FHGrade)


def unregister():
    del bpy.types.Object.fh_grade
    del bpy.types.Scene.fh_base_size
    del bpy.types.Scene.fh_size_index
    del bpy.types.Scene.fh_sizes
    bpy.utils.unregister_class(FHGrade)
    bpy.utils.unregister_class(FHSize)


class FH_OT_set_base_size(bpy.types.Operator):
    """Make the selected size the base size (the one your pattern is drafted in)"""
    bl_idname = "fashionhov.set_base_size"
    bl_label = "Set as Base"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.fh_base_size = context.scene.fh_size_index
        return {'FINISHED'}


classes = classes + (FH_OT_set_base_size,)
