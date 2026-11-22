"""Talk to MPFB (MakeHuman Plugin For Blender) if it is installed.

MPFB is installed as an extension, so its package name depends on the
repository (e.g. bl_ext.blender_org.mpfb). We find its modules by suffix,
the same way MPFB's own script samples do.
"""

import sys
import importlib

MACROS = ("height", "weight", "muscle", "proportions")

# our measurement -> MPFB "decr/incr" target base name
MEASURE_TARGETS = {
    "chest": "measure-bust-circ",
    "waist": "measure-waist-circ",
    "hips": "measure-hips-circ",
    "neck": "measure-neck-circ",
    "thigh": "measure-thigh-circ",
    "inseam": "measure-upperleg-height",
    "shoulders": "measure-shoulder-dist",
}


def _find(suffix, attr):
    for name in list(sys.modules):
        if name.endswith(suffix):
            mod = importlib.import_module(name)
            if hasattr(mod, attr):
                return getattr(mod, attr)
    return None


def services():
    hs = _find("mpfb.services.humanservice", "HumanService")
    ts = _find("mpfb.services.targetservice", "TargetService")
    hop = _find("mpfb.entities.objectproperties", "HumanObjectProperties")
    if not (hs and ts and hop):
        return None
    return hs, ts, hop


def available():
    try:
        return services() is not None
    except Exception:
        return False


def create_human(gender=1.0):
    hs, ts, hop = services()
    macro = ts.get_default_macro_info_dict()
    macro["gender"] = gender
    return hs.create_human(macro_detail_dict=macro)


def is_human(obj):
    return obj is not None and any(k.startswith("HUM_") for k in obj.keys())


def get_macro(obj, name):
    _, _, hop = services()
    return float(hop.get_value(name, entity_reference=obj))


def set_macros(obj, values):
    _, ts, hop = services()
    for k, v in values.items():
        hop.set_value(k, float(v), entity_reference=obj)
    ts.reapply_macro_details(obj)


def get_measure(obj, key):
    _, ts, _ = services()
    base = MEASURE_TARGETS[key]
    pos, neg = base + "-incr", base + "-decr"
    if ts.has_target(obj, pos):
        return ts.get_target_value(obj, pos)
    if ts.has_target(obj, neg):
        return -ts.get_target_value(obj, neg)
    return 0.0


def set_measure(obj, key, value):
    """Same logic as MPFB's own opposed-modifier sliders, so values show up there too."""
    _, ts, _ = services()
    base = MEASURE_TARGETS[key]
    pos, neg = base + "-incr", base + "-decr"
    on, off = (pos, neg) if value >= 0 else (neg, pos)
    if ts.has_target(obj, off):
        ts.set_target_value(obj, off, 0.0)
    if ts.has_target(obj, on):
        ts.set_target_value(obj, on, abs(value))
    elif abs(value) > 1e-4:
        path = ts.target_full_path(on)
        if path:
            ts.load_target(obj, path, weight=abs(value), name=on)
