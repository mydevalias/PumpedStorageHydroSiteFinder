"""Part 1 (data layer): download DEM tiles, country boundary, and lake polygons,
then produce data/lakes.geojson (id, anchor point, elevation, area, volume).

To reuse for a different country, edit the CONFIG block below (COUNTRY_NAME,
COUNTRY_ISO_A3, BBOX) and re-run. See ../DATA_SOURCES.md for details on each
source and what "reuse for another country" involves.
"""

import math
import zipfile
from pathlib import Path

import geopandas as gpd
import rasterio
import requests

# ---- CONFIG (edit these to reuse for another country) ----------------------

COUNTRY_NAME = "Romania"
COUNTRY_ISO_A3 = "ROU"  # matches the ISO_A3 field in the Natural Earth boundary dataset

# (min_lon, min_lat, max_lon, max_lat) — only used to pick which 1x1 degree DEM
# tiles to download. Padded a bit beyond the real border; extra tiles are fine.
BBOX = (20.0, 43.5, 30.0, 48.3)

# ---- Sources (see DATA_SOURCES.md for how these were found/verified) -------

DEM_BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
NATURAL_EARTH_COUNTRIES_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip"
)
HYDROLAKES_URL = "https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip"

# ---- Paths -------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEM_DIR = DATA_DIR / "dem"
BOUNDARY_DIR = DATA_DIR / "boundary"
LAKES_RAW_DIR = DATA_DIR / "lakes_raw"
LAKES_OUT_PATH = DATA_DIR / "lakes.geojson"


def download_file(url: str, dest_path: Path) -> None:
    """Stream url to dest_path, skipping if dest_path already exists (cache).
    Downloads to a .part file first so an interrupted download can't be
    mistaken for a complete one.
    """
    if dest_path.exists():
        print(f"  cached: {dest_path.name}")
        return

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")

    response = requests.get(url, stream=True, timeout=60)
    if response.status_code == 404:
        raise FileNotFoundError(f"404 Not Found: {url}")
    response.raise_for_status()

    with open(part_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)

    part_path.rename(dest_path)
    print(f"  downloaded: {dest_path.name}")


def dem_tile_name(south_lat: int, west_lon: int) -> str:
    ns = "N" if south_lat >= 0 else "S"
    ew = "E" if west_lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(south_lat):02d}_00_{ew}{abs(west_lon):03d}_00_DEM"


def dem_tile_path(south_lat: int, west_lon: int) -> Path:
    name = dem_tile_name(south_lat, west_lon)
    return DEM_DIR / f"{name}.tif"


def fetch_dem_tiles(bbox: tuple[float, float, float, float]) -> list[Path]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lats = range(math.floor(min_lat), math.floor(max_lat) + 1)
    lons = range(math.floor(min_lon), math.floor(max_lon) + 1)

    print(f"Fetching DEM tiles for bbox {bbox} ({len(list(lats)) * len(list(lons))} tiles)...")
    tile_paths = []
    for south_lat in lats:
        for west_lon in lons:
            name = dem_tile_name(south_lat, west_lon)
            url = f"{DEM_BASE_URL}/{name}/{name}.tif"
            dest = dem_tile_path(south_lat, west_lon)
            try:
                download_file(url, dest)
                tile_paths.append(dest)
            except FileNotFoundError:
                # Some 1x1 tiles genuinely don't exist (e.g. entirely open sea).
                print(f"  no tile at {name} (likely open water), skipping")
    return tile_paths


def fetch_country_boundary() -> gpd.GeoSeries:
    zip_path = BOUNDARY_DIR / "ne_10m_admin_0_countries.zip"
    print("Fetching Natural Earth country boundaries...")
    download_file(NATURAL_EARTH_COUNTRIES_URL, zip_path)

    shp_path = BOUNDARY_DIR / "ne_10m_admin_0_countries.shp"
    if not shp_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(BOUNDARY_DIR)

    countries = gpd.read_file(shp_path)
    match = countries[countries["ISO_A3"] == COUNTRY_ISO_A3]
    if match.empty:
        raise ValueError(
            f"No boundary found for ISO_A3={COUNTRY_ISO_A3!r} in Natural Earth admin_0 countries"
        )
    return match.geometry


def fetch_hydrolakes_raw() -> Path:
    zip_path = LAKES_RAW_DIR / "HydroLAKES_polys_v10_shp.zip"
    print("Fetching HydroLAKES polygons (820MB, first run only)...")
    download_file(HYDROLAKES_URL, zip_path)

    shp_path = LAKES_RAW_DIR / "HydroLAKES_polys_v10_shp" / "HydroLAKES_polys_v10.shp"
    if not shp_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(LAKES_RAW_DIR)
    return shp_path


def sample_elevation(lon: float, lat: float) -> float | None:
    south_lat = math.floor(lat)
    west_lon = math.floor(lon)
    tile_path = dem_tile_path(south_lat, west_lon)
    if not tile_path.exists():
        return None

    with rasterio.open(tile_path) as dataset:
        row, col = dataset.index(lon, lat)
        value = dataset.read(1)[row, col]
        if value == dataset.nodata:
            return None
        return float(value)


def build_lakes_geojson(boundary: gpd.GeoSeries) -> None:
    shp_path = fetch_hydrolakes_raw()

    print(f"Clipping HydroLAKES to {COUNTRY_NAME}...")
    lakes = gpd.read_file(shp_path, mask=boundary)
    print(f"  {len(lakes)} lakes found")

    # NOT geometry.centroid: that's the polygon's center of mass, which for a
    # non-convex shape (a long curving reservoir, an irregular natural lake) can land
    # outside the polygon entirely — checked directly this session: 101 of 1100 lakes
    # here do exactly that (e.g. id=1293, a large Danube-valley reservoir, centroids to
    # a point ~500m higher in elevation than the actual lake, on a hillside nowhere near
    # the water). representative_point() is guaranteed to fall inside the polygon.
    anchor_points = lakes.geometry.representative_point()
    # Vol_total is HydroLAKES' own volume estimate (Messager et al. 2016, a geostatistical
    # model — not derived from our DEM), in million m^3; 0 means "unknown", not "empty lake".
    volume_m3 = (lakes["Vol_total"] * 1_000_000).where(lakes["Vol_total"] > 0)
    out = gpd.GeoDataFrame(
        {
            "id": lakes["Hylak_id"],
            "area_km2": lakes["Lake_area"],
            "elevation": [sample_elevation(pt.x, pt.y) for pt in anchor_points],
            "volume_m3": volume_m3,
        },
        geometry=anchor_points,
        crs=lakes.crs,
    )

    missing_elevation = out["elevation"].isna().sum()
    if missing_elevation:
        print(f"  warning: {missing_elevation} lakes have no elevation (missing DEM tile)")

    missing_volume = out["volume_m3"].isna().sum()
    if missing_volume:
        print(f"  note: {missing_volume}/{len(out)} lakes have no HydroLAKES volume estimate")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_file(LAKES_OUT_PATH, driver="GeoJSON")
    print(f"  wrote {LAKES_OUT_PATH}")


def main() -> None:
    fetch_dem_tiles(BBOX)
    boundary = fetch_country_boundary()
    build_lakes_geojson(boundary)


if __name__ == "__main__":
    main()
