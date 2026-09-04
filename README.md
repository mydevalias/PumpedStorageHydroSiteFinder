# Pumped-Storage Hydro Site Finder — Romania

A terrain-driven search for pumped-storage hydroelectric sites: for every
existing lake/reservoir in Romania, it looks at the real elevation data
around it and asks whether a second reservoir could realistically be paired
with it — high enough for real head, close enough to be practical, and
actually buildable given the terrain, not just theoretically nearby on a map.

**[Open the map →](https://mydevalias.github.io/PumpedStorageHydroSiteFinder/)**
*(once GitHub Pages is enabled on `docs/` — see below if it's not live yet)*

## What it finds

Every candidate falls into one of three categories, because "build a second
reservoir" means three genuinely different things depending on the terrain:

| Mode | What it looks for | Real-world precedent |
|---|---|---|
| **Natural bowl** | An already-existing depression — no wall needed beyond a modest one | A pre-existing pit or basin |
| **Engineered dam** | A valley narrow enough to wall off with a single dam | Most real pumped-storage projects, e.g. Vidraru, Lotru–Ciunget |
| **Plateau** | Flat high ground diked around its perimeter — no valley or bowl involved | Romania's own planned [Tarnița–Lăpuștești](https://ro.wikipedia.org/wiki/Hidrocentrala_Tarni%C8%9Ba%E2%80%93L%C4%83pu%C8%99te%C8%99ti) project |

Each candidate reports estimated power (MW), storage energy (MWh), head,
distance from the existing lake, a real volume estimate (not a guess — the
actual terrain footprint, flood-filled or diked from the DEM), and a
containment check specific to its mode, all shown on the map with the real
computed shape of the new reservoir, not a placeholder circle.

## Status

Working, but still v1 and worth reading with that in mind:

- **Romania only** — the pipeline is written to be portable to other
  countries (see `DATA_SOURCES.md`), just not run anywhere else yet.
- **A heuristic search, not a survey** — every number is grounded in real
  elevation data and cross-checked against real Romanian hydro projects
  (Tarnița, Vidraru, Lotru–Ciunget) wherever possible, but this is terrain
  analysis from open elevation data, not a geological or engineering study.
  Treat results as "worth a closer look," not "ready to build."
- **Actively corrected in the open** — `DATA_SOURCES.md` is a running,
  dated log of every bug found and fixed this way, including several that
  came from checking specific candidates against real satellite imagery and
  finding they didn't hold up. Nothing here is presented as more certain
  than it's been checked to be.

## How to run it

```bash
# 1. Set up the environment (once)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Fetch the data (once — cached after that)
.venv/bin/python scripts/fetch_data.py

# 3. Run the search (fast — re-run anytime you tweak scripts/find_sites.py)
.venv/bin/python scripts/find_sites.py

# 4. View the map locally
cd docs && python3 -m http.server 8934
# open http://localhost:8934
```

Full details — every config constant, what each script does, the exact
output files — are in [`ReadmeAi.md`](ReadmeAi.md).

## Data sources

- **Terrain**: [Copernicus GLO-30](https://registry.opendata.aws/copernicus-dem/)
  DEM (30m resolution, AWS Open Data, no auth)
- **Lakes/reservoirs**: [HydroLAKES](https://www.hydrosheds.org/products/hydrolakes)
  v1.0 (CC-BY 4.0)
- **Country boundary**: [Natural Earth](https://www.naturalearthdata.com/)

Every material decision — why a threshold is what it is, what real project
it's calibrated against, what turned out to be wrong and how it was fixed —
is logged with sources in [`DATA_SOURCES.md`](DATA_SOURCES.md).

## Related

- [Global Pumped Hydro Atlas](https://www.dropbox.com/scl/fi/8q3aflrhgxgnrubhpmge1/190606-Global-pumped-hydro-Atlas.pdf?rlkey=qm0422re035z4ntwofijho3ad&e=3&dl=0) —
  a global reference survey (ANU), useful context for how this kind of site
  search is normally done at a much larger scale.
