"""End-to-end headless test: avatar -> panels -> sew -> simulate -> fit map -> grade.
Run with a Python that has the `bpy` module:  python tests/test_pipeline.py
"""
import sys
import time
from pathlib import Path

import bpy
import bmesh
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fashionhov  # noqa: E402
from fashionhov import trace, cloth, sewing, arrange, fitmap, drape  # noqa: E402

IN = 0.0254
bpy.ops.wm.read_factory_settings(use_empty=True)
fashionhov.register()
ctx = bpy.context
sc = ctx.scene
sc.fh.units = 'IN'

# ---- avatar: dress form fitted to measurements ----
b = sc.fh_body
me = dict(height=76 * IN, chest=46 * IN, waist=40 * IN, hips=45 * IN, inseam=33 * IN)
for k, v in me.items():
    setattr(b, k, v)
b.use_mass = False
assert bpy.ops.fashionhov.create_avatar(kind='FORM') == {'FINISHED'}
t0 = time.time()
assert bpy.ops.fashionhov.fit_avatar() == {'FINISHED'}
m = b.avatar["fh_measured"]
for k, v in me.items():
    print(f"  {k:7s} want {v / IN:5.1f}in  avatar {m[k] / IN:5.1f}in")
    assert abs(m[k] - v) < 0.5 * IN, k
print(f"avatar fitted in {time.time() - t0:.0f}s, est. weight {m['mass'] / 0.4536:.0f} lb")

# ---- two panels: a tube skirt that should sit on the hips ----
W = 0.93 * me["hips"] / 2          # slightly smaller than the hips: it must grip
L = 0.45
front = trace.create_panel(ctx, [(0, 0), (W, 0), (W, L), (0, L)], "Front")
back = trace.create_panel(ctx, [(0.8, 0), (0.8 + W, 0), (0.8 + W, L), (0.8, L)], "Back")
hip_top = m["z_waist"] - m["z_floor"] + 0.06
for p, where in ((front, 'FRONT'), (back, 'BACK')):
    p.fh_place.where = where
    p.fh_place.top = hip_top
    p.fh_place.gap = 0.03
    p.fh_grade.girth = 'HIPS'

# Sew the side seams through the real Edit Mode selection path.
def select_edges(obj, pairs):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    for e in bm.edges:
        e.select = False
    for v in bm.verts:
        v.select = False
    loop = bm.faces[0].verts[:]
    for i, j in pairs:
        e = bm.edges.get((loop[i], loop[j]))
        e.select = True
    bmesh.update_edit_mesh(obj.data)

for f_edge, b_edge in (((1, 2), (3, 0)), ((3, 0), (1, 2))):
    for o in sc.objects:
        o.select_set(o in (front, back))
    ctx.view_layer.objects.active = front
    bpy.ops.object.mode_set(mode='EDIT')
    select_edges(front, [f_edge])
    select_edges(back, [b_edge])
    assert bpy.ops.fashionhov.sew() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
assert len(sc.fh_seams) == 2 and all(sewing.seam_ok(s) for s in sc.fh_seams)
print("seams:", [(s.number, round(sewing.polyline_length(sewing.seam_chains(s)[0]), 3)) for s in sc.fh_seams])

# Adding a point to a panel must not break its seams.
ctx.view_layer.objects.active = front
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(front.data)
bm.faces.ensure_lookup_table()
loop = bm.faces[0].verts[:]
bmesh.ops.subdivide_edges(bm, edges=[bm.edges.get((loop[0], loop[1]))], cuts=1)
bmesh.update_edit_mesh(front.data)
bpy.ops.object.mode_set(mode='OBJECT')
sewing.ensure_vids(front)
assert all(sewing.seam_ok(s) for s in sc.fh_seams), "seams broke after adding a point"

# ---- cloth, arrange, simulate ----
sc.fh.cloth_spacing = 0.015
for p in (front, back):
    cloth.build_cloth(ctx, p, sc.fh.cloth_spacing)
    bpy.data.objects[p.name + "_cloth"].fh_fabric.preset = 'JERSEY'
for o in sc.objects:
    o.select_set(False)
assert bpy.ops.fashionhov.arrange() == {'FINISHED'}
# ---- 3D sewing: select edges on the arranged pieces, must match the 2D seam ----
def select_piece_side(piece, x_pattern):
    bm = bmesh.from_edit_mesh(piece.data)
    uv = bm.loops.layers.uv["Pattern"]
    px = {l.vert: l[uv].uv.x for f in bm.faces for l in f.loops}
    for e in bm.edges:
        e.select = e.is_boundary and all(abs(px[v] - x_pattern) < 1e-4 for v in e.verts)
    bmesh.update_edit_mesh(piece.data)

pf, pb = bpy.data.objects["Front_cloth"], bpy.data.objects["Back_cloth"]
first = (sc.fh_seams[0].a_v0, sc.fh_seams[0].a_v1, sc.fh_seams[0].b_v0, sc.fh_seams[0].b_v1)
for o in sc.objects:
    o.select_set(o in (pf, pb))
ctx.view_layer.objects.active = pf
bpy.ops.object.mode_set(mode='EDIT')
select_piece_side(pf, W)
select_piece_side(pb, 0.8)
assert bpy.ops.fashionhov.sew() == {'FINISHED'}
bpy.ops.object.mode_set(mode='OBJECT')
s3 = sc.fh_seams[-1]
print("3D seam:", (s3.a_obj.name, s3.a_v0, s3.a_v1, s3.b_obj.name, s3.b_v0, s3.b_v1), "2D seam #1:", first)
assert (s3.a_v0, s3.a_v1, s3.b_v0, s3.b_v1) == first, "3D sewing should find the same edges as 2D"
sc.fh_seams.remove(len(sc.fh_seams) - 1)

g = arrange.build_garment(ctx)
nsew = sum(1 for e in g.data.edges if e.is_loose)
print(f"garment {len(g.data.vertices)} verts, {nsew} stitches")
assert nsew > 40
t0 = time.time()
for fr in range(1, 91):
    sc.frame_set(fr)
co = fitmap.evaluated_coords(ctx, g)
gaps = [np.linalg.norm(co[e.vertices[0]] - co[e.vertices[1]]) for e in g.data.edges if e.is_loose]
print(f"simulated 90 frames in {time.time() - t0:.0f}s; seam gap median {np.median(gaps) * 100:.1f} cm, "
      f"garment z {co[:, 2].min():.2f}..{co[:, 2].max():.2f} (crotch {m['z_crotch']:.2f}, waist {m['z_waist']:.2f})")
assert np.median(gaps) < 0.02, "seams didn't close"
assert co[:, 2].max() > m["z_crotch"], "skirt fell off the hips"

# ---- fit maps ----
assert bpy.ops.fashionhov.fit_map(kind='STRAIN') == {'FINISHED'}
assert bpy.ops.fashionhov.fit_map(kind='EASE') == {'FINISHED'}
print("fit:", dict(g["fh_fit"]["EASE"]), "| strain attr:", fitmap.STRAIN_ATTR in g.data.color_attributes)

# ---- sizes ----
assert bpy.ops.fashionhov.add_standard_sizes() == {'FINISHED'}
assert bpy.ops.fashionhov.size_from_body() == {'FINISHED'}
assert bpy.ops.fashionhov.grade() == {'FINISHED'}
graded = [o for o in sc.objects if o.get("fh_graded_of")]
assert len(graded) == 2 * 5
xl = next(o for o in graded if o["fh_size"] == "XL" and o["fh_graded_of"] == "Back")
w_xl = max(v.co.x for v in xl.data.vertices) - min(v.co.x for v in xl.data.vertices)
assert abs(w_xl / W - 44 / 38.5) < 1e-3, w_xl / W
print(bpy.data.texts["FH Size Chart"].as_string())

# ---- back to pieces ----
assert bpy.ops.fashionhov.unsew() == {'FINISHED'}
assert bpy.data.objects.get("FH Garment") is None

# ---- drape test ----
assert bpy.ops.fashionhov.drape_test() == {'FINISHED'}
assert bpy.data.scenes.get(drape.TEST_SCENE)

fashionhov.unregister()
print("OK")
