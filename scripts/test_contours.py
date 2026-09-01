"""Tests for contours.py.

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_contours -v
"""

import unittest

import numpy as np

from contours import generate_contours


class TestGenerateContours(unittest.TestCase):
    def test_flat_grid_has_no_contours(self):
        # No elevation variation means no lines to draw at all.
        lon_1d = np.linspace(20, 21, 10)
        lat_1d = np.linspace(45, 46, 10)
        elev = np.full((10, 10), 500.0)
        valid = np.ones_like(elev, dtype=bool)

        lines = generate_contours(lon_1d, lat_1d, elev, valid, interval_m=50)
        self.assertEqual(lines, [])

    def test_paraboloid_bowl_produces_closed_rings_at_expected_elevations(self):
        # z = x^2 + y^2 (a bowl centered at the origin) — every contour at level L should
        # be a closed ring at radius sqrt(L), so this has an exact, checkable answer.
        lon_1d = np.linspace(-10, 10, 60)
        lat_1d = np.linspace(-10, 10, 60)
        xx, yy = np.meshgrid(lon_1d, lat_1d)
        elev = xx**2 + yy**2
        valid = np.ones_like(elev, dtype=bool)

        lines = generate_contours(lon_1d, lat_1d, elev, valid, interval_m=20)
        self.assertGreater(len(lines), 0)

        levels_seen = {round(line["elevation_m"]) for line in lines}
        self.assertIn(20, levels_seen)
        self.assertIn(40, levels_seen)

        # The 20-level ring should sit at radius sqrt(20) ~= 4.47 from the origin.
        ring_20 = next(line for line in lines if round(line["elevation_m"]) == 20)
        coords = np.array(ring_20["coordinates"])
        radii = np.hypot(coords[:, 0], coords[:, 1])
        self.assertAlmostEqual(radii.mean(), np.sqrt(20), delta=0.3)

    def test_invalid_cells_do_not_produce_spurious_contours_at_the_edge(self):
        # A block of nodata cells shouldn't create a fake cliff at the fill value —
        # filling with the mean (not min/max) keeps it from looking like real terrain.
        lon_1d = np.linspace(0, 10, 20)
        lat_1d = np.linspace(0, 10, 20)
        xx, yy = np.meshgrid(lon_1d, lat_1d)
        elev = 500 + xx * 10  # a gentle, real slope from 500 to 600
        valid = np.ones_like(elev, dtype=bool)
        valid[:, 15:] = False  # right-hand chunk is "nodata"

        lines = generate_contours(lon_1d, lat_1d, elev, valid, interval_m=10)
        # Every returned contour should be a real slope level (between the real min/max
        # of the VALID region), not something bunched up at an artificial fill value.
        real_min, real_max = elev[valid].min(), elev[valid].max()
        for line in lines:
            self.assertGreaterEqual(line["elevation_m"], real_min - 10)
            self.assertLessEqual(line["elevation_m"], real_max + 10)

    def test_no_valid_cells_returns_empty(self):
        elev = np.zeros((5, 5))
        valid = np.zeros((5, 5), dtype=bool)
        lines = generate_contours(np.arange(5.0), np.arange(5.0), elev, valid)
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
