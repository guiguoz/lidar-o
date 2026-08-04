"""Test preset sparse_winter (t406=0.25) sur Airelles — tranche seuil vs sémantique.

Si coverage passe de 12.2% (grimbosq_v0, t406=0.20) vers ~1.7% (FFCO Airelles)
sans reformer de blob → cause = seuil par type de peuplement.
Si coverage reste >> 1.7% ou max%406 explose → cause distincte du seuil.

Protocole identique à diag_airelles_sigma1.py mais avec les seuils sparse_winter :
  t406=0.25 / t408=0.55 / t410=0.80
  σ=1.0 m (config production)
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
HAG_TIF = ROOT / "output_airelles" / "density_hag.tif"
TOTAL_TIF = ROOT / "output_airelles" / "total_count.tif"
GPKG = ROOT / "airelles.gpkg"
FFCO_COV_AIRELLES = 1.7
FFCO_MAX_AIRELLES = 6.6

# Preset sparse_winter
T_406, T_408, T_410 = 0.25, 0.55, 0.80
SIGMA_M = 1.0
MEDIAN_PX = 9

# Pour comparaison directe avec le run précédent
PREV_COV = 12.2   # grimbosq_v0 t406=0.20
PREV_MAX = 3.4


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

XMIN, YMAX = gt[0], gt[3]
XMAX, YMIN = XMIN + c * gt[1], YMAX + r * gt[5]
BBOX = (XMIN, YMIN, XMAX, YMAX)
BBOX_HA = (XMAX - XMIN) * (YMAX - YMIN) / 1e4

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
areas = sub.geometry.area.values if len(sub) > 0 else np.array([0.0])
total_ha = areas.sum() / 1e4
max_pct = 100.0 * areas.max() / areas.sum() if areas.sum() > 0 else 0.0
cov = 100.0 * total_ha / BBOX_HA

print(f"\n{'='*55}", flush=True)
print(f"  {'':20} {'coverage%':>10} {'max%406':>10}", flush=True)
print(f"  {'FFCO Airelles (réf)':20} {FFCO_COV_AIRELLES:>10.1f}% {FFCO_MAX_AIRELLES:>10.1f}%", flush=True)
print(f"  {'grimbosq_v0 (t=0.20)':20} {PREV_COV:>10.1f}% {PREV_MAX:>10.1f}%", flush=True)
print(f"  {'sparse_winter(t=0.25)':20} {cov:>10.1f}% {max_pct:>10.1f}%", flush=True)
print(f"  {'Δ vs FFCO':20} {cov-FFCO_COV_AIRELLES:>+10.1f}% {max_pct-FFCO_MAX_AIRELLES:>+10.1f}%", flush=True)

delta_cov = cov - PREV_COV
print(f"\n  Δcov grimbosq→sparse : {delta_cov:+.1f}%", flush=True)
if cov < 4.0 and max_pct < 15.0:
    verdict = "Seuil seul suffit → calibration preset par type de peuplement"
elif cov < 4.0 and max_pct > 20.0:
    verdict = "Seuil réduit la surface mais crée un blob → effet non monotone, à examiner"
else:
    verdict = f"Seuil insuffisant (coverage={cov:.1f}%, >4%) → hypothèse sémantique plus probable"
print(f"  Verdict : {verdict}", flush=True)

out = {
    "preset": "sparse_winter", "t406": T_406, "t408": T_408, "t410": T_410,
    "sigma_m": SIGMA_M, "bbox_ha": BBOX_HA,
    "pipeline_fd0": {"count": int(len(sub)), "total_ha": float(total_ha),
                     "coverage_pct": float(cov), "max_pct_406": float(max_pct)},
    "ffco_airelles": {"coverage_pct": FFCO_COV_AIRELLES, "max_pct_406": FFCO_MAX_AIRELLES},
    "prev_grimbosq_v0": {"coverage_pct": PREV_COV, "max_pct_406": PREV_MAX},
    "verdict": verdict,
}
(ROOT / "rapports" / "diag_airelles_preset.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nJSON -> rapports/diag_airelles_preset.json", flush=True)
