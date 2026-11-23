"""Headless test: pockets as child panels, fisheye darts, tapered pleats and
non-destructive detail toggles. Run with a Python that has `bpy`."""
import os
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fashionhov  # noqa: E402
from fashionhov import trace, cloth, arrange, fitmap, features as ft, pockets, export, details, sewing  # noqa: E402
from fashionhov.core import geometry as geo  # noqa: E402

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
front = trace.create_panel(ctx, [(0, 0), (W, 0), (W, L), (0, L)], "Front")          # vids 1..4 BL BR TR TL
back = trace.create_panel(ctx, [(0.6, 0), (0.6 + W, 0), (0.6 + W, L), (0.6, L)], "Back")

# --- quick adds ---
bp = pockets.add_patch_pocket(ctx, back, (0.6 + W / 2, 0.22), 'JEANS')
sp = pockets.add_scoop_pocket(ctx, front, pockets.nearest_corner(front, (W, L)))
pl = front.fh_features.pleats.add()
pl.id, pl.va, pl.vb, pl.t, pl.depth, pl.taper = ft.new_id(front), 3, 4, 0.5, 0.012, 0.25
fd = back.fh_features.darts.add()
fd.id, fd.mode, fd.width, fd.length, fd.down = ft.new_id(back), 'INNER', 0.02, 0.07, 0.05
ft.set_hardware_world(back, fd, (0.6 + 0.07, 0.25))
zp = front.fh_features.hardware.add()
zp.id, zp.kind, zp.va, zp.vb, zp.length, zp.style = ft.new_id(front), 'ZIPPER', 4, 1, 0.15, 'FLY'
pockets.add_fly_shield(ctx, front, zp)
ft.flush_now(ctx)

children = [o for o in sc.objects if o.get("fh_feature_of")]
print("child panels:", sorted(o.name for o in children))
assert {o.name for o in children} == {"Back Back Pocket", "Front Pocket Facing", "Front Pocket Bag", "Front Fly Shield"}
assert bp.piece and len(bp.piece.fh_features.hardware) == 2, "jeans pocket rivets"
assert any(l["kind"] == "pocket_place" for l in ft.get_derived(back).lines)

# pocket panels are real panels: reshape one in edit mode-like fashion (move a vertex)
pk = bp.piece
pk.data.vertices[2].co.y -= 0.01          # deeper point
ft.request_rebuild(back)
ft.flush_now(ctx)

# --- cloth + sim ---
for p, where in ((front, 'FRONT'), (back, 'BACK')):
    p.fh_place.where = where
    p.fh_place.top = m["z_waist"] - m["z_floor"] + 0.05
    p.fh_place.gap = 0.04
    cloth.build_cloth(ctx, p, 0.012)
ft.request_rebuild(pk)
ft.flush_now(ctx)                               # pocket gets its own cloth piece automatically
pk_piece = arrange.piece_of(sc, pk)
assert pk_piece is not None, "pocket piece built"
assert arrange.piece_of(sc, sp.facing) is None, "facing is paper-only"
# fisheye dart: a hole in the back piece
bk_piece = arrange.piece_of(sc, back)
hole = ft.get_derived(back).holes[0]
inside = [v for v in bk_piece.data.vertices
          if geo.point_in_polygon((v.co.x, v.co.y), hole) and geo.dist_to_polygon((v.co.x, v.co.y), hole) > 1e-4]
on_edge = [v for v in bk_piece.data.vertices if geo.dist_to_polygon((v.co.x, v.co.y), hole) < 1e-4]
print(f"fisheye dart: {len(inside)} verts inside, {len(on_edge)} on its legs")
assert not inside and len(on_edge) > 8, "dart is a hole with stitchable legs"

for s_ in (((front, 2, 3), (back, 4, 1)), ((front, 4, 1), (back, 2, 3))):
    sewing.add_seam(sc, *s_)
bpy.ops.fashionhov.arrange()
g = arrange.build_garment(ctx)
names = list(g["fh_pieces"])
print("garment pieces:", names)
assert pk_piece.name in names
stitches = sum(1 for e in g.data.edges if e.is_loose)
for fr in range(1, 81):
    sc.frame_set(fr)
co = fitmap.evaluated_coords(ctx, g)
off = 0
for n in names:
    if n == pk_piece.name:
        break
    off += len(bpy.data.objects[n].data.vertices)
pocket_co = co[off: off + len(pk_piece.data.vertices)]
from mathutils.bvhtree import BVHTree
boff = sum(len(bpy.data.objects[n].data.vertices) for n in names[:names.index(bk_piece.name)])
bco = co[boff: boff + len(bk_piece.data.vertices)]
bvh = BVHTree.FromPolygons([tuple(c) for c in bco], [tuple(p.vertices) for p in bk_piece.data.polygons])
dist = [bvh.find_nearest(tuple(p))[3] for p in pocket_co]
print(f"{stitches} stitches; pocket sits a median {np.median(dist) * 1000:.1f} mm off the back panel")
assert np.median(dist) < 0.012

# --- toggles: hide all pockets, nothing deleted ---
sc.fh_show.pockets = False
ft.flush_now(ctx)
assert not ft.panel_active(pk, sc) and pk.hide_get()
assert len(back.fh_features.pockets) == 1 and bpy.data.objects.get(pk.name)
assert not any(l["kind"] == "pocket_place" for l in ft.get_derived(back).lines)
g2 = arrange.build_garment(ctx)
assert pk_piece.name not in list(g2["fh_pieces"]), "hidden pocket left out of the sim"
ex = export.collect(ctx)
assert not any("Pocket" in p["name"] for p in ex), [p["name"] for p in ex]
sc.fh_show.pockets = True
ft.flush_now(ctx)
assert not pk.hide_get()
names_on = [p["name"] for p in export.collect(ctx)]
print("export with pockets:", names_on)
assert {"Back Back Pocket", "Front Pocket Facing", "Front Pocket Bag", "Front Fly Shield"} <= set(names_on)

# per-item toggle: pleat off -> front back to its drafted width
w_on = max(p[0] for p in ft.get_derived(front).cut) - min(p[0] for p in ft.get_derived(front).cut)
pl.enabled = False
ft.flush_now(ctx)
w_off = max(p[0] for p in ft.get_derived(front).cut) - min(p[0] for p in ft.get_derived(front).cut)
print(f"front width with pleat {w_on:.3f} m, pleat switched off {w_off:.3f} m")
assert abs((w_on - w_off) - 0.024) < 1e-3   # fly edge is slightly slanted by the taper
pl.enabled = True
# zippers off -> fly extension and shield gone
sc.fh_show.zippers = False
ft.flush_now(ctx)
assert min(p[0] for p, _ in ft.get_derived(front).export) > -0.03 and not ft.panel_active(zp.child, sc)
sc.fh_show.zippers = True

# scoop: paper pattern cut, sim keeps fabric
d = ft.get_derived(front)
near = lambda pts: any(abs(p[0] - W) < 1e-6 and abs(p[1] - L) < 1e-6 for p in pts)
assert near(d.cut), "sim keeps the corner fabric"
assert not near([p for p, _ in d.export]), "paper pattern is cut along the scoop"
tmp = tempfile.mkdtemp()
export.write_svg(os.path.join(tmp, "p.svg"), export.collect(ctx))
assert "pocketing" in open(os.path.join(tmp, "p.svg")).read()
res = details.rebuild(ctx)
print("details:", res[1], "thread segments,", res[2], "hardware")

# deleting the pocket detail removes its panel too
bpy.ops.object.select_all(action='DESELECT')
ctx.view_layer.objects.active = back
bpy.ops.fashionhov.feature_remove(coll="pockets", index=0)
assert bpy.data.objects.get("Back Back Pocket") is None

fashionhov.unregister()
print("OK")
