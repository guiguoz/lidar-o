"""Test de généralisation σ=1.0 sur Airelles (résineux).

Compare les métriques (coverage_pct, max%406) du pipeline σ=1.0 / fd[406]=0
contre le FFCO Airelles clippé sur la bbox density_hag.tif (16 tuiles).

Même protocole que diag_sigma_t406.py Run A sur Grimbosq, pour comparaison directe :
  Grimbosq σ=1.0 → coverage 16.6% (cible FFCO 15.0%), max%406 7.2% (cible 5.4%)
  Airelles  σ=1.0 → ?

Nécessite PDAL 16 tuiles terminé (output_airelles/density_hag.tif à jour).
Bug class string/int corrigé : class.astype(str) == str(cls) partout.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import numpy as np
import yaml
from osgeo import gdal
from scipy.ndimage import gaussian_filter, median_filter
from shapely.geometry import box

gdal.UseExceptions()

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from scripts.measure_corpus import load_ffco
from src.metrics import compute_ratio
from src.vegetation import run_pipeline

import geopandas as gpd

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

# ── Vérification données sources ──────────────────────────────────────────────

if not HAG_TIF.exists():
    raise FileNotFoundError(f"density_hag.tif absent — PDAL non terminé ? {HAG_TIF}")
if not TOTAL_TIF.exists():
    raise FileNotFoundError(f"total_count.tif absent — {TOTAL_TIF}")

# ── Bbox depuis density_hag.tif ───────────────────────────────────────────────

ds = gdal.Open(str(HAG_TIF))
_gt = ds.GetGeoTransform()
_w, _h = ds.RasterXSize, ds.RasterYSize
XMIN, YMAX = _gt[0], _gt[3]
XMAX = XMIN + _w * _gt[1]
YMIN = YMAX + _h * _gt[5]
BBOX = (XMIN, YMIN, XMAX, YMAX)
BBOX_AREA_HA = (_w * _gt[1]) * (-_h * _gt[5]) / 1e4
ds = None

print(f"Bbox density_hag : {BBOX}", flush=True)
print(f"Surface          : {BBOX_AREA_HA:.1f} ha", flush=True)


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
actual_res = abs(gt[1])
sigma_px = SIGMA_M / actual_res
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

pipeline_stats: dict = {}
with tempfile.TemporaryDirectory(prefix="diag_airelles_") as tmpdir:
    out_tif = pathlib.Path(tmpdir) / "classified_airelles_sigma1.tif"
    _save_gdal(classified, out_tif, gt, prj)
    gdf, logs = run_pipeline(str(out_tif), cfg, debug_dir=None)

    sub406 = gdf[gdf["class"] == 406]
    if len(sub406) > 0:
        areas = sub406.geometry.area.values
        total_ha = areas.sum() / 1e4
        max_ha = areas.max() / 1e4
        max_pct = 100.0 * areas.max() / areas.sum()
        pipeline_stats = {
            "count": int(len(sub406)),
            "total_ha": float(total_ha),
            "coverage_pct": float(100.0 * total_ha / BBOX_AREA_HA),
            "max_ha": float(max_ha),
            "max_pct_406": float(max_pct),
        }
    else:
        pipeline_stats = {"count": 0, "total_ha": 0.0, "coverage_pct": 0.0,
                          "max_ha": 0.0, "max_pct_406": 0.0}

print(f"  Pipeline 406 : {pipeline_stats['count']} poly, "
      f"{pipeline_stats['coverage_pct']:.1f}% couverture, "
      f"max%406={pipeline_stats['max_pct_406']:.1f}%", flush=True)


# ── FFCO Airelles clippé ──────────────────────────────────────────────────────

print("\n=== FFCO Airelles clippé sur bbox ===", flush=True)
gdf_ffco = load_ffco(str(GPKG), class_col="class")
gdf_ffco.geometry = gdf_ffco.geometry.buffer(0)
gdf_clip = gdf_ffco.clip(box(*BBOX))
print(f"  GPKG : {len(gdf_ffco)} features → clip : {len(gdf_clip)}", flush=True)

ffco_stats: dict = {}
for cls in [406, 408, 410]:
    sub = gdf_clip[gdf_clip["class"].astype(str) == str(cls)]
    area_ha = sub.geometry.area.sum() / 1e4
    ffco_stats[str(cls)] = {"count": int(len(sub)), "area_ha": float(area_ha)}
    print(f"  FFCO {cls} : {len(sub)} poly, {area_ha:.1f} ha  "
          f"({100*area_ha/BBOX_AREA_HA:.1f}% emprise)", flush=True)

ffco_406 = gdf_clip[gdf_clip["class"].astype(str) == "406"]
if len(ffco_406) > 0:
    areas_f = ffco_406.geometry.area.values
    ffco_max_ha = areas_f.max() / 1e4
    ffco_max_pct = 100.0 * areas_f.max() / areas_f.sum()
    ffco_stats["406"]["max_ha"] = float(ffco_max_ha)
    ffco_stats["406"]["max_pct"] = float(ffco_max_pct)
    ffco_stats["406"]["coverage_pct"] = float(100.0 * areas_f.sum() / 1e4 / BBOX_AREA_HA)
    print(f"  FFCO 406 plus gros : {ffco_max_ha:.1f} ha  ({ffco_max_pct:.1f}% du 406)", flush=True)


# ── Résumé comparatif ─────────────────────────────────────────────────────────

print(f"\n{'='*60}", flush=True)
print("RÉSUMÉ — Airelles σ=1.0 vs FFCO (cibles Grimbosq pour référence)", flush=True)
print(f"{'='*60}", flush=True)

ffco_cov = ffco_stats.get("406", {}).get("coverage_pct", 0.0)
ffco_max = ffco_stats.get("406", {}).get("max_pct", 0.0)
pipe_cov = pipeline_stats.get("coverage_pct", 0.0)
pipe_max = pipeline_stats.get("max_pct_406", 0.0)

print(f"  {'Source':<20} {'coverage%':>10} {'max%406':>10}", flush=True)
print(f"  {'-'*42}", flush=True)
print(f"  {'FFCO Airelles':<20} {ffco_cov:>10.1f}% {ffco_max:>10.1f}%", flush=True)
print(f"  {'Pipeline σ=1.0':<20} {pipe_cov:>10.1f}% {pipe_max:>10.1f}%", flush=True)
print(f"  {'Δ (pipe−FFCO)':<20} {pipe_cov-ffco_cov:>+10.1f}% {pipe_max-ffco_max:>+10.1f}%",
      flush=True)
print(f"\n  [Grimbosq σ=1.0 : Δcov=+1.6%, Δmax%406=+1.8%]", flush=True)

# ── Lecture ───────────────────────────────────────────────────────────────────

delta_cov = pipe_cov - ffco_cov
delta_max = pipe_max - ffco_max
print(f"\n  Lecture :", flush=True)
if abs(delta_max) <= 5 and abs(delta_cov) <= 5:
    print("  → Résidu comparable à Grimbosq — σ=1.0 tient sur les deux terrains.", flush=True)
elif delta_max > 20:
    print(f"  → max%406 trop élevé (Δ={delta_max:+.1f}%) — nappe persistante sur Airelles.", flush=True)
elif delta_cov < -10:
    print(f"  → coverage trop bas (Δ={delta_cov:+.1f}%) — σ=1.0 sur-corrige sur résineux.", flush=True)
else:
    print(f"  → Résidu modéré (Δcov={delta_cov:+.1f}%, Δmax={delta_max:+.1f}%) — à interpréter.", flush=True)

# ── JSON ──────────────────────────────────────────────────────────────────────

out_json = ROOT / "rapports" / "diag_airelles_sigma1.json"
out_json.write_text(json.dumps({
    "bbox": BBOX, "bbox_area_ha": BBOX_AREA_HA,
    "sigma_m": SIGMA_M, "t406": T_406,
    "ffco_airelles": ffco_stats,
    "pipeline_fd0": pipeline_stats,
    "deltas": {"coverage_pct": float(delta_cov), "max_pct_406": float(delta_max)},
    "grimbosq_ref": {"delta_coverage_pct": 1.6, "delta_max_pct_406": 1.8},
}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nJSON -> {out_json}", flush=True)
