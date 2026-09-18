"""Tests for reference_projects.py — specifically, that a hand-entered "real project"
marker's site coordinates are actually consistent with what OUR OWN search finds
nearby, not just a plausible-looking guess sitting somewhere in the right country.

Run from the scripts/ directory:
    cd scripts && ../.venv/bin/python -m unittest test_reference_projects -v

Concrete bug this class caught (see DATA_SOURCES.md, 2026-09-18): the user reported
"still not finding the proposed tarnita project" despite our PLATEAU search finding a
real, well-matching candidate for lake 169355 (Tarnița) days earlier. The two were
never actually the same point on the map — reference_projects.py's Tarnița entry used
an admittedly-approximate stand-in coordinate ("highest point in our own DEM search
window", picked before PLATEAU_SEARCH_RADIUS_M existed) that turned out to be a rounded
hilltop ~3.9km from the real, flat, well-matching plateau our OWN later search
independently verified against the published head/volume/MW. The "real project"
benchmark marker and our own best candidate were pointing at two different hills on
the map, so a numeric match in a CLI report never showed up as a visual one.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_data
from find_sites import best_plateau_site, load_lake_polygons, meters_per_degree
from reference_projects import REFERENCE_PROJECTS

DEM_AVAILABLE = fetch_data.DEM_DIR.exists() and any(fetch_data.DEM_DIR.glob("*.tif"))
HYDROLAKES_SHP = (
    fetch_data.LAKES_RAW_DIR / "HydroLAKES_polys_v10_shp" / "HydroLAKES_polys_v10.shp"
)
HYDROLAKES_AVAILABLE = HYDROLAKES_SHP.exists()

# Real, published (via reference_projects.py) DEM-sampled elevation/volume for lake
# 169355 — see reference_projects.py's own comment for why these two particular numbers
# (not HydroLAKES' own Vol_total) are used here.
TARNITA_LAKE = next(p for p in REFERENCE_PROJECTS if p["name"] == "Tarnița–Lăpuștești")


@unittest.skipUnless(
    DEM_AVAILABLE and HYDROLAKES_AVAILABLE,
    "requires downloaded DEM tiles and the cached HydroLAKES shapefile",
)
class TestReferenceProjectSitesMatchOurOwnSearch(unittest.TestCase):
    """A reference project's site_lon/site_lat is our own best GUESS at where a real,
    published project's upper reservoir actually sits (never an independently confirmed
    survey location — see reference_projects.py's own comment). That guess is only
    worth showing on the map if it's actually close to what our own search, running the
    same real DEM, independently finds nearby — otherwise the "real project" benchmark
    marker and our own algorithm's candidate point at two different hills, and a reader
    has no way to tell the map is even claiming a match.
    """

    def test_tarnita_reference_site_is_near_our_own_best_plateau_candidate(self):
        polygons = load_lake_polygons(fetch_data.fetch_hydrolakes_raw())
        polygon = polygons.get(169355)

        result = best_plateau_site(
            TARNITA_LAKE["lake_lon"], TARNITA_LAKE["lake_lat"],
            TARNITA_LAKE["lake_elevation_m"], TARNITA_LAKE["lake_volume_million_m3"] * 1_000_000,
            polygon,
        )
        self.assertIsNotNone(result, "expected our own search to find a real plateau near Tarnița")

        m_per_deg_lon, m_per_deg_lat = meters_per_degree(TARNITA_LAKE["lake_lat"])
        dx_m = (TARNITA_LAKE["site_lon"] - result["site_lon"]) * m_per_deg_lon
        dy_m = (TARNITA_LAKE["site_lat"] - result["site_lat"]) * m_per_deg_lat
        gap_m = math.hypot(dx_m, dy_m)

        # 800m, not a tight pixel-exact match: plateau_footprint()'s exact growth extent
        # has some real run-to-run wobble (see DATA_SOURCES.md) since it's a BFS over a
        # slope threshold, so the WINNING seed can shift a little within the same real,
        # contiguous flat area. 800m is comfortably tighter than the ~3.9km gap the
        # original stand-in coordinate had, so this still fails loudly if the reference
        # marker drifts back to pointing at an unrelated hill.
        self.assertLess(gap_m, 800, f"reference site is {gap_m:.0f}m from our own best candidate")
