"""Diagnostique la percolation du merge_proximity.

Étape 1 — clip FFCO sur la bbox pipeline et mesure la vraie distribution vectorielle.
Étape 2 — runs à fusion_distance_m[406] = 0, 2, 4, 8 m sur classified.tif 1m.

Nécessite geopandas + shapely (conda base).
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import geopandas as gpd
import numpy as np
import yaml
from shapely.geometry import box

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.vegetation import run_pipeline
from scripts.measure_corpus import load_ffco

ROOT = pathlib.Path(".")
GPKG = ROOT / "grimbosq.gpkg"
CLASSIFIED = ROOT / "output_etapeA_1m" / "density_hag_classified.tif"

# Bbox pipeline (Lambert 93, mesurée sur density_hag.tif)
BBOX = (448000.0, 6886000.0, 450001.0, 6889001.0)  # left, bottom, right, top
BBOX_AREA_HA = (BBOX[2] - BBOX[0]) * (BBOX[3] - BBOX[1]) / 1e4


def _poly_stats(gdf: gpd.GeoDataFrame, label: str) -> dict:
    """Statistiques de tailles et de structure pour les polygones 406."""
    sub = gdf[gdf["class"].astype(str) == "406"] if "class" in gdf.columns else gdf.copy()
    if len(sub) == 0:
        print(f"  {label}: 0 polygones", flush=True)
        return {}
    areas = sub.geometry.area.values
    total_ha = areas.sum() / 1e4
    max_ha = areas.max() / 1e4
    max_pct = 100 * areas.max() / areas.sum() if areas.sum() > 0 else 0
    print(f"\n  {label} :", flush=True)
    print(f"    count     : {len(sub)}", flush=True)
    print(f"    total     : {total_ha:.1f} ha  ({100*total_ha/BBOX_AREA_HA:.1f}% emprise)", flush=True)
    print(f"    plus gros : {max_ha:.1f} ha  ({max_pct:.1f}% du 406)", flush=True)
    print(f"    median    : {np.median(areas)/1e4*1e4:.0f} m²", flush=True)
    print(f"    min       : {areas.min():.0f} m²", flush=True)
    # Top 5
    top5 = sorted(areas, reverse=True)[:5]
    top5_pct = [100 * a / areas.sum() for a in top5]
    print(f"    top5 %    : {' / '.join(f'{p:.1f}' for p in top5_pct)}", flush=True)
    return {
        "count": int(len(sub)),
        "total_ha": float(total_ha),
        "coverage_pct": float(100 * total_ha / BBOX_AREA_HA),
        "max_ha": float(max_ha),
        "max_pct_of_406": float(max_pct),
        "median_m2": float(np.median(areas)),
        "top5_pct": [float(p) for p in top5_pct],
    }


# ── Étape 1 : FFCO clippé ────────────────────────────────────────────────────

print("=" * 60, flush=True)
print("ÉTAPE 1 — FFCO Grimbosq clippé sur bbox pipeline", flush=True)
print(f"  Bbox : {BBOX}", flush=True)
print(f"  Surface bbox : {BBOX_AREA_HA:.1f} ha", flush=True)
print("=" * 60, flush=True)

# load_ffco utilise OGR directement (contourne pyogrio/encodage latin-1)
# et auto-détecte la couche *_areas
gdf_ffco = load_ffco(str(GPKG), class_col="class")
print(f"\n  GPKG chargé : {len(gdf_ffco)} features, CRS={gdf_ffco.crs}", flush=True)

# Réparer géométries invalides (TopologyException connue à 448762.17, 6886835.99)
gdf_ffco = gdf_ffco.copy()
gdf_ffco.geometry = gdf_ffco.geometry.buffer(0)

# Clip sur bbox
clip_box = box(*BBOX)
gdf_clipped = gdf_ffco.clip(clip_box)
print(f"  Après clip  : {len(gdf_clipped)} features", flush=True)

ffco_stats = _poly_stats(gdf_clipped, "FFCO 406 (clippé bbox)")

# Toutes classes
for cls in [406, 408, 410]:
    sub = gdf_clipped[gdf_clipped["class"].astype(str) == str(cls)]
    area_ha = sub.geometry.area.sum() / 1e4
    print(f"  FFCO {cls} clippé : {len(sub)} poly, {area_ha:.1f} ha  "
          f"({100*area_ha/BBOX_AREA_HA:.1f}% emprise)", flush=True)

# ── Étape 2 : runs fusion_distance ────────────────────────────────────────────

print("\n" + "=" * 60, flush=True)
print("ÉTAPE 2 — Runs fusion_distance_m[406] = 0 / 2 / 4 / 8 m", flush=True)
print("=" * 60, flush=True)

cfg_base = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
results = {}

for fd in [0, 2, 4, 8]:
    cfg = copy.deepcopy(cfg_base)
    profile = cfg["generalization"]["active_profile"]
    cfg["generalization"]["profiles"][profile]["fusion_distance_m"]["406"] = fd

    gdf_run, logs = run_pipeline(str(CLASSIFIED), cfg, debug_dir=None)
    stats = _poly_stats(gdf_run, f"Pipeline fusion={fd}m")

    # Log pipeline
    print(f"    Pipeline CO stages :", flush=True)
    for entry in logs:
        if "before" in entry and "after" in entry:
            b, a = entry["before"], entry["after"]
            pct = (a["count"] - b["count"]) / b["count"] * 100 if b["count"] else 0
            print(f"      {entry['stage']:28s}: {b['count']:5d} → {a['count']:5d} ({pct:+.1f}%)",
                  flush=True)

    results[str(fd)] = stats

# ── Résumé comparatif ─────────────────────────────────────────────────────────

print("\n" + "=" * 60, flush=True)
print("RÉSUMÉ COMPARATIF — 406", flush=True)
print("=" * 60, flush=True)
print(f"  {'Source':<20} {'count':>6} {'total_ha':>10} {'emprise%':>9} {'max%406':>9}", flush=True)

if ffco_stats:
    print(f"  {'FFCO clippé':<20} {ffco_stats['count']:>6} "
          f"{ffco_stats['total_ha']:>10.1f} {ffco_stats['coverage_pct']:>9.1f}% "
          f"{ffco_stats['max_pct_of_406']:>9.1f}%", flush=True)

for fd, s in results.items():
    if s:
        print(f"  {'Pipeline fd='+fd+'m':<20} {s['count']:>6} "
              f"{s['total_ha']:>10.1f} {s['coverage_pct']:>9.1f}% "
              f"{s['max_pct_of_406']:>9.1f}%", flush=True)

# Sauvegarde
out = {"ffco_clipped": ffco_stats, "pipeline_fusion_runs": results,
       "bbox": BBOX, "bbox_area_ha": BBOX_AREA_HA}
(ROOT / "rapports" / "fusion_percolation_diag.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print("\nJSON -> rapports/fusion_percolation_diag.json", flush=True)
