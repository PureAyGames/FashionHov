import bpy
import bmesh

from .core import geometry as geo
from .core.fabrics import FABRICS
from .util import fmt_len, fmt_area, world_outline


class FHPanelBase:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FashionHov"


class FH_PT_main(FHPanelBase, bpy.types.Panel):
    bl_label = "FashionHov"

    def draw(self, context):
        s = context.scene.fh
        row = self.layout.row(align=True)
        row.prop(s, "units", expand=True)
        self.layout.prop(s, "show_measurements")


class FH_PT_photo(FHPanelBase, bpy.types.Panel):
    bl_label = "1. Reference Photo"
    bl_parent_id = "FH_PT_main"

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


class FH_PT_panels(FHPanelBase, bpy.types.Panel):
    bl_label = "2. Pattern Panels"
    bl_parent_id = "FH_PT_main"

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
        box.label(text=f"Width:  {fmt_len(context, x1 - x0)}")
        box.label(text=f"Height: {fmt_len(context, y1 - y0)}")
        box.label(text=f"Perimeter: {fmt_len(context, geo.perimeter(pts))}")
        box.label(text=f"Area: {fmt_area(context, geo.area(pts))}")
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(obj.data)
            mw = obj.matrix_world
            sel = [e for e in bm.edges if e.select]
            total = sum((mw @ e.verts[0].co - mw @ e.verts[1].co).length for e in sel)
            box.label(text=f"Selected edges ({len(sel)}): {fmt_len(context, total)}", icon='EDGESEL')
        else:
            col.label(text="Tab into Edit Mode to tweak points;", icon='INFO')
            col.label(text="select edges to measure a seam.")


class FH_PT_cloth(FHPanelBase, bpy.types.Panel):
    bl_label = "3. Fabric & Cloth"
    bl_parent_id = "FH_PT_main"

    def draw(self, context):
        s = context.scene.fh
        col = self.layout.column()
        col.prop(s, "fabric")
        col.label(text=f"Weight: {FABRICS[s.fabric]['gsm']} g/m²")
        col.prop(s, "cloth_spacing")
        col.operator("fashionhov.build_cloth", icon='MOD_CLOTH')
        obj = context.active_object
        if obj and obj.get("fh_cloth_source"):
            col.label(text=f"{obj.name}: {obj.get('fh_weight_g', 0):.0f} g of fabric")


classes = (FH_PT_main, FH_PT_photo, FH_PT_panels, FH_PT_cloth)
