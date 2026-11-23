"""Headless test of darts, pleats, hems, zipper fly, hardware, thread and export.
Run with a Python that has `bpy`:  python tests/test_details.py
"""
import os
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fashionhov  # noqa: E402
from fashionhov import trace, cloth, arrange, fitmap, features as ft, details, export, sewing  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)
fashionhov.register()
ctx = bpy.context
sc = ctx.scene
b = sc.fh_body
for k, v in dict(height=1.85, chest=1.05, waist=0.90, hips=1.02, inseam=0.84).items():
    setattr(b, k, v)
b.use_mass = False
bpy.ops.fashionhov.create_avatar(kind='FORM')
bpy.ops.fashionhov.fit_avatar()
m = b.avatar["fh_measured"]

W, L = 0.30, 0.40
front = trace.create_panel(ctx, [(0, 0), (W, 0), (W, L), (0, L)], "Front")   # vids 1..4: BL BR TR TL
back = trace.create_panel(ctx, [(0.6, 0), (0.6 + W, 0), (0.6 + W, L), (0.6, L)], "Back")
f = front.fh_features

def add(coll, **kw):
    x = coll.add()
    if hasattr(x, "id"):
        x.id = ft.new_id(front)
    for k, v in kw.items():
        setattr(x, k, v)
    return x

dart = add(f.darts, va=3, vb=4, t=0.3, width=0.03, length=0.09)
pleat = add(f.pleats, va=3, vb=4, t=0.7, depth=0.015, kind='KNIFE', stitch=0.04)
hem = add(f.hems, va=1, vb=2, width=0.02, fold='DOUBLE')
zipper = add(f.hardware, kind='ZIPPER', va=4, vb=1, start=0.0, length=0.15, style='FLY', fly_width=0.035)
rivet = add(f.hardware, kind='RIVET', x=0.0, y=0.0, size=0.009, finish='COPPER')
ft.set_hardware_world(front, rivet, (0.25, 0.3))
button = add(f.hardware, kind='BUTTON_SHANK', size=0.017, finish='BRASS')
ft.set_hardware_world(front, button, (0.05, 0.37))
hole = add(f.hardware, kind='BUTTONHOLE', size=0.019)
ft.set_hardware_world(front, hole, (0.12, 0.37))

d = ft.get_derived(front)
xs = [p[0] for p in d.cut]
# The top edge runs right-to-left (CCW), so the pleat spreads the part left of it
# 3 cm further left, and the fly sticks out another 3.5 cm beyond that.
print(f"front cut: {len(d.cut)} pts, x {min(xs):.3f}..{max(xs):.3f}")
assert abs(min(xs) + 0.03 + 0.035) < 1e-6 and abs(max(xs) - W) < 1e-6
top, j = d.chain(3, 4)
assert abs(sewing.polyline_length(sewing.Poly(top, j)) - (W - 0.03)) < 1e-6   # dart removed from sewn length
# rivet sits on the + side of the pleat (pleat direction is -x along the top edge 3->4), so it does not move
rw = ft.hardware_world(front, rivet)
print("rivet world", tuple(round(c, 4) for c in rw))

# side seams + topstitch
for (fa, fb), (ba, bb) in (((2, 3), (4, 1)), ((4, 1), (2, 3))):
    s = sewing.add_seam(sc, (front, fa, fb), (back, ba, bb))
sc.fh_seams[0].topstitch = 'DOUBLE'
sc.fh_seams[0].ts_side = 'A'

for p, where in ((front, 'FRONT'), (back, 'BACK')):
    p.fh_place.where = where
    p.fh_place.top = m["z_waist"] - m["z_floor"] + 0.05
    p.fh_place.gap = 0.04
    cloth.build_cloth(ctx, p, 0.012)
fp = bpy.data.objects["Front_cloth"]
assert len(fp["fh_sews"]) == 2, "dart + pleat internal seams"
pw = max(v.co.x for v in fp.data.vertices) - min(v.co.x for v in fp.data.vertices)
print(f"front piece width {pw:.3f} m")

# auto rebuild: deeper pleat -> wider piece, nothing else touched
pleat.depth = 0.03
ft.flush_now(ctx)
fp = bpy.data.objects["Front_cloth"]
pw2 = max(v.co.x for v in fp.data.vertices) - min(v.co.x for v in fp.data.vertices)
print(f"after pleat depth 1.5 -> 3 cm: width {pw2:.3f} m")
assert abs((pw2 - pw) - 0.03) < 2e-3
assert len(f.darts) == 1 and len(f.hems) == 1 and len(sc.fh_seams) == 2

# details before simulation (on the pieces)
res = details.rebuild(ctx)
obj, n_edges, n_pts = res
print(f"details: {n_edges} thread/teeth segments, {n_pts} hardware items")
assert n_edges > 100 and n_pts == 2          # rivet + jeans button (buttonhole is thread, fly zip hidden)

bpy.ops.fashionhov.arrange()
g = arrange.build_garment(ctx)
for fr in range(1, 81):
    sc.frame_set(fr)
co = fitmap.evaluated_coords(ctx, g)

# dart legs should be closed after sewing
off = 0
for p in g["fh_pieces"]:
    if p == "Front_cloth":
        break
    off += len(bpy.data.objects[p].data.vertices)
a, bb = fp["fh_sews"][1] if len(fp["fh_sews"][1][0]) == 2 and abs(fp["fh_sews"][1][0][0][1] - L) < 1e-6 else fp["fh_sews"][0]
sa = arrange.boundary_on_chain(fp, [tuple(x) for x in a])
sb = arrange.boundary_on_chain(fp, [tuple(x) for x in bb])
gaps = [np.linalg.norm(co[off + i] - co[off + j]) for (i, _), (j, _) in zip(sa, sb)]
print(f"internal seam gap after sim: median {np.median(gaps) * 1000:.1f} mm")
assert np.median(gaps) < 0.01

# thread/hardware geometry follows the garment
dg = ctx.evaluated_depsgraph_get()
det = obj.evaluated_get(dg)
dv_ = np.array([det.matrix_world @ v.co for v in det.data.vertices])
from mathutils.bvhtree import BVHTree
bvh = BVHTree.FromPolygons([tuple(c) for c in co], [tuple(p.vertices) for p in g.data.polygons])
dist = [bvh.find_nearest(tuple(p))[3] for p in dv_[:: max(1, len(dv_) // 400)]]
print(f"details geometry: {len(dv_)} verts, median distance to cloth {np.median(dist) * 1000:.1f} mm")
assert len(dv_) > 500 and np.median(dist) < 0.005

# thread toggle hides thread
sc.fh_thread.visible = False
_, n2, _ = details.rebuild(ctx)
assert n2 == 0
sc.fh_thread.visible = True

# export
tmp = tempfile.mkdtemp()
svg = os.path.join(tmp, "jeans.svg")
dxf = os.path.join(tmp, "jeans.dxf")
pieces = export.collect(ctx)
export.write_svg(svg, pieces)
export.write_dxf(dxf, pieces)
txt = open(svg).read()
for needle in ('id="Front"', "#c0392b", "#2c6fbb", "#8e44ad", "#27ae60", "<circle"):
    assert needle in txt, needle
fg = next(p for p in pieces if p["name"] == "Front")
cx = [p[0] for p in fg["cut"]]
cy = [p[1] for p in fg["cut"]]
print(f"exported Front cut line {(max(cx) - min(cx)) * 100:.1f} x {(max(cy) - min(cy)) * 100:.1f} cm "
      f"(with 1 cm SA, 2.8 cm hem allowance, fly, pleat)")
assert abs((max(cy) - min(cy)) - (L + 0.01 + 0.028)) < 1e-3
assert "LINE" in open(dxf).read()
sc.fh_sizes.clear()
bpy.ops.fashionhov.add_standard_sizes()
xl = export.collect(ctx, 3)
print("sizes export ok,", len(xl), "pieces in XL")

fashionhov.unregister()
print("OK")
