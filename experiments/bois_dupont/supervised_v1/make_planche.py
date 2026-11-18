"""Planche comparative : OCAD / NDVD best_v2 / modèle supervisé / différences.

3 zones × 4 colonnes :
  OCAD référence · NDVD best_v2 · RF supervisé · Différences supervisé vs OCAD
"""
from __future__ import annotations

import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

_THIS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

from config import (
    OCAD_PATH, LABEL_NODATA, CLASS_NAMES, CLASS_CODES, N_CLASSES,
    CLASS_DISPLAY, NODATA_COLOR, FIGURES_DIR, MODELS_DIR,
    GRID_H, GRID_W, SPLIT_CFG,
)
from infer import _pred_to_rgb

# Zones d'affichage (reprend la géométrie du découpage spatial)
DISPLAY_ZONES = [
    ("train", "Train  (lignes 0–184)"),
    ("val",   "Val    (lignes 200–334)"),
    ("test",  "Test   (lignes 350–499)"),
]

DIFF_COLORS: dict[str, tuple[int, int, int]] = {
    "accord_nonveg": (200, 200, 200),
    "accord_veg":    (200, 200, 200),
    "FP_veg":        (220,  60,  60),
    "FN_veg":        ( 60,  60, 220),
    "FN_nodata":     ( 50,  50, 180),
    "err_classe":    (255, 160,   0),
    "ref_inconnu":   (230, 230, 230),
}


def _crop(arr: np.ndarray, zone_key: str) -> np.ndarray:
    blk = SPLIT_CFG[zone_key]
    return arr[blk["r0"]:blk["r1"], blk["c0"]:blk["c1"]]


def _diff_map(pred: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Carte de différences pred vs labels (H, W, 3) RGB."""
    veg_codes = {CLASS_CODES[n] for n in ("veg_406", "veg_408", "veg_410")}
    out = np.full((*pred.shape, 3), DIFF_COLORS["ref_inconnu"], dtype=np.uint8)

    known    = labels != LABEL_NODATA
    ref_veg  = np.isin(labels, list(veg_codes))
    pred_veg = np.isin(pred,   list(veg_codes))
    pred_nd  = pred == LABEL_NODATA

    out[known & ~pred_nd & ~pred_veg & ~ref_veg] = DIFF_COLORS["accord_nonveg"]
    out[known & ~pred_nd &  pred_veg &  ref_veg] = DIFF_COLORS["accord_veg"]
    out[known & ~pred_nd &  pred_veg & ~ref_veg] = DIFF_COLORS["FP_veg"]
    out[known & ~pred_nd & ~pred_veg &  ref_veg] = DIFF_COLORS["FN_veg"]
    out[known &  pred_nd &  ref_veg]             = DIFF_COLORS["FN_nodata"]
    # Erreurs de sous-classe (veg correct mais mauvaise catégorie)
    for name in ("veg_406", "veg_408", "veg_410"):
        code = CLASS_CODES[name]
        wrong = known & (pred == code) & ref_veg & (labels != code)
        out[wrong] = DIFF_COLORS["err_classe"]
    return out


def _ocad_to_rgb(ocad_arr: np.ndarray) -> np.ndarray:
    return ocad_arr[:, :, :3]  # déjà RGB depuis PIL


def _zone_summary(pred: np.ndarray, labels: np.ndarray) -> str:
    from metrics import evaluate
    res = evaluate(pred, labels, "")
    return (
        f"macro-IoU={res.macro_iou:.3f}\n"
        f"IoU_pres={res.iou_presence:.3f}"
    )


def build_planche() -> pathlib.Path:
    # Chargement
    ocad_arr = np.array(Image.open(OCAD_PATH).convert("RGB"), dtype=np.uint8)
    pred_rf   = np.load(str(MODELS_DIR / "pred_best.npy"))
    pred_ndvd = np.load(str(MODELS_DIR / "pred_ndvd.npy"))
    best_meta = json.loads((MODELS_DIR / "best.json").read_text())
    best_cfg  = best_meta["best_cfg"]

    # Labels pour les différences
    from labels import load_labels
    labels = load_labels()
    from descriptors import load_descriptors
    _, support_grid, _ = load_descriptors()
    labels_masked = labels.copy()
    labels_masked[~support_grid] = LABEL_NODATA

    fig, axes = plt.subplots(3, 4, figsize=(20, 15))
    fig.patch.set_facecolor("#1a1a1a")

    col_titles = [
        "OCAD référence",
        "NDVD best_v2",
        f"RF supervisé cfg{best_cfg['id']:02d}\n"
        f"{best_cfg['type']} n={best_cfg['n']} depth={best_cfg['depth']}",
        "Différences RF vs OCAD",
    ]
    for ci, title in enumerate(col_titles):
        axes[0, ci].set_title(title, color="white", fontsize=8, fontweight="bold", pad=4)

    for ri, (zone_key, zlabel) in enumerate(DISPLAY_ZONES):
        ocad_crop = _crop(ocad_arr, zone_key)
        rgb_ndvd  = _pred_to_rgb(_crop(pred_ndvd, zone_key))
        rgb_rf    = _pred_to_rgb(_crop(pred_rf, zone_key))
        diff_rf   = _diff_map(_crop(pred_rf, zone_key), _crop(labels_masked, zone_key))

        sum_ndvd = _zone_summary(_crop(pred_ndvd, zone_key), _crop(labels_masked, zone_key))
        sum_rf   = _zone_summary(_crop(pred_rf, zone_key),   _crop(labels_masked, zone_key))

        for ci, (img, subtitle) in enumerate([
            (ocad_crop, zlabel),
            (rgb_ndvd,  sum_ndvd),
            (rgb_rf,    sum_rf),
            (diff_rf,   ""),
        ]):
            ax = axes[ri, ci]
            ax.imshow(img)
            if ci == 0:
                ax.set_ylabel(zlabel, color="white", fontsize=7, rotation=90, labelpad=2)
            if subtitle and ci != 0:
                ax.set_xlabel(subtitle, color="#bbbbbb", fontsize=6, labelpad=2)
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values():
                sp.set_edgecolor("#555")
            ax.set_facecolor("#1a1a1a")

    # Légende
    patches = []
    for name in CLASS_NAMES:
        r, g, b = CLASS_DISPLAY[name]
        patches.append(mpatches.Patch(facecolor=(r/255, g/255, b/255), label=name))
    patches.append(mpatches.Patch(facecolor=tuple(c/255 for c in NODATA_COLOR), label="NODATA"))
    for key, (r, g, b) in DIFF_COLORS.items():
        if key not in ("accord_nonveg", "ref_inconnu"):
            patches.append(mpatches.Patch(
                facecolor=(r/255, g/255, b/255), edgecolor="white",
                linewidth=0.3, label=f"[diff] {key}",
            ))

    fig.legend(handles=patches, loc="lower center", ncol=6, fontsize=6.5,
               labelcolor="white", facecolor="#2a2a2a", framealpha=0.3,
               bbox_to_anchor=(0.5, -0.01))

    # Scores globaux depuis best.json
    rf_val  = best_meta["val"]["macro_iou"]
    nd_val  = best_meta["ndvd_val"]["macro_iou"]
    rf_test = best_meta["test"]["macro_iou"]
    nd_test = best_meta["ndvd_test"]["macro_iou"]
    fig.suptitle(
        f"Supervisé v1 vs NDVD best_v2 — Bois Dupont\n"
        f"RF cfg{best_cfg['id']:02d}  val macro-IoU={rf_val:.4f}  test macro-IoU={rf_test:.4f}  "
        f"|  NDVD val={nd_val:.4f}  test={nd_test:.4f}",
        color="white", fontsize=8, y=1.01,
    )

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    out = FIGURES_DIR / "planche_supervised_v1.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Planche : {out}")
    return out


if __name__ == "__main__":
    build_planche()
