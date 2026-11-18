"""Planches comparatives T vs E — 4 panneaux : OCAD / T / E / Diff T↔E.

Protocole identique à make_planches.py pour T seul.
La branche E (63 features) est comparée à T (30 features).

Diff T↔E :
  bleu-vert   : T faux, E correct   (gain E)
  rouge-vif   : T correct, E faux   (perte E)
  orange       : T et E faux (même erreur)
  jaune        : T et E faux (erreurs différentes)
  couleur classe : T et E corrects
  violet       : prédiction sur réf. inconnue (hors éval.)

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/make_planches_te.py
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

_spec = importlib.util.spec_from_file_location("loto_pipeline", str(_THIS / "loto_pipeline.py"))
_loto = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "experiments/bois_dupont/supervised_v1"))
sys.path.insert(0, str(_THIS))
_spec.loader.exec_module(_loto)  # type: ignore[union-attr]

load_bd          = _loto.load_bd
load_caen        = _loto.load_caen
load_montmirel   = _loto.load_montmirel
load_sainte_anne = _loto.load_sainte_anne
N_FEATURES_T  = _loto.N_FEATURES
NODATA_CODE   = _loto.NODATA_CODE
VEG_CLASSES   = _loto.VEG_CLASSES
RESULTS_DIR   = _loto.RESULTS_DIR

from loto_pipeline_e import (   # noqa: E402
    augment_terrain,
    N_FEATURES_E,
    CFG_E,
    RESULTS_E_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PLANCHES_TE_DIR = _THIS / "planches_te"
PLANCHES_TE_DIR.mkdir(exist_ok=True)

# ── Palette ───────────────────────────────────────────────────────────────
CLASS_COLORS = np.array([
    [255, 201,  15],
    [255, 255, 255],
    [204, 255, 179],
    [153, 255, 102],
    [ 51, 255,   0],
], dtype=np.uint8)

NODATA_COLOR  = np.array([ 60,  60,  60], dtype=np.uint8)
PARTIAL_COLOR = np.array([ 90,  90,  90], dtype=np.uint8)
EXCL_COLOR    = np.array([ 42,  42,  42], dtype=np.uint8)
UNK_COLOR     = np.array([160, 120,  80], dtype=np.uint8)
OVERLAP_COLOR = np.array([ 38,  38,  38], dtype=np.uint8)

DIFF_TE_E_WIN   = np.array([  0, 220, 160], dtype=np.uint8)  # bleu-vert  T faux, E correct
DIFF_TE_T_WIN   = np.array([230,  55,  55], dtype=np.uint8)  # rouge-vif  T correct, E faux
DIFF_TE_SAME_KO = np.array([255, 155,  20], dtype=np.uint8)  # orange     les deux faux, même err.
DIFF_TE_DIFF_KO = np.array([230, 220,  30], dtype=np.uint8)  # jaune      les deux faux, err. diff.
DIFF_TE_FP_UNK  = np.array([180,  55, 220], dtype=np.uint8)  # violet     prédiction hors réf.
DIFF_ABS        = np.array([140, 140, 140], dtype=np.uint8)  # gris       abstention


# ── Rendu RGB ─────────────────────────────────────────────────────────────

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


def diff_te_to_rgb(pred_t: np.ndarray, pred_e: np.ndarray,
                   td: dict, fold_test: str) -> np.ndarray:
    """Diff T vs E par rapport à la référence."""
    support = td["support"]
    ref_cat = td["ref_cat"]
    partial = td["partial_ctx"]
    h, w    = td["h"], td["w"]

    img = np.full((h, w, 3), EXCL_COLOR, dtype=np.uint8)
    img[~support]           = NODATA_COLOR
    img[partial & support]  = PARTIAL_COLOR

    ovlp_mask = np.zeros((h, w), bool)
    if fold_test == "sainte_anne" and td.get("caen_overlap"):
        r0, r1, c0, c1 = td["caen_overlap"]
        ovlp_mask[r0:r1, c0:c1] = True
        img[ovlp_mask] = OVERLAP_COLOR

    evaluable = support & ~partial & (ref_cat >= 0) & ~ovlp_mask

    t_ok = evaluable & (pred_t.astype(np.int16) == ref_cat.astype(np.int16)) & (pred_t != NODATA_CODE)
    e_ok = evaluable & (pred_e.astype(np.int16) == ref_cat.astype(np.int16)) & (pred_e != NODATA_CODE)
    t_ko = evaluable & ~t_ok & (pred_t != NODATA_CODE)
    e_ko = evaluable & ~e_ok & (pred_e != NODATA_CODE)

    # Les deux corrects → couleur de classe
    for ci, color in enumerate(CLASS_COLORS):
        img[t_ok & e_ok & (ref_cat == ci)] = color

    # Abstentions
    img[evaluable & (pred_t == NODATA_CODE)] = DIFF_ABS

    # T correct, E faux → perte E (rouge)
    img[t_ok & e_ko] = DIFF_TE_T_WIN

    # T faux, E correct → gain E (bleu-vert)
    img[t_ko & e_ok] = DIFF_TE_E_WIN

    # Les deux faux : même erreur ou erreur différente
    both_ko = t_ko & e_ko
    img[both_ko & (pred_t.astype(np.int16) == pred_e.astype(np.int16))] = DIFF_TE_SAME_KO
    img[both_ko & (pred_t.astype(np.int16) != pred_e.astype(np.int16))] = DIFF_TE_DIFF_KO

    # Prédiction sur référence inconnue
    unk = support & ~partial & (ref_cat == -2) & ~ovlp_mask
    img[unk & np.isin(pred_e, VEG_CLASSES)] = DIFF_TE_FP_UNK

    return img


# ── Zoom ──────────────────────────────────────────────────────────────────

def find_zoom(ref_cat: np.ndarray, pred_t: np.ndarray, pred_e: np.ndarray,
              support: np.ndarray, partial: np.ndarray,
              h_win: int, w_win: int) -> tuple[int, int, int, int]:
    """Fenêtre maximisant diversité veg + désaccords T/E."""
    has_406   = (ref_cat == 2).astype(float)
    has_408   = (ref_cat == 3).astype(float)
    has_veg   = np.isin(ref_cat, [2, 3, 4]).astype(float)
    t_e_diff  = (pred_t.astype(np.int16) != pred_e.astype(np.int16)).astype(float)
    err_t     = ((pred_t.astype(np.int16) != ref_cat.astype(np.int16)) &
                 support & ~partial & (ref_cat >= 0)).astype(float)

    score = (has_406 * 2 + has_408 * 2 + has_veg + t_e_diff * 4 + err_t * 2) * support
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
        (CLASS_COLORS[0],   "découvert"),
        (CLASS_COLORS[1],   "blanc"),
        (CLASS_COLORS[2],   "veg_406"),
        (CLASS_COLORS[3],   "veg_408"),
        (CLASS_COLORS[4],   "veg_410"),
        (DIFF_TE_E_WIN,     "Gain E (T faux → E correct)"),
        (DIFF_TE_T_WIN,     "Perte E (T correct → E faux)"),
        (DIFF_TE_SAME_KO,   "Deux faux, même erreur"),
        (DIFF_TE_DIFF_KO,   "Deux faux, erreurs différentes"),
        (DIFF_TE_FP_UNK,    "Végétation prédite, zone de réf. inconnue"),
        (PARTIAL_COLOR,     "Zone bord 12 m (hors éval.)"),
        (NODATA_COLOR,      "NODATA"),
    ]
    return [
        mpatches.Patch(
            facecolor=tuple(c / 255 for c in color),
            edgecolor='#555555', linewidth=0.4, label=label,
        )
        for color, label in items
    ]


# ── Figure ────────────────────────────────────────────────────────────────

def plot_planche_te(name: str, td: dict,
                    pred_t: np.ndarray, pred_e: np.ndarray,
                    fold_test: str,
                    metrics_t: dict, metrics_e: dict) -> pathlib.Path:
    support = td["support"]
    ref_cat = td["ref_cat"]
    partial = td["partial_ctx"]

    h_win = max(150, td["h"] // 5)
    w_win = max(150, td["w"] // 5)

    ocad_rgb   = ref_to_rgb(ref_cat)
    pred_t_rgb = pred_to_rgb(pred_t, support)
    pred_e_rgb = pred_to_rgb(pred_e, support)
    diff_rgb   = diff_te_to_rgb(pred_t, pred_e, td, fold_test)

    r0, r1, c0, c1 = find_zoom(ref_cat, pred_t, pred_e, support, partial, h_win, w_win)
    log.info("%s : zoom → rows %d:%d  cols %d:%d", name, r0, r1, c0, c1)

    ov_ocad, scale = _downsample(ocad_rgb)
    ov_t, _        = _downsample(pred_t_rgb)
    ov_e, _        = _downsample(pred_e_rgb)
    ov_diff, _     = _downsample(diff_rgb)

    zm_ocad = ocad_rgb[r0:r1, c0:c1]
    zm_t    = pred_t_rgb[r0:r1, c0:c1]
    zm_e    = pred_e_rgb[r0:r1, c0:c1]
    zm_diff = diff_rgb[r0:r1, c0:c1]

    bg = '#181818'
    fig = plt.figure(figsize=(28, 14), facecolor=bg)
    gs = GridSpec(3, 4, figure=fig,
                  top=0.90, bottom=0.03, left=0.01, right=0.99,
                  hspace=0.07, wspace=0.03,
                  height_ratios=[1, 1, 0.16])

    miv_t = metrics_t.get("macro_veg", float("nan"))
    miv_e = metrics_e.get("macro_veg", float("nan"))
    iop_t = metrics_t.get("iou_veg",   float("nan"))
    iop_e = metrics_e.get("iou_veg",   float("nan"))

    titles_ov = [
        "Référence OCAD",
        f"Prédiction T  mIoU-veg={miv_t:.3f}",
        f"Prédiction E  mIoU-veg={miv_e:.3f}",
        f"Diff T↔E  IoU-prés T={iop_t:.3f} / E={iop_e:.3f}",
    ]
    titles_zm = [
        f"Zoom OCAD  [{r0}:{r1},{c0}:{c1}]",
        "Zoom T",
        "Zoom E",
        "Zoom Diff T↔E",
    ]

    for col, (img, title) in enumerate(zip([ov_ocad, ov_t, ov_e, ov_diff], titles_ov)):
        ax = fig.add_subplot(gs[0, col])
        ax.set_facecolor(bg)
        ax.imshow(img, interpolation='nearest', aspect='equal')
        rect = mpatches.Rectangle(
            (c0 * scale, r0 * scale),
            (c1 - c0) * scale, (r1 - r0) * scale,
            linewidth=1.5, edgecolor='white', facecolor='none',
        )
        ax.add_patch(rect)
        ax.set_title(title, color='white', fontsize=10, pad=5)
        ax.axis('off')

    for col, (img, title) in enumerate(zip([zm_ocad, zm_t, zm_e, zm_diff], titles_zm)):
        ax = fig.add_subplot(gs[1, col])
        ax.set_facecolor(bg)
        ax.imshow(img, interpolation='nearest', aspect='equal')
        ax.set_title(title, color='#cccccc', fontsize=9, pad=4)
        ax.axis('off')

    ax_leg = fig.add_subplot(gs[2, :])
    ax_leg.set_facecolor(bg)
    ax_leg.axis('off')
    ax_leg.legend(
        handles=_legend_handles(), loc='center', ncol=6,
        fontsize=8.5, framealpha=0.25, labelcolor='white', edgecolor='#555',
    )

    delta_v = miv_e - miv_t
    sign_v  = "+" if delta_v >= 0 else ""
    fig.suptitle(
        f"LOTO T vs E — Terrain : {name}  |  Config pré-spécifiée : RF_leaf5"
        f"  [aucune sélection sur validation interne]\n"
        f"Δ mIoU-veg = {sign_v}{delta_v:.3f}"
        f"   T: mIoU-veg={miv_t:.3f}  IoU-prés={iop_t:.3f}"
        f"   E: mIoU-veg={miv_e:.3f}  IoU-prés={iop_e:.3f}",
        color='white', fontsize=11, y=0.96, va='top',
    )

    out = PLANCHES_TE_DIR / f"planche_te_{name}.png"
    fig.savefig(str(out), dpi=150, bbox_inches='tight', facecolor=bg)
    plt.close(fig)
    log.info("%s : sauvegardé → %s", name, out.name)
    return out


# ── Inférence ─────────────────────────────────────────────────────────────

def infer_t(td: dict, clf, imputer) -> np.ndarray:
    support = td["support"]
    h, w    = td["h"], td["w"]
    X_all   = td["X_grid"].reshape(-1, N_FEATURES_T)
    X_imp   = imputer.transform(X_all)
    pred_flat = clf.predict(X_imp).astype(np.uint8)
    pred_flat[~support.reshape(-1)] = NODATA_CODE
    return pred_flat.reshape(h, w)


def infer_e(td_e: dict, clf, imputer) -> np.ndarray:
    support = td_e["support"]
    h, w    = td_e["h"], td_e["w"]
    X_all   = td_e["X_grid"].reshape(-1, N_FEATURES_E)
    X_imp   = imputer.transform(X_all)
    pred_flat = clf.predict(X_imp).astype(np.uint8)
    pred_flat[~support.reshape(-1)] = NODATA_CODE
    return pred_flat.reshape(h, w)


# ── Main ──────────────────────────────────────────────────────────────────

_LOADERS = {
    "bd":          load_bd,
    "caen":        load_caen,
    "montmirel":   load_montmirel,
    "sainte_anne": load_sainte_anne,
}


def main() -> None:
    import gc

    for name in ["bd", "caen", "montmirel", "sainte_anne"]:
        out = PLANCHES_TE_DIR / f"planche_te_{name}.png"
        if out.exists():
            log.info("%s : planche déjà présente, ignoré", name)
            continue

        log.info("=== %s : chargement + augmentation ===", name)
        td_t = _LOADERS[name]()
        td_e = augment_terrain(name, td_t)

        pkl_t = RESULTS_DIR / "models" / f"{name}_RF_leaf5.pkl"
        with pkl_t.open("rb") as f:
            saved_t = pickle.load(f)
        metrics_t = saved_t["metrics"]

        pkl_e = RESULTS_E_DIR / "models" / f"{name}_{CFG_E['id']}.pkl"
        with pkl_e.open("rb") as f:
            saved_e = pickle.load(f)
        metrics_e = saved_e["metrics"]

        log.info("%s : inférence T...", name)
        pred_t = infer_t(td_t, saved_t["clf"], saved_t["imputer"])

        log.info("%s : inférence E...", name)
        pred_e = infer_e(td_e, saved_e["clf"], saved_e["imputer"])

        log.info("%s : génération planche TE...", name)
        plot_planche_te(name, td_t, pred_t, pred_e, name, metrics_t, metrics_e)

        del td_t, td_e, saved_t, saved_e, pred_t, pred_e
        gc.collect()

    log.info("Planches T vs E enregistrées dans : %s", PLANCHES_TE_DIR)


if __name__ == "__main__":
    main()
