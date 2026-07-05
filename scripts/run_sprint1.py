"""Sprint 1 — Test Polygonize + Dissolve."""
import logging
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from src.vegetation import run_pipeline

cfg = yaml.safe_load(open("config.yaml"))
gdf, logs = run_pipeline(
    "output/density_hag_classified.tif",
    cfg,
    debug_dir=pathlib.Path("debug/"),
)

counts = gdf["class"].value_counts().sort_index()
print(f"\nRésultat : {len(gdf)} polygones")
for cls, n in counts.items():
    print(f"  classe {cls} : {n}")

for entry in logs:
    stage = entry["stage"]
    if entry.get("status") == "todo":
        print(f"  {stage} : todo")
    elif stage == "remove_holes":
        print(f"  {stage} : {entry['holes_removed']} trous supprimés")
    elif stage in ("simplify", "smooth") and "vertices_before" in entry:
        b, a = entry["before"], entry["after"]
        vb, va = entry["vertices_before"], entry["vertices_after"]
        delta = b["count"] - a["count"]
        print(f"  {stage} : {b['count']} -> {a['count']} (-{delta}), sommets {vb} -> {va}")
    elif "before" in entry and "after" in entry:
        b, a = entry["before"], entry["after"]
        delta = b["count"] - a["count"]
        print(f"  {stage} : {b['count']} -> {a['count']} (-{delta})")
    else:
        print(f"  {stage} : ok")
