import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fashionhov"))
from core import homography as hg, geometry as geo  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
