"""Clip FFCO Grimbosq sur bbox pipeline et affiche les stats par classe.

Correctif : class column est string ("406") dans load_ffco(), pas int.
"""
from __future__ import annotations
import json
import pathlib
import sys

import geopandas as gpd
from shapely.geometry import box

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from scripts.measure_corpus import load_ffco

ROOT = pathlib.Path(".")
GPKG = ROOT / "grimbosq.gpkg"
BBOX = (448000.0, 6886000.0, 450001.0, 6889001.0)
BBOX_AREA_HA = (BBOX[2] - BBOX[0]) * (BBOX[3] - BBOX[1]) / 1e4

print(f"Bbox : {BBOX}  ({BBOX_AREA_HA:.1f} ha)", flush=True)

gdf = load_ffco(str(GPKG), class_col="class")
print(f"GPKG chargé : {len(gdf)} features, CRS={gdf.crs}", flush=True)
print(f"Types uniques de 'class' : {gdf['class'].dtype} — ex: {gdf['class'].iloc[:3].tolist()}", flush=True)

gdf.geometry = gdf.geometry.buffer(0)
gdf_clip = gdf.clip(box(*BBOX))
print(f"Après clip : {len(gdf_clip)} features", flush=True)

results = {}
for cls in [406, 408, 410]:
    sub = gdf_clip[gdf_clip["class"].astype(str) == str(cls)]
    area_ha = sub.geometry.area.sum() / 1e4
    results[str(cls)] = {"count": len(sub), "area_ha": float(area_ha)}
    print(f"  FFCO {cls} clippé : {len(sub)} poly, {area_ha:.1f} ha  "
          f"({100*area_ha/BBOX_AREA_HA:.1f}% emprise)", flush=True)

if results.get("406", {}).get("count", 0) > 0:
    sub406 = gdf_clip[gdf_clip["class"].astype(str) == "406"]
    areas = sub406.geometry.area.values
    max_ha = areas.max() / 1e4
    max_pct = 100 * areas.max() / areas.sum()
    print(f"\n  FFCO 406 — plus gros : {max_ha:.1f} ha  ({max_pct:.1f}% du 406)", flush=True)
    results["406"]["max_ha"] = float(max_ha)
    results["406"]["max_pct"] = float(max_pct)

out_path = ROOT / "rapports" / "ffco_clip_stats.json"
out_path.write_text(json.dumps({"bbox": BBOX, "bbox_area_ha": BBOX_AREA_HA, "classes": results},
                               indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nJSON -> {out_path}", flush=True)
