"""Sweep min_hole_area_m2 -- mesure granularite sur emprise hull FFCO.

Quadruplet par classe : couverture%, n poly, mediane mm2, %<1mm2.
Garde-fou : max% polygone 406 (anti-percolation, plancher 7.4%).

Usage :
    python scripts/sweep_holes.py
"""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys

import geopandas as gpd
import numpy as np
import shapely.geometry as sg
from shapely.ops import unary_union

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"

# Classes vegetation OOM -> code ISOM
# "bonne visibilite" = variantes 407/409 : exclues (pipeline ne les produit pas)
FFCO_VEG_NAMES = {
    "course lente": 406,
    "marche": 408,
    "progression": 410,
}
FFCO_EXCLUDE = "bonne"  # exclut 407 ("course lente, bonne visib") et 409 ("marche, bonne visib")

# Valeurs sweep
HOLE_VALUES = [30, 100, 300, 1000, 3000]

SCALE = 10_000  # 1:10000
MM2_PER_M2 = 1e6 / (SCALE ** 2)  # m2 terrain -> mm2 carte


def load_ffco_veg() -> gpd.GeoDataFrame:
    """Charge les polygones vegetation 406/408/410 de grimbosq.gpkg via ogr2ogr."""
    r = subprocess.run(
        ["ogr2ogr", "-f", "GeoJSON", "-oo", "ENCODING=ISO-8859-1",
         "/vsistdout/", str(FFCO_GPKG), "grimbosq_areas"],
        capture_output=True, errors="replace",
    )
    fc = json.loads(r.stdout)
    records = []
    for feat in fc["features"]:
        name = feat["properties"].get("Name", "")
        cls = None
        for key, code in FFCO_VEG_NAMES.items():
            if key in name and FFCO_EXCLUDE not in name:
                cls = code
                break
        if cls is None:
            continue
        try:
            geom = sg.shape(feat["geometry"])
            if not geom.is_valid:
                geom = geom.buffer(0)
        except Exception:
            continue
        records.append({"class": cls, "geometry": geom})
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:2154")


def build_hull(ffco_veg: gpd.GeoDataFrame) -> sg.Polygon:
    """Convex hull de l'union des polygones vegetation FFCO."""
    return unary_union(ffco_veg.geometry.values).convex_hull


def quadruplet(gdf: gpd.GeoDataFrame, hull: sg.Polygon, cls: int) -> tuple:
    """(cov_pct, n, median_mm2, pct_lt1mm2) pour une classe, clippee sur hull."""
    sub = gdf[gdf["class"] == cls].copy()
    if sub.empty:
        return 0.0, 0, 0.0, 0.0
    sub = sub.clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return 0.0, 0, 0.0, 0.0
    areas_m2 = sub.geometry.area
    hull_area_m2 = hull.area
    cov = areas_m2.sum() / hull_area_m2 * 100
    n = len(sub)
    areas_mm2 = areas_m2 * MM2_PER_M2
    median_mm2 = float(np.median(areas_mm2))
    pct_lt1 = float((areas_mm2 < 1.0).mean() * 100)
    return cov, n, median_mm2, pct_lt1


def max_pct_406(gdf: gpd.GeoDataFrame, hull: sg.Polygon) -> float:
    """Concentration du plus gros polygone 406 (sur hull), garde-fou percolation."""
    sub = gdf[gdf["class"] == 406].copy().clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return 0.0
    areas = sub.geometry.area
    return float(areas.max() / areas.sum() * 100)


def run_with(cfg_base: dict, hole_val: float) -> gpd.GeoDataFrame:
    cfg = copy.deepcopy(cfg_base)
    cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]][
        "min_hole_area_m2"
    ] = hole_val
    gdf, _ = run_pipeline(str(CLASSIFIED), cfg)
    return gdf


def load_config() -> dict:
    import yaml
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def print_header() -> None:
    print()
    print(f"{'hole':>6}  {'cls':>3}  {'cov%':>6}  {'n':>5}  {'med mm2':>8}  {'%<1mm2':>7}  {'max%406':>8}")
    print("-" * 62)


def print_row(hole: float, cls: int, q: tuple, mx: float | None) -> None:
    cov, n, med, plt = q
    mx_str = f"{mx:>8.1f}" if mx is not None else " " * 9
    print(f"{hole:>6}  {cls:>3}  {cov:>6.1f}  {n:>5}  {med:>8.2f}  {plt:>7.1f}{mx_str}")


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")
    if not FFCO_GPKG.exists():
        sys.exit(f"ABSENT : {FFCO_GPKG}")

    cfg = load_config()
    profile = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    current_hole = profile["min_hole_area_m2"]
    min_areas = profile["min_area_m2"]

    print(f"Sweep min_hole_area_m2 -- sigma=1.0, fd[406]=2")
    print(f"min_area : 406={min_areas[406]} 408={min_areas[408]} 410={min_areas[410]} (inchange)")
    print(f"min_hole actuel : {current_hole} m2")
    print()
    print("Chargement FFCO Grimbosq (grimbosq.gpkg) ...")
    ffco_veg = load_ffco_veg()
    hull = build_hull(ffco_veg)
    hull_ha = hull.area / 1e4

    print(f"Hull FFCO : {hull_ha:.1f} ha (convex hull vegetation 406+408+410)")
    print()

    # Cibles FFCO sur hull
    print("Cibles FFCO sur emprise hull :")
    for cls in [406, 408, 410]:
        q = quadruplet(ffco_veg, hull, cls)
        print(f"  {cls}: cov={q[0]:.1f}%  n={q[1]}  med={q[2]:.2f}mm2  %<1mm2={q[3]:.1f}%")

    print_header()

    for hole_val in HOLE_VALUES:
        gdf = run_with(cfg, hole_val)
        mx = max_pct_406(gdf, hull)
        for i, cls in enumerate([406, 408, 410]):
            q = quadruplet(gdf, hull, cls)
            print_row(hole_val, cls, q, mx if i == 0 else None)
        sys.stdout.flush()

    print()
    print("Rappel cibles FFCO : 406=5.17mm2 | 408=2.31mm2 | 410=1.39mm2")
    print("Garde-fou max%406 : plancher 7.4% (infranchissable), percolation > 10%")


if __name__ == "__main__":
    main()
