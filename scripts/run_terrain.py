"""Validation multi-terrain v1 — lance le pipeline complet sur un nouveau terrain.

Usage :
    conda run --no-capture-output -n base python scripts/run_terrain.py \
        --name foret_retz \
        --tiles LIDAR/LHD_FXX_0314_6712_PTS_LAMB93_IGN69.copc.laz \
                LIDAR/LHD_FXX_0315_6712_PTS_LAMB93_IGN69.copc.laz

Sortie : output_<name>/
    density_hag.tif, total_count.tif, density_hag_classified.tif
    vegetation_final.geojson, veg_406.geojson, veg_408.geojson, veg_410.geojson
    vegetation.gpkg (prêt pour import OCAD avec vegetation_t8.crt)
"""
import argparse
import json
import logging
import pathlib
import subprocess
import sys

import geopandas as gpd
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.vegetation import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

CONDA = "C:/Users/glemi/miniconda3/Scripts/conda.exe"
PY314 = "py -3.14"


def build_pdal_hag(tiles: list[str], out_tif: str) -> dict:
    readers = [{"type": "readers.copc", "filename": t} for t in tiles]
    return {
        "pipeline": readers + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range", "limits": "HeightAboveGround[0.3:3.0]"},
            {
                "type": "writers.gdal",
                "filename": out_tif,
                "resolution": 1.0,
                "output_type": "count",
                "data_type": "float32",
                "nodata": -1,
            },
        ]
    }


def build_pdal_total(tiles: list[str], out_tif: str) -> dict:
    readers = [{"type": "readers.copc", "filename": t} for t in tiles]
    return {
        "pipeline": readers + [
            {"type": "filters.merge"},
            {
                "type": "writers.gdal",
                "filename": out_tif,
                "resolution": 1.0,
                "output_type": "count",
                "data_type": "float32",
                "nodata": -1,
            },
        ]
    }


def run_pdal(pipeline_dict: dict, label: str) -> None:
    tmp = pathlib.Path("temp") / f"pdal_{label}.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(pipeline_dict, indent=2), encoding="utf-8")
    log.info("PDAL %s ...", label)
    result = subprocess.run(["pdal", "pipeline", str(tmp)], capture_output=True, text=True)
    if result.returncode != 0:
        log.error("PDAL stderr:\n%s", result.stderr)
        raise RuntimeError(f"PDAL échoué : {label}")
    log.info("PDAL %s OK", label)


def run_process_hag(src_tif: str) -> None:
    log.info("process_hag.py ...")
    result = subprocess.run(
        [sys.executable, "scripts/process_hag.py", "--src", src_tif],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error(result.stderr)
        raise RuntimeError("process_hag.py échoué")
    log.info(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Identifiant terrain (ex: foret_retz)")
    parser.add_argument("--tiles", nargs="+", required=True, help="Chemins vers les .copc.laz")
    parser.add_argument("--skip-pdal", action="store_true", help="Saute PDAL si rasters déjà générés")
    args = parser.parse_args()

    out_dir = pathlib.Path(f"output_{args.name}")
    out_dir.mkdir(exist_ok=True)

    hag_tif = str(out_dir / "density_hag.tif")
    total_tif = str(out_dir / "total_count.tif")
    classified_tif = str(out_dir / "density_hag_classified.tif")

    # 1. PDAL
    if not args.skip_pdal:
        run_pdal(build_pdal_hag(args.tiles, hag_tif), f"{args.name}_hag")
        run_pdal(build_pdal_total(args.tiles, total_tif), f"{args.name}_total")
    else:
        log.info("PDAL ignoré (--skip-pdal)")

    # 2. Normalisation + classification
    # process_hag.py utilise rasterio (py -3.14) — appel séparé si nécessaire
    # Si lancé depuis conda, utiliser :
    #   py -3.14 scripts/process_hag.py --src output_<name>/density_hag.tif
    log.info("process_hag.py → lancer manuellement si besoin :")
    log.info("  py -3.14 scripts/process_hag.py --src %s", hag_tif)

    if not pathlib.Path(classified_tif).exists():
        log.warning("density_hag_classified.tif absent — lancer process_hag.py d'abord (py -3.14)")
        log.warning("Puis relancer : python scripts/run_terrain.py --name %s --tiles ... --skip-pdal", args.name)
        sys.exit(1)

    # 3. Pipeline généralisation
    cfg = yaml.safe_load(open("config.yaml"))
    log.info("Pipeline généralisation ...")
    gdf, logs = run_pipeline(classified_tif, cfg, debug_dir=None)

    # 4. Sauvegarde
    gdf.to_file(out_dir / "vegetation_final.geojson", driver="GeoJSON")
    gpkg = out_dir / "vegetation.gpkg"
    for cls in [406, 408, 410]:
        sub = gdf[gdf["class"] == cls]
        sub.to_file(out_dir / f"veg_{cls}.geojson", driver="GeoJSON")
        sub.to_file(gpkg, layer=f"veg_{cls}", driver="GPKG")

    # 5. Résultats
    print(f"\n=== {args.name} — résultats ===")
    print(f"Tuiles : {len(args.tiles)}")
    print(f"Total  : {len(gdf)} polygones")
    for cls in [406, 408, 410]:
        sub = gdf[gdf["class"] == cls]
        area = sub.geometry.area
        print(f"  {cls} : {len(sub)} polygones | {area.sum()/1e4:.1f} ha | médiane {area.median():.0f} m²")

    print(f"\nGeoPackage OCAD : {gpkg}")
    print("CRT à utiliser  : output/vegetation_t8.crt  (champ 'class')")

    # 6. Log pipeline
    print("\nLog étapes :")
    for entry in logs:
        if "before" in entry and "after" in entry:
            b, a = entry["before"], entry["after"]
            pct = (a["count"] - b["count"]) / b["count"] * 100 if b["count"] else 0
            print(f"  {entry['stage']:25s} : {b['count']:5d} → {a['count']:5d} ({pct:+.1f}%)")


if __name__ == "__main__":
    main()
