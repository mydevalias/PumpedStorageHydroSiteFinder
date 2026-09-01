"""Real, published pumped-storage projects in Romania — for the map to show as a visual
benchmark next to our own algorithm's candidates. Every number here is from a cited
source, not computed by our search — the opposite of candidates_<mode>.geojson, whose
whole schema this deliberately mirrors so the map can render both with the same code
(rating/volume/head side by side with what our own candidates report).

See DATA_SOURCES.md for how each figure was sourced and verified.
"""

import math
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

from volumes import DESIGN_DISCHARGE_HOURS, storage_capacity_mwh

REFERENCE_PROJECTS = [
    {
        "name": "Tarnița–Lăpuștești",
        "status": "planned, unbuilt as of 2026",
        # Lake Tarnița's centroid (matches data/lakes.geojson id=169355; elevation there
        # samples 515.0m from our DEM vs. this real published 521.5m NNR level, confirming
        # it's the right lake).
        "lake_lon": 23.278707869648212,
        "lake_lat": 46.721549912777185,
        "lake_elevation_m": 521.5,
        # The Lăpuștești plateau's exact intake coordinates aren't published anywhere we
        # found. This is the highest point in our own DEM search window near Tarnița
        # (1075.7m) — close to the real 1085m and geometrically plausible (within the
        # search radius, in the right direction) but NOT an independently confirmed site
        # location. Treat this marker's position as approximate; head/volume/MW are real.
        "site_lon": 23.280417307625946,
        "site_lat": 46.70382169183256,
        "new_site_elevation_m": 1085.0,
        "head_m": 563.5,
        "volume_million_m3": 10.0,  # real design cycling volume, upper reservoir
        "lake_volume_million_m3": 15.0,  # real design cycling volume, lower reservoir
        "rated_mw": 1000,  # real published rating — not computed by our formula
        "source": "en.wikipedia.org & ro.wikipedia.org “Tarnița–Lăpuștești”, "
                  "checked 2026-09-01",
    },
]


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_deg))
    return m_per_deg_lon, m_per_deg_lat


def build() -> gpd.GeoDataFrame:
    properties = []
    geometries = []
    for project in REFERENCE_PROJECTS:
        m_per_deg_lon, m_per_deg_lat = meters_per_degree(project["lake_lat"])
        dx_m = (project["site_lon"] - project["lake_lon"]) * m_per_deg_lon
        dy_m = (project["site_lat"] - project["lake_lat"]) * m_per_deg_lat
        distance_m = math.hypot(dx_m, dy_m)

        # Computed the same way as our own candidates, purely for side-by-side context —
        # not itself a published figure (the real design's actual duration/discharge
        # curve isn't public; this just answers "what would our own formula say").
        storage_mwh = storage_capacity_mwh(project["head_m"], project["volume_million_m3"] * 1_000_000)

        properties.append({
            "type": "reference-real",
            "name": project["name"],
            "status": project["status"],
            "lake_elevation_m": project["lake_elevation_m"],
            "new_site_elevation_m": project["new_site_elevation_m"],
            "head_m": project["head_m"],
            "distance_m": round(distance_m, 1),
            "volume_million_m3": project["volume_million_m3"],
            "lake_volume_million_m3": project["lake_volume_million_m3"],
            "rated_mw": project["rated_mw"],
            "storage_mwh_at_rated_mw": round(storage_mwh, 1),
            "implied_duration_h": round(storage_mwh / project["rated_mw"], 1),
            "source": project["source"],
        })
        geometries.append(LineString([
            (project["lake_lon"], project["lake_lat"]),
            (project["site_lon"], project["site_lat"]),
        ]))

    return gpd.GeoDataFrame(properties, geometry=geometries, crs="EPSG:4326")


def main() -> None:
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "reference_projects.geojson"
    build().to_file(out_path, driver="GeoJSON")
    print(f"wrote {out_path} ({len(REFERENCE_PROJECTS)} reference project(s))")


if __name__ == "__main__":
    main()
