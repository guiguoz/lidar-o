"""Inférence autonome — ne requiert PAS le raster OCAD.

Entrées :
  - raster de strates (4 bandes) ou chemin LAZ + emprise/CRS
  - modèle + imputer sauvegardés (clf_<id>.pkl)

Sortie :
  - raster des catégories prédites (uint8, même grille que strates)
  - PNG + géoréférencement
  - masque de support

Vérification explicite :
  - aucun argument OCAD n'est utilisé ni demandé
  - la commande fonctionne sans VegetationBaseMap
"""
from __future__ import annotations

import pathlib
import pickle
import sys

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from PIL import Image

_THIS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

from config import (
    STRATES_PATH, MODELS_DIR, FIGURES_DIR,
    BBOX, CRS, RES_M, GRID_H, GRID_W,
    LABEL_NODATA, CLASS_DISPLAY, NODATA_COLOR,
)
from descriptors import build_descriptors, N_FEATURES


def infer(
    strates_path: pathlib.Path,
    model_id: int | None = None,  # None → charge best.json
    *,
    out_dir: pathlib.Path | None = None,
    ocad_path: pathlib.Path | None = None,  # INTERDIT — vérifié explicitement
) -> np.ndarray:
    """
    Prédit les catégories de végétation depuis un raster de strates.
    Ne lit PAS le raster OCAD.

    Retourne pred_grid (H, W) uint8.
    """
    # Vérification d'indépendance OCAD
    assert ocad_path is None, (
        "infer() ne doit pas recevoir de chemin OCAD. "
        "L'inférence autonome est indépendante de la référence OCAD."
    )

    out_dir = out_dir or FIGURES_DIR

    # 1. Charge le raster de strates (LiDAR uniquement)
    with rasterio.open(strates_path) as src:
        strates = src.read().astype(np.float32)   # (4, H, W)
        transform = src.transform
        h, w = src.height, src.width

    # 2. Calcule les descripteurs (aucune information OCAD)
    X_grid, support_grid = build_descriptors(strates)

    # 3. Charge le modèle
    if model_id is None:
        import json
        best_meta = json.loads((MODELS_DIR / "best.json").read_text())
        model_id = best_meta["best_cfg_id"]

    model_path = MODELS_DIR / f"clf_{model_id:02d}.pkl"
    with model_path.open("rb") as f:
        saved = pickle.load(f)
    clf = saved["clf"]
    imputer = saved["imputer"]

    # 4. Prédiction
    X_flat = imputer.transform(X_grid.reshape(-1, N_FEATURES))
    pred_flat = clf.predict(X_flat).astype(np.uint8)
    pred_flat[~support_grid.reshape(-1)] = LABEL_NODATA  # support nul → inconnu

    pred_grid = pred_flat.reshape(h, w)

    # 5. Export raster GeoTIFF
    out_tif = out_dir / "supervised_v1_pred.tif"
    with rasterio.open(
        out_tif, "w",
        driver="GTiff", height=h, width=w, count=1,
        dtype=np.uint8, crs=CRS, transform=transform,
        nodata=LABEL_NODATA,
    ) as dst:
        dst.write(pred_grid[np.newaxis, :, :])

    # 6. Export PNG + PGW
    rgb = _pred_to_rgb(pred_grid)
    out_png = out_dir / "supervised_v1_pred.png"
    Image.fromarray(rgb).save(str(out_png))

    # PGW (worldfile) : centre du pixel (0,0)
    xmin, ymin, xmax, ymax = BBOX
    res = RES_M
    out_pgw = out_png.with_suffix(".pgw")
    out_pgw.write_text(
        f"{res}\n0\n0\n-{res}\n{xmin + res/2}\n{ymax - res/2}\n"
    )

    # 7. Export masque support
    out_support = out_dir / "supervised_v1_support.tif"
    with rasterio.open(
        out_support, "w",
        driver="GTiff", height=h, width=w, count=1,
        dtype=np.uint8, crs=CRS, transform=transform,
    ) as dst:
        dst.write(support_grid.astype(np.uint8)[np.newaxis, :, :])

    print(f"Prédiction : {out_tif.name}")
    print(f"PNG        : {out_png.name}")
    print(f"Support    : {out_support.name}")
    n_pred = int(support_grid.sum())
    n_nodata = int((pred_grid == LABEL_NODATA).sum())
    print(f"Support    : {n_pred:,} / {h*w:,} px  |  NODATA prédit : {n_nodata:,} px")
    return pred_grid


def _pred_to_rgb(pred: np.ndarray) -> np.ndarray:
    """uint8 pred → RGB (H, W, 3)."""
    from config import CLASS_NAMES, CLASS_CODES
    rgb = np.full((*pred.shape, 3), 200, dtype=np.uint8)
    for name in CLASS_NAMES:
        code = CLASS_CODES[name]
        rgb[pred == code] = CLASS_DISPLAY[name]
    rgb[pred == LABEL_NODATA] = NODATA_COLOR
    return rgb


if __name__ == "__main__":
    pred = infer(STRATES_PATH)
    # Vérification d'indépendance : OCAD_PATH jamais importé ni utilisé
    print("Inférence complète sans OCAD.")
