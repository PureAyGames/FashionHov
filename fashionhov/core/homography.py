"""Projective (perspective) transforms used to rectify reference photos."""

import numpy as np


def solve(src, dst):
    """Return the 3x3 homography mapping 4 src points onto 4 dst points."""
    src = np.asarray(src, dtype=float)
    dst = np.asarray(dst, dtype=float)
    if src.shape != (4, 2) or dst.shape != (4, 2):
        raise ValueError("need exactly 4 source and 4 destination points")
    a = np.zeros((8, 8))
    b = np.zeros(8)
    for i, ((x, y), (u, v)) in enumerate(zip(src, dst)):
        a[2 * i] = [x, y, 1, 0, 0, 0, -u * x, -u * y]
        a[2 * i + 1] = [0, 0, 0, x, y, 1, -v * x, -v * y]
        b[2 * i] = u
        b[2 * i + 1] = v
    h = np.linalg.solve(a, b)
    return np.append(h, 1.0).reshape(3, 3)


def apply(h, points):
    """Transform an (N, 2) array of points by homography h."""
    pts = np.asarray(points, dtype=float)
    ones = np.ones((pts.shape[0], 1))
    out = np.hstack([pts, ones]) @ np.asarray(h).T
    return out[:, :2] / out[:, 2:3]


def invert(h):
    hi = np.linalg.inv(np.asarray(h, dtype=float))
    return hi / hi[2, 2]


def scale(s):
    return np.diag([s, s, 1.0])


def order_quad(points):
    """Order 4 points counter-clockwise starting at the bottom-left one."""
    pts = np.asarray(points, dtype=float)
    c = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(angles)]
    start = int(np.argmin(pts[:, 0] + pts[:, 1]))
    return np.roll(pts, -start, axis=0)


def rectify_quad(points, width, height):
    """Homography taking 4 clicked corners of a known rectangle to real units.

    Points may be clicked in any order. The longer side as seen in the photo
    is matched to the longer of width/height, so portrait/landscape does not
    matter. Returns (H, ordered_points) where H maps the clicked space to a
    space where the rectangle spans (0,0)-(w,h).
    """
    q = order_quad(points)
    edge = lambda i: np.linalg.norm(q[(i + 1) % 4] - q[i])
    horiz = (edge(0) + edge(2)) / 2
    vert = (edge(1) + edge(3)) / 2
    big, small = max(width, height), min(width, height)
    w, h = (big, small) if horiz >= vert else (small, big)
    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    return solve(q, dst), q
