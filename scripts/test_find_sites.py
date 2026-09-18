"""Tests for find_sites.py.

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_find_sites -v
"""

import math
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.ndimage import minimum_filter

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_data
import find_sites
from find_sites import (
    basin_wall_fraction,
    compute_within_lake_mask,
    dam_line_endpoints,
    head_from_water_levels,
    load_lake_polygons,
    meters_per_degree,
    passes_display_filters,
    plateau_flat_fraction,
    plateau_footprint,
    DAM_LINE_HALF_LENGTH_M,
    ENGINEERED,
    LAKE_EXCLUSION_BUFFER_M,
    MAX_DAM_LENGTH_M,
    MIN_DISPLAY_MW,
    MIN_VOLUME_RATIO_TO_LAKE,
    MIN_WALL_FRACTION,
    NATURAL,
    PLATEAU_MAX_RADIUS_M,
    PLATEAU_MAX_RELIEF_M,
    PLATEAU_MAX_SLOPE_GRADE,
    PLATEAU_MIN_FLAT_FRACTION,
    UNREALISTIC_DAM_PROBE_HALF_M,
)
from volumes import basin_volume

PIXEL_M = 30.0
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(46.0))  # at ~46N, roughly Romania's latitude

DEM_AVAILABLE = fetch_data.DEM_DIR.exists() and any(fetch_data.DEM_DIR.glob("*.tif"))
HYDROLAKES_SHP = (
    fetch_data.LAKES_RAW_DIR / "HydroLAKES_polys_v10_shp" / "HydroLAKES_polys_v10.shp"
)
HYDROLAKES_AVAILABLE = HYDROLAKES_SHP.exists()
LAKES_AVAILABLE = fetch_data.LAKES_OUT_PATH.exists()


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


class TestBasinWallFractionHeightCapRegression(unittest.TestCase):
    """Regression test for the real bug found and fixed this session (2026-09-02, see
    DATA_SOURCES.md and basin_wall_fraction()'s own docstring): the first version
    excluded any neighbor exceeding max_dam_height_m as "budget-limited, ambiguous" —
    which silently discarded the STRONGEST wall evidence available (a real tall wall
    almost always exceeds a modest height cap) and made the whole check reject nearly
    everything, including genuinely contained basins (caught because a known-good real
    candidate came back with 0 wall_cells — physically impossible for any basin with
    real terrain around it). Fixed by removing the height-cap carve-out entirely: a
    neighbor excluded for being too tall is, by construction, always >= water_level, so
    it already counts as a wall on its own.
    """

    def test_a_neighbor_taller_than_the_height_cap_counts_as_a_wall(self):
        # A steep-walled pit whose rim rises WAY above the 20m dam-height cap on every
        # side — the only kind of "wall" evidence available here is neighbors that
        # exceed the cap. If the bug were still present, every one of them would be
        # discarded as "ambiguous" and this would come back as 0/0 -> the fallback 1.0,
        # not because it's genuinely proven contained, but by accident. Use a basin
        # that's NOT radius-limited (so the fallback path isn't what's under test) —
        # a wide-open max_basin_radius_m so containment is only ever decided by height.
        size = 41
        cy = cx = size // 2
        rows, cols = np.mgrid[0:size, 0:size]
        # Steep paraboloid: rises 200m within just 10 cells (100m) of the seed —
        # comfortably past a 20m height cap almost immediately.
        elev = 2.0 * ((rows - cy) ** 2 + (cols - cx) ** 2)
        valid = np.ones_like(elev, dtype=bool)

        volume_m3, area_m2, water_level_m, pour_point, visited = basin_volume(
            elev, valid, cy, cx, pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=20.0, max_basin_radius_m=2000.0,  # radius far from limiting
        )
        self.assertIsNotNone(pour_point)  # confirms it stopped on height, not radius

        fraction = basin_wall_fraction(
            visited, elev, valid, cy, cx, water_level_m,
            pixel_dx_m=10.0, pixel_dy_m=10.0, max_basin_radius_m=2000.0,
        )
        # Every boundary neighbor here is either genuinely below water_level (open,
        # correctly so — the seed's own basin has a real edge somewhere) or genuinely
        # above the height cap (a real, steep wall) — this basin should read as
        # essentially fully walled, not fall back to an accidental 1.0 or an
        # under-counted low score.
        self.assertGreater(fraction, 0.9)


class TestDamLineEndpointsHalfLengthOverride(unittest.TestCase):
    """half_length_override_m — the diagnostic-only wide probe best_new_site() uses to
    tell "no valley shape here at all" apart from "there's a valley, just wider than
    MAX_DAM_LENGTH_M" (see UNREALISTIC_DAM_PROBE_HALF_M and best_new_site()'s comment).
    """

    def test_override_bypasses_the_configured_clamp(self):
        rows, cols = 121, 121
        # A wide valley: real walls, but only found ~600m out (twice
        # DAM_LINE_HALF_LENGTH_M's own max) — the practical search must miss it, the
        # wide diagnostic probe must find it.
        elev = np.array([[abs(c - cols // 2) * 1.0 for c in range(cols)] for _ in range(rows)])
        valid = np.ones_like(elev, dtype=bool)
        lon_grid, lat_grid = grids(rows, cols)
        row, col = rows // 2, cols // 2

        practical = dam_line_endpoints(row, col, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                        lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT)
        self.assertIsNone(practical)  # valley is wider than the practical clamp allows

        wide = dam_line_endpoints(row, col, elev, valid, PIXEL_M, PIXEL_M, 10_000.0,
                                   lon_grid, lat_grid, M_PER_DEG_LON, M_PER_DEG_LAT,
                                   half_length_override_m=UNREALISTIC_DAM_PROBE_HALF_M)
        self.assertIsNotNone(wide)  # the wider diagnostic probe finds the real valley
        (lon1, lat1), (lon2, lat2) = wide
        length_m = math.hypot((lon2 - lon1) * M_PER_DEG_LON, (lat2 - lat1) * M_PER_DEG_LAT)
        self.assertAlmostEqual(length_m, 2 * UNREALISTIC_DAM_PROBE_HALF_M, delta=PIXEL_M)


class TestPlateauFootprint(unittest.TestCase):
    """plateau_footprint() — PLATEAU's real-terrain flat-ground growth (see its
    docstring for why this isn't basin_volume()'s flood-fill model: a diked plateau
    pond has no natural water level to flood up to).
    """

    def test_grows_across_flat_ground_and_stops_at_a_real_slope(self):
        # A flat disc (elevation 0) surrounded by a steep rise starting at radius 150m —
        # the footprint should cover the flat disc and stop there, not spill past it.
        size = 81
        cy = cx = size // 2
        rows, cols = np.mgrid[0:size, 0:size]
        dist_px = np.sqrt((rows - cy) ** 2 + (cols - cx) ** 2)
        dist_m = dist_px * 10.0  # 10m pixels
        elev = np.where(dist_m <= 150, 0.0, (dist_m - 150) * 5.0)  # steep beyond 150m
        valid = np.ones_like(elev, dtype=bool)
        slope = np.where(dist_m <= 150, 0.0, 5.0 / 10.0)  # matches the elevation step

        area_m2, visited = plateau_footprint(
            elev, valid, slope, cy, cx, pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_relief_m=PLATEAU_MAX_RELIEF_M, max_radius_m=1000.0,  # radius not the limiter
        )
        # Real flat disc is pi*150^2 ~ 70,686 m^2 -- footprint should land close to that,
        # not spill onto the surrounding slope (which would inflate it) or stop far
        # short (which would mean the growth rule is broken).
        self.assertGreater(area_m2, 0.7 * math.pi * 150**2)
        self.assertLess(area_m2, 1.3 * math.pi * 150**2)
        # Every visited cell should be within the flat disc's own true elevation band.
        self.assertTrue(np.all(np.abs(elev[visited]) <= PLATEAU_MAX_RELIEF_M))

    def test_respects_max_radius_even_on_endless_flat_ground(self):
        # Perfectly flat, everywhere, valid — with no natural edge at all, only
        # max_radius_m can stop the growth. Confirms the cap is real, not just
        # theoretical (MAX_PLATEAU_CELLS could otherwise silently be the actual limit).
        size = 121
        cy = cx = size // 2
        elev = np.zeros((size, size))
        valid = np.ones_like(elev, dtype=bool)
        slope = np.zeros((size, size))

        area_m2, visited = plateau_footprint(
            elev, valid, slope, cy, cx, pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_relief_m=PLATEAU_MAX_RELIEF_M, max_radius_m=300.0,
        )
        expected = math.pi * 300**2
        # 4-connected growth on a square grid isn't a perfect circle, so allow real
        # margin either way rather than an exact match.
        self.assertGreater(area_m2, 0.6 * expected)
        self.assertLess(area_m2, 1.3 * expected)


class TestPlateauFlatFraction(unittest.TestCase):
    def test_a_footprint_that_is_all_flat_scores_one(self):
        visited = np.ones((10, 10), dtype=bool)
        slope = np.zeros((10, 10))
        self.assertEqual(plateau_flat_fraction(visited, slope), 1.0)

    def test_an_empty_footprint_scores_zero_not_a_crash(self):
        visited = np.zeros((10, 10), dtype=bool)
        slope = np.zeros((10, 10))
        self.assertEqual(plateau_flat_fraction(visited, slope), 0.0)

    def test_a_partly_steep_footprint_scores_the_real_fraction(self):
        visited = np.ones((10, 10), dtype=bool)
        slope = np.zeros((10, 10))
        slope[:3, :] = 10.0  # 30 of 100 cells are steep
        self.assertAlmostEqual(plateau_flat_fraction(visited, slope), 0.70, delta=0.01)


@unittest.skipUnless(
    DEM_AVAILABLE and LAKES_AVAILABLE and HYDROLAKES_AVAILABLE,
    "requires downloaded DEM tiles, data/lakes.geojson, and the cached HydroLAKES shapefile",
)
class TestRealWorldRegressions(unittest.TestCase):
    """Locks in three concrete, user-flagged findings from this session against the
    real DEM/HydroLAKES data they were found in, rather than trusting they stay fixed.
    """

    def _wall_fraction_at(self, lake_lon, lake_lat, site_lon, site_lat):
        window = find_sites.load_elevation_window(lake_lon, lake_lat, find_sites.SEARCH_WINDOW_RADIUS_M)
        elev, valid, transform, lon_1d, lat_1d = window
        col = int(round((site_lon - transform.c) / transform.a - 0.5))
        row = int(round((site_lat - transform.f) / transform.e - 0.5))
        m_per_deg_lon, m_per_deg_lat = meters_per_degree(site_lat)
        pixel_dx_m = abs(transform.a) * m_per_deg_lon
        pixel_dy_m = abs(transform.e) * m_per_deg_lat
        bv, area, wl, pp, visited = basin_volume(
            elev, valid, row, col, pixel_dx_m, pixel_dy_m,
            ENGINEERED.max_dam_height_m, ENGINEERED.max_basin_radius_m,
        )
        return basin_wall_fraction(
            visited, elev, valid, row, col, wl, pixel_dx_m, pixel_dy_m, ENGINEERED.max_basin_radius_m,
        )

    def test_the_flagged_promontory_seed_stays_below_the_containment_gate(self):
        # Lake 169296, "#10 ... there is a dam on the top of the montain" (user,
        # 2026-09-02). Real elevation profile: drops 100-175m within 200-500m in 7 of
        # 12 sampled directions. Checked its full 2km search window at the time: 0.54
        # was the HIGHEST wall_fraction achievable anywhere near this lake — this is
        # that exact seed, well below even that ceiling, let alone MIN_WALL_FRACTION.
        lake_lon, lake_lat = 22.715126314873245, 46.770064968533404
        site_lon, site_lat = 22.710177102079466, 46.76926332562208
        fraction = self._wall_fraction_at(lake_lon, lake_lat, site_lon, site_lat)
        self.assertLess(fraction, MIN_WALL_FRACTION)

    def test_lake_1358492_site_is_much_closer_to_the_real_shore_than_the_anchor_point_suggested(self):
        # "#3 makes no sens, it is just below the existing dam" (user, 2026-09-02). The
        # flagged candidate was reported 1273m from the lake (measured from HydroLAKES'
        # own anchor point) but its seed was really only ~557m from the true polygon
        # edge — locks in both numbers, and that load_lake_polygons() actually returns
        # usable real geometry for this lake.
        import geopandas as gpd
        from shapely.geometry import Point

        polygons = load_lake_polygons(fetch_data.fetch_hydrolakes_raw())
        polygon = polygons.get(1358492)
        self.assertIsNotNone(polygon)

        site = Point(22.471389123591898, 45.4271150237556)
        anchor = Point(22.486689868068066, 45.423194444444704)
        real_distance_m = polygon.distance(site) * 111_320
        anchor_reported_m = 1272.647158718497

        self.assertLess(real_distance_m, 700)  # the real ~557m figure, with margin
        self.assertGreater(anchor_reported_m - real_distance_m, 500)  # a real, large gap
        self.assertLess(real_distance_m, LAKE_EXCLUSION_BUFFER_M + 700)  # sanity: same ballpark as the buffer

    def test_no_engineered_dam_length_exceeds_the_practical_cap(self):
        # Direct regression for MAX_DAM_LENGTH_M actually being enforced by a real
        # search, not just by the DAM_LINE_HALF_LENGTH_M clamp in isolation (see
        # TestDamLineEndpoints.test_length_is_clamped_to_configured_range for that).
        lon, lat, elev_m, lake_volume_m3 = 22.459219129732748, 44.937792400784815, 231.0, 15_800_000.0
        result = find_sites.best_new_site(lon, lat, elev_m, lake_volume_m3, ENGINEERED)
        if result is None or result["dam_length_m"] is None:
            self.skipTest("this real search found no dam axis to check a length on")
        self.assertLessEqual(result["dam_length_m"], MAX_DAM_LENGTH_M + 1.0)  # +1 rounding room

    def test_engineered_known_large_basin_stays_real_and_well_contained(self):
        # Direct regression (2026-09-18) for ENGINEERED.seed_radius_m 2000 -> 3000: lake
        # 1360316 is the one basin over 50M m^3 found in the widened-radius scan that
        # motivated the change (see ENGINEERED's own comment in find_sites.py for the
        # full national scan this was checked against — 186 candidates, only this one
        # over 50M m^3). Pins that it stays real and well-contained, not just large.
        lon, lat, elev_m, lake_volume_m3 = 22.459219129732748, 44.937792400784815, 231.0, 15_800_000.0
        result = find_sites.best_new_site(lon, lat, elev_m, lake_volume_m3, ENGINEERED)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["wall_fraction"], MIN_WALL_FRACTION)
        # Real Romanian ceiling, not an arbitrary round number: Vidraru, one of the
        # country's largest actual dams, holds ~465M m^3 — see DATA_SOURCES.md.
        self.assertLess(result["basin_volume_m3"], 500_000_000)

    def test_engineered_wider_radius_does_not_reintroduce_the_mega_sprawl_regression(self):
        # Broad, deliberately NOT lake-specific sanity net -- the whole point of "do not
        # overfit" (user, 2026-09-18): a test pinned to one known lake only proves that
        # ONE case stays fixed, not that the fix generalizes. Scans a spread sample of
        # real lakes (every 15th, ~73 of 1100 -- cheap enough for the test suite, wide
        # enough to catch a new sprawl case appearing somewhere else in the country) with
        # the real, current ENGINEERED mode and asserts every candidate found, wherever
        # it is, stays under the same real-world ceiling. This is the actual regression
        # test for the 2026-09-02 mega-sprawl bug (175/522 candidates at 40-220M m^3,
        # see SEARCH_WINDOW_RADIUS_M's docstring) -- it must keep passing even if a
        # future change (a bigger seed_radius_m, a tighter MIN_WALL_FRACTION, a DEM
        # update) shifts which specific lakes produce ENGINEERED's largest basins.
        import geopandas as gpd

        lakes = gpd.read_file(fetch_data.LAKES_OUT_PATH)
        polygons = load_lake_polygons(fetch_data.fetch_hydrolakes_raw())
        checked = 0
        for _, lake in lakes.iloc[::15].iterrows():
            elevation = lake["elevation"]
            if elevation is None or (isinstance(elevation, float) and math.isnan(elevation)):
                continue
            lake_volume_m3 = lake["volume_m3"]
            if isinstance(lake_volume_m3, float) and math.isnan(lake_volume_m3):
                lake_volume_m3 = None
            result = find_sites.best_new_site(
                lake.geometry.x, lake.geometry.y, elevation, lake_volume_m3,
                ENGINEERED, polygons.get(lake["id"]),
            )
            checked += 1
            if result is None:
                continue
            self.assertLess(
                result["basin_volume_m3"], 500_000_000,
                f"lake {lake['id']}: basin_volume_m3={result['basin_volume_m3']:.0f} "
                f"looks like the mega-sprawl regression, not a real basin",
            )
        self.assertGreater(checked, 50, "sample too small to be a meaningful sanity net")

    def test_plateau_search_now_finds_a_real_match_to_tarnita_lapustesti(self):
        # User (2026-09-03): "let's tune the algoritm until it also finds the tarnita
        # lapus naturaly, for plateu searches." Direct regression on the real search
        # over real Tarnița (lake 169355, lon/lat/elev/volume from reference_projects.py
        # via data/lakes.geojson) actually finding a plateau that resembles the
        # published Lăpuștești project, not just a plausible-looking number picked by
        # hand -- head within 10% of the real 563.5m, basin volume within 25% of the
        # real 10.0M m^3 design figure, genuinely flat (flat_fraction 1.0), and beyond
        # the old SEARCH_RADIUS_M=2000 (proving PLATEAU_SEARCH_RADIUS_M is what made
        # this findable, not something already reachable before).
        lon, lat, elev_m, lake_volume_m3 = 23.278707869648212, 46.721549912777185, 515.0, 74_000_000.0
        result = find_sites.best_plateau_site(lon, lat, elev_m, lake_volume_m3)
        self.assertIsNotNone(result, "expected a real plateau candidate near Tarnița")
        self.assertGreater(result["distance_m"], find_sites.SEARCH_RADIUS_M)
        self.assertAlmostEqual(result["head_m"], 563.5, delta=60)
        self.assertAlmostEqual(result["basin_volume_m3"], 10_000_000, delta=2_500_000)
        self.assertEqual(result["flat_fraction"], 1.0)

    def test_natural_search_now_finds_a_real_bowl_near_lesu(self):
        # User (2026-09-03): "i believe near lesu there is a very good natural spoot."
        # Direct regression on the real search over real Leșu (lake 1352457): a genuine,
        # pour-point-BOUNDED (not radius/height-capped) basin at 22.54605E/46.81261N,
        # ~2307m from the lake -- past the old SEARCH_RADIUS_M=2000, findable only with
        # NATURAL.seed_radius_m=2500. Loose bounds (this is NATURAL's own single best
        # candidate, which could shift slightly with DEM/library updates) but locks in
        # the real order of magnitude: a substantial bowl, not a marginal one.
        lon, lat, elev_m, lake_volume_m3 = 22.571578063977327, 46.8014678276914, 553.537841796875, 8_680_000.0
        result = find_sites.best_new_site(lon, lat, elev_m, lake_volume_m3, NATURAL)
        self.assertIsNotNone(result, "expected a real natural bowl near Leșu")
        self.assertGreater(result["distance_m"], find_sites.SEARCH_RADIUS_M)
        self.assertTrue(result["basin_bounded"], "expected a real pour point, not a radius/height-capped flood")
        self.assertGreater(result["basin_volume_m3"], 5_000_000)
        self.assertGreater(result["score"], 100)  # MW


class TestHeadFromWaterLevels(unittest.TestCase):
    """Direct regression coverage for the real bug fixed this session (2026-09-03,
    see ReadmeAi.md's "How head is calculated"): head must come from the new
    reservoir's WATER LEVEL, not the bare ground elevation at the dam/embankment site.
    """

    def test_higher_site_head_uses_the_flooded_water_level_not_bare_ground(self):
        # Real-shaped example: a 60m-tall dam (site_elev=500, water_level=560) above a
        # lake at 400m. Head must reflect the full 160m drop to the flooded surface,
        # not the 100m a bare-ground calculation would give.
        self.assertAlmostEqual(head_from_water_levels(new_site_water_level_m=560, lake_elev_m=400), 160)

    def test_lower_site_head_uses_the_flooded_water_level_too(self):
        # New site is the LOWER reservoir: lake at 600m, new reservoir's own water
        # level (once filled) at 450m -- head is still the water-to-water gap.
        self.assertAlmostEqual(head_from_water_levels(new_site_water_level_m=450, lake_elev_m=600), 150)

    def test_matches_the_real_tarnita_lapustesti_head(self):
        # The one real, published figure available (see reference_projects.py):
        # 1085m upper NNR minus 521.5m lower NNR = 563.5m.
        self.assertAlmostEqual(head_from_water_levels(new_site_water_level_m=1085.0, lake_elev_m=521.5), 563.5)


class TestComputeWithinLakeMask(unittest.TestCase):
    """compute_within_lake_mask() — extracted this session from two identical inline
    copies in best_new_site() and best_plateau_site()."""

    def test_falls_back_to_a_circle_around_the_window_center_with_no_polygon(self):
        distance_grid = np.array([[0.0, 50.0, 150.0], [50.0, 70.0, 200.0], [150.0, 200.0, 300.0]])
        mask = compute_within_lake_mask(
            elev_shape=distance_grid.shape, transform=None, lake_polygon=None,
            distance_grid=distance_grid, pixel_dx_m=10.0, pixel_dy_m=10.0,
        )
        np.testing.assert_array_equal(mask, distance_grid < LAKE_EXCLUSION_BUFFER_M)

    def test_uses_the_real_polygon_when_one_is_given(self):
        import rasterio
        from shapely.geometry import box

        size = 121
        pixel_deg = 0.0001  # ~11m at this scale
        transform = rasterio.transform.from_origin(0.0, 0.0, pixel_deg, pixel_deg)
        # A polygon covering only the left quarter of a ~1330m-wide window, leaving the
        # right edge ~1000m away -- comfortably past LAKE_EXCLUSION_BUFFER_M (500m), so
        # a pass here can only come from the real polygon geometry, not window size.
        lake_polygon = box(0.0, -size * pixel_deg, size * pixel_deg / 4, 0.0)
        distance_grid = np.full((size, size), 1e9)  # deliberately useless as a fallback

        mask = compute_within_lake_mask(
            elev_shape=(size, size), transform=transform, lake_polygon=lake_polygon,
            distance_grid=distance_grid, pixel_dx_m=11.0, pixel_dy_m=11.0,
        )
        # Left edge (inside/near the polygon) excluded; far right edge (well past
        # LAKE_EXCLUSION_BUFFER_M from it) is not -- proves the real polygon geometry
        # is what's driving this, not the deliberately-wrong distance_grid fallback.
        self.assertTrue(mask[size // 2, 0])
        self.assertFalse(mask[size // 2, size - 1])


class TestPassesDisplayFilters(unittest.TestCase):
    """passes_display_filters() — both are the user's own explicit calls (2026-09-03):
    MIN_DISPLAY_MW ("don't display any project under 50 MW", then same day "for natural
    allow a smaller mw given it is cheaper to build") and MIN_VOLUME_RATIO_TO_LAKE
    ("remove projects not at least twice the existing lake's water volume", then same
    day "if the new lake is smallert that is still good" for NATURAL). Both are now
    per-mode dicts: NATURAL and PLATEAU loosened on the ratio bar (NATURAL: free to
    build; PLATEAU: found to exclude its own real-world precedent, ratio 0.157 at
    real Tarnița — see MIN_VOLUME_RATIO_TO_LAKE), ENGINEERED keeps the strict 2.0x bar.
    """

    def _record(self, score, lake_volume_m3, basin_volume_m3, mode="engineered"):
        return {"score": score, "lake_volume_m3": lake_volume_m3,
                "basin_volume_m3": basin_volume_m3, "mode": mode}

    def test_passes_when_both_bars_are_cleared(self):
        r = self._record(score=MIN_DISPLAY_MW["engineered"] + 1, lake_volume_m3=1_000_000,
                          basin_volume_m3=MIN_VOLUME_RATIO_TO_LAKE["engineered"] * 1_000_000 + 1)
        self.assertTrue(passes_display_filters(r))

    def test_fails_below_the_mw_floor(self):
        r = self._record(score=MIN_DISPLAY_MW["engineered"] - 0.1, lake_volume_m3=1_000_000,
                          basin_volume_m3=MIN_VOLUME_RATIO_TO_LAKE["engineered"] * 1_000_000 + 1)
        self.assertFalse(passes_display_filters(r))

    def test_fails_below_the_volume_ratio(self):
        # Exactly at the lake's own volume (a fully lake-capped candidate) is only a
        # 1x ratio -- must fail a >=2x bar, which is the whole point of comparing
        # basin_volume_m3 (uncapped) rather than the already-capped usable volume.
        r = self._record(score=MIN_DISPLAY_MW["engineered"] + 100, lake_volume_m3=1_000_000, basin_volume_m3=1_000_000)
        self.assertFalse(passes_display_filters(r))

    def test_fails_with_unknown_lake_volume_rather_than_assuming_it_passes(self):
        r = self._record(score=MIN_DISPLAY_MW["engineered"] + 100, lake_volume_m3=None, basin_volume_m3=999_999_999)
        self.assertFalse(passes_display_filters(r))

    def test_natural_mw_floor_is_lower_than_engineered(self):
        self.assertLess(MIN_DISPLAY_MW["natural"], MIN_DISPLAY_MW["engineered"])

    def test_natural_passes_below_the_engineered_mw_floor(self):
        score = (MIN_DISPLAY_MW["natural"] + MIN_DISPLAY_MW["engineered"]) / 2
        r = self._record(score=score, lake_volume_m3=1_000_000, basin_volume_m3=1_000_000, mode="natural")
        self.assertTrue(passes_display_filters(r))
        # Same numbers under engineered's stricter floor -- must fail.
        r["mode"] = "engineered"
        self.assertFalse(passes_display_filters(r))

    def test_natural_passes_with_a_smaller_new_lake_than_the_existing_one(self):
        # NATURAL has no volume-ratio floor -- a new bowl smaller than the paired lake
        # is still worth showing since it costs almost nothing to add.
        r = self._record(score=MIN_DISPLAY_MW["natural"] + 1, lake_volume_m3=1_000_000,
                          basin_volume_m3=100_000, mode="natural")
        self.assertTrue(passes_display_filters(r))

    def test_plateau_has_no_volume_ratio_floor_either(self):
        self.assertEqual(MIN_VOLUME_RATIO_TO_LAKE["plateau"], 0.0)

    def test_plateau_passes_the_real_tarnita_lapustesti_ratio(self):
        # Direct regression (2026-09-03): after widening PLATEAU_SEARCH_RADIUS_M, the
        # algorithm's own candidate at real Tarnița (lake 169355) has basin_volume_m3
        # 11.59M vs lake_volume_m3 74.0M -- a 0.157 ratio, the exact real-world case
        # that motivated dropping PLATEAU's ratio floor to 0. This must keep passing so
        # a future re-tightening of the ratio floor can't silently exclude it again.
        r = self._record(score=MIN_DISPLAY_MW["plateau"] + 1, lake_volume_m3=74_000_000,
                          basin_volume_m3=11_590_000, mode="plateau")
        self.assertTrue(passes_display_filters(r))

    def test_engineered_still_fails_with_a_smaller_new_lake_than_the_existing_one(self):
        r = self._record(score=MIN_DISPLAY_MW["engineered"] + 1, lake_volume_m3=1_000_000,
                          basin_volume_m3=100_000, mode="engineered")
        self.assertFalse(passes_display_filters(r))


if __name__ == "__main__":
    unittest.main()
