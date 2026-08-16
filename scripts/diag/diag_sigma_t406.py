"""Diagnostic σ × t406 — identifie la cause du blob veg_406.

4 runs en mode ratio + fd[406]=0 (aucune fusion CO sur classe 406) :
  Baseline : σ=3.0 m, t406=0.20  (config actuelle)
  Run A    : σ=1.0 m, t406=0.20  (σ réduit seul)
  Run B    : σ=3.0 m, t406=0.35  (t406 relevé seul)
  Run C    : σ=1.0 m, t406=0.35  (les deux leviers)

fd[406]=0 isole la cause au niveau raster — en amont du CO.
fd[408/410] gardés à leurs valeurs config pour ne pas masquer de régressions.

Critère de lecture — couple :
  max%406      (concentration) → cible FFCO  5.4 %
  coverage_pct (surface)       → cible FFCO 15.0 %

  Un run à 20 % de couverture avec max%406 à 10 % est un progrès réel.
  Un run à 15 % avec max%406 à 50 % est un échec structurel.

Source FFCO : rapports/ffco_clip_stats.json  (bbox 600.5 ha, 550 poly, 89.9 ha)
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile

import numpy as np
import yaml
from osgeo import gdal
from scipy.ndimage import gaussian_filter, median_filter

gdal.UseExceptions()

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.metrics import compute_ratio
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
SRC_DIR = ROOT / "output"   # density_hag.tif partagé (PDAL base, pdal_skipped=true pour étapeA)
HAG_TIF = SRC_DIR / "density_hag.tif"
TOTAL_TIF = SRC_DIR / "total_count.tif"
BBOX_AREA_HA = 600.5   # bbox pipeline 3×2 km ≈ 600.5 ha

FFCO_COVERAGE_PCT = 15.0   # FFCO 406 clippé sur bbox
FFCO_MAX_PCT = 5.4         # plus gros polygone FFCO = 4.8 ha / 89.9 ha

# Seuils 408/410 fixes — seul t406 varie
T_408 = 0.45
T_410 = 0.85

MEDIAN_PX = 9   # 9 m / 1 m à résolution 1m — impair, cohérent avec config

RUNS = [
    {"name": "Baseline", "sigma_m": 3.0, "t406": 0.20, "desc": "config actuelle"},
    {"name": "Run A",    "sigma_m": 1.0, "t406": 0.20, "desc": "σ réduit seul"},
    {"name": "Run B",    "sigma_m": 3.0, "t406": 0.35, "desc": "t406 relevé seul"},
    {"name": "Run C",    "sigma_m": 1.0, "t406": 0.35, "desc": "les deux leviers"},
]


# ─────────────────────────────────────────────────────────────────────────────
# I/O raster via GDAL (disponible dans conda base)
# ─────────────────────────────────────────────────────────────────────────────

def _load_gdal(path: pathlib.Path) -> tuple[np.ndarray, tuple, str, np.ndarray]:
    """Charge un raster float32 via GDAL. Retourne (arr, geotransform, projection, mask)."""
    ds = gdal.Open(str(path))
    if ds is None:
        raise FileNotFoundError(f"GDAL ne peut pas ouvrir : {path}")
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float32)
    nd = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    prj = ds.GetProjection()
    w, h = ds.RasterXSize, ds.RasterYSize
    ds = None
    mask = (arr == nd) if nd is not None else np.zeros_like(arr, dtype=bool)
    arr[mask] = 0.0
    return arr, gt, prj, mask


def _save_gdal(arr: np.ndarray, path: pathlib.Path, gt: tuple, prj: str) -> None:
    """Écrit un raster uint8 via GDAL (driver GTiff)."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    ds.SetProjection(prj)
    band = ds.GetRasterBand(1)
    band.WriteArray(arr)
    band.SetNoDataValue(0)
    ds.FlushCache()
    ds = None


# ─────────────────────────────────────────────────────────────────────────────
# Classification raster
# ─────────────────────────────────────────────────────────────────────────────

def _classify(sigma_m: float, t406: float, out_tif: pathlib.Path) -> None:
    """Génère un classified.tif à partir de density_hag.tif + total_count.tif."""
    hag, gt, prj, mask_h = _load_gdal(HAG_TIF)
    total, _, _, mask_t = _load_gdal(TOTAL_TIF)

    r = min(hag.shape[0], total.shape[0])
    c = min(hag.shape[1], total.shape[1])
    hag, total = hag[:r, :c], total[:r, :c]
    mask = (mask_h | mask_t | (total <= 0))[:r, :c]

    metric = compute_ratio(hag, total, mask)

    actual_res = abs(gt[1])   # gt[1] = pixel width en mètres
    sigma_px = sigma_m / actual_res
    smoothed = gaussian_filter(metric, sigma=sigma_px)
    smoothed = median_filter(smoothed, size=MEDIAN_PX)

    valid = smoothed[~mask]
    vmax = float(np.percentile(valid, 95)) if valid.size > 0 else 1.0
    norm = np.clip(smoothed / vmax if vmax > 1e-9 else smoothed, 0.0, 1.0)
    norm[mask] = 0.0

    classified = np.zeros(norm.shape, dtype=np.uint8)
    classified[norm > t406] = 85    # 406
    classified[norm > T_408] = 170  # 408
    classified[norm > T_410] = 255  # 410
    classified[mask] = 0

    _save_gdal(classified, out_tif, gt, prj)

    n406 = int(np.sum(classified == 85))
    n408 = int(np.sum(classified == 170))
    n410 = int(np.sum(classified == 255))
    print(f"  pixels → 406:{n406:,}  408:{n408:,}  410:{n410:,}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Statistiques polygones 406
# ─────────────────────────────────────────────────────────────────────────────

def _stats406(gdf) -> dict:
    sub = gdf[gdf["class"] == 406]
    if len(sub) == 0:
        return {"count": 0, "total_ha": 0.0, "coverage_pct": 0.0,
                "max_ha": 0.0, "max_pct_406": 0.0}
    areas = sub.geometry.area.values
    total_ha = areas.sum() / 1e4
    max_ha = areas.max() / 1e4
    max_pct = 100.0 * areas.max() / areas.sum() if areas.sum() > 0 else 0.0
    return {
        "count": int(len(sub)),
        "total_ha": float(total_ha),
        "coverage_pct": float(100.0 * total_ha / BBOX_AREA_HA),
        "max_ha": float(max_ha),
        "max_pct_406": float(max_pct),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg_base = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    results: dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="diag_sigma_") as tmpdir:
        tmp = pathlib.Path(tmpdir)

        for run in RUNS:
            name = run["name"]
            print(f"\n{'='*60}", flush=True)
            print(f"{name} — σ={run['sigma_m']}m, t406={run['t406']}  ({run['desc']})",
                  flush=True)
            print(f"{'='*60}", flush=True)

            out_tif = tmp / f"classified_{name.replace(' ', '_')}.tif"
            _classify(run["sigma_m"], run["t406"], out_tif)

            # fd[406]=0 pour isoler la cause raster ; fd[408/410] restent config
            cfg = copy.deepcopy(cfg_base)
            profile_key = cfg["generalization"]["active_profile"]
            cfg["generalization"]["profiles"][profile_key]["fusion_distance_m"]["406"] = 0

            gdf, logs = run_pipeline(str(out_tif), cfg, debug_dir=None)
            s = _stats406(gdf)

            delta_cov = s["coverage_pct"] - FFCO_COVERAGE_PCT
            delta_max = s["max_pct_406"] - FFCO_MAX_PCT

            print(f"  count        : {s['count']}", flush=True)
            print(f"  coverage_pct : {s['coverage_pct']:.1f}%"
                  f"   (cible {FFCO_COVERAGE_PCT}%,  Δ={delta_cov:+.1f}%)", flush=True)
            print(f"  max_ha       : {s['max_ha']:.1f} ha", flush=True)
            print(f"  max%406      : {s['max_pct_406']:.1f}%"
                  f"   (cible {FFCO_MAX_PCT}%,  Δ={delta_max:+.1f}%)", flush=True)

            results[name] = {
                **s,
                "sigma_m": run["sigma_m"],
                "t406": run["t406"],
                "delta_coverage_pct": float(delta_cov),
                "delta_max_pct": float(delta_max),
            }

    # ── Résumé comparatif ─────────────────────────────────────────────────────
    print(f"\n{'='*60}", flush=True)
    print("RÉSUMÉ — couple (coverage_pct, max%406) vs cibles FFCO", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Cibles FFCO : coverage={FFCO_COVERAGE_PCT}%  max%406={FFCO_MAX_PCT}%", flush=True)
    hdr = f"  {'Run':<12} {'σ(m)':>6} {'t406':>6} {'cov%':>8} {'Δcov':>7} {'max%':>8} {'Δmax':>7}"
    print(hdr, flush=True)
    print(f"  {'-'*67}", flush=True)
    for name, s in results.items():
        print(
            f"  {name:<12} {s['sigma_m']:>6.1f} {s['t406']:>6.2f}"
            f" {s['coverage_pct']:>8.1f}% {s['delta_coverage_pct']:>+7.1f}%"
            f" {s['max_pct_406']:>8.1f}% {s['delta_max_pct']:>+7.1f}%",
            flush=True,
        )

    # ── Lecture automatique ───────────────────────────────────────────────────
    print(f"\n{'='*60}", flush=True)
    print("LECTURE AUTOMATIQUE", flush=True)
    print(f"{'='*60}", flush=True)
    b = results.get("Baseline", {})
    a = results.get("Run A", {})
    rb = results.get("Run B", {})
    c = results.get("Run C", {})

    def _improved(r: dict) -> bool:
        return r.get("max_pct_406", 99) < b.get("max_pct_406", 0) * 0.8

    conclusions = []
    if _improved(a) and not _improved(rb):
        conclusions.append("σ est la cause principale (A améliore, B n'améliore pas)")
    elif _improved(rb) and not _improved(a):
        conclusions.append("t406 est la cause principale (B améliore, A n'améliore pas)")
    elif _improved(a) and _improved(rb):
        conclusions.append("σ ET t406 contribuent indépendamment")
    elif _improved(c) and not _improved(a) and not _improved(rb):
        conclusions.append("Effet conjoint : les deux leviers doivent bouger ensemble (C seul améliore)")
    else:
        conclusions.append("Aucun levier simple ne casse la nappe — cause probable en amont (raster brut ou tuiles)")

    for line in conclusions:
        print(f"  → {line}", flush=True)

    # ── JSON ──────────────────────────────────────────────────────────────────
    out_json = ROOT / "rapports" / "diag_sigma_t406.json"
    out_json.write_text(json.dumps({
        "ffco_targets": {
            "coverage_pct": FFCO_COVERAGE_PCT,
            "max_pct_406": FFCO_MAX_PCT,
            "source": "rapports/ffco_clip_stats.json",
        },
        "runs": results,
        "conclusions": conclusions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON -> {out_json}", flush=True)


if __name__ == "__main__":
    main()
