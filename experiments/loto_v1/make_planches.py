"""Planches LOTO — Référence OCAD / Prédiction RF_leaf5 / Différences.

NOTA MÉTHODOLOGIQUE
-------------------
Aucune sélection interne n'a été réalisée avant le test.
La config RF_leaf5 est pré-spécifiée (équivalent de clf_A4) et n'est
PAS choisie a posteriori sur les scores de test externes.
Les 3 configs (RF_leaf5 / RF_leaf10 / ET_leaf5) ont été exécutées en
analyse de sensibilité post-hoc — elles ne constituent pas une
sélection indépendante.

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/make_planches.py
"""
from __future__ import annotations

import importlib.util
import logging
import pathlib
import pickle
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import numpy as np
from scipy.ndimage import uniform_filter

_THIS = pathlib.Path(__file__).resolve().parent
_ROOT = _THIS.parents[1]

# Charge loto_pipeline sans __init__.py
_spec = importlib.util.spec_from_file_location("loto_pipeline", str(_THIS / "loto_pipeline.py"))
_loto = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "experiments/bois_dupont/supervised_v1"))
_spec.loader.exec_module(_loto)  # type: ignore[union-attr]

load_bd          = _loto.load_bd
load_caen        = _loto.load_caen
load_montmirel   = _loto.load_montmirel
load_sainte_anne = _loto.load_sainte_anne
N_FEATURES  = _loto.N_FEATURES
NODATA_CODE = _loto.NODATA_CODE
VEG_CLASSES = _loto.VEG_CLASSES
RESULTS_DIR = _loto.RESULTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PLANCHES_DIR = _THIS / "planches"
PLANCHES_DIR.mkdir(exist_ok=True)

# ── Palette de couleurs ────────────────────────────────────────────────────
CLASS_COLORS = np.array([
    [255, 201,  15],   # 0 découvert  — jaune
    [255, 255, 255],   # 1 blanc      — blanc
    [204, 255, 179],   # 2 veg_406    — vert pâle
    [153, 255, 102],   # 3 veg_408    — vert moyen
    [ 51, 255,   0],   # 4 veg_410    — vert fort
], dtype=np.uint8)

NODATA_COLOR  = np.array([ 60,  60,  60], dtype=np.uint8)
PARTIAL_COLOR = np.array([ 90,  90,  90], dtype=np.uint8)
EXCL_COLOR    = np.array([ 42,  42,  42], dtype=np.uint8)
UNK_COLOR     = np.array([160, 120,  80], dtype=np.uint8)   # orange-brun
OVERLAP_COLOR = np.array([ 38,  38,  38], dtype=np.uint8)   # hors éval SA↔Caen

DIFF_FP_VEG    = np.array([230,  55,  55], dtype=np.uint8)  # rouge      FP veg
DIFF_FN_VEG    = np.array([ 55, 100, 230], dtype=np.uint8)  # bleu       FN veg
DIFF_WRONG_VEG = np.array([255, 155,  20], dtype=np.uint8)  # orange     mauvais niveau
DIFF_WRONG_NV  = np.array([180, 155,  60], dtype=np.uint8)  # brun-jaune autre erreur
DIFF_FP_UNK    = np.array([180,  55, 220], dtype=np.uint8)  # violet     FP inconnu
DIFF_ABS       = np.array([140, 140, 140], dtype=np.uint8)  # gris moyen abstention


# ── Conversion RGB ─────────────────────────────────────────────────────────

def ref_to_rgb(ref_cat: np.ndarray) -> np.ndarray:
    img = np.full((*ref_cat.shape, 3), NODATA_COLOR, dtype=np.uint8)
    for ci, color in enumerate(CLASS_COLORS):
        img[ref_cat == ci] = color
    img[ref_cat == -1] = EXCL_COLOR
    img[ref_cat == -2] = UNK_COLOR
    return img


def pred_to_rgb(pred: np.ndarray, support: np.ndarray) -> np.ndarray:
    img = np.full((*pred.shape, 3), NODATA_COLOR, dtype=np.uint8)
    for ci, color in enumerate(CLASS_COLORS):
        img[pred == ci] = color
    img[~support] = NODATA_COLOR
    return img


def diff_to_rgb(pred: np.ndarray, td: dict, fold_test: str) -> np.ndarray:
    support = td["support"]
    ref_cat = td["ref_cat"]
    partial = td["partial_ctx"]
    h, w    = td["h"], td["w"]

    img = np.full((h, w, 3), EXCL_COLOR, dtype=np.uint8)
    img[~support]           = NODATA_COLOR
    img[partial & support]  = PARTIAL_COLOR

    # Overlap SA↔Caen : zone exclue de l'éval
    ovlp_mask = np.zeros((h, w), bool)
    if fold_test == "sainte_anne" and td.get("caen_overlap"):
        r0, r1, c0, c1 = td["caen_overlap"]
        ovlp_mask[r0:r1, c0:c1] = True
        img[ovlp_mask] = OVERLAP_COLOR

    evaluable = support & ~partial & (ref_cat >= 0) & ~ovlp_mask

    # Prédictions correctes → couleur de classe
    for ci, color in enumerate(CLASS_COLORS):
        img[evaluable & (ref_cat == ci) & (pred == ci)] = color

    # Abstention
    img[evaluable & (pred == NODATA_CODE)] = DIFF_ABS

    # Erreurs (hors abstention)
    err      = evaluable & (pred != NODATA_CODE) & (pred != ref_cat.astype(pred.dtype))
    pred_veg = np.isin(pred, VEG_CLASSES)
    ref_veg  = np.isin(ref_cat, VEG_CLASSES)

    img[err & ~ref_veg & pred_veg]  = DIFF_FP_VEG     # FP veg
    img[err & ref_veg  & ~pred_veg] = DIFF_FN_VEG     # FN veg
    img[err & ref_veg  & pred_veg]  = DIFF_WRONG_VEG  # mauvais niveau veg
    img[err & ~ref_veg & ~pred_veg] = DIFF_WRONG_NV   # autre

    # FP sur OCAD inconnu (veg prédit sur couleur non mappée)
    unk = support & ~partial & (ref_cat == -2) & ~ovlp_mask
    img[unk & pred_veg] = DIFF_FP_UNK

    return img


# ── Sélection automatique du zoom ─────────────────────────────────────────

def find_zoom(ref_cat: np.ndarray, pred: np.ndarray,
              support: np.ndarray, partial: np.ndarray,
              h_win: int, w_win: int) -> tuple[int, int, int, int]:
    """Fenêtre maximisant la diversité veg intermédiaire + erreurs."""
    has_406  = (ref_cat == 2).astype(float)
    has_408  = (ref_cat == 3).astype(float)
    has_blanc = (ref_cat == 1).astype(float)
    has_veg  = np.isin(ref_cat, [2, 3, 4]).astype(float)
    err = ((pred.astype(np.int16) != ref_cat.astype(np.int16)) &
           support & ~partial & (ref_cat >= 0)).astype(float)

    score = (has_406 * 2 + has_408 * 2 + has_blanc + has_veg + err * 3) * support
    ws = uniform_filter(score, size=[h_win, w_win], mode='constant') * h_win * w_win

    ph, pw = h_win // 2, w_win // 2
    ws[:ph, :] = 0;  ws[-ph:, :] = 0
    ws[:, :pw] = 0;  ws[:, -pw:] = 0

    r_c, c_c = np.unravel_index(ws.argmax(), ws.shape)
    r0 = max(0, r_c - ph)
    c0 = max(0, c_c - pw)
    r1 = min(ref_cat.shape[0], r0 + h_win)
    c1 = min(ref_cat.shape[1], c0 + w_win)
    return r0, r1, c0, c1


def _downsample(img: np.ndarray, max_dim: int = 650) -> tuple[np.ndarray, float]:
    from PIL import Image as PILImage
    h, w = img.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        nh, nw = int(h * scale), int(w * scale)
        pil = PILImage.fromarray(img).resize((nw, nh), PILImage.NEAREST)
        return np.array(pil), scale
    return img, 1.0


# ── Légende ───────────────────────────────────────────────────────────────

def _legend_handles() -> list:
    items = [
        (CLASS_COLORS[0], "découvert"),
        (CLASS_COLORS[1], "blanc"),
        (CLASS_COLORS[2], "veg_406 (intermédiaire)"),
        (CLASS_COLORS[3], "veg_408 (intermédiaire)"),
        (CLASS_COLORS[4], "veg_410 (vert fort)"),
        (DIFF_FP_VEG,    "FP veg (non-veg→veg)"),
        (DIFF_FN_VEG,    "FN veg (veg→non-veg)"),
        (DIFF_WRONG_VEG, "Mauvais niveau veg"),
        (DIFF_FP_UNK,    "Préd. sur réf. inconnue (hors éval.)"),
        (PARTIAL_COLOR,  "Zone bord 12 m (hors éval)"),
        (NODATA_COLOR,   "NODATA / hors emprise"),
    ]
    return [
        mpatches.Patch(
            facecolor=tuple(c / 255 for c in color),
            edgecolor='#555555', linewidth=0.4, label=label,
        )
        for color, label in items
    ]


# ── Figure principale ──────────────────────────────────────────────────────

def plot_planche(name: str, td: dict, pred: np.ndarray,
                 fold_test: str, metrics: dict) -> pathlib.Path:
    support = td["support"]
    ref_cat = td["ref_cat"]
    partial = td["partial_ctx"]

    # Taille de fenêtre de zoom : 1/5 du terrain, min 150 px
    h_win = max(150, td["h"] // 5)
    w_win = max(150, td["w"] // 5)

    ocad_rgb = ref_to_rgb(ref_cat)
    pred_rgb = pred_to_rgb(pred, support)
    diff_rgb = diff_to_rgb(pred, td, fold_test)

    r0, r1, c0, c1 = find_zoom(ref_cat, pred, support, partial, h_win, w_win)
    log.info("%s : zoom → rows %d:%d  cols %d:%d", name, r0, r1, c0, c1)

    # Vues d'ensemble (downsamplées)
    ov_ocad, scale = _downsample(ocad_rgb)
    ov_pred, _     = _downsample(pred_rgb)
    ov_diff, _     = _downsample(diff_rgb)

    # Zooms natifs
    zm_ocad = ocad_rgb[r0:r1, c0:c1]
    zm_pred = pred_rgb[r0:r1, c0:c1]
    zm_diff = diff_rgb[r0:r1, c0:c1]

    # ── Figure ────────────────────────────────────────────────────────────
    bg = '#181818'
    fig = plt.figure(figsize=(21, 14), facecolor=bg)
    gs = GridSpec(3, 3, figure=fig,
                  top=0.90, bottom=0.03, left=0.02, right=0.98,
                  hspace=0.07, wspace=0.03,
                  height_ratios=[1, 1, 0.16])

    titles_ov  = ["Référence OCAD", "Prédiction RF_leaf5", "Différences"]
    titles_zm  = [
        f"Zoom OCAD  [{r0}:{r1}, {c0}:{c1}]",
        "Zoom Prédiction",
        "Zoom Différences",
    ]

    # Surimpression du rectangle de zoom sur les vues d'ensemble
    for col, (img, title) in enumerate(zip([ov_ocad, ov_pred, ov_diff], titles_ov)):
        ax = fig.add_subplot(gs[0, col])
        ax.set_facecolor(bg)
        ax.imshow(img, interpolation='nearest', aspect='equal')
        # Rectangle de zoom (coordonnées en espace downsamplé)
        rect = mpatches.Rectangle(
            (c0 * scale, r0 * scale),
            (c1 - c0) * scale, (r1 - r0) * scale,
            linewidth=1.5, edgecolor='white', facecolor='none',
        )
        ax.add_patch(rect)
        ax.set_title(title, color='white', fontsize=11, pad=5)
        ax.axis('off')

    for col, (img, title) in enumerate(zip([zm_ocad, zm_pred, zm_diff], titles_zm)):
        ax = fig.add_subplot(gs[1, col])
        ax.set_facecolor(bg)
        ax.imshow(img, interpolation='nearest', aspect='equal')
        ax.set_title(title, color='#cccccc', fontsize=10, pad=4)
        ax.axis('off')

    # Légende
    ax_leg = fig.add_subplot(gs[2, :])
    ax_leg.set_facecolor(bg)
    ax_leg.axis('off')
    ax_leg.legend(
        handles=_legend_handles(), loc='center', ncol=6,
        fontsize=8.5, framealpha=0.25, labelcolor='white', edgecolor='#555',
    )

    # Titre + métriques
    miv = metrics.get("macro_veg", float("nan"))
    iop = metrics.get("iou_veg",   float("nan"))
    epx = metrics.get("eval_px",   0)
    fpk = metrics.get("n_fp_unknown", 0)
    fig.suptitle(
        f"LOTO — Terrain : {name}  |  Config pré-spécifiée : RF_leaf5"
        f"  [aucune sélection sur validation interne]\n"
        f"mIoU-veg = {miv:.3f}   IoU-prés = {iop:.3f}"
        f"   eval_px = {epx:,}   Préd. hors réf. = {fpk:,}",
        color='white', fontsize=12, y=0.96, va='top',
    )

    out = PLANCHES_DIR / f"planche_{name}.png"
    fig.savefig(str(out), dpi=150, bbox_inches='tight', facecolor=bg)
    plt.close(fig)
    log.info("%s : sauvegardé → %s", name, out.name)
    return out


# ── Inférence (sans ré-entraînement) ──────────────────────────────────────

def infer(td: dict, clf, imputer) -> np.ndarray:
    support = td["support"]
    h, w    = td["h"], td["w"]
    X_all   = td["X_grid"].reshape(-1, N_FEATURES)
    X_imp   = imputer.transform(X_all)
    pred_flat = clf.predict(X_imp).astype(np.uint8)
    pred_flat[~support.reshape(-1)] = NODATA_CODE
    return pred_flat.reshape(h, w)


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== Planches LOTO — chargement terrains ===")
    terrains = [
        ("bd",          load_bd()),
        ("caen",        load_caen()),
        ("montmirel",   load_montmirel()),
        ("sainte_anne", load_sainte_anne()),
    ]

    for name, td in terrains:
        pkl_path = RESULTS_DIR / "models" / f"{name}_RF_leaf5.pkl"
        log.info("%s : lecture pkl...", name)
        with pkl_path.open("rb") as f:
            saved = pickle.load(f)
        clf     = saved["clf"]
        imputer = saved["imputer"]
        metrics = saved["metrics"]

        log.info("%s : inférence %d×%d px...", name, td["h"], td["w"])
        pred = infer(td, clf, imputer)
        log.info("%s : génération planche...", name)
        plot_planche(name, td, pred, name, metrics)

        del clf, imputer, pred  # libère la mémoire avant le terrain suivant
        import gc; gc.collect()

    log.info("Planches enregistrées dans : %s", PLANCHES_DIR)


if __name__ == "__main__":
    main()
