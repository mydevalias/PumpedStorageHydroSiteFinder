"""Part 2 (algorithm) — Case B only: for each existing lake, search the
surrounding terrain for the best nearby spot to build a *new* reservoir.

Two search modes, run independently, each producing its own ranked top list:

- NATURAL: only considers sites that are already a closed topographic
  depression (a "bowl" — local minimum in a small neighborhood), i.e. no
  more than a modest containment wall needed. These are rare and small by
  nature — that's not a bug, a genuinely enclosed natural pit just doesn't
  hold much water.
- ENGINEERED: considers *any* qualifying point in the valley as a place to
  build a dam wall across, the way most real reservoirs are actually made
  (see calibration note below) — the site doesn't need to be a pre-existing
  depression, the dam creates the depression. This is what "build a new
  lake" means in the project discussion. Because monotonically-sloping
  valley points aren't local minima, ENGINEERED can't use the bowl filter
  to keep the search cheap — instead it samples a coarse grid of points
  (SEED_STRIDE_PX apart) and flood-fills from each.

Real-world calibration (Tarnița–Lăpuștești, Cluj County — Romania's actual
1000 MW pumped-storage project, still unbuilt as of 2026):
  - Existing lower reservoir (Lake Tarnița): arch dam, 97m tall, impounds a
    2.2km² lake (drainage basin 491km²).
  - Upper reservoir: NOT a natural bowl — an engineered lake to be built on
    the Lăpuștești *plateau*, at 1085m, 563.5m of head above Tarnița.
  - Design volumes used for the pumped-storage cycle: ~15M m³ (lower) /
    ~10M m³ (upper) — smaller than either figure above suggests, since only
    part of each reservoir's volume is cycled daily.
  Sources: en.wikipedia.org and ro.wikipedia.org "Tarnița–Lăpuștești"
  articles, adevarul.ro coverage of the Tarnița dam (checked 2026-09-01).
  ENGINEERED's MAX_DAM_HEIGHT_M and MAX_BASIN_RADIUS_M are set from the
  97m dam / ~2.2km² lake, not invented numbers.

Volume estimate (both modes): see volumes.basin_volume() — a priority-flood
fill grows a basin outward from a seed pixel (like the "trapping rain water"
problem), raising the water level only as far as the terrain naturally
contains it, capped at max_dam_height_m vertically and max_basin_radius_m
laterally. Still a heuristic, not a real basin-delineation algorithm (out of
scope for v1, see ReadmeAi.md) — a basin whose true rim lies outside the
search window gets cut off early (underestimated), never overestimated.

Dam location: the seed pixel *is* the dam site (see basin_volume()'s
docstring) — the reservoir forms upstream/around it, never below its own
elevation. dam_start/dam_end is a short line through that seed, perpendicular
to the local slope (i.e. roughly along the valley's contour), for the map to
draw. Earlier this session it was drawn through the flood's pour point (the
far rim of the basin) instead — a bug, since that's the opposite side of the
reservoir from where a dam would actually go; fixed. Separately, basin_bounded
records whether the flood found a genuine topographic rim (True — confident
volume) or was cut off by max_basin_radius_m/MAX_BASIN_CELLS first (False —
volume_m3 is a lower bound, the true basin may extend further).

Existing-lake volume cap: a pumped-storage cycle can't move more water than
whichever reservoir is smaller — basin_volume() only looks at the new site's
terrain, so on its own it can (and did, before this was added) return a new
basin bigger than the anchor lake could ever fill. volumes.usable_cycling_
volume_m3() caps it against the lake's own volume (HydroLAKES' Vol_total,
not something we compute), and *that* capped value — not the raw basin
volume — feeds MIN_VOLUME_M3, storage_mwh, and the MW ranking.
basin_volume_m3 keeps the uncapped figure for reference; limited_by_
existing_lake says whether the cap actually bit.

Empirical cross-check: volumes.fit_reservoir_area_volume_model() fits an
independent area->volume power law on real, built reservoirs worldwide
(HydroLAKES Lake_type=2), then empirical_reservoir_volume_m3() applies it to
each candidate's own surface_area_m2. This is a *second opinion* on
basin_volume_m3, from a completely different method (statistics on real
reservoirs vs. our terrain flood-fill) — not used for scoring or filtering,
just reported (empirical_volume_m3) so a wildly-disagreeing candidate is
visible rather than silently trusted. See that function's docstring for a
real, checked caveat: it still underestimates deep mountain reservoirs
(Tarnița, our one ground-truth case) by ~3x, so basin_volume_m3 legitimately
exceeding it is expected and not itself a red flag — only a huge
*shortfall* (basin_volume_m3 far *below* the cross-check) is worth a second
look.

Ranking: both modes score by estimated power capacity in MW (volumes.
realistic_power_mw), not the old head/distance ratio — volume (and hence
power) has a much bigger effect on whether a site is worth building than
being a bit closer or a bit higher. head/distance are still hard filters,
not the ranking metric.

Flow-rate ceiling: MW isn't derivable from head/volume alone — that also
needs a flow rate (penstock/turbine sizing we don't model), and naively
assuming the whole volume discharges over DESIGN_DISCHARGE_HOURS implies
*some* flow rate, however large. A candidate found this session needed
1970 m3/s to do that (under the DESIGN_DISCHARGE_HOURS=8 in effect then,
since corrected to 13 — see volumes.py) — 9x the flow of Romania's actual
flagship pumped-storage project (the planned Tarnița–Lăpuștești, 1000MW).
volumes.realistic_power_mw() caps the flow at MAX_FLOW_RATE_M3_S (calibrated
against three real plants — see its docstring) instead: large-volume
candidates just take longer than DESIGN_DISCHARGE_HOURS to fully cycle,
rather than reporting an unbuildable instantaneous power. flow_limited and
implied_flow_m3_s (the uncapped figure) show whether and by how much a
candidate hit this ceiling.

Reads data/lakes.geojson (from fetch_data.py) and the cached DEM tiles in
data/dem/. Writes, per mode:
  - data/candidates_<mode>_all.geojson — every lake's best candidate, ranked
  - docs/candidates_<mode>.geojson     — just the top N, for the map
"""

import math
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.merge import merge
from scipy.ndimage import minimum_filter
from shapely.geometry import LineString

from contours import CONTOUR_INTERVAL_M, generate_contours
from fetch_data import DATA_DIR, LAKES_OUT_PATH, dem_tile_path, fetch_hydrolakes_raw
from volumes import (
    DESIGN_DISCHARGE_HOURS,
    MAX_FLOW_RATE_M3_S,
    basin_volume,
    empirical_reservoir_volume_m3,
    fit_reservoir_area_volume_model,
    realistic_power_mw,
    storage_capacity_mwh,
    usable_cycling_volume_m3,
)

# ---- CONFIG ------------------------------------------------------------

SEARCH_RADIUS_M = 2000  # how far around each lake to look for a new site
MIN_HEAD_M = 100  # minimum elevation difference to be worth building
MAX_SLOPE_GRADE = 1.0  # reject candidates on implausibly steep ground (100% grade / 45deg)
MIN_VOLUME_M3 = 100_000  # below this, treat the site as "no real basin", not a candidate
TOP_N = 3

DAM_LINE_HALF_LENGTH_M = (80, 400)  # (min, max) — clamp for the illustrative dam line drawn
                                      # on the map; not derived from real valley cross-sections


@dataclass(frozen=True)
class SearchMode:
    name: str
    bowl_required: bool
    max_dam_height_m: float
    max_basin_radius_m: float
    bowl_window_px: int = 5  # only used when bowl_required
    seed_stride_px: int = 3  # only used when not bowl_required (compute guard)
    max_volume_candidates: int = 50  # flood-fills per lake — the real per-lake compute cap


NATURAL = SearchMode(
    name="natural",
    bowl_required=True,
    bowl_window_px=5,
    max_dam_height_m=60,
    max_basin_radius_m=500,
)

# Calibrated to the real Tarnița dam (97m) and Tarnița lake (2.2km^2, radius ~840m) — see
# module docstring. Not bowl-restricted: a dam can be built across any qualifying valley point,
# which means far more lakes have *some* candidate than NATURAL — max_volume_candidates and
# seed_stride_px are cut down accordingly to keep total runtime in the same ballpark (each
# flood-fill here also covers ~9x the area of a NATURAL one, radius^2, so it's disproportionately
# more expensive per-candidate too — see MAX_BASIN_CELLS in volumes.py).
ENGINEERED = SearchMode(
    name="engineered",
    bowl_required=False,
    seed_stride_px=5,
    max_dam_height_m=100,
    max_basin_radius_m=1500,
    max_volume_candidates=15,
)


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """Returns (meters per degree of longitude, meters per degree of latitude) at lat_deg."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_deg))
    return m_per_deg_lon, m_per_deg_lat


def dam_line_endpoints(row: int, col: int, grad_x: np.ndarray, grad_y: np.ndarray,
                        surface_area_m2: float, lon_grid: np.ndarray, lat_grid: np.ndarray,
                        m_per_deg_lon: float, m_per_deg_lat: float):
    """A short illustrative line through the pour point, perpendicular to the local slope
    (i.e. roughly along the valley's contour — where a dam wall would run). Length is a
    heuristic guess from the basin's surface area, clamped to DAM_LINE_HALF_LENGTH_M —
    not a real cross-valley survey.
    """
    gx, gy = grad_x[row, col], grad_y[row, col]
    slope_mag = math.hypot(gx, gy)
    if slope_mag == 0:
        return None
    # Perpendicular to the slope direction, in meters.
    perp_x, perp_y = -gy / slope_mag, gx / slope_mag

    half_length_m = math.sqrt(surface_area_m2) * 0.5
    half_length_m = max(DAM_LINE_HALF_LENGTH_M[0], min(DAM_LINE_HALF_LENGTH_M[1], half_length_m))

    lon0, lat0 = lon_grid[row, col], lat_grid[row, col]
    start = (
        lon0 - perp_x * half_length_m / m_per_deg_lon,
        lat0 - perp_y * half_length_m / m_per_deg_lat,
    )
    end = (
        lon0 + perp_x * half_length_m / m_per_deg_lon,
        lat0 + perp_y * half_length_m / m_per_deg_lat,
    )
    return start, end


def tiles_for_window(min_lon, min_lat, max_lon, max_lat) -> list[Path]:
    tiles = set()
    for lat in (math.floor(min_lat), math.floor(max_lat)):
        for lon in (math.floor(min_lon), math.floor(max_lon)):
            path = dem_tile_path(lat, lon)
            if path.exists():
                tiles.add(path)
    return sorted(tiles)


def load_elevation_window(center_lon: float, center_lat: float, radius_m: float):
    """Reads and merges just enough cached DEM tiles to cover a radius_m square around
    (center_lon, center_lat). Returns (elev, valid, transform, lon_1d, lat_1d) — the 1D
    axis arrays are the natural coordinates for a regular grid (what contourpy and the
    meshgrid-based searches both want), or None if no tiles cover this point at all.
    Shared by best_new_site() (the search) and contours.py (drawing what's already there)
    so both read the DEM the same way.
    """
    m_per_deg_lon, m_per_deg_lat = meters_per_degree(center_lat)
    d_lon = radius_m / m_per_deg_lon
    d_lat = radius_m / m_per_deg_lat
    window = (center_lon - d_lon, center_lat - d_lat, center_lon + d_lon, center_lat + d_lat)

    tile_paths = tiles_for_window(*window)
    if not tile_paths:
        return None

    with rasterio.open(tile_paths[0]) as first:
        nodata = first.nodata
    mosaic, transform = merge([str(p) for p in tile_paths], bounds=window, nodata=nodata)
    elev = mosaic[0].astype(np.float64)
    valid = np.ones_like(elev, dtype=bool)
    if nodata is not None:
        valid &= elev != nodata
    if elev.size == 0 or not valid.any():
        return None

    height, width = elev.shape
    cols = np.arange(width)
    rows = np.arange(height)
    lon_1d = transform.c + (cols + 0.5) * transform.a
    lat_1d = transform.f + (rows + 0.5) * transform.e
    return elev, valid, transform, lon_1d, lat_1d


def best_new_site(lake_lon: float, lake_lat: float, lake_elev: float, lake_volume_m3: float | None,
                   mode: SearchMode) -> dict | None:
    m_per_deg_lon, m_per_deg_lat = meters_per_degree(lake_lat)

    window = load_elevation_window(lake_lon, lake_lat, SEARCH_RADIUS_M)
    if window is None:
        return None
    elev, valid, transform, lon_1d, lat_1d = window
    lon_grid, lat_grid = np.meshgrid(lon_1d, lat_1d)

    dx_m = (lon_grid - lake_lon) * m_per_deg_lon
    dy_m = (lat_grid - lake_lat) * m_per_deg_lat
    distance_grid = np.sqrt(dx_m**2 + dy_m**2)

    # Exclude the lake's own footprint (approximated as a circle from its area).
    lake_radius_m = 100.0
    within_lake_mask = distance_grid < lake_radius_m

    fill_value = np.nanmax(elev[valid]) + 1.0
    elev_filled = np.where(valid, elev, fill_value)

    pixel_dx_m = abs(transform.a) * m_per_deg_lon
    pixel_dy_m = abs(transform.e) * m_per_deg_lat
    grad_y, grad_x = np.gradient(elev_filled, pixel_dy_m, pixel_dx_m)
    slope = np.sqrt(grad_x**2 + grad_y**2)

    head_grid = np.abs(elev - lake_elev)

    base_mask = (
        valid
        & ~within_lake_mask
        & (distance_grid <= SEARCH_RADIUS_M)
        & (head_grid >= MIN_HEAD_M)
        & (slope <= MAX_SLOPE_GRADE)
    )

    if mode.bowl_required:
        local_min = minimum_filter(elev_filled, size=mode.bowl_window_px, mode="nearest")
        candidate_mask = base_mask & (elev_filled <= local_min)
    else:
        # No bowl requirement: a dam can go anywhere qualifying in the valley. Sample a
        # coarse grid instead of every pixel to keep the flood-fill count bounded.
        stride_mask = np.zeros_like(base_mask)
        stride_mask[::mode.seed_stride_px, ::mode.seed_stride_px] = True
        candidate_mask = base_mask & stride_mask

    if not candidate_mask.any():
        return None

    # Flood-filling every qualifying pixel would be wasteful. Shortlist by the old
    # head/distance ratio first, then only run the (more expensive) volume estimate
    # on the shortlist.
    prelim_score = np.where(candidate_mask, head_grid / np.maximum(distance_grid, 1.0), -np.inf)
    candidate_rows, candidate_cols = np.where(candidate_mask)
    order = np.argsort(prelim_score[candidate_rows, candidate_cols])[::-1]
    shortlist = list(zip(candidate_rows[order], candidate_cols[order]))[:mode.max_volume_candidates]

    best = None
    for row, col in shortlist:
        basin_volume_m3, surface_area_m2, water_level_m, pour_point = basin_volume(
            elev, valid, row, col, pixel_dx_m, pixel_dy_m,
            mode.max_dam_height_m, mode.max_basin_radius_m,
        )
        # basin_volume() only looks at terrain around the NEW site — it has no idea how
        # much water the EXISTING lake actually holds. A pumped-storage cycle can't move
        # more water than the smaller of the two reservoirs, so cap it here before scoring
        # (see usable_cycling_volume_m3 docstring).
        volume_m3 = usable_cycling_volume_m3(basin_volume_m3, lake_volume_m3)
        if volume_m3 < MIN_VOLUME_M3:
            continue

        head_m = float(head_grid[row, col])
        storage_mwh = storage_capacity_mwh(head_m, volume_m3)
        power_mw, implied_flow_m3_s, flow_limited = realistic_power_mw(storage_mwh, head_m, volume_m3)
        if best is None or power_mw > best["score"]:
            site_elev = float(elev[row, col])
            # The dam goes at the seed itself — that's "the dam site" by basin_volume()'s
            # own definition (see its docstring). pour_point is a different thing: the far
            # rim of the flooded basin, wherever that happens to land — drawing the dam
            # line there instead (a bug fixed this session) put it on the opposite side of
            # the reservoir from where it'd actually be built.
            dam_line = dam_line_endpoints(
                row, col, grad_x, grad_y, surface_area_m2,
                lon_grid, lat_grid, m_per_deg_lon, m_per_deg_lat,
            )
            best = {
                "site_lon": float(lon_grid[row, col]),
                "site_lat": float(lat_grid[row, col]),
                "site_elevation_m": site_elev,
                "head_m": head_m,
                "distance_m": float(distance_grid[row, col]),
                "basin_volume_m3": basin_volume_m3,  # what the terrain could physically hold
                "volume_m3": volume_m3,  # what's actually usable — capped by the existing lake
                "lake_volume_m3": lake_volume_m3,
                "limited_by_existing_lake": (
                    lake_volume_m3 is not None and lake_volume_m3 > 0
                    and lake_volume_m3 < basin_volume_m3
                ),
                "surface_area_m2": surface_area_m2,
                "water_level_m": water_level_m,
                "storage_mwh": storage_mwh,
                "implied_flow_m3_s": implied_flow_m3_s,
                "flow_limited": flow_limited,
                "score": power_mw,
                "direction": "higher" if site_elev > lake_elev else "lower",
                "dam_line": dam_line,
                # pour_point is None when the flood was cut off by our radius/cell caps
                # rather than finding a genuine topographic rim — that means basin_volume_m3
                # is a lower bound, not a confident estimate (the true basin may be bigger).
                "basin_bounded": pour_point is not None,
            }

    return best


def run_mode(mode: SearchMode, lakes: gpd.GeoDataFrame, empirical_model: tuple[float, float]) -> list[dict]:
    print(f"Scanning {len(lakes)} lakes, mode={mode.name} "
          f"(max dam height={mode.max_dam_height_m}m, max basin radius={mode.max_basin_radius_m}m)...")
    empirical_a, empirical_b = empirical_model

    records = []
    skipped_no_elevation = 0
    unknown_lake_volume = 0
    for _, lake in lakes.iterrows():
        elevation = lake["elevation"]
        if elevation is None or (isinstance(elevation, float) and math.isnan(elevation)):
            skipped_no_elevation += 1
            continue

        lake_volume_m3 = lake["volume_m3"]
        if lake_volume_m3 is None or (isinstance(lake_volume_m3, float) and math.isnan(lake_volume_m3)):
            lake_volume_m3 = None
            unknown_lake_volume += 1

        result = best_new_site(lake.geometry.x, lake.geometry.y, elevation, lake_volume_m3, mode)
        if result is None:
            continue

        # Independent cross-check (see fit_reservoir_area_volume_model docstring for the
        # significant caveats — this is a loose plausibility floor, not a precise estimate).
        result["empirical_volume_m3"] = empirical_reservoir_volume_m3(
            result["surface_area_m2"] / 1_000_000, empirical_a, empirical_b
        )

        records.append(
            {
                "lake_id": lake["id"],
                "lake_lon": lake.geometry.x,
                "lake_lat": lake.geometry.y,
                "lake_elevation_m": elevation,
                **result,
            }
        )

    limited = sum(1 for r in records if r["limited_by_existing_lake"])
    print(f"  {len(records)} lakes produced a candidate "
          f"({skipped_no_elevation} skipped for missing elevation, "
          f"{unknown_lake_volume} with unknown lake volume — not validated against it, "
          f"{limited} capped by the existing lake's own volume)")
    records.sort(key=lambda r: r["score"], reverse=True)
    return records


def to_geodataframe(rows: list[dict]) -> gpd.GeoDataFrame:
    properties = []
    for i, r in enumerate(rows):
        dam_line = r["dam_line"]
        row_props = {
            "type": "lake-new",
            "rank": i + 1,
            "lake_id": r["lake_id"],
            "lake_elevation_m": round(r["lake_elevation_m"], 1),
            "new_site_elevation_m": round(r["site_elevation_m"], 1),
            "head_m": round(r["head_m"], 1),
            "distance_m": round(r["distance_m"], 1),
            "direction": r["direction"],
            "volume_million_m3": round(r["volume_m3"] / 1_000_000, 3),
            "basin_volume_million_m3": round(r["basin_volume_m3"] / 1_000_000, 3),
            "empirical_volume_million_m3": round(r["empirical_volume_m3"] / 1_000_000, 3),
            "lake_volume_million_m3": (
                round(r["lake_volume_m3"] / 1_000_000, 3) if r["lake_volume_m3"] else None
            ),
            "limited_by_existing_lake": r["limited_by_existing_lake"],
            "surface_area_km2": round(r["surface_area_m2"] / 1_000_000, 4),
            "storage_mwh": round(r["storage_mwh"], 1),
            "estimated_mw": round(r["score"], 1),
            "score": round(r["score"], 4),
            "implied_flow_m3_s": round(r["implied_flow_m3_s"], 1),
            "flow_limited": r["flow_limited"],
            "basin_bounded": r["basin_bounded"],
            "dam_start_lon": round(dam_line[0][0], 6) if dam_line else None,
            "dam_start_lat": round(dam_line[0][1], 6) if dam_line else None,
            "dam_end_lon": round(dam_line[1][0], 6) if dam_line else None,
            "dam_end_lat": round(dam_line[1][1], 6) if dam_line else None,
        }
        properties.append(row_props)

    return gpd.GeoDataFrame(
        properties,
        geometry=[
            LineString([(r["lake_lon"], r["lake_lat"]), (r["site_lon"], r["site_lat"])])
            for r in rows
        ],
        crs="EPSG:4326",
    )


def contours_geodataframe(top_candidates: list[dict]) -> gpd.GeoDataFrame:
    """Elevation contour lines for the search window around each of the given (already-
    ranked, top-N) candidates — reloads the DEM window per candidate (cheap: cached
    tiles, no network) rather than threading contour data through the whole search,
    since only a handful of candidates ever need this, not every lake scanned."""
    properties = []
    geometries = []
    for rank, r in enumerate(top_candidates, start=1):
        window = load_elevation_window(r["lake_lon"], r["lake_lat"], SEARCH_RADIUS_M)
        if window is None:
            continue
        elev, valid, _transform, lon_1d, lat_1d = window
        for line in generate_contours(lon_1d, lat_1d, elev, valid):
            properties.append({
                "rank": rank,
                "lake_id": r["lake_id"],
                "elevation_m": line["elevation_m"],
            })
            geometries.append(LineString(line["coordinates"]))

    return gpd.GeoDataFrame(properties, geometry=geometries, crs="EPSG:4326")


def main() -> None:
    lakes = gpd.read_file(LAKES_OUT_PATH)
    docs_dir = Path(__file__).resolve().parent.parent / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    hydrolakes_shp_path = fetch_hydrolakes_raw()  # cached, no download — just reused
    empirical_a, empirical_b, r_squared, n = fit_reservoir_area_volume_model(hydrolakes_shp_path)
    print(
        f"Empirical cross-check model (global HydroLAKES reservoirs, n={n}): "
        f"V = {empirical_a:.2f} * A^{empirical_b:.3f}  (R^2={r_squared:.3f} in log-log space — "
        f"a loose sanity floor, not a precise estimate; see fit_reservoir_area_volume_model)\n"
    )

    for mode in (NATURAL, ENGINEERED):
        records = run_mode(mode, lakes, (empirical_a, empirical_b))

        all_path = DATA_DIR / f"candidates_{mode.name}_all.geojson"
        to_geodataframe(records).to_file(all_path, driver="GeoJSON")
        print(f"  wrote {all_path} ({len(records)} candidates)")

        top = records[:TOP_N]
        top_path = docs_dir / f"candidates_{mode.name}.geojson"
        to_geodataframe(top).to_file(top_path, driver="GeoJSON")
        print(f"  wrote {top_path} (top {len(top)})")

        contours = contours_geodataframe(top)
        contours_path = docs_dir / f"contours_{mode.name}.geojson"
        contours.to_file(contours_path, driver="GeoJSON")
        print(f"  wrote {contours_path} ({len(contours)} contour segments, "
              f"{CONTOUR_INTERVAL_M}m interval)")

        for i, r in enumerate(top, start=1):
            confidence = "bounded" if r["basin_bounded"] else "may extend further — search-limited"
            lake_vol_note = (
                f"lake holds {r['lake_volume_m3']/1e6:.1f}Mm3, "
                f"{'CAPPED to it' if r['limited_by_existing_lake'] else 'not the limit'}"
                if r["lake_volume_m3"] else "lake volume unknown, not validated"
            )
            flow_note = (
                f"flow CAPPED to {MAX_FLOW_RATE_M3_S}m3/s (would need {r['implied_flow_m3_s']:.0f}m3/s otherwise)"
                if r["flow_limited"] else f"flow {r['implied_flow_m3_s']:.0f}m3/s, within realistic range"
            )
            print(
                f"  #{i}: lake {r['lake_id']} -> new site {r['direction']}, "
                f"head={r['head_m']:.0f}m, distance={r['distance_m']:.0f}m, "
                f"basin could hold {r['basin_volume_m3']/1e6:.2f}Mm3 "
                f"(cross-check predicts {r['empirical_volume_m3']/1e6:.2f}Mm3 for this footprint), "
                f"usable={r['volume_m3']/1e6:.2f}Mm3 ({confidence}; {lake_vol_note}), "
                f"~{r['score']:.0f}MW, {flow_note} "
                f"({r['storage_mwh']:.0f}MWh @ {DESIGN_DISCHARGE_HOURS}h)"
            )
        print()


if __name__ == "__main__":
    main()
