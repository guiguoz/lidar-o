"""Sweep fusion_distance_m[406] -- sigma=1.0 fixe.

Mesure le triplet (count_406, ha_406, max%_406) sur density_hag_classified.tif
sans re-lancer PDAL ni toucher config.yaml.
Deux passes par fd : production (min_area=100) et fd pur (min_area=0).

Usage :
    python scripts/sweep_fd406.py
"""
from __future__ import annotations

import copy
import pathlib
import sys

import geopandas as gpd
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
BBOX_HA = 600.5

FD_VALUES = [0.5, 1, 2, 4, 6]

# remove_isolated reste actif (search_dist=12 m) dans les deux passes.
# Son effet croit quand fd baisse (a fd eleve tout est fusionne, remove_isolated
# ne fait rien ; a fd bas il protege des fragments isoles). Peut aplatir la pente
# du sweep sans changer le classement des configurations.


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def measure_406(gdf: gpd.GeoDataFrame) -> tuple[int, float, float, float]:
    sub = gdf[gdf["class"] == 406]
    if sub.empty:
        return 0, 0.0, 0.0, 0.0
    areas = sub.area
    total_ha = areas.sum() / 1e4
    max_pct = areas.max() / areas.sum() * 100
    coverage = total_ha / BBOX_HA * 100
    return len(sub), total_ha, coverage, max_pct


def run_with(cfg_base: dict, fd: float, min_area_override: int | None) -> tuple[int, float, float, float]:
    cfg = copy.deepcopy(cfg_base)
    profile = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    profile["fusion_distance_m"][406] = fd
    if min_area_override is not None:
        profile["min_area_m2"][406] = min_area_override
    gdf, _ = run_pipeline(str(CLASSIFIED), cfg)
    return measure_406(gdf)


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")

    cfg_base = load_config()
    sigma = cfg_base["vegetation"]["process_hag"]["gaussian_sigma"]
    t406 = cfg_base["vegetation"]["presets"][cfg_base["vegetation"]["active_preset"]]["thresholds"][0]
    min_area = cfg_base["generalization"]["profiles"][
        cfg_base["generalization"]["active_profile"]]["min_area_m2"][406]

    print(f"Sweep fd[406] -- sigma={sigma}, t406={t406}")
    print(f"Deux passes : min_area[406]={min_area} (prod) et min_area[406]=0 (fd pur)")
    print(f"Cibles FFCO Grimbosq : cov=15.0%, max%=5.4%")
    print()
    hdr = f"{'fd':>5} | {'n(prod)':>8} | {'ha(prod)':>9} | {'cov%(p)':>8} | {'max%(p)':>8} || {'n(fd0)':>8} | {'ha(fd0)':>9} | {'max%(0)':>8}"
    print(hdr)
    print("-" * len(hdr))

    results = []
    for fd in FD_VALUES:
        c_p, h_p, cov_p, mx_p = run_with(cfg_base, fd, None)
        c_0, h_0, cov_0, mx_0 = run_with(cfg_base, fd, 0)
        results.append((fd, c_p, h_p, cov_p, mx_p, c_0, h_0, mx_0))
        print(f"{fd:>5} | {c_p:>8} | {h_p:>9.1f} | {cov_p:>8.1f} | {mx_p:>8.1f} || {c_0:>8} | {h_0:>9.1f} | {mx_0:>8.1f}")
        sys.stdout.flush()

    print()
    best = [(fd, c, h, cov, mx) for fd, c, h, cov, mx, *_ in results if mx < 15 and c > 300]
    if best:
        fd_b, c_b, h_b, cov_b, mx_b = best[-1]
        print(f"Candidat (max%<15, n>300) : fd={fd_b} -> {c_b} poly, {h_b:.1f} ha, cov={cov_b:.1f}%, max%={mx_b:.1f}%")
    else:
        print("Aucun candidat max%<15 avec n>300 -- voir fd pur")


if __name__ == "__main__":
    main()
