"""Headless Blender test. Run with a Python that has the `bpy` module:
    python tests/test_blender.py
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fashionhov  # noqa: E402
from fashionhov import photo, trace, cloth, util  # noqa: E402
from fashionhov.core import homography as hg, geometry as geo  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
fashionhov.register()
ctx = bpy.context
scene = ctx.scene

# Fake 4:3 photo.
img = bpy.data.images.new("garment.jpg", 400, 300)
obj = photo.create_photo_object(ctx, img)
assert math.isclose(obj["fh_aspect"], 4 / 3)

# Simulate a tilted camera: the true letter sheet (and a 30x60 cm pant leg)
# appear perspective-warped in image space.
paper = np.array([(0, 0), (0.2159, 0), (0.2159, 0.2794), (0, 0.2794)])
warp = hg.solve(paper, [(0.10, 0.10), (0.30, 0.12), (0.31, 0.38), (0.09, 0.36)])
clicks = hg.apply(warp, paper)  # world == image space before calibration (H = I)

# Trace a panel BEFORE calibrating, to check panels follow recalibration.
leg_true = [(0.3, 0.0), (0.6, 0.0), (0.6, 0.6), (0.3, 0.6)]
p = trace.create_panel(ctx, [tuple(x) for x in hg.apply(warp, np.array(leg_true))], "Leg", obj)

photo.calibrate_four_points(obj, clicks, 0.2159, 0.2794, scene)
pts = util.world_outline(p)
x0, y0, x1, y1 = geo.bbox(pts)
print(f"leg after rectify: {x1 - x0:.4f} x {y1 - y0:.4f} m")
assert abs((x1 - x0) - 0.30) < 1e-6 and abs((y1 - y0) - 0.60) < 1e-6

# 2-point refine: say the 30 cm edge is actually 31 cm.
photo.calibrate_two_points(obj, pts[0], pts[1], 0.31 * math.dist(pts[0], pts[1]) / 0.30, scene)
pts = util.world_outline(p)
assert abs(math.dist(pts[0], pts[1]) - 0.31) < 1e-6

# Cloth mesh with fabric weight.
c = cloth.build_cloth(ctx, p, "DENIM", 0.02)
area = sum(f.area for f in c.data.polygons)
assert abs(area - geo.area(pts)) / area < 1e-3, area
assert all(len(f.vertices) == 3 for f in c.data.polygons)
st = c.modifiers["FH Cloth"].settings
total_kg = st.mass * len(c.data.vertices)
print(f"cloth: {len(c.data.vertices)} verts, {c['fh_weight_g']:.0f} g, sim mass total {total_kg * 1000:.0f} g")
assert abs(total_kg * 1000 - c["fh_weight_g"]) < 1e-3

# Rebuild replaces rather than duplicates.
cloth.build_cloth(ctx, p, "JERSEY", 0.03)
assert len([o for o in scene.objects if o.get("fh_cloth_source")]) == 1

# Run a few sim frames to make sure the cloth solver accepts it.
scene.frame_start, scene.frame_end = 1, 5
for f in range(1, 6):
    scene.frame_set(f)
dz = c.evaluated_get(ctx.evaluated_depsgraph_get()).data.vertices[0].co.z
print(f"after 5 frames vertex z = {dz:.4f}")
assert dz < 0, "cloth should fall under gravity"

fashionhov.unregister()
print("OK")
