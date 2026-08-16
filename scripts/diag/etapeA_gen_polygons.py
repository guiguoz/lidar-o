"""Génère les polygones CO pour les 4 résolutions Étape A.

Utilise run_pipeline() sur les classified.tif déjà produits par process_hag.py.
Sortie : output_etapeA_{res}/veg_406.geojson + veg_408.geojson + veg_410.geojson

Statistiques de tailles imprimées : count, min, p10, p25, p50, max, total_ha.
Nécessite geopandas → conda base.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import numpy as np
import yaml
import geopandas as gpd

from src.vegetation import run_pipeline

RESOLUTIONS = ["1m", "2m", "3m", "4m"]
ROOT = pathlib.Path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _area_stats(areas: "np.ndarray") -> dict:
    if len(areas) == 0:
        return {"count": 0}
    return {
        "count": int(len(areas)),
        "min_m2": float(areas.min()),
        "p10_m2": float(np.percentile(areas, 10)),
        "p25_m2": float(np.percentile(areas, 25)),
        "p50_m2": float(np.percentile(areas, 50)),
        "p75_m2": float(np.percentile(areas, 75)),
        "max_m2": float(areas.max()),
        "total_ha": float(areas.sum() / 1e4),
    }


def main() -> None:
    results = {}

    for res in RESOLUTIONS:
        out_dir = ROOT / f"output_etapeA_{res}"
        classified = out_dir / "density_hag_classified.tif"
        if not classified.exists():
            print(f"[ABSENT] {classified}", flush=True)
            continue

        print(f"\n{'='*50}", flush=True)
        print(f"  Résolution {res}", flush=True)
        print(f"{'='*50}", flush=True)

        gdf, logs = run_pipeline(str(classified), CFG, debug_dir=None)

        # Sauvegarde polygones
        gdf.to_file(out_dir / "vegetation_final.geojson", driver="GeoJSON")
        for cls in [406, 408, 410]:
            sub = gdf[gdf["class"] == cls]
            sub.to_file(out_dir / f"veg_{cls}.geojson", driver="GeoJSON")

        # Statistiques par classe
        stats_res = {}
        for cls in [406, 408, 410]:
            sub = gdf[gdf["class"] == cls]
            areas = sub.geometry.area.values if len(sub) > 0 else np.array([])
            s = _area_stats(areas)
            stats_res[str(cls)] = s

            print(f"\n  Classe {cls} :", flush=True)
            if s.get("count", 0) == 0:
                print("    Aucun polygone", flush=True)
            else:
                print(f"    count    : {s['count']}", flush=True)
                print(f"    min      : {s['min_m2']:.0f} m²", flush=True)
                print(f"    p10      : {s['p10_m2']:.0f} m²", flush=True)
                print(f"    p25      : {s['p25_m2']:.0f} m²", flush=True)
                print(f"    median   : {s['p50_m2']:.0f} m²", flush=True)
                print(f"    p75      : {s['p75_m2']:.0f} m²", flush=True)
                print(f"    max      : {s['max_m2']:.0f} m²", flush=True)
                print(f"    total    : {s['total_ha']:.1f} ha", flush=True)

        # Log étapes
        print(f"\n  Pipeline CO :", flush=True)
        for entry in logs:
            if "before" in entry and "after" in entry:
                b, a = entry["before"], entry["after"]
                pct = (a["count"] - b["count"]) / b["count"] * 100 if b["count"] else 0
                print(f"    {entry['stage']:30s}: {b['count']:5d} → {a['count']:5d} ({pct:+.1f}%)", flush=True)

        results[res] = stats_res

    # Résumé comparatif 406
    print(f"\n{'='*50}", flush=True)
    print("  COMPARATIF 406 — impact résolution sur les taches", flush=True)
    print(f"{'='*50}", flush=True)
    print(f"  {'Rés':<5} {'count':>6} {'min':>8} {'p10':>8} {'p50':>8} {'total_ha':>10}", flush=True)
    for res in RESOLUTIONS:
        s = results.get(res, {}).get("406", {})
        if s.get("count", 0) == 0:
            print(f"  {res:<5} {'—':>6}", flush=True)
        else:
            print(
                f"  {res:<5} {s['count']:>6} {s['min_m2']:>8.0f} {s['p10_m2']:>8.0f} "
                f"{s['p50_m2']:>8.0f} {s['total_ha']:>10.1f}",
                flush=True,
            )

    # Sauvegarder le résumé JSON
    rap_dir = ROOT / "rapports"
    rap_dir.mkdir(exist_ok=True)
    (rap_dir / "etapeA_polygons_summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\nRésumé JSON -> rapports/etapeA_polygons_summary.json", flush=True)


if __name__ == "__main__":
    main()
