# Data Sources

Reference for what `scripts/fetch_data.py` downloads, where from, and how to
point the whole pipeline at a different country.

## Sources

**DEM — Copernicus GLO-30**
- Host: AWS Open Data, public S3 bucket `copernicus-dem-30m`, no account/API key.
- Tile key layout: `Copernicus_DSM_COG_10_{N|S}{lat:02d}_00_{E|W}{lon:03d}_00_DEM/Copernicus_DSM_COG_10_{N|S}{lat:02d}_00_{E|W}{lon:03d}_00_DEM.tif`
  (note: resolution code in the key is `10`, not `30`, despite this being the
  GLO-30 product — that's how AWS/DLR named it). `{lat, lon}` are the tile's
  south/west corner, floored to an integer degree.
- 1x1 degree tiles. Some tiles (open ocean) don't exist — a 404 there is
  expected and handled as a skip, not an error.
- Verified 2026-08-31 via a direct S3 `ListBucket` call against the tile at
  N45/E025.

**Country boundary — Natural Earth 1:10m Admin 0 Countries**
- Direct zip mirror: `https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip`
  (~4.7MB, no auth). Used only to clip HydroLAKES to the target country.
- Select the country via the `ISO_A3` field in the shapefile.

**Lakes — HydroLAKES v1.0**
- Direct download: `https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip`
  (~820MB shapefile, global coverage — one file for every country, no
  per-country subset available). No account/registration, but CC-BY 4.0 —
  attribution required if the derived data is published.
- Verified 2026-08-31 via HTTP HEAD (200, content-length 820295132).
- Key columns used: `Hylak_id` (id), `Lake_area` (km², used as-is rather than
  recomputed from geometry).

## Reusing for a different country

Edit the `CONFIG` block at the top of `scripts/fetch_data.py`:

| Variable | What it controls |
|---|---|
| `COUNTRY_NAME` | Cosmetic, used in log output only |
| `COUNTRY_ISO_A3` | Selects the boundary polygon from Natural Earth (must match its `ISO_A3` field) |
| `BBOX` | `(min_lon, min_lat, max_lon, max_lat)` — which DEM tiles get downloaded. Pad generously; extra edge tiles are harmless, missing ones mean lakes near the border get `elevation: null` |

Everything else (HydroLAKES is global, Natural Earth boundaries cover every
country) needs no changes — re-run `python scripts/fetch_data.py` and it
downloads the new DEM tiles, re-clips the (already-cached) HydroLAKES file to
the new boundary, and overwrites `data/lakes.geojson`.

## Case B algorithm (`scripts/find_sites.py`)

- Resolves the README's "Open decision" (lake-lower vs lake-higher) as
  **both directions**: a reservoir site is a topographic depression either
  way (a valley floor, or a saddle/basin up on a ridge), so the script
  classifies each hit as `higher` or `lower` than the anchor lake after
  finding it, instead of running two separate passes.
- Two independent search modes, each with its own ranked top list — see
  `SearchMode` / `NATURAL` / `ENGINEERED` in `find_sites.py`:
  - **natural**: only sites that are already a closed depression (local
    minimum in a small pixel window) — no real construction beyond a
    modest containment wall. Small by nature; that's expected, not a bug.
  - **engineered**: any qualifying valley point can be a dam site — the
    dam creates the depression, same as most real reservoirs (see the
    Tarnița–Lăpuștești calibration note in the module docstring and below).
    Doesn't require a bowl, so it samples a coarse stride grid instead —
    the compute-cost tradeoff is the reason its `max_volume_candidates` is
    much lower than natural's (15 vs 50).
- Global tunables in `CONFIG`: `SEARCH_RADIUS_M` (2000), `MIN_HEAD_M` (100),
  `MAX_SLOPE_GRADE` (1.0 = 100% grade), `MAX_BASIN_CELLS` (4000, a hard
  compute guard independent of the radius/height caps — see fetch log),
  `DESIGN_DISCHARGE_HOURS` (8, for converting MWh to a comparable MW
  figure), `TOP_N` (3). None are country-specific.
- Output per mode: `data/candidates_<mode>_all.geojson` (every lake's best
  candidate for that mode, ranked) and `docs/candidates_<mode>.geojson`
  (top `TOP_N`, what the map reads) — `<mode>` is `natural` or `engineered`.
- Ranking metric is estimated power (MW), not raw storage energy (MWh) or
  the original head/distance ratio — see `estimated_power_mw()` and the
  module docstring's Ranking section. It's a constant rescaling of MWh
  (MWh / `DESIGN_DISCHARGE_HOURS`), so it never reorders candidates versus
  ranking by MWh directly — it's used because MW is what's comparable to a
  real plant's rated capacity.

**Real-world calibration — Tarnița–Lăpuștești (Cluj County, Romania's actual
1000MW pumped-storage project, unbuilt as of 2026):** existing lower
reservoir (Lake Tarnița) sits behind a 97m arch dam, lake surface 2.2km²,
drainage basin 491km². Upper reservoir is **not a natural bowl** — an
engineered lake planned for the Lăpuștești *plateau*, 563.5m of head above
Tarnița. Cycling volumes used in the design: ~15M m³ (lower) / ~10M m³
(upper). `ENGINEERED`'s `max_dam_height_m` (100) and `max_basin_radius_m`
(1500) come from the 97m dam / 2.2km² lake, not invented numbers. Sources:
en.wikipedia.org and ro.wikipedia.org "Tarnița–Lăpuștești" articles,
adevarul.ro coverage of the Tarnița dam (checked 2026-09-01).

## Fetch log

- **2026-08-31** — Implemented `scripts/fetch_data.py` for Romania
  (`BBOX = (20.0, 43.5, 30.0, 48.3)` → 60 DEM tiles, ~40MB each). Verified all
  three source URLs live before writing the download logic (see above).
  Not yet run end-to-end (HydroLAKES alone is an 820MB download).
- **2026-09-01** — Ran `fetch_data.py` end-to-end: 59/60 DEM tiles downloaded
  (`N44/E030` doesn't exist — open Black Sea water, expected), HydroLAKES
  clipped to Romania → **1100 lakes** in `data/lakes.geojson`. Implemented and
  ran `find_sites.py`: 92/1100 lakes produced a valid Case B candidate inside
  the 2km/100m-head filters (the rest had no qualifying nearby bowl). Wrote
  `docs/candidates.geojson` (top 3) and built `docs/index.html` (Leaflet, OSM
  tiles, lines colored by score, popups with head/distance/type).
- **2026-09-01** — Added reservoir volume to the ranking (was head/distance
  ratio only). Volume comes from a priority-flood fill from each candidate
  bowl pixel (`basin_volume()` in `find_sites.py`) — same idea as the
  "trapping rain water" problem: water level only rises as far as the
  terrain naturally contains it. First attempt capped only the vertical
  growth (`MAX_DAM_HEIGHT_M`) and produced nonsense (a top candidate at
  ~6 billion m³ — bigger than nearly any real reservoir) because gentle
  mountain slopes let the flood sprawl across the entire 2km search window
  instead of stopping at a plausible footprint. Fixed by also capping
  lateral extent (`MAX_BASIN_RADIUS_M = 500`m). Ranking metric is now
  estimated storage capacity in MWh (`storage_capacity_mwh()`: E = ρgVHη,
  η=0.85 round-trip efficiency, both approximate), not head/distance —
  volume changes which candidate wins, not just the score. New top 3 (all
  Carpathian, all "new site higher"): lake 1359758 (Vâlcea, 324m head,
  80.3M m³, ~60,300 MWh), lake 1352046 (369m head, 65.4M m³, ~56,000 MWh),
  lake 1358492 (530m head, 33.8M m³, ~41,500 MWh) — this displaced the
  previous #2 (lake 14030, 158m head/504m distance) entirely once volume
  was factored in, confirming volume dominates the ranking as expected.
- **2026-09-01** — User feedback: natural-bowl volumes (tens of M m³) read
  as too small to be financially credible, and asked to look at how the
  real Cluj project (Tarnița–Lăpuștești) is actually built. Researched it
  (see calibration note above) — its upper reservoir is an engineered lake
  on a plateau, not a natural depression, which is structurally why
  natural-bowl volumes are small: genuine enclosed pits just don't hold
  much water. Added the **engineered** search mode (dam-anywhere-in-the-
  valley, not bowl-restricted) calibrated to Tarnița's real dam height/lake
  size, and switched the ranking metric to estimated MW (see algorithm
  section above). Also added, for both modes: a dam-site (pour point) — the
  natural rim the flood-fill stops at — and an illustrative dam line drawn
  perpendicular to the local slope through it, for the map.
  - **Bug 1 (compute):** engineered mode's first run didn't finish in 9+
    minutes (vs ~30s for natural). Cause: engineered's larger radius (1500m
    vs 500m, ~9x the area) combined with no bowl pre-filter (far more lakes
    qualify at all) blew up total flood-fill work. Fixed with `MAX_BASIN_CELLS`
    (hard cell-count cap per flood-fill, independent of the radius/height
    caps) and a lower `max_volume_candidates` for engineered (15 vs 50).
  - **Bug 2 (correctness, more serious):** with that fixed, engineered's top
    candidates still came back at 1.2–1.6 **billion** m³ — mathematically
    impossible given `MAX_BASIN_CELLS`. Cause: `basin_volume()`'s flood-fill
    let water spread to any *reachable* lower-elevation neighbor, which is
    correct for a true bowl (by definition every neighbor of the bottom is
    higher) but wrong once bowl-restriction was dropped — a seed partway
    down an open slope would flood downhill indefinitely while `water_level`
    (pinned to the seed's own elevation ceiling logic) never rose, so cells
    arbitrarily far downhill counted as arbitrarily deep "water". Fixed by
    never letting the flood go below the seed's own elevation (a reservoir
    behind a dam at the seed can't extend downstream of it) — a 2m
    tolerance for DEM noise, no looser. This is a general correctness fix,
    not engineered-only: natural mode's results shifted too once it was
    applied (same latent bug, smaller effect at 500m/60m scale).
  - Final calibrated top 3, **natural**: lake 1352457 (338m head, 18.7M m³,
    ~1832 MW), lake 14030 (158m head, 33.2M m³, ~1516 MW), lake 1356686
    (150m head, 29.7M m³, ~1289 MW, no dam site found within the search
    window — likely underestimated). **engineered**: lake 1357337 (308m
    head, 128.5M m³, ~11,470 MW), lake 1352457 (293m head, 124.2M m³,
    ~10,524 MW), lake 1360316 (701m head, 50.1M m³, ~10,170 MW) — all three
    with a dam site found. Engineered MW figures are large relative to any
    single real plant built to date (largest is ~3.6GW) — a caveat worth
    keeping in mind, not necessarily a further bug: `max_dam_height_m`/
    `max_basin_radius_m` are a ceiling on what the search will *consider*,
    not a claim that building at that scale is economically sane.
- **2026-09-01** — Split `find_sites.py`: pulled everything about estimating
  a basin's volume and translating it to MW/MWh into a new `volumes.py`
  (`basin_volume`, `storage_capacity_mwh`, `estimated_power_mw`, and their
  constants — `MAX_BASIN_CELLS`, `DESIGN_DISCHARGE_HOURS`, etc.).
  `find_sites.py` now just imports from it; verified identical output on a
  known candidate (lake 1357337, engineered mode) before/after the split.
  `find_sites.py` still owns the search itself (seed selection, both
  `SearchMode`s), dam-line geometry, and all file I/O.
- **2026-09-01** — User asked: given we know Tarnița–Lăpuștești's real
  numbers, does this project actually find it? Located the real Lake
  Tarnița in our own data (`id=169355`, elevation 515.0m vs the published
  521.5m NNR level — close enough to confirm it's the same lake) and ran
  both search modes on it directly. **Neither found anything close to the
  real 563.5m head** — natural got 194m, engineered (untruncated shortlist)
  got 297m at best. Dug into why:
  - The real Lăpuștești site (~1085m) *is* within our 2km search radius —
    the DEM window's max elevation is 1075.7m at 1978m distance, just
    inside the boundary. So it's not a radius problem.
  - Slope wasn't the blocker either (checked directly: all pixels above
    1000m in the window have slope <= 0.75, under our 1.0 cutoff).
  - Seeding `basin_volume()` directly at that highest point returns
    **~46 m³** — essentially nothing. Root cause: it's the top of a
    plateau, i.e. a local *maximum*, not a depression. Our flood-fill can
    only find water a basin already naturally contains; it has no way to
    represent an embanked pond built on relatively flat high ground, which
    is what the real Lăpuștești reservoir actually is (confirmed by the
    project docs — it's explicitly built on "the Lăpuștești *plateau*",
    not in a valley). This is a structural limitation, not a bug: **this
    tool finds valley/bowl dam sites; it cannot find plateau-diking sites
    like the real Cluj project.** Worth remembering when judging any
    result's plausibility — a "no candidate" or a low-head candidate near
    a real known plateau-reservoir site doesn't mean the search is broken.
  - This also reframes the earlier "engineered MW figures are large"
    caveat: those aren't attempts at reproducing real known sites at all,
    they're valley-dam alternatives our search happened to find nearby —
    their plausibility should be judged on their own terrain, not against
    Tarnița–Lăpuștești specifically.
  - Captured as a permanent regression test (not just a one-off finding) —
    see `test_volumes.py` below.
- **2026-09-01** — Added `scripts/test_volumes.py` (stdlib `unittest`, no
  new dependency). Two kinds of coverage:
  - Synthetic elevation grids with a hand-computable exact volume — a flat-
    bottomed pit, a dam-height cap finding the rim, `MAX_BASIN_CELLS` as a
    hard stop, and a monotonic-slope regression test pinning down the
    downhill-runaway fix (a seed on a slope must never flood below its own
    elevation, no matter how generous the radius/height caps are).
  - Real-world reference tests against Lake Tarnița's actual downloaded DEM
    (skipped automatically if `data/dem/` isn't populated): sampled
    elevation vs. the published NNR level (521.5m, within 15m), the
    plateau-peak-gives-near-zero-volume finding above, and a sanity bound
    on `find_sites.best_new_site()` near Tarnița (volume comfortably below
    the pre-fix bug's billion-m³ territory). All 10 tests pass
    (`cd scripts && ../.venv/bin/python -m unittest test_volumes -v`).
  - Considered and rejected: asserting `basin_volume()` reproduces a real
    lake's *published* volume directly. Not possible honestly — GLO-30 DEM
    reflects today's terrain, so an existing lake shows as an already-flat,
    already-flooded surface, not the dry basin under it. There's no way to
    recover true lake volume from surface elevation data alone.
- **2026-09-01** — User flagged "some lines on the map make no sense."
  Found it: `dam_line` was being drawn through `pour_point` (the far rim of
  the flooded basin) instead of through the seed pixel — even though
  `basin_volume()`'s own docstring calls the seed "the dam site". Fixed:
  dam line now always centered on the new-site marker (verified: 0.0m
  offset between the two, on every candidate that has a dam line).
  Consequence worth knowing: `NATURAL` mode candidates often have *no* dam
  line at all — a bowl's exact bottom (the seed, a local minimum) usually
  has ~zero local slope, so there's no direction to draw a perpendicular
  line. That's expected math, not a regression. Added `basin_bounded` to
  the output (True = flood found a genuine rim, confident volume; False =
  cut off by the search caps, volume is a lower bound) to replace the old
  pour_point-based "dam site found/not found" messaging, which conflated
  two unrelated things (where the dam is vs. how confident the volume is).
  Map now also shows volume + head directly on the permanent on-map label,
  not just in the click popup. Re-ran `find_sites.py` — as expected, this
  is a purely cosmetic fix (the flood-fill math and scoring are untouched),
  so the top 3 for both modes are numerically identical to the previous run.
- **2026-09-01** — User pointed out a real physical gap: a pumped-storage
  cycle can't move more water than whichever reservoir is smaller — a new
  site's basin can look huge on its own terrain while the *existing* anchor
  lake is tiny, making the pair physically impossible to actually cycle.
  `basin_volume()` never knew anything about the anchor lake at all.
  - Turned out HydroLAKES already ships its own per-lake volume estimate
    (`Vol_total`, million m³, from Messager et al. 2016 — a geostatistical
    model, not derived from our DEM). For Tarnița this gives **74M m³**,
    matching the independently published >70M m³ closely — confirmed the
    field is trustworthy before wiring it in.
  - Added `volume_m3` to `fetch_data.py`'s `lakes.geojson` output (`Vol_total
    * 1e6`, `0`/missing treated as "unknown", not "empty lake" — re-run is
    cheap, no re-download, just re-clips the already-cached HydroLAKES file).
  - Added `volumes.usable_cycling_volume_m3()`: usable volume =
    `min(basin_volume, existing_lake_volume)`, or the raw basin volume
    unchanged if the lake's volume is unknown (explicitly *not* validated in
    that case, not silently assumed fine). `find_sites.py` now scores on
    this capped value, not the raw basin volume — `MIN_VOLUME_M3`,
    `storage_mwh`, and the MW ranking all use it. `basin_volume_m3` (the
    uncapped figure) and `limited_by_existing_lake` are kept in the output
    for transparency.
  - Effect was real: **52/92 natural and 210/265 engineered candidates**
    were capped by their anchor lake. New top 3: **natural** — lake 14030
    (158m head, 33.2M m³, ~1516MW, lake holds 1230M m³ — not the limit),
    lake 170453 (197m, 21.3M m³, ~1214MW), lake 1357845 (320m, 12.7M m³,
    ~1175MW). **engineered** — lake 1358492 (444m, 48.2M m³, ~6191MW, was
    ~11470MW pre-cap for a different lake), lake 170958 (349m, 56.7M m³,
    ~5738MW), lake 170750 (579m, 36.6M m³ basin **capped to 33.7M m³** —
    the lake's own volume — ~5654MW). Engineered's #1 MW roughly halved.
  - Map (`docs/index.html`) now labels each existing lake with its own
    volume directly (not just in the popup — user asked for this
    specifically, "also good for testing"), and the new-site popup shows
    basin volume vs. usable volume vs. lake volume separately with which
    one is the binding constraint.
  - Added `test_volumes.py::TestUsableCyclingVolume` (pure unit tests, no
    external data) and three more `TestBasinVolumeRealWorld` cases:
    `test_fetched_lake_volume_matches_published_value` (round-trips through
    the actual `lakes.geojson`, not a hardcoded stand-in), a capping
    sanity check on the real Tarnița search, and an explicit
    "tiny anchor lake caps a much bigger basin" case. 16/16 tests pass.
- **2026-09-01** — User's idea: since we're already using HydroLAKES' real
  (area, volume) pairs for the existing-lake cap above, use that same data
  to fit our *own* area->volume model, as an independent cross-check on
  `basin_volume()`'s terrain-based estimate for the *new* site.
  - `volumes.fit_reservoir_area_volume_model()`: log-log power law
    (V = a·A^b, the standard limnological form) fit on HydroLAKES'
    **global** reservoir-type lakes (`Lake_type=2` — dammed, not natural —
    read straight from the already-cached shapefile, `ignore_geometry=True`
    + a `where` filter, ~3s, no new download). Global, not Romania-only:
    tested both — Romania alone has only 78 reservoirs and the fit is
    noticeably worse (R²  0.46 vs 0.76 for the n=6687 global fit), and a
    global model is also the right call for a pipeline meant to be reused
    for other countries.
  - Checked the naive version (all lake types, unfiltered) against Tarnița
    first: **19x underestimate** (predicted 3.9M m³ vs real 74M m³) — most
    lakes on Earth are shallow natural ponds, nothing like a deep dammed
    mountain valley. Filtering to reservoirs-only brought that down to
    **~3x underestimate** (predicted ~24-26M m³, leave-one-out tested) —
    much better, but still a real, systematic low bias for exactly the
    site type pumped-storage cares about. Documented honestly rather than
    presented as more precise than it is: this is a *loose plausibility
    floor*, and `basin_volume()` legitimately exceeding it is expected, not
    a red flag — only a large *shortfall* would be worth a second look.
  - `find_sites.py` fits the model once per run (reservoir polygons don't
    change per-lake) and reports `empirical_volume_m3` per candidate
    alongside `basin_volume_m3`, purely as a diagnostic — it does **not**
    feed scoring or filtering, to keep the terrain-specific method (which
    should be more accurate per-site, provided it's implemented correctly)
    as the actual ranking basis. All top-6 current candidates show
    `basin_volume_m3` 2-4x their cross-check prediction — consistent with
    the Tarnița finding (steep Carpathian terrain genuinely holds more
    than a generic reservoir's area would suggest), not a red flag.
  - Tests: `TestEmpiricalReservoirVolume` — a pure-formula check, a fit
    against synthetic exact-power-law data (recovers the true `a`/`b` to
    tight tolerance, validates the *fitting procedure* independent of
    HydroLAKES' real data), and a real-data test pinned to the Tarnița
    ratio range (0.1-0.6) — deliberately asserting the underestimate is
    real, so a future change that "fixes" it without understanding why
    gets caught. 19/19 tests pass.
- **2026-09-01** — Map's permanent on-map label was showing only the
  (possibly lake-capped) usable volume — the new site's own estimate
  (`basin_volume_million_m3`) was popup-only. Now shown on the map label
  directly, with a second line ("&rarr; X usable, lake-limited") when the
  cap actually reduced it, so the gap between "what the bowl could hold"
  and "what's actually usable" is visible without a click. Pure map change,
  no re-run of `find_sites.py` needed (the field was already in the geojson
  from the empirical-cross-check work above).
- **2026-09-01** — User flagged a specific candidate as implausible: lake
  170958 ("Iovanu" on the Cerna, engineered #2) at ~5738MW — "way larger
  than Tarnița [-Lăpuștești]". Traced it: `MW = MWh / DESIGN_DISCHARGE_HOURS`
  silently assumes a large enough waterway exists to move the whole volume
  in 8h, however large that requires the flow to be. This candidate needed
  **1970 m³/s** — 9x the flow of Romania's own actual flagship 1000MW
  project (Tarnița–Lăpuștești, whose flow isn't published but backs out to
  ~213 m³/s from its own 1000MW/563.5m rating).
  - Looked up two more **real, currently operating** Romanian plants (not
    just the one planned project) to validate the physics independently:
    **Vidraru** (324m head, 90 m³/s, 220MW real — formula predicts ~243MW)
    and **Lotru-Ciunget** (809m, 80 m³/s, 510MW real — predicts ~540MW).
    Both within ~10%, confirming ρ·g·Q·H·η itself is accurate; the missing
    piece was specifically the flow-rate ceiling, not the energy physics.
  - Added `volumes.MAX_FLOW_RATE_M3_S = 250` (headroom above Tarnița–
    Lăpuștești's ~213 m³/s, the largest of the three real figures — a
    modern multi-unit design vs. 80-90 m³/s for the older single/few-unit
    plants) and `realistic_power_mw()`: caps the flow at that ceiling
    instead of letting duration-based MW run unbounded — a large-volume
    candidate just takes longer than 8h to fully cycle, rather than
    reporting an unbuildable instantaneous power. `find_sites.py` now
    scores on this, not the naive duration-based figure; `implied_flow_m3_s`
    (uncapped) and `flow_limited` are kept in the output for transparency.
  - Effect was large and reshaped the rankings: **51/92 natural and
    200/265 engineered candidates hit the flow cap.** Since capped
    candidates all share the same ceiling flow, ranking among them becomes
    driven mostly by head — volume stops differentiating once "enough" to
    sustain the capped flow. New top 3, **natural**: lake 1357337 (488m
    head, ~962MW, flow 237m³/s — under the cap), lake 1358492 (530m,
    ~919MW, 208m³/s), lake 169296 (360m, ~751MW, capped from 391m³/s).
    **engineered**: lake 170750 (824m, ~1670MW, 243m³/s — right at the
    ceiling but not capped), lake 1360316 (701m, ~1461MW, capped from
    549m³/s, also lake-volume-capped), lake 1358492 (534m, ~1113MW, capped
    from 923m³/s). The flagged lake 170958 fell to **rank 5 at ~937MW** —
    a different specific site within its search window now scores best,
    since the ranking criterion itself changed (head-favoring, not
    volume-favoring, once flow-limited).
  - Map: on-map label and popup now show required flow and whether it was
    capped (`Required flow` row); on-map label also now shows distance to
    the existing lake directly (was popup-only before).
  - Tests: `TestRealisticPower` — formula checked against Vidraru and
    Lotru-Ciunget directly, `MAX_FLOW_RATE_M3_S` checked against the
    Tarnița–Lăpuștești-implied flow, and a regression test using the exact
    reported bug's numbers (lake 170958's volume/head) asserting the capped
    result is meaningfully smaller and bounded under 1000MW. 24/24 tests
    pass.
- **2026-09-01** — Added elevation contour lines to the map, per user
  request. New `scripts/contours.py` (kept separate from `find_sites.py` —
  a pure rendering concern, doesn't know about lakes/volume/search at all)
  uses `contourpy` (matplotlib's own contouring engine, without needing
  matplotlib itself — a new dependency, added deliberately for this,
  flagged rather than snuck in) to draw lines at a 50m interval from the
  DEM window around each top candidate. Refactored the window-loading code
  out of `best_new_site()` into `load_elevation_window()` so both the
  search and the contour step read the DEM the same way — verified
  behavior-identical before/after (same head/volume/score on a known
  candidate). `find_sites.py` writes `docs/contours_<mode>.geojson`
  alongside the candidates file; only for the final top-N per mode (not
  every lake scanned — reloads cached tiles per candidate, cheap, no
  network). Map draws them as thin lines under the candidate lines/markers,
  every 5th (250m) bolder as an index contour, click for exact elevation.
  Tests: `test_contours.py` — a paraboloid bowl with an exact known ring
  radius per level (`sqrt(elevation)`), flat-grid and no-valid-data edge
  cases, and a check that nodata fill doesn't invent a fake cliff at the
  fill value. 4/4 pass (28/28 across the whole suite).
- **2026-09-01** — User (repeated, correctly): MW still felt too high for
  the volume of the new dam, even after the flow-rate cap fix. Right —
  found a real reasoning error, not just a calibration nit. `volumes.
  DESIGN_DISCHARGE_HOURS = 8` carried a comment claiming "8h is
  conservative... produces a lower MW estimate" versus the real Lăpuștești
  duration. That's backwards: MW = MWh / duration, so a *shorter* duration
  always gives a *larger* MW for the same energy, never a smaller one.
  Checked directly: real Lăpuștești is 10M m³ @ 563.5m head = 13,052 MWh
  (our own formula); at its real 1000MW rating that's a **13.0h** duration,
  not 8h. Using 8h would have reported **1631MW for that same real site —
  1.63x its actual rating — before any flow cap even applied.** Corrected
  `DESIGN_DISCHARGE_HOURS` to 13 (the one real duration figure we have),
  updated the comment to explain the corrected reasoning, and added
  `test_design_discharge_hours_matches_tarnita_lapustesti_duration` to pin
  it down so it can't silently drift back to something shorter. `MAX_FLOW_
  RATE_M3_S` (calibrated independently, straight from real Q/H/MW figures)
  needed no change. Note the 1970 m³/s / "9x Tarnița's flow" figure in
  earlier log entries and code comments was measured under the old,
  now-corrected 8h assumption — left as historical record with that noted,
  not rewritten. New top 3, **natural**: lake 169296 (360m head, 11.3M m³,
  ~723MW), lake 1357845 (320m, 12.7M m³, ~666MW, flow-capped), lake
  1357337 (488m, 6.8M m³, ~592MW). **engineered**: lake 170750 (736m,
  12.0M m³, ~1534MW, flow-capped), lake 1360316 (701m, 15.8M m³ lake-
  capped, ~1461MW), lake 1358492 (534m, 26.6M m³, ~1113MW, flow-capped) —
  every current candidate is now comfortably below even what our own
  formula would (incorrectly) have reported for the real 1000MW Lăpuștești
  project under the old assumption, and all are in a believable range
  against the real 1000MW/510MW/220MW reference points. 29/29 tests pass.
- **2026-09-01** — Added `scripts/reference_projects.py`, per user request:
  render the real Tarnița–Lăpuștești project on the map itself (not just in
  writeups), in the same visual language as our own candidates, as a
  built-in benchmark. Deliberately a separate script/file from `find_sites.
  py`'s output — every number in it is a cited real figure, not something
  our search computed, and the schema is intentionally simple rather than
  forced into the candidates' schema (no fake `empirical_volume`/
  `basin_bounded`/etc. for fields that don't apply to a hand-sourced
  entry). Writes `docs/reference_projects.geojson`; map renders it as a
  distinct green layer/marker style with "REAL:" in its label, clearly
  separated from the algorithm's own orange/blue candidates. One caveat
  documented in the script and popup: the Lăpuștești site's exact
  coordinates aren't published anywhere found — the marker uses the
  highest point in our own DEM search window near Tarnița (1075.7m, close
  to the real 1085m) as a plausible stand-in, explicitly flagged as
  approximate; head/volume/MW are the real published figures regardless.
- **2026-09-01** — Added a Google Maps link (`?q=lat,lon`) for the new
  site/dam location in every popup that names a coordinate: each
  candidate's main popup and its "new reservoir site" marker, the dam-line
  popup, and the reference project's popup and site marker (flagged there
  as approximate, matching the coordinate caveat already on that entry).
  Pure map change — no Python/data regeneration needed.
- **2026-09-01** — Added a rough concrete-volume estimate for the dam
  itself, and repositioned the Google Maps link per user request. New
  `scripts/dam_construction.py`, kept separate from `volumes.py` (that
  module is about how much *water* a site holds; this is about how much
  *material* the wall itself needs — a genuinely different concern).
  Assumes a plain concrete gravity dam (triangular cross-section, base
  width = 0.75x height — a standard textbook rule of thumb, not calibrated
  to a specific real project the way the water-physics formulas were) and
  is explicit in the code/docstrings/popup that this likely overestimates
  for a site an arch dam would suit (like the real Tarnița itself — 97m
  tall on a 237m crest, arch, much less concrete than a gravity dam that
  size would need) and doesn't apply at all to an embankment dam. Height
  comes from `water_level_m - site_elevation` (already computed by
  `basin_volume()`), length from the existing illustrative `dam_line` — so
  it inherits that line's own caveats (not a real cross-valley survey) and
  is `None` wherever `dam_line` is, for the same reason. Wired into
  `find_sites.py`'s output (`dam_height_m`, `dam_length_m`,
  `concrete_volume_m3`) and the console summary. Current top 6 range
  0.70-3.00 million m³ of concrete, roughly proportional to each dam's
  height/length. Tests (`test_dam_construction.py`): hand-calculated exact
  volume, height²/length¹ scaling checks, zero/negative-input edge cases,
  and a sanity bound on the base-to-height ratio itself. 5/5 pass (34/34
  across the whole suite).
  - Also moved the map's Google Maps link: previously always the bare new-
    site coordinate: now the *middle of the dam* (`dam_line`'s midpoint)
    when one exists, or the site coordinate itself (a reasonable stand-in
    for "the middle of the new lake" — it's the bottom of the depression)
    when there's no dam axis to speak of, per the user's exact framing
    ("middle of the new dam or... middle of the new lake if a natural
    bowl"). Fixed a small pre-existing inaccuracy along the way: the dam-
    line popup's own link was pointing at `dam_start`, one endpoint, not
    the actual middle — now uses the true midpoint everywhere.
- **2026-09-01** — User: "not sure the dam line is in the right place...
  I always find there another place right close to it." Right — found a
  genuine geometry bug in `dam_line_endpoints()`, not just imprecision:
  1. It drew the line **perpendicular** to the local slope, reasoning
     "perpendicular to slope = along the contour = where a dam runs." That
     reasoning is backwards — a contour line runs *along* a valley
     (parallel to the flow direction); a dam has to *cross* the valley, so
     it needs to align *with* the slope direction (up one wall, across,
     up the other), not run perpendicular to it. A 90-degree rotation
     error.
  2. `grad_y` (from `np.gradient()`'s row-axis) points *south*, since DEM
     rows increase as latitude decreases — it was used as a north-positive
     component without negating it.
  Verified both independently with a synthetic north-south valley: the old
  code drew the line running north-south (**along** the valley, parallel
  to the river) instead of the correct east-west (**across** it) — exactly
  the kind of error that would put the marker "close by" but at a real
  spot that looks more obviously right on satellite imagery. Fixed both;
  added `test_find_sites.py` (new — `find_sites.py` had no dedicated tests
  before this) with synthetic N-S and E-W valleys of known correct
  orientation, confirmed these tests **fail** against the old buggy logic
  (checked directly, not assumed) and pass against the fix, plus edge
  cases (flat ground -> None, length clamping). 4/4 new tests, 38/38 across
  the whole suite. This bug only affected the dam line's drawn
  orientation — slope magnitude (used for the `MAX_SLOPE_GRADE` filter)
  is unaffected by the sign/rotation error, so site selection, volume,
  power, and ranking were never wrong from this.
  - User also asked whether, "if everything is correct," the search should
    naturally find the real Tarnița–Lăpuștești site near Lake Tarnița.
    Re-tested after the fix: still no — natural mode's best candidate
    there is 259m head/442MW, engineered's is 302m head/630MW, both far
    short of the real 563.5m/1000MW. Went further than before: specifically
    searched for locally *flat* elevated patches (not just the single
    highest point) near the real target elevation, using a local
    standard-deviation filter — found a genuine flat area (~14 pixels,
    ~950-980m elevation, far short of the real 1085m target and small),
    seeding there gives 456m head but only 4.26M m³/346MW, still worse
    than what the regular search already finds elsewhere nearby. Confirms
    the earlier finding still holds: the real site needs actual
    engineering (leveling/diking a plateau) that a "flood a natural
    depression" algorithm structurally cannot discover, not a bug to fix.
    Notably, Lake Tarnița *does* show up in its own right in the top-20
    (see below) — natural #7 (442MW), engineered #16 (630MW) — just for a
    different, more modest nearby site than the real Lăpuștești.
  - Raised `TOP_N` from 3 to 20 per user request. New top-20 written to
    `docs/candidates_natural.geojson` / `_engineered.geojson` (and their
    contour files, now larger: 965 / 1057 segments) — full ranked lists
    logged in this session's terminal output, not reproduced here in full;
    top MW unchanged from the top-3 report above (natural #1 lake 169296
    ~723MW, engineered #1 lake 170750 ~1534MW), now with 17 more ranked
    candidates each visible on the map.
- **2026-09-01** — User, after the orientation/sign fix above: "the line for
  the new dam on the map makes no sense." Checked properly this time —
  sampled real DEM elevation along several dam lines instead of re-deriving
  the math again. The gradient-aligned line from the previous fix was
  mathematically consistent but still wrong in practice: **7 of 8 sampled
  ENGINEERED candidates' lines climbed monotonically end to end** (e.g. lake
  170750's: 1018m -> 1320m, no dip anywhere) — just a straight line up a
  hillside, not a valley crossing. A single pixel's gradient can't tell you
  whether the site is actually a two-walled valley in the first place;
  NATURAL mode fared better (5/8 valley-like) since those seeds are true
  local minima.
  - Rewrote `dam_line_endpoints()`: tries `DAM_LINE_ANGLE_STEPS` (8)
    candidate orientations and requires REAL terrain (sampled from the
    actual elevation grid, not inferred from one gradient reading) to rise
    by at least `DAM_LINE_MIN_RISE_M` (5m) on BOTH sides of the seed.
    Returns `None` — no dam line drawn, `"no dam axis found"` reported
    plainly — when no orientation clears that bar, rather than drawing a
    line that misrepresents the site. Real basis for this: many ENGINEERED
    candidates flood a chunk of hillside bounded only by our own
    `MAX_BASIN_RADIUS_M`/`max_dam_height_m`, not real valley walls on both
    sides — those genuinely would need a perimeter embankment, not a
    single wall, so there's no honest single "dam axis" to report.
  - Fully rewrote `test_find_sites.py` for the new signature/semantics: a
    valley with a known-correct crossing direction (seed placed exactly at
    the trough, the case dam sites are actually drawn for), a uniform
    tilted plane proven to *always* fail the "both sides rise" check for
    any orientation (a clean analytical case, not just an empirical one),
    flat ground, length clamping, and an out-of-window edge case. 6/6 new
    tests pass, 40/40 across the whole suite at this point.
  - Effect on real data: ENGINEERED mode now reports "no dam axis found"
    for nearly all of its top 20 (consistent with the 7/8 finding above —
    this isn't new information suppressing something that used to work,
    it's the honest version of what was already true). NATURAL mode still
    finds real axes for a solid fraction of its list. Rankings themselves
    are unaffected either way (dam geometry was never part of scoring).
- **2026-09-01** — User, same message: "the finding 19 makes no sense"
  (natural-mode candidate #19 at the time, anchored to lake 1293 — 118.58
  km², 2550M m³, by far the largest lake in the dataset). Investigated:
  lake 1293's polygon bounds (21.7-22.5°E, 44.4-44.7°N) match the real
  **Porțile de Fier I / Iron Gate I** reservoir on the Danube (Romania-
  Serbia border) closely — but its stored elevation was **566.2m**, wildly
  implausible for a Danube-valley reservoir (should be well under 100m).
  Root cause: `fetch_data.py` used `geometry.centroid` — a polygon's
  center of *mass*, which for a non-convex shape (a long, curving
  reservoir, exactly what Iron Gate I is) isn't guaranteed to fall inside
  the polygon at all. Confirmed directly: `polygon.contains(polygon.
  centroid)` is **False** for lake 1293 — the centroid landed on a
  hillside ~500m higher than the actual water. Checked how widespread
  this is: **101 of Romania's 1100 lakes (9%) have a centroid outside
  their own polygon**, including lake 14030, which had appeared in top
  results multiple times earlier in this session with a potentially-wrong
  anchor point.
  - Fixed: switched to `geometry.representative_point()`, which shapely
    guarantees falls inside the polygon. Re-ran `fetch_data.py` (fast,
    fully cached, just re-clips) — lake 1293's elevation corrected from
    566.2m to **67.0m**, a plausible Danube-valley figure.
  - Added `TestAnchorPointFix` to `test_volumes.py`: confirms lake 1293's
    real polygon does NOT contain its own centroid (pins the bug's
    precondition down, so if HydroLAKES data changes and this stops being
    true, the test says so rather than silently passing for the wrong
    reason) but DOES contain `representative_point()`, and that the
    fetched elevation is now plausible (<150m). Updated the existing
    Tarnița test constants to the new (representative_point-based)
    coordinates — shifted slightly (~150m) from the old centroid-based
    ones, same 515.0m elevation, since Tarnița's own shape is simple
    enough that neither method was actually wrong for it. 42/42 tests
    pass across the whole suite.
  - Re-ran the full pipeline with the corrected data. Lake 1293 now ranks
    **natural #4 (560m head, ~582MW)** and **engineered #7 (513m head,
    ~1068MW)** with its corrected location/elevation — a real, material
    change, not a cosmetic one. New top 3, **natural**: lake 169296 (360m,
    ~751MW), lake 1357845 (320m, ~666MW), lake 1357337 (488m, ~592MW).
    **engineered**: lake 1360316 (722m, ~1504MW), lake 170750 (646m,
    ~1347MW), lake 1358492 (612m, ~1275MW).
- **2026-09-01** — User asked about the visible "arc" on the map (the
  contour showing the natural basin rim) and whether writing an algorithm
  to place it and compute volume from it would be hard. Answered: it's not
  a new algorithm to write — `basin_volume()`'s priority-flood *is* the
  standard algorithm for exactly this (the same approach real GIS software
  uses for watershed/depression-filling), and `basin_bounded` already
  records whether the "arc" actually closed within our search limits.
  Checked how often it doesn't: **17/20 natural, only 9/20 engineered**
  candidates in the current top-20 have `basin_bounded=True` — the rest
  are genuinely underestimates (the true rim lies beyond what we searched),
  not just imprecise. Since that's a real, fixable limitation (not a new
  algorithm), raised the actual limits: `MAX_BASIN_CELLS` 4000 -> 12000
  (~2.8km² -> ~8km²), and `ENGINEERED.max_basin_radius_m` 1500 -> `SEARCH_
  RADIUS_M` (2000) — the flood can never reach past the already-loaded DEM
  window anyway, so capping it any tighter than that window bought nothing.
  - Result: **NATURAL mode was completely unaffected** — its 500m radius
    means even the theoretical max footprint (~1172 cells) was always well
    under the old 4000-cell cap, so its estimates were already as accurate
    as this method allows. **ENGINEERED mode's basin_bounded count didn't
    move either (still 9/20)**, though several large candidates' volumes
    *did* grow somewhat (e.g. lake 170750: 20.35M m³ -> 26.61M m³, lake
    169296: 52.80M m³ -> 59.94M m³) — meaningful, but not enough to close
    the remaining ~11/20 arcs. Rankings were completely unchanged, since
    MW for a flow-capped candidate is a function of head alone once volume
    is "enough" to sustain `MAX_FLOW_RATE_M3_S` — more volume beyond that
    point doesn't change the score.
  - Read honestly: for roughly half of ENGINEERED's top 20, the true
    natural rim lies even further than 2000m/12000 cells away — consistent
    with (not contradicting) the dam-axis finding above: these aren't
    small, cleanly enclosed valleys, they're broad terrain features. Caps
    could be raised further, but with diminishing accuracy return per unit
    of slower search, and it wouldn't address the underlying reason
    (there may genuinely be no small natural enclosure to find). 42/42
    tests still pass (the MAX_BASIN_CELLS-hard-cap test references the
    constant, not a hardcoded number, so it stayed valid across the change).
- **2026-09-01** — User asked for something easy to see where the new dam
  will be and what it will look like. Realized `basin_volume()` already
  computes exactly that internally — the `visited` boolean mask of every
  cell the flood-fill included — and was just discarding it after use.
  Changed `basin_volume()` to always return it (updated all 6 call sites:
  1 in `find_sites.py`, 5 in `test_volumes.py`), and added
  `basin_footprints_geodataframe()`: reruns `basin_volume()` once per
  top-N candidate (same reasoning as `contours_geodataframe()` — cheap,
  cached tiles, only for the handful that make top-N) and vectorizes the
  mask into a real polygon with `rasterio.features.shapes()` (already a
  dependency — no new library). Cross-checked the result: polygon area
  matched the already-reported `surface_area_m2` to within rounding.
  Writes `docs/basins_<mode>.geojson`; map renders it as a filled,
  semi-transparent shape in the candidate's own mode color, under the
  line/markers so those still draw on top. This is the actual computed
  shape, not a circle or other proxy — "how will it look" answered with
  real data already being computed, not a new approximation. 42/42 tests
  still pass.
- **2026-09-01** — User: "I feel like the lake is not in the right place"
  looking at natural candidate #6 — they could see a more obviously
  "natural" spot nearby. Checked concretely: for lake 1357337, NATURAL
  mode's own candidate (a real local-minimum bowl) sits ~709m from
  ENGINEERED mode's candidate for the *same lake*, and the ENGINEERED
  basin polygon stops ~65-70m short of actually reaching that bowl.
  Followed up on "is this just #6, or does engineered have this
  everywhere" (user's exact next question) by checking systematically:
  compared all 20 of ENGINEERED's top candidates against NATURAL's own
  candidate for the same lake (19/20 had one). **Site-to-site distance
  ranged 196m to 3281m** — not a #6-specific glitch, a structural property
  of the whole list.
  - Tested whether finer seed sampling would close the gap (in case 150m
    stride was just too coarse to land on the real bowl): tried 60m and
    30m stride on lake 1357337. Neither converged toward the known bowl —
    each found a *different* point, with progressively *lower* MW (1096 ->
    782 -> 652). Not a resolution problem.
  - Root cause is the same one already found for the missing dam axes:
    ENGINEERED mode accepts any reachable point as a candidate and only
    checks for real terrain containment *after* picking a winner by MW —
    it was never required *during* selection. Tested making it required:
    for lake 1357337's own 15 shortlisted candidates, ran the dam-axis
    containment check (dam_line_endpoints' "does the terrain rise on both
    sides" logic) on *all* of them before scoring, not just the winner —
    **0 of 15 passed.** Hard-filtering on this would eliminate ENGINEERED
    candidates almost entirely for at least some lakes — not implemented,
    since that changes ENGINEERED from "best MW among any qualifying
    point" to something much closer to NATURAL mode, which needs a
    decision, not a unilateral change. Flagged to the user rather than
    applied.
  - User's own conclusion, mid-investigation: de-emphasize the dam concept
    entirely for now and lean on the basin footprint instead — see below.
- **2026-09-01** — User: "also coloring where the new lake will be, remove
  the [dam] line for now. I feel like showing the lake is superior."
  Removed the dam-line polyline from the map (both modes — NATURAL's own
  axis-found rate, 12/20, wasn't much better once actually looked at
  critically). Boosted the basin footprint polygon's visual weight
  (fillOpacity 0.35 -> 0.55, outline weight 1.5 -> 2) since it's now the
  primary "where/how will it look" visual. Google Maps link, which used to
  prefer the dam line's midpoint, now always points at the site (verified
  earlier to always be inside its own basin polygon). Backing data
  (dam_start/dam_end, dam_height_m, dam_length_m, concrete_volume_m3) is
  unchanged in the geojson and still in the popup as a concrete-volume
  estimate — only the drawn line itself was removed, along with an unused
  DAM_COLOR constant and two stale "see popup below" self-references
  fixed while touching that block. Pure map change, no Python/data
  regeneration needed.
- **2026-09-01** — Implemented the containment fix flagged (not yet
  applied) in the entry above: `best_new_site()` now requires
  `dam_line_endpoints()` to succeed *during* ENGINEERED shortlist
  scoring, not just for the eventual winner — a candidate that can't show
  real terrain rising on both sides is now rejected outright rather than
  just noted. `ENGINEERED.max_volume_candidates` raised 15 -> 40 to
  compensate for the shortlist getting thinned. NATURAL is unaffected
  (its `bowl_required`/`is_bowl` check already guarantees containment a
  different way — see the code comment for why a true bowl's exact
  bottom can fail the line-check despite being real).
  - Verified on the single worst case first (lake 1360316, previously the
    #1-ranked ENGINEERED candidate 3006m from its NATURAL counterpart):
    filter now finds a real dam axis (`dam_line found=True`, previously
    effectively never true for ENGINEERED), MW dropped 1504 -> 1139 at
    the new (now-contained) site, gap only closed 3006m -> 2756m — i.e.
    it moved to a *different*, also-real depression, not the same one
    NATURAL finds.
  - Ran the full pipeline (`find_sites.py`, all 1100 lakes, both modes)
    and checked the result properly this time — not just the one lake:
    ENGINEERED coverage dropped 269 -> 132 lakes with any candidate at
    all (many lakes' whole shortlist failed containment, same as the
    0/15 case found earlier for lake 1357337). Of the 66 lakes that now
    have *both* a NATURAL and an ENGINEERED candidate, site-to-site
    distance: mean 1313m, median 991m, range 95m-3437m (`#1352046`:
    3437m; `#170318`: 848m at the tight end). **Read honestly: the
    containment filter fixed "is this a real place," it did not fix "is
    it the same place NATURAL finds."** That's expected, not a residual
    bug — ENGINEERED searches the full `SEARCH_RADIUS_M` window for the
    single best-MW *contained* point, while NATURAL is restricted to a
    tiny local-minimum window right at the lake; the two modes are
    supposed to explore different candidate sets and can legitimately
    land on different real basins. 42/42 tests still pass.
  - Every top-20 ENGINEERED candidate (in the new run) now has a dam
    axis (20/20, up from 0/20); NATURAL sits at 12/20 (unchanged — it
    was never the one with the problem).
- **2026-09-01** — User: "please individually check each result and fix
  the upcoming bugs. I really think if we want to publish this it needs
  to be high quality." Went through all 40 top-ranked candidates (20
  NATURAL + 20 ENGINEERED) with automated, data-grounded checks rather
  than re-reading the code and asserting it's fine — methodology and
  results below, so this is reproducible for future runs or other
  countries.
  - **Checked, found genuinely fine** (each of these looked like a
    plausible bug going in, so recording that they were actually ruled
    out, not just skipped): basin footprint polygon area vs. reported
    `surface_area_m2` (matches to <10% once measured in a proper
    equal-area CRS — an EPSG:3857/Web Mercator area comparison was tried
    first and showed a suspicious ~2x gap on every single candidate,
    which is exactly Web Mercator's own area-distortion factor at
    Romania's ~46 degrees N latitude, 1/cos^2(46)~=2.07 — a bug in the
    *check*, not the pipeline); head/direction/distance recomputed
    independently from each candidate's own coordinates (exact match,
    all 40); basin polygon contains its own seed/dam point (all 40); no
    candidate's new site lands on or near (<50m) an *existing* HydroLAKES
    polygon other than its own anchor lake (checked against the real
    polygon shapes, not just lake centroids); `usable <= basin` and the
    "capped by lake" flag agreeing with the actual usable-vs-lake-volume
    numbers (all 40); cross-check ratio (`basin_volume_m3` vs. the
    independent empirical area->volume model) stays within the ~3x range
    already calibrated against Tarnita (natural: 1.2-2.2x, engineered:
    1.7-3.5x, one candidate at 3.54x — not treated as an outlier, this
    is the same ballpark as the real ground-truth case); one branching,
    low-compactness basin shape (lake 1360316, compactness=0.30, splits
    into 6 pieces under a 20m erosion test) was checked further —
    plausible as a real dendritic mountain-valley reservoir shape (real
    reservoirs branch like this), not distinguishable from a cross-ridge
    leak with the data at hand; flagged as an open heuristic limitation
    below, not fixed.
  - **Real bug found and fixed**: `basin_bounded` (surfaced to users as
    "flood found a natural rim — confident estimate" in the map popup,
    and reused in comments in `volumes.py`/`find_sites.py`) does not
    mean what its own name and wording claim. Checked directly against
    `pour_point`'s one and only set-site in `basin_volume()` (the
    `elev_here - seed_elev > max_dam_height_m` branch) against the full
    dataset: **100% of `basin_bounded=True` candidates with a known dam
    height sit within 2m of that mode's `max_dam_height_m` cap** (31/31
    natural, 22/22 engineered, checked on `data/candidates_*_all.geojson`
    — not just top-20). There is no code path where the flood exhausts
    its own frontier and stops *below* the height cap on open terrain —
    real terrain essentially never encloses that way (already noted in
    `basin_volume()`'s own docstring, just not connected to what
    `pour_point` actually measures). So `basin_bounded=True` really means
    "used its full height budget," not "found where the terrain
    naturally closes" — the two are not the same claim, and the old
    wording overclaimed confidence a reader would reasonably use to
    trust one candidate over another. Reworded everywhere this leaked
    into text a person reads: the map popup's confidence note, the CLI's
    per-candidate summary line, and four docstrings/comments
    (`volumes.py`'s `basin_volume()` and `MAX_BASIN_CELLS`,
    `find_sites.py`'s module docstring and the `basin_bounded` dict
    comment) — no numbers changed, this was purely a mischaracterization
    of an existing, correctly-computed field. Also fixed a second,
    smaller issue found while in that code: a stale code comment in
    `index.html` still citing "ENGINEERED's dam axis is essentially
    never found (0/20)" as the reason the dam line isn't drawn — true
    before the containment fix above, false after it (20/20 now) —
    updated so a future reader isn't told the wrong reason for a
    still-correct design choice (the dam line stays hidden because the
    user prefers the lake footprint, not because the axis is unreliable).
    42/42 tests still pass (wording-only change, no logic touched); no
    pipeline re-run needed (the fix doesn't change any written geojson
    field, only how `basin_bounded`'s existing True/False value is
    described in the CLI print and client-side JS).
  - **Known, documented, not fixed this pass**: `basin_volume()`'s only
    protection against the flood crossing a low mountain saddle into an
    unrelated adjacent valley is "don't go more than 2m below the seed's
    *own* elevation" — this deliberately allows genuine interior dips
    (a real requirement, tested, see the "downhill runaway" fix earlier
    in this log) but has no way to distinguish a legitimate interior low
    point from the start of a different valley on the far side of a
    ridge that's still above the seed's elevation. Considered a stricter
    rule (reject any newly-discovered neighbor below the *running* water
    level, not the fixed seed elevation) and rejected it: proved it would
    also reject genuine interior dips reached only via a slightly higher
    connecting cell (walked through the heap-ordering argument for both
    cases) — the two scenarios are provably indistinguishable from
    elevation data alone without a real watershed/depression-filling
    algorithm, which is explicitly out of scope for v1 (see
    ReadmeAi.md's v3 roadmap entry). This is the honest boundary of what
    the current heuristic can promise; the empirical cross-check ratios
    above are the mitigation already in place, not a fix for this
    specific failure mode.
- **2026-09-02** — User looked at NATURAL candidates #5 and #6 on the map
  and flagged both as not making sense: #5 "I can't find the bowl...
  might be one there on the plateau but it will have a small volume;"
  #6 "defently drawed on the middle of the mountain... I can see to the
  south what you wanted to color but it makes no sense the place it was
  coloured." Investigated both with real DEM elevation profiles (8
  directions, 50m steps out to 500-800m) rather than re-deriving the
  containment math in the abstract:
  - #5 (lake 170958, seed elev 996.9m): terrain *rises* in 7 of 8 sampled
    directions (up to +30 to +60m within 300-500m) — the seed is a
    shoulder, not a bowl bottom.
  - #6 (lake 1352457, seed elev 890.2m): same pattern, worse — 7 of 8
    directions rise (up to +40 to +60m), the flood painted a ~950m-wide,
    roughly circular patch straddling the seed, and the one real dip in
    the profile is due south, exactly where the user was looking, well
    outside the seed's own immediate neighborhood.
  - Root cause, checked directly (not assumed): `bowl_required`'s
    `is_bowl` test only asked whether the seed is the lowest point within
    `bowl_window_px=5` (~130m) — far too small a neighborhood for a
    feature the flood then credits with up to `max_basin_radius_m=500m`
    of radius and `max_dam_height_m=60m` of depth. Re-tested both flagged
    seeds against bigger windows: both fail as a local minimum at just
    ~240m, let alone ~500m. Then checked systemically against all 95 of
    the previous NATURAL run's candidates (not just these two): only
    19% would still qualify at a ~240m window, only **4% at ~500m**
    (matching `max_basin_radius_m` — the principled choice: the seed
    should be the true lowest point over the whole area the flood is
    allowed to explore, not just its immediate few pixels). Presented
    this to the user with three options (strict ~500m fix, a looser
    ~240m middle ground, or leave the search alone and just relabel the
    output) before touching anything, given how much it would shrink
    NATURAL's list.
  - User's call: apply the strict fix, and label the surviving results
    as **plateau** depressions rather than "bowls" — matching their own
    read of #5 ("might be one there on the plateau") and the terrain
    character of what a ~500m-neighborhood true-minimum mostly finds in
    Romania's highlands (broad, gently-sloping high ground, not
    steep-walled cirques). Implemented: `NATURAL.bowl_window_px` 5 -> 19
    (~500m at this DEM's ~26m pixel size, deliberately matching
    `max_basin_radius_m`); mode label changed everywhere it's shown to
    "Natural / plateau depression" (map legend, layer control, popups);
    `find_sites.py`'s module docstring and the `NATURAL` definition's own
    comment rewritten with this evidence so a future reader doesn't have
    to re-derive it. 42/42 tests unaffected (none hardcode this
    constant). Full pipeline re-run to see the real before/after —
    results logged separately once that run completes.
- **2026-09-02** — Ran the pipeline with the `bowl_window_px` fix above and
  checked the actual result, individually, rather than trusting the
  aggregate number: NATURAL collapsed from 95 candidates (1 per lake,
  top 20 shown) to **13 lakes total** — consistent with the ~4%
  ballpark predicted before the fix, and matching the module docstring's
  own "these are rare" claim for the first time.
  - The two lakes that started this investigation: lake 1352457 (old
    #6, "middle of the mountain") now produces **no NATURAL candidate at
    all** — no genuine depression exists for it within the search
    window, which matches the user's own read (the coloured shoulder
    made no sense, and the real feature to the south apparently isn't a
    closed depression either). Lake 170958 (old #5) now ranks #13 at a
    *different* location entirely (the old shoulder no longer
    qualifies), with volume dropped from the old 9.33M m³ to **0.86M
    m³** — small, exactly as the user predicted ("might be one there on
    the plateau but it will have a small volume").
  - Spot-checked 4 of the new 13 with the same real-elevation-profile
    method used to diagnose the original bug (8 directions, 50m steps):
    #7 (lake 1359151) and #13 (lake 170958, above) rise in *every*
    sampled direction, strongly (+90 to +180m by 500m) — genuine,
    well-contained depressions. #1 (lake 1356659) and #4 (lake 1357899)
    are mixed: mostly rising, but with a mild decline in 1-2 of the 8
    sampled directions beyond ~250-450m (-10 to -25m) — far softer than
    the old failures (which dropped 40-130m within 100-300m) but a
    reminder that a fixed ~500m/19px window is a big improvement, not a
    perfect guarantee right at its own edge; plausibly a real mountain
    saddle/col rather than a fully enclosed pit. Not chased further —
    logging it honestly rather than either overclaiming the fix is
    perfect or re-opening the investigation for a marginal case.
  - ENGINEERED's output is byte-for-byte the same as the previous run
    (unaffected by this change, as expected — confirmed by diffing the
    printed top-20 against the prior log). 42/42 tests pass. Map
    re-served; `docs/candidates_natural.geojson`, `basins_natural.
    geojson`, `contours_natural.geojson` all regenerated and validated
    as parseable JSON.
- **2026-09-02** — Continuation of the window-truncation fix above: user asked why
  distance to another candidate ("#4") looked wrong too, which led to actually reading
  the underlying elevation data for it, which surfaced a much bigger, pre-existing
  problem. Full trail, in order:
  1. Tried padding the search window by `mode.max_basin_radius_m` (2000m for
     ENGINEERED, matching how far the flood-fill can actually reach from a seed, not
     just the ~500m the bowl-check needed) instead of a flat +400m. Checked EVERY
     candidate (not just the shortlist) near Lake Tarnița with the fully-padded window:
     **175 of 522 "passed" the existing dam_line_endpoints containment check with
     basin_volume_m3 of 40-220 million m^3 over 1-4 km^2** — physically absurd density
     (Vidraru, one of Romania's largest real dams, holds ~465M m^3; this implied dozens
     of Vidraru-scale reservoirs within 2km of one lake). Traced one concretely: seed on
     a ridge nose, terrain drops 100-288m in 8 of 12 sampled directions within 500m, and
     the flood sprawls 2km across the one direction that doesn't — dam_line_endpoints
     only samples +/-400m from the seed, so it never sees that the "basin" behind it is
     an open sprawl. **Reverted the padding to a flat +400m** rather than ship this —
     the window-truncation bug had been an *accidental* cap on how much damage this
     pre-existing containment weakness could do; removing it without also fixing
     containment made results worse, not better.
  2. Directly checked whether this was already live in the *shipped* top-20 (not just a
     theoretical near-edge case): yes — **5 of 20 ENGINEERED candidates whose
     basin_volume fed the headline MW directly** (not capped by the existing lake:
     lakes 1293/170958/170671/169061/14030) **dropped 240-443m within 1000m in 10-11 of
     12 sampled directions**, yet had passed containment. This was real, current, and
     affecting a quarter of the published top-20.
  3. Implemented `basin_wall_fraction()` (find_sites.py) to replace dam_line_endpoints
     as ENGINEERED's actual gate: checks the flooded basin's OWN boundary (the
     `visited` mask from `basin_volume()`, already computed, previously discarded) for
     what fraction is genuine topographic wall vs. open terrain the flood only stopped
     at because of `basin_volume()`'s own downhill-tolerance heuristic — not a short
     fixed-radius probe from the seed. First version had a real bug: it excluded any
     neighbor near/above `max_dam_height_m` as "budget-limited, ambiguous" — which
     silently discarded the *strongest* wall evidence available (a genuine tall wall
     usually exceeds the height cap) and made the check reject nearly everything,
     including a known-good real candidate (0 wall_cells reported for it — caught
     because that's physically impossible for any basin with real terrain around it).
     Fixed by only excluding radius-cap-limited neighbors; a height-cap-excluded
     neighbor is, by construction, always >= water_level, so it already and correctly
     counts as a wall without a separate carve-out.
  4. Calibrated `MIN_WALL_FRACTION` against two real, contrasting candidates: the known-
     bad ridge-nose seed above scored 0.14 walled; a plausible real valley-dam candidate
     (lake 1360316's previous top-1 ENGINEERED result) scored 0.57. Set to **0.5**,
     which cleanly separates the two.
  5. Found a second, subtler issue AFTER recalibrating and re-running the full pipeline:
     **all 20 of the new top-20 ENGINEERED candidates scored 0.50-0.58** — clustered
     tightly at the threshold, not comfortably above it. Root cause understood, not a
     bug to "fix" with a different number: `best_new_site()` picks the highest-MW
     candidate among everything that clears the gate, and a less-contained basin
     generally grows bigger (more MW) right up until it fails — so the ranking itself is
     adversarial to the containment check, and raising the threshold would only relocate
     the same clustering, not remove it. Response: don't hide this behind a pass/fail
     boolean — `wall_fraction` is now a first-class reported field (geojson property,
     CLI summary line, map popup "Containment check" row, mirrored `MIN_WALL_FRACTION`
     constant in index.html) so a reader can see exactly how close to the line each
     ENGINEERED candidate actually sits, same transparency pattern as `basin_bounded`.
  6. Net effect after all of the above: ENGINEERED coverage now 126 lakes (down from
     269 at the start of this session); NATURAL unaffected (6 lakes, unchanged from the
     `bowl_window_px` fix). Candidate distances dropped substantially (mostly <1000m
     from the anchor lake now, vs. clustering near the 2000m search edge before) —
     consistent with genuinely-contained valley crossings being found close to the lake
     rather than sprawling floods being found far away. `dam_line_endpoints`'s
     illustrative axis (concrete-volume estimate) now rarely finds anything for
     ENGINEERED specifically (its narrow +/-400m probe is a worse fit for these
     properly-contained-but-large basins than it was for the old, smaller ones) — a
     known, minor loss of a secondary display field, not a correctness issue; flagged
     here rather than silently accepted.
  7. Two real-world regression tests (`TestBasinVolumeRealWorld` in test_volumes.py)
     needed updating along the way, each for a concrete, checked reason recorded in
     their own comments: `test_tiny_anchor_lake_caps_a_much_bigger_basin`'s artificial
     cap dropped from 1M to 300K m3 once the window fix changed which real candidate won
     near Tarnița; both Tarnița ENGINEERED tests continued to need real search results
     as ENGINEERED's containment logic was rewritten twice more in this same entry —
     final state re-verified passing against real DEM data, not just mocked. 45/45 tests
     pass (3 new: `TestBasinWallFraction`, calibrated against synthetic enclosed-pit,
     plateau-sprawl, and radius-limited-plain cases). Structural re-audit (head/distance
     recomputation, basin-contains-site, usable<=basin) re-run clean on the final output,
     same methodology as the 2026-09-01 QA pass.
- **2026-09-02** — User checked ENGINEERED #10 (lake 169296) on real satellite imagery
  ("i checked it google maps and there is a dam on the top of the montain") — exactly
  the clustering-at-the-threshold risk flagged (but not resolved) in the entry above,
  now with a concrete instance. Investigated:
  - Pulled the real elevation profile at the seed: terrain drops 100-175m within
    200-500m in 7 of 12 sampled directions (essentially every direction except a
    ~120deg arc to the southwest) — a promontory, not a valley, matching what the user
    saw. `wall_fraction` for this candidate was exactly 0.500, the lowest passing value.
  - Checked whether a better candidate existed nearby that the ranking had passed over
    (the same failure mode found for Tarnița earlier): no — swept the ENTIRE candidate
    grid for this lake (506 points, not just the 40-shortlist), and **0.54 is the
    highest wall_fraction achievable anywhere in its whole 2km search radius**. This
    lake genuinely has no real valley-dam site nearby; 0.5 was letting it through
    anyway, not just ranking marginal-but-real sites too tightly.
  - Tried a more targeted "near-seed-only" wall fraction (restricting the same check to
    just the terrain within 150-500m of the seed, on the theory that a real dam site
    should look like a valley in its *immediate* vicinity specifically, not just
    somewhere within its much larger basin) to see if it separated this case more
    clearly than the whole-basin fraction. It didn't: lake 169296 scored 0.00-0.46 at
    150-500m, but the calibration "good" example (lake 1360316) also scored low there
    (0.21-0.50) — not a clean separation, so not adopted; noted here so it isn't
    silently re-tried later without this result.
  - Raised `MIN_WALL_FRACTION` 0.5 -> 0.6 instead — a real, if less elegant, fix: it
    excludes lake 169296 entirely (max 0.54 < 0.6) while lake 1360316's true maximum
    (rechecked properly this time, full-grid: 0.683, not just the one seed tested
    before) clears it with real margin. Full pipeline re-run: **ENGINEERED coverage
    97 lakes (down from 126)**; lake 169296 no longer appears anywhere in the results.
    wall_fraction across the new top-20 now spans 0.616-1.000 (several at 0.95-1.0) —
    materially less clustered than the old 0.50-0.58 band, though the top 2 (highest
    MW) are still the lowest of the twenty at 0.616/0.622, consistent with the
    clustering dynamic being inherent, not eliminated. Spot-checked both with real
    elevation profiles: both now show a genuine valley shape — a coherent ~150-180deg
    arc of rising terrain opposite a coherent arc of dropping terrain (the valley's
    open/downstream side) — a real qualitative difference from #10's scattered,
    mostly-dropping-in-every-direction pattern.
  - Two more real-world ENGINEERED tests needed updating as a direct result: Tarnița's
    own best achievable wall_fraction (0.598) now falls just under 0.6, so
    `best_new_site()` correctly returns None there — added
    `test_tarnita_correctly_finds_no_engineered_candidate` as a positive regression
    test for that (symmetric with the existing plateau-peak test), and moved the two
    tests that need ENGINEERED to actually find something (`test_valley_seed_near_a
    _real_lake_gives_a_plausible_volume`, renamed from the Tarnița-specific version, and
    `test_tiny_anchor_lake_caps_a_much_bigger_basin`) to lake 1360316, whose margin
    above the gate was re-verified properly this time (full-grid sweep, not one seed).
    46/46 tests pass. Structural audit (head/distance recomputation, basin-contains-
    site, usable<=basin) re-run clean.
  - Honest bottom line, not smoothed over: `wall_fraction` is a real improvement over
    both the original dam_line_endpoints gate and the first (buggy) version of this
    check, and 0.6 is measurably better calibrated than 0.5 — but it's still a
    geometric proxy, not a substitute for looking at the actual place. The clustering
    dynamic documented in the prior entry is structural (MW-maximizing selection will
    always favor whatever is loosest among what passes, at any threshold) and wasn't
    eliminated here, only pushed to a higher, better-populated floor. A "passed"
    result — especially one near the current threshold, which `wall_fraction` now makes
    visible per-candidate rather than hidden — should still be read as "not obviously
    fake," not "confidently real."
- **2026-09-02** — User: "add a constant a[n]d limit the upper side of the dam to
  200m, everything that is larger than that is too long to be practical." Added
  `MAX_DAM_LENGTH_M = 200` and changed `DAM_LINE_HALF_LENGTH_M`'s upper bound from the
  old 400 (800m total) to `MAX_DAM_LENGTH_M / 2` (200m total) — min half-length (80,
  i.e. 160m minimum) left as-is, the request was specifically about the upper side.
  This constant does double duty, both intentional: it clamps the illustrative dam
  line/concrete-volume estimate's length, AND — since dam_line_endpoints() samples
  exactly half_length_m out from the seed to test for a rise on both sides — it's also
  now the actual search distance for finding a valid crossing at all. A basin whose real
  valley is wider than 200m at the seed now correctly reports "no dam axis found — no
  concrete estimate" rather than drawing a shortened, misleadingly-clamped line across
  it. Does NOT affect which candidates get selected: dam_line_endpoints stopped being
  ENGINEERED's containment gate earlier this session (basin_wall_fraction() replaced
  it) and was never NATURAL's gate — confirmed by re-running the full pipeline: lake
  coverage identical (6 natural, 97 engineered) before and after, only the
  dam_height_m/dam_length_m/concrete_volume_m3 fields (and how often they're present)
  changed. As expected, this tightened probe distance means ENGINEERED's already-rare
  dam-axis detection (most basins here are wider than a single short crossing, see the
  entries above on basin_wall_fraction) dropped further, to 0/20 in the current top
  list — an honest "we don't have a confident concrete estimate for a valley this wide
  with a wall this short" rather than continuing to imply a 200m dam elsewhere. 46/46
  tests pass unaffected (test_length_is_clamped_to_configured_range reads the constant
  directly rather than a hardcoded number, so it re-verified against the new value
  automatically).
- **2026-09-02** — User: "#3 makes no sens, it is just below the existing dam."
  Investigated concretely:
  - The bowl itself is real terrain (elevation profile rises in nearly every direction),
    ruling out the class of bug fixed earlier this session (fake sprawl/promontory).
  - The actual issue: `best_new_site()`'s "don't seed too close to the existing lake"
    check only ever excluded a circle around the lake's single anchor point (all
    `lakes.geojson` stores) — not the lake's real shape. For a large or elongated
    reservoir (common for HydroLAKES lakes, which follow valleys) the anchor point can
    sit a kilometer or more from the actual shoreline. This candidate was reported
    1273m from the lake (measured from the anchor point) but its seed was really only
    557m from the lake's true polygon edge, and the resulting basin footprint reached
    to within 246m — close enough to visually read as "just below the existing dam."
  - Fixed properly, not just re-measured: added `load_lake_polygons()` (loads the real
    HydroLAKES geometry once for the whole country, ~2200 polygons, cheap — keyed by
    Hylak_id) and threaded the specific polygon through to `best_new_site()`, which now
    rasterizes it and measures true distance with `scipy.ndimage.distance_transform_edt`
    (sampling in real pixel_dy_m/pixel_dx_m, not distorted by non-square pixels) instead
    of a circle from one interior point. Falls back to the old circle only if a lake's
    polygon can't be found (shouldn't normally happen, same source).
  - This alone didn't remove the flagged candidate (557m still clears the old 100m
    buffer) — asked the user how the exclusion should actually work, given it also
    doesn't stop the flood itself from growing toward the lake after seeding (only
    where a seed can *start*, not how close basin_volume() then lets it grow — flagged
    as a real, separate, NOT-made change: capping flood growth near an existing lake
    is a genuine algorithm change, not a constant tweak, and wasn't bundled in here).
    User's call: raise `LAKE_EXCLUSION_BUFFER_M` 100 -> 500 (seed-only, not the more
    invasive flood-growth-capping option).
  - Re-ran the full pipeline: lake 1358492 (source of the flagged candidate #3) no
    longer produces any NATURAL candidate at all. NATURAL coverage 6 -> 5 lakes,
    ENGINEERED 97 -> 96 (this buffer applies to both modes' seed selection). 46/46
    tests pass, structural audit (head/distance recomputation, basin-contains-site,
    usable<=basin) re-run clean.
