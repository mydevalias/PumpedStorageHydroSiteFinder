"""How much water a candidate reservoir site could hold, and what that's roughly
worth in power/energy terms. Doesn't know anything about lakes, the DEM tiles, or
the map — just: given an elevation grid and a starting pixel, how big a basin forms
there, and what does that basin's volume + head translate to in MW/MWh.

See find_sites.py for how these are actually used (searching for candidate seed
pixels, drawing a dam line, writing the output files, etc).
"""

import heapq
import math

import numpy as np

# ---- CONFIG ------------------------------------------------------------

MAX_BASIN_CELLS = 4000  # hard cap on cells per flood-fill (~3.6km^2 at 30m res) — a compute
                          # guard independent of max_basin_radius_m/max_dam_height_m: gentle
                          # terrain can fill a huge fraction of even a bounded search window

WATER_DENSITY_KG_M3 = 1000
GRAVITY_M_S2 = 9.81
ROUND_TRIP_EFFICIENCY = 0.85  # typical for pumped hydro; approximate

# Power (MW) isn't derivable from head/volume alone — that also needs a flow rate, which
# depends on penstock/turbine sizing we don't model. Standard back-of-envelope approach:
# assume the reservoir discharges over a fixed duration, so MW = MWh / hours.
#
# CORRECTED 2026-09-01: this was 8, on the reasoning "8h is conservative — a shorter
# duration than the real Lăpuștești's ~13h, so it'd underestimate MW". That reasoning was
# backwards: MW = MWh / duration, so a SHORTER duration divides by a smaller number and
# gives a LARGER MW, not a smaller one. Checked directly: real Lăpuștești is 10M m3 @
# 563.5m head = 13047 MWh; at the real 1000MW rating that's a 13.0h duration. Using 8h
# instead would have reported 1631MW for that same real site — 1.63x its actual rating,
# before any flow-rate cap even applies. 13 is the one real duration figure we have for a
# Romanian pumped-storage design; use it rather than a shorter, unjustified guess. Because
# this is a constant divisor, it rescales storage_mwh but never changes the ranking order
# between candidates — MAX_FLOW_RATE_M3_S (calibrated independently, see below) is
# unaffected by this change, though which candidates trigger it shifts (a longer duration
# means a given volume implies a smaller flow, so fewer candidates hit the cap; the ones
# that don't are still reduced directly by the smaller MWh/duration ratio, so both effects
# push non-capped candidates' MW down, not up).
DESIGN_DISCHARGE_HOURS = 13


def basin_volume(elev: np.ndarray, valid: np.ndarray, seed_row: int, seed_col: int,
                  pixel_dx_m: float, pixel_dy_m: float, max_dam_height_m: float,
                  max_basin_radius_m: float) -> tuple[float, float, float, tuple | None]:
    """Priority-flood outward from (seed_row, seed_col) — the dam site — never going
    below the seed's own elevation (that's downstream of the dam, not in the
    reservoir), raising the water level only as far as the surrounding terrain
    naturally contains it, capped at max_dam_height_m vertically, max_basin_radius_m
    laterally, and MAX_BASIN_CELLS as a hard compute guard (real terrain rarely
    encloses a basin within the first two bounds alone — a gentle slope can run for
    kilometers before rising 100m, and MAX_BASIN_CELLS exists for exactly that case).
    Returns (volume_m3, surface_area_m2, water_level_m,
    pour_point) where pour_point is (row, col) of the natural rim the flood stopped
    at, or None if the flood instead ran out of search window/cell budget first.
    """
    height, width = elev.shape
    seed_elev = elev[seed_row, seed_col]
    pixel_area_m2 = pixel_dx_m * pixel_dy_m

    visited = np.zeros_like(valid, dtype=bool)
    heap = [(seed_elev, seed_row, seed_col)]
    basin_cells = []  # elevation of each cell included in the basin
    water_level = seed_elev
    pour_point = None

    while heap:
        if len(basin_cells) >= MAX_BASIN_CELLS:
            break  # hit the compute guard, not a real rim — no pour_point reported
        elev_here, r, c = heapq.heappop(heap)
        if visited[r, c]:
            continue
        if elev_here - seed_elev > max_dam_height_m:
            pour_point = (r, c)
            break  # would need a taller dam than allowed to include this cell
        visited[r, c] = True
        water_level = max(water_level, elev_here)
        basin_cells.append(elev_here)

        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < height and 0 <= nc < width) or visited[nr, nc] or not valid[nr, nc]:
                continue
            # A reservoir behind a dam at the seed never extends below the seed's own
            # elevation — that's downstream, on the far side of the dam. Without this,
            # a seed that isn't a true valley bottom (ENGINEERED mode doesn't require
            # one) lets the flood run downhill indefinitely, "flooding" an open
            # hillside instead of a basin (2m tolerance for DEM noise on flat ground).
            if elev[nr, nc] < seed_elev - 2.0:
                continue
            dist_m = math.hypot((nr - seed_row) * pixel_dy_m, (nc - seed_col) * pixel_dx_m)
            if dist_m > max_basin_radius_m:
                continue
            heapq.heappush(heap, (elev[nr, nc], nr, nc))

    if not basin_cells:
        return 0.0, 0.0, seed_elev, None

    cell_elevs = np.array(basin_cells)
    volume_m3 = float(np.sum(water_level - cell_elevs)) * pixel_area_m2
    surface_area_m2 = len(basin_cells) * pixel_area_m2
    return volume_m3, surface_area_m2, water_level, pour_point


def storage_capacity_mwh(head_m: float, volume_m3: float) -> float:
    """E = rho * g * V * H * efficiency, converted from Joules to MWh."""
    energy_joules = WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * volume_m3 * head_m * ROUND_TRIP_EFFICIENCY
    return energy_joules / 3_600_000_000


def estimated_power_mw(storage_mwh: float) -> float:
    """See DESIGN_DISCHARGE_HOURS comment: average power if the basin discharges over
    that fixed duration. Naive — see realistic_power_mw(), which is what find_sites.py
    actually scores on: this alone silently assumes any flow rate is buildable, however
    large."""
    return storage_mwh / DESIGN_DISCHARGE_HOURS


# Calibrated and cross-checked against three real Romanian hydro plants — head, flow, and
# rated MW are all independently published for each, not derived by us:
#   Vidraru:          324m / 90 m3/s / 220MW real  -> rho*g*Q*H*eta predicts ~243MW
#   Lotru-Ciunget:    809m / 80 m3/s / 510MW real   -> predicts ~540MW
#   Tarnița-Lăpuștești (planned): 563.5m / 1000MW rated -> implied flow ~213 m3/s
#     (its flow isn't independently published, so this direction is back-calculated,
#     unlike the other two which check the formula against a real flow AND a real MW).
# The first two validate that rho*g*Q*H*eta itself is accurate to ~10% against real plants.
# MAX_FLOW_RATE_M3_S is set from the largest of the three (Tarnița–Lăpuștești's ~213 m3/s —
# a big modern multi-unit design, vs. 80-90 m3/s for the single/few-unit older plants),
# rounded up for headroom: the ceiling on what a single realistic project's waterway can
# carry, checked in-session against a candidate that otherwise reported ~5700MW at 1970
# m3/s (under the DESIGN_DISCHARGE_HOURS=8 in effect at the time; see that constant's
# history above) — 9x Tarnița–Lăpuștești's own flow, not something any single project
# could build. This ceiling is independent of DESIGN_DISCHARGE_HOURS (it comes straight
# from real Q, H, MW figures) and needed no change when that constant was corrected.
MAX_FLOW_RATE_M3_S = 250


def implied_flow_m3_s(volume_m3: float, discharge_hours: float = DESIGN_DISCHARGE_HOURS) -> float:
    """Flow rate needed to move volume_m3 over discharge_hours."""
    return volume_m3 / (discharge_hours * 3600)


def power_from_flow_mw(flow_m3_s: float, head_m: float) -> float:
    """P = rho * g * Q * H * eta, in MW. The same physics as storage_capacity_mwh(), just
    per unit time instead of integrated over a volume."""
    return (WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * flow_m3_s * head_m * ROUND_TRIP_EFFICIENCY) / 1_000_000


def realistic_power_mw(storage_mwh: float, head_m: float, volume_m3: float) -> tuple[float, float, bool]:
    """estimated_power_mw() alone assumes you can build a waterway big enough to move the
    whole volume in DESIGN_DISCHARGE_HOURS, however large that requires the flow to be —
    caught this session on a candidate demanding 1970 m3/s (see MAX_FLOW_RATE_M3_S comment;
    that figure was under the since-corrected DESIGN_DISCHARGE_HOURS=8).
    This caps the flow at MAX_FLOW_RATE_M3_S instead: a large-volume candidate just takes
    longer than DESIGN_DISCHARGE_HOURS to fully cycle, rather than reporting an unbuildable
    instantaneous power figure. Small-volume candidates are never affected — their required
    flow is already well under the ceiling, so this only ever reduces implausibly large
    numbers, never inflates small ones.

    Returns (power_mw, implied_flow_m3_s, flow_limited) — the flow returned is always the
    UNCAPPED figure (what DESIGN_DISCHARGE_HOURS would require), so callers can see how far
    over the ceiling a candidate actually was, not just that it was capped.
    """
    flow = implied_flow_m3_s(volume_m3)
    if flow <= MAX_FLOW_RATE_M3_S:
        return storage_mwh / DESIGN_DISCHARGE_HOURS, flow, False
    return power_from_flow_mw(MAX_FLOW_RATE_M3_S, head_m), flow, True


def fit_reservoir_area_volume_model(hydrolakes_shp_path) -> tuple[float, float, float, int]:
    """An independent, data-driven cross-check for basin_volume()'s terrain-based
    estimate: fit V = a * A^b (log-log least squares — the standard form for this in
    limnology) on HydroLAKES' *global* reservoir-type lakes (Lake_type=2 — dammed water
    bodies, not natural lakes), reading straight from the cached HydroLAKES shapefile
    (no new download, and no network at all — it's the file fetch_data.py already
    pulled down). Global, not Romania-only: Romania alone only has 78 reservoirs, too
    few for a stable fit (R^2 drops from ~0.76 to ~0.46 in testing) — country-agnostic
    is also right for a pipeline meant to be reused elsewhere (see DATA_SOURCES.md).

    Important, verified caveat: even reservoir-only, this still systematically
    *underestimates* deep, narrow-valley mountain reservoirs — checked against the one
    real ground-truth example available (Lake Tarnița, leave-one-out: predicts ~26M m3
    against a real 74M m3, ~3x low; the unfiltered all-lake-types fit is ~20x low).
    That's exactly the site profile pumped-storage cares about. Treat this as a loose
    plausibility floor, not a precise estimate, and expect basin_volume() to often
    legitimately exceed it for good candidates — that's the terrain-specific method
    picking up depth an area-only statistical model can't see.

    Returns (a, b, r_squared, n) so callers can print/log the fit quality rather than
    trust it blindly.
    """
    import geopandas as gpd

    lakes = gpd.read_file(hydrolakes_shp_path, where="Lake_type = 2", ignore_geometry=True)
    lakes = lakes[(lakes["Lake_area"] > 0) & (lakes["Vol_total"] > 0)]

    log_area = np.log(lakes["Lake_area"].values)
    log_volume = np.log(lakes["Vol_total"].values * 1_000_000)
    b, log_a = np.polyfit(log_area, log_volume, 1)
    a = np.exp(log_a)

    predicted = a * lakes["Lake_area"].values ** b
    ss_res = np.sum((log_volume - np.log(predicted)) ** 2)
    ss_tot = np.sum((log_volume - log_volume.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot

    return float(a), float(b), float(r_squared), len(lakes)


def empirical_reservoir_volume_m3(surface_area_km2: float, a: float, b: float) -> float:
    """Apply the fit_reservoir_area_volume_model() power law to a candidate's own
    surface area. See that function's docstring for the (significant) caveats."""
    return a * surface_area_km2 ** b


def usable_cycling_volume_m3(new_site_volume_m3: float, existing_lake_volume_m3: float | None) -> float:
    """A pumped-storage cycle moves water between two reservoirs — you can never move
    more than whichever one is smaller actually holds, no matter how large the other
    one's basin could physically be. `basin_volume()` only looks at the terrain around
    the *new* site; it has no idea how big the anchor lake itself is, so a new site can
    come back with a much bigger footprint than the existing lake could ever fill.

    existing_lake_volume_m3 is HydroLAKES' own estimate (see fetch_data.py) — a value we
    didn't compute, not derived from our DEM. None/<=0 means "unknown" (some small lakes
    aren't in HydroLAKES' volume model): in that case we can't validate the constraint,
    so we return new_site_volume_m3 unchanged rather than silently assuming it's fine —
    callers should treat that case as unverified, not as "no constraint applies".
    """
    if existing_lake_volume_m3 is None or existing_lake_volume_m3 <= 0:
        return new_site_volume_m3
    return min(new_site_volume_m3, existing_lake_volume_m3)
