"""Per-object fabric settings (weight in GSM / oz, drape, stretch)."""

import bpy

from .core import fabrics as fb

DEFAULT_WIDTH = 58 * 0.0254   # common roll width


def _push(self, context):
    """Re-apply to the owning cloth object when any value changes."""
    owner = self.id_data
    if isinstance(owner, bpy.types.Object):
        apply_to_object(owner)


def _preset(self, context):
    p = fb.FABRICS.get(self.preset)
    if not p:
        return
    self["gsm"] = float(p["gsm"])
    self["drape"] = p["drape"]
    self["stretch"] = p["stretch"]
    _push(self, context)


def _oz_get(self):
    return fb.gsm_to_oz_sq_yd(self.gsm)


def _oz_set(self, v):
    self.gsm = fb.oz_sq_yd_to_gsm(v)


def _ozlin_get(self):
    return fb.gsm_to_oz_lin_yd(self.gsm, self.width)


def _ozlin_set(self, v):
    self.gsm = fb.oz_lin_yd_to_gsm(v, self.width)


class FHFabric(bpy.types.PropertyGroup):
    preset: bpy.props.EnumProperty(
        name="Preset",
        items=[(k, v["label"], f'{v["gsm"]} g/m²') for k, v in fb.FABRICS.items()] + [('CUSTOM', "Custom", "")],
        default='TWILL', update=_preset)
    gsm: bpy.props.FloatProperty(
        name="GSM", description="Weight in grams per square metre",
        default=250, min=5, max=2000, precision=0, update=_push)
    oz_sq_yd: bpy.props.FloatProperty(
        name="oz/yd²", description="Ounces per square yard. This is the '12 oz' number for denim",
        min=0.1, max=60, precision=2, get=_oz_get, set=_oz_set)
    width: bpy.props.FloatProperty(
        name="Roll Width", description="Fabric width off the roll; only needed for oz per linear yard",
        default=DEFAULT_WIDTH, min=0.1, max=4, subtype='DISTANCE', unit='LENGTH', update=_push)
    oz_lin_yd: bpy.props.FloatProperty(
        name="oz/linear yd", description="Ounces for one yard cut off the roll at full width",
        min=0.1, max=150, precision=2, get=_ozlin_get, set=_ozlin_set)
    drape: bpy.props.FloatProperty(
        name="Drape", description="0 = stiff (canvas, leather), 1 = liquid (silk, chiffon). "
                                  "Use the hand drape test to match a real fabric by eye",
        default=0.35, min=0, max=1, subtype='FACTOR', update=_push)
    stretch: bpy.props.FloatProperty(
        name="Stretch", description="0 = rigid woven, 1 = very stretchy knit",
        default=0.25, min=0, max=1, subtype='FACTOR', update=_push)


FIELDS = ("gsm", "width", "drape", "stretch")


def copy_fabric(src, dst):
    """Copy values without triggering the preset callback (which would overwrite them)."""
    dst["preset"] = src.get("preset", 3)
    for k in FIELDS:
        setattr(dst, k, getattr(src, k))


def apply_to_object(obj):
    """Write the object's fabric into its cloth modifier."""
    if obj.type != 'MESH':
        return
    f = obj.fh_fabric
    area = sum(p.area for p in obj.data.polygons) * obj.matrix_world.to_scale().x ** 2
    obj["fh_weight_g"] = f.gsm * area
    mod = obj.modifiers.get("FH Cloth")
    if not mod:
        return
    s = fb.solver_settings(f.gsm, f.drape, f.stretch)
    st = mod.settings
    st.mass = fb.sim_vertex_mass(f.gsm, area, len(obj.data.vertices))
    st.tension_stiffness = s["tension"]
    st.compression_stiffness = s["compression"]
    st.shear_stiffness = s["shear"]
    st.bending_stiffness = s["bending"]


def ensure_cloth(obj):
    mod = obj.modifiers.get("FH Cloth") or obj.modifiers.new("FH Cloth", 'CLOTH')
    st = mod.settings
    st.quality = 8
    st.air_damping = fb.SIM_AIR_DAMPING
    cs = mod.collision_settings
    cs.use_self_collision = True
    cs.distance_min = 0.003
    cs.self_distance_min = 0.003
    apply_to_object(obj)
    return mod


def draw_fabric(layout, f):
    col = layout.column()
    col.prop(f, "preset", text="")
    box = col.box()
    box.label(text="Weight")
    box.prop(f, "gsm")
    box.prop(f, "oz_sq_yd")
    row = box.row(align=True)
    row.prop(f, "oz_lin_yd")
    row.prop(f, "width", text="@")
    col.prop(f, "drape", slider=True)
    col.prop(f, "stretch", slider=True)


class FH_OT_copy_fabric(bpy.types.Operator):
    """Copy the active object's fabric to all other selected cloth pieces"""
    bl_idname = "fashionhov.copy_fabric"
    bl_label = "Copy Fabric to Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and len(context.selected_objects) > 1

    def execute(self, context):
        src = context.active_object.fh_fabric
        for o in context.selected_objects:
            if o is not context.active_object and o.type == 'MESH':
                copy_fabric(src, o.fh_fabric)
                apply_to_object(o)
        return {'FINISHED'}


classes = (FH_OT_copy_fabric,)


def register():
    bpy.utils.register_class(FHFabric)
    bpy.types.Object.fh_fabric = bpy.props.PointerProperty(type=FHFabric)


def unregister():
    del bpy.types.Object.fh_fabric
    bpy.utils.unregister_class(FHFabric)
