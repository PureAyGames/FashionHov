import bpy
import bmesh

from .core import geometry as geo
from .util import fmt_len, fmt_area, world_outline
from . import fabric, mpfb_bridge, drape
from .avatar import KEYS, LABELS


class Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FashionHov"


class FH_PT_main(Base, bpy.types.Panel):
    bl_label = "FashionHov"

    def draw(self, context):
        s = context.scene.fh
        row = self.layout.row(align=True)
        row.prop(s, "units", expand=True)
        self.layout.prop(s, "show_measurements")


class Sub(Base):
    bl_parent_id = "FH_PT_main"

    @classmethod
    def poll(cls, context):
        return context.scene.name != drape.TEST_SCENE


class FH_PT_photo(Sub, bpy.types.Panel):
    bl_label = "1. Reference Photo"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.fh
        col = self.layout.column()
        col.operator("fashionhov.import_photo", icon='IMAGE_DATA')
        col.prop(s, "photo")
        if not s.photo:
            col.label(text="Lay the garment flat, shoot straight down,", icon='INFO')
            col.label(text="with paper, a card or a ruler in frame.")
            return
        box = col.box()
        box.label(text="Scale from paper/card (best):")
        box.prop(s, "ref_preset", text="")
        sub = box.column(align=True)
        sub.enabled = s.ref_preset == 'CUSTOM'
        sub.prop(s, "ref_width")
        sub.prop(s, "ref_height")
        box.operator("fashionhov.calibrate", text="Click 4 Corners", icon='MOD_LATTICE').mode = 'FOUR'
        box = col.box()
        box.label(text="Or scale from a ruler:")
        box.prop(s, "ref_distance")
        box.operator("fashionhov.calibrate", text="Click 2 Points", icon='DRIVER_DISTANCE').mode = 'TWO'


class FH_PT_panels(Sub, bpy.types.Panel):
    bl_label = "2. Pattern Panels"

    def draw(self, context):
        col = self.layout.column()
        col.operator("fashionhov.trace_panel", icon='GREASEPENCIL')
        obj = context.active_object
        if not obj or not obj.get("fh_panel"):
            col.label(text="Select a panel to see its measurements")
            return
        pts = world_outline(obj)
        if len(pts) < 3:
            return
        x0, y0, x1, y1 = geo.bbox(pts)
        box = col.box()
        box.label(text=obj.name, icon='MESH_PLANE')
        grid = box.grid_flow(columns=2, even_columns=True)
        grid.label(text=f"Width {fmt_len(context, x1 - x0)}")
        grid.label(text=f"Height {fmt_len(context, y1 - y0)}")
        grid.label(text=f"Perimeter {fmt_len(context, geo.perimeter(pts))}")
        grid.label(text=f"Area {fmt_area(context, geo.area(pts))}")
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            mw = obj.matrix_world
            sel = [e for e in bm.edges if e.select]
            total = sum((mw @ e.verts[0].co - mw @ e.verts[1].co).length for e in sel)
            box.label(text=f"Selected edges ({len(sel)}): {fmt_len(context, total)}", icon='EDGESEL')
        else:
            box.label(text="Tab: edit points / select edges to measure", icon='INFO')
        box = col.box()
        box.label(text="On the avatar:", icon='ARMATURE_DATA')
        box.prop(obj.fh_place, "where")
        if obj.fh_place.where != 'NONE':
            row = box.row(align=True)
            row.prop(obj.fh_place, "top")
            row.prop(obj.fh_place, "gap")
            box.prop(obj.fh_place, "mirror")
        box = col.box()
        box.label(text="Grading:", icon='FULLSCREEN_ENTER')
        box.prop(obj.fh_grade, "girth")
        box.prop(obj.fh_grade, "length")


def _tool_grid(layout):
    from .tool import KINDS
    grid = layout.grid_flow(columns=2, even_columns=True, align=True)
    for ident, label, _, icon, _ in KINDS:
        grid.operator("fashionhov.tool", text=label, icon=icon).kind = ident


STACK_ICONS = {"darts": 'MOD_TRIANGULATE', "pleats": 'MOD_SOLIDIFY', "hems": 'MOD_EDGESPLIT',
               "hardware": 'RADIOBUT_ON', "pockets": 'MOD_BOOLEAN'}


def _item_title(coll, it, i):
    if coll == "darts":
        return ("Fisheye Dart" if it.mode == 'INNER' else "Dart") + f" {i + 1}"
    if coll == "pleats":
        return f"{it.kind.title()} Pleat {i + 1}" + (" (tapered)" if it.taper > 0 else "")
    if coll == "hems":
        return f"Hem {i + 1}"
    if coll == "pockets":
        from .features import POCKET_KINDS
        return dict((a, b) for a, b, _ in POCKET_KINDS)[it.kind]
    return it.kind.replace("_", " ").title() + (f" ({it.style.title()})" if it.kind == 'ZIPPER' else "")


def _item_fields(coll, it):
    if coll == "darts":
        return ("t", "width", "length", "angle") if it.mode == 'EDGE' else ("width", "length", "down", "angle")
    if coll == "pleats":
        return ("kind", "t", "depth", "taper", "stitch")
    if coll == "hems":
        return ("fold", "width", "turn", "topstitch") if it.fold == 'DOUBLE' else ("fold", "width", "topstitch")
    if coll == "pockets":
        return ("topstitch", "in_sim") if it.kind != 'SCOOP' else ("width", "depth", "curve", "topstitch")
    if it.kind == 'ZIPPER':
        f = ("style", "start", "length", "finish", "pull_at_start")
        return f + (("fly_width",) if it.style == 'FLY' else ())
    if it.kind == 'BUTTONHOLE':
        return ("size", "angle")
    return ("size", "finish")


class FH_PT_details(Sub, bpy.types.Panel):
    bl_label = "Details (modifiers)"

    def draw(self, context):
        ts = context.scene.fh_tool
        sh = context.scene.fh_show
        col = self.layout.column()

        box = col.box()
        box.label(text="Show on all panels (nothing is deleted):", icon='HIDE_OFF')
        g = box.grid_flow(columns=3, even_columns=True, align=True)
        for k in ("pockets", "darts", "pleats", "hems", "zippers", "hardware"):
            g.prop(sh, k, toggle=True)

        col.label(text="Pick one, then click / drag on your panels:", icon='INFO')
        _tool_grid(col)
        box = col.box()
        box.label(text="Defaults for new items")
        row = box.row(align=True)
        row.prop(ts, "pocket_kind", text="")
        row.prop(ts, "pocket_rivets")
        row = box.row(align=True)
        row.prop(ts, "dart_width", text="Dart W")
        row.prop(ts, "dart_length", text="L")
        row = box.row(align=True)
        row.prop(ts, "pleat_depth", text="Pleat")
        row.prop(ts, "pleat_kind", text="")
        row.prop(ts, "pleat_taper", text="Taper")
        row = box.row(align=True)
        row.prop(ts, "hem_width", text="Hem")
        row.prop(ts, "zip_style", text="")
        box.prop(ts, "finish")
        if context.mode == 'EDIT_MESH':
            col.operator("fashionhov.hem_selected", icon='MOD_EDGESPLIT')

        obj = context.active_object
        if not obj or not obj.get("fh_panel"):
            col.label(text="Select a panel to see its detail stack")
            return
        from .features import owner_of
        if obj.get("fh_feature_of"):
            parent, item = owner_of(obj)
            if parent:
                row = col.row()
                row.label(text=f"Part of {parent.name}", icon='LINKED')
                row.operator("fashionhov.pocket_select", text="Go to Parent").name = parent.name
        f = obj.fh_features
        col.prop(f, "seam_allowance", text="Seam Allowance (-1 = default)")
        stack = col.box()
        stack.label(text=f"{obj.name}: detail stack", icon='MODIFIER')
        empty = True
        for coll in ("pockets", "darts", "pleats", "hems", "hardware"):
            for i, it in enumerate(getattr(f, coll)):
                empty = False
                sub = stack.box()
                head = sub.row(align=True)
                head.prop(it, "enabled", text="", icon='HIDE_OFF' if it.enabled else 'HIDE_ON', emboss=False)
                head.label(text=_item_title(coll, it, i), icon=STACK_ICONS[coll])
                if coll == "pockets":
                    for attr in ("piece", "facing", "bag"):
                        o = getattr(it, attr)
                        if o:
                            head.operator("fashionhov.pocket_select", text="", icon='EDITMODE_HLT').name = o.name
                    head.operator("fashionhov.pocket_reset", text="", icon='FILE_REFRESH').index = i
                if coll == "hardware" and it.kind == 'ZIPPER' and it.child:
                    head.operator("fashionhov.pocket_select", text="", icon='EDITMODE_HLT').name = it.child.name
                op = head.operator("fashionhov.feature_remove", text="", icon='X')
                op.coll, op.index = coll, i
                if not it.enabled:
                    continue
                grid = sub.grid_flow(columns=2, even_columns=True, align=True)
                for fld in _item_fields(coll, it):
                    grid.prop(it, fld)
        if empty:
            stack.label(text="No details yet: use the buttons above")


class FH_PT_thread(Sub, bpy.types.Panel):
    bl_label = "Thread"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        th = context.scene.fh_thread
        col = self.layout.column()
        row = col.row(align=True)
        row.prop(th, "visible", toggle=True, icon='HIDE_OFF' if th.visible else 'HIDE_ON')
        row.prop(th, "show_hardware", toggle=True, icon='HIDE_OFF' if th.show_hardware else 'HIDE_ON')
        col.prop(th, "color")
        from .details import THREAD_PRESETS
        row = col.row(align=True)
        for k, (rgb, label) in THREAD_PRESETS.items():
            row.operator("fashionhov.thread_preset", text=label.split(" ")[0]).preset = k
        col.prop(th, "thickness")
        col.prop(th, "stitch_length")
        sc = context.scene
        if len(sc.fh_seams) and sc.fh_seam_index < len(sc.fh_seams):
            s = sc.fh_seams[sc.fh_seam_index]
            box = col.box()
            box.label(text=f"Seam #{s.number} topstitch")
            box.prop(s, "topstitch", expand=True)
            if s.topstitch != 'NONE':
                box.prop(s, "ts_side")
                row = box.row(align=True)
                row.prop(s, "ts_dist")
                if s.topstitch == 'DOUBLE':
                    row.prop(s, "ts_gap")
        else:
            col.label(text="Select a seam (Sew & Fit) to topstitch it")
        col.operator("fashionhov.rebuild_details", icon='FILE_REFRESH')


class FH_PT_export(Sub, bpy.types.Panel):
    bl_label = "7. Export Pattern"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column()
        col.prop(context.scene.fh_thread, "seam_allowance", text="Default Seam Allowance")
        col.prop(context.scene.fh, "show_allowance")
        row = col.row()
        row.scale_y = 1.4
        row.operator("fashionhov.export_pattern", icon='EXPORT')
        col.label(text="SVG prints 1:1; check the 10 cm square.", icon='INFO')


class FH_PT_fabric(Sub, bpy.types.Panel):
    bl_label = "3. Fabric"

    def draw(self, context):
        s = context.scene.fh
        obj = context.active_object
        col = self.layout.column()
        if obj and obj.type == 'MESH' and obj.modifiers.get("FH Cloth"):
            col.label(text=f"{obj.name}  ({obj.get('fh_weight_g', 0):.0f} g of fabric)", icon='MOD_CLOTH')
            fabric.draw_fabric(col, obj.fh_fabric)
            col.operator("fashionhov.copy_fabric", icon='DUPLICATE')
        else:
            col.label(text="Default fabric for new pieces:", icon='MOD_CLOTH')
            fabric.draw_fabric(col, s.fabric)
        col.operator("fashionhov.drape_test", icon='VIEW_PAN')
        col.separator()
        col.prop(s, "cloth_spacing")
        col.operator("fashionhov.build_cloth", icon='MESH_GRID')


class FH_PT_drape_test(Base, bpy.types.Panel):
    bl_label = "Hand Drape Test"
    bl_parent_id = "FH_PT_main"

    @classmethod
    def poll(cls, context):
        return context.scene.name == drape.TEST_SCENE

    def draw(self, context):
        s = context.scene.fh
        col = self.layout.column()
        col.label(text="Drape the real fabric over your hand", icon='INFO')
        col.label(text="the same way, then move Drape until it matches.")
        sw = next((o for o in context.scene.objects if o.get("fh_swatch")), None)
        if sw:
            fabric.draw_fabric(col, sw.fh_fabric)
            col.operator("fashionhov.drape_replay", icon='PLAY')
        box = col.box()
        box.prop(s, "hand_pose", expand=True)
        box.prop(s, "hand_scale")
        row = box.row(align=True)
        row.prop(s, "swatch_width")
        row.prop(s, "swatch_height")
        box.prop(s, "swatch_detail")
        box.operator("fashionhov.drape_rebuild", icon='FILE_REFRESH')
        row = col.row(align=True)
        row.scale_y = 1.4
        row.operator("fashionhov.drape_done", text="Use This Fabric", icon='CHECKMARK').apply = True
        row.operator("fashionhov.drape_done", text="Cancel", icon='X').apply = False


class FH_PT_body(Sub, bpy.types.Panel):
    bl_label = "4. Body"

    def draw(self, context):
        b = context.scene.fh_body
        col = self.layout.column()
        has_mpfb = mpfb_bridge.available()
        if has_mpfb:
            col.label(text="MPFB found: realistic human avatar", icon='CHECKMARK')
        else:
            col.label(text="MPFB not installed: using a dress form.", icon='INFO')
            col.label(text="Get it free: Preferences > Get Extensions > MPFB")
        row = col.row(align=True)
        row.operator("fashionhov.create_avatar", icon='OUTLINER_OB_ARMATURE').kind = 'AUTO'
        if has_mpfb:
            row.operator("fashionhov.create_avatar", text="", icon='MOD_CLOTH').kind = 'FORM'
        col.prop(b, "avatar")
        if has_mpfb:
            col.prop(b, "gender", slider=True)
        m = b.avatar.get("fh_measured", {}) if b.avatar else {}
        box = col.box()
        head = box.row()
        head.label(text="Your measurements")
        head.label(text="Avatar")
        for k in KEYS + ("mass",):
            row = box.row(align=True)
            row.prop(b, "use_" + k, text="")
            sub = row.row(align=True)
            sub.active = getattr(b, "use_" + k)
            sub.prop(b, k, text=LABELS[k].split(" (")[0])
            if k in m:
                if k == "mass":
                    v = m[k] / 0.45359237 if context.scene.fh.units == 'IN' else m[k]
                    row.label(text=f"{v:.0f} {'lb' if context.scene.fh.units == 'IN' else 'kg'}")
                else:
                    row.label(text=fmt_len(context, m[k]))
        row = col.row(align=True)
        row.scale_y = 1.4
        row.operator("fashionhov.fit_avatar", icon='CON_SIZELIKE')
        row = col.row(align=True)
        row.operator("fashionhov.measure_avatar", icon='DRIVER_DISTANCE')
        row.operator("fashionhov.measured_to_inputs", icon='IMPORT')
        if has_mpfb and b.avatar and b.avatar.get("fh_avatar") == "MPFB":
            col.label(text="Fine-tune freely in MPFB's Model tab,", icon='INFO')
            col.label(text="then press Measure Avatar.")


class FH_PT_sew(Sub, bpy.types.Panel):
    bl_label = "5. Sew & Fit"

    def draw(self, context):
        sc = context.scene
        col = self.layout.column()
        col.operator("fashionhov.arrange", icon='MOD_SIMPLEDEFORM')
        box = col.box()
        box.label(text="Seams (same colour + number in 2D and 3D)")
        box.operator("fashionhov.sew", icon='AUTOMERGE_ON')
        if context.mode != 'EDIT_MESH':
            box.label(text="Tab into Edit Mode on panels or 3D pieces,", icon='INFO')
            box.label(text="select 2 runs of edges, then Sew.")
        box.template_list("FH_UL_seams", "", sc, "fh_seams", sc, "fh_seam_index", rows=3)
        if sc.get("fh_garment_stale"):
            col.label(text="Pattern changed: Simulate again", icon='ERROR')
        row = col.row(align=True)
        row.scale_y = 1.4
        row.operator("fashionhov.simulate", icon='PLAY')
        row.operator("fashionhov.unsew", text="", icon='LOOP_BACK')
        row = col.row(align=True)
        row.operator("fashionhov.fit_map", text="Strain Map", icon='MOD_PHYSICS').kind = 'STRAIN'
        row.operator("fashionhov.fit_map", text="Ease Map", icon='SNAP_VOLUME').kind = 'EASE'
        g = bpy.data.objects.get("FH Garment")
        if g and "fh_fit" in g:
            leg = col.box().column(align=True)
            if "STRAIN" in g["fh_fit"]:
                leg.label(text="Strain: blue loose · green relaxed · red tight")
            if "EASE" in g["fh_fit"]:
                leg.label(text="Ease: red skin-tight · green ~2.5 cm · blue loose")


class FH_PT_sizes(Sub, bpy.types.Panel):
    bl_label = "6. Sizes"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        sc = context.scene
        col = self.layout.column()
        row = col.row(align=True)
        row.operator("fashionhov.add_standard_sizes", icon='PRESET')
        row.operator("fashionhov.size_from_body", icon='USER')
        row = col.row()
        row.template_list("FH_UL_sizes", "", sc, "fh_sizes", sc, "fh_size_index", rows=4)
        side = row.column(align=True)
        side.operator("fashionhov.size_remove", text="", icon='REMOVE')
        side.operator("fashionhov.set_base_size", text="", icon='PINNED')
        if len(sc.fh_sizes) and sc.fh_size_index < len(sc.fh_sizes):
            s = sc.fh_sizes[sc.fh_size_index]
            box = col.box()
            box.prop(s, "name")
            for k in ("chest", "waist", "hips", "height", "inseam"):
                box.prop(s, k)
        col.label(text=f"Base (pattern drafted in): "
                       f"{sc.fh_sizes[sc.fh_base_size].name if sc.fh_base_size < len(sc.fh_sizes) else '-'}",
                  icon='PINNED')
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("fashionhov.grade", icon='FULLSCREEN_ENTER')
        col.operator("fashionhov.fit_avatar_to_size", icon='CON_SIZELIKE')


classes = (FH_PT_main, FH_PT_photo, FH_PT_panels, FH_PT_details, FH_PT_fabric, FH_PT_drape_test,
           FH_PT_body, FH_PT_sew, FH_PT_thread, FH_PT_sizes, FH_PT_export)
