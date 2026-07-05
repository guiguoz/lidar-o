"""Divise debug/06_smoothed.geojson en 3 fichiers par classe CO."""
import json
import pathlib
import sys

src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("debug/06_smoothed.geojson")
data = json.loads(src.read_text(encoding="utf-8"))

for cls in [406, 408, 410]:
    features = [f for f in data["features"] if f["properties"].get("class") == str(cls)]
    out = {k: v for k, v in data.items() if k != "features"}  # copie name, crs, type
    out["features"] = features
    out_path = src.parent / f"class_{cls}.geojson"
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"class_{cls}.geojson : {len(features)} polygones")
