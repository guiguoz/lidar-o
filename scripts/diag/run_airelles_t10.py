"""Pipeline T10 Airelles — min_area_m2 406 : 50→100."""
import logging
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from src.vegetation import run_pipeline

cfg = yaml.safe_load(open("config.yaml"))
gdf, logs = run_pipeline("output_airelles/density_hag_classified.tif", cfg, debug_dir=None)

out_dir = pathlib.Path("output_airelles")
gdf.to_file(out_dir / "vegetation_final_t10.geojson", driver="GeoJSON")

print(f"\nFinal : {len(gdf)} polygones")
for cls in [406, 408, 410]:
    sub = gdf[gdf["class"] == cls]
    sub.to_file(out_dir / f"veg_{cls}_t10.geojson", driver="GeoJSON")
    area = sub.geometry.area
    print(f"  {cls} : {len(sub)} polygones | surface {area.sum()/1000:.1f} km² | médiane {area.median():.0f} m²")

# Comparaison vs T8 baseline
import geopandas as gpd
t8 = gpd.read_file(out_dir / "vegetation_final_t8.geojson")
for cls in [406, 408, 410]:
    n8 = len(t8[t8["class"] == cls])
    n10 = len(gdf[gdf["class"] == cls])
    a8 = t8[t8["class"] == cls].geometry.area.sum()
    a10 = gdf[gdf["class"] == cls].geometry.area.sum()
    print(f"  {cls} : polygones {n8}→{n10} ({(n10-n8)/n8*100:+.1f}%) | surface {a8/1e4:.1f}→{a10/1e4:.1f} ha ({(a10-a8)/a8*100:+.1f}%)")

for entry in logs:
    stage = entry["stage"]
    if "before" in entry and "after" in entry:
        b, a = entry["before"], entry["after"]
        print(f"  {stage} : {b['count']} -> {a['count']} (-{b['count']-a['count']})")
