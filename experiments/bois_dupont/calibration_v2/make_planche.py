"""Génère la planche comparative : OCAD / témoin_040 / meilleur_v2 / différences.
Lecture seule — aucun nouveau calcul, aucun paramètre modifié.
"""
from __future__ import annotations
import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
import rasterio
from rasterio.transform import from_bounds

_THIS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

# Réutilise les constantes et fonctions de run_calibration_v2
from run_calibration_v2 import (
    STRATES_PATH, OCAD_PATH, ZONES, OCAD_COLORS, RESULT_PALETTE,
    RES_M, OBJ_W, WITNESSES, NODATA_CLS,
    load_strates, load_ocad_rgb, build_ocad_masks,
    zone_slice, apply_gaussian, compute_ndvd, classify_ndvd,
    compute_zone_metrics,
)

OUT_DIR = _THIS / "figures"
OUT_DIR.mkdir(exist_ok=True)

BEST_CFG = json.loads((_THIS / "best_config.json").read_text())["params"]
WITNESS_040 = WITNESSES[0]  # t406=0.40, poids référence

# ─── Palette différences ─────────────────────────────────────────────────────
# 0 = accord, 1 = faux positif veg, 2 = faux négatif veg, 3 = erreur de classe
DIFF_COLORS = {
    "accord":          (200, 200, 200),
    "FP veg":          (220,  60,  60),
    "FN veg":          ( 60,  60, 220),
    "erreur classe":   (255, 160,   0),
    "ref inconnue":    (240, 240, 240),
}


def _to_rgb(cls: np.ndarray) -> np.ndarray:
    rgb = np.full((*cls.shape, 3), 255, dtype=np.uint8)
    for code, (r, g, b) in RESULT_PALETTE.items():
        mask = cls == code
        rgb[mask] = (r, g, b)
    # NODATA_CLS (support insuffisant) : violet distinctif
    rgb[cls == NODATA_CLS] = (180, 0, 220)
    return rgb


def _diff_map(pred: np.ndarray, ocad_masks: dict,
              r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
    pz = pred[r0:r1, c0:c1]
    m = {k: v[r0:r1, c0:c1] for k, v in ocad_masks.items()}

    out = np.full((*pz.shape, 3), DIFF_COLORS["ref inconnue"], dtype=np.uint8)
    known = ~m["unknown"]
    ref_veg = m["veg_406"] | m["veg_408"] | m["veg_410"]
    pred_veg = pz >= 406

    # Accord (veg→veg ou nonveg→nonveg)
    accord = known & (pred_veg == ref_veg)
    # Affiner : erreur de classe (veg→veg mais mauvaise sous-classe)
    for code, cat in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        correct_class = m[cat] & (pz == code) & known
        accord_veg    = m[cat] & pred_veg & known & ~correct_class
        # accord général reste accord si sous-classe différente → reclassifier
        accord &= ~accord_veg

    out[known & ~pred_veg & ~ref_veg] = DIFF_COLORS["accord"]   # nonveg correct
    out[known &  pred_veg &  ref_veg] = DIFF_COLORS["accord"]   # veg correct
    out[known &  pred_veg & ~ref_veg] = DIFF_COLORS["FP veg"]
    out[known & ~pred_veg &  ref_veg] = DIFF_COLORS["FN veg"]
    # Erreur de sous-classe : prédit veg correct mais mauvaise catégorie
    for code, cat in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        wrong_class = known & (pz == code) & ref_veg & ~m[cat]
        out[wrong_class] = DIFF_COLORS["erreur classe"]
    return out


def _make_pred(cfg: dict, smooth: np.ndarray) -> np.ndarray:
    ndvd = compute_ndvd(smooth, cfg["w_low"], cfg["w_med"], cfg["w_high"])
    return classify_ndvd(ndvd, cfg["t406"], cfg["t408"], cfg["t410"])


def _iou(tp, fp, fn):
    d = tp + fp + fn
    return tp / d if d > 0 else 0.0


def _zone_summary(pred, ocad_masks, r0, r1, c0, c1) -> str:
    pz = pred[r0:r1, c0:c1]
    m = {k: v[r0:r1, c0:c1] for k, v in ocad_masks.items()}
    known = ~m["unknown"]
    ref_veg  = m["veg_406"] | m["veg_408"] | m["veg_410"]
    pred_veg = pz >= 406
    tp = int((pred_veg &  ref_veg & known).sum())
    fp = int((pred_veg & ~ref_veg & known).sum())
    fn = int((~pred_veg & ref_veg & known).sum())
    iou_p = _iou(tp, fp, fn)
    ious = []
    for code, cat in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        tp2 = int(((pz == code) &  m[cat] & known).sum())
        fp2 = int(((pz == code) & ~m[cat] & known).sum())
        fn2 = int(((pz != code) &  m[cat] & known).sum())
        ious.append(_iou(tp2, fp2, fn2))
    score = OBJ_W["miou3"] * np.mean(ious) + OBJ_W["iou_pres"] * iou_p
    return f"IoU_pres={iou_p:.3f}  mIoU3={np.mean(ious):.3f}\nscore(partiel)={score:.3f}"


def build_planche():
    strates = load_strates()
    ocad_rgb = load_ocad_rgb()
    ocad_masks = build_ocad_masks(ocad_rgb, strates.h, strates.w)

    smooth_040 = apply_gaussian(strates.arr, WITNESS_040["sigma_m"])
    smooth_v2  = apply_gaussian(strates.arr, BEST_CFG["sigma_m"])

    pred_040 = _make_pred(WITNESS_040, smooth_040)
    pred_v2  = _make_pred(BEST_CFG,   smooth_v2)

    zones_ordered = [
        ("cal",  "Cal-NE   (calibration)"),
        ("val",  "Val-SE   (validation)"),
        ("ctrl", "Ctrl-NW  (contrôle)"),
    ]

    # 3 zones × 5 colonnes : OCAD / témoin / best_v2 / diff_040 / diff_v2
    fig, axes = plt.subplots(3, 5, figsize=(20, 13))
    fig.patch.set_facecolor("#1a1a1a")

    col_titles = [
        "OCAD référence",
        "Témoin t406=0.40\nw=(0.50,0.35,0.15)",
        "Meilleur v2\nt406=0.38 σ=1.0\nw=(0.35,0.55,0.10)",
        "Différences\ntémoin vs OCAD",
        "Différences\nv2 vs OCAD",
    ]
    for col, ct in enumerate(col_titles):
        axes[0, col].set_title(ct, color="white", fontsize=8, fontweight="bold", pad=4)

    for row, (zk, zlabel) in enumerate(zones_ordered):
        sl = zone_slice(ZONES[zk], strates.transform, strates.h, strates.w)
        r0, r1, c0, c1 = sl

        ocad_crop  = ocad_rgb[r0:r1, c0:c1]
        rgb_040    = _to_rgb(pred_040[r0:r1, c0:c1])
        rgb_v2     = _to_rgb(pred_v2[r0:r1, c0:c1])
        diff_040   = _diff_map(pred_040, ocad_masks, r0, r1, c0, c1)
        diff_v2    = _diff_map(pred_v2,  ocad_masks, r0, r1, c0, c1)

        sum_040 = _zone_summary(pred_040, ocad_masks, r0, r1, c0, c1)
        sum_v2  = _zone_summary(pred_v2,  ocad_masks, r0, r1, c0, c1)

        for col, (img, subtitle) in enumerate([
            (ocad_crop, zlabel),
            (rgb_040,   sum_040),
            (rgb_v2,    sum_v2),
            (diff_040,  ""),
            (diff_v2,   ""),
        ]):
            ax = axes[row, col]
            ax.imshow(img)
            ax.set_ylabel(zlabel if col == 0 else "", color="white",
                          fontsize=7, rotation=90, labelpad=2)
            if subtitle and col != 0:
                ax.set_xlabel(subtitle, color="#bbbbbb", fontsize=6, labelpad=2)
            ax.set_xticks([]); ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_edgecolor("#555555")
            ax.set_facecolor("#1a1a1a")

    # Légende palette OCAD
    legend_patches = []
    for (r, g, b), name in OCAD_COLORS.items():
        legend_patches.append(
            mpatches.Patch(facecolor=(r/255, g/255, b/255), label=name)
        )
    for label, (r, g, b) in DIFF_COLORS.items():
        legend_patches.append(
            mpatches.Patch(facecolor=(r/255, g/255, b/255),
                           edgecolor="white", linewidth=0.5, label=f"[diff] {label}")
        )
    fig.legend(handles=legend_patches, loc="lower center",
               ncol=5, fontsize=6.5, framealpha=0.3,
               labelcolor="white", facecolor="#2a2a2a",
               bbox_to_anchor=(0.5, -0.01))

    fig.suptitle(
        "Campagne calibration v2 — Bois Dupont\n"
        "Palette OCAD : (255,201,15)=découvert  (255,255,255)=blanc  "
        "(204,255,179)=veg_406  (153,255,102)=veg_408  (51,255,0)=veg_410  (25,25,25)=bâti",
        color="white", fontsize=8, y=1.01,
    )

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    out = OUT_DIR / "planche_calib_v2.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Planche : {out}")
    return out


if __name__ == "__main__":
    build_planche()
