"""Comparaison méthodes de voisinage A vs B — Bois Dupont.

MÉTHODE A (omapmaker / best_v2 existant)
-----------------------------------------
  Gaussien appliqué séparément sur chaque bande de comptage brut.
  Signal = ratio calculé à partir des comptages lissés.
  signal_A = NDVD(gaussian(g), gaussian(V))

MÉTHODE B (ratio puis voisinage normalisé)
-------------------------------------------
  Ratio calculé par cellule valide (V+g > 0) AVANT le Gaussien.
  Voisinage par convolution normalisée :
    signal_B = gaussian(ratio * validity) / gaussian(validity)
  Les cellules sans retour (validity=0) ne contribuent ni au numérateur
  ni au dénominateur — aucune sentinelle injectée dans le filtre.

RÈGLE DE SUPPORT (définie avant les essais)
--------------------------------------------
  Méthode B : une cellule est évaluable après Gaussien si
    gaussian(validity) > MIN_SUPPORT_B
  où MIN_SUPPORT_B = 1e-9 (strictement positif).
  Interprétation : au moins un voisin valide (V+g > 0) contribue au noyau.
  Équivalent à la condition de la méthode A : gaussian(all_strates) > 0.
  Cellule sans aucun voisin valide dans le noyau → NODATA_CLS.

CONVENTIONS PARTAGÉES
----------------------
  - Troncature du noyau : truncate = 2.0 (rayon = 2×sigma_px)
  - Paramètres figés : w=(0.35, 0.55, 0.10), seuils=(0.38, 0.60, 0.75)
  - Résolution : 2 m/px
  - 6 configurations : A×{σ=1,2,4} + B×{σ=1,2,4}
  - Témoin conservé : best_v2 = A, σ=1 m (vérification numérique obligatoire)

ÉVALUATION DES INCONNUS
------------------------
  pred=NODATA_CLS sur ref=veg → FN de présence et de catégorie.
  pred=NODATA_CLS sur ref=non-veg → exclu du dénominateur des spécificités.
  Taux d'inconnus reporté séparément.

Secteurs Cal/Val/Ctrl : tous désormais consultés — présentés comme
secteurs d'évaluation connus, non comme split calibration/contrôle aveugle.
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter

_THIS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

import importlib
_m = importlib.import_module("run_calibration_v2")
STRATES_PATH = _m.STRATES_PATH
OCAD_PATH    = _m.OCAD_PATH
ZONES        = _m.ZONES
OCAD_COLORS  = _m.OCAD_COLORS
RESULT_PALETTE = _m.RESULT_PALETTE
NODATA_CLS   = _m.NODATA_CLS
RES_M        = _m.RES_M
OBJ_W        = _m.OBJ_W
load_strates     = _m.load_strates
load_ocad_rgb    = _m.load_ocad_rgb
build_ocad_masks = _m.build_ocad_masks
zone_slice       = _m.zone_slice
compute_ndvd     = _m.compute_ndvd
classify_ndvd    = _m.classify_ndvd
compute_zone_metrics = _m.compute_zone_metrics

OUT_DIR  = _THIS
FIGS_DIR = _THIS / "figures"
FIGS_DIR.mkdir(exist_ok=True)

BEST_CFG: dict = json.loads((_THIS / "best_config.json").read_text())["params"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Règle de support B ──────────────────────────────────────────────────────
MIN_SUPPORT_B: float = 1e-9  # gaussian(validity) > 0 → tout voisin valide suffit

TRUNCATE: float = 2.0        # convention omapmaker partagée A et B

# ─── Poids et seuils figés (best_v2) ─────────────────────────────────────────
W_LOW  = BEST_CFG["w_low"]    # 0.35
W_MED  = BEST_CFG["w_med"]    # 0.55
W_HIGH = BEST_CFG["w_high"]   # 0.10
T406   = BEST_CFG["t406"]     # 0.38
T408   = BEST_CFG["t408"]     # 0.60
T410   = BEST_CFG["t410"]     # 0.75


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes de calcul du signal
# ─────────────────────────────────────────────────────────────────────────────

def _gaussian_1band(arr: np.ndarray, sigma_m: float) -> np.ndarray:
    """Gaussien sur un seul plan (H×W), convention omapmaker."""
    return gaussian_filter(
        arr.astype(np.float32),
        sigma=sigma_m / RES_M,
        truncate=TRUNCATE,
    )


def compute_signal_a(
    strates: np.ndarray, sigma_m: float,
    w_low: float = W_LOW, w_med: float = W_MED, w_high: float = W_HIGH,
) -> np.ndarray:
    """Méthode A : Gaussien sur comptages bruts, ratio ensuite.

    Chaque bande lissée séparément, puis V_lissé et g_lissé combinés en NDVD.
    Identique au pipeline omapmaker (apply_gaussian + compute_ndvd).
    """
    smooth = np.stack([_gaussian_1band(strates[i], sigma_m) for i in range(4)])
    return compute_ndvd(smooth, w_low, w_med, w_high)


def compute_signal_b(
    strates: np.ndarray, sigma_m: float,
    w_low: float = W_LOW, w_med: float = W_MED, w_high: float = W_HIGH,
) -> np.ndarray:
    """Méthode B : ratio brut par cellule, Gaussien normalisé ensuite.

    signal_B[i,j] = Σ_k w_k · ratio[k] · validity[k]
                    ─────────────────────────────────
                           Σ_k w_k · validity[k]

    où w_k est le poids gaussien de la cellule k par rapport à (i,j).
    Les cellules sans retour (validity=0) ne contribuent à aucun des deux termes.
    Support insuffisant (gaussian(validity) ≤ MIN_SUPPORT_B) → NODATA_CLS.
    """
    g = strates[0].astype(np.float32)
    V = (w_low * strates[1] + w_med * strates[2] + w_high * strates[3]).astype(np.float32)
    denom = V + g
    validity = (denom > 0.0).astype(np.float32)

    # Ratio en [0,1] pour cellules valides, 0.0 ailleurs (ne contribue pas)
    raw_ratio = np.zeros_like(denom, dtype=np.float32)
    valid = denom > 0.0
    raw_ratio[valid] = ((V[valid] - g[valid]) / denom[valid] + 1.0) / 2.0

    # Convolution normalisée : ne jamais injecter de sentinelle dans le filtre
    smooth_num = _gaussian_1band(raw_ratio * validity, sigma_m)
    smooth_den = _gaussian_1band(validity, sigma_m)

    signal = np.where(
        smooth_den > MIN_SUPPORT_B,
        smooth_num / smooth_den,
        np.float32(-9999.0),
    )
    return signal.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Configurations (6 + témoin)
# ─────────────────────────────────────────────────────────────────────────────

SIGMA_VALS = [1.0, 2.0, 4.0]

CONFIGS: list[dict] = [{"method": "A", "sigma_m": s} for s in SIGMA_VALS] + \
                      [{"method": "B", "sigma_m": s} for s in SIGMA_VALS]


def run_config(cfg: dict, strates_arr: np.ndarray) -> np.ndarray:
    if cfg["method"] == "A":
        sig = compute_signal_a(strates_arr, cfg["sigma_m"])
    else:
        sig = compute_signal_b(strates_arr, cfg["sigma_m"])
    return classify_ndvd(sig, T406, T408, T410)


# ─────────────────────────────────────────────────────────────────────────────
# Planche visuelle
# ─────────────────────────────────────────────────────────────────────────────

def _classes_to_rgb(cls: np.ndarray) -> np.ndarray:
    rgb = np.full((*cls.shape, 3), 255, dtype=np.uint8)
    for code, color in RESULT_PALETTE.items():
        rgb[cls == code] = color
    rgb[cls == NODATA_CLS] = (180, 0, 220)   # violet : support insuffisant
    return rgb


def _diff_map(pred: np.ndarray, ocad_masks: dict,
              r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
    pz = pred[r0:r1, c0:c1]
    m  = {k: v[r0:r1, c0:c1] for k, v in ocad_masks.items()}
    known = ~m["unknown"]
    ref_veg  = m["veg_406"] | m["veg_408"] | m["veg_410"]
    pred_veg = (pz >= 406) & (pz != NODATA_CLS)

    out = np.full((*pz.shape, 3), (230, 230, 230), dtype=np.uint8)
    out[known & ~pred_veg & ~ref_veg]  = (200, 200, 200)   # TN non-veg
    out[known &  pred_veg &  ref_veg]  = (200, 200, 200)   # accord veg
    out[known &  pred_veg & ~ref_veg]  = (220,  60,  60)   # FP veg
    out[known & ~pred_veg &  ref_veg & (pz != NODATA_CLS)] = (60, 60, 220)  # FN sol
    out[known & (pz == NODATA_CLS) &  ref_veg] = ( 50,  50, 180)  # FN inconnu
    out[known & (pz == NODATA_CLS) & ~ref_veg] = (180,   0, 220)  # inconnu non-veg
    # Erreur de sous-classe
    for code, cat in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        wrong = known & (pz == code) & ref_veg & ~m[cat]
        out[wrong] = (255, 160, 0)
    return out


def _crop(arr: np.ndarray, sl: tuple) -> np.ndarray:
    r0, r1, c0, c1 = sl
    return arr[r0:r1, c0:c1]


def build_planche(
    strates, ocad_rgb: np.ndarray, ocad_masks: dict,
    preds: dict[str, np.ndarray],
    témoin_key: str,
    best_a_key: str,
    best_b_key: str,
) -> pathlib.Path:
    """Planche 3 zones × 6 colonnes :
    OCAD / témoin / best_A / best_B / diff_A / diff_B.
    """
    zones_ordered = [
        ("cal",  "Cal-NE"),
        ("val",  "Val-SE"),
        ("ctrl", "Ctrl-NW"),
    ]
    col_configs = [
        ("OCAD\nréférence",   None),
        (f"Témoin\n{témoin_key}",    témoin_key),
        (f"Meilleur A\n{best_a_key}", best_a_key),
        (f"Meilleur B\n{best_b_key}", best_b_key),
        (f"Diff A\nvs OCAD",  "_diff_" + best_a_key),
        (f"Diff B\nvs OCAD",  "_diff_" + best_b_key),
    ]

    fig, axes = plt.subplots(3, 6, figsize=(24, 13))
    fig.patch.set_facecolor("#1a1a1a")

    for ci, (title, _) in enumerate(col_configs):
        axes[0, ci].set_title(title, color="white", fontsize=7, fontweight="bold", pad=3)

    for ri, (zk, zlabel) in enumerate(zones_ordered):
        sl = zone_slice(ZONES[zk], strates.transform, strates.h, strates.w)
        r0, r1, c0, c1 = sl

        for ci, (_, key) in enumerate(col_configs):
            ax = axes[ri, ci]
            if key is None:
                img = ocad_rgb[r0:r1, c0:c1]
            elif key.startswith("_diff_"):
                pred_key = key[len("_diff_"):]
                img = _diff_map(preds[pred_key], ocad_masks, r0, r1, c0, c1)
            else:
                img = _classes_to_rgb(_crop(preds[key], sl))
            ax.imshow(img)
            if ci == 0:
                ax.set_ylabel(zlabel, color="white", fontsize=7, rotation=90, labelpad=2)
            ax.set_xticks([]); ax.set_yticks([])
            ax.set_facecolor("#1a1a1a")
            for s in ax.spines.values():
                s.set_edgecolor("#555")

    # Légende
    legend = [
        mpatches.Patch(facecolor=(204/255,255/255,179/255), label="veg_406"),
        mpatches.Patch(facecolor=(153/255,255/255,102/255), label="veg_408"),
        mpatches.Patch(facecolor=( 51/255,255/255,  0/255), label="veg_410"),
        mpatches.Patch(facecolor=(255/255,201/255, 15/255), label="découvert"),
        mpatches.Patch(facecolor=(180/255,  0/255,220/255), label="NODATA (B)"),
        mpatches.Patch(facecolor=(220/255, 60/255, 60/255), label="FP veg"),
        mpatches.Patch(facecolor=( 60/255, 60/255,220/255), label="FN sol"),
        mpatches.Patch(facecolor=( 50/255, 50/255,180/255), label="FN inconnu"),
        mpatches.Patch(facecolor=(255/255,160/255,  0/255), label="erreur sous-classe"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=9, fontsize=6.5,
               labelcolor="white", facecolor="#2a2a2a", framealpha=0.3,
               bbox_to_anchor=(0.5, -0.01))

    fig.suptitle(
        "Voisinage A (Gaussien sur comptages) vs B (ratio puis Gaussien normalisé)\n"
        "Paramètres figés best_v2 · seuils 0.38/0.60/0.75 · poids 0.35/0.55/0.10",
        color="white", fontsize=8, y=1.01,
    )
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    out = FIGS_DIR / "compare_ab_voisinage.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("Planche : %s", out.name)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    strates  = load_strates()
    ocad_rgb = load_ocad_rgb()
    ocad_masks = build_ocad_masks(ocad_rgb, strates.h, strates.w)

    zone_keys = list(ZONES.keys())  # cal, val, ctrl

    # ── Témoin : best_v2 = A, sigma=1 ───────────────────────────────────────
    sig_témoin = compute_signal_a(strates.arr, 1.0)
    pred_témoin = classify_ndvd(sig_témoin, T406, T408, T410)

    # ── 6 configurations ─────────────────────────────────────────────────────
    all_preds: dict[str, np.ndarray] = {"A_1m": pred_témoin}
    for cfg in CONFIGS:
        key = f"{cfg['method']}_{cfg['sigma_m']:.0f}m"
        if key == "A_1m":
            continue   # déjà calculé
        all_preds[key] = run_config(cfg, strates.arr)
        log.info("Config %s : NODATA total = %d px",
                 key, int((all_preds[key] == NODATA_CLS).sum()))

    # ── Vérification : A sigma=1 == témoin best_v2 (tolérance numérique) ────
    sig_check = compute_signal_a(strates.arr, 1.0)
    pred_check = classify_ndvd(sig_check, T406, T408, T410)
    n_diff = int((pred_témoin != pred_check).sum())
    if n_diff == 0:
        log.info("VÉRIF OK : A, sigma=1 identique au témoin best_v2 (0 pixel différent)")
    else:
        log.warning("VÉRIF ÉCHEC : A, sigma=1 diffère du témoin sur %d pixels", n_diff)

    # ── Métriques ─────────────────────────────────────────────────────────────
    zone_sls = {zk: zone_slice(ZONES[zk], strates.transform, strates.h, strates.w)
                for zk in zone_keys}

    header = (
        f"{'Config':>6}  {'Zone':5}  "
        f"{'IoU_p':5}  {'Prec':5}  {'Rec':5}  "
        f"{'IoU406':6}  {'IoU408':6}  {'IoU410':6}  {'mIoU3':5}  "
        f"{'sp_nv':5}  {'sp_bl':5}  "
        f"{'score':5}  {'nunk':4}"
    )
    print()
    print(header)
    print("-" * len(header))

    all_results: dict[str, dict] = {}
    for key in ["A_1m", "A_2m", "A_4m", "B_1m", "B_2m", "B_4m"]:
        pred = all_preds[key]
        all_results[key] = {}
        for zk in zone_keys:
            m = compute_zone_metrics(pred, ocad_masks, zone_sls[zk])
            all_results[key][zk] = m
            unk_pct = 100.0 * m.n_pred_unknown / m.n_known if m.n_known > 0 else 0.0
            print(
                f"{key:>6}  {ZONES[zk]['label'][:5]:5}  "
                f"{m.iou_presence:.3f}  {m.precision_presence:.3f}  {m.recall_presence:.3f}  "
                f"{m.iou_406:.4f}  {m.iou_408:.4f}  {m.iou_410:.4f}  {m.miou3:.3f}  "
                f"{m.spec_nonveg:.3f}  {m.spec_blanc:.3f}  "
                f"{m.score:.3f}  {unk_pct:.2f}%"
            )
        print()

    # ── Meilleurs A et B (par val_score) ─────────────────────────────────────
    best_a = max([k for k in all_results if k.startswith("A")],
                 key=lambda k: all_results[k]["val"].score)
    best_b = max([k for k in all_results if k.startswith("B")],
                 key=lambda k: all_results[k]["val"].score)
    log.info("Meilleur A (val) : %s  score=%.4f", best_a, all_results[best_a]["val"].score)
    log.info("Meilleur B (val) : %s  score=%.4f", best_b, all_results[best_b]["val"].score)

    # ── Planche ───────────────────────────────────────────────────────────────
    build_planche(strates, ocad_rgb, ocad_masks, all_preds,
                  témoin_key="A_1m", best_a_key=best_a, best_b_key=best_b)


if __name__ == "__main__":
    main()
