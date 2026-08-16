"""Test preset sparse_winter (t406=0.25) sur Airelles — tranche seuil vs sémantique.

Question : le seuil seul (t406=0.25) suffit-il à ramener la surface 406 vers la cible
FFCO (5.7% sur hull FFCO ~389 ha) ? Si oui → problème de calibration preset.
Si non → cause structurelle (sémantique ou canopée).

Correction dénominateur (2026-08-04) : emprise de référence = hull convex FFCO (~389 ha),
non bbox pipeline (2501 ha). Les deux sources clippées sur ce hull avant comparaison.

407 exclu de la cible (directionnel, non détectable par pipeline raster).
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
HAG_TIF = ROOT / "output_airelles" / "density_hag.tif"
TOTAL_TIF = ROOT / "output_airelles" / "total_count.tif"
GPKG = ROOT / "airelles.gpkg"

# Preset sparse_winter
T_406, T_408, T_410 = 0.25, 0.55, 0.80
SIGMA_M = 1.0
MEDIAN_PX = 9

for p, label in [(HAG_TIF, "density_hag.tif"), (TOTAL_TIF, "total_count.tif"), (GPKG, "airelles.gpkg")]:
    if not p.exists():
        raise FileNotFoundError(f"{label} absent : {p}")


# ── Hull convex FFCO ──────────────────────────────────────────────────────────

def _ffco_hull_geom(gpkg_path: pathlib.Path):
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
    return unary_union(geoms).convex_hull


hull_geom = _ffco_hull_geom(GPKG)
FFCO_HULL_HA = hull_geom.area / 1e4
print(f"Hull convex FFCO : {FFCO_HULL_HA:.1f} ha", flush=True)

# Référence grimbosq_v0 (σ=1.0, t406=0.20) sur hull
PREV_COV = None   # recalculé ci-dessous si on l'a
PREV_MAX = None


# ── I/O raster ───────────────────────────────────────────────────────────────

def _load(path):
    ds = gdal.Open(str(path))
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nd = ds.GetRasterBand(1).GetNoDataValue()
    gt, prj = ds.GetGeoTransform(), ds.GetProjection()
    ds = None
    mask = (arr == nd) if nd is not None else np.zeros_like(arr, dtype=bool)
    arr[mask] = 0.0
    return arr, gt, prj, mask


def _save(arr, path, gt, prj):
    d = gdal.GetDriverByName("GTiff")
    ds = d.Create(str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt); ds.SetProjection(prj)
    b = ds.GetRasterBand(1); b.WriteArray(arr); b.SetNoDataValue(0)
    ds.FlushCache(); ds = None


hag, gt, prj, mh = _load(HAG_TIF)
total, _, _, mt = _load(TOTAL_TIF)
r, c = min(hag.shape[0], total.shape[0]), min(hag.shape[1], total.shape[1])
hag, total = hag[:r, :c], total[:r, :c]
mask = (mh | mt | (total <= 0))[:r, :c]

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

print(f"sparse_winter (t406={T_406}/t408={T_408}/t410={T_410}, σ={SIGMA_M}m)", flush=True)
print(f"  pixels → 406:{int(np.sum(classified==85)):,}  "
      f"408:{int(np.sum(classified==170)):,}  "
      f"410:{int(np.sum(classified==255)):,}", flush=True)

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
pk = cfg["generalization"]["active_profile"]
cfg["generalization"]["profiles"][pk]["fusion_distance_m"]["406"] = 0

with tempfile.TemporaryDirectory(prefix="diag_preset_") as tmpdir:
    out_tif = pathlib.Path(tmpdir) / "classified_sparse_winter.tif"
    _save(classified, out_tif, gt, prj)
    gdf, _ = run_pipeline(str(out_tif), cfg, debug_dir=None)

sub = gdf[gdf["class"] == 406]
sub_hull = sub.clip(hull_geom) if len(sub) > 0 else sub
areas = sub_hull.geometry.area.values if len(sub_hull) > 0 else np.array([0.0])
total_ha = areas.sum() / 1e4
max_pct = 100.0 * areas.max() / areas.sum() if areas.sum() > 0 else 0.0
cov = 100.0 * total_ha / FFCO_HULL_HA

# FFCO 406 sur hull
gdf_ffco = load_ffco(str(GPKG), class_col="class")
gdf_ffco.geometry = gdf_ffco.geometry.buffer(0)
ffco_clip = gdf_ffco.clip(hull_geom)
ffco_406 = ffco_clip[ffco_clip["class"].astype(str) == "406"]
FFCO_COV = 100.0 * ffco_406.geometry.area.sum() / 1e4 / FFCO_HULL_HA if len(ffco_406) > 0 else 0.0
FFCO_MAX = float(100.0 * ffco_406.geometry.area.max() / ffco_406.geometry.area.sum()) if len(ffco_406) > 0 else 0.0
print(f"\nFFCO 406 (hull) : {len(ffco_406)} poly | cov={FFCO_COV:.1f}% | max%406={FFCO_MAX:.1f}%", flush=True)

# Résultats grimbosq_v0 depuis JSON si disponible (même dénominateur hull → non disponible, on skip)

print(f"\n{'='*55}", flush=True)
print(f"  {'':20} {'coverage%':>10} {'max%406':>10}", flush=True)
print(f"  {'FFCO Airelles (cible)':20} {FFCO_COV:>10.1f}% {FFCO_MAX:>10.1f}%", flush=True)
print(f"  {'sparse_winter(t=0.25)':20} {cov:>10.1f}% {max_pct:>10.1f}%", flush=True)
print(f"  {'Δ vs FFCO':20} {cov-FFCO_COV:>+10.1f}% {max_pct-FFCO_MAX:>+10.1f}%", flush=True)
print(f"\n  [Hull {FFCO_HULL_HA:.0f} ha — dénominateur corrigé (ancien: bbox pipeline 2501 ha)]", flush=True)

if cov < 4.0 and max_pct < 15.0:
    verdict = "Seuil seul suffit → calibration preset par type de peuplement"
elif cov < 4.0 and max_pct > 20.0:
    verdict = "Seuil réduit la surface mais crée un blob → effet non monotone"
else:
    verdict = f"Seuil insuffisant (coverage={cov:.1f}%>{FFCO_COV+4:.1f}%) → cause structurelle"
print(f"  Verdict : {verdict}", flush=True)

out = {
    "preset": "sparse_winter", "t406": T_406, "t408": T_408, "t410": T_410,
    "sigma_m": SIGMA_M,
    "ffco_hull_ha": float(FFCO_HULL_HA),
    "pipeline_fd0": {
        "count_hull": int(len(sub_hull)),
        "total_ha_hull": float(total_ha),
        "coverage_pct_hull": float(cov),
        "max_pct_406": float(max_pct),
    },
    "ffco_airelles": {
        "coverage_pct_hull": float(FFCO_COV), "max_pct_406": float(FFCO_MAX),
        "note_407": "407 exclu de la cible (directionnel, pipeline non détectable)",
    },
    "verdict": verdict,
}
(ROOT / "rapports" / "diag_airelles_preset.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nJSON -> rapports/diag_airelles_preset.json", flush=True)
