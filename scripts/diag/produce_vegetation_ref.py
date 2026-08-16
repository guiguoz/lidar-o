"""Run de production vegetation Grimbosq -- reference v3_vegetation_fd.

Utilise output/density_hag_classified.tif (sigma=1.0, regenere 2026-08-06)
et la config active (fd[406]=2, sigma=1.0, t406=0.20).
Ecrit output/vegetation.gpkg -- reference canonique, remplace t8/t10.

Usage :
    python scripts/produce_vegetation_ref.py
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

import geopandas as gpd
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
OUT = ROOT / "output"
CLASSIFIED = OUT / "density_hag_classified.tif"
BBOX_HA = 600.5


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")

    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        cfg = yaml.safe_load(f)

    # Verifier sigma et fd actifs
    sigma = cfg["vegetation"]["process_hag"]["gaussian_sigma"]
    profile = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    fd406 = profile["fusion_distance_m"][406]
    t406 = cfg["vegetation"]["presets"][cfg["vegetation"]["active_preset"]]["thresholds"][0]
    print(f"Config : sigma={sigma}, t406={t406}, fd[406]={fd406}")

    print("Pipeline generalisation ...")
    gdf, logs = run_pipeline(str(CLASSIFIED), cfg)

    # Sauvegarder
    gpkg = OUT / "vegetation.gpkg"
    for cls in [406, 408, 410]:
        sub = gdf[gdf["class"] == cls]
        sub.to_file(gpkg, layer=f"veg_{cls}", driver="GPKG")

    # Metriques 406
    sub406 = gdf[gdf["class"] == 406]
    areas = sub406.area
    ha = areas.sum() / 1e4
    max_pct = areas.max() / areas.sum() * 100
    cov = ha / BBOX_HA * 100

    print(f"\n=== Grimbosq v3_vegetation_fd ===")
    print(f"  veg_406 : {len(sub406)} poly, {ha:.1f} ha, cov={cov:.1f}%, max%={max_pct:.1f}%")
    print(f"  veg_408 : {len(gdf[gdf['class']==408])} poly")
    print(f"  veg_410 : {len(gdf[gdf['class']==410])} poly")
    print(f"  GPKG    : {gpkg}")

    # run_metadata
    meta = {
        "terrain": "grimbosq",
        "run_date": datetime.datetime.now().isoformat(timespec="seconds"),
        "script": "produce_vegetation_ref.py",
        "tag": "v3_vegetation_fd",
        "sigma": sigma,
        "t406": t406,
        "fd_406": fd406,
        "classified_tif": str(CLASSIFIED),
        "metrics_406": {
            "count": int(len(sub406)),
            "total_ha": round(float(ha), 2),
            "coverage_pct": round(float(cov), 2),
            "max_pct_406": round(float(max_pct), 2),
        },
    }
    (OUT / "run_metadata_v3.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Metadata: output/run_metadata_v3.json")


if __name__ == "__main__":
    main()
