import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fashionhov"))
from core import homography as hg, geometry as geo  # noqa: E402
from core import fabrics as fb, bodymeasure, mannequin, fit, derive as dv  # noqa: E402
from core.fabrics import vertex_mass_kg  # noqa: E402


class Homography(unittest.TestCase):
    def test_solve_round_trip(self):
        src = [(0.1, 0.2), (0.9, 0.15), (0.95, 0.8), (0.05, 0.9)]
        dst = [(0, 0), (2, 0), (2, 3), (0, 3)]
        h = hg.solve(src, dst)
        np.testing.assert_allclose(hg.apply(h, src), dst, atol=1e-9)
        np.testing.assert_allclose(hg.apply(hg.invert(h), dst), src, atol=1e-9)

    def test_rectify_any_click_order_and_orientation(self):
        # Letter paper photographed landscape, with perspective, clicked in random order.
        true = np.array([(0, 0), (0.2794, 0), (0.2794, 0.2159), (0, 0.2159)])
        warp = hg.solve(true, [(0.3, 0.2), (1.1, 0.25), (1.0, 0.85), (0.35, 0.8)])
        clicked = hg.apply(warp, true)[[2, 0, 3, 1]]
        h, _ = hg.rectify_quad(clicked, 0.2159, 0.2794)  # entered portrait
        out = hg.apply(h, hg.apply(warp, true))
        np.testing.assert_allclose(out, true, atol=1e-9)
        # A point elsewhere in the photo measures correctly too.
        far = np.array([[0.9, 0.6]])
        np.testing.assert_allclose(hg.apply(h, hg.apply(warp, far)), far, atol=1e-9)


class Geometry(unittest.TestCase):
    sq = [(0, 0), (1, 0), (1, 1), (0, 1)]

    def test_basic(self):
        self.assertAlmostEqual(geo.perimeter(self.sq), 4)
        self.assertAlmostEqual(geo.area(self.sq), 1)
        self.assertGreater(geo.signed_area(self.sq), 0)
        self.assertTrue(geo.point_in_polygon((0.5, 0.5), self.sq))
        self.assertFalse(geo.point_in_polygon((1.5, 0.5), self.sq))

    def test_resample_and_fill(self):
        r = geo.resample_outline(self.sq, 0.1)
        self.assertEqual(len(r), 40)
        pts = geo.hex_fill(r, 0.1)
        self.assertTrue(all(geo.point_in_polygon(p, self.sq) for p in pts))
        self.assertGreater(len(pts), 60)

    def test_snap(self):
        x, y = geo.snap_angle((0, 0), (1, 0.1))
        self.assertAlmostEqual(y, 0)
        self.assertAlmostEqual(x, math.hypot(1, 0.1))

    def test_mass(self):
        # 1 m² of 400 gsm denim over 1000 verts -> 0.4 g per vertex
        self.assertAlmostEqual(vertex_mass_kg(400, 1.0, 1000), 0.0004)


class Fabrics(unittest.TestCase):
    def test_oz_conversions(self):
        self.assertAlmostEqual(fb.oz_sq_yd_to_gsm(1), 33.9057, places=3)
        self.assertAlmostEqual(fb.oz_sq_yd_to_gsm(14), 474.68, places=1)
        # oz per linear yard depends on roll width: 8 oz/lin yd at 60 in = 4.8 oz/yd²
        self.assertAlmostEqual(fb.oz_lin_yd_to_gsm(8, 60 * 0.0254), fb.oz_sq_yd_to_gsm(4.8), places=6)
        g = 300
        self.assertAlmostEqual(fb.oz_lin_yd_to_gsm(fb.gsm_to_oz_lin_yd(g, 1.5), 1.5), g)

    def test_drape_monotonic(self):
        b = [fb.drape_to_bending(d / 20) for d in range(21)]
        self.assertTrue(all(x > y for x, y in zip(b, b[1:])))
        self.assertAlmostEqual(fb.drape_to_bending(0.35), 70.0)


class Body(unittest.TestCase):
    want = dict(height=1.93, chest=1.20, waist=1.08, hips=1.15, neck=0.45, thigh=0.67, inseam=0.84, shoulders=0.50)

    def test_measure_dress_form(self):
        v, t = mannequin.build(self.want)
        m, loops = bodymeasure.measure(v, t)
        for k in ("height", "chest", "waist", "hips", "neck"):
            self.assertAlmostEqual(m[k], self.want[k], delta=0.01, msg=k)
        for k in ("inseam", "thigh", "shoulders"):
            self.assertAlmostEqual(m[k], self.want[k], delta=0.03, msg=k)
        self.assertTrue(60 < m["mass"] < 160)

    def test_fit_closes_gap(self):
        knobs = [(k, v * 0.7, v * 1.3) for k, v in self.want.items()]
        ev = lambda x: bodymeasure.measure(*mannequin.build(x))[0]
        x, m, rms, _ = fit.fit(knobs, dict(self.want), ev, self.want, iters=2)
        self.assertLess(rms, 0.5)


class Features(unittest.TestCase):
    base = [(1, (0, 0)), (2, (0.5, 0)), (3, (0.5, 0.6)), (4, (0, 0.6))]

    def test_no_features_is_identity(self):
        d = dv.derive(self.base)
        self.assertEqual(d.sew_xy(), [p for _, p in self.base])
        self.assertEqual(d.cut, [p for _, p in self.base])
        self.assertEqual(d.jumps, set())

    def test_pleat_adds_intake_but_not_sewn_length(self):
        for kind, mult in (("KNIFE", 2), ("BOX", 4), ("INVERTED", 4)):
            d = dv.derive(self.base, pleats=[dict(id=1, va=3, vb=4, t=0.5, depth=0.02, kind=kind, stitch=0.05)])
            xs = [p[0] for p in d.cut]
            self.assertAlmostEqual(max(xs) - min(xs), 0.5 + mult * 0.02, msg=kind)
            top, j = d.chain(3, 4)
            self.assertAlmostEqual(dv.polyline_len(top, j), 0.5, msg=kind)
            self.assertAlmostEqual(dv.polyline_len(top), 0.5 + mult * 0.02, msg=kind)
            self.assertEqual(len(d.sews), 1)

    def test_point_mapping_round_trip(self):
        d = dv.derive(self.base, pleats=[dict(id=1, va=3, vb=4, t=0.5, depth=0.03, kind="KNIFE", stitch=0)])
        for p in [(0.1, 0.3), (0.4, 0.2)]:
            q = d.unmap_point(d.map_point(p))
            self.assertAlmostEqual(q[0], p[0])
            self.assertAlmostEqual(q[1], p[1])

    def test_dart(self):
        d = dv.derive(self.base, darts=[dict(id=1, va=3, vb=4, t=0.3, width=0.03, length=0.1)])
        top, j = d.chain(3, 4)
        self.assertAlmostEqual(dv.polyline_len(top, j), 0.47)
        self.assertEqual(len(d.cut), 7)               # 4 corners + 2 legs + apex
        (a1, apex), (a2, apex2) = d.sews[0]
        self.assertAlmostEqual(math.dist(a1, apex), math.dist(a2, apex2))
        self.assertAlmostEqual(apex[1], 0.5)          # 10 cm straight down from the top edge

    def test_fly_extension_keeps_seam(self):
        d = dv.derive(self.base, flies=[dict(id=1, va=4, vb=1, start=0.0, length=0.18, width=0.035)])
        self.assertAlmostEqual(min(p[0] for p in d.cut), -0.035)
        cf, j = d.chain(4, 1)
        self.assertAlmostEqual(dv.polyline_len(cf, j), 0.6)
        self.assertTrue(any(l["kind"] == "fly_stitch" for l in d.lines))

    def test_tapered_pleat(self):
        d = dv.derive(self.base, pleats=[dict(id=1, va=3, vb=4, t=0.5, depth=0.02, kind="KNIFE",
                                              stitch=0.03, taper=0.25)])
        top = [p[0] for p in d.cut if abs(p[1] - 0.6) < 1e-9]
        bottom = [p[0] for p in d.cut if abs(p[1]) < 1e-9]
        self.assertAlmostEqual(max(top) - min(top), 0.54)       # opened 4 cm at the edge
        self.assertAlmostEqual(max(bottom) - min(bottom), 0.5)  # nothing at the far edge
        lines = [l for l in d.lines if l["kind"] == "pleat_fold"]
        self.assertTrue(all(abs(l["pts"][1][1] - 0.35) < 1e-9 for l in lines))   # meet at the pivot
        for q in [(0.1, 0.55), (0.1, 0.1), (0.45, 0.5)]:
            r = d.unmap_point(d.map_point(q))
            self.assertAlmostEqual(r[0], q[0])
            self.assertAlmostEqual(r[1], q[1])

    def test_fisheye_dart(self):
        d = dv.derive(self.base, inner_darts=[dict(id=1, c=(0.25, 0.3), width=0.03, up=0.1, down=0.08)])
        self.assertEqual(len(d.holes), 1)
        self.assertEqual(d.sew_xy(), [p for _, p in self.base])   # outline untouched
        a, b = d.sews[0]
        self.assertAlmostEqual(dv.polyline_len(a), dv.polyline_len(b))

    def test_scoop_pocket(self):
        d = dv.derive(self.base, scoops=[dict(id=1, corner=3, width=0.12, depth=0.08, curve=0.35)])
        ex = [p for p, _ in d.export]
        self.assertNotIn((0.5, 0.6), [tuple(round(c, 9) for c in p) for p in ex])   # paper: corner cut away
        self.assertIn((0.5, 0.6), [tuple(round(c, 9) for c in p) for p in d.cut])   # sim: fabric stays
        side, j = d.chain(2, 3)
        self.assertAlmostEqual(dv.polyline_len(side, j), 0.6)                         # seams unaffected

    def test_seam_allowance_offset(self):
        sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
        out = dv.offset_closed(sq, [0.01, 0.02, 0.01, 0.03])
        self.assertEqual([tuple(round(c, 6) for c in p) for p in out],
                         [(-0.03, -0.01), (1.02, -0.01), (1.02, 1.01), (-0.03, 1.01)])


if __name__ == "__main__":
    unittest.main()
