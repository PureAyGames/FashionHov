"""Fabric presets, weight-unit conversions and "feel" -> solver mappings.

Weight units:
  * GSM     = grams per square metre (international standard)
  * oz/yd²  = ounces per square yard. This is what denim's "12 oz" means.
              It's an area weight, so it converts to GSM by a fixed factor.
  * oz/lin yd = ounces per *linear* yard: one yard cut off the roll at full
              width. It depends on the roll width, so width is needed.

Drape and stretch are 0..1 "feel" sliders, mapped onto the solver's
bending / tension stiffness. The drape curve was calibrated with a virtual
drape tester (30 cm square on a 9 cm-radius disc, 250 gsm, 1 cm mesh):
the share of the flat area still covered after draping went from ~98% at
drape 0 to ~82% at 0.3 (denim-like), ~55% at 0.5, collapsing below ~20%
from about 0.75 (jersey / silk-like).
"""

import math

OZ_G = 28.349523125          # grams per avoirdupois ounce
YD_M = 0.9144                # metres per yard
GSM_PER_OZYD2 = OZ_G / (YD_M * YD_M)   # 33.9057...

# (drape, bending stiffness) knots, interpolated on a log scale.
DRAPE_KNOTS = [(0.0, 600.0), (0.2, 150.0), (0.35, 70.0), (0.5, 45.0),
               (0.65, 35.0), (0.8, 20.0), (1.0, 2.0)]
# Stretch: 0 = basically no stretch (woven, rigid), 1 = very stretchy knit.
TENSION_RIGID, TENSION_STRETCHY = 2.5, 0.5


def gsm_to_oz_sq_yd(gsm):
    return gsm / GSM_PER_OZYD2


def oz_sq_yd_to_gsm(oz):
    return oz * GSM_PER_OZYD2


def gsm_to_oz_lin_yd(gsm, width_m):
    """Weight of one yard off the roll, at the given roll width."""
    return gsm_to_oz_sq_yd(gsm) * (width_m / YD_M)


def oz_lin_yd_to_gsm(oz, width_m):
    if width_m <= 0:
        raise ValueError("width must be positive")
    return oz_sq_yd_to_gsm(oz * YD_M / width_m)


def drape_to_bending(drape):
    d = min(max(drape, 0.0), 1.0)
    for (d0, b0), (d1, b1) in zip(DRAPE_KNOTS, DRAPE_KNOTS[1:]):
        if d <= d1:
            t = (d - d0) / (d1 - d0)
            return 10 ** (math.log10(b0) + t * (math.log10(b1) - math.log10(b0)))
    return DRAPE_KNOTS[-1][1]


def stretch_to_tension(stretch):
    s = min(max(stretch, 0.0), 1.0)
    return 10 ** (TENSION_RIGID + (TENSION_STRETCHY - TENSION_RIGID) * s)


def solver_settings(gsm, drape, stretch):
    tension = stretch_to_tension(stretch)
    return dict(
        tension=tension,
        compression=tension,
        shear=tension * 0.7,
        bending=drape_to_bending(drape),
    )


# Real per-vertex masses are milligrams; with those, Blender's air drag
# dominates and cloth floats. Scaling every mass by 1000 (grams entered as
# kg) keeps weights physically proportional and the solver stable; the
# drape curve above is calibrated at this scale. Real weight is shown
# to the user separately.
SIM_MASS_SCALE = 1000.0
SIM_AIR_DAMPING = 0.1


def sim_vertex_mass(gsm, area_m2, vertex_count):
    return vertex_mass_kg(gsm, area_m2, vertex_count) * SIM_MASS_SCALE


def vertex_mass_kg(gsm, area_m2, vertex_count):
    """Blender's cloth mass is per vertex, so spread the panel weight evenly."""
    if vertex_count <= 0:
        return 0.0
    return (gsm / 1000.0) * area_m2 / vertex_count


# gsm = real typical weights. drape/stretch = starting guesses; tweak by eye
# with the hand drape test.
FABRICS = {
    "JERSEY":  dict(label="Cotton Jersey (T-shirt)", gsm=160, drape=0.65, stretch=0.8),
    "POPLIN":  dict(label="Cotton Poplin (shirting)", gsm=110, drape=0.45, stretch=0.35),
    "FLEECE":  dict(label="Fleece (hoodie)", gsm=300, drape=0.45, stretch=0.65),
    "TWILL":   dict(label="Cotton Twill (chinos)", gsm=250, drape=0.35, stretch=0.25),
    "DENIM":   dict(label="Denim 12 oz", gsm=round(oz_sq_yd_to_gsm(12)), drape=0.3, stretch=0.2),
    "DENIM_STRETCH": dict(label="Stretch Denim 10 oz", gsm=round(oz_sq_yd_to_gsm(10)), drape=0.4, stretch=0.5),
    "WOOL":    dict(label="Wool Suiting", gsm=250, drape=0.45, stretch=0.3),
    "LINEN":   dict(label="Linen", gsm=180, drape=0.4, stretch=0.15),
    "SATIN":   dict(label="Satin", gsm=120, drape=0.8, stretch=0.3),
    "CHIFFON": dict(label="Chiffon", gsm=50, drape=0.9, stretch=0.4),
    "CANVAS":  dict(label="Canvas / Duck", gsm=400, drape=0.12, stretch=0.05),
    "LEATHER": dict(label="Leather (1 mm)", gsm=800, drape=0.15, stretch=0.1),
}
