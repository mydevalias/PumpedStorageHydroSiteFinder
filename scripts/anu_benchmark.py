"""Benchmark our candidates against an independent, published study: the ANU Global
Pumped Hydro Energy Storage Atlas (RE100 Group, Australian National University,
https://re100.eng.anu.edu.au/global — Stocks, Stocks, Lu, Cheng & Blakers). Their
"Bluefield" atlas is the same problem this project solves: one EXISTING reservoir
paired with one NEW reservoir, found by a GIS search over a global DEM. Comparing
against it is external validation — "does an independent university study find the
same places we do, and what does each find that the other doesn't" — not the
self-validation everything else in this project rests on.

Data access: ANU serves the atlas from a public GeoServer (WFS, GeoJSON output);
this module fetches the Bluefield layers for Romania's bounding box once and caches
them under data/anu/ (gitignored, like every other raw download here). ANU's stated
terms are attribution, not a formal open licence ("In publications or developments
that use this information please acknowledge the RE100 Group, Australian National
University" — re100.eng.anu.edu.au/global/#access, checked 2026-09-18), so the raw
data is NOT redistributed: only our own derived comparison numbers are written to
docs/, with that acknowledgement.

What "match" means here, and why it's deliberately loose: ANU reports each pair as a
line between two reservoirs plus the NEW reservoir's footprint polygon. One of our
candidates matches an ANU pair if our new-site point lies within MATCH_RADIUS_M of
that polygon (0m if inside it). Their reservoirs are sized in fixed energy classes
(2 GWh/6h up to 500 GWh/50h) and selected under their own rules (head 100-800m,
slope >= 1:20, volume >= 1 GL, outside protected areas) — none of which are ours —
so exact coincidence isn't expected; "same hillside" is the meaningful question.

Run:  .venv/bin/python scripts/anu_benchmark.py   (after find_sites.py)
"""

import json
import re
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from fetch_data import BBOX, COUNTRY_NAME, DATA_DIR, LAKES_OUT_PATH

ANU_WFS_URL = "https://re100.anu.edu.au/geoserver/global_bluefield/wfs"
ANU_ATTRIBUTION = ("RE100 Group, Australian National University, "
                   "http://re100.eng.anu.edu.au (Global Pumped Hydro Energy Storage Atlas, Bluefield)")
# Every Bluefield energy class the atlas publishes (larger classes exist but return
# nothing for Romania — checked 2026-09-18: 1500 GWh and 5000 GWh both came back empty).
ANU_CLASSES = ["2gwh_6h", "5gwh_18h", "15gwh_18h", "50gwh_18h", "150gwh_50h", "500gwh_50h"]
ANU_DIR = DATA_DIR / "anu"
MATCH_RADIUS_M = 1000.0  # our site point to the edge of ANU's new-reservoir polygon —
                          # roughly the size of one of their smaller reservoirs, so
                          # "adjacent on the same hillside" counts, "next valley" doesn't
MODES = ["natural", "engineered", "plateau", "watershed", "twinlake"]
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "anu_benchmark.json"


def fetch_anu_bluefield(bbox=BBOX) -> list[Path]:
    """One GeoJSON per energy class, cached. NB: GeoServer's WFS 2.0 wants the bbox as
    lon,lat order for EPSG:4326 here — lat,lon silently returns zero features."""
    ANU_DIR.mkdir(parents=True, exist_ok=True)
    min_lon, min_lat, max_lon, max_lat = bbox
    paths = []
    for cls in ANU_CLASSES:
        path = ANU_DIR / f"bluefield_{cls}.geojson"
        if not path.exists():
            params = {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": f"global_bluefield:{cls}", "outputFormat": "application/json",
                "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326", "srsName": "EPSG:4326",
            }
            response = requests.get(ANU_WFS_URL, params=params, timeout=120)
            response.raise_for_status()
            path.write_bytes(response.content)
        paths.append(path)
    return paths


def _field(description: str, label: str) -> str | None:
    match = re.search(r"<td>" + re.escape(label) + r"<\/td><td>([^<]*)", description or "")
    return match.group(1).strip() if match else None


def parse_anu_pairs(paths: list[Path], country: str = COUNTRY_NAME) -> gpd.GeoDataFrame:
    """One row per ANU reservoir PAIR (their 'pipe' line feature carries the pair's
    numbers in an HTML table; the new reservoir's own polygon is a separate feature
    named by its id, which the pipe's name embeds). Filtered to the given country by
    ANU's own Country field — no boundary clip needed."""
    reservoirs = {}
    pipes = []
    for path in paths:
        energy_class = path.stem.replace("bluefield_", "")
        for feature in json.loads(path.read_text())["features"]:
            props = feature["properties"]
            geom = feature.get("geometry")
            if geom is None:
                continue
            if not props.get("ispipe") and not props.get("ispin") and not props.get("isdam"):
                reservoirs[props["name"]] = shape(geom)  # the NEW reservoir's footprint
            elif props.get("ispipe"):
                desc = props.get("description") or ""
                if _field(desc, "Country") != country:
                    continue
                # "RES_143785 & n46_e022_RES9751": the n..RES.. token is the new reservoir.
                new_id = next((t.strip() for t in props["name"].split("&") if t.strip().startswith("n")), None)
                pipes.append({
                    "pair_name": props["name"],
                    "new_reservoir_id": new_id,
                    "energy_class": energy_class,
                    "anu_class": _field(desc, "Class"),
                    "head_m": float(_field(desc, "Head (m)") or "nan"),
                    "separation_km": float(_field(desc, "Separation (km)") or "nan"),
                    "slope_pct": float(_field(desc, "Average Slope (%)") or "nan"),
                    "volume_gl": float(_field(desc, "Volume (GL)") or "nan"),
                    "energy_gwh": float(_field(desc, "Energy (GWh)") or "nan"),
                    "geometry": shape(geom),
                })
    columns = ["pair_name", "new_reservoir_id", "energy_class", "anu_class", "head_m",
               "separation_km", "slope_pct", "volume_gl", "energy_gwh"]
    gdf = gpd.GeoDataFrame(
        pipes if pipes else {c: [] for c in columns},
        geometry=[p["geometry"] for p in pipes] if pipes else [], crs="EPSG:4326",
    )
    # A pair named "RES_a & RES_b" is two EXISTING reservoirs (ANU's own twin-lake case,
    # 2 of Romania's 1560 pairs) — no new reservoir, so no polygon to match against.
    gdf["reservoir_polygon"] = [reservoirs.get(i) for i in gdf["new_reservoir_id"]]
    return gdf


def _meters_per_degree(lat: float) -> tuple[float, float]:
    import math
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    return m_per_deg_lon, m_per_deg_lat


def match_sites_to_anu(site_points: list[Point], anu: gpd.GeoDataFrame,
                       radius_m: float = MATCH_RADIUS_M) -> list[int | None]:
    """For each of our site points, the index of the nearest ANU pair whose NEW
    reservoir polygon is within radius_m (or None). Distances are computed using
    equirectangular scaling (accounting for both lat and lon degrees)."""
    import shapely.affinity
    from shapely.geometry import box

    polys = [p for p in anu["reservoir_polygon"] if p is not None]
    poly_rows = [i for i, p in enumerate(anu["reservoir_polygon"]) if p is not None]
    if not polys:
        return [None] * len(site_points)
    tree = STRtree(polys)
    out = []
    for pt in site_points:
        m_per_deg_lon, m_per_deg_lat = _meters_per_degree(pt.y)
        d_lon = radius_m / m_per_deg_lon
        d_lat = radius_m / m_per_deg_lat
        query_box = box(pt.x - d_lon, pt.y - d_lat, pt.x + d_lon, pt.y + d_lat)
        candidates = tree.query(query_box)
        best, best_d = None, None
        pt_m = Point(pt.x * m_per_deg_lon, pt.y * m_per_deg_lat)
        for k in candidates:
            poly_m = shapely.affinity.scale(polys[k], xfact=m_per_deg_lon, yfact=m_per_deg_lat, origin=(0, 0))
            d_m = poly_m.distance(pt_m)
            if d_m <= radius_m and (best_d is None or d_m < best_d):
                best, best_d = poly_rows[k], d_m
        out.append(best)
    return out


def _load_ours(path: Path) -> gpd.GeoDataFrame | None:
    if not path.exists():
        return None
    gdf = gpd.read_file(path)
    if len(gdf) == 0:
        return gdf
    gdf["site_point"] = [Point(g.coords[-1]) for g in gdf.geometry]
    return gdf


def benchmark() -> dict:
    anu = parse_anu_pairs(fetch_anu_bluefield())
    n_pairs = len(anu)
    unique_reservoirs = anu["new_reservoir_id"].nunique()

    result = {
        "attribution": ANU_ATTRIBUTION,
        "match_radius_m": MATCH_RADIUS_M,
        "anu_pairs_in_country": n_pairs,
        "anu_unique_new_reservoirs": int(unique_reservoirs),
        "anu_head_m": {"min": float(anu["head_m"].min()), "median": float(anu["head_m"].median()),
                       "max": float(anu["head_m"].max())},
        "modes": {},
        "matched_displayed": [],  # per displayed candidate, for the map popup
    }

    anu_matched_by_any_raw = set()
    for mode in MODES:
        raw = _load_ours(DATA_DIR / f"candidates_{mode}_all.geojson")
        top = _load_ours(Path(__file__).resolve().parent.parent / "docs" / f"candidates_{mode}.geojson")
        entry = {}
        for label, gdf in (("raw", raw), ("displayed", top)):
            if gdf is None or len(gdf) == 0:
                entry[label] = {"count": 0 if gdf is not None else None, "with_anu_counterpart": 0}
                continue
            idx = match_sites_to_anu(list(gdf["site_point"]), anu)
            hits = [i for i in idx if i is not None]
            entry[label] = {
                "count": int(len(gdf)),
                "with_anu_counterpart": len(hits),
                "fraction_with_anu_counterpart": round(len(hits) / len(gdf), 3),
            }
            if label == "raw":
                anu_matched_by_any_raw.update(anu.iloc[i]["new_reservoir_id"] for i in hits)
            else:
                # Head agreement on the matched displayed ones — a real cross-check of
                # our head_from_water_levels() against an independent computation.
                diffs = []
                for row_i, i in enumerate(idx):
                    if i is None:
                        continue
                    ours = gdf.iloc[row_i]
                    theirs = anu.iloc[i]
                    diffs.append(abs(float(ours["head_m"]) - theirs["head_m"]) / theirs["head_m"])
                    result["matched_displayed"].append({
                        "mode": mode, "rank": int(ours["rank"]), "lake_id": int(ours["lake_id"]),
                        "anu_pair": theirs["pair_name"], "anu_class": theirs["anu_class"],
                        "anu_energy_class": theirs["energy_class"],
                        "anu_head_m": theirs["head_m"], "our_head_m": float(ours["head_m"]),
                        "anu_volume_gl": theirs["volume_gl"],
                        "our_basin_volume_gl": float(ours["basin_volume_million_m3"]),
                    })
                if diffs:
                    diffs.sort()
                    entry["displayed"]["median_abs_head_diff_fraction"] = round(diffs[len(diffs) // 2], 3)
        result["modes"][mode] = entry

    result["anu_reservoirs_recovered_by_any_raw_candidate"] = len(anu_matched_by_any_raw)
    result["anu_recall_fraction"] = round(len(anu_matched_by_any_raw) / unique_reservoirs, 3) if unique_reservoirs else None
    return result


def main() -> None:
    result = benchmark()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2))

    print(f"ANU Bluefield atlas, {COUNTRY_NAME}: {result['anu_pairs_in_country']} reservoir pairs "
          f"({result['anu_unique_new_reservoirs']} distinct new-reservoir sites), "
          f"head {result['anu_head_m']['min']:.0f}-{result['anu_head_m']['max']:.0f}m "
          f"(median {result['anu_head_m']['median']:.0f}m)")
    print(f"Match = our new-site point within {MATCH_RADIUS_M:.0f}m of an ANU new-reservoir polygon.\n")
    for mode, entry in result["modes"].items():
        for label in ("raw", "displayed"):
            e = entry[label]
            if e["count"] is None:
                print(f"  {mode:11s} {label:9s}: (no file)")
                continue
            extra = (f", median |head diff| {e['median_abs_head_diff_fraction']:.0%}"
                     if "median_abs_head_diff_fraction" in e else "")
            frac = f" ({e['fraction_with_anu_counterpart']:.0%})" if e["count"] else ""
            print(f"  {mode:11s} {label:9s}: {e['with_anu_counterpart']}/{e['count']} have an ANU counterpart{frac}{extra}")
    print(f"\n  ANU sites recovered by at least one of our raw candidates (any mode): "
          f"{result['anu_reservoirs_recovered_by_any_raw_candidate']}/{result['anu_unique_new_reservoirs']} "
          f"= {result['anu_recall_fraction']:.0%}")
    print(f"\nwrote {OUT_PATH}\nAcknowledgement: {ANU_ATTRIBUTION}")


if __name__ == "__main__":
    main()
