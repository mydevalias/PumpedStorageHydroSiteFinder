"""Tests for volumes.py.

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_volumes -v

Two kinds of test here, deliberately kept separate:

1. Synthetic elevation grids with a hand-computable exact answer — these test
   basin_volume()'s math itself (including regression coverage for the two real
   bugs found in session: the runaway-downhill-flood bug, and the earlier
   unbounded-radius sprawl bug), and need no external data.

2. A real-world reference case using the actual downloaded DEM around Lake
   Tarnița (Cluj County) — skipped automatically if data/dem/ isn't populated
   (run fetch_data.py first). Important caveat learned validating against this
   real site: GLO-30 DEM reflects *today's* terrain, so an EXISTING lake shows
   up as a flat, already-flooded surface, not the dry basin underneath it —
   there is no way to recover a real lake's true volume from surface DEM data
   alone. That means we can't write a test asserting basin_volume() reproduces
   a real lake's published volume; the real-world test below instead documents
   a genuine, verified limitation (see TestBasinVolumeRealWorld's docstring).

   What we CAN validate for real: HydroLAKES ships its own volume estimate per
   lake (Vol_total, from Messager et al. 2016 — not derived from our DEM).
   fetch_data.py now carries that into lakes.geojson as volume_m3, and
   find_sites.py uses it to cap a candidate's usable volume at whatever the
   existing lake actually holds (see TestUsableCyclingVolume, and
   volumes.usable_cycling_volume_m3's docstring for why that cap exists). For
   Tarnița this gives 74M m3 vs. the independently published >70M m3
   (ro.wikipedia.org/wiki/Lacul_Tarni%C8%9Ba) — close enough to trust the
   Vol_total -> volume_m3 plumbing.
"""

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_data
import find_sites
from volumes import (
    estimated_power_mw,
    storage_capacity_mwh,
    basin_volume,
    empirical_reservoir_volume_m3,
    fit_reservoir_area_volume_model,
    implied_flow_m3_s,
    power_from_flow_mw,
    realistic_power_mw,
    usable_cycling_volume_m3,
    DESIGN_DISCHARGE_HOURS,
    MAX_BASIN_CELLS,
    MAX_FLOW_RATE_M3_S,
)

DEM_AVAILABLE = fetch_data.DEM_DIR.exists() and any(fetch_data.DEM_DIR.glob("*.tif"))
HYDROLAKES_SHP = (
    fetch_data.LAKES_RAW_DIR / "HydroLAKES_polys_v10_shp" / "HydroLAKES_polys_v10.shp"
)
HYDROLAKES_AVAILABLE = HYDROLAKES_SHP.exists()


class TestBasinVolumeSynthetic(unittest.TestCase):
    """No DEM, no lakes — just elevation arrays with a volume we can compute by hand."""

    def test_pit_with_flat_rim(self):
        # 3x3 grid: a single low cell (0) surrounded by a rim at 10. 4-connectivity means
        # the pit floods the center first, then the 4 edge-adjacent rim cells, then the 4
        # corners (each reachable via two rim cells) — the whole grid, since nothing here
        # exceeds max_dam_height_m or max_basin_radius_m.
        #   10 10 10
        #   10  0 10
        #   10 10 10
        elev = np.array([
            [10.0, 10.0, 10.0],
            [10.0, 0.0, 10.0],
            [10.0, 10.0, 10.0],
        ])
        valid = np.ones_like(elev, dtype=bool)

        volume_m3, surface_area_m2, water_level_m, pour_point, _visited = basin_volume(
            elev, valid, seed_row=1, seed_col=1,
            pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=20.0, max_basin_radius_m=1000.0,
        )

        # water rises to 10 (the rim), every rim cell is included at 0 depth, only the
        # center cell (100 m^2) holds water, 10m deep.
        self.assertEqual(water_level_m, 10.0)
        self.assertAlmostEqual(volume_m3, 10.0 * 100.0)  # 1000 m^3
        self.assertAlmostEqual(surface_area_m2, 9 * 100.0)  # all 9 cells "in the basin"
        # The whole grid got flooded with no cell left over — heap ran dry, not a real rim.
        self.assertIsNone(pour_point)

    def test_dam_height_cap_finds_the_rim(self):
        # Same pit, but the rim (10m up) now exceeds a 5m dam height cap — only the
        # center cell should be included, and the rim should be reported as the pour point.
        elev = np.array([
            [10.0, 10.0, 10.0],
            [10.0, 0.0, 10.0],
            [10.0, 10.0, 10.0],
        ])
        valid = np.ones_like(elev, dtype=bool)

        volume_m3, surface_area_m2, water_level_m, pour_point, _visited = basin_volume(
            elev, valid, seed_row=1, seed_col=1,
            pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=5.0, max_basin_radius_m=1000.0,
        )

        self.assertAlmostEqual(surface_area_m2, 100.0)  # only the center cell
        self.assertAlmostEqual(volume_m3, 0.0)  # water_level == seed_elev, no depth yet
        self.assertIsNotNone(pour_point)  # a genuine rim was found, just above the cap

    def test_downhill_seed_does_not_flood_the_whole_slope(self):
        # Regression test for the real bug found this session: seeding somewhere that
        # ISN'T the true bottom of a basin (here, a monotonic ramp — every row further
        # down is lower) must not let the flood run downhill forever. A reservoir behind
        # a dam at the seed can't extend below the seed's own elevation.
        #
        # 5m/row step (bigger than the 2m noise-tolerance in the floor check) so exactly
        # which rows qualify is unambiguous: only rows with elevation >= seed_elev - 2.
        rows, cols = 20, 5
        elev = np.zeros((rows, cols))
        for r in range(rows):
            elev[r, :] = 100.0 - 5.0 * r  # row 0 = 100m ... row 19 = 5m, strictly decreasing

        valid = np.ones_like(elev, dtype=bool)
        seed_row = 10  # elevation 50 here; rows 11-19 are all LOWER (downhill)

        volume_m3, surface_area_m2, water_level_m, pour_point, _visited = basin_volume(
            elev, valid, seed_row=seed_row, seed_col=2,
            pixel_dx_m=10.0, pixel_dy_m=10.0,
            max_dam_height_m=1000.0, max_basin_radius_m=100_000.0,  # deliberately generous
        )

        # Only rows 0..10 (elevation >= seed's 50) can possibly be included — that's
        # 11 rows * 5 cols = 55 cells, all within max_dam_height_m of the seed (100-50=50).
        # Without the fix, this kept eating progressively lower rows and could reach
        # nearly the whole 20x5 grid (100 cells).
        expected_cells = 11 * cols
        self.assertEqual(surface_area_m2 / 100.0, expected_cells)
        self.assertEqual(water_level_m, 100.0)  # row 0, the highest reachable row

    def test_max_basin_cells_is_a_hard_cap(self):
        # A huge, gently-rising plain with no true rim anywhere nearby — this is the
        # shape that caused the original "6 billion m^3" and "1.5 billion m^3" bugs.
        # MAX_BASIN_CELLS must stop it well before it eats the whole grid.
        size = 200
        elev = np.zeros((size, size))
        for r in range(size):
            elev[r, :] = r * 0.01  # rises 1cm per row — practically flat

        valid = np.ones_like(elev, dtype=bool)

        volume_m3, surface_area_m2, water_level_m, pour_point, _visited = basin_volume(
            elev, valid, seed_row=0, seed_col=size // 2,
            pixel_dx_m=30.0, pixel_dy_m=30.0,
            max_dam_height_m=1000.0, max_basin_radius_m=100_000.0,
        )

        cells_included = surface_area_m2 / (30.0 * 30.0)
        self.assertLessEqual(cells_included, MAX_BASIN_CELLS)
        # It hit the compute guard, not a real rim.
        self.assertIsNone(pour_point)


class TestStoragePower(unittest.TestCase):
    def test_storage_capacity_matches_hand_calc(self):
        # E = rho * g * V * H * eta / 3.6e9. 1000 kg/m3 * 9.81 * 1,000,000 m3 * 100m * 0.85
        expected_joules = 1000 * 9.81 * 1_000_000 * 100 * 0.85
        self.assertAlmostEqual(
            storage_capacity_mwh(head_m=100, volume_m3=1_000_000),
            expected_joules / 3_600_000_000,
        )

    def test_power_is_energy_over_design_hours(self):
        mwh = storage_capacity_mwh(head_m=200, volume_m3=5_000_000)
        self.assertAlmostEqual(estimated_power_mw(mwh), mwh / DESIGN_DISCHARGE_HOURS)

    def test_zero_volume_is_zero_everything(self):
        self.assertEqual(storage_capacity_mwh(head_m=500, volume_m3=0), 0.0)
        self.assertEqual(estimated_power_mw(0.0), 0.0)


class TestRealisticPower(unittest.TestCase):
    """The rho*g*Q*H*eta formula itself, and the flow-rate ceiling, checked against three
    real Romanian hydro plants — head, flow, and rated MW are all independently published
    for each (not derived by us). See MAX_FLOW_RATE_M3_S's docstring for sources."""

    def test_formula_matches_vidraru(self):
        # 324m head, 90 m3/s installed flow, 220MW real rated capacity.
        predicted = power_from_flow_mw(flow_m3_s=90, head_m=324)
        self.assertAlmostEqual(predicted, 220, delta=30)  # within ~15% — real turbines
                                                             # aren't exactly 85% efficient

    def test_formula_matches_lotru_ciunget(self):
        # 809m head, 80 m3/s installed flow, 510MW real rated capacity.
        predicted = power_from_flow_mw(flow_m3_s=80, head_m=809)
        self.assertAlmostEqual(predicted, 510, delta=40)

    def test_design_discharge_hours_matches_tarnita_lapustesti_duration(self):
        # Regression test for a real reasoning error made and corrected this session:
        # DESIGN_DISCHARGE_HOURS was originally 8, on the (backwards) claim that a
        # shorter duration was "conservative". It's not — MW = MWh / duration, so a
        # shorter duration always means a LARGER MW for the same energy, never smaller.
        # Checked directly against the one real duration figure available: Tarnița–
        # Lăpuștești's own 10M m3 @ 563.5m head = 13047 MWh, at its real 1000MW rating
        # that's 13.0h — not 8h. Using 8h would have reported 1631MW for that same real
        # site, 1.63x its actual rating. This pins the corrected value down so it can't
        # silently drift back to something shorter (and higher) without a test failing.
        real_mwh = storage_capacity_mwh(head_m=563.5, volume_m3=10_000_000)
        real_implied_duration_h = real_mwh / 1000
        self.assertAlmostEqual(real_implied_duration_h, 13.0, delta=0.2)
        self.assertAlmostEqual(DESIGN_DISCHARGE_HOURS, real_implied_duration_h, delta=1)

    def test_max_flow_rate_matches_tarnita_lapustesti(self):
        # The planned 1000MW/563.5m Tarnița–Lăpuștești project implies ~213 m3/s — the
        # basis for MAX_FLOW_RATE_M3_S (250, rounded up for headroom).
        implied_real_flow = 1000 / power_from_flow_mw(flow_m3_s=1, head_m=563.5)
        self.assertAlmostEqual(implied_real_flow, 213, delta=5)
        self.assertGreater(MAX_FLOW_RATE_M3_S, implied_real_flow)  # headroom, not a tight fit

    def test_uncapped_for_a_reasonably_sized_candidate(self):
        # A candidate whose flow requirement (at DESIGN_DISCHARGE_HOURS) is comfortably
        # under the ceiling should score exactly like the naive duration-based estimate —
        # the cap shouldn't touch it.
        volume_m3, head_m = 5_000_000, 300  # implies ~107 m3/s at 13h, under the 250 ceiling
        mwh = storage_capacity_mwh(head_m, volume_m3)
        power_mw, flow, flow_limited = realistic_power_mw(mwh, head_m, volume_m3)
        self.assertFalse(flow_limited)
        self.assertAlmostEqual(power_mw, estimated_power_mw(mwh))

    def test_capped_for_a_large_volume_short_duration_candidate(self):
        # Regression test for the actual bug found this session: lake 170958 ("Iovanu" on
        # the Cerna) reported ~5738MW before this fix — needing 1970 m3/s, ~9x Tarnița–
        # Lăpuștești's own flow. Same shape of input, checked directly.
        volume_m3, head_m = 56_732_000, 349.4
        mwh = storage_capacity_mwh(head_m, volume_m3)
        naive_mw = estimated_power_mw(mwh)
        power_mw, flow, flow_limited = realistic_power_mw(mwh, head_m, volume_m3)

        self.assertAlmostEqual(flow, implied_flow_m3_s(volume_m3))
        self.assertGreater(flow, MAX_FLOW_RATE_M3_S)  # confirms this candidate WAS the problem
        self.assertTrue(flow_limited)
        self.assertLess(power_mw, naive_mw)  # capped value must be smaller than the naive one
        self.assertLess(power_mw, 1000)  # bounded well under even Tarnița–Lăpuștești's rating
        self.assertAlmostEqual(power_mw, power_from_flow_mw(MAX_FLOW_RATE_M3_S, head_m))


class TestUsableCyclingVolume(unittest.TestCase):
    """A pumped-storage cycle can't move more water than the smaller of the two
    reservoirs actually holds — see the user's own framing: 'if the existing dam has a
    small volume you will never have enough water to fill the second one.'"""

    def test_small_lake_caps_a_bigger_basin(self):
        self.assertEqual(
            usable_cycling_volume_m3(new_site_volume_m3=100_000_000, existing_lake_volume_m3=5_000_000),
            5_000_000,
        )

    def test_big_lake_does_not_cap_a_smaller_basin(self):
        self.assertEqual(
            usable_cycling_volume_m3(new_site_volume_m3=5_000_000, existing_lake_volume_m3=100_000_000),
            5_000_000,
        )

    def test_unknown_lake_volume_leaves_basin_volume_unchanged(self):
        # None = "HydroLAKES doesn't have an estimate for this lake", not "unlimited".
        # Returning the basin volume unmodified means callers should treat it as
        # unverified against this constraint, not as "no constraint applies".
        self.assertEqual(
            usable_cycling_volume_m3(new_site_volume_m3=50_000_000, existing_lake_volume_m3=None),
            50_000_000,
        )

    def test_zero_or_negative_lake_volume_treated_as_unknown(self):
        self.assertEqual(usable_cycling_volume_m3(50_000_000, 0), 50_000_000)
        self.assertEqual(usable_cycling_volume_m3(50_000_000, -1), 50_000_000)


class TestEmpiricalReservoirVolume(unittest.TestCase):
    def test_power_law_formula(self):
        # V = a * A^b — no fitting involved, just the formula itself.
        self.assertAlmostEqual(empirical_reservoir_volume_m3(surface_area_km2=4, a=10, b=2), 160)
        self.assertAlmostEqual(empirical_reservoir_volume_m3(surface_area_km2=1, a=10, b=2), 10)

    @unittest.skipUnless(
        HYDROLAKES_AVAILABLE, "requires the cached HydroLAKES shapefile — run fetch_data.py first"
    )
    def test_fit_recovers_a_known_power_law_from_synthetic_data(self):
        # Sanity-checks the fitting *procedure* (log-log least squares) against data with
        # a known, exact answer — independent of whatever HydroLAKES' real data says.
        import geopandas as gpd

        rng = np.random.default_rng(42)
        areas = rng.uniform(0.5, 200, size=500)
        true_a, true_b = 15.0, 1.1
        volumes = true_a * areas**true_b  # no noise — should recover (a, b) almost exactly

        gdf = gpd.GeoDataFrame(
            {"Lake_type": 2, "Lake_area": areas, "Vol_total": volumes / 1e6},
            geometry=gpd.points_from_xy(rng.uniform(-10, 10, 500), rng.uniform(-10, 10, 500)),
            crs="EPSG:4326",
        )
        tmp_path = Path(fetch_data.DATA_DIR) / "_test_synthetic_reservoirs.shp"
        gdf.to_file(tmp_path)
        try:
            a, b, r_squared, n = fit_reservoir_area_volume_model(tmp_path)
            self.assertEqual(n, 500)
            self.assertAlmostEqual(a, true_a, delta=0.5)
            self.assertAlmostEqual(b, true_b, delta=0.01)
            self.assertGreater(r_squared, 0.999)
        finally:
            for f in Path(fetch_data.DATA_DIR).glob("_test_synthetic_reservoirs.*"):
                f.unlink()

    @unittest.skipUnless(
        HYDROLAKES_AVAILABLE, "requires the cached HydroLAKES shapefile — run fetch_data.py first"
    )
    def test_fit_on_real_data_is_a_loose_but_sane_floor_for_tarnita(self):
        # Documents the real, checked limitation from DATA_SOURCES.md: even fit on
        # reservoirs specifically, this underestimates a deep mountain reservoir like
        # Tarnița — by design it's a floor, not a precise estimate. If this ever came
        # back accurate to within, say, 20%, that would be surprising enough to
        # re-examine (the model / data changed in some way worth understanding).
        a, b, r_squared, n = fit_reservoir_area_volume_model(HYDROLAKES_SHP)
        self.assertGreater(n, 1000)  # global dataset, not just Romania
        self.assertGreater(r_squared, 0.5)  # fit shouldn't be noise, but isn't precise either

        tarnita_area_km2 = 1.36
        tarnita_real_volume_m3 = 74_000_000
        predicted = empirical_reservoir_volume_m3(tarnita_area_km2, a, b)
        ratio = predicted / tarnita_real_volume_m3
        self.assertGreater(ratio, 0.1)  # not wildly off
        self.assertLess(ratio, 0.6)  # ...but a real, systematic underestimate


@unittest.skipUnless(DEM_AVAILABLE, "requires downloaded DEM tiles — run fetch_data.py first")
class TestBasinVolumeRealWorld(unittest.TestCase):
    """Lake Tarnița, Cluj County — chosen because it's Romania's one pumped-storage site
    with a real, published second-reservoir design we can check against: the actual
    Tarnița-Lăpuștești project (~1000MW, 563.5m head, Lăpuștești reservoir on a
    *plateau* at 1085m — see DATA_SOURCES.md).

    Coordinates below are Lake Tarnița's anchor point from data/lakes.geojson —
    geometry.representative_point(), not .centroid (fetch_data.py switched this
    session: centroid can land outside a non-convex polygon entirely, confirmed on
    101 of 1100 Romania lakes, one of which — id=1293, a curving Danube reservoir —
    centroided to a hillside 500m higher than the actual water; see
    TestAnchorPointFix below). Elevation there is 515.0m — close to the real published
    NNR level of 521.5m (ro.wikipedia.org/wiki/Lacul_Tarni%C8%9Ba), confirming this is
    the right lake.
    """

    LON = 23.277492752515492
    LAT = 46.72019978841189
    ELEV_M = 515.0
    # HydroLAKES' own Vol_total for this lake (data/lakes.geojson, id=169355) — matches
    # the independently published >70M m3 (ro.wikipedia.org/wiki/Lacul_Tarni%C8%9Ba)
    # closely enough to trust the fetch_data.py Vol_total -> volume_m3 plumbing.
    LAKE_VOLUME_M3 = 74_000_000

    def _load_window(self, mode):
        m_per_deg_lon, m_per_deg_lat = find_sites.meters_per_degree(self.LAT)
        d_lon = find_sites.SEARCH_RADIUS_M / m_per_deg_lon
        d_lat = find_sites.SEARCH_RADIUS_M / m_per_deg_lat
        window = (self.LON - d_lon, self.LAT - d_lat, self.LON + d_lon, self.LAT + d_lat)
        tile_paths = find_sites.tiles_for_window(*window)

        import rasterio
        from rasterio.merge import merge

        with rasterio.open(tile_paths[0]) as first:
            nodata = first.nodata
        mosaic, transform = merge([str(p) for p in tile_paths], bounds=window, nodata=nodata)
        elev = mosaic[0].astype(np.float64)
        valid = np.ones_like(elev, dtype=bool)
        if nodata is not None:
            valid &= elev != nodata
        pixel_dx_m = abs(transform.a) * m_per_deg_lon
        pixel_dy_m = abs(transform.e) * m_per_deg_lat
        return elev, valid, pixel_dx_m, pixel_dy_m

    def test_sampled_elevation_matches_published_value(self):
        # Validates fetch_data's DEM sampling against a real, independently published
        # number — the closest thing to "ground truth" available without a lake's true
        # bathymetry (see module docstring).
        sampled = fetch_data.sample_elevation(self.LON, self.LAT)
        self.assertIsNotNone(sampled)
        self.assertAlmostEqual(sampled, 521.5, delta=15)  # published NNR level

    def test_seeding_at_the_plateau_peak_finds_almost_no_water(self):
        # The real Lăpuștești reservoir sits on a plateau at ~1085m, ~2km from Tarnița —
        # right at our search radius, and reachable in this window (checked: max elevation
        # here is ~1076m). But it's an EMBANKED pond on relatively flat high ground, not a
        # natural depression — building it required diking, not just flooding a bowl.
        # basin_volume() can only find naturally-contained water, so seeding at the
        # highest point in the window (the closest analog to "the plateau") should find
        # almost nothing: a peak has nowhere lower to flood FROM, and our floor rule
        # (can't flood below the seed) prevents it from including anything downhill.
        # This is not a bug — it's a real, verified limitation: this tool finds valley/bowl
        # dam sites, not plateau-diking sites like the real Lăpuștești. See DATA_SOURCES.md.
        elev, valid, pixel_dx_m, pixel_dy_m = self._load_window(find_sites.ENGINEERED)
        peak_row, peak_col = np.unravel_index(np.argmax(np.where(valid, elev, -np.inf)), elev.shape)

        volume_m3, surface_area_m2, water_level_m, pour_point, _visited = basin_volume(
            elev, valid, peak_row, peak_col, pixel_dx_m, pixel_dy_m,
            max_dam_height_m=find_sites.ENGINEERED.max_dam_height_m,
            max_basin_radius_m=find_sites.ENGINEERED.max_basin_radius_m,
        )

        self.assertLess(volume_m3, 10_000)  # near-zero, not a real reservoir

    def test_tarnita_correctly_finds_no_engineered_candidate(self):
        # Checked directly this session (2026-09-02) after raising MIN_WALL_FRACTION to
        # 0.6: Tarnița's best achievable wall_fraction anywhere in its whole 2km search
        # window is 0.598 — just under the gate. Consistent with the real world (see
        # test_seeding_at_the_plateau_peak_finds_almost_no_water's docstring): the real
        # Lăpuștești project is plateau diking, not a valley dam, so ENGINEERED
        # correctly has nothing to offer here. A companion, positive-case regression
        # test for that same real fact, from the other direction.
        result = find_sites.best_new_site(
            self.LON, self.LAT, self.ELEV_M, self.LAKE_VOLUME_M3, find_sites.ENGINEERED
        )
        self.assertIsNone(result)

    def test_valley_seed_near_a_real_lake_gives_a_plausible_volume(self):
        # Same sanity/regression check the Tarnița-based version of this test used to do
        # (bounded above by what MAX_BASIN_CELLS/max_dam_height_m can produce, comfortably
        # below the billion-m^3 territory the pre-fix bug produced) — moved to a
        # different real lake once Tarnița itself started correctly returning None (see
        # test_tarnita_correctly_finds_no_engineered_candidate above). Lake 1360316: its
        # best achievable wall_fraction (0.683) clears MIN_WALL_FRACTION with real margin,
        # unlike Tarnița's 0.598 — chosen for that reason, not arbitrarily.
        lon, lat, elev_m, lake_volume_m3 = 22.459219129732748, 44.937792400784815, 231.0, 15_800_000.0
        result = find_sites.best_new_site(lon, lat, elev_m, lake_volume_m3, find_sites.ENGINEERED)
        self.assertIsNotNone(result)
        self.assertGreater(result["volume_m3"], find_sites.MIN_VOLUME_M3)
        self.assertLess(result["volume_m3"], 500_000_000)  # well below the pre-fix bug's scale
        self.assertGreater(result["head_m"], find_sites.MIN_HEAD_M)
        # usable volume can never exceed either reservoir, including the anchor lake's own.
        self.assertLessEqual(result["volume_m3"], lake_volume_m3)
        self.assertGreaterEqual(result["wall_fraction"], find_sites.MIN_WALL_FRACTION)

    def test_tiny_anchor_lake_caps_a_much_bigger_basin(self):
        # Same search (lake 1360316, see above), but claiming it only holds 300K m3 (it
        # really holds ~15.8M) — the usable volume must drop to that cap, while the
        # basin's own physical size (basin_volume_m3) stays whatever the terrain
        # actually supports. 300K stays comfortably below any plausible real basin here.
        lon, lat, elev_m = 22.459219129732748, 44.937792400784815, 231.0
        result = find_sites.best_new_site(lon, lat, elev_m, 300_000, find_sites.ENGINEERED)
        self.assertIsNotNone(result)
        self.assertEqual(result["volume_m3"], 300_000)
        self.assertGreater(result["basin_volume_m3"], 300_000)
        self.assertTrue(result["limited_by_existing_lake"])

    def test_fetched_lake_volume_matches_published_value(self):
        # Round-trips through the real pipeline: data/lakes.geojson as fetch_data.py
        # actually wrote it, not a hardcoded stand-in.
        lakes_path = find_sites.LAKES_OUT_PATH
        if not lakes_path.exists():
            self.skipTest("data/lakes.geojson not present — run fetch_data.py first")

        import geopandas as gpd
        lakes = gpd.read_file(lakes_path)
        match = lakes[lakes["id"] == 169355]
        self.assertEqual(len(match), 1)
        volume_m3 = match.iloc[0]["volume_m3"]
        self.assertAlmostEqual(volume_m3, self.LAKE_VOLUME_M3, delta=1)
        self.assertGreaterEqual(volume_m3, 70_000_000)  # the published lower bound


@unittest.skipUnless(
    fetch_data.LAKES_OUT_PATH.exists(), "requires data/lakes.geojson — run fetch_data.py first"
)
class TestAnchorPointFix(unittest.TestCase):
    """fetch_data.py used geometry.centroid for each lake's anchor point — a polygon's
    center of MASS, which for a non-convex shape isn't guaranteed to fall inside the
    polygon at all. Checked directly this session: 101 of Romania's 1100 lakes have a
    centroid outside their own polygon. The worst case found, id=1293 (a large, curving
    Danube-valley reservoir — real name likely Porțile de Fier I / Iron Gate I, bounds
    matching it closely): centroid landed on a hillside, sampling 566.2m elevation —
    500m higher than the water. Switched to geometry.representative_point(), which
    shapely guarantees falls inside the polygon.
    """

    LAKE_ID = 1293

    def test_anchor_point_is_inside_the_real_polygon(self):
        import geopandas as gpd
        import fetch_data as fd

        boundary = fd.fetch_country_boundary()
        shp_path = fd.LAKES_RAW_DIR / "HydroLAKES_polys_v10_shp" / "HydroLAKES_polys_v10.shp"
        if not shp_path.exists():
            self.skipTest("requires the cached HydroLAKES shapefile — run fetch_data.py first")
        raw = gpd.read_file(shp_path, mask=boundary, where=f"Hylak_id = {self.LAKE_ID}")
        self.assertEqual(len(raw), 1)
        polygon = raw.iloc[0].geometry

        self.assertFalse(polygon.contains(polygon.centroid), "test fixture assumption broke: "
                          "centroid is now inside the polygon, this lake no longer demonstrates the bug")
        self.assertTrue(polygon.contains(polygon.representative_point()))

    def test_fetched_elevation_is_plausible_for_a_danube_valley_reservoir(self):
        # Not a Danube-valley elevation check by coincidence — id=1293's polygon bounds
        # (21.7-22.5 E, 44.4-44.7 N) match the real Porțile de Fier I / Iron Gate I
        # reservoir on the Romania-Serbia border closely enough to be confident this is
        # it, and that stretch of the Danube sits at well under 100m elevation.
        import geopandas as gpd
        lakes = gpd.read_file(fetch_data.LAKES_OUT_PATH)
        match = lakes[lakes["id"] == self.LAKE_ID]
        self.assertEqual(len(match), 1)
        elevation = match.iloc[0]["elevation"]
        self.assertLess(elevation, 150)  # the old centroid bug sampled 566.2m here


if __name__ == "__main__":
    unittest.main()
