"""Part 2 (algorithm) — Case B only: for each existing lake, search the
surrounding terrain for the best nearby spot to build a *new* reservoir.

Two search modes, run independently, each producing its own ranked top list:

- NATURAL: only considers sites that are already a closed topographic
  depression (a "bowl" — the true lowest point over a neighborhood as big
  as the flood is itself allowed to grow into, see bowl_window_px), i.e.
  no more than a modest containment wall needed. These are rare — that's
  not a bug, a genuinely enclosed natural pit is uncommon by nature.
  What NATURAL mode does still find plenty of, especially in Romania's
  highland regions, is broad, gently-sloping *plateau* depressions —
  real, locally-lowest points, just not classic steep-walled mountain
  bowls — surfaced as "plateau depression" rather than "bowl" for that
  reason (see bowl_window_px below for how this was checked against real
  terrain, not assumed).
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
records whether the flood grew all the way up to this mode's max_dam_height_m
budget (True) or was cut off by max_basin_radius_m/MAX_BASIN_CELLS first
before ever reaching that height (False — volume_m3 is a lower bound, the
true basin may extend further). True does NOT mean "found where the terrain
naturally closes" — checked directly against the full dataset this session:
100% of basin_bounded=True candidates (50/95 natural, 22/132 engineered) sit
within 2m of the height cap, meaning it's really just "spent our whole height
budget," not evidence the real rim is right there (see basin_volume()'s
docstring in volumes.py). Read it as "this is the full basin at the tallest
dam this mode allows," not as a confidence signal either way. When
dam_line exists, dam_construction.estimate_concrete_volume_m3() gives a
crude order-of-magnitude concrete estimate from the dam's height (water_
level_m - site elevation) and the dam_line's own length — see that
function's docstring for why this assumes a plain concrete gravity dam
specifically (likely overestimating for a site an arch dam would suit, and
not applicable at all to an embankment dam). No dam_line means no estimate
either, for the same reason dam_line itself is sometimes absent (see above).

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
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.merge import merge
from scipy.ndimage import distance_transform_edt, minimum_filter, uniform_filter
from rasterio.features import geometry_mask, shapes as rasterio_shapes
from shapely.geometry import LineString
from shapely.geometry import shape as shapely_shape
from shapely.ops import unary_union

from contours import CONTOUR_INTERVAL_M, generate_contours
from dam_construction import estimate_concrete_volume_m3
from fetch_data import BBOX, DATA_DIR, LAKES_OUT_PATH, dem_tile_path, fetch_hydrolakes_raw
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

SEARCH_RADIUS_M = 2000  # how far around each lake to look for a new site (the CANDIDATE
                          # filter — not the loaded DEM window, see SEARCH_WINDOW_RADIUS_M
                          # below). This is ENGINEERED's own radius (via SearchMode's
                          # seed_radius_m default) and PLATEAU/NATURAL's fallback constant
                          # for anything that isn't itself mode-aware (contours_geodataframe's
                          # default) — NATURAL overrides its own seed_radius_m to 2500,
                          # PLATEAU has its own separate PLATEAU_SEARCH_RADIUS_M entirely.
                          # See best_new_site(), which reads mode.seed_radius_m, not this
                          # constant directly.
# Real bug found this session: a candidate right at the edge of SEARCH_RADIUS_M sits right
# at the edge of the loaded DEM array too, if the array is only loaded out to that same
# radius. minimum_filter's bowl check (mode="nearest") then pads past the array edge by
# repeating the edge row/column — it never sees real terrain beyond the window, and a slope
# that's simply still descending off the edge of what got loaded looks like a local minimum
# by default. Caught concretely: lake 1357899's NATURAL #4 candidate (distance=1986m, 14m
# inside the 2000m cutoff) sat at row=0 of its loaded array; re-probing with a window
# properly centered on the SITE itself (not truncated) found real terrain descending 175m
# within 500m to the north — the opposite of a bowl. Fix: load extra margin around
# SEARCH_RADIUS_M so every valid candidate keeps a full, untruncated neighborhood for its
# own bowl/flood-fill/dam-axis checks; the candidate filter itself still cuts off at the
# original SEARCH_RADIUS_M, only the loaded array is bigger.
#
# Tried scaling this margin all the way up to mode.max_basin_radius_m (2000m for
# ENGINEERED, since basin_volume()'s flood-fill can reach that far from the SEED, and a
# seed can itself be up to SEARCH_RADIUS_M from the lake) — technically correct for what
# it targeted (near-edge ENGINEERED candidates were basin_volume_m3-underestimated by
# 1.4x-3x, confirmed on lakes 1358492/170761/170671/14030/169243), but reverted: letting
# ENGINEERED's flood run its FULL, un-truncated 2000m reach near Tarnița exposed a much
# bigger, pre-existing problem the truncation had been accidentally masking. Checked
# EVERY candidate (not just the shortlist) in that window, not only the flagged ones:
# 175 of 522 "pass" dam_line's containment check with basin_volume_m3 of 40-220 million
# m^3 over 1-4 km^2 each — physically absurd at this density (Vidraru, one of Romania's
# largest real dams, holds ~465M m^3; this would put dozens of Vidraru-scale reservoirs
# within 2km of one lake). Traced one concretely: seed sits on a ridge nose, terrain
# drops 100-288m in 8 of 12 sampled directions within 500m, and the flood sprawls 2km
# across the one direction that doesn't drop — dam_line_endpoints only samples +/-400m
# from the seed, so it never sees that the "basin" behind it is an open sprawl, not a
# valley. This is the same weak-downhill-guard limitation flagged (and deliberately left
# alone) in the 2026-09-01 QA pass — the window truncation had been an accidental,
# unintended cap on how much damage it could do. Un-truncating it without ALSO fixing
# containment (checking along the basin's own footprint, not a fixed short probe from the
# seed — a real redesign, not a margin tweak) makes results worse, not better. Reverted
# to a flat, mode-independent margin instead: enough for the CONFIRMED, narrower bugs
# (the bowl-check's minimum_filter window, and one-sided-gradient slope artifacts at the
# array edge — both only need ~500m, not 2000m), while leaving ENGINEERED's near-edge
# under-measurement as a known, smaller, not-yet-fixed limitation rather than trading it
# for a worse one. See DATA_SOURCES.md.
SEARCH_WINDOW_RADIUS_M = SEARCH_RADIUS_M + 400

LAKE_EXCLUSION_BUFFER_M = 500.0  # how far beyond the lake's real shoreline (not its
                                   # anchor point — see best_new_site()) to also exclude.
                                   # Raised from 100 (user's call, 2026-09-02): even
                                   # measured correctly from the real shore, 100m let a
                                   # flagged candidate's SEED sit 557m away (245m for the
                                   # resulting basin footprint, which grows toward the
                                   # lake unconstrained by this buffer — see the
                                   # docstring note below) — close enough to read as
                                   # "right next to the existing dam" on the map. Seed-
                                   # only, not a cap on how close the flood itself can
                                   # then grow — see best_new_site() for why.

MIN_HEAD_M = 100  # minimum elevation difference to be worth building
MAX_SLOPE_GRADE = 1.0  # reject candidates on implausibly steep ground (100% grade / 45deg)
MIN_VOLUME_M3 = 100_000  # below this, treat the site as "no real basin", not a candidate
TOP_N = {  # 20 -> 100 -> 20 (user's calls, 2026-09-02/03): raised for a broader look
            # while the display filters below didn't exist yet; lowered back once
            # MIN_DISPLAY_MW/MIN_VOLUME_RATIO_TO_LAKE were doing the real filtering
            # work and "top 20 per mode" was the more useful, comparable-across-modes
            # shape again. contours_geodataframe/basin_footprints_geodataframe both
            # scale with this (one DEM reload + basin_volume() rerun per candidate).
            # Split per-mode (2026-09-03, later same day): after PLATEAU_SEARCH_RADIUS_M
            # and the ratio-floor drop let far more real PLATEAU candidates qualify
            # nationally, Leșu (a real, previously user-verified candidate — see the
            # 2026-09-03 Leșu entries above) fell to raw rank 42, just past the top-20
            # cutoff. User's call (AskUserQuestion): raise PLATEAU's own TOP_N to 50 so
            # candidates like it stay visible. NATURAL raised to 50 too, same day, for
            # consistency across modes — it only has 5 raw candidates total (see
            # run_mode()'s own print), so this is a no-op on what's actually displayed
            # right now, not a meaningful loosening; kept as a dict rather than folded
            # back into one shared constant since ENGINEERED (96 raw candidates) still
            # has real headroom for the cap to matter, unlike NATURAL.
    "natural": 50,
    "engineered": 20,
    "plateau": 50,
}
MIN_DISPLAY_MW = {  # user's call (2026-09-03): don't show a project this small — a
                     # display-only floor, applied after ranking so it doesn't change
                     # which candidate wins for a given lake, just whether the map/
                     # docs/candidates_<mode>.geojson bothers showing it. The full,
                     # unfiltered ranking still goes to data/candidates_<mode>_all.
                     # geojson (internal reference, not published) — nothing here
                     # changes what best_new_site()/best_plateau_site() themselves
                     # consider a valid candidate, only what gets drawn.
                     # Split per-mode (2026-09-03, same day): "for natural allow a
                     # smaller mw given it is cheaper to build" — NATURAL needs no dam/
                     # embankment at all (bowl_required already guarantees containment),
                     # so a small project is still worth building where ENGINEERED/
                     # PLATEAU's wall/dike cost means small ones usually aren't. 10MW is
                     # the widely-used regulatory "small hydro" cutoff (EU, China) —
                     # below that, treat it as noise; above it, a cheap natural bowl is
                     # worth showing even at a fraction of ENGINEERED/PLATEAU's floor.
    "natural": 10,
    "engineered": 50,
    "plateau": 50,
}
MIN_VOLUME_RATIO_TO_LAKE = {  # user's call (2026-09-03): don't show a project unless
                     # the new site's own physical capacity (basin_volume_m3, NOT the
                     # usable/capped volume_m3 — comparing the CAPPED figure against
                     # the very lake it's capped to would fail by definition for every
                     # lake-limited candidate, which is most of them) is at least this
                     # many times the existing lake's own volume. Unknown lake volume
                     # -> excluded too (can't confirm the ratio, so don't claim it).
                     # Split per-mode (2026-09-03, same day): "2x-lake volume rati[o],
                     # if the new lake is smallert that is still good" for NATURAL — a
                     # natural bowl smaller than the paired lake is still worth showing
                     # since it costs almost nothing to add (no dam/embankment build);
                     # the ratio floor stays for ENGINEERED, where a big lake paired
                     # with a small new reservoir isn't worth the wall cost.
                     # PLATEAU dropped to 0.0 too (2026-09-03, later same day): after
                     # widening PLATEAU_SEARCH_RADIUS_M, the algorithm found a genuine
                     # candidate at real Tarnița (lake 169355) matching the real
                     # Lăpuștești project closely (11.6M m^3 vs published 10.0M, 1110MW
                     # vs published ~1000MW, head 538m vs published 563.5m) — but that
                     # candidate's own ratio is basin_volume_m3 11.6M / lake_volume_m3
                     # 74.0M = 0.157. Any floor above ~0.157 would exclude PLATEAU's own
                     # flagship real-world precedent, the exact project this mode is
                     # grounded in — not a judgment call at that point, the 2.0 bar was
                     # just wrong for this mode. Real diking cost (unlike NATURAL) is
                     # still real, but that's what MIN_DISPLAY_MW's 50MW floor already
                     # screens for; no non-zero ratio value here is better-grounded than
                     # 0, so matched NATURAL's.
    "natural": 0.0,
    "engineered": 2.0,
    "plateau": 0.0,
}

MAX_DAM_LENGTH_M = 300  # 200 -> 300 (user's call, 2026-09-03): raised after asking for
                          # real practical grounding rather than a round-number guess.
                          # Checked two real dams in this same river cascade (see
                          # DATA_SOURCES.md): Tarnița's own dam is 237m crest length,
                          # Someșul Cald's is 130m — 300m covers both with real margin.
                          # Considered capping by concrete volume instead (the user's
                          # other suggestion) but found no clean, comparable real figure
                          # to calibrate it against — the one real number available (the
                          # full Tarnița-Lăpuștești CHEAP scheme's 16,000 m^3 surface +
                          # 192,000 m^3 underground concrete) covers the WHOLE project
                          # (tunnels, underground powerhouse, everything), not a wall
                          # alone, so it's not a like-for-like comparison to
                          # dam_construction.py's wall-only estimate. Left for later if a
                          # cleaner reference turns up — not guessed at now. Also doubles
                          # as the effective search distance dam_line_endpoints samples
                          # for a valid crossing — a basin whose real valley is wider
                          # than this correctly reports "no dam axis found" rather than
                          # drawing an artificially-shortened, misleading line/estimate.
DAM_LINE_HALF_LENGTH_M = (80, MAX_DAM_LENGTH_M / 2)  # (min, max) half-length — clamp
                                      # for the illustrative dam line drawn on the map;
                                      # not derived from real valley cross-sections
UNREALISTIC_DAM_PROBE_HALF_M = 1000  # diagnostic-only wide probe (see best_new_site) —
                                       # tells "no valley shape here at all" apart from
                                       # "there's a valley, just wider than
                                       # MAX_DAM_LENGTH_M allows" for a candidate that
                                       # found no axis at the practical length. 1000m
                                       # picked to comfortably exceed real large dams
                                       # (Tarnița's own 237m crest, Someșul Cald's 130m —
                                       # see DATA_SOURCES.md) without reaching all the
                                       # way to ENGINEERED's own max_basin_radius_m
                                       # (2000m), which would just relabel "no valley at
                                       # all" candidates as "unrealistic" too.
DAM_LINE_ANGLE_STEPS = 8  # candidate dam-axis orientations tried per site (0-157.5deg,
                           # 22.5deg apart — a line and its 180deg-rotated self are the same line)
DAM_LINE_MIN_RISE_M = 5  # both ends of the dam axis must be at least this much higher than
                          # the seed — see dam_line_endpoints' docstring for why

MIN_WALL_FRACTION = 0.6  # ENGINEERED's containment gate — see basin_wall_fraction()'s
                          # docstring for calibration and its known clustering-at-the-
                          # threshold caveat

# --- PLATEAU mode config ---------------------------------------------------
# A third category, distinct from both NATURAL and ENGINEERED: a reservoir built by
# diking the perimeter of genuinely flat/gently-rolling high ground, the way the real
# Lăpuștești upper reservoir actually is (see reference_projects.py and module
# docstring) — NOT a natural depression (NATURAL's whole premise) and NOT a single
# wall across a valley (ENGINEERED's). Every number below is grounded in that one real,
# citable precedent rather than guessed, since this project has no other real plateau
# reservoir to calibrate against: "Studiu de Fundamentare — Centrala cu Acumulare prin
# Pompaj Tarnița-Lăpuștești" (CNSP, 2021), pg. 68-69 — see DATA_SOURCES.md, 2026-09-02,
# for the full citation and the numbers quoted directly from it.
PLATEAU_MAX_SLOPE_GRADE = 0.15  # ~8.5deg — must look like genuinely buildable, gently
                                 # rolling ground, not a hillside. Started at 0.3
                                 # (~17deg) and tightened after checking real output:
                                 # that value found a candidate for 29% of a sample of
                                 # lakes — far more than NATURAL (<1%) or ENGINEERED
                                 # (~9%) find, which doesn't match how rare a genuine
                                 # plateau should be. Real Lăpuștești isn't billiard-
                                 # table flat either (its own footprint has ~34m of
                                 # natural relief over roughly its own radius — see
                                 # PLATEAU_MAX_RELIEF_M), just far gentler than
                                 # MAX_SLOPE_GRADE=1.0 (45deg, ENGINEERED's bar)
PLATEAU_MAX_RELIEF_M = 40.0  # how far a candidate cell's elevation may differ from the
                               # seed's and still count as "the same plateau" — matches
                               # the real embankment height below, not a separate guess
PLATEAU_EMBANKMENT_HEIGHT_M = 40.0  # design assumption for volume (footprint_area *
                                      # this — see plateau_footprint()), NOT a natural
                                      # flood-fill result: a diked plateau pond has no
                                      # natural water level to speak of. The real
                                      # Lăpuștești dike is "până la 40 m" (up to 40m) in
                                      # cross-section — using that exact figure, not a
                                      # rounder or more convenient number.
PLATEAU_MAX_RADIUS_M = 450  # real Lăpuștești's own lake surface (388,750 m^2, same
                              # source) has an equivalent circular radius of ~350m; a
                              # first pass doubled this to 700m "for search headroom"
                              # and, combined with the too-loose slope grade above,
                              # produced footprints of 65-155ha — 2-4x the real
                              # reference's own 38.9ha. 450m (modest headroom, not 2x)
                              # keeps candidates in the same ballpark as the one real
                              # precedent this mode has to calibrate against
MAX_PLATEAU_CELLS = 12000  # hard compute guard, same role and same value as volumes.
                             # MAX_BASIN_CELLS — genuinely flat terrain could otherwise
                             # keep growing a long way before hitting PLATEAU_MAX_RADIUS_M
PLATEAU_WINDOW_PX = 9  # the flat-window seed check (candidate must be flat over a real
                         # neighborhood, not just its own pixel) — smaller than NATURAL's
                         # bowl_window_px=19 deliberately: flatness is a much noisier
                         # per-pixel DEM signal than "locally lowest," so a window this
                         # wide already filters effectively without over-shrinking the
                         # candidate pool the way copying bowl_window_px's size would
PLATEAU_SEED_STRIDE_PX = 5  # matches ENGINEERED's coarse-grid sampling reasoning — not
                              # every qualifying pixel needs its own flood-fill
PLATEAU_MAX_CANDIDATES = 40  # matches ENGINEERED's shortlist cap, same reasoning
PLATEAU_MIN_FLAT_FRACTION = 0.8  # most of the discovered footprint, not just the seed,
                                    # must itself be genuinely flat — see
                                    # plateau_flat_fraction(). Higher than ENGINEERED's
                                    # MIN_WALL_FRACTION=0.6 deliberately: an ENGINEERED
                                    # basin legitimately has an open downstream edge by
                                    # design, but a plateau footprint that's mostly NOT
                                    # flat isn't a plateau candidate at all, it leaked
                                    # onto a slope — there's no equivalent "supposed to
                                    # be open" edge to excuse it here.
PLATEAU_SEARCH_RADIUS_M = 3000  # own radius, separate from SEARCH_RADIUS_M (user's call,
                                  # 2026-09-03: "tune the algoritm until it also finds
                                  # the tarnita lapus naturaly, for plateu searches").
                                  # SEARCH_RADIUS_M=2000 was calibrated for NATURAL/
                                  # ENGINEERED, where the new site has to be close enough
                                  # for a short dam/bowl adjacent to the lake itself — but
                                  # a diked PLATEAU reservoir sits on high ground that can
                                  # legitimately be farther out, and 2000m was silently
                                  # excluding the mode's own real-world precedent. Checked
                                  # directly against real Tarnița (lake 169355): within
                                  # 2000m, nothing above 886.5m passes PLATEAU's own
                                  # flatness test — terrain climbs too steeply close in.
                                  # Widening the DEM window to 8000m found a genuine,
                                  # flat_fraction=1.0, 15.8ha plateau at 1007-1034m
                                  # elevation, 2718-2800m due west of the lake (same
                                  # latitude as the lake center, matching the real
                                  # Lăpuștești village's own direction and the CNSP
                                  # study's "left mountainside adjacent to the
                                  # reservoir") — head from there (541.8m) lands within
                                  # 4% of the real published 563.5m. 3000m gives that
                                  # real cluster (2718-2800m out) comfortable margin
                                  # without reaching into the unrelated, much taller
                                  # terrain further out (a different, higher summit
                                  # cluster starts appearing past ~4900m in a different
                                  # compass direction — not this same real feature, so
                                  # deliberately left outside this radius). See
                                  # DATA_SOURCES.md for the full investigation.
PLATEAU_SEARCH_WINDOW_RADIUS_M = PLATEAU_SEARCH_RADIUS_M + 400  # same margin-past-the-
                                  # candidate-cutoff reasoning as SEARCH_WINDOW_RADIUS_M
                                  # above (untruncated neighborhood for the flatness/
                                  # slope checks at a candidate near the radius edge)


@dataclass(frozen=True)
class SearchMode:
    name: str
    bowl_required: bool
    max_dam_height_m: float
    max_basin_radius_m: float
    bowl_window_px: int = 5  # only used when bowl_required — real, physical size of this
                              # window matters (see NATURAL below); it's not just a knob
    seed_stride_px: int = 3  # only used when not bowl_required (compute guard)
    max_volume_candidates: int = 50  # flood-fills per lake — the real per-lake compute cap
    seed_radius_m: float = SEARCH_RADIUS_M  # how far a SEED may sit from the lake (the
        # base_mask distance filter in best_new_site()) — separate from max_basin_radius_m
        # (how far the FLOOD may then grow from that seed). Defaults to the shared
        # SEARCH_RADIUS_M; NATURAL overrides it (see below) after finding a real bowl
        # just past the shared radius. ENGINEERED deliberately keeps the shared default —
        # widening it once already surfaced a much bigger, pre-existing containment
        # problem (see SEARCH_WINDOW_RADIUS_M's docstring above) that a margin tweak can't
        # fix on its own.


NATURAL = SearchMode(
    name="natural",
    bowl_required=True,
    # 19px (~500m at this DEM's typical ~26m pixel size) — deliberately matches
    # max_basin_radius_m below, not a smaller, cheaper window. Was 5 (~130m) until a user
    # looked at two "bowls" on the map and found them nonsensical: #5 (lake 170958) turned
    # out to sit on a shoulder that RISES in 7 of 8 sampled directions (up to +30-60m
    # within 300-500m) — not a bowl bottom at all, just the locally-lowest of its
    # immediate ~130m neighbors; #6 (lake 1352457) was worse — the flood painted a
    # ~950m-wide roughly circular patch straddling a seed that rises in 7 of 8 directions
    # too, with the one real dip (visible on the map, per the user) sitting well outside
    # that 130m window to the south. A 5px window can't tell "locally lowest" from
    # "genuinely the lowest point over the whole area the flood is about to claim" —
    # checked directly against all 95 of the previous run's candidates: only 19% would
    # still qualify at a ~240m window, only 4% at ~500m. That 4% isn't a bug in the new
    # filter, it's the honest number — see module docstring, "these are rare by nature."
    # What (mostly) survives instead: broad, gently-sloping high-elevation terrain — real
    # locally-lowest points, just not classic steep-walled cirques — hence "plateau
    # depression" rather than "bowl" in the mode's own label and map legend.
    bowl_window_px=19,
    max_dam_height_m=60,
    max_basin_radius_m=500,
    # 2000 -> 2500 (user's call, 2026-09-03: "i believe near lesu there is a very good
    # natural spoot"). Checked directly rather than assumed: NATURAL's own bowl test
    # (local minimum over bowl_window_px=19, ~500m) finds 537 qualifying pixels in the
    # window around lake 1352457 (Leșu) -- 527 of them sit inside the lake's own
    # footprint (a lake IS the local minimum of its own basin, expected), and of the 10
    # real, external ones, every single one sits BEYOND the old SEARCH_RADIUS_M=2000
    # (2307-3070m out). Ran basin_volume() on the closest/strongest one directly: seed
    # at 22.54605E/46.81261N, 841m elevation, 2307m from the lake -- a real, POUR-POINT-
    # BOUNDED (not radius/height-capped) basin holding 12.27M m^3, water level 900.9m,
    # head 347.4m, ~269MW. A genuine, sizeable natural bowl, just past the old cutoff --
    # exactly what the user suspected. 2500m gives it clear margin without reaching the
    # weaker candidates further out (31-119MW, 2408-3070m) that this investigation also
    # found but didn't specifically motivate widening for.
    seed_radius_m=2500,
)

# Calibrated to the real Tarnița dam (97m) and Tarnița lake (2.2km^2, radius ~840m) — see
# module docstring. Not bowl-restricted: a dam can be built across any qualifying valley point,
# which means far more lakes have *some* candidate than NATURAL — max_volume_candidates and
# seed_stride_px are cut down accordingly to keep total runtime in the same ballpark (each
# flood-fill here also covers ~9x the area of a NATURAL one, radius^2, so it's disproportionately
# more expensive per-candidate too — see MAX_BASIN_CELLS in volumes.py).
# max_basin_radius_m = SEARCH_RADIUS_M (not a smaller sub-limit, as an earlier 1500 was): the
# flood-fill can never reach past the loaded DEM window anyway, so capping it any tighter than
# that window just cuts the flood off early for no benefit — confirmed this session as a real
# accuracy problem (11 of the top 20 candidates hadn't even reached max_dam_height_m yet,
# basin_bounded=False, meaning volume_m3 was an underestimate, not a confident figure).
ENGINEERED = SearchMode(
    name="engineered",
    bowl_required=False,
    seed_stride_px=5,
    max_dam_height_m=100,
    max_basin_radius_m=SEARCH_RADIUS_M,
    # Raised from 15: the containment requirement (see best_new_site — a candidate now
    # has to show real terrain rising on both sides, not just be reachable) rejects a lot
    # of the old shortlist, so a bigger pool is needed to still find one that qualifies.
    # dam_line_endpoints() itself is cheap (8 direction samples, no flood-fill), so this
    # mainly costs more basin_volume() calls, not a proportionally bigger runtime hit.
    max_volume_candidates=40,
)


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """Returns (meters per degree of longitude, meters per degree of latitude) at lat_deg."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_deg))
    return m_per_deg_lon, m_per_deg_lat


def dam_line_endpoints(row: int, col: int, elev: np.ndarray, valid: np.ndarray,
                        pixel_dx_m: float, pixel_dy_m: float, surface_area_m2: float,
                        lon_grid: np.ndarray, lat_grid: np.ndarray,
                        m_per_deg_lon: float, m_per_deg_lat: float,
                        half_length_override_m: float | None = None):
    """A short illustrative line through the seed (the dam site — see basin_volume()'s
    docstring): tries DAM_LINE_ANGLE_STEPS candidate orientations and picks the one
    where the REAL terrain rises on BOTH sides of the seed by at least
    DAM_LINE_MIN_RISE_M — i.e. the seed sits in an actual local dip along that axis, the
    way a real valley (or saddle) does, rather than partway up an open slope.

    Returns None if no orientation clears that bar. Not every candidate is a clean
    two-walled valley — many ENGINEERED candidates flood a chunk of hillside bounded
    only by our own MAX_BASIN_RADIUS_M / max_dam_height_m, not real valley walls on
    both sides — and for those there usually isn't a single short wall that would
    actually contain the water (a real design there would need a perimeter embankment,
    not one dam axis). Drawing a line anyway would misrepresent the site, so this
    reports "no dam axis found" instead.

    History — two things fixed this session, in order:
    1. The direction came from the local gradient's PERPENDICULAR, reasoning
       "perpendicular to slope = along the contour = where a dam runs". Backwards: a
       contour runs ALONG a valley (the flow direction); a dam has to CROSS that.
    2. Fixed to align WITH the gradient instead (plus a sign bug: np.gradient's row-axis
       output points south, not north, since DEM rows increase as latitude decreases).
       This was mathematically consistent but still wrong in practice: checked directly
       against real elevation profiles and found 7 of 8 sampled ENGINEERED candidates'
       "fixed" lines climbed monotonically end to end — no dip anywhere, just a straight
       line up a hillside. A single pixel's gradient only indicates the true
       valley-crossing direction where the site actually IS a valley; it doesn't detect
       whether that's even the case. This version checks real terrain in multiple
       directions and requires an actual dip, rather than inferring an answer from one
       point's local slope.

    Length (when an axis is found) is a heuristic guess from the basin's surface area,
    clamped to DAM_LINE_HALF_LENGTH_M — not a real cross-valley survey either way.

    half_length_override_m bypasses that clamp entirely when given — used by
    best_new_site() for exactly one diagnostic purpose: when the practical (clamped)
    search finds nothing, try again at a much larger half-length purely to tell "no
    valley shape here at all" apart from "there's a valley, just wider than
    MAX_DAM_LENGTH_M allows" (see unrealistic_dam_length_m there). Not used for the
    real illustrative line/concrete estimate either way — those stay capped at the
    practical length regardless of what this diagnostic finds.
    """
    height, width = elev.shape
    seed_elev = elev[row, col]

    if half_length_override_m is not None:
        half_length_m = half_length_override_m
    else:
        half_length_m = math.sqrt(surface_area_m2) * 0.5
        half_length_m = max(DAM_LINE_HALF_LENGTH_M[0], min(DAM_LINE_HALF_LENGTH_M[1], half_length_m))

    def sample(d_row_m: float, d_col_m: float) -> float | None:
        r = int(round(row + d_row_m / pixel_dy_m))
        c = int(round(col + d_col_m / pixel_dx_m))
        if not (0 <= r < height and 0 <= c < width) or not valid[r, c]:
            return None
        return float(elev[r, c])

    best = None
    for step in range(DAM_LINE_ANGLE_STEPS):
        angle = math.pi * step / DAM_LINE_ANGLE_STEPS  # 0..pi; angle+pi is the same line
        dx_east = math.cos(angle)
        dy_north = math.sin(angle)
        # East distance -> +col; north distance -> -row (DEM rows increase southward).
        d_row_m = -dy_north * half_length_m
        d_col_m = dx_east * half_length_m

        end1 = sample(d_row_m, d_col_m)
        end2 = sample(-d_row_m, -d_col_m)
        if end1 is None or end2 is None:
            continue
        rise = min(end1, end2) - seed_elev
        if best is None or rise > best[0]:
            best = (rise, dx_east, dy_north)

    if best is None or best[0] < DAM_LINE_MIN_RISE_M:
        return None
    _, dx_east, dy_north = best

    lon0, lat0 = lon_grid[row, col], lat_grid[row, col]
    start = (
        lon0 - dx_east * half_length_m / m_per_deg_lon,
        lat0 - dy_north * half_length_m / m_per_deg_lat,
    )
    end = (
        lon0 + dx_east * half_length_m / m_per_deg_lon,
        lat0 + dy_north * half_length_m / m_per_deg_lat,
    )
    return start, end


def basin_wall_fraction(visited: np.ndarray, elev: np.ndarray, valid: np.ndarray,
                         seed_row: int, seed_col: int, water_level: float,
                         pixel_dx_m: float, pixel_dy_m: float, max_basin_radius_m: float,
                         min_wall_rise_m: float = 10.0) -> float:
    """Real containment metric, using the basin's OWN flooded footprint (visited, from
    basin_volume()) — not dam_line_endpoints' short, fixed +/-400m probe from the seed,
    which this replaces as ENGINEERED's containment gate (see module docstring's
    ENGINEERED section and DATA_SOURCES.md, 2026-09-02, for why: it can be fooled by a
    small local bump within 400m of the seed while the basin behind it — which can be
    1-2km across — sprawls across genuinely open terrain the short probe never reaches).

    For every boundary cell of the flooded basin (a visited cell with a non-visited
    neighbor), classifies that neighbor as one of:
      - budget-limited: excluded only because it's past our own max_basin_radius_m cap
        (not because real terrain stops there) — not evidence either way, same
        reasoning as basin_bounded in best_new_site(). max_dam_height_m does NOT need
        its own carve-out here: any neighbor excluded specifically for being too tall
        (elev > seed_elev + max_dam_height_m) is, by that same fact, always >=
        water_level (which never exceeds seed_elev + max_dam_height_m) — so it already
        and correctly falls out as a wall below, not something needing separate handling.
        First version of this function DID give it a separate carve-out, discarding it
        as "ambiguous" instead — that silently threw away the strongest wall evidence
        available (a real height-capped basin's neighbor is almost always well above the
        cap) and made this check reject nearly everything, including genuinely contained
        basins. Caught by testing against a known-good real candidate (a previous top-1
        ENGINEERED result) and finding 0 wall_cells reported for it — physically
        impossible for a basin with any real terrain around it at all.
      - a wall: elevation at or above water_level - min_wall_rise_m — real terrain that
        would actually hold the water back there.
      - open: elevation below that — the flood stopped there only because of
        basin_volume()'s own downhill-tolerance rule (elev >= seed_elev - 2m), not
        because the terrain closes; water would really keep flowing out here.
    Returns wall_cells / (wall_cells + open_cells) — 1.0 when the boundary is ENTIRELY
    budget-limited (never found real terrain on any side either way; that ambiguity is
    what basin_bounded=False already flags separately, as search-limited rather than
    open sprawl).

    A real dam only needs the valley SIDES walled — the downstream end is deliberately
    open (that's where the dam itself goes, artificial not natural), and the upstream
    end may run out to max_basin_radius_m without ever finding a real close
    (budget-limited, already excluded above) or may just keep sloping gently for a while
    before it does. So this is graded, not a strict "must be walled all around" check.

    best_new_site() applies its own threshold as the actual pass/fail gate — currently
    0.6, raised from an initial 0.5. That first value was chosen from two real,
    contrasting candidates: a known-bad ridge-nose seed (catastrophic 100-288m drops in
    most sampled directions, see best_new_site()'s comment) scored 0.14; a plausible
    real valley-dam candidate (lake 1360316's previous top-1 ENGINEERED result) scored
    0.57. It also produced a clustering effect worth understanding before trusting a
    "passed" result too far: because best_new_site() picks the highest-MW candidate
    among everything that clears the gate, and a less-contained basin can generally grow
    bigger (more MW) right up until it fails, winning candidates don't land safely above
    the threshold — they cluster tightly AT it (a full pipeline run at 0.5 put all 20 of
    ENGINEERED's top candidates at 0.50-0.58). That clustering is inherent to any fixed
    threshold, not evidence 0.5 itself was wrong — but a user directly checking one of
    those 0.50 candidates (lake 169296, "#10") on real satellite imagery found a dam
    site sitting on what's visibly a mountain edge, not a valley. Checked why: 0.54 is
    the highest wall_fraction achievable ANYWHERE in that lake's entire 2km search
    radius — meaning 0.5 was letting through lakes with no real site at all, not just
    ranking real sites tightly. Raised to 0.6 for that reason (excludes lake 169296
    entirely, correctly returning no candidate there) — this does NOT eliminate the
    clustering effect itself (a full re-run should be expected to again show winners
    hugging whatever the current threshold is), so best_new_site() still stores the raw
    fraction (see wall_fraction in its return dict) rather than just the pass/fail
    boolean, and a "passed" result should still be read as "not obviously fake," not
    "confidently real" — this metric alone can't fully replace looking at the actual
    place.
    """
    height, width = elev.shape
    pixel_margin = max(pixel_dx_m, pixel_dy_m) * 1.5  # rounding room at the radius cap

    wall_cells = 0
    open_cells = 0
    for r, c in zip(*np.where(visited)):
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < height and 0 <= nc < width):
                continue  # array edge — ambiguous, doesn't count either way
            if visited[nr, nc] or not valid[nr, nc]:
                continue
            dist_m = math.hypot((nr - seed_row) * pixel_dy_m, (nc - seed_col) * pixel_dx_m)
            if dist_m > max_basin_radius_m - pixel_margin:
                continue  # radius cap, not sprawl evidence
            if elev[nr, nc] >= water_level - min_wall_rise_m:
                wall_cells += 1
            else:
                open_cells += 1

    total = wall_cells + open_cells
    if total == 0:
        return 1.0  # nothing but budget-limited/edge boundary — can't call it open
    return wall_cells / total


def plateau_footprint(elev: np.ndarray, valid: np.ndarray, slope: np.ndarray,
                       seed_row: int, seed_col: int, pixel_dx_m: float, pixel_dy_m: float,
                       max_relief_m: float, max_radius_m: float) -> tuple[float, np.ndarray]:
    """How much contiguous, genuinely flat ground actually surrounds a PLATEAU seed —
    real terrain data, not a flood-fill volume model dressed up as one. A diked plateau
    reservoir has no natural water level to flood up to (that's the whole point of
    PLATEAU mode — see its config block above): this is a plain 4-connected BFS, joining
    a neighbor cell only if its slope stays under PLATEAU_MAX_SLOPE_GRADE and its
    elevation stays within max_relief_m of the seed (a real plateau isn't billiard-table
    flat — Lăpuștești's own footprint has real relief across it too, see
    PLATEAU_MAX_RELIEF_M — but it should be bounded, not the tens-to-hundreds of meters
    a valley or mountainside would show). Returns (footprint_area_m2, visited boolean
    mask) — deliberately the same shape of return as basin_volume()'s footprint half, so
    plateau_footprints_geodataframe() can reuse the same polygon-vectorizing code.
    """
    height, width = elev.shape
    seed_elev = elev[seed_row, seed_col]
    pixel_area_m2 = pixel_dx_m * pixel_dy_m

    visited = np.zeros_like(valid, dtype=bool)
    visited[seed_row, seed_col] = True
    queue = deque([(seed_row, seed_col)])
    count = 1

    while queue:
        if count >= MAX_PLATEAU_CELLS:
            break
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < height and 0 <= nc < width) or visited[nr, nc] or not valid[nr, nc]:
                continue
            if abs(elev[nr, nc] - seed_elev) > max_relief_m:
                continue
            if slope[nr, nc] > PLATEAU_MAX_SLOPE_GRADE:
                continue
            dist_m = math.hypot((nr - seed_row) * pixel_dy_m, (nc - seed_col) * pixel_dx_m)
            if dist_m > max_radius_m:
                continue
            visited[nr, nc] = True
            count += 1
            queue.append((nr, nc))

    return count * pixel_area_m2, visited


def plateau_flat_fraction(visited: np.ndarray, slope: np.ndarray) -> float:
    """What fraction of a PLATEAU candidate's OWN discovered footprint is genuinely
    flat (slope <= PLATEAU_MAX_SLOPE_GRADE) — the plateau analog of
    basin_wall_fraction(), but checking the footprint's OWN interior rather than its
    boundary, since flatness (not a natural wall) is what makes a plateau candidate
    real here. Every visited cell already passed this test to be included by
    plateau_footprint() in the first place, so in principle this should always read
    1.0 — kept as a real, computed check anyway (not hardcoded to 1.0) so a future
    change to plateau_footprint()'s own growth rule can't silently stop meaning what
    this claims it means without this number changing to reveal it.
    """
    if not visited.any():
        return 0.0
    return float((slope[visited] <= PLATEAU_MAX_SLOPE_GRADE).mean())


def best_plateau_site(lake_lon: float, lake_lat: float, lake_elev: float,
                       lake_volume_m3: float | None, lake_polygon=None) -> dict | None:
    """PLATEAU's version of best_new_site() — kept as a separate function rather than
    folded into SearchMode/best_new_site() because the seed test (genuinely flat over a
    window, not locally lowest or just any qualifying point) and the volume model
    (footprint_area * a fixed design depth, not basin_volume()'s natural flood-fill
    integral — see plateau_footprint()) are both different enough that sharing the one
    function would need more branching than it saves. Reuses the same shared pieces as
    best_new_site() (load_elevation_window, meters_per_degree, the lake-polygon
    exclusion logic, storage_capacity_mwh/realistic_power_mw) and returns a dict with
    the same keys to_geodataframe() already expects — including ones that don't apply
    here (wall_fraction, unrealistic_dam_length_m, dam_line, concrete_volume_m3, all
    None; dam_height_m repurposed as the embankment height) so the map/CLI code paths
    don't need PLATEAU-specific branches downstream.
    """
    m_per_deg_lon, m_per_deg_lat = meters_per_degree(lake_lat)

    window = load_elevation_window(lake_lon, lake_lat, PLATEAU_SEARCH_WINDOW_RADIUS_M)
    if window is None:
        return None
    elev, valid, transform, lon_1d, lat_1d = window
    lon_grid, lat_grid = np.meshgrid(lon_1d, lat_1d)

    dx_m = (lon_grid - lake_lon) * m_per_deg_lon
    dy_m = (lat_grid - lake_lat) * m_per_deg_lat
    distance_grid = np.sqrt(dx_m**2 + dy_m**2)

    pixel_dx_m = abs(transform.a) * m_per_deg_lon
    pixel_dy_m = abs(transform.e) * m_per_deg_lat

    within_lake_mask = compute_within_lake_mask(
        elev.shape, transform, lake_polygon, distance_grid, pixel_dx_m, pixel_dy_m
    )

    fill_value = np.nanmax(elev[valid]) + 1.0
    elev_filled = np.where(valid, elev, fill_value)
    grad_y, grad_x = np.gradient(elev_filled, pixel_dy_m, pixel_dx_m)
    slope = np.sqrt(grad_x**2 + grad_y**2)

    head_grid = np.abs(elev - lake_elev)

    base_mask = (
        valid
        & ~within_lake_mask
        & (distance_grid <= PLATEAU_SEARCH_RADIUS_M)
        & (head_grid >= MIN_HEAD_M)
        & (slope <= PLATEAU_MAX_SLOPE_GRADE)
    )
    # Flat over a real neighborhood, not just the one pixel — the same "check a window,
    # not a point" idea as NATURAL's bowl_window_px, applied to flatness instead of
    # elevation minimum. Uses the window's MEAN slope, not maximum_filter's "every
    # single pixel must pass" — checked against real terrain and found that too brittle:
    # near Lake Leșu (Bihor), 698 individual pixels passed the per-pixel slope test, but
    # the all-must-pass window check failed EVERY one of them (0 candidates) — a single
    # noisy or genuinely-but-narrowly steep DEM cell anywhere in a 9x9 window is enough
    # to fail it, even on ground that's clearly, broadly flat. The mean-based version
    # recovered 22 real candidates at that same location. Still real terrain, not DEM
    # noise being ignored: plateau_footprint()'s own per-cell growth (below) still
    # requires every individual cell it adds to pass the same strict slope bar, so a
    # genuinely rough patch inside an otherwise-flat area still correctly stops growth
    # there — this only relaxes which SEED gets a chance to grow from, not what counts
    # as flat ground once growing.
    mean_slope_nearby = uniform_filter(slope, size=PLATEAU_WINDOW_PX, mode="nearest")
    stride_mask = np.zeros_like(base_mask)
    stride_mask[::PLATEAU_SEED_STRIDE_PX, ::PLATEAU_SEED_STRIDE_PX] = True
    candidate_mask = base_mask & (mean_slope_nearby <= PLATEAU_MAX_SLOPE_GRADE) & stride_mask

    if not candidate_mask.any():
        return None

    prelim_score = np.where(candidate_mask, head_grid / np.maximum(distance_grid, 1.0), -np.inf)
    candidate_rows, candidate_cols = np.where(candidate_mask)
    order = np.argsort(prelim_score[candidate_rows, candidate_cols])[::-1]
    shortlist = list(zip(candidate_rows[order], candidate_cols[order]))[:PLATEAU_MAX_CANDIDATES]

    best = None
    for row, col in shortlist:
        footprint_area_m2, visited = plateau_footprint(
            elev, valid, slope, row, col, pixel_dx_m, pixel_dy_m,
            PLATEAU_MAX_RELIEF_M, PLATEAU_MAX_RADIUS_M,
        )
        basin_volume_m3 = footprint_area_m2 * PLATEAU_EMBANKMENT_HEIGHT_M
        volume_m3 = usable_cycling_volume_m3(basin_volume_m3, lake_volume_m3)
        if volume_m3 < MIN_VOLUME_M3:
            continue

        flat_fraction = plateau_flat_fraction(visited, slope)
        if flat_fraction < PLATEAU_MIN_FLAT_FRACTION:
            continue

        # Real bug found this session (2026-09-03): head must be the difference between
        # the two reservoirs' own WATER SURFACES (that's what actually drives the
        # turbines), not between the new site's bare ground elevation and the existing
        # lake's surface. head_grid (used above only for the cheap MIN_HEAD_M
        # pre-filter/shortlist ranking, where water_level isn't known yet) uses ground
        # elevation and was leaking into the FINAL reported head_m too — for PLATEAU,
        # site_elev is the ground under the future embankment, not the pond's own
        # surface once diked to PLATEAU_EMBANKMENT_HEIGHT_M.
        site_elev = float(elev[row, col])
        water_level_m = site_elev + PLATEAU_EMBANKMENT_HEIGHT_M
        head_m = head_from_water_levels(water_level_m, lake_elev)
        storage_mwh = storage_capacity_mwh(head_m, volume_m3)
        power_mw, implied_flow_m3_s, flow_limited = realistic_power_mw(storage_mwh, head_m, volume_m3)
        if best is None or power_mw > best["score"]:
            best = {
                "site_lon": float(lon_grid[row, col]),
                "site_lat": float(lat_grid[row, col]),
                "site_elevation_m": site_elev,
                "head_m": head_m,
                "distance_m": float(distance_grid[row, col]),
                "basin_volume_m3": basin_volume_m3,
                "volume_m3": volume_m3,
                "lake_volume_m3": lake_volume_m3,
                # volume_m3 < basin_volume_m3 directly (not re-deriving
                # MAX_LAKE_DRAWDOWN_FRACTION * lake_volume_m3 here) so this can't drift
                # out of sync with whatever usable_cycling_volume_m3() actually did.
                "limited_by_existing_lake": (
                    lake_volume_m3 is not None and lake_volume_m3 > 0
                    and volume_m3 < basin_volume_m3
                ),
                "surface_area_m2": footprint_area_m2,
                # Not a natural flood result (there's no water here to flood) — the
                # design water level implied by diking to PLATEAU_EMBANKMENT_HEIGHT_M.
                "water_level_m": water_level_m,
                "wall_fraction": None,  # not applicable — see flat_fraction instead
                "unrealistic_dam_length_m": None,  # not applicable — see dam_length_m
                "flat_fraction": flat_fraction,
                "storage_mwh": storage_mwh,
                "implied_flow_m3_s": implied_flow_m3_s,
                "flow_limited": flow_limited,
                "score": power_mw,
                "direction": "higher" if site_elev > lake_elev else "lower",
                "dam_line": None,  # a plateau needs a PERIMETER dike, not a crossing —
                                     # dam_line_endpoints' whole model doesn't apply
                                     # (see DATA_SOURCES.md, 2026-09-02, on why the real
                                     # Lăpuștești's 2715m ring dike isn't comparable to
                                     # a short valley-dam wall)
                "dam_height_m": PLATEAU_EMBANKMENT_HEIGHT_M,  # a real design figure
                                                                 # here (see config block
                                                                 # above), not a flood
                                                                 # result like the other
                                                                 # two modes report
                "dam_length_m": None,  # would be the visited footprint's own perimeter,
                                         # not computed (no concrete-volume estimate
                                         # exists for a ring dike in this project either
                                         # — dam_construction.py assumes a short wall)
                "concrete_volume_m3": None,
                # True (bounded) only if growth stopped for a real reason (relief or
                # slope) rather than exhausting the radius/cell budget — same
                # "did we hit our own compute limit vs find a genuine edge" idea as
                # basin_bounded elsewhere, just checked directly against the footprint's
                # own extent instead of a pour_point signal (plateau_footprint() has no
                # equivalent height-cap branch to report one from).
                "basin_bounded": footprint_area_m2 < math.pi * (PLATEAU_MAX_RADIUS_M ** 2) * 0.85,
            }

    return best


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


def compute_within_lake_mask(elev_shape: tuple, transform, lake_polygon, distance_grid: np.ndarray,
                              pixel_dx_m: float, pixel_dy_m: float) -> np.ndarray:
    """Which cells of a loaded window are too close to the existing lake's real
    shoreline to seed a candidate from — shared by best_new_site() and
    best_plateau_site() (previously duplicated inline in both). Real bug this replaced
    (2026-09-02): excluding only a circle around the lake's single anchor point (all
    lakes.geojson stores) — for a large or elongated lake the anchor can be a kilometer
    or more from the actual shoreline, letting a candidate seed sit right next to real
    water while reporting a large, reassuring "distance from lake". Fixed by
    rasterizing the actual HydroLAKES polygon and measuring true distance to it in real
    meters (distance_transform_edt, sampled in pixel_dy_m/pixel_dx_m so it isn't
    distorted by non-square pixels) — falls back to a circle around the window's own
    center (what distance_grid is already measured from) only if no polygon was found
    for this lake, which shouldn't normally happen since every lake here comes from the
    same HydroLAKES source.
    """
    if lake_polygon is not None:
        lake_cell_mask = geometry_mask([lake_polygon], out_shape=elev_shape, transform=transform, invert=True)
        if lake_cell_mask.any():
            dist_to_lake_m = distance_transform_edt(~lake_cell_mask, sampling=(pixel_dy_m, pixel_dx_m))
            return dist_to_lake_m < LAKE_EXCLUSION_BUFFER_M
    return distance_grid < LAKE_EXCLUSION_BUFFER_M


def head_from_water_levels(new_site_water_level_m: float, lake_elev_m: float) -> float:
    """Head is the difference between the two reservoirs' own WATER SURFACES — see
    ReadmeAi.md's "How head is calculated" for the full explanation and the real bug
    (2026-09-03) this function's introduction fixed: head_m used to come from the new
    site's bare ground elevation instead, understating it by however tall the dam/
    embankment was (17-31% of head_m on real candidates checked). Pulled out as its own
    tiny, directly-testable function specifically because that bug was a one-line
    mistake with an outsized, easy-to-miss effect (MW scales directly with head) — a
    dedicated test for this one line is cheap insurance against it recurring.
    """
    return abs(new_site_water_level_m - lake_elev_m)


def best_new_site(lake_lon: float, lake_lat: float, lake_elev: float, lake_volume_m3: float | None,
                   mode: SearchMode, lake_polygon=None) -> dict | None:
    m_per_deg_lon, m_per_deg_lat = meters_per_degree(lake_lat)

    # mode.seed_radius_m + 400, not the flat SEARCH_WINDOW_RADIUS_M — same untruncated-
    # neighborhood margin (see SEARCH_WINDOW_RADIUS_M's own docstring), but keyed to
    # this mode's own seed radius so a seed near NATURAL's wider 2500m cutoff still
    # gets a full, unpadded neighborhood for its bowl/flood checks.
    window = load_elevation_window(lake_lon, lake_lat, mode.seed_radius_m + 400)
    if window is None:
        return None
    elev, valid, transform, lon_1d, lat_1d = window
    lon_grid, lat_grid = np.meshgrid(lon_1d, lat_1d)

    dx_m = (lon_grid - lake_lon) * m_per_deg_lon
    dy_m = (lat_grid - lake_lat) * m_per_deg_lat
    distance_grid = np.sqrt(dx_m**2 + dy_m**2)

    pixel_dx_m = abs(transform.a) * m_per_deg_lon
    pixel_dy_m = abs(transform.e) * m_per_deg_lat

    # Exclude the lake's own footprint — see compute_within_lake_mask()'s docstring for
    # the real bug this fixed (a user-flagged candidate reported 1273m from the lake by
    # its anchor point, but only 557m from the real shore) and why a flood can still end
    # up closer than this buffer once it starts growing (a separate, deliberately
    # not-yet-made fix).
    within_lake_mask = compute_within_lake_mask(
        elev.shape, transform, lake_polygon, distance_grid, pixel_dx_m, pixel_dy_m
    )

    fill_value = np.nanmax(elev[valid]) + 1.0
    elev_filled = np.where(valid, elev, fill_value)

    grad_y, grad_x = np.gradient(elev_filled, pixel_dy_m, pixel_dx_m)
    slope = np.sqrt(grad_x**2 + grad_y**2)

    head_grid = np.abs(elev - lake_elev)

    base_mask = (
        valid
        & ~within_lake_mask
        & (distance_grid <= mode.seed_radius_m)
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
        # visited: the flooded footprint — needed here now for basin_is_contained() (not
        # just thrown away like before); basin_footprints_geodataframe() still recomputes
        # its own copy for the final winner only, rather than carrying all of these around.
        basin_volume_m3, surface_area_m2, water_level_m, pour_point, visited = basin_volume(
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

        # For non-bowl modes (ENGINEERED), nothing yet guarantees this seed sits in a
        # real depression at all — bowl_required modes already have that guarantee via
        # is_bowl (a true local minimum, by construction, has terrain rising immediately
        # around it; near the exact bottom that rise can be too gentle for a short probe
        # to see, which is part of why bowl mode doesn't use this as a filter).
        #
        # Originally gated on dam_line_endpoints (a short, fixed +/-400m probe from the
        # seed) — confirmed this session that's not enough: checked EVERY candidate (not
        # just the shortlist) near one real lake and found 175 of 522 "passed" that probe
        # with basin_volume_m3 of 40-220 million m^3 over 1-4 km^2 — a small local bump
        # within 400m of the seed is enough to pass while the actual flooded footprint,
        # which can be 1-2km across, sprawls across open terrain the probe never reaches.
        # Directly confirmed this was already live in the shipped top-20: 5 of 20
        # candidates (basin_volume not capped by the existing lake, so it fed the
        # headline MW directly) dropped 240-443m within 1000m in 10-11 of 12 sampled
        # directions, yet had passed. basin_wall_fraction() replaces the gate with a
        # check against the basin's OWN actual footprint instead of a short ray — see
        # its docstring, including the clustering-at-the-threshold caveat found after
        # calibrating it: wall_fraction is kept in the result (below) for exactly that
        # reason. dam_line_endpoints is still used below, but only for the winning
        # candidate's illustrative dam-axis geometry/concrete estimate, the same
        # non-gating role it already had for NATURAL.
        wall_fraction = None
        if not mode.bowl_required:
            wall_fraction = basin_wall_fraction(
                visited, elev, valid, row, col, water_level_m,
                pixel_dx_m, pixel_dy_m, mode.max_basin_radius_m,
            )
            if wall_fraction < MIN_WALL_FRACTION:
                continue

        # Real bug found this session (2026-09-03): head must be the difference between
        # the two reservoirs' own WATER SURFACES (that's what actually drives the
        # turbines), not between the new site's bare ground elevation (the dam's own
        # foundation) and the existing lake's surface. head_grid (used above only for
        # the cheap MIN_HEAD_M pre-filter/shortlist ranking, before water_level_m is
        # known) uses ground elevation and was leaking into the FINAL reported head_m
        # too — understating it by exactly dam_height_m for every "higher" candidate
        # (checked: 17-31% of head_m on the current top candidates, not a rounding
        # error). basin_volume() already returns the real, flooded water_level_m above;
        # use that instead of re-reading the seed's own bare elevation.
        head_m = head_from_water_levels(water_level_m, lake_elev)
        storage_mwh = storage_capacity_mwh(head_m, volume_m3)
        power_mw, implied_flow_m3_s, flow_limited = realistic_power_mw(storage_mwh, head_m, volume_m3)
        if best is None or power_mw > best["score"]:
            site_elev = float(elev[row, col])
            # Not a filter for either mode now (see above — ENGINEERED's real gate is
            # basin_wall_fraction()) — just the illustrative axis/concrete-estimate
            # line, computed for the winning seed only.
            dam_line = dam_line_endpoints(
                row, col, elev, valid, pixel_dx_m, pixel_dy_m, surface_area_m2,
                lon_grid, lat_grid, m_per_deg_lon, m_per_deg_lat,
            )
            # When the practical-length search above found nothing, a second, wider
            # diagnostic probe distinguishes "no valley shape here at all" from "there's
            # a real valley, just wider than MAX_DAM_LENGTH_M" — the latter gets flagged
            # unrealistic_dam_length_m rather than silently looking identical to the
            # former in the output. Not used for dam_height_m/dam_length_m/
            # concrete_volume_m3 below — those stay None either way, since neither case
            # has a practical estimate to show.
            unrealistic_dam_length_m = None
            if dam_line is None:
                diagnostic_line = dam_line_endpoints(
                    row, col, elev, valid, pixel_dx_m, pixel_dy_m, surface_area_m2,
                    lon_grid, lat_grid, m_per_deg_lon, m_per_deg_lat,
                    half_length_override_m=UNREALISTIC_DAM_PROBE_HALF_M,
                )
                if diagnostic_line is not None:
                    (dl_lon1, dl_lat1), (dl_lon2, dl_lat2) = diagnostic_line
                    unrealistic_dam_length_m = math.hypot(
                        (dl_lon2 - dl_lon1) * m_per_deg_lon, (dl_lat2 - dl_lat1) * m_per_deg_lat
                    )
            # Dam height = how far the water rises above the dam site itself; dam length
            # = the illustrative dam_line's own length (see its docstring's caveats —
            # this inherits them, it's not a separate survey). No dam_line means no
            # concrete estimate either, for the same reason (e.g. NATURAL mode's seed
            # often has ~zero local slope, so there's no direction to draw a dam axis in).
            if dam_line is not None:
                dam_height_m = water_level_m - site_elev
                (dl_lon1, dl_lat1), (dl_lon2, dl_lat2) = dam_line
                dam_length_m = math.hypot(
                    (dl_lon2 - dl_lon1) * m_per_deg_lon, (dl_lat2 - dl_lat1) * m_per_deg_lat
                )
                concrete_volume_m3 = estimate_concrete_volume_m3(dam_height_m, dam_length_m)
            else:
                dam_height_m = dam_length_m = concrete_volume_m3 = None
            best = {
                "site_lon": float(lon_grid[row, col]),
                "site_lat": float(lat_grid[row, col]),
                "site_elevation_m": site_elev,
                "head_m": head_m,
                "distance_m": float(distance_grid[row, col]),
                "basin_volume_m3": basin_volume_m3,  # what the terrain could physically hold
                "volume_m3": volume_m3,  # what's actually usable — capped by the existing lake
                "lake_volume_m3": lake_volume_m3,
                # volume_m3 < basin_volume_m3 directly (not re-deriving
                # MAX_LAKE_DRAWDOWN_FRACTION * lake_volume_m3 here) so this can't drift
                # out of sync with whatever usable_cycling_volume_m3() actually did.
                "limited_by_existing_lake": (
                    lake_volume_m3 is not None and lake_volume_m3 > 0
                    and volume_m3 < basin_volume_m3
                ),
                "surface_area_m2": surface_area_m2,
                "water_level_m": water_level_m,
                # None for NATURAL (bowl_required already guarantees containment a
                # different way — see above); for ENGINEERED, the fraction of the
                # basin's own boundary that's real wall vs open terrain (see
                # basin_wall_fraction()'s docstring, including why "passed the >=
                # MIN_WALL_FRACTION gate" isn't the same as "comfortably contained" —
                # this raw number is what lets a reader tell the difference).
                "wall_fraction": wall_fraction,
                # Only set when dam_line is None AND a wider diagnostic probe found a
                # real axis anyway — "the valley here needs roughly this long a dam,
                # over the MAX_DAM_LENGTH_M practical limit" (see the comment above).
                "unrealistic_dam_length_m": unrealistic_dam_length_m,
                "storage_mwh": storage_mwh,
                "implied_flow_m3_s": implied_flow_m3_s,
                "flow_limited": flow_limited,
                "score": power_mw,
                "direction": "higher" if site_elev > lake_elev else "lower",
                "dam_line": dam_line,
                "dam_height_m": dam_height_m,
                "dam_length_m": dam_length_m,
                "concrete_volume_m3": concrete_volume_m3,
                # pour_point is None when the flood was cut off by our radius/cell caps
                # before ever reaching max_dam_height_m — that means basin_volume_m3 is a
                # lower bound (the true basin may be bigger). pour_point NOT None just means
                # the flood used its full height budget (see basin_volume()'s docstring for
                # why that's not the same as "confident, natural rim found").
                "basin_bounded": pour_point is not None,
            }

    return best


def load_lake_polygons(hydrolakes_shp_path) -> dict:
    """Real HydroLAKES polygon geometry, keyed by Hylak_id — loaded once for the whole
    country bbox (cheap: ~2200 polygons for Romania, well under a second, same file
    fetch_data.py already caches) rather than per-lake, since best_new_site() needs the
    real shoreline shape for its lake-exclusion buffer (see there for why the anchor
    point alone isn't enough) and every one of the 1100 lakes searched needs a lookup.
    """
    lakes_poly = gpd.read_file(hydrolakes_shp_path, bbox=BBOX)
    return dict(zip(lakes_poly["Hylak_id"], lakes_poly.geometry))


def run_mode(mode: SearchMode, lakes: gpd.GeoDataFrame, empirical_model: tuple[float, float],
             lake_polygons: dict) -> list[dict]:
    print(f"Scanning {len(lakes)} lakes, mode={mode.name} "
          f"(seed radius={mode.seed_radius_m:.0f}m, max dam height={mode.max_dam_height_m}m, "
          f"max basin radius={mode.max_basin_radius_m}m)...")
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

        lake_polygon = lake_polygons.get(lake["id"])
        result = best_new_site(lake.geometry.x, lake.geometry.y, elevation, lake_volume_m3, mode, lake_polygon)
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
                "mode": mode.name,  # lets passes_display_filters() apply mode-specific
                                     # thresholds (NATURAL's are looser — see MIN_DISPLAY_MW)
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


def run_plateau_mode(lakes: gpd.GeoDataFrame, empirical_model: tuple[float, float],
                      lake_polygons: dict) -> list[dict]:
    """PLATEAU's version of run_mode() — same loop, calls best_plateau_site() instead
    of best_new_site() since PLATEAU isn't a SearchMode (see best_plateau_site()'s
    docstring for why)."""
    print(f"Scanning {len(lakes)} lakes, mode=plateau "
          f"(max relief={PLATEAU_MAX_RELIEF_M}m, max radius={PLATEAU_MAX_RADIUS_M}m, "
          f"embankment height={PLATEAU_EMBANKMENT_HEIGHT_M}m)...")
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

        lake_polygon = lake_polygons.get(lake["id"])
        result = best_plateau_site(lake.geometry.x, lake.geometry.y, elevation, lake_volume_m3, lake_polygon)
        if result is None:
            continue

        result["empirical_volume_m3"] = empirical_reservoir_volume_m3(
            result["surface_area_m2"] / 1_000_000, empirical_a, empirical_b
        )

        records.append(
            {
                "lake_id": lake["id"],
                "lake_lon": lake.geometry.x,
                "lake_lat": lake.geometry.y,
                "lake_elevation_m": elevation,
                "mode": "plateau",  # see run_mode()'s matching field for why
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
            # The existing lake's own water surface altitude — sampled straight from the
            # DEM at the lake's location, which (being already flooded) already shows
            # today's water surface, not bare ground (see fetch_data.sample_elevation).
            "lake_elevation_m": round(r["lake_elevation_m"], 1),
            # Bare ground at the seed/dam location — the future basin's LOWEST point,
            # not its water surface once filled. See new_site_water_level_m for that.
            "new_site_elevation_m": round(r["site_elevation_m"], 1),
            # The new reservoir's own water surface once filled — site_elevation_m plus
            # however far it's flooded (or, for PLATEAU, diked) above that. This, not
            # new_site_elevation_m, is the other side of the head_m subtraction below —
            # see ReadmeAi.md's "How head is calculated" for the full picture.
            "new_site_water_level_m": round(r["water_level_m"], 1),
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
            "wall_fraction": (
                round(r["wall_fraction"], 3) if r["wall_fraction"] is not None else None
            ),
            "unrealistic_dam_length_m": (
                round(r["unrealistic_dam_length_m"]) if r["unrealistic_dam_length_m"] is not None else None
            ),
            # Only set by best_plateau_site() — r.get(), not r[], since NATURAL/
            # ENGINEERED records (from best_new_site()) don't carry this key at all.
            "flat_fraction": (
                round(r["flat_fraction"], 3) if r.get("flat_fraction") is not None else None
            ),
            "dam_start_lon": round(dam_line[0][0], 6) if dam_line else None,
            "dam_start_lat": round(dam_line[0][1], 6) if dam_line else None,
            "dam_end_lon": round(dam_line[1][0], 6) if dam_line else None,
            "dam_end_lat": round(dam_line[1][1], 6) if dam_line else None,
            "dam_height_m": round(r["dam_height_m"], 1) if r["dam_height_m"] is not None else None,
            "dam_length_m": round(r["dam_length_m"], 1) if r["dam_length_m"] is not None else None,
            "concrete_volume_m3": (
                round(r["concrete_volume_m3"]) if r["concrete_volume_m3"] is not None else None
            ),
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


def contours_geodataframe(top_candidates: list[dict], radius_m: float = SEARCH_RADIUS_M) -> gpd.GeoDataFrame:
    """Elevation contour lines for the search window around each of the given (already-
    ranked, top-N) candidates — reloads the DEM window per candidate (cheap: cached
    tiles, no network) rather than threading contour data through the whole search,
    since only a handful of candidates ever need this, not every lake scanned.
    radius_m defaults to SEARCH_RADIUS_M (NATURAL/ENGINEERED's own candidate radius) —
    PLATEAU passes its own, larger PLATEAU_SEARCH_RADIUS_M so the drawn contours
    actually reach a site that can legitimately sit farther from the lake than that."""
    properties = []
    geometries = []
    for rank, r in enumerate(top_candidates, start=1):
        window = load_elevation_window(r["lake_lon"], r["lake_lat"], radius_m)
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


def basin_footprints_geodataframe(top_candidates: list[dict], mode: SearchMode) -> gpd.GeoDataFrame:
    """The actual flooded shape for each of the given (already-ranked, top-N)
    candidates — not a circle or any other stand-in, the real set of cells basin_volume()
    included, vectorized into a polygon with rasterio.features.shapes(). Answers "how
    will the new lake look", not just "roughly how big" (surface_area_m2 already
    answers that).

    Reloads the DEM window and reruns basin_volume() once per candidate (cheap: cached
    tiles, no network, and only for the handful of candidates that make top-N — not
    threaded through the whole 1100-lake search, same reasoning as
    contours_geodataframe()). mode is needed here (contours_geodataframe() doesn't need
    it) because reproducing the same flood requires the same max_dam_height_m/
    max_basin_radius_m the candidate was actually found with.
    """
    properties = []
    geometries = []
    for rank, r in enumerate(top_candidates, start=1):
        # mode.seed_radius_m + 400, not the flat SEARCH_WINDOW_RADIUS_M — must match
        # best_new_site()'s own window sizing (see its docstring) or a candidate found
        # near NATURAL's wider seed_radius_m silently fails the row/col bounds check
        # below and never gets its footprint drawn, even though it was found and ranked.
        window = load_elevation_window(r["lake_lon"], r["lake_lat"], mode.seed_radius_m + 400)
        if window is None:
            continue
        elev, valid, transform, _lon_1d, _lat_1d = window
        height, width = elev.shape

        # Invert the forward pixel-center mapping (lon = transform.c + (col+0.5)*transform.a)
        # to recover which pixel the candidate's own site coordinates fall in.
        col = int(round((r["site_lon"] - transform.c) / transform.a - 0.5))
        row = int(round((r["site_lat"] - transform.f) / transform.e - 0.5))
        if not (0 <= row < height and 0 <= col < width):
            continue

        m_per_deg_lon, m_per_deg_lat = meters_per_degree(r["site_lat"])
        pixel_dx_m = abs(transform.a) * m_per_deg_lon
        pixel_dy_m = abs(transform.e) * m_per_deg_lat

        _volume_m3, _area_m2, _water_level, _pour_point, visited = basin_volume(
            elev, valid, row, col, pixel_dx_m, pixel_dy_m,
            mode.max_dam_height_m, mode.max_basin_radius_m,
        )
        if not visited.any():
            continue

        polygons = [
            shapely_shape(geom) for geom, value in rasterio_shapes(
                visited.astype(np.uint8), mask=visited, transform=transform
            )
            if value == 1
        ]
        if not polygons:
            continue

        properties.append({"rank": rank, "lake_id": r["lake_id"]})
        geometries.append(unary_union(polygons))

    return gpd.GeoDataFrame(properties, geometry=geometries, crs="EPSG:4326")


def plateau_footprints_geodataframe(top_candidates: list[dict]) -> gpd.GeoDataFrame:
    """PLATEAU's version of basin_footprints_geodataframe() — reruns plateau_footprint()
    (not basin_volume(), which doesn't apply here — see best_plateau_site()) once per
    top-N candidate and vectorizes the result the same way."""
    properties = []
    geometries = []
    for rank, r in enumerate(top_candidates, start=1):
        # Must match best_plateau_site()'s own window radius (PLATEAU_SEARCH_WINDOW_
        # RADIUS_M, not the smaller shared SEARCH_WINDOW_RADIUS_M) — otherwise a real
        # candidate found out near the edge of PLATEAU_SEARCH_RADIUS_M loads a window
        # too small to contain its own site_lon/site_lat, and the row/col bounds check
        # below silently drops it (no footprint drawn on the map, even though a real
        # candidate was found and ranked).
        window = load_elevation_window(r["lake_lon"], r["lake_lat"], PLATEAU_SEARCH_WINDOW_RADIUS_M)
        if window is None:
            continue
        elev, valid, transform, _lon_1d, _lat_1d = window
        height, width = elev.shape

        col = int(round((r["site_lon"] - transform.c) / transform.a - 0.5))
        row = int(round((r["site_lat"] - transform.f) / transform.e - 0.5))
        if not (0 <= row < height and 0 <= col < width):
            continue

        m_per_deg_lon, m_per_deg_lat = meters_per_degree(r["site_lat"])
        pixel_dx_m = abs(transform.a) * m_per_deg_lon
        pixel_dy_m = abs(transform.e) * m_per_deg_lat

        fill_value = np.nanmax(elev[valid]) + 1.0
        elev_filled = np.where(valid, elev, fill_value)
        grad_y, grad_x = np.gradient(elev_filled, pixel_dy_m, pixel_dx_m)
        slope = np.sqrt(grad_x**2 + grad_y**2)

        _area_m2, visited = plateau_footprint(
            elev, valid, slope, row, col, pixel_dx_m, pixel_dy_m,
            PLATEAU_MAX_RELIEF_M, PLATEAU_MAX_RADIUS_M,
        )
        if not visited.any():
            continue

        polygons = [
            shapely_shape(geom) for geom, value in rasterio_shapes(
                visited.astype(np.uint8), mask=visited, transform=transform
            )
            if value == 1
        ]
        if not polygons:
            continue

        properties.append({"rank": rank, "lake_id": r["lake_id"]})
        geometries.append(unary_union(polygons))

    return gpd.GeoDataFrame(properties, geometry=geometries, crs="EPSG:4326")


def passes_display_filters(r: dict) -> bool:
    """Display-only gate applied to the ranked list before it's written to
    docs/candidates_<mode>.geojson (the full, unfiltered ranking still goes to
    data/candidates_<mode>_all.geojson) — both are the user's own calls (2026-09-03),
    not a change to what best_new_site()/best_plateau_site() consider a valid
    candidate. Thresholds are per-mode — see MIN_DISPLAY_MW and
    MIN_VOLUME_RATIO_TO_LAKE for the reasoning (NATURAL is looser on both: cheap to
    build, so a smaller/lower-power bowl is still worth showing)."""
    mode = r["mode"]
    if r["score"] < MIN_DISPLAY_MW[mode]:
        return False
    if r["lake_volume_m3"] is None or r["lake_volume_m3"] <= 0:
        return False
    return r["basin_volume_m3"] >= MIN_VOLUME_RATIO_TO_LAKE[mode] * r["lake_volume_m3"]


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
    lake_polygons = load_lake_polygons(hydrolakes_shp_path)

    for mode in (NATURAL, ENGINEERED):
        records = run_mode(mode, lakes, (empirical_a, empirical_b), lake_polygons)

        all_path = DATA_DIR / f"candidates_{mode.name}_all.geojson"
        to_geodataframe(records).to_file(all_path, driver="GeoJSON")
        print(f"  wrote {all_path} ({len(records)} candidates)")

        top = [r for r in records if passes_display_filters(r)][:TOP_N[mode.name]]
        top_path = docs_dir / f"candidates_{mode.name}.geojson"
        to_geodataframe(top).to_file(top_path, driver="GeoJSON")
        print(f"  wrote {top_path} (top {len(top)})")

        contours = contours_geodataframe(top, radius_m=mode.seed_radius_m)
        contours_path = docs_dir / f"contours_{mode.name}.geojson"
        contours.to_file(contours_path, driver="GeoJSON")
        print(f"  wrote {contours_path} ({len(contours)} contour segments, "
              f"{CONTOUR_INTERVAL_M}m interval)")

        basins = basin_footprints_geodataframe(top, mode)
        basins_path = docs_dir / f"basins_{mode.name}.geojson"
        basins.to_file(basins_path, driver="GeoJSON")
        print(f"  wrote {basins_path} ({len(basins)} basin footprint(s))")

        for i, r in enumerate(top, start=1):
            confidence = (
                f"full basin at this mode's {mode.max_dam_height_m:.0f}m max dam height"
                if r["basin_bounded"] else "may extend further — search-limited"
            )
            lake_vol_note = (
                f"lake holds {r['lake_volume_m3']/1e6:.1f}Mm3, "
                f"{'CAPPED to 50% of it' if r['limited_by_existing_lake'] else 'not the limit'}"
                if r["lake_volume_m3"] else "lake volume unknown, not validated"
            )
            flow_note = (
                f"flow CAPPED to {MAX_FLOW_RATE_M3_S}m3/s (would need {r['implied_flow_m3_s']:.0f}m3/s otherwise)"
                if r["flow_limited"] else f"flow {r['implied_flow_m3_s']:.0f}m3/s, within realistic range"
            )
            if r["concrete_volume_m3"] is not None:
                concrete_note = (
                    f"~{r['concrete_volume_m3']/1e6:.2f}Mm3 concrete (gravity-dam estimate, "
                    f"{r['dam_height_m']:.0f}m x {r['dam_length_m']:.0f}m)"
                )
            elif r["unrealistic_dam_length_m"] is not None:
                concrete_note = (
                    f"UNREALISTIC: needs a ~{r['unrealistic_dam_length_m']:.0f}m dam, over the "
                    f"{MAX_DAM_LENGTH_M:.0f}m practical limit — no concrete estimate"
                )
            else:
                concrete_note = "no dam axis found (no valley shape here) — no concrete estimate"
            wall_note = (
                f", {r['wall_fraction']*100:.0f}% of basin boundary is real wall (>={MIN_WALL_FRACTION*100:.0f}% required)"
                if r["wall_fraction"] is not None else ""
            )
            print(
                f"  #{i}: lake {r['lake_id']} -> new site {r['direction']}, "
                f"head={r['head_m']:.0f}m, distance={r['distance_m']:.0f}m, "
                f"basin could hold {r['basin_volume_m3']/1e6:.2f}Mm3 "
                f"(cross-check predicts {r['empirical_volume_m3']/1e6:.2f}Mm3 for this footprint), "
                f"usable={r['volume_m3']/1e6:.2f}Mm3 ({confidence}; {lake_vol_note}){wall_note}, "
                f"~{r['score']:.0f}MW, {flow_note}, {concrete_note} "
                f"({r['storage_mwh']:.0f}MWh @ {DESIGN_DISCHARGE_HOURS}h)"
            )
        print()

    # PLATEAU isn't a SearchMode (see best_plateau_site()'s docstring for why), so it's
    # not in the (NATURAL, ENGINEERED) loop above — same write/print pattern, plateau-
    # specific fields (flat_fraction instead of wall_fraction, no dam/concrete notion).
    plateau_records = run_plateau_mode(lakes, (empirical_a, empirical_b), lake_polygons)

    all_path = DATA_DIR / "candidates_plateau_all.geojson"
    to_geodataframe(plateau_records).to_file(all_path, driver="GeoJSON")
    print(f"  wrote {all_path} ({len(plateau_records)} candidates)")

    plateau_top = [r for r in plateau_records if passes_display_filters(r)][:TOP_N["plateau"]]
    top_path = docs_dir / "candidates_plateau.geojson"
    to_geodataframe(plateau_top).to_file(top_path, driver="GeoJSON")
    print(f"  wrote {top_path} (top {len(plateau_top)})")

    plateau_contours = contours_geodataframe(plateau_top, radius_m=PLATEAU_SEARCH_RADIUS_M)
    contours_path = docs_dir / "contours_plateau.geojson"
    plateau_contours.to_file(contours_path, driver="GeoJSON")
    print(f"  wrote {contours_path} ({len(plateau_contours)} contour segments, "
          f"{CONTOUR_INTERVAL_M}m interval)")

    plateau_basins = plateau_footprints_geodataframe(plateau_top)
    basins_path = docs_dir / "basins_plateau.geojson"
    plateau_basins.to_file(basins_path, driver="GeoJSON")
    print(f"  wrote {basins_path} ({len(plateau_basins)} basin footprint(s))")

    for i, r in enumerate(plateau_top, start=1):
        confidence = (
            f"full footprint at this mode's {PLATEAU_MAX_RADIUS_M:.0f}m max radius/{PLATEAU_MAX_RELIEF_M:.0f}m max relief"
            if r["basin_bounded"] else "may extend further — search-limited"
        )
        lake_vol_note = (
            f"lake holds {r['lake_volume_m3']/1e6:.1f}Mm3, "
            f"{'CAPPED to 50% of it' if r['limited_by_existing_lake'] else 'not the limit'}"
            if r["lake_volume_m3"] else "lake volume unknown, not validated"
        )
        flow_note = (
            f"flow CAPPED to {MAX_FLOW_RATE_M3_S}m3/s (would need {r['implied_flow_m3_s']:.0f}m3/s otherwise)"
            if r["flow_limited"] else f"flow {r['implied_flow_m3_s']:.0f}m3/s, within realistic range"
        )
        print(
            f"  #{i}: lake {r['lake_id']} -> new site {r['direction']}, "
            f"head={r['head_m']:.0f}m, distance={r['distance_m']:.0f}m, "
            f"footprint {r['surface_area_m2']/1e4:.1f}ha "
            f"(cross-check predicts {r['empirical_volume_m3']/1e6:.2f}Mm3 for this footprint), "
            f"usable={r['volume_m3']/1e6:.2f}Mm3 at a design {PLATEAU_EMBANKMENT_HEIGHT_M:.0f}m embankment "
            f"({confidence}; {lake_vol_note}), {r['flat_fraction']*100:.0f}% of footprint is genuinely flat "
            f"(>={PLATEAU_MIN_FLAT_FRACTION*100:.0f}% required), "
            f"~{r['score']:.0f}MW, {flow_note} "
            f"({r['storage_mwh']:.0f}MWh @ {DESIGN_DISCHARGE_HOURS}h)"
        )
    print()


if __name__ == "__main__":
    main()
