"""Sweep closing_kernel_size -- fermeture morphologique raster avant polygonize.

Mesure le quadruplet (cov%, n, mediane mm2, %<1mm2) sur emprise hull FFCO
et le garde-fou max%406 a chaque valeur de noyau.

Usage :
    python scripts/sweep_closing.py
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
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"

KERNEL_VALUES = [0, 3, 5, 7]  # 0=off, 3=3x3 (1m), 5=5x5 (2m), 7=7x7 (3m)

SCALE = 10_000
MM2 = 1e6 / SCALE**2


def load_ffco_hull() -> sg.Polygon:
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
        for key, code in [("course lente", 406), ("marche", 408), ("progression", 410)]:
            if key in name and "bonne" not in name:
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
        records.append(geom)
    return unary_union(records).convex_hull


def quadruplet(gdf: gpd.GeoDataFrame, hull: sg.Polygon, cls: int) -> tuple:
    sub = gdf[gdf["class"] == cls].copy().clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return 0.0, 0, 0.0, 0.0
    areas = sub.geometry.area
    hull_ha = hull.area / 1e4
    cov = areas.sum() / hull.area * 100
    n = len(sub)
    mm2 = areas * MM2
    return cov, n, float(np.median(mm2)), float((mm2 < 1.0).mean() * 100)


def max_pct_406(gdf: gpd.GeoDataFrame, hull: sg.Polygon) -> float:
    sub = gdf[gdf["class"] == 406].copy().clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return 0.0
    areas = sub.geometry.area
    return float(areas.max() / areas.sum() * 100)


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def run_with(cfg_base: dict, kernel: int) -> gpd.GeoDataFrame:
    cfg = copy.deepcopy(cfg_base)
    cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]][
        "closing_kernel_size"
    ] = kernel
    gdf, _ = run_pipeline(str(CLASSIFIED), cfg)
    return gdf


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")
    if not FFCO_GPKG.exists():
        sys.exit(f"ABSENT : {FFCO_GPKG}")

    cfg = load_config()
    profile = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    print(f"Sweep closing_kernel -- sigma=1.0, fd=2, min_area 406/408/410={profile['min_area_m2'][406]}/{profile['min_area_m2'][408]}/{profile['min_area_m2'][410]}")
    print()

    print("Chargement hull FFCO ...")
    hull = load_ffco_hull()
    print(f"Hull : {hull.area/1e4:.1f} ha")
    print()

    print("Cibles FFCO sur hull :")
    print("  406 : cov=19.3%  n=463  med=5.17mm2  %<1mm2=3.7%")
    print("  408 : cov=6.9%   n=432  med=2.31mm2  %<1mm2=13.4%")
    print("  410 : cov=8.0%   n=363  med=1.39mm2  %<1mm2=32.0%")
    print()

    hdr = f"{'kern':>5}  {'cls':>3}  {'cov%':>6}  {'n':>5}  {'med mm2':>8}  {'%<1mm2':>7}  {'max%406':>8}"
    print(hdr)
    print("-" * 58)

    for kernel in KERNEL_VALUES:
        gdf = run_with(cfg, kernel)
        mx = max_pct_406(gdf, hull)
        for i, cls in enumerate([406, 408, 410]):
            q = quadruplet(gdf, hull, cls)
            cov, n, med, plt = q
            mx_str = f"{mx:>8.1f}" if i == 0 else " " * 9
            print(f"{kernel:>5}  {cls:>3}  {cov:>6.1f}  {n:>5}  {med:>8.2f}  {plt:>7.1f}{mx_str}")
        sys.stdout.flush()

    print()
    print("Rappel : max%406 > 10% = zone percolation (plancher 7.4% sur bbox totale)")
    print("Noyau 3x3 = rayon 1m | 5x5 = 2m | 7x7 = 3m")


if __name__ == "__main__":
    main()
