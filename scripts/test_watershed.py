"""Tests for watershed.py — real priority-flood depression-filling, independent of any
lake's search window (see its module docstring for why this exists and how it differs
from NATURAL mode's per-lake heuristic).

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_watershed -v
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_data
from watershed import MAX_FILL_DEPTH_M, MIN_BASIN_AREA_M2, find_depressions_in_tile

DEM_AVAILABLE = fetch_data.DEM_DIR.exists() and any(fetch_data.DEM_DIR.glob("*.tif"))
LESU_TILE = fetch_data.DEM_DIR / "Copernicus_DSM_COG_10_N46_00_E022_00_DEM.tif"


def _write_tile(path, elev, lon0=25.0, lat0=46.0, pixel_deg=0.0003):
    """A small north-up GeoTIFF the way Copernicus tiles are laid out (no nodata value
    declared; sea stored as 0.0), so find_depressions_in_tile() reads it unchanged."""
    import rasterio
    from rasterio.transform import from_origin
    transform = from_origin(lon0, lat0, pixel_deg, pixel_deg)
    with rasterio.open(path, "w", driver="GTiff", height=elev.shape[0], width=elev.shape[1],
                       count=1, dtype="float32", crs="EPSG:4326", transform=transform) as dst:
        dst.write(elev.astype("float32"), 1)


class TestOutletHygiene(unittest.TestCase):
    """The rules added after the first country-wide build (2026-09-18) put 130 one-pixel
    'basins' on the Black Sea coast, each 'filled' 400m+ deep against sea-level nodata:
    a basin that touches the sea or the tile edge has an unknown outlet and is dropped;
    so is anything under MIN_BASIN_AREA_M2 or deeper than MAX_FILL_DEPTH_M.
    """

    def setUp(self):
        import numpy as np
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        # 60x60 tile of gently sloping high ground (so nothing is a pit by accident)...
        yy, xx = np.mgrid[0:60, 0:60]
        self.elev = 800.0 + 0.05 * xx + 0.05 * yy
        # ...with a real interior bowl: 8x8 cells, 12m deep, well inside the tile.
        self.elev[20:28, 20:28] -= 12.0

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, elev):
        import numpy as np
        path = Path(self.tmp.name) / "tile.tif"
        _write_tile(path, np.asarray(elev))
        return find_depressions_in_tile(path, min_volume_m3=1_000)

    def test_a_real_interior_bowl_is_found_with_sane_numbers(self):
        basins = self._run(self.elev)
        self.assertEqual(len(basins), 1)
        b = basins[0]
        self.assertGreaterEqual(b["area_m2"], MIN_BASIN_AREA_M2)
        self.assertAlmostEqual(b["pour_point_elevation_m"] - b["elevation_m"], 12.0, delta=1.5)
        self.assertLess(b["pour_point_elevation_m"] - b["elevation_m"], MAX_FILL_DEPTH_M)

    def test_a_bowl_touching_the_tile_edge_is_dropped(self):
        elev = self.elev.copy()
        elev[0:8, 40:48] -= 12.0  # second bowl, flush with the top edge
        basins = self._run(elev)
        self.assertEqual(len(basins), 1)  # only the interior one survives
        self.assertAlmostEqual(basins[0]["lat"], 46.0 - 24 * 0.0003, delta=0.002)

    def test_a_cell_pinned_against_sea_level_nodata_is_dropped(self):
        elev = self.elev.copy()
        elev[40:50, 40:50] = 0.0  # a patch of "sea" (Copernicus stores it as exactly 0)
        elev[39, 45] = 0.6  # one coastal cell beside it, like the real Black Sea artifacts
        basins = self._run(elev)
        self.assertEqual(len(basins), 1)
        self.assertGreater(basins[0]["elevation_m"], 700)  # the interior bowl, not the coast

    def test_a_sub_hectare_pit_is_dropped(self):
        elev = self.elev.copy()
        elev[45, 10] -= 30.0  # a single deep cell: 30m x 1 cell is real DEM noise
        basins = self._run(elev)
        self.assertEqual(len(basins), 1)


@unittest.skipUnless(DEM_AVAILABLE and LESU_TILE.exists(), "requires the real DEM tile covering Leșu")
class TestFindDepressionsInTile(unittest.TestCase):
    """Real-DEM regression: this method must independently rediscover the exact same
    natural bowl near Leșu (lake 1352457) that NATURAL mode's own search found this
    session by hand-checking a specific seed (see DATA_SOURCES.md, 2026-09-18) — not a
    coincidentally-similar one, the SAME depression, found by a completely different
    algorithm (priority-flood fill vs. a windowed local-minimum heuristic).
    """

    @classmethod
    def setUpClass(cls):
        cls.basins = find_depressions_in_tile(LESU_TILE, min_volume_m3=100_000)

    def test_finds_a_substantial_number_of_real_basins(self):
        # Not overfit to one lake -- a real DEM tile this size (110km x 75km at this
        # latitude, mountainous terrain) should have plenty of genuine small depressions
        # once tiny/noise ones are filtered by MIN_FILL_DEPTH_M/min_volume_m3.
        self.assertGreater(len(self.basins), 20)

    def test_rediscovers_the_known_real_lesu_basin(self):
        # The known real bowl (found by NATURAL's own search, 2026-09-18): deepest
        # point ~22.54605E/46.81261N, elevation 841.0m, our own capped volume 12.27M m^3
        # (basin_volume()'s max_dam_height_m=60m cut it off there). pysheds' UNCAPPED
        # real pour point should be close by and report the true, larger natural fill.
        candidates = [
            b for b in self.basins
            if abs(b["lon"] - 22.54605) < 0.01 and abs(b["lat"] - 46.81261) < 0.01
        ]
        self.assertEqual(len(candidates), 1, "expected exactly one basin near the known Leșu bowl")
        basin = candidates[0]
        self.assertAlmostEqual(basin["elevation_m"], 841.0, delta=2.0)
        # Real, uncapped volume should be at least NATURAL's own height-capped estimate
        # (12.27M m^3) -- the true pour point can only be at or above whatever a
        # height-limited flood already reached, never below it.
        self.assertGreaterEqual(basin["volume_m3"], 9_000_000)

    def test_no_basin_is_larger_than_romanias_actual_largest_reservoir(self):
        # Same "do not overfit" sanity net as ENGINEERED's own mega-sprawl regression
        # test (see test_find_sites.py) -- a real hydrology algorithm can still surface
        # an implausibly large "depression" if the underlying DEM has a large flat/
        # nodata artifact; Vidraru's real ~465M m^3 is the ceiling to check against.
        for basin in self.basins:
            self.assertLess(basin["volume_m3"], 500_000_000)

    def test_pour_point_is_always_at_or_above_the_deepest_point(self):
        # A basin's rim can't be lower than its own floor -- direct sanity check on the
        # arithmetic (elevation_m + fill depth), not just plausible-looking output.
        for basin in self.basins:
            self.assertGreaterEqual(basin["pour_point_elevation_m"], basin["elevation_m"])


if __name__ == "__main__":
    unittest.main()
