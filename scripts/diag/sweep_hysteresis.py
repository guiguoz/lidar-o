"""Sweep t_low[406] -- hysteresis pour reduire la fragmentation du 406.

t_high[406] = 0.20 (fixe). 408/410 en seuillage simple (pas d hysteresis).
Regenere density_hag_classified.tif a chaque valeur, mesure le quadruplet.

Usage :
    python scripts/sweep_hysteresis.py
"""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile

import geopandas as gpd
import numpy as np
import shapely.geometry as sg
from shapely.ops import unary_union
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
SMOOTHED = ROOT / "output" / "density_hag_smoothed.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"

# t_low valeurs a tester (t_high = 0.20)
LOW_VALUES = [0.20, 0.16, 0.13, 0.10, 0.08]
# 0.20 = reference (hysteresis degeneree = seuillage simple)

SCALE = 10_000
MM2 = 1e6 / SCALE**2


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


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def classify_with_low(smoothed_path: pathlib.Path, t_low_406: float,
                      t_high: float, cfg: dict, tmp_dir: pathlib.Path) -> pathlib.Path:
    """Regenere un TIF classifie avec hysteresis t_low[406]=t_low_406."""
    import numpy as np
    import rasterio
    from scipy.ndimage import label as ndlabel

    with rasterio.open(smoothed_path) as ds:
        arr = ds.read(1).astype(np.float32)
        profile = ds.profile.copy()
        nodata = ds.nodata

    cur_mask = (arr == nodata) if nodata is not None else np.zeros_like(arr, dtype=bool)
    arr[cur_mask] = 0.0

    veg = cfg["vegetation"]
    preset = veg["presets"][veg["active_preset"]]
    T_406, T_408, T_410 = preset["thresholds"]

    def hysteresis(a: np.ndarray, t_lo: float, t_hi: float) -> np.ndarray:
        candidates = a > t_lo
        seeds = a > t_hi
        labeled, _ = ndlabel(candidates)
        sl = np.unique(labeled[seeds])
        sl = sl[sl != 0]
        if sl.size == 0:
            return np.zeros_like(a, dtype=bool)
        return np.isin(labeled, sl)

    classified = np.zeros(arr.shape, dtype=np.uint8)
    # 406 : hysteresis avec t_low variable
    classified[hysteresis(arr, t_low_406, T_406)] = 85
    # 408/410 : seuillage simple
    classified[arr > T_408] = 170
    classified[arr > T_410] = 255
    classified[cur_mask] = 0

    out = tmp_dir / f"classified_low{t_low_406:.2f}.tif"
    profile.update(dtype="uint8", nodata=0, count=1)
    with rasterio.open(out, "w", **profile) as ds:
        ds.write(classified[np.newaxis, :, :])
    return out


def main() -> None:
    if not SMOOTHED.exists():
        sys.exit(f"ABSENT : {SMOOTHED} -- lancer process_hag.py d abord")
    if not FFCO_GPKG.exists():
        sys.exit(f"ABSENT : {FFCO_GPKG}")

    cfg = load_config()
    preset = cfg["vegetation"]["presets"][cfg["vegetation"]["active_preset"]]
    T_406 = preset["thresholds"][0]

    print(f"Sweep t_low[406] -- t_high={T_406} (fixe), 408/410 seuillage simple")
    print(f"min_area : 406={cfg['generalization']['profiles']['grimbosq_v0']['min_area_m2'][406]}"
          f" 408={cfg['generalization']['profiles']['grimbosq_v0']['min_area_m2'][408]}"
          f" 410={cfg['generalization']['profiles']['grimbosq_v0']['min_area_m2'][410]}")
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

    hdr = f"{'t_low':>6}  {'cls':>3}  {'cov%':>6}  {'n':>5}  {'med mm2':>8}  {'%<1mm2':>7}  {'max%406':>8}"
    print(hdr)
    print("-" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = pathlib.Path(tmp)
        for t_low in LOW_VALUES:
            tif = classify_with_low(SMOOTHED, t_low, T_406, cfg, tmp_dir)
            gdf, _ = run_pipeline(str(tif), cfg)
            mx = max_pct_406(gdf, hull)
            for i, cls in enumerate([406, 408, 410]):
                q = quadruplet(gdf, hull, cls)
                cov, n, med, pct = q
                mx_str = f"{mx:>8.1f}" if i == 0 else " " * 9
                print(f"{t_low:>6.2f}  {cls:>3}  {cov:>6.1f}  {n:>5}  {med:>8.2f}  {pct:>7.1f}{mx_str}")
            sys.stdout.flush()

    print()
    print("t_low=t_high = seuillage simple (reference).")
    print("Garde-fou : max%406 > 10% = percolation sur hull (plancher 7.4% sur bbox).")


if __name__ == "__main__":
    main()
