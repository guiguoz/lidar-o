"""Rapport QA végétation — à lancer après chaque run de production.

Affiche le quadruplet (cov%, n, med mm², %<1mm², max%406) par classe,
avec l'écart par rapport aux cibles FFCO si le profil les contient.
Écrit également un snapshot de la config dans run_metadata.json.

Usage :
    python scripts/report_metrics.py
"""
from __future__ import annotations

import pathlib
import sys

import geopandas as gpd
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.guards import check_config_snapshot
from src.qa import load_ffco_hull, report_hull_metrics, write_config_snapshot

ROOT       = pathlib.Path(".")
VEG_GPKG   = ROOT / "output" / "controle_visuel" / "vegetation_grimbosq.gpkg"
FFCO_GPKG  = ROOT / "grimbosq.gpkg"
OUTPUT_DIR = ROOT / "output"

LAYER_MAP = {406: "406_Slow_Running", 408: "408_Walk", 410: "410_Fight"}


def main() -> None:
    for p in [VEG_GPKG]:
        if not p.exists():
            sys.exit(f"ABSENT : {p} — lancer process_hag.py d'abord")

    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8", errors="replace"))

    diffs = check_config_snapshot(cfg, OUTPUT_DIR / "run_metadata.json")
    if diffs:
        print("ATTENTION -- CONFIG MODIFIEE depuis le dernier snapshot enregistre :")
        for d in diffs:
            print(f"  {d}")
        print("  Rebuild recommande (process_hag.py + regeneration GPKG) avant ce rapport.")
        print()

    print("Chargement GPKG …")
    gdfs = []
    for code, name in LAYER_MAP.items():
        gdf = gpd.read_file(VEG_GPKG, layer=name)
        gdf = gdf.copy()
        gdf["class"] = code
        gdfs.append(gdf)
    import pandas as pd
    gdf_all = pd.concat(gdfs, ignore_index=True)
    gdf_all = gpd.GeoDataFrame(gdf_all, geometry="geometry", crs=gdfs[0].crs)

    print("Chargement hull FFCO …")
    hull = load_ffco_hull(FFCO_GPKG)

    report_hull_metrics(gdf_all, cfg, hull)

    write_config_snapshot(cfg, OUTPUT_DIR)
    print("Snapshot config écrit dans output/run_metadata.json")


if __name__ == "__main__":
    main()
