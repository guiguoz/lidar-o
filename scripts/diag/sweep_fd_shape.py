"""Sweep fusion_distance_m[406] -- métriques de forme.

Mesure pour chaque fd : compactness (médiane, %<0.3), ext/sqrt(A) (n>15, surface >15),
n_polygones, cov%, max%.

Usage :
    python scripts/sweep_fd_shape.py
"""
from __future__ import annotations

import copy
import math
import pathlib
import sys

import geopandas as gpd
import numpy as np
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
BBOX_HA = 600.5

FD_VALUES = [0.5, 1, 2]


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def _compactness(geom) -> float:
    a = geom.area
    p = geom.length
    if p == 0:
        return 0.0
    return 4 * math.pi * a / (p * p)


def _ext_perimeter(geom) -> float:
    """Périmètre extérieur seulement (sans trous)."""
    from shapely.geometry import Polygon, MultiPolygon
    if isinstance(geom, Polygon):
        return geom.exterior.length
    elif isinstance(geom, MultiPolygon):
        return sum(p.exterior.length for p in geom.geoms)
    return geom.length


def _ext_sqrt_a(geom) -> float:
    a = geom.area
    if a <= 0:
        return 0.0
    return _ext_perimeter(geom) / math.sqrt(a)


def _has_holes(geom) -> bool:
    from shapely.geometry import Polygon, MultiPolygon
    if isinstance(geom, Polygon):
        return len(list(geom.interiors)) > 0
    elif isinstance(geom, MultiPolygon):
        return any(len(list(p.interiors)) > 0 for p in geom.geoms)
    return False


def measure_shape(gdf: gpd.GeoDataFrame) -> dict:
    sub = gdf[gdf["class"] == 406].copy()
    if sub.empty:
        return {}

    areas = sub.geometry.area
    total_ha = areas.sum() / 1e4
    max_pct = areas.max() / areas.sum() * 100
    coverage = total_ha / BBOX_HA * 100
    n = len(sub)

    cpt = sub.geometry.apply(_compactness)
    esa = sub.geometry.apply(_ext_sqrt_a)
    has_hole = sub.geometry.apply(_has_holes)

    # isthmes : ext/sqrt(A) > 15
    mask15 = esa > 15
    n_isthme = mask15.sum()
    ha_isthme = areas[mask15].sum() / 1e4
    pct_surf_isthme = ha_isthme / total_ha * 100 if total_ha > 0 else 0.0

    return {
        "n": n,
        "ha": total_ha,
        "cov_pct": coverage,
        "max_pct": max_pct,
        "cpt_med": float(np.median(cpt)),
        "cpt_p10": float(np.percentile(cpt, 10)),
        "pct_cpt_lt03": float((cpt < 0.3).mean() * 100),
        "pct_troues": float(has_hole.mean() * 100),
        "n_isthme": int(n_isthme),
        "pct_isthme_surf": float(pct_surf_isthme),
    }


def run_with(cfg_base: dict, fd: float) -> dict:
    cfg = copy.deepcopy(cfg_base)
    profile = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    profile["fusion_distance_m"][406] = fd
    gdf, _ = run_pipeline(str(CLASSIFIED), cfg)
    return measure_shape(gdf)


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")

    cfg_base = load_config()
    sigma = cfg_base["vegetation"]["process_hag"]["gaussian_sigma"]
    t406 = cfg_base["vegetation"]["presets"][cfg_base["vegetation"]["active_preset"]]["thresholds"][0]

    print(f"Sweep fd[406] shape quality -- sigma={sigma}, t406={t406}")
    print(f"Baseline fd=2 : 942 poly, cpt_med=0.479, %<0.3=34.3%, 41 isthmes=59.8% surf")
    print()

    hdr = (
        f"{'fd':>5} | {'n':>5} | {'cov%':>6} | {'max%':>6} | "
        f"{'cpt_med':>8} | {'p10_cpt':>8} | {'%<0.3':>7} | "
        f"{'%troués':>8} | {'n_isth':>7} | {'isth_surf%':>10}"
    )
    print(hdr)
    print("-" * len(hdr))

    results = []
    for fd in FD_VALUES:
        print(f"  running fd={fd}...", end="", flush=True)
        m = run_with(cfg_base, fd)
        results.append((fd, m))
        print(
            f"\r{fd:>5} | {m['n']:>5} | {m['cov_pct']:>6.1f} | {m['max_pct']:>6.1f} | "
            f"{m['cpt_med']:>8.3f} | {m['cpt_p10']:>8.3f} | {m['pct_cpt_lt03']:>7.1f} | "
            f"{m['pct_troues']:>8.1f} | {m['n_isthme']:>7} | {m['pct_isthme_surf']:>10.1f}"
        )

    print()
    print("Rappel cibles FFCO : cpt_med=0.669, %<0.3=4.5%, %troués≈1%")
    print("Rappel baseline fd=2 (non-masqué) :")
    print("  942 poly | cov=? | max=? | cpt_med=0.479 | %<0.3=34.3% | %troués=35.1% | n_isth=41 (59.8% surf)")


if __name__ == "__main__":
    main()
