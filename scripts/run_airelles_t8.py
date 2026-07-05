"""Pipeline T8 Airelles — exporte GeoJSON final + split par classe."""
import logging
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from src.vegetation import run_pipeline

cfg = yaml.safe_load(open("config.yaml"))
gdf, logs = run_pipeline(
    "output_airelles/density_hag_classified.tif",
    cfg,
    debug_dir=None,
)

out_dir = pathlib.Path("output_airelles")

gdf.to_file(out_dir / "vegetation_final_t9.geojson", driver="GeoJSON")
print(f"\nFinal : {len(gdf)} polygones -> {out_dir / 'vegetation_final_t9.geojson'}")

for cls in [406, 408, 410]:
    sub = gdf[gdf["class"] == cls]
    sub.to_file(out_dir / f"veg_{cls}_t9.geojson", driver="GeoJSON")
    print(f"  {cls} : {len(sub)} polygones")

for entry in logs:
    stage = entry["stage"]
    if "before" in entry and "after" in entry:
        b, a = entry["before"], entry["after"]
        delta = b["count"] - a["count"]
        print(f"  {stage} : {b['count']} -> {a['count']} (-{delta})")
    else:
        print(f"  {stage} : ok")
