"""Avatar: your body from tape measurements.

Uses MPFB (realistic MakeHuman body, Sims-style sliders) when installed,
otherwise a parametric dress form. Either way, "Fit" adjusts the body until
a virtual tape measure reads your numbers.
"""

import time
import bpy
import numpy as np

from .core import bodymeasure, mannequin, fit as fitter
from . import mpfb_bridge as mpfb

KEYS = ("height", "chest", "waist", "hips", "neck", "thigh", "inseam", "shoulders")
LABELS = dict(height="Height", chest="Chest", waist="Waist", hips="Hips", neck="Neck",
              thigh="Thigh", inseam="Inseam (crotch to floor)", shoulders="Shoulder Width",
              mass="Weight")
TAPES = {}   # avatar name -> {key: (z, pts2d)} for the viewport overlay


def _len(name, default, desc=""):
    return bpy.props.FloatProperty(name=name, default=default, min=0.05, max=3.0,
                                   subtype='DISTANCE', unit='LENGTH', description=desc)


class FHBody(bpy.types.PropertyGroup):
    avatar: bpy.props.PointerProperty(name="Avatar", type=bpy.types.Object)
    gender: bpy.props.FloatProperty(name="Female ⟷ Male", default=1.0, min=0, max=1, subtype='FACTOR')
    height: _len("Height", 1.78)
    mass: bpy.props.FloatProperty(name="Weight", default=80.0, min=20, max=400, subtype='NONE', unit='MASS',
                                  description="Body weight. The avatar's is estimated from its volume")
    chest: _len("Chest", 1.00, "Around the fullest part of the chest, under the arms")
    waist: _len("Waist", 0.86, "Around the narrowest part of the torso")
    hips: _len("Hips", 1.00, "Around the fullest part of the seat")
    neck: _len("Neck", 0.39, "Around the middle of the neck")
    thigh: _len("Thigh", 0.58, "Around the top of the thigh, just under the crotch")
    inseam: _len("Inseam", 0.82, "Crotch straight down to the floor, barefoot")
    shoulders: _len("Shoulders", 0.47, "Shoulder point to shoulder point")
    use_height: bpy.props.BoolProperty(default=True)
    use_mass: bpy.props.BoolProperty(default=True)
    use_chest: bpy.props.BoolProperty(default=True)
    use_waist: bpy.props.BoolProperty(default=True)
    use_hips: bpy.props.BoolProperty(default=True)
    use_neck: bpy.props.BoolProperty(default=False)
    use_thigh: bpy.props.BoolProperty(default=False)
    use_inseam: bpy.props.BoolProperty(default=True)
    use_shoulders: bpy.props.BoolProperty(default=False)


def targets(body):
    t = {k: getattr(body, k) for k in KEYS if getattr(body, "use_" + k)}
    if body.use_mass:
        t["mass"] = body.mass
    return t


# ---------- mesh access ----------

def mesh_arrays(context, obj):
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    v = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", v)
    v = v.reshape(-1, 3)
    t = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    ev.to_mesh_clear()
    mw = np.array(obj.matrix_world)
    v = v @ mw[:3, :3].T + mw[:3, 3]
    return v, t.reshape(-1, 3)


def measure_avatar(context, obj, with_mass=True):
    v, t = mesh_arrays(context, obj)
    m, loops = bodymeasure.measure(v, t, with_mass)
    TAPES[obj.name] = loops
    obj["fh_measured"] = {k: float(x) for k, x in m.items()}
    return m


# ---------- dress form ----------

def set_form(obj, params):
    v, t = mannequin.build(params)
    me = bpy.data.meshes.new(obj.data.name)
    me.from_pydata(v.tolist(), [], t.tolist())
    for p in me.polygons:
        p.use_smooth = True
    old = obj.data
    obj.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    obj["fh_form"] = {k: float(x) for k, x in params.items()}


def create_form(context, body):
    params = {k: getattr(body, k) for k in KEYS}
    me = bpy.data.meshes.new("FH Dress Form")
    obj = bpy.data.objects.new("FH Dress Form", me)
    context.scene.collection.objects.link(obj)
    set_form(obj, params)
    return obj


def fit_form(context, obj, body, progress=None):
    tg = targets(body)
    tg.pop("mass", None)    # a dress form's weight follows from its measurements
    start = dict(obj.get("fh_form", {}))
    start.update({k: getattr(body, k) for k in KEYS})
    knobs = [(k, start[k] * 0.6, start[k] * 1.4) for k in KEYS if k in tg]
    fixed = {k: start[k] for k in KEYS if k not in tg}

    def ev(x):
        p = dict(fixed, **x)
        return bodymeasure.measure(*mannequin.build(p), with_mass=False)[0]
    x, _, rms, calls = fitter.fit(knobs, start, ev, tg, iters=3, progress=progress)
    set_form(obj, dict(fixed, **x))
    return rms, calls


# ---------- MPFB ----------

def fit_mpfb(context, obj, body, progress=None):
    tg = targets(body)
    with_mass = "mass" in tg
    mods = [m for m in obj.modifiers if m.type == 'SUBSURF' and m.show_viewport]
    for m in mods:
        m.show_viewport = False
    try:
        mpfb.set_macros(obj, {"gender": body.gender})

        def ev_macros(x):
            mpfb.set_macros(obj, x)
            return measure_avatar(context, obj, with_mass)

        # Stage 1: overall build from height / weight / muscle / proportions.
        knobs = [(k, 0.0, 1.0) for k in mpfb.MACROS]
        x0 = {k: mpfb.get_macro(obj, k) for k in mpfb.MACROS}
        stage1 = {k: v for k, v in tg.items() if k in ("height", "mass", "chest", "waist", "hips")}
        x1, _, _, c1 = fitter.fit(knobs, x0, ev_macros, stage1, iters=5, progress=progress)
        mpfb.set_macros(obj, x1)

        # Stage 2: individual measurement targets (+ height) for the exact numbers.
        mkeys = [k for k in mpfb.MEASURE_TARGETS if k in tg]

        def ev_detail(x):
            for k in mkeys:
                mpfb.set_measure(obj, k, x[k])
            if "height" in x:
                mpfb.set_macros(obj, {"height": x["height"]})
            return measure_avatar(context, obj, with_mass)
        knobs = [(k, -1.0, 1.0) for k in mkeys] + [("height", 0.0, 1.0)]
        x0 = {k: mpfb.get_measure(obj, k) for k in mkeys}
        x0["height"] = x1["height"]
        x2, _, rms, c2 = fitter.fit(knobs, x0, ev_detail, tg, iters=4, progress=progress)
        ev_detail(x2)
        return rms, c1 + c2
    finally:
        for m in mods:
            m.show_viewport = True


def ensure_collision(obj):
    if not any(m.type == 'COLLISION' for m in obj.modifiers):
        obj.modifiers.new("Collision", 'COLLISION')
        obj.collision.thickness_outer = 0.004
        obj.collision.cloth_friction = 5.0


# ---------- operators ----------

class FH_OT_create_avatar(bpy.types.Operator):
    """Create your avatar: a realistic MPFB human if MPFB is installed, otherwise a dress form"""
    bl_idname = "fashionhov.create_avatar"
    bl_label = "Create Avatar"
    bl_options = {'REGISTER', 'UNDO'}

    kind: bpy.props.EnumProperty(items=[('AUTO', "Auto", ""), ('MPFB', "MPFB Human", ""),
                                        ('FORM', "Dress Form", "")], default='AUTO')

    def execute(self, context):
        body = context.scene.fh_body
        use_mpfb = self.kind == 'MPFB' or (self.kind == 'AUTO' and mpfb.available())
        if use_mpfb:
            if not mpfb.available():
                self.report({'ERROR'}, "MPFB isn't installed (Edit > Preferences > Get Extensions > MPFB)")
                return {'CANCELLED'}
            obj = mpfb.create_human(body.gender)
            obj["fh_avatar"] = "MPFB"
        else:
            obj = create_form(context, body)
            obj["fh_avatar"] = "FORM"
        ensure_collision(obj)
        body.avatar = obj
        measure_avatar(context, obj)
        self.report({'INFO'}, "Avatar created. Enter your measurements and press Fit.")
        return {'FINISHED'}


class FH_OT_fit_avatar(bpy.types.Operator):
    """Reshape the avatar until a virtual tape measure reads your measurements"""
    bl_idname = "fashionhov.fit_avatar"
    bl_label = "Fit to My Measurements"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene.fh_body.avatar is not None

    def execute(self, context):
        body = context.scene.fh_body
        obj = body.avatar
        wm = context.window_manager
        wm.progress_begin(0, 100)
        n = [0]

        def progress(it, j):
            n[0] += 1
            wm.progress_update(min(99, n[0]))
        t0 = time.time()
        try:
            if obj.get("fh_avatar") == "MPFB":
                rms, calls = fit_mpfb(context, obj, body, progress)
            else:
                rms, calls = fit_form(context, obj, body, progress)
        except ValueError as e:
            self.report({'ERROR'}, f"Couldn't measure the body: {e}")
            return {'CANCELLED'}
        finally:
            wm.progress_end()
        measure_avatar(context, obj)
        unit = '"' if context.scene.fh.units == 'IN' else " cm"
        err = rms / 2.54 if unit == '"' else rms
        self.report({'INFO'}, f"Fitted in {time.time() - t0:.0f}s, average error {err:.1f}{unit}")
        return {'FINISHED'}


class FH_OT_measure_avatar(bpy.types.Operator):
    """Measure the avatar again (after moving sliders yourself, e.g. in MPFB's Model panel)"""
    bl_idname = "fashionhov.measure_avatar"
    bl_label = "Measure Avatar"

    @classmethod
    def poll(cls, context):
        return context.scene.fh_body.avatar is not None

    def execute(self, context):
        try:
            measure_avatar(context, context.scene.fh_body.avatar)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class FH_OT_measured_to_inputs(bpy.types.Operator):
    """Copy the avatar's current measurements into the input fields"""
    bl_idname = "fashionhov.measured_to_inputs"
    bl_label = "Use Avatar's Numbers"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        a = context.scene.fh_body.avatar
        return a is not None and "fh_measured" in a

    def execute(self, context):
        body = context.scene.fh_body
        m = body.avatar["fh_measured"]
        for k in KEYS + ("mass",):
            if k in m:
                setattr(body, k, m[k])
        return {'FINISHED'}


classes = (FH_OT_create_avatar, FH_OT_fit_avatar, FH_OT_measure_avatar, FH_OT_measured_to_inputs)


def register():
    bpy.utils.register_class(FHBody)
    bpy.types.Scene.fh_body = bpy.props.PointerProperty(type=FHBody)


def unregister():
    del bpy.types.Scene.fh_body
    bpy.utils.unregister_class(FHBody)
