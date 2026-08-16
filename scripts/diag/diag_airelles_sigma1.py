"""Test de généralisation σ=1.0 sur Airelles (résineux/lande altitude).

Compare les métriques (coverage_pct, max%406) du pipeline σ=1.0 / fd[406]=0
contre le FFCO Airelles, **sur l'emprise réelle FFCO** (hull convex ~389 ha).

Correction dénominateur (2026-08-04) : l'emprise pipeline bbox (2501 ha) surestimait
le ratio ×7. Le hull convex de toutes les zones cartographiées FFCO (~389 ha) est le
dénominateur commun correct. Les deux sources sont clippées sur ce hull.

Cible = FFCO 406 seul = 5.7% (corrigé). 407 exclu (directionnel, pipeline non détectable).

Même protocole que diag_sigma_t406.py Run A sur Grimbosq, pour comparaison directe :
  Grimbosq σ=1.0 → Δcov=+1.6%, Δmax%406=+1.8% vs FFCO sur emprise commune
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import numpy as np
import yaml
from osgeo import gdal, ogr
from scipy.ndimage import gaussian_filter, median_filter
from shapely.ops import unary_union
from shapely.wkt import loads as wkt_loads

gdal.UseExceptions()

import geopandas as gpd

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from scripts.measure_corpus import load_ffco
from src.metrics import compute_ratio
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
SRC_DIR = ROOT / "output_airelles"
HAG_TIF = SRC_DIR / "density_hag.tif"
TOTAL_TIF = SRC_DIR / "total_count.tif"
GPKG = ROOT / "airelles.gpkg"

SIGMA_M = 1.0
T_406 = 0.20
T_408 = 0.45
T_410 = 0.85
MEDIAN_PX = 9

for p, label in [(HAG_TIF, "density_hag.tif"), (TOTAL_TIF, "total_count.tif"), (GPKG, "airelles.gpkg")]:
    if not p.exists():
        raise FileNotFoundError(f"{label} absent : {p}")


# ── Hull convex FFCO (dénominateur commun) ────────────────────────────────────

def _ffco_hull_geom(gpkg_path: pathlib.Path):
    """Hull convex de toutes les zones cartographiées du GPKG OOM."""
    ds = ogr.Open(str(gpkg_path))
    lyr = None
    for i in range(ds.GetLayerCount()):
        n = ds.GetLayer(i).GetName()
        if n.endswith("_areas"):
            lyr = ds.GetLayer(i)
            break
    if lyr is None:
        lyr = ds.GetLayer(0)
    geoms = []
    for feat in lyr:
        ref = feat.GetGeometryRef()
        if ref:
            geoms.append(wkt_loads(ref.ExportToWkt()))
    ds = None
    if not geoms:
        raise ValueError("Aucune géométrie dans le GPKG")
    return unary_union(geoms).convex_hull


hull_geom = _ffco_hull_geom(GPKG)
FFCO_HULL_HA = hull_geom.area / 1e4
HULL_BOUNDS = hull_geom.bounds   # (minx, miny, maxx, maxy)
print(f"Hull convex FFCO : {FFCO_HULL_HA:.1f} ha | bounds={HULL_BOUNDS}", flush=True)


# ── I/O raster GDAL ──────────────────────────────────────────────────────────

def _load_gdal(path: pathlib.Path):
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float32)
    nd = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    prj = ds.GetProjection()
    ds = None
    mask = (arr == nd) if nd is not None else np.zeros_like(arr, dtype=bool)
    arr[mask] = 0.0
    return arr, gt, prj, mask


def _save_gdal(arr: np.ndarray, path: pathlib.Path, gt, prj: str) -> None:
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    ds.SetProjection(prj)
    band = ds.GetRasterBand(1)
    band.WriteArray(arr)
    band.SetNoDataValue(0)
    ds.FlushCache()
    ds = None


# ── Classification σ=1.0 ─────────────────────────────────────────────────────

print(f"\n=== Classification σ={SIGMA_M}m, t406={T_406} ===", flush=True)
hag, gt, prj, mask_h = _load_gdal(HAG_TIF)
total, _, _, mask_t = _load_gdal(TOTAL_TIF)

r = min(hag.shape[0], total.shape[0])
c = min(hag.shape[1], total.shape[1])
hag, total = hag[:r, :c], total[:r, :c]
mask = (mask_h | mask_t | (total <= 0))[:r, :c]

metric = compute_ratio(hag, total, mask)
sigma_px = SIGMA_M / abs(gt[1])
smoothed = gaussian_filter(metric, sigma=sigma_px)
smoothed = median_filter(smoothed, size=MEDIAN_PX)

valid = smoothed[~mask]
vmax = float(np.percentile(valid, 95)) if valid.size > 0 else 1.0
norm = np.clip(smoothed / vmax if vmax > 1e-9 else smoothed, 0.0, 1.0)
norm[mask] = 0.0

classified = np.zeros(norm.shape, dtype=np.uint8)
classified[norm > T_406] = 85
classified[norm > T_408] = 170
classified[norm > T_410] = 255
classified[mask] = 0

print(f"  pixels → 406:{int(np.sum(classified==85)):,}  "
      f"408:{int(np.sum(classified==170)):,}  "
      f"410:{int(np.sum(classified==255)):,}", flush=True)


# ── Pipeline CO fd[406]=0 ─────────────────────────────────────────────────────

print("\n=== Pipeline CO (fd[406]=0) ===", flush=True)
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
profile_key = cfg["generalization"]["active_profile"]
cfg["generalization"]["profiles"][profile_key]["fusion_distance_m"]["406"] = 0

with tempfile.TemporaryDirectory(prefix="diag_airelles_") as tmpdir:
    out_tif = pathlib.Path(tmpdir) / "classified_airelles_sigma1.tif"
    _save_gdal(classified, out_tif, gt, prj)
    gdf, _ = run_pipeline(str(out_tif), cfg, debug_dir=None)

# Clipper sur hull FFCO
sub406_all = gdf[gdf["class"] == 406]
sub406_hull = sub406_all.clip(hull_geom) if len(sub406_all) > 0 else sub406_all
areas_pipe = sub406_hull.geometry.area.values if len(sub406_hull) > 0 else np.array([0.0])
total_ha_pipe = areas_pipe.sum() / 1e4
max_pct_pipe = 100.0 * areas_pipe.max() / areas_pipe.sum() if areas_pipe.sum() > 0 else 0.0
cov_pipe = 100.0 * total_ha_pipe / FFCO_HULL_HA

print(f"  Pipeline 406 (total) : {len(sub406_all)} poly | {sub406_all.geometry.area.sum()/1e4:.1f} ha", flush=True)
print(f"  Pipeline 406 (hull)  : {len(sub406_hull)} poly | {total_ha_pipe:.1f} ha | "
      f"cov={cov_pipe:.1f}% | max%406={max_pct_pipe:.1f}%", flush=True)


# ── FFCO Airelles clippé sur hull ────────────────────────────────────────────

print("\n=== FFCO Airelles clippé sur hull convex ===", flush=True)
gdf_ffco = load_ffco(str(GPKG), class_col="class")
gdf_ffco.geometry = gdf_ffco.geometry.buffer(0)
gdf_clip = gdf_ffco.clip(hull_geom)
print(f"  GPKG : {len(gdf_ffco)} features → clip hull : {len(gdf_clip)}", flush=True)

ffco_stats: dict = {}
for cls in [406, 407, 408, 410]:
    sub = gdf_clip[gdf_clip["class"].astype(str) == str(cls)]
    area_ha = sub.geometry.area.sum() / 1e4
    cov_ffco = 100.0 * area_ha / FFCO_HULL_HA
    ffco_stats[str(cls)] = {
        "count": int(len(sub)), "area_ha": float(area_ha), "coverage_pct": float(cov_ffco)
    }
    if len(sub) > 0:
        print(f"  FFCO {cls} : {len(sub)} poly, {area_ha:.1f} ha ({cov_ffco:.1f}% hull)", flush=True)

ffco_406 = gdf_clip[gdf_clip["class"].astype(str) == "406"]
if len(ffco_406) > 0:
    a406 = ffco_406.geometry.area.values
    max_pct_ffco = 100.0 * a406.max() / a406.sum()
    ffco_stats["406"]["max_pct"] = float(max_pct_ffco)
    print(f"  FFCO 406 max%406 : {max_pct_ffco:.1f}%", flush=True)
else:
    max_pct_ffco = 0.0


# ── Résumé comparatif ─────────────────────────────────────────────────────────

ffco_cov = ffco_stats.get("406", {}).get("coverage_pct", 0.0)
ffco_max = ffco_stats.get("406", {}).get("max_pct", 0.0)
delta_cov = cov_pipe - ffco_cov
delta_max = max_pct_pipe - ffco_max

print(f"\n{'='*60}", flush=True)
print(f"RÉSUMÉ — Airelles σ=1.0 vs FFCO (emprise hull ~{FFCO_HULL_HA:.0f} ha)", flush=True)
print(f"{'='*60}", flush=True)
print(f"  {'Source':<22} {'coverage%':>10} {'max%406':>10}", flush=True)
print(f"  {'-'*44}", flush=True)
print(f"  {'FFCO 406 seul (cible)':<22} {ffco_cov:>10.1f}% {ffco_max:>10.1f}%", flush=True)
print(f"  {'Pipeline σ=1.0':<22} {cov_pipe:>10.1f}% {max_pct_pipe:>10.1f}%", flush=True)
print(f"  {'Δ (pipe−FFCO)':<22} {delta_cov:>+10.1f}% {delta_max:>+10.1f}%", flush=True)
print(f"\n  [Grimbosq σ=1.0 sur emprise commune : Δcov=+1.6%, Δmax%406=+1.8%]", flush=True)
print(f"  [Note: FFCO 406+407 sur hull = "
      f"{ffco_stats.get('406', {}).get('area_ha', 0)+ffco_stats.get('407', {}).get('area_ha', 0):.1f} ha"
      f" ({ffco_stats.get('406', {}).get('coverage_pct', 0)+ffco_stats.get('407', {}).get('coverage_pct', 0):.1f}%)"
      f" — 407 exclu de la cible]", flush=True)

if abs(delta_max) <= 5 and abs(delta_cov) <= 15:
    verdict = f"Résidu modéré (Δcov={delta_cov:+.1f}%, Δmax={delta_max:+.1f}%) — cohérent avec Grimbosq"
elif delta_max > 20:
    verdict = f"max%406 élevé (Δ={delta_max:+.1f}%) — nappe persistante sur Airelles"
elif delta_cov < -10:
    verdict = f"coverage bas (Δ={delta_cov:+.1f}%) — σ=1.0 sur-corrige sur résineux"
else:
    verdict = f"Δcov={delta_cov:+.1f}%, Δmax={delta_max:+.1f}%"
print(f"\n  Verdict : {verdict}", flush=True)

# ── JSON ──────────────────────────────────────────────────────────────────────

out_json = ROOT / "rapports" / "diag_airelles_sigma1.json"
out_json.write_text(json.dumps({
    "ffco_hull_ha": float(FFCO_HULL_HA),
    "hull_bounds": list(HULL_BOUNDS),
    "sigma_m": SIGMA_M, "t406": T_406,
    "ffco_airelles": ffco_stats,
    "pipeline_fd0": {
        "count_hull": int(len(sub406_hull)),
        "total_ha_hull": float(total_ha_pipe),
        "coverage_pct_hull": float(cov_pipe),
        "max_pct_406": float(max_pct_pipe),
    },
    "deltas": {"coverage_pct": float(delta_cov), "max_pct_406": float(delta_max)},
    "verdict": verdict,
}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nJSON -> {out_json}", flush=True)
