"""Fabric presets.

gsm is real fabric weight (grams per square metre) and drives cloth mass.
The stiffness values are Blender cloth-solver settings tuned as starting
points; real fabrics vary a lot, so treat them as a base to tweak.
"""

FABRICS = {
    "JERSEY":  dict(label="Cotton Jersey (T-shirt)", gsm=160, tension=8, compression=8, shear=5, bending=0.05),
    "POPLIN":  dict(label="Cotton Poplin (shirting)", gsm=110, tension=40, compression=40, shear=30, bending=0.3),
    "FLEECE":  dict(label="Fleece (hoodie)", gsm=300, tension=15, compression=15, shear=10, bending=0.5),
    "TWILL":   dict(label="Cotton Twill (chinos)", gsm=250, tension=60, compression=60, shear=45, bending=1.2),
    "DENIM":   dict(label="Denim 12oz", gsm=400, tension=80, compression=80, shear=60, bending=2.0),
    "WOOL":    dict(label="Wool Suiting", gsm=250, tension=50, compression=50, shear=40, bending=1.0),
    "CHIFFON": dict(label="Chiffon", gsm=50, tension=20, compression=20, shear=5, bending=0.005),
    "LEATHER": dict(label="Leather (1mm)", gsm=800, tension=150, compression=150, shear=100, bending=15),
}


def vertex_mass_kg(gsm, area_m2, vertex_count):
    """Blender's cloth mass is per vertex, so spread the panel weight evenly."""
    if vertex_count <= 0:
        return 0.0
    return (gsm / 1000.0) * area_m2 / vertex_count
