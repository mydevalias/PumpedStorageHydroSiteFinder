"""Tests for find_sites.py.

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_find_sites -v
"""

import math
import unittest

import numpy as np

from find_sites import basin_wall_fraction, dam_line_endpoints, DAM_LINE_HALF_LENGTH_M, MIN_WALL_FRACTION
from volumes import basin_volume

PIXEL_M = 30.0
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(46.0))  # at ~46N, roughly Romania's latitude


def grids(rows=21, cols=21):
    """Standard north-up raster axes: longitude increases with column, latitude
    DECREASES with row — the sign dam_line_endpoints has to get right for its
    north-south component (a real bug, fixed this session — see the class docstring).
    """
    lon_1d = np.arange(cols) * (PIXEL_M / M_PER_DEG_LON)
    lat_1d = 46.0 - np.arange(rows) * (PIXEL_M / M_PER_DEG_LAT)
    return np.meshgrid(lon_1d, lat_1d)


class TestDamLineEndpoints(unittest.TestCase):
    """dam_line_endpoints() went through two rounds of fixes this session, both
    documented in its own docstring:

    1. It used the gradient's PERPENDICULAR direction, on the backwards reasoning
       "perpendicular to slope = along the contour = where a dam runs" (a contour runs
       ALONG a valley, parallel to flow; a dam has to CROSS that).
    2. Fixed to align WITH the gradient — mathematically consistent, but checked
       directly against real elevation profiles and found 7 of 8 sampled ENGINEERED
       candidates' lines climbed monotonically end to end: no dip anywhere, just a
       straight line up a hillside. A single pixel's gradient doesn't reveal whether
       the site is actually a valley at all.

    The current version instead tries several real orientations and requires the
    terrain to genuinely rise on BOTH sides of the seed — these tests are built around
    that "does it actually dip" requirement, not a single gradient reading.
    """

    def test_finds_the_axis_across_a_north_south_valley(self):
        # Trough at column 10, walls rising east and west, constant along every row —
        # so the valley's own long axis is north-south, and a real dam needs to run
        # east-west. Seed exactly at the trough (a true local low point, the case
        # dam sites are actually drawn for — see basin_volume()'s docstring).
        rows, cols = 21, 21
        elev = np.array([[(c - 10) ** 2 for c in range(cols)] for _ in range(rows)], dtype=float)
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)

        result = dam_line_endpoints(10, 10, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                     lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNotNone(result)
        (lon1, lat1), (lon2, lat2) = result
        d_lon, d_lat = abs(lon2 - lon1), abs(lat2 - lat1)
        self.assertGreater(d_lon, d_lat * 3)  # mostly east-west, ~no north-south

    def test_finds_the_axis_across_an_east_west_valley(self):
        # Mirror case: trough along row 10 (constant per row), walls rising north and
        # south — the valley runs east-west, so the dam should run north-south.
        rows, cols = 21, 21
        elev = np.array([[(r - 10) ** 2 for _ in range(cols)] for r in range(rows)], dtype=float)
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)

        result = dam_line_endpoints(10, 10, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                     lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNotNone(result)
        (lon1, lat1), (lon2, lat2) = result
        d_lon, d_lat = abs(lon2 - lon1), abs(lat2 - lat1)
        self.assertGreater(d_lat, d_lon * 3)  # mostly north-south, ~no east-west

    def test_a_uniform_slope_has_no_dam_axis(self):
        # A plain tilted plane (no valley at all — this is what an "engineered"
        # candidate's flooded hillside often looks like, per the real-data check that
        # motivated this rewrite). For any straight line through a point on a plane,
        # one end is always lower than the seed and the other always higher by the
        # same amount — never both higher — so no orientation should ever qualify.
        rows, cols = 21, 21
        elev = np.array([[float(r + c) for c in range(cols)] for r in range(rows)])
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)

        result = dam_line_endpoints(10, 10, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                     lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNone(result)

    def test_flat_ground_has_no_dam_axis(self):
        rows, cols = 21, 21
        elev = np.full((rows, cols), 500.0)
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)

        result = dam_line_endpoints(10, 10, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                     lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNone(result)

    def test_length_is_clamped_to_configured_range(self):
        rows, cols = 61, 61  # large enough that even the max clamp stays in-bounds
        elev = np.array([[(c - 30) ** 2 for c in range(cols)] for _ in range(rows)], dtype=float)
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)
        row, col = 30, 30

        # A tiny basin should clamp up to the minimum half-length, not shrink to ~0.
        result_tiny = dam_line_endpoints(row, col, elev, valid, PIXEL_M, PIXEL_M, 1.0,
                                          lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNotNone(result_tiny)
        (lon1, lat1), (lon2, lat2) = result_tiny
        length_m = math.hypot((lon2 - lon1) * M_PER_DEG_LON, (lat2 - lat1) * M_PER_DEG_LAT)
        self.assertAlmostEqual(length_m, 2 * DAM_LINE_HALF_LENGTH_M[0], delta=1)

        # A huge basin should clamp down to the maximum half-length, not grow unbounded.
        result_huge = dam_line_endpoints(row, col, elev, valid, PIXEL_M, PIXEL_M, 1e12,
                                          lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNotNone(result_huge)
        (lon1, lat1), (lon2, lat2) = result_huge
        length_m = math.hypot((lon2 - lon1) * M_PER_DEG_LON, (lat2 - lat1) * M_PER_DEG_LAT)
        self.assertAlmostEqual(length_m, 2 * DAM_LINE_HALF_LENGTH_M[1], delta=1)

    def test_out_of_window_endpoint_is_treated_as_no_data_for_that_angle(self):
        # A valley near the edge of the search window: the "correct" east-west axis
        # partly runs off the grid. Should still find SOME valid axis rather than
        # crashing or silently sampling garbage — either None, or a real in-bounds line.
        rows, cols = 21, 21
        elev = np.array([[(c - 1) ** 2 for c in range(cols)] for _ in range(rows)], dtype=float)
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)

        result = dam_line_endpoints(10, 1, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                     lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        if result is not None:
            (lon1, lat1), (lon2, lat2) = result
            for lon, lat in ((lon1, lat1), (lon2, lat2)):
                self.assertGreaterEqual(lon, lon_grid.min() - 1e-9)
                self.assertLessEqual(lon, lon_grid.max() + 1e-9)


class TestBasinWallFraction(unittest.TestCase):
    """Replaces dam_line_endpoints as ENGINEERED's actual containment gate (see
    best_new_site() and DATA_SOURCES.md, 2026-09-02) — checks the basin's own flooded
    footprint for real topographic walls, not a short +/-400m probe from the seed. These
    tests run basin_volume() first to get a real visited/water_level pair, the same way
    the real search does, rather than hand-building a visited mask.
    """

    def test_a_true_enclosed_pit_is_well_above_the_gate(self):
        # A paraboloid bowl, walls well within both budgets: real terrain rises on
        # every side, comfortably closing the basin before either cap is hit.
        size = 41
        cy = cx = size // 2
        rows, cols = np.mgrid[0:size, 0:size]
        elev = 0.02 * ((rows - cy) ** 2 + (cols - cx) ** 2)  # 0 at center, rises outward
        valid = np.ones_like(elev, dtype=bool)

        volume_m3, area_m2, water_level_m, pour_point, visited = basin_volume(
            elev, valid, cy, cx, pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=50.0, max_basin_radius_m=500.0,
        )
        self.assertGreater(volume_m3, 0)  # sanity: a real basin was found at all

        fraction = basin_wall_fraction(
            visited, elev, valid, cy, cx, water_level_m,
            pixel_dx_m=10.0, pixel_dy_m=10.0, max_basin_radius_m=500.0,
        )
        self.assertGreaterEqual(fraction, MIN_WALL_FRACTION)

    def test_a_plateau_edge_sprawl_scores_below_the_gate(self):
        # The real bug this replaces a check for: a seed with a genuine wall on ONE
        # side (north) but flat, open terrain on the others that only stops because it
        # runs off a cliff into a real valley (elevation drops well below seed_elev-2,
        # basin_volume()'s own downhill floor) — well within max_basin_radius_m, not cut
        # off by our own radius/height budget. The flood sprawls across the whole flat
        # plateau; its boundary there borders genuinely lower, open terrain, not a wall.
        size = 61
        seed_row = seed_col = 30
        rows, cols = np.mgrid[0:size, 0:size]
        dist_from_seed = np.maximum(np.abs(rows - seed_row), np.abs(cols - seed_col))

        elev = np.zeros((size, size))
        north_wall = rows < seed_row
        elev[north_wall] = 20.0 * (seed_row - rows[north_wall])  # real wall, north only
        plateau = (~north_wall) & (dist_from_seed <= 12)
        elev[plateau] = 0.0  # flat plateau at seed elevation, south/east/west
        cliff = (~north_wall) & (dist_from_seed > 12)
        elev[cliff] = -50.0  # drops well below seed_elev - 2 just past the plateau edge
        valid = np.ones_like(elev, dtype=bool)

        volume_m3, area_m2, water_level_m, pour_point, visited = basin_volume(
            elev, valid, seed_row, seed_col, pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=50.0, max_basin_radius_m=1000.0,  # generous — not the limiter
        )
        # Sanity: the flood really did sprawl across the whole plateau, not just the
        # cell budget or radius cutting it short.
        self.assertGreater(visited.sum(), 200)

        fraction = basin_wall_fraction(
            visited, elev, valid, seed_row, seed_col, water_level_m,
            pixel_dx_m=10.0, pixel_dy_m=10.0, max_basin_radius_m=1000.0,
        )
        self.assertLess(fraction, MIN_WALL_FRACTION)

    def test_radius_limited_flat_plain_is_not_called_open(self):
        # A perfectly flat plain within the search radius, cut off ONLY by
        # max_basin_radius_m itself (no real terrain anywhere, walled or open) — this is
        # the same "we don't actually know" case basin_bounded=False already flags
        # elsewhere; basin_wall_fraction shouldn't call it definitively open either,
        # since every boundary cell is budget-limited, not evidence of a real leak.
        size = 41
        cy = cx = size // 2
        elev = np.zeros((size, size))
        valid = np.ones_like(elev, dtype=bool)

        volume_m3, area_m2, water_level_m, pour_point, visited = basin_volume(
            elev, valid, cy, cx, pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=50.0, max_basin_radius_m=150.0,  # smaller than the grid itself
        )
        self.assertIsNone(pour_point)  # confirms it was cut short by radius, not a real rim

        fraction = basin_wall_fraction(
            visited, elev, valid, cy, cx, water_level_m,
            pixel_dx_m=10.0, pixel_dy_m=10.0, max_basin_radius_m=150.0,
        )
        self.assertEqual(fraction, 1.0)


if __name__ == "__main__":
    unittest.main()
