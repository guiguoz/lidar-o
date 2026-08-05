"""Validation multi-terrain v1 — lance le pipeline complet sur un nouveau terrain.

Usage :
    conda run --no-capture-output -n base python scripts/run_terrain.py \
        --name foret_retz \
        --tiles LIDAR/LHD_FXX_0314_6712_PTS_LAMB93_IGN69.copc.laz \
                LIDAR/LHD_FXX_0315_6712_PTS_LAMB93_IGN69.copc.laz

Sortie : output_<name>/
    density_hag.tif, total_count.tif, density_hag_classified.tif
    count_below.tif          (mode nrd)
    count_band_low.tif       (mode nrd + band_split)
    count_band_mid.tif       (mode nrd + band_split)
    vegetation_final.geojson, veg_406.geojson, veg_408.geojson, veg_410.geojson
    vegetation.gpkg (prêt pour import OCAD avec vegetation_t8.crt)
"""
import argparse
import datetime
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


# ─────────────────────────────────────────────────────────────────────────────
# Constructeurs de pipelines PDAL
# ─────────────────────────────────────────────────────────────────────────────

def _readers(tiles: list[str], reader: str = "readers.copc") -> list[dict]:
    return [{"type": reader, "filename": t} for t in tiles]


def _gdal_writer(out_tif: str, resolution: float) -> dict:
    return {
        "type": "writers.gdal",
        "filename": out_tif,
        "resolution": resolution,
        "output_type": "count",
        "data_type": "float32",
        "nodata": -1,
    }


def build_pdal_hag(tiles: list[str], out_tif: str, resolution: float,
                   min_h: float, max_h: float, reader: str = "readers.copc") -> dict:
    """Compte les retours HAG dans [min_h, max_h] — density_hag.tif."""
    return {
        "pipeline": _readers(tiles, reader) + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range",
             "limits": f"HeightAboveGround[{min_h}:{max_h}]"},
            _gdal_writer(out_tif, resolution),
        ]
    }


def build_pdal_total(tiles: list[str], out_tif: str, resolution: float,
                     reader: str = "readers.copc") -> dict:
    """Compte tous les retours (toutes hauteurs) — total_count.tif."""
    return {
        "pipeline": _readers(tiles, reader) + [
            {"type": "filters.merge"},
            _gdal_writer(out_tif, resolution),
        ]
    }


def build_pdal_below(tiles: list[str], out_tif: str, resolution: float,
                     min_h: float, reader: str = "readers.copc") -> dict:
    """Compte les retours HAG sous la bande [0, min_h] — count_below.tif.

    Ces retours ont traversé la bande de végétation sans y être absorbés :
    ils constituent le dénominateur du NRD (impulsions pénétrantes).
    """
    return {
        "pipeline": _readers(tiles, reader) + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range",
             "limits": f"HeightAboveGround[0.0:{min_h}]"},
            _gdal_writer(out_tif, resolution),
        ]
    }


def build_pdal_band_low(tiles: list[str], out_tif: str, resolution: float,
                        min_h: float, low_h: float,
                        reader: str = "readers.copc") -> dict:
    """Bande basse [min_h, low_h] — count_band_low.tif (Étape D)."""
    return {
        "pipeline": _readers(tiles, reader) + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range",
             "limits": f"HeightAboveGround[{min_h}:{low_h}]"},
            _gdal_writer(out_tif, resolution),
        ]
    }


def build_pdal_band_mid(tiles: list[str], out_tif: str, resolution: float,
                        low_h: float, mid_max: float,
                        reader: str = "readers.copc") -> dict:
    """Bande moyenne [low_h, mid_max] — count_band_mid.tif (Étape D)."""
    return {
        "pipeline": _readers(tiles, reader) + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range",
             "limits": f"HeightAboveGround[{low_h}:{mid_max}]"},
            _gdal_writer(out_tif, resolution),
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# Exécution
# ─────────────────────────────────────────────────────────────────────────────

def run_pdal(pipeline_dict: dict, label: str) -> None:
    tmp = pathlib.Path("temp") / f"pdal_{label}.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(pipeline_dict, indent=2), encoding="utf-8")
    reader_count = sum(
        1 for s in pipeline_dict["pipeline"] if str(s.get("type", "")).startswith("readers")
    )
    log.info("PDAL %s — %d reader(s) ...", label, reader_count)
    result = subprocess.run(
        ["pdal", "pipeline", str(tmp)], capture_output=True, text=True
    )
    if result.returncode != 0:
        log.error("PDAL stderr:\n%s", result.stderr)
        raise RuntimeError(f"PDAL échoué : {label}")
    log.info("PDAL %s OK", label)


def _resolve_tiles(tiles: list[str] | None, tiles_dir: str | None, force: bool,
                   reader: str = "readers.copc") -> list[str]:
    """Retourne la liste des tuiles, avec garde-fou si des tuiles du dossier sont ignorées."""
    pattern = "*.laz" if reader == "readers.las" else "*.copc.laz"

    if tiles_dir is not None:
        p = pathlib.Path(tiles_dir)
        found = sorted(p.glob(pattern))
        if not found:
            raise ValueError(f"Aucun {pattern} dans {tiles_dir}")
        log.info("--tiles-dir : %d tuile(s) dans %s", len(found), tiles_dir)
        return [str(f) for f in found]

    if not tiles:
        raise ValueError("Fournir --tiles ou --tiles-dir")

    if not force:
        parents = {pathlib.Path(t).parent for t in tiles}
        for parent in parents:
            all_in_dir = set(parent.glob(pattern))
            provided = {pathlib.Path(t) for t in tiles if pathlib.Path(t).parent == parent}
            missing = all_in_dir - provided
            if missing:
                names = "\n  ".join(sorted(m.name for m in missing))
                log.error(
                    "GARDE-FOU TUILES : %d fichier(s) present(s) dans %s mais absent(s) de --tiles :\n"
                    "  %s\n"
                    "  --> Utiliser --tiles-dir %s (auto-glob) ou ajouter ces tuiles.\n"
                    "  --> Si intentionnel (terrain partiel), ajouter --force-tiles.",
                    len(missing), parent, names, parent,
                )
                raise SystemExit(1)

    return list(tiles)


def _check_nodata(tif_path: str, label: str, warn_threshold_pct: float = 5.0) -> None:
    """Vérifie le % nodata d'un raster post-PDAL et avertit si anormalement élevé.

    Un taux > warn_threshold_pct signale typiquement des tuiles manquantes ou
    un problème de pipeline (bounding box vide, projection incorrecte).
    """
    try:
        import numpy as np
        import rasterio
    except ImportError:
        log.warning("rasterio non disponible — garde-fou nodata ignoré")
        return

    try:
        with rasterio.open(tif_path) as ds:
            arr = ds.read(1).astype(np.float32)
            nd = ds.nodata
            total = arr.size
            nodata_n = int(np.sum(arr == nd)) if nd is not None else 0
            pct = 100.0 * nodata_n / total if total > 0 else 0.0
        if pct > warn_threshold_pct:
            log.warning(
                "GARDE-FOU NODATA [%s] : %.1f%% de pixels nodata dans %s\n"
                "  Causes typiques : tuiles LiDAR manquantes, bounding box mal définie.\n"
                "  Vérifier avec diag_airelles_nodata.py ou en ouvrant le raster dans QGIS.",
                label, pct, tif_path,
            )
        else:
            log.info("Nodata check [%s] : %.1f%% — OK", label, pct)
    except Exception as exc:
        log.warning("Impossible de vérifier nodata dans %s : %s", tif_path, exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Identifiant terrain (ex: foret_retz)")
    tiles_grp = parser.add_mutually_exclusive_group(required=True)
    tiles_grp.add_argument("--tiles", nargs="+", help="Chemins explicites vers les .copc.laz")
    tiles_grp.add_argument("--tiles-dir", help="Dossier contenant les .copc.laz (auto-glob)")
    parser.add_argument("--force-tiles", action="store_true",
                        help="Desactive le garde-fou tuiles manquantes (terrain partiel)")
    parser.add_argument("--skip-pdal", action="store_true",
                        help="Saute PDAL si rasters déjà générés")
    parser.add_argument("--reader", default="readers.copc",
                        choices=["readers.copc", "readers.las"],
                        help="Type de reader PDAL (defaut: readers.copc)")
    parser.add_argument("--min-h", type=float, default=None,
                        help="Override de min_m (ex: 0.50 pour variante flip-zone)")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    READER = args.reader
    tiles = _resolve_tiles(args.tiles, args.tiles_dir, args.force_tiles, READER)

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    veg = cfg["vegetation"]
    dm = veg.get("density_metric", {})
    heights = veg.get("heights", {})

    MODE = dm.get("mode", "count")
    BAND_SPLIT = bool(dm.get("band_split", False))
    RESOLUTION = float(veg.get("grid_resolution_m", 1.0))
    MIN_H = args.min_h if args.min_h is not None else float(heights.get("min_m", 0.3))
    BAND_MAX = float(heights.get("band_max_m", 3.0))
    LOW_H = float(dm.get("low_height_m", 1.3))
    MID_MAX = float(heights.get("mid_max_m", 4.0))

    out_dir = pathlib.Path(f"output_{args.name}")
    out_dir.mkdir(exist_ok=True)

    # ── Métadonnées run — écrites avant PDAL pour traçabilité même en cas d'échec
    tile_ids = [pathlib.Path(t).stem for t in tiles]
    run_meta = {
        "terrain": args.name,
        "run_date": datetime.datetime.now().isoformat(timespec="seconds"),
        "tiles_count": len(tiles),
        "tile_ids": tile_ids,
        "pdal_skipped": args.skip_pdal,
        "mode": MODE,
        "resolution_m": RESOLUTION,
        "band_split": BAND_SPLIT,
    }
    meta_path = out_dir / "run_metadata.json"
    meta_path.write_text(json.dumps(run_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Métadonnées run -> %s (%d tuiles)", meta_path, len(tiles))

    hag_tif = str(out_dir / "density_hag.tif")
    total_tif = str(out_dir / "total_count.tif")
    below_tif = str(out_dir / "count_below.tif")
    low_tif = str(out_dir / "count_band_low.tif")
    mid_tif = str(out_dir / "count_band_mid.tif")
    classified_tif = str(out_dir / "density_hag_classified.tif")

    # ── 1. PDAL ───────────────────────────────────────────────────────────────
    if not args.skip_pdal:
        # Raster principal : HAG [min_h:band_max]
        run_pdal(
            build_pdal_hag(tiles, hag_tif, RESOLUTION, MIN_H, BAND_MAX, READER),
            f"{args.name}_hag",
        )
        # Ratio mode : besoin du total
        if MODE in ("ratio", "count"):
            run_pdal(
                build_pdal_total(tiles, total_tif, RESOLUTION, READER),
                f"{args.name}_total",
            )
        # NRD mode : besoin des retours sous la bande
        if MODE == "nrd":
            run_pdal(
                build_pdal_below(tiles, below_tif, RESOLUTION, MIN_H, READER),
                f"{args.name}_below",
            )
            if BAND_SPLIT:
                run_pdal(
                    build_pdal_band_low(tiles, low_tif, RESOLUTION, MIN_H, LOW_H, READER),
                    f"{args.name}_low",
                )
                run_pdal(
                    build_pdal_band_mid(tiles, mid_tif, RESOLUTION, LOW_H, MID_MAX, READER),
                    f"{args.name}_mid",
                )
    else:
        log.info("PDAL ignoré (--skip-pdal)")

    # ── Garde-fou nodata post-PDAL ────────────────────────────────────────────
    if not args.skip_pdal:
        _check_nodata(hag_tif, args.name, warn_threshold_pct=5.0)

    # ── 2. Normalisation + classification ────────────────────────────────────
    log.info("process_hag.py → lancer manuellement si besoin :")
    log.info("  py -3.14 scripts/process_hag.py --src %s", hag_tif)

    classified_path = pathlib.Path(classified_tif)
    if not classified_path.exists():
        log.error(
            "ARRÊT : density_hag_classified.tif absent — lancer process_hag.py :\n"
            "  py -3.14 scripts/process_hag.py --src %s\n"
            "  Puis relancer avec --skip-pdal.",
            hag_tif,
        )
        sys.exit(1)

    # Garde-fou fraîcheur : classified doit être plus récent que density_hag.tif.
    # Indépendant de --skip-pdal : un classified périmé produit des chiffres plausibles
    # mais faux (cf. Airelles 16 tuiles → résultats calculés sur artefact 14 tuiles).
    hag_path = pathlib.Path(hag_tif)
    if hag_path.exists():
        hag_mtime = hag_path.stat().st_mtime
        cls_mtime = classified_path.stat().st_mtime
        if cls_mtime < hag_mtime:
            fmt = datetime.datetime.fromtimestamp
            log.error(
                "ARRÊT — GARDE-FOU FRAÎCHEUR : density_hag_classified.tif (%s)"
                " est antérieur à density_hag.tif (%s).\n"
                "  Artefact périmé détecté — lancer process_hag.py pour régénérer :\n"
                "  py -3.14 scripts/process_hag.py --src %s\n"
                "  Puis relancer avec --skip-pdal.",
                fmt(cls_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
                fmt(hag_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
                hag_tif,
            )
            sys.exit(1)

    # ── 3. Pipeline généralisation ────────────────────────────────────────────
    log.info("Pipeline généralisation ...")
    gdf, logs = run_pipeline(classified_tif, cfg, debug_dir=None)

    # ── 4. Sauvegarde ─────────────────────────────────────────────────────────
    gdf.to_file(out_dir / "vegetation_final.geojson", driver="GeoJSON")
    gpkg = out_dir / "vegetation.gpkg"
    for cls in [406, 408, 410]:
        sub = gdf[gdf["class"] == cls]
        sub.to_file(out_dir / f"veg_{cls}.geojson", driver="GeoJSON")
        sub.to_file(gpkg, layer=f"veg_{cls}", driver="GPKG")

    # ── 5. Résultats ──────────────────────────────────────────────────────────
    print(f"\n=== {args.name} — résultats ===")
    print(f"Tuiles     : {len(tiles)}")
    print(f"Résolution : {RESOLUTION}m | Mode : {MODE} | band_split={BAND_SPLIT}")
    print(f"Total      : {len(gdf)} polygones")
    for cls in [406, 408, 410]:
        sub = gdf[gdf["class"] == cls]
        area = sub.geometry.area
        print(f"  {cls} : {len(sub)} polygones | {area.sum()/1e4:.1f} ha | médiane {area.median():.0f} m²")

    print(f"\nGeoPackage OCAD : {gpkg}")
    print("CRT à utiliser  : output/vegetation_t8.crt  (champ 'class')")

    # ── 6. Log pipeline ───────────────────────────────────────────────────────
    print("\nLog étapes :")
    for entry in logs:
        if "before" in entry and "after" in entry:
            b, a = entry["before"], entry["after"]
            pct = (a["count"] - b["count"]) / b["count"] * 100 if b["count"] else 0
            print(f"  {entry['stage']:25s} : {b['count']:5d} → {a['count']:5d} ({pct:+.1f}%)")


if __name__ == "__main__":
    main()
