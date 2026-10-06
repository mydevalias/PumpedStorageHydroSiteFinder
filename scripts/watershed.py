"""Real, country-wide watershed depression-filling — a genuinely different (and more
rigorous) way of finding natural bowl-shaped terrain than NATURAL mode's per-lake,
windowed local-minimum heuristic (see find_sites.py's NATURAL SearchMode).

NATURAL mode only ever looks in a window around each of Romania's ~1,100 HydroLAKES
lakes, and flags a SEED as a candidate if it's locally lowest over a ~500m
neighborhood — a proxy for "this might be a bowl," confirmed afterward by an actual
flood-fill (basin_volume()). That's inherently incomplete: a real depression that
isn't within the search window of any existing lake is invisible to it no matter how
real or large it is.

This module instead runs a real priority-flood depression-fill (via the `pysheds`
library — an actual hydrology tool, the same class of algorithm GIS/hydrology software
uses for watershed delineation) ONCE over each DEM tile, independent of where any lake
is. Filling every pit to its real pour-point elevation and taking (filled - original)
gives the exact volume of every closed depression in the terrain directly — no lake
anchor, no search window, no locally-lowest heuristic. Validated directly against a
depression already found and confirmed real this session (see DATA_SOURCES.md,
2026-09-18): the real bowl near Leșu (lake 1352457) that NATURAL mode's own widened
seed_radius_m search found by hand-checking basin_volume() at a specific seed.
pysheds independently finds the SAME depression (same deepest point to within one DEM
cell) with a volume of 9.32M m^3 -- the real, uncapped pour-point volume, vs. NATURAL's
own 12.27M m^3 (capped by NATURAL's own max_dam_height_m=60m budget, since basin_volume()
doesn't know the real pour point until it hits it or runs out of height/radius budget).

Known limitation, documented rather than silently ignored: this processes one DEM tile
(1x1 degree) at a time, so a real depression that straddles a tile boundary gets split
into two smaller, separately-reported pieces. Romania's tiles are large enough (roughly
110km x 75km at this latitude) that this should be rare for anything the size of a
realistic reservoir, but it is a real, acknowledged gap, not a fixed one.
"""

import math
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation, label

MIN_FILL_DEPTH_M = 0.5  # ignore sub-pixel-noise-level fills (DEM vertical noise floor,
                          # not a real depression) when grouping cells into basins
SEA_LEVEL_NODATA_M = 0.0  # Copernicus GLO-30 has no nodata value; open water at sea
                            # level is stored as exactly 0.0. pysheds also defaults
                            # nodata to 0, so those cells become impassable "walls" to
                            # the fill — which is how the first catalog build (2026-09-18)
                            # produced 130 one-pixel "basins" on the Black Sea coast,
                            # each "filled" 400m+ deep against the sea. A basin that
                            # touches the sea (or the tile edge — same problem, an
                            # unknown outlet) is not a closed depression; see
                            # find_depressions_in_tile().
MIN_BASIN_AREA_M2 = 10_000  # 1 ha (~15 cells): below this it's DEM noise, not a
                              # reservoir footprint — 150 of the first build's 44,766
                              # basins, 124 of them a single cell.
MAX_FILL_DEPTH_M = 200.0  # sanity net, not a tuning knob: real closed depressions on
                            # the first build have p99 depth 34.5m; anything deeper is a
                            # data artifact (all 130 of the >150m ones were the coastal
                            # single cells above). Kept generous on purpose.


def find_depressions_in_tile(dem_path: Path, min_volume_m3: float = 100_000) -> list[dict]:
    """Runs a real depression-fill over one DEM tile and returns every distinct closed
    basin at least min_volume_m3 in size, as a dict: lon/lat/elevation of the deepest
    point (where a new reservoir's floor would be), pour_point_elevation_m (the real,
    uncapped natural water level once full — the DEM elevation the basin overflows at),
    volume_m3, area_m2. Basins are found independent of any lake; pairing with a real
    existing lake happens separately (see find_watershed_candidates() in find_sites.py).
    """
    # Deferred import: pysheds pulls in numba/scikit-image, a real dependency weight
    # only this module needs -- everything else in the project works without it.
    from pysheds.grid import Grid

    grid = Grid.from_raster(str(dem_path), nodata=SEA_LEVEL_NODATA_M)
    dem = grid.read_raster(str(dem_path), nodata=SEA_LEVEL_NODATA_M)
    pit_filled = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit_filled)

    dem_arr = np.array(dem)
    fill_depth = np.array(flooded) - dem_arr

    transform = grid.affine
    lat_center = transform.f + (dem_arr.shape[0] / 2) * transform.e
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_center))
    pixel_dx_m = abs(transform.a) * m_per_deg_lon
    pixel_dy_m = abs(transform.e) * m_per_deg_lat
    cell_area_m2 = pixel_dx_m * pixel_dy_m

    mask = fill_depth > MIN_FILL_DEPTH_M
    labels, n = label(mask)
    if n == 0:
        return []

    volumes = np.zeros(n + 1)
    np.add.at(volumes, labels.ravel(), fill_depth.ravel() * cell_area_m2)
    areas = np.bincount(labels.ravel(), minlength=n + 1).astype(float) * cell_area_m2

    # A basin whose flooded cells sit next to the sea or the tile edge was bounded by
    # an unknown outlet, not by real terrain — drop it entirely rather than report a
    # made-up pour point (see SEA_LEVEL_NODATA_M).
    unknown_outlet = (dem_arr == SEA_LEVEL_NODATA_M)
    unknown_outlet[0, :] = unknown_outlet[-1, :] = unknown_outlet[:, 0] = unknown_outlet[:, -1] = True
    touches_unknown = binary_dilation(unknown_outlet, structure=np.ones((3, 3), bool)) & mask
    unbounded = set(np.unique(labels[touches_unknown])) - {0}

    basins = []
    for lbl in np.where(volumes >= min_volume_m3)[0]:
        if lbl == 0 or lbl in unbounded or areas[lbl] < MIN_BASIN_AREA_M2:
            continue
        rows, cols = np.where(labels == lbl)
        depths_here = fill_depth[rows, cols]
        if depths_here.max() > MAX_FILL_DEPTH_M:
            continue
        deepest_idx = depths_here.argmax()
        deepest_row, deepest_col = int(rows[deepest_idx]), int(cols[deepest_idx])
        deepest_elev = float(dem_arr[deepest_row, deepest_col])
        max_fill_depth_m = float(depths_here.max())

        basins.append({
            "lon": transform.c + (deepest_col + 0.5) * transform.a,
            "lat": transform.f + (deepest_row + 0.5) * transform.e,
            "elevation_m": deepest_elev,
            "pour_point_elevation_m": deepest_elev + max_fill_depth_m,
            "volume_m3": float(volumes[lbl]),
            "area_m2": float(areas[lbl]),
        })

    return basins


def find_all_depressions(tile_paths: list[Path], min_volume_m3: float = 100_000) -> list[dict]:
    """find_depressions_in_tile() across every given tile. Each tile is independent
    (see module docstring for the tile-boundary limitation this implies)."""
    basins = []
    for i, tile_path in enumerate(tile_paths, start=1):
        tile_basins = find_depressions_in_tile(tile_path, min_volume_m3)
        basins.extend(tile_basins)
        print(f"  [{i}/{len(tile_paths)}] {tile_path.name}: {len(tile_basins)} basins "
              f">= {min_volume_m3/1e6:.2f}Mm3 (running total {len(basins)})", flush=True)
    return basins


def main() -> None:
    """A separate, cached data-prep step (like fetch_data.py) rather than something
    find_sites.py recomputes every run: ~1 minute per DEM tile (63 tiles for Romania),
    so a full country run takes over an hour. find_sites.py's WATERSHED mode just reads
    the cached data/watershed_basins.geojson this writes and does the (cheap) lake-
    pairing fresh each run — the expensive part, real depression-filling, happens once.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    data_dir = Path(__file__).resolve().parent.parent / "data"
    out_path = data_dir / "watershed_basins.geojson"

    tile_paths = sorted((data_dir / "dem").glob("*.tif"))
    print(f"Finding natural depressions across {len(tile_paths)} DEM tiles "
          f"(min_volume_m3={100_000:,}, ~1min/tile)...")
    basins = find_all_depressions(tile_paths, min_volume_m3=100_000)

    gdf = gpd.GeoDataFrame(
        [{k: v for k, v in b.items() if k not in ("lon", "lat")} for b in basins],
        geometry=[Point(b["lon"], b["lat"]) for b in basins],
        crs="EPSG:4326",
    )
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"wrote {out_path} ({len(basins)} natural depressions found)")


if __name__ == "__main__":
    main()
