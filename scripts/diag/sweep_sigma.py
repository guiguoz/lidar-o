"""Sweep gaussian_sigma -- mesure le compromis mediane / concentration.

Relit density_hag.tif + total_count.tif (ratio mode), applique le meme
pipeline que process_hag.py avec des sigma differents sans toucher
density_hag_classified.tif de reference.

Question : existe-t-il une zone sigma ou la mediane monte AVANT que
la concentration decolle ? Signature fusion : mediane * ratio_sigma >
couverture * ratio_sigma. Signature croissance : les deux bougent pareil.

Usage :
    python scripts/sweep_sigma.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

import geopandas as gpd
import numpy as np
import rasterio
import shapely.geometry as sg
from scipy.ndimage import gaussian_filter, median_filter
from shapely.ops import unary_union
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
HAG_TIF = ROOT / "output" / "density_hag.tif"
TOTAL_TIF = ROOT / "output" / "total_count.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"

SIGMA_VALUES = [1.0, 1.5, 2.0]   # sigma en metres
MEDIAN_M = 9.0                    # taille mediane (m) -- inchange

SCALE = 10_000
MM2 = 1e6 / SCALE**2


# ── Fonctions FFCO ────────────────────────────────────────────────────────────

def load_ffco_hull() -> sg.Polygon:
    r = subprocess.run(
        ["ogr2ogr", "-f", "GeoJSON", "-oo", "ENCODING=ISO-8859-1",
         "/vsistdout/", str(FFCO_GPKG), "grimbosq_areas"],
        capture_output=True, errors="replace",
    )
    fc = json.loads(r.stdout)
    geoms = []
    for feat in fc["features"]:
        name = feat["properties"].get("Name", "")
        for key in ("course lente", "marche", "progression"):
            if key in name and "bonne" not in name:
                try:
                    g = sg.shape(feat["geometry"])
                    geoms.append(g.buffer(0) if not g.is_valid else g)
                except Exception:
                    pass
                break
    return unary_union(geoms).convex_hull


def quadruplet(gdf: gpd.GeoDataFrame, hull: sg.Polygon, cls: int) -> tuple:
    sub = gdf[gdf["class"] == cls].copy().clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return 0.0, 0, 0.0, 0.0
    areas = sub.geometry.area
    mm2 = areas * MM2
    return (
        float(areas.sum() / hull.area * 100),
        len(sub),
        float(np.median(mm2)),
        float((mm2 < 1.0).mean() * 100),
    )


def max_pct_406(gdf: gpd.GeoDataFrame, hull: sg.Polygon) -> float:
    sub = gdf[gdf["class"] == 406].copy().clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return 0.0
    areas = sub.geometry.area
    return float(areas.max() / areas.sum() * 100)


# ── Pipeline raster ───────────────────────────────────────────────────────────

def _load(path: pathlib.Path) -> tuple[np.ndarray, dict, np.ndarray]:
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype(np.float32)
        nd = ds.nodata
        profile = ds.profile.copy()
    mask = (arr == nd) if nd is not None else np.zeros_like(arr, dtype=bool)
    arr[mask] = 0.0
    return arr, profile, mask


def classify_with_sigma(sigma_m: float, cfg: dict, tmp_dir: pathlib.Path) -> pathlib.Path:
    """Lisse la densite brute avec sigma_m, classifie, ecrit un TIF temporaire."""
    hag, profile, mask_hag = _load(HAG_TIF)
    total, _, mask_total = _load(TOTAL_TIF)

    # Ratio (replique compute_ratio)
    mask = mask_hag | mask_total | (total <= 0)
    ratio = np.where(mask, 0.0, np.where(total > 0, hag / total, 0.0)).astype(np.float32)

    res = abs(profile["transform"].a)
    sigma_px = sigma_m / res
    median_px = int(round(MEDIAN_M / res))
    if median_px % 2 == 0:
        median_px += 1

    # Lissage identique a process_hag.py
    smoothed = median_filter(gaussian_filter(ratio, sigma=sigma_px), size=median_px)
    smoothed[mask] = 0.0

    # Normalisation p95_local
    valid = smoothed[~mask]
    p95 = float(np.percentile(valid, 95)) if valid.size > 0 else 1.0
    p95 = max(p95, 1e-6)
    normed = np.clip(smoothed / p95, 0.0, 1.0)
    normed[mask] = 0.0

    # Classification (seuillage simple -- hysteresis desactivee pour ce sweep)
    preset = cfg["vegetation"]["presets"][cfg["vegetation"]["active_preset"]]
    T_406, T_408, T_410 = preset["thresholds"]

    classified = np.zeros(normed.shape, dtype=np.uint8)
    classified[normed > T_406] = 85
    classified[normed > T_408] = 170
    classified[normed > T_410] = 255
    classified[mask] = 0

    out = tmp_dir / f"classified_sigma{sigma_m:.1f}.tif"
    prof = profile.copy()
    prof.update(dtype="uint8", nodata=0, count=1)
    with rasterio.open(out, "w", **prof) as ds:
        ds.write(classified[np.newaxis, :, :])
    return out


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def main() -> None:
    for p in [HAG_TIF, TOTAL_TIF, FFCO_GPKG]:
        if not p.exists():
            sys.exit(f"ABSENT : {p}")

    cfg = load_config()
    prof = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    ma = prof["min_area_m2"]
    preset = cfg["vegetation"]["presets"][cfg["vegetation"]["active_preset"]]
    T_406, T_408, T_410 = preset["thresholds"]

    print(f"Sweep sigma -- t406={T_406}, t408={T_408}, t410={T_410}")
    print(f"min_area 406/408/410 = {ma[406]}/{ma[408]}/{ma[410]}")
    print(f"median_size = {MEDIAN_M}m (inchange)")
    print()

    print("Chargement hull FFCO ...")
    hull = load_ffco_hull()
    print(f"Hull : {hull.area/1e4:.1f} ha")
    print()
    print("Cibles FFCO :")
    print("  406 : cov=19.3%  n=463  med=5.17mm2  pct=3.7%")
    print("  408 : cov=6.9%   n=432  med=2.31mm2  pct=13.4%")
    print("  410 : cov=8.0%   n=363  med=1.39mm2  pct=32.0%")
    print()

    hdr = f"{'sigma':>6}  {'cls':>3}  {'cov%':>6}  {'n':>5}  {'med mm2':>8}  {'%<1mm2':>7}  {'max%406':>8}"
    print(hdr)
    print("-" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = pathlib.Path(tmp)
        for sigma in SIGMA_VALUES:
            tif = classify_with_sigma(sigma, cfg, tmp_dir)
            gdf, _ = run_pipeline(str(tif), cfg)
            mx = max_pct_406(gdf, hull)
            for i, cls in enumerate([406, 408, 410]):
                q = quadruplet(gdf, hull, cls)
                cov, n, med, pct = q
                mx_str = f"{mx:>8.1f}" if i == 0 else " " * 9
                print(f"{sigma:>6.1f}  {cls:>3}  {cov:>6.1f}  {n:>5}  {med:>8.2f}  {pct:>7.1f}{mx_str}")
            sys.stdout.flush()

    print()
    print("Signature fusion    : mediane *X, couverture *Y, X >> Y.")
    print("Signature croissance: mediane *X, couverture *Y, X ~ Y.")
    print("Garde-fou : max%406 > 15% = percolation naissante.")


if __name__ == "__main__":
    main()
