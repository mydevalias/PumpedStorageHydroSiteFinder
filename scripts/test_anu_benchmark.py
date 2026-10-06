"""Tests for anu_benchmark.py — the external benchmark against the ANU Global Pumped
Hydro Atlas (see its module docstring for what the atlas is and the attribution terms).

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_anu_benchmark -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anu_benchmark import (
    ANU_CLASSES, ANU_DIR, MATCH_RADIUS_M, match_sites_to_anu, parse_anu_pairs,
)

ANU_CACHED = all((ANU_DIR / f"bluefield_{c}.geojson").exists() for c in ANU_CLASSES)


def _desc(**fields):
    """ANU packs a pair's numbers into an HTML table inside the `description` field —
    build one the same way so the parser is tested against the real format."""
    # (the JSON escapes "/" as "\/" on the wire; after json.loads it's a plain "</td>")
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in fields.items())
    return f"<html><body><table>{rows}</table></body></html>"


def _feature(name, geom, ispipe=False, ispin=False, isdam=False, description=""):
    return {
        "type": "Feature", "geometry": geom,
        "properties": {"name": name, "ispipe": ispipe, "ispin": ispin, "isdam": isdam,
                       "description": description},
    }


class TestParseAnuPairs(unittest.TestCase):
    def _write(self, features, cls="5gwh_18h"):
        path = Path(self.tmp.name) / f"bluefield_{cls}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_a_pipe_to_its_new_reservoir_polygon_and_parses_the_numbers(self):
        square = {"type": "Polygon", "coordinates": [[[23.0, 46.0], [23.01, 46.0], [23.01, 46.01], [23.0, 46.01], [23.0, 46.0]]]}
        path = self._write([
            _feature("n46_e023_RES1", square),  # the new reservoir (not pipe/pin/dam)
            _feature("n46_e023_RES1 Dam", square, isdam=True),
            _feature("RES_99 & n46_e023_RES1", {"type": "Point", "coordinates": [23.0, 46.0]}, ispin=True),
            _feature("RES_99 & n46_e023_RES1",
                     {"type": "LineString", "coordinates": [[23.0, 46.0], [23.1, 46.1]]}, ispipe=True,
                     description=_desc(**{"Class": "C", "Head (m)": "315", "Separation (km)": "9.7",
                                          "Average Slope (%)": "3", "Volume (GL)": "80.5",
                                          "Energy (GWh)": "50", "Country": "Romania"})),
        ])
        pairs = parse_anu_pairs([path], country="Romania")
        self.assertEqual(len(pairs), 1)  # one PAIR, not four features
        r = pairs.iloc[0]
        self.assertEqual(r["new_reservoir_id"], "n46_e023_RES1")
        self.assertEqual(r["anu_class"], "C")
        self.assertEqual(r["head_m"], 315.0)
        self.assertEqual(r["separation_km"], 9.7)
        self.assertEqual(r["volume_gl"], 80.5)
        self.assertEqual(r["energy_class"], "5gwh_18h")
        self.assertIsNotNone(r["reservoir_polygon"])
        self.assertTrue(r["reservoir_polygon"].contains(Point(23.005, 46.005)))

    def test_filters_by_anu_country_field_not_by_bbox(self):
        line = {"type": "LineString", "coordinates": [[23.0, 46.0], [23.1, 46.1]]}
        path = self._write([
            _feature("RES_1 & n46_e023_RESa", line, ispipe=True, description=_desc(**{"Head (m)": "200", "Country": "Serbia"})),
            _feature("RES_2 & n46_e023_RESb", line, ispipe=True, description=_desc(**{"Head (m)": "200", "Country": "Romania"})),
        ])
        pairs = parse_anu_pairs([path], country="Romania")
        self.assertEqual(list(pairs["new_reservoir_id"]), ["n46_e023_RESb"])


class TestMatchSitesToAnu(unittest.TestCase):
    def _anu(self):
        poly = Polygon([(23.0, 46.0), (23.01, 46.0), (23.01, 46.01), (23.0, 46.01)])  # ~770m x 1.1km
        return gpd.GeoDataFrame(
            [{"new_reservoir_id": "x", "reservoir_polygon": poly, "geometry": poly.exterior}],
            geometry="geometry", crs="EPSG:4326",
        )

    def test_inside_and_just_outside_the_polygon_match(self):
        anu = self._anu()
        inside = Point(23.005, 46.005)
        near = Point(23.01 + 500 / 77_000, 46.005)  # ~500m east of the polygon edge
        self.assertEqual(match_sites_to_anu([inside, near], anu), [0, 0])

    def test_beyond_the_match_radius_does_not(self):
        anu = self._anu()
        far = Point(23.01 + (MATCH_RADIUS_M + 300) / 77_000, 46.005)  # ~1.3km east
        self.assertEqual(match_sites_to_anu([far], anu), [None])

    def test_no_polygons_at_all_is_all_none_not_a_crash(self):
        anu = gpd.GeoDataFrame([{"new_reservoir_id": "x", "reservoir_polygon": None}])
        self.assertEqual(match_sites_to_anu([Point(0, 0)], anu), [None])


@unittest.skipUnless(ANU_CACHED, "requires the cached ANU Bluefield download under data/anu/")
class TestRealAnuRomaniaData(unittest.TestCase):
    """Invariants over the real cached atlas data, not pinned counts (a re-download
    after ANU updates the atlas must not break these)."""

    @classmethod
    def setUpClass(cls):
        cls.pairs = parse_anu_pairs([ANU_DIR / f"bluefield_{c}.geojson" for c in ANU_CLASSES])

    def test_a_substantial_number_of_romanian_pairs_parse(self):
        self.assertGreater(len(self.pairs), 500)

    def test_every_pair_meets_anus_own_published_minimum_head(self):
        # "minimum head = 100m" per re100.eng.anu.edu.au/global — if the parser ever
        # misread the head column this is the first thing that would fail.
        self.assertTrue((self.pairs["head_m"] >= 100).all())

    def test_nearly_every_pair_links_to_a_new_reservoir_polygon(self):
        # All but ANU's own two-EXISTING-reservoir pairs ("RES_a & RES_b", 2 of 1560 for
        # Romania at the time of writing) have a new-reservoir polygon to match against.
        linked = self.pairs["reservoir_polygon"].notna().mean()
        self.assertGreater(linked, 0.99)


if __name__ == "__main__":
    unittest.main()
