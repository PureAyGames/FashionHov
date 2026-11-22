import bpy
from .core.fabrics import FABRICS

REF_PRESETS = {
    'LETTER': (0.2159, 0.2794),   # US Letter paper 8.5 x 11 in
    'A4': (0.210, 0.297),
    'CARD': (0.08560, 0.05398),   # credit / ID card
}


def _units_update(self, context):
    us = context.scene.unit_settings
    if self.units == 'IN':
        us.system = 'IMPERIAL'
        us.length_unit = 'INCHES'
    else:
        us.system = 'METRIC'
        us.length_unit = 'CENTIMETERS'
    us.scale_length = 1.0


def _preset_update(self, context):
    if self.ref_preset in REF_PRESETS:
        self.ref_width, self.ref_height = REF_PRESETS[self.ref_preset]


def _is_photo(self, obj):
    return bool(obj.get("fh_photo"))


class FHSettings(bpy.types.PropertyGroup):
    units: bpy.props.EnumProperty(
        name="Units", items=[('CM', "cm", "Centimetres"), ('IN', "in", "Inches")],
        default='CM', update=_units_update)
    photo: bpy.props.PointerProperty(name="Photo", type=bpy.types.Object, poll=_is_photo)
    ref_preset: bpy.props.EnumProperty(
        name="Reference",
        items=[('LETTER', "US Letter Paper", "8.5 x 11 in sheet"),
               ('A4', "A4 Paper", "210 x 297 mm sheet"),
               ('CARD', "Credit Card", "85.6 x 54 mm card"),
               ('CUSTOM', "Custom Rectangle", "Enter the size yourself")],
        default='LETTER', update=_preset_update)
    ref_width: bpy.props.FloatProperty(name="Width", default=0.2159, min=0.001, subtype='DISTANCE', unit='LENGTH')
    ref_height: bpy.props.FloatProperty(name="Height", default=0.2794, min=0.001, subtype='DISTANCE', unit='LENGTH')
    ref_distance: bpy.props.FloatProperty(
        name="Known Length", default=0.3048, min=0.001, subtype='DISTANCE', unit='LENGTH',
        description="Real length between the two points you click (e.g. 12 in on a ruler)")
    show_measurements: bpy.props.BoolProperty(name="Show Measurements", default=True)
    fabric: bpy.props.EnumProperty(
        name="Fabric", items=[(k, v["label"], f'{v["gsm"]} g/m²') for k, v in FABRICS.items()],
        default='TWILL')
    cloth_spacing: bpy.props.FloatProperty(
        name="Mesh Detail", default=0.012, min=0.003, max=0.1, subtype='DISTANCE', unit='LENGTH',
        description="Triangle size of the cloth mesh. Smaller = finer wrinkles, slower sim")


def register():
    bpy.utils.register_class(FHSettings)
    bpy.types.Scene.fh = bpy.props.PointerProperty(type=FHSettings)


def unregister():
    del bpy.types.Scene.fh
    bpy.utils.unregister_class(FHSettings)
