"""Vectorise supervised_v1_pred.tif → vegetation_rf.gpkg (3 couches veg_406/408/410).

Réplique exactement le pipeline step_vegetation_kp :
  1. Lecture raster (codes 2→406, 3→408, 4→410)
  2. Polygonisation rasterio par classe
  3. coverage_is_valid intra-classe
  4. coverage_simplify global (tol=2.0 m)
  5. Écriture GPKG

Sortie : output_bois_dupont/vegetation_rf.gpkg
Après validation, remplacer vegetation_kp.gpkg par vegetation_rf.gpkg et relancer assemble.
"""
from __future__ import annotations

import logging
import pathlib
import shutil
import sys

import numpy as np
import rasterio
import shapely
import shapely.geometry as sg
import geopandas as gpd
from rasterio.features import shapes as rasterio_shapes

_THIS = pathlib.Path(__file__).resolve().parent
_ROOT = _THIS.parents[2]
_OUTPUT = _ROOT / "output_bois_dupont"

PRED_TIF = _THIS / "figures" / "supervised_v1_pred.tif"
OUT_RF_GPKG = _OUTPUT / "vegetation_rf.gpkg"
OUT_KP_GPKG = _OUTPUT / "vegetation_kp.gpkg"

CODE_TO_ISOM = {2: 406, 3: 408, 4: 410}
TOL_M = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def vectorize(pred_tif: pathlib.Path = PRED_TIF) -> pathlib.Path:
    if not pred_tif.exists():
        raise FileNotFoundError(f"Raster introuvable : {pred_tif}")

    with rasterio.open(pred_tif) as ds:
        data = ds.read(1)
        transform = ds.transform
        crs_str = ds.crs.to_string()

    log.info("Raster : %s  shape=%s  crs=%s", pred_tif.name, data.shape, crs_str)

    all_geoms: list = []
    all_codes: list[int] = []

    for cls_code, isom in sorted(CODE_TO_ISOM.items()):
        mask_arr = (data == cls_code).astype(np.uint8)
        n_px = int(mask_arr.sum())
        if n_px == 0:
            log.warning("Classe %d (ISOM %d) : aucun pixel — couche vide", cls_code, isom)
            continue

        geoms: list = []
        for geom_dict, _ in rasterio_shapes(mask_arr, mask=mask_arr, transform=transform):
            geom = sg.shape(geom_dict)
            if not geom.is_empty:
                geoms.append(geom)

        if not geoms:
            log.warning("Classe %d (ISOM %d) : %d px mais aucun polygone produit", cls_code, isom, n_px)
            continue

        geom_arr_cls = np.array(geoms, dtype=object)
        if not shapely.coverage_is_valid(geom_arr_cls):
            invalid_edges = shapely.coverage_invalid_edges(geom_arr_cls)
            n_inv = int(sum(1 for e in invalid_edges if e is not None and not e.is_empty))
            raise ValueError(
                f"Couverture invalide intra-classe ISOM {isom} ({n_inv} arête(s)) — "
                "vérifier la polygonisation."
            )

        all_geoms.extend(geoms)
        all_codes.extend([isom] * len(geoms))
        log.info("ISOM %d : %d px → %d polygones (avant simplify)", isom, n_px, len(geoms))

    if not all_geoms:
        log.error("Aucun polygone produit — GPKG vide")
        for code in [406, 408, 410]:
            gpd.GeoDataFrame({"geometry": []}, crs=crs_str).to_file(
                str(OUT_RF_GPKG), layer=f"veg_{code}", driver="GPKG",
            )
        return OUT_RF_GPKG

    log.info("coverage_simplify global (%d polygones, tol=%.1f m)...", len(all_geoms), TOL_M)
    geom_arr = np.array(all_geoms, dtype=object)
    simplified = shapely.coverage_simplify(geom_arr, tolerance=TOL_M, simplify_boundary=True)

    layers: dict[int, list] = {406: [], 408: [], 410: []}
    for geom, code in zip(simplified, all_codes):
        if geom is not None and not geom.is_empty:
            layers[code].append(geom)

    _OUTPUT.mkdir(parents=True, exist_ok=True)
    for code in [406, 408, 410]:
        gdf = gpd.GeoDataFrame({"geometry": layers[code]}, crs=crs_str)
        gdf.to_file(str(OUT_RF_GPKG), layer=f"veg_{code}", driver="GPKG")

    counts = {c: len(v) for c, v in layers.items()}
    log.info(
        "vegetation_rf.gpkg : veg_406=%d  veg_408=%d  veg_410=%d  total=%d polygones",
        counts[406], counts[408], counts[410], sum(counts.values()),
    )
    return OUT_RF_GPKG


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--replace-kp", action="store_true",
        help="Remplace vegetation_kp.gpkg par vegetation_rf.gpkg après vectorisation "
             "(permet de relancer step_assemble directement).",
    )
    args = parser.parse_args()

    out = vectorize()
    print(f"Ecrit : {out}")

    if args.replace_kp:
        shutil.copy2(out, OUT_KP_GPKG)
        log.info("vegetation_kp.gpkg remplace par vegetation_rf.gpkg")
        print(f"Remplace : {OUT_KP_GPKG}")
