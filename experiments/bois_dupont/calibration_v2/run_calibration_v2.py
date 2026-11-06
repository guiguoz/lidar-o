"""Calibration autonome moteur végétation — Bois Dupont, campagne v2.

Découpage spatial (2 m/px, grille 500×500 sur 425000–426000 × 6922000–6923000) :
  Cal  (NE) : cols [255,500) × rows [0,245)   → x=[425510,426000] y=[6922510,6923000]
              — inclut la fenêtre NE examinée (session précédente)
  Val  (SE) : cols [255,500) × rows [255,500) → x=[425510,426000] y=[6922000,6922490]
              — VIERGE, non examinée avant cette campagne
  Ctrl (NW) : cols [0,245)   × rows [0,245)   → x=[425000,425490] y=[6922510,6923000]
              — VIERGE, non examinée avant cette campagne
  Exclu(SW) : cols [0,245)   × rows [255,500) — exclue (fenêtre SW examinée)
  Marge entre zones : 10 px = 20 m (>>  portée Gaussien max ≈ 3 px à sigma_m=4 m)

  Réserve : toutes les zones sont sur la même dalle. Le contrôle Ctrl-NW est
  un contrôle spatial local, non une validation sur un autre terrain ou une autre
  acquisition. Limite documentée.

Fonction objectif (définie avant la recherche, non ajustée ensuite) :
  score = 0.50·mIoU(406,408,410) + 0.25·IoU_présence + 0.15·(1−fp_nonveg) + 0.10·(1−fp_blanc)
  mIoU(406,408,410) : moyenne des IoU par catégorie, pixels à référence connue uniquement
  IoU_présence      : IoU binaire veg / non-veg
  fp_nonveg         : faux positifs veg sur découvert+bâti (doit rester bas)
  fp_blanc          : faux positifs veg sur blanc/clarières (surveille les passages)

  Blanc et découvert sont des catégories connues, pas des données absentes.
  Bâti/routes ne seront pas reproduits par le moteur végétation ; leur traitement
  est un post-traitement séparé (non implémenté ici).

  Couverture = fraction de pixels avec référence OCAD connue, reportée séparément
  pour détecter une amélioration artificielle par abstention.

Critère plateau (défini avant la recherche) :
  Arrêt anticipé si delta_val < 0.005 sur 15 configs consécutives.

Budget :
  Phase 1 (cheap)  : thresholds sur signal existant     ≤ 100 configs,  0 recalcul LAZ
  Phase 2 (medium) : Gaussien + thresholds sur strates  ≤ 30  configs,  0 recalcul LAZ
  Phase 2b(medium) : poids + thresholds sur strates     ≤ 20  configs,  0 recalcul LAZ
  Phase 3 (costly) : re-lecture LAZ, si et seulement si les phases 1–2b
                     sont insuffisantes — max 5 upstream runs (non implémenté ici,
                     à déclencher manuellement selon le bilan)

Témoins figés (scores de référence) :
  v0_t406_040 : t406=0.4, t408=0.6, t410=0.8, sigma=1.0 m (baseline v0)
  v0_t406_030 : t406=0.3, t408=0.6, t410=0.8, sigma=1.0 m (seuil-03, session précédente)

Rappel A/B/C :
  A — documenté omapmaker (open-source, non OCAD) : strates, NDVD, Gaussien, DTM
  B — déduit / non garanti : seuils 0.4/0.6/0.8, méthode DTM exacte
  C — choix propre : résolution 2 m/px
  omapmaker ≠ implémentation certifiée OCAD. Lien non établi.
"""
from __future__ import annotations

import datetime
import itertools
import json
import logging
import pathlib
import sys
from dataclasses import dataclass
from typing import Any, NamedTuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Chemins ─────────────────────────────────────────────────────────────────
_THIS = pathlib.Path(__file__).resolve().parent
_DIAG = _THIS.parent / "diagnostic_vege"
SIGNAL_PATH  = _DIAG / "lidar_vege" / "omapmaker_signal_apres_voisinage.tif"
STRATES_PATH = _DIAG / "lidar_vege" / "omapmaker_strates.tif"
OCAD_PATH = pathlib.Path(
    "E:/RunningRaid/Cartographie/ça te dit 2027/bois Dupont/"
    "LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc_VegetationBaseMap.png"
)
LAZ_PATH = pathlib.Path(
    "E:/RunningRaid/Cartographie/ça te dit 2027/bois Dupont/"
    "LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz"
)
CRS = "EPSG:2154"
OUT_DIR  = _THIS
FIGS_DIR = _THIS / "figures"
JOURNAL_PATH = _THIS / "journal.jsonl"

# ─── Découpage spatial ───────────────────────────────────────────────────────
RES_M = 2.0

ZONES: dict[str, dict] = {
    "cal":  {"label": "Cal-NE",  "xmin": 425510.0, "ymin": 6922510.0,
             "xmax": 426000.0, "ymax": 6923000.0},
    "val":  {"label": "Val-SE",  "xmin": 425510.0, "ymin": 6922000.0,
             "xmax": 426000.0, "ymax": 6922490.0},
    "ctrl": {"label": "Ctrl-NW", "xmin": 425000.0, "ymin": 6922510.0,
             "xmax": 425490.0, "ymax": 6923000.0},
}

# ─── Couleurs OCAD ───────────────────────────────────────────────────────────
OCAD_COLORS: dict[tuple[int, int, int], str] = {
    (255, 201,  15): "decouvert",
    (255, 255, 255): "blanc",
    (204, 255, 179): "veg_406",
    (153, 255, 102): "veg_408",
    ( 51, 255,   0): "veg_410",
    ( 25,  25,  25): "bati",
}
OCAD_VEG = frozenset({"veg_406", "veg_408", "veg_410"})
OCAD_NONVEG_STRICT = frozenset({"decouvert", "bati"})

RESULT_PALETTE: dict[int, tuple[int, int, int]] = {
    0:   (255, 201,  15),
    406: (204, 255, 179),
    408: (153, 255, 102),
    410: ( 51, 255,   0),
}

# Support insuffisant après voisinage : V+g==0 dans les strates lissées.
# Distinct de classe 0 (sol/non-veg). Exclu des TP/FP/FN, compté séparément.
NODATA_CLS: int = 65535

# ─── Fonction objectif (définie avant la recherche) ──────────────────────────
OBJ_W = {"miou3": 0.50, "iou_pres": 0.25, "spec_nonveg": 0.15, "spec_blanc": 0.10}

# ─── Critère plateau (défini avant la recherche) ─────────────────────────────
PLATEAU_DELTA = 0.005
PLATEAU_N     = 15

# ─── Témoins figés ───────────────────────────────────────────────────────────
WITNESSES: list[dict] = [
    {"name": "témoin_t406_040", "t406": 0.40, "t408": 0.60, "t410": 0.80,
     "sigma_m": 1.0, "w_low": 0.50, "w_med": 0.35, "w_high": 0.15},
    {"name": "témoin_t406_030", "t406": 0.30, "t408": 0.60, "t410": 0.80,
     "sigma_m": 1.0, "w_low": 0.50, "w_med": 0.35, "w_high": 0.15},
]


# ─────────────────────────────────────────────────────────────────────────────
# Types de données
# ─────────────────────────────────────────────────────────────────────────────

class RasterData(NamedTuple):
    arr: np.ndarray
    transform: Any
    h: int
    w: int


@dataclass
class ZoneMetrics:
    n_total: int
    n_known: int
    n_pred_unknown: int   # pixels NODATA_CLS à l'intérieur d'une référence évaluable
    coverage: float
    iou_presence: float
    precision_presence: float
    recall_presence: float
    iou_406: float
    iou_408: float
    iou_410: float
    miou3: float
    spec_nonveg: float
    spec_blanc: float
    score: float

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Chargement des données
# ─────────────────────────────────────────────────────────────────────────────

def load_strates() -> RasterData:
    with rasterio.open(STRATES_PATH) as src:
        arr = src.read().astype(np.float32)   # (4, H, W) : g, low, med, high
        transform = src.transform
    h, w = arr.shape[1], arr.shape[2]
    log.info("Strates : %d×%d px, %d bandes", w, h, arr.shape[0])
    return RasterData(arr, transform, h, w)


def load_ocad_rgb() -> np.ndarray:
    img = Image.open(OCAD_PATH).convert("RGB")
    return np.array(img)


def build_ocad_masks(ocad_rgb: np.ndarray, h: int, w: int) -> dict[str, np.ndarray]:
    """Construit les masques booléens par catégorie OCAD."""
    oh, ow = ocad_rgb.shape[:2]
    if (oh, ow) != (h, w):
        log.warning("Taille OCAD (%d×%d) ≠ raster (%d×%d) — troncature", ow, oh, w, h)
    min_h, min_w = min(h, oh), min(w, ow)
    rgb = ocad_rgb[:min_h, :min_w]

    masks: dict[str, np.ndarray] = {name: np.zeros((h, w), bool)
                                     for name in list(OCAD_COLORS.values()) + ["unknown"]}
    for (r, g, b), cat in OCAD_COLORS.items():
        masks[cat][:min_h, :min_w] |= (
            (rgb[:, :, 0] == r) & (rgb[:, :, 1] == g) & (rgb[:, :, 2] == b)
        )
    known = np.zeros((h, w), bool)
    for cat in OCAD_COLORS.values():
        known |= masks[cat]
    masks["unknown"] = ~known

    for cat, m in masks.items():
        if cat != "unknown":
            log.debug("OCAD %-12s : %d px", cat, int(m.sum()))
    log.info("OCAD inconnu : %d px (%.1f%%)", int(masks["unknown"].sum()),
             100 * masks["unknown"].sum() / (h * w))
    return masks


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires spatiaux
# ─────────────────────────────────────────────────────────────────────────────

def zone_slice(zone: dict, transform: Any, h: int, w: int) -> tuple[int, int, int, int]:
    res_x = abs(transform.a)
    res_y = abs(transform.e)
    xmin_grid = transform.c
    ymax_grid = transform.f
    c0 = max(0, int(np.floor((zone["xmin"] - xmin_grid) / res_x)))
    c1 = min(w, int(np.ceil( (zone["xmax"] - xmin_grid) / res_x)))
    r0 = max(0, int(np.floor((ymax_grid - zone["ymax"]) / res_y)))
    r1 = min(h, int(np.ceil( (ymax_grid - zone["ymin"]) / res_y)))
    return r0, r1, c0, c1


# ─────────────────────────────────────────────────────────────────────────────
# Traitement du signal
# ─────────────────────────────────────────────────────────────────────────────

def apply_gaussian(strates: np.ndarray, sigma_m: float) -> np.ndarray:
    """Voisinage gaussien, rayon = 2×sigma (convention omapmaker), sur chaque bande."""
    sigma_px = sigma_m / RES_M
    truncate = 2.0
    result = np.empty_like(strates)
    for i in range(strates.shape[0]):
        result[i] = gaussian_filter(strates[i].astype(np.float32),
                                    sigma=sigma_px, truncate=truncate)
    return result


def compute_ndvd(strates: np.ndarray, w_low: float, w_med: float, w_high: float) -> np.ndarray:
    """NDVD = ((V − g) / (V + g) + 1) / 2.  NaN → −9999 (aucun retour)."""
    g = strates[0]
    V = w_low * strates[1] + w_med * strates[2] + w_high * strates[3]
    denom = V + g
    valid = denom > 0.0
    raw = np.full_like(denom, np.nan, dtype=np.float32)
    raw[valid] = (V[valid] - g[valid]) / denom[valid]
    ndvd = ((raw + 1.0) / 2.0).astype(np.float32)
    return np.where(np.isnan(ndvd), np.float32(-9999.0), ndvd)


def classify_ndvd(signal: np.ndarray, t406: float, t408: float, t410: float) -> np.ndarray:
    """Seuillage ordonné.
    signal=−9999 (V+g==0 après voisinage) → NODATA_CLS (support insuffisant),
    distinct de classe 0 (sol/non-veg).
    """
    cls = np.zeros(signal.shape, dtype=np.uint16)
    cls[signal >= t406] = 406
    cls[signal >= t408] = 408
    cls[signal >= t410] = 410
    cls[signal == np.float32(-9999.0)] = NODATA_CLS
    return cls


def config_to_pred(cfg: dict, strates: RasterData, _cache: dict) -> np.ndarray:
    """Calcule la prédiction pour un config dict, avec cache des strates lissées."""
    sigma_m = cfg["sigma_m"]
    if sigma_m not in _cache:
        _cache[sigma_m] = apply_gaussian(strates.arr, sigma_m)
    smooth = _cache[sigma_m]
    ndvd = compute_ndvd(smooth, cfg["w_low"], cfg["w_med"], cfg["w_high"])
    return classify_ndvd(ndvd, cfg["t406"], cfg["t408"], cfg["t410"])


# ─────────────────────────────────────────────────────────────────────────────
# Métriques
# ─────────────────────────────────────────────────────────────────────────────

def _iou(tp: int, fp: int, fn: int) -> float:
    denom = tp + fp + fn
    return float(tp) / denom if denom > 0 else 0.0


def compute_zone_metrics(
    pred: np.ndarray,
    ocad_masks: dict[str, np.ndarray],
    sl: tuple[int, int, int, int],
) -> ZoneMetrics:
    r0, r1, c0, c1 = sl
    n_total = (r1 - r0) * (c1 - c0)
    pred_z = pred[r0:r1, c0:c1]
    m = {k: v[r0:r1, c0:c1] for k, v in ocad_masks.items()}

    known = ~m["unknown"]
    n_known = int(known.sum())

    # Support insuffisant après voisinage.
    # Comptés dans n_known si OCAD les connaît.
    # Prédiction inconnue sur référence végétation : FN de présence ET de catégorie.
    # Prédiction inconnue sur référence non-veg : exclue du dénominateur des spécificités
    # (ne compte ni comme succès ni comme erreur).
    pred_nodata = pred_z == NODATA_CLS
    n_pred_unknown = int((pred_nodata & known).sum())
    pred_evaluable = ~pred_nodata

    # Présence binaire
    ref_veg  = m["veg_406"] | m["veg_408"] | m["veg_410"]
    pred_veg = (pred_z >= 406) & (pred_z != NODATA_CLS)
    tp_p = int((pred_veg &  ref_veg & known).sum())
    fp_p = int((pred_veg & ~ref_veg & known).sum())
    # ~pred_veg inclut pred=0 ET pred=NODATA_CLS → NODATA sur ref_veg = FN
    fn_p = int((~pred_veg & ref_veg & known).sum())
    iou_pres  = _iou(tp_p, fp_p, fn_p)
    prec_pres = float(tp_p) / (tp_p + fp_p) if (tp_p + fp_p) > 0 else 0.0
    rec_pres  = float(tp_p) / (tp_p + fn_p) if (tp_p + fn_p) > 0 else 0.0

    # IoU par catégorie végétation
    # ~pred_c inclut pred≠code ET pred=NODATA → NODATA sur ref_cat = FN de cette catégorie
    ious = []
    for code, cat in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        ref_c  = m[cat]
        pred_c = (pred_z == code)
        tp = int((pred_c &  ref_c & known).sum())
        fp = int((pred_c & ~ref_c & known).sum())
        fn = int((~pred_c & ref_c & known).sum())
        ious.append(_iou(tp, fp, fn))
    iou_406, iou_408, iou_410 = ious
    miou3 = float(np.mean(ious))

    # Spécificité non-veg strict (découvert + bâti)
    # Dénominateur = pixels évaluables uniquement (NODATA exclus, ne compte pas comme succès)
    ref_strict = m["decouvert"] | m["bati"]
    fp_nonveg = int((pred_veg & ref_strict & known).sum())
    n_strict_eval = int((ref_strict & known & pred_evaluable).sum())
    spec_nonveg = 1.0 - float(fp_nonveg) / n_strict_eval if n_strict_eval > 0 else 1.0

    # Spécificité blanc (passages, clarières)
    fp_blanc = int((pred_veg & m["blanc"] & known).sum())
    n_blanc_eval = int((m["blanc"] & known & pred_evaluable).sum())
    spec_blanc = 1.0 - float(fp_blanc) / n_blanc_eval if n_blanc_eval > 0 else 1.0

    score = (
        OBJ_W["miou3"]     * miou3
        + OBJ_W["iou_pres"]   * iou_pres
        + OBJ_W["spec_nonveg"] * spec_nonveg
        + OBJ_W["spec_blanc"]  * spec_blanc
    )

    return ZoneMetrics(
        n_total=n_total, n_known=n_known, n_pred_unknown=n_pred_unknown,
        coverage=round(float(n_known) / n_total, 4),
        iou_presence=round(iou_pres, 4), precision_presence=round(prec_pres, 4),
        recall_presence=round(rec_pres, 4),
        iou_406=round(iou_406, 4), iou_408=round(iou_408, 4), iou_410=round(iou_410, 4),
        miou3=round(miou3, 4),
        spec_nonveg=round(spec_nonveg, 4), spec_blanc=round(spec_blanc, 4),
        score=round(score, 4),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Journal
# ─────────────────────────────────────────────────────────────────────────────

def journal_append(entry: dict) -> None:
    entry = {**entry, "ts": datetime.datetime.now().isoformat(timespec="seconds")}
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Plateau detector
# ─────────────────────────────────────────────────────────────────────────────

def has_plateau(val_scores: list[float]) -> bool:
    if len(val_scores) < PLATEAU_N:
        return False
    recent = val_scores[-PLATEAU_N:]
    return (max(recent) - min(recent)) < PLATEAU_DELTA


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Grille de seuils sur signal recalculé depuis strates (sigma=1.0 m)
# ─────────────────────────────────────────────────────────────────────────────

def _threshold_grid() -> list[tuple[float, float, float]]:
    t406_vals = [0.22, 0.25, 0.28, 0.30, 0.32, 0.35, 0.38, 0.40, 0.42, 0.45]
    t408_vals = [0.50, 0.55, 0.60, 0.65, 0.70]
    t410_vals = [0.70, 0.75, 0.80, 0.85]
    return [
        (t406, t408, t410)
        for t406, t408, t410 in itertools.product(t406_vals, t408_vals, t410_vals)
        if t406 < t408 < t410
    ]


def _run_threshold_grid(
    ndvd: np.ndarray,
    strates: RasterData,
    ocad_masks: dict,
    sigma_m: float,
    w_low: float,
    w_med: float,
    w_high: float,
    phase_label: Any,
    id_offset: int = 0,
) -> list[dict]:
    """Applique la grille de seuils sur un signal NDVD pré-calculé."""
    configs = _threshold_grid()
    sl = {k: zone_slice(ZONES[k], strates.transform, strates.h, strates.w)
          for k in ("cal", "val")}
    results = []
    for i, (t406, t408, t410) in enumerate(configs, 1):
        pred = classify_ndvd(ndvd, t406, t408, t410)
        m_cal = compute_zone_metrics(pred, ocad_masks, sl["cal"])
        m_val = compute_zone_metrics(pred, ocad_masks, sl["val"])
        entry: dict = {
            "phase": phase_label, "config_id": id_offset + i,
            "t406": t406, "t408": t408, "t410": t410,
            "sigma_m": sigma_m, "w_low": w_low, "w_med": w_med, "w_high": w_high,
            "cal": m_cal.to_dict(), "val": m_val.to_dict(),
        }
        journal_append(entry)
        results.append(entry)
    n = len(results)
    best_i = max(range(n), key=lambda j: results[j]["val"]["score"])
    best = results[best_i]
    log.info(
        "  → %d configs : best val=%.4f (t406=%.2f t408=%.2f t410=%.2f)",
        n, best["val"]["score"], best["t406"], best["t408"], best["t410"],
    )
    return results


def phase1(strates: RasterData, ocad_masks: dict) -> list[dict]:
    log.info("=" * 70)
    log.info("PHASE 1 — Grille seuils complète (sigma=1.0 m, poids référence)")
    log.info("  poids : w_low=0.50 w_med=0.35 w_high=0.15 (hérités d'omapmaker)")
    log.info("  Pas de plateau — grille entière (cheap, aucun recalcul LAZ)")
    log.info("=" * 70)

    smooth_1m = apply_gaussian(strates.arr, 1.0)
    ndvd_1m   = compute_ndvd(smooth_1m, 0.50, 0.35, 0.15)
    configs_total = len(_threshold_grid())
    log.info("Configurations Phase 1 : %d", configs_total)

    results = _run_threshold_grid(
        ndvd_1m, strates, ocad_masks,
        sigma_m=1.0, w_low=0.50, w_med=0.35, w_high=0.15,
        phase_label=1,
    )
    results_sorted = sorted(results, key=lambda r: r["val"]["score"], reverse=True)
    best = results_sorted[0]
    log.info(
        "Phase 1 terminée : best val=%.4f (t406=%.2f t408=%.2f t410=%.2f)",
        best["val"]["score"], best["t406"], best["t408"], best["t410"],
    )
    return results_sorted


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Gaussien variés × top-5 seuils Phase 1
# ─────────────────────────────────────────────────────────────────────────────

def phase2(strates: RasterData, ocad_masks: dict, top_p1: list[dict]) -> list[dict]:
    log.info("=" * 70)
    log.info("PHASE 2 — Grille sigma_m (recalcul Gaussien strates) × top-5 P1")
    log.info("  sigma_m=1.0 est le baseline P1 ; on explore 1.5–4.0")
    log.info("=" * 70)

    sigma_vals = [1.5, 2.0, 2.5, 3.0, 4.0]
    top5 = top_p1[:5]

    sl = {k: zone_slice(ZONES[k], strates.transform, strates.h, strates.w)
          for k in ("cal", "val")}

    results = []
    cfg_id = 0
    val_scores: list[float] = []

    for sigma_m in sigma_vals:
        sigma_px = sigma_m / RES_M
        log.info("  Gaussien sigma_m=%.1f (sigma_px=%.2f, noyau ~%dx%d)",
                 sigma_m, sigma_px,
                 2 * int(np.ceil(2.0 * sigma_px)) + 1,
                 2 * int(np.ceil(2.0 * sigma_px)) + 1)
        smooth = apply_gaussian(strates.arr, sigma_m)

        for cfg in top5:
            cfg_id += 1
            ndvd = compute_ndvd(smooth, cfg["w_low"], cfg["w_med"], cfg["w_high"])
            pred = classify_ndvd(ndvd, cfg["t406"], cfg["t408"], cfg["t410"])
            m_cal = compute_zone_metrics(pred, ocad_masks, sl["cal"])
            m_val = compute_zone_metrics(pred, ocad_masks, sl["val"])

            entry: dict = {
                "phase": 2, "config_id": cfg_id,
                "t406": cfg["t406"], "t408": cfg["t408"], "t410": cfg["t410"],
                "sigma_m": sigma_m,
                "w_low": cfg["w_low"], "w_med": cfg["w_med"], "w_high": cfg["w_high"],
                "cal": m_cal.to_dict(), "val": m_val.to_dict(),
            }
            journal_append(entry)
            results.append(entry)
            val_scores.append(m_val.score)
            log.info("    sigma=%.1f t406=%.2f  cal=%.3f val=%.3f",
                     sigma_m, cfg["t406"], m_cal.score, m_val.score)

        if has_plateau(val_scores):
            log.info("  Plateau Phase 2 après sigma_m=%.1f", sigma_m)
            break

    results_sorted = sorted(results, key=lambda r: r["val"]["score"], reverse=True)
    best = results_sorted[0]
    log.info("Phase 2 terminée : best val=%.4f (sigma=%.1f t406=%.2f)",
             best["val"]["score"], best["sigma_m"], best["t406"])
    return results_sorted


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2b — Poids strates variés (meilleur sigma de Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

def phase2b(strates: RasterData, ocad_masks: dict,
            best_sigma: float, best_thresh: dict) -> list[dict]:
    log.info("=" * 70)
    log.info("PHASE 2b — Poids strates (sigma_m=%.1f, seuils figés)", best_sigma)
    log.info("=" * 70)

    weight_combos: list[tuple[float, float, float]] = []
    for w_high in [0.10, 0.15, 0.20, 0.25, 0.30]:
        for w_low in [0.35, 0.45, 0.55, 0.60]:
            w_med = round(1.0 - w_low - w_high, 6)
            if w_med > 0.05:
                weight_combos.append((w_low, w_med, w_high))

    log.info("Configurations Phase 2b : %d", len(weight_combos))

    smooth = apply_gaussian(strates.arr, best_sigma)
    sl = {k: zone_slice(ZONES[k], strates.transform, strates.h, strates.w)
          for k in ("cal", "val")}

    t406, t408, t410 = best_thresh["t406"], best_thresh["t408"], best_thresh["t410"]
    results = []
    val_scores: list[float] = []

    for i, (w_low, w_med, w_high) in enumerate(weight_combos, 1):
        ndvd = compute_ndvd(smooth, w_low, w_med, w_high)
        pred = classify_ndvd(ndvd, t406, t408, t410)
        m_cal = compute_zone_metrics(pred, ocad_masks, sl["cal"])
        m_val = compute_zone_metrics(pred, ocad_masks, sl["val"])

        entry: dict = {
            "phase": "2b", "config_id": i,
            "t406": t406, "t408": t408, "t410": t410,
            "sigma_m": best_sigma,
            "w_low": w_low, "w_med": w_med, "w_high": w_high,
            "cal": m_cal.to_dict(), "val": m_val.to_dict(),
        }
        journal_append(entry)
        results.append(entry)
        val_scores.append(m_val.score)
        log.info("  [%2d/%d] w=(%.2f,%.2f,%.2f)  cal=%.3f val=%.3f",
                 i, len(weight_combos), w_low, w_med, w_high,
                 m_cal.score, m_val.score)

        if has_plateau(val_scores):
            log.info("  Plateau Phase 2b après %d configs", i)
            break

    results_sorted = sorted(results, key=lambda r: r["val"]["score"], reverse=True)
    best = results_sorted[0]
    log.info("Phase 2b terminée : best val=%.4f (w=%.2f,%.2f,%.2f)",
             best["val"]["score"], best["w_low"], best["w_med"], best["w_high"])
    return results_sorted


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2c — Grille seuils avec les meilleurs poids+sigma de Phase 2b
# ─────────────────────────────────────────────────────────────────────────────

def phase2c(strates: RasterData, ocad_masks: dict,
            best_sigma: float, best_w: dict, id_offset: int = 0) -> list[dict]:
    log.info("=" * 70)
    log.info("PHASE 2c — Grille seuils avec meilleurs poids+sigma de Phase 2b")
    log.info("  sigma_m=%.1f  w=(%.2f,%.2f,%.2f)",
             best_sigma, best_w["w_low"], best_w["w_med"], best_w["w_high"])
    log.info("=" * 70)
    smooth = apply_gaussian(strates.arr, best_sigma)
    ndvd   = compute_ndvd(smooth, best_w["w_low"], best_w["w_med"], best_w["w_high"])
    results = _run_threshold_grid(
        ndvd, strates, ocad_masks,
        sigma_m=best_sigma,
        w_low=best_w["w_low"], w_med=best_w["w_med"], w_high=best_w["w_high"],
        phase_label="2c", id_offset=id_offset,
    )
    return sorted(results, key=lambda r: r["val"]["score"], reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────────────────────────

def _classes_to_rgb(cls: np.ndarray) -> np.ndarray:
    rgb = np.full((*cls.shape, 3), 255, dtype=np.uint8)
    for code, (r, g, b) in RESULT_PALETTE.items():
        mask = cls == code
        rgb[mask, 0] = r
        rgb[mask, 1] = g
        rgb[mask, 2] = b
    return rgb


def _crop(arr: np.ndarray, sl: tuple) -> np.ndarray:
    r0, r1, c0, c1 = sl
    return arr[r0:r1, c0:c1]


def _pred_rgb_for_cfg(cfg: dict, strates: RasterData,
                      sl: tuple, smooth_cache: dict) -> np.ndarray:
    sigma = cfg["sigma_m"]
    if sigma not in smooth_cache:
        smooth_cache[sigma] = apply_gaussian(strates.arr, sigma)
    ndvd = compute_ndvd(smooth_cache[sigma], cfg["w_low"], cfg["w_med"], cfg["w_high"])
    pred = classify_ndvd(ndvd, cfg["t406"], cfg["t408"], cfg["t410"])
    return _classes_to_rgb(_crop(pred, sl))


def build_comparison_figure(
    strates: RasterData,
    ocad_rgb: np.ndarray,
    ocad_masks: dict,
    configs: list[dict],
    zone_key: str,
    fig_name: str,
    title: str,
    smooth_cache: dict,
) -> pathlib.Path:
    sl = zone_slice(ZONES[zone_key], strates.transform, strates.h, strates.w)
    ocad_crop = _crop(ocad_rgb, sl)

    panels = [("OCAD référence", ocad_crop)]
    for cfg in configs:
        name = cfg.get("name", f"p{cfg.get('phase','?')}")
        label = (f"{name}\nσ={cfg['sigma_m']:.1f} t406={cfg['t406']:.2f} "
                 f"w=({cfg['w_low']:.2f},{cfg['w_med']:.2f},{cfg['w_high']:.2f})\n"
                 f"val={cfg.get('val', {}).get('score', '?'):.3f}" if isinstance(cfg.get('val', {}).get('score'), float)
                 else name)
        rgb = _pred_rgb_for_cfg(cfg, strates, sl, smooth_cache)
        panels.append((label, rgb))

    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
    if n == 1:
        axes = [axes]
    for ax, (lbl, img) in zip(axes, panels):
        ax.imshow(img)
        ax.set_title(lbl, fontsize=7)
        ax.axis("off")

    fig.suptitle(f"{title} — {ZONES[zone_key]['label']}", fontsize=9, fontweight="bold")
    plt.tight_layout()
    out = FIGS_DIR / fig_name
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Figure : %s", out.name)
    return out


def build_zone_overview(
    strates: RasterData,
    ocad_rgb: np.ndarray,
    best_cfg: dict,
    smooth_cache: dict,
) -> pathlib.Path:
    sl_full = (0, strates.h, 0, strates.w)
    if best_cfg["sigma_m"] not in smooth_cache:
        smooth_cache[best_cfg["sigma_m"]] = apply_gaussian(strates.arr, best_cfg["sigma_m"])
    ndvd_full = compute_ndvd(
        smooth_cache[best_cfg["sigma_m"]],
        best_cfg["w_low"], best_cfg["w_med"], best_cfg["w_high"],
    )
    pred_full = classify_ndvd(ndvd_full, best_cfg["t406"], best_cfg["t408"], best_cfg["t410"])
    pred_rgb  = _classes_to_rgb(pred_full)

    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for ax, (img, ttl) in zip(axes, [
        (ocad_rgb, "OCAD référence"),
        (pred_rgb, (f"Best config — σ={best_cfg['sigma_m']:.1f} m "
                    f"t406={best_cfg['t406']:.2f} "
                    f"val={best_cfg.get('val', {}).get('score', 0):.3f}")),
    ]):
        ax.imshow(img)
        ax.set_title(ttl, fontsize=9)
        for zk, z in ZONES.items():
            sl = zone_slice(z, strates.transform, strates.h, strates.w)
            r0, r1, c0, c1 = sl
            color = {"cal": "blue", "val": "limegreen", "ctrl": "red"}[zk]
            rect = plt.Rectangle((c0, r0), c1 - c0, r1 - r0,
                                  fill=False, edgecolor=color, lw=1.5, ls="--")
            ax.add_patch(rect)
            ax.text(c0 + 2, r0 + 10, z["label"], color=color, fontsize=7, fontweight="bold")
        ax.axis("off")

    fig.suptitle("Vue globale — Bois Dupont — zones Cal/Val/Ctrl", fontsize=10, fontweight="bold")
    plt.tight_layout()
    out = FIGS_DIR / "overview_zones.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Figure : %s", out.name)
    return out


def build_ctrl_figure(
    strates: RasterData,
    ocad_rgb: np.ndarray,
    ocad_masks: dict,
    best_cfg: dict,
    witnesses_ext: list[dict],
    smooth_cache: dict,
) -> ZoneMetrics:
    zone = "ctrl"
    sl = zone_slice(ZONES[zone], strates.transform, strates.h, strates.w)
    ocad_crop = _crop(ocad_rgb, sl)

    # Prédiction best config sur ctrl
    sigma = best_cfg["sigma_m"]
    if sigma not in smooth_cache:
        smooth_cache[sigma] = apply_gaussian(strates.arr, sigma)
    ndvd_best = compute_ndvd(smooth_cache[sigma],
                              best_cfg["w_low"], best_cfg["w_med"], best_cfg["w_high"])
    pred_best = classify_ndvd(ndvd_best, best_cfg["t406"], best_cfg["t408"], best_cfg["t410"])
    m_ctrl    = compute_zone_metrics(pred_best, ocad_masks, sl)

    panels = [("OCAD Ctrl-NW", ocad_crop)]
    for w in witnesses_ext:
        panels.append((
            f"{w['name']}\nctrl_pres={w.get('ctrl', {}).get('iou_presence', 0):.3f}",
            _pred_rgb_for_cfg(w, strates, sl, smooth_cache),
        ))
    panels.append((
        f"Best final\nctrl_score={m_ctrl.score:.3f}\nmiou3={m_ctrl.miou3:.3f}",
        _classes_to_rgb(_crop(pred_best, sl)),
    ))

    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
    if n == 1:
        axes = [axes]
    for ax, (lbl, img) in zip(axes, panels):
        ax.imshow(img)
        ax.set_title(lbl, fontsize=8)
        ax.axis("off")

    fig.suptitle(
        "CONTRÔLE FINAL — Ctrl-NW (vierge, non consultée pendant la calibration)\n"
        "Réserve : même dalle, contrôle spatial local uniquement",
        fontsize=9, fontweight="bold",
    )
    plt.tight_layout()
    out = FIGS_DIR / "ctrl_final.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Figure contrôle : %s", out.name)
    return m_ctrl


def export_palette_png(strates: RasterData, cfg: dict, smooth_cache: dict) -> pathlib.Path:
    """Exporte best config en PNG+PGW pour affichage dans l'application."""
    sigma = cfg["sigma_m"]
    if sigma not in smooth_cache:
        smooth_cache[sigma] = apply_gaussian(strates.arr, sigma)
    ndvd = compute_ndvd(smooth_cache[sigma], cfg["w_low"], cfg["w_med"], cfg["w_high"])
    pred = classify_ndvd(ndvd, cfg["t406"], cfg["t408"], cfg["t410"])

    h, w = pred.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for code, (r, g, b) in RESULT_PALETTE.items():
        mask = pred == code
        rgba[mask, 0] = r
        rgba[mask, 1] = g
        rgba[mask, 2] = b
        rgba[mask, 3] = 0 if code == 0 else 255

    out_png = OUT_DIR / "best_vege_calib_v2.png"
    Image.fromarray(rgba, "RGBA").save(out_png)

    t = strates.transform
    res_x, res_y = abs(t.a), abs(t.e)
    x_ul = t.c + res_x / 2.0
    y_ul = t.f - res_y / 2.0
    out_png.with_suffix(".pgw").write_text(
        f"{res_x:.9f}\n0.000000000000\n0.000000000000\n"
        f"-{res_y:.9f}\n{x_ul:.4f}\n{y_ul:.4f}\n",
        encoding="utf-8",
    )
    log.info("Export palette : %s (%d×%d px, %.1f m/px)", out_png.name, w, h, res_x)
    return out_png


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────────────────────────────────────

def run_campaign() -> None:
    FIGS_DIR.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.unlink(missing_ok=True)

    for p in (STRATES_PATH, OCAD_PATH):
        if not p.exists():
            log.error("Fichier manquant : %s", p)
            sys.exit(1)

    log.info("Chargement des données...")
    strates    = load_strates()
    ocad_rgb   = load_ocad_rgb()
    ocad_masks = build_ocad_masks(ocad_rgb, strates.h, strates.w)

    # Cache partagé des strates lissées (sigma_m → smoothed array)
    smooth_cache: dict[float, np.ndarray] = {}

    # Vérification des zones
    log.info("Zones :")
    for zk, z in ZONES.items():
        sl = zone_slice(z, strates.transform, strates.h, strates.w)
        r0, r1, c0, c1 = sl
        n = (r1 - r0) * (c1 - c0)
        ref_veg = sum(ocad_masks[f"veg_{c}"][r0:r1, c0:c1].astype(int) for c in [406, 408, 410])
        pct_veg = 100 * ref_veg.sum() / n
        pct_unk = 100 * ocad_masks["unknown"][r0:r1, c0:c1].sum() / n
        pct_bla = 100 * ocad_masks["blanc"][r0:r1, c0:c1].sum() / n
        log.info("  %-6s %d×%d=%d px | OCAD veg=%.1f%% blanc=%.1f%% inconnu=%.1f%%",
                 zk, c1-c0, r1-r0, n, pct_veg, pct_bla, pct_unk)

    # ── Témoins ───────────────────────────────────────────────────────────────
    log.info("Calcul des témoins...")
    witnesses_ext = [{**w} for w in WITNESSES]
    for w in witnesses_ext:
        sl_cal = zone_slice(ZONES["cal"], strates.transform, strates.h, strates.w)
        sl_val = zone_slice(ZONES["val"], strates.transform, strates.h, strates.w)
        sl_ctrl = zone_slice(ZONES["ctrl"], strates.transform, strates.h, strates.w)
        sigma = w["sigma_m"]
        if sigma not in smooth_cache:
            smooth_cache[sigma] = apply_gaussian(strates.arr, sigma)
        ndvd = compute_ndvd(smooth_cache[sigma], w["w_low"], w["w_med"], w["w_high"])
        pred = classify_ndvd(ndvd, w["t406"], w["t408"], w["t410"])
        w["cal"]  = compute_zone_metrics(pred, ocad_masks, sl_cal).to_dict()
        w["val"]  = compute_zone_metrics(pred, ocad_masks, sl_val).to_dict()
        w["ctrl"] = compute_zone_metrics(pred, ocad_masks, sl_ctrl).to_dict()
        w["phase"] = "témoin"
        journal_append({**w, "config_id": 0})
        log.info("  %-25s : cal=%.3f val=%.3f ctrl=%.3f",
                 w["name"], w["cal"]["score"], w["val"]["score"], w["ctrl"]["score"])

    # ── Phase 1 ───────────────────────────────────────────────────────────────
    p1_sorted = phase1(strates, ocad_masks)
    best_p1   = p1_sorted[0]

    # ── Phase 2 ───────────────────────────────────────────────────────────────
    p2_sorted = phase2(strates, ocad_masks, p1_sorted)
    best_p2   = p2_sorted[0]
    gain_p2   = best_p2["val"]["score"] - best_p1["val"]["score"]

    if gain_p2 >= PLATEAU_DELTA:
        best_sigma  = best_p2["sigma_m"]
        best_after2 = best_p2
        log.info("Phase 2 : gain significatif (%.4f) → sigma_m=%.1f retenu", gain_p2, best_sigma)
    else:
        best_sigma  = 1.0
        best_after2 = best_p1
        log.info("Phase 2 : gain négligeable (%.4f) → sigma_m=1.0 (baseline) conservé", gain_p2)

    # ── Phase 2b ──────────────────────────────────────────────────────────────
    best_thresh = {k: best_after2[k] for k in ("t406", "t408", "t410")}
    p2b_sorted  = phase2b(strates, ocad_masks, best_sigma, best_thresh)
    best_p2b    = p2b_sorted[0]
    gain_p2b    = best_p2b["val"]["score"] - best_after2["val"]["score"]

    # ── Phase 2c : seuils avec meilleurs poids+sigma (Phase 2b) ──────────────
    # La Phase 2b a figé les seuils à ceux de P1 ; on les ré-explore avec le
    # meilleur signal (poids+sigma) pour chercher la combinaison optimale.
    best_w = {k: best_p2b[k] for k in ("w_low", "w_med", "w_high")}
    id_offset_2c = len(p1_sorted) + len(p2_sorted) + len(p2b_sorted)
    p2c_sorted = phase2c(strates, ocad_masks, best_sigma, best_w, id_offset=id_offset_2c)
    best_p2c   = p2c_sorted[0]
    gain_p2c   = best_p2c["val"]["score"] - best_p2b["val"]["score"]
    log.info("Phase 2c : best val=%.4f (gain=%.4f vs P2b)", best_p2c["val"]["score"], gain_p2c)

    # ── Sélection candidat final ──────────────────────────────────────────────
    all_results = p1_sorted + p2_sorted + p2b_sorted + p2c_sorted
    best_final  = max(all_results, key=lambda r: r["val"]["score"])

    log.info(
        "Candidat final : phase=%s val=%.4f "
        "σ=%.1f t406=%.2f t408=%.2f t410=%.2f w=(%.2f,%.2f,%.2f)",
        best_final.get("phase", "?"), best_final["val"]["score"],
        best_final["sigma_m"], best_final["t406"], best_final["t408"], best_final["t410"],
        best_final["w_low"], best_final["w_med"], best_final["w_high"],
    )

    # ── Figures calibration ───────────────────────────────────────────────────
    # Top-5 Phase 1 sur Cal
    top5_cfgs = p1_sorted[:5]
    for cfg in top5_cfgs:
        cfg.setdefault("name", f"p1_{cfg['config_id']}")
    build_comparison_figure(
        strates, ocad_rgb, ocad_masks,
        [witnesses_ext[0], witnesses_ext[1]] + top5_cfgs[:3],
        "cal", "top5_phase1_cal.png",
        "Top-3 P1 vs témoins", smooth_cache,
    )

    # Comparaison best P1 / best P2 / best final sur Val
    cfgs_val = [witnesses_ext[0], witnesses_ext[1], best_p1, best_p2, best_final]
    seen_ids = set()
    cfgs_val_dedup = []
    for c in cfgs_val:
        cid = (c.get("phase"), c.get("config_id"))
        if cid not in seen_ids:
            seen_ids.add(cid)
            c.setdefault("name", f"p{c.get('phase','?')}_{c.get('config_id','?')}")
            cfgs_val_dedup.append(c)
    build_comparison_figure(
        strates, ocad_rgb, ocad_masks,
        cfgs_val_dedup,
        "val", "evolution_phases_val.png",
        "Évolution témoin→P1→P2→final sur Val (vierge)", smooth_cache,
    )

    # Vue d'ensemble
    build_zone_overview(strates, ocad_rgb, best_final, smooth_cache)

    # ── Contrôle final (zone Ctrl-NW, non consultée) ─────────────────────────
    log.info("=" * 70)
    log.info("CONTRÔLE FINAL — Ctrl-NW (vierge, non consultée pendant calibration)")
    log.info("  Réserve : même dalle bois Dupont — contrôle spatial local uniquement.")
    log.info("=" * 70)

    m_ctrl = build_ctrl_figure(
        strates, ocad_rgb, ocad_masks,
        best_final, witnesses_ext, smooth_cache,
    )

    # Stocke ctrl dans best_final
    best_final["ctrl"] = m_ctrl.to_dict()

    gap_cal_val  = round(best_final["cal"]["score"] - best_final["val"]["score"], 4)
    gap_ctrl_val = round(m_ctrl.score - best_final["val"]["score"], 4)

    # ── Export palette PNG pour l'application ────────────────────────────────
    export_palette_png(strates, best_final, smooth_cache)

    # ── Sauvegarde best_config.json ───────────────────────────────────────────
    best_config_data = {
        "params": {k: best_final[k]
                   for k in ("t406", "t408", "t410", "sigma_m", "w_low", "w_med", "w_high")},
        "scores": {
            "cal_score":    best_final["cal"]["score"],
            "val_score":    best_final["val"]["score"],
            "ctrl_score":   m_ctrl.score,
            "gap_cal_val":  gap_cal_val,
            "gap_ctrl_val": gap_ctrl_val,
        },
        "metrics_val": best_final["val"],
        "metrics_ctrl": m_ctrl.to_dict(),
        "total_configs": len(all_results),
        "phase_gains": {
            "p1_vs_witness_040": round(best_p1["val"]["score"] - witnesses_ext[0]["val"]["score"], 4),
            "p2_vs_p1": round(gain_p2, 4),
            "p2b_vs_best": round(gain_p2b, 4),
            "p2c_vs_p2b": round(gain_p2c, 4),
        },
        "reproductible_depuis_laz": str(LAZ_PATH),
        "strates_source": str(STRATES_PATH),
        "crs": CRS,
        "res_m": RES_M,
    }
    bc_path = OUT_DIR / "best_config.json"
    bc_path.write_text(json.dumps(best_config_data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Best config : %s", bc_path.name)

    # ── Bilan final ───────────────────────────────────────────────────────────
    log.info("")
    log.info("═" * 70)
    log.info("BILAN CAMPAGNE CALIBRATION V2 — %s", datetime.date.today().isoformat())
    log.info("═" * 70)
    log.info("")
    log.info("Témoins :")
    for w in witnesses_ext:
        log.info("  %-25s  cal=%.3f  val=%.3f  ctrl=%.3f",
                 w["name"], w["cal"]["score"], w["val"]["score"], w["ctrl"]["score"])
    log.info("")
    log.info("Best Phase 1  : val=%.4f (t406=%.2f t408=%.2f t410=%.2f)",
             best_p1["val"]["score"], best_p1["t406"], best_p1["t408"], best_p1["t410"])
    log.info("Best Phase 2  : val=%.4f (sigma=%.1f, gain=%.4f)", best_p2["val"]["score"],
             best_p2["sigma_m"], gain_p2)
    log.info("Best Phase 2b : val=%.4f (w=%.2f,%.2f,%.2f, gain=%.4f)",
             best_p2b["val"]["score"], best_p2b["w_low"], best_p2b["w_med"],
             best_p2b["w_high"], gain_p2b)
    log.info("Best Phase 2c : val=%.4f (seuils sur meilleurs poids, gain=%.4f)",
             best_p2c["val"]["score"], gain_p2c)
    log.info("Best final    : val=%.4f", best_final["val"]["score"])
    log.info("")
    log.info("Contrôle final (Ctrl-NW) : score=%.4f  mIoU3=%.3f  IoU_pres=%.3f",
             m_ctrl.score, m_ctrl.miou3, m_ctrl.iou_presence)
    log.info("  spec_nonveg=%.3f  spec_blanc=%.3f", m_ctrl.spec_nonveg, m_ctrl.spec_blanc)
    log.info("  IoU_406=%.3f  IoU_408=%.3f  IoU_410=%.3f",
             m_ctrl.iou_406, m_ctrl.iou_408, m_ctrl.iou_410)
    log.info("")
    log.info("Cohérence Cal/Val/Ctrl :")
    log.info("  Cal−Val  = %.4f", gap_cal_val)
    log.info("  Ctrl−Val = %.4f", gap_ctrl_val)
    if gap_cal_val > 0.03:
        log.warning("  → Écart Cal−Val élevé : risque de surajustement")
    if gap_ctrl_val < -0.03:
        log.warning("  → Dégradation Ctrl vs Val : surajustement probable")
    elif abs(gap_ctrl_val) < 0.03:
        log.info("  → Cohérent entre zones. Résultat vraisemblablement généralisable sur cette dalle.")
    log.info("")
    if m_ctrl.miou3 < 0.30 and gain_p2b < PLATEAU_DELTA:
        log.info("Phase 3 (re-lecture LAZ) : envisageable (mIoU3_ctrl=%.3f faible)", m_ctrl.miou3)
        log.info("  Paramètres candidats : H_low ∈ {0.15,0.20,0.25}, H_med ∈ {1.2,1.5,2.0}")
    else:
        log.info("Phase 3 (re-lecture LAZ) : non prioritaire (mIoU3_ctrl=%.3f)", m_ctrl.miou3)
    log.info("")
    log.info("Configurations évaluées : %d", len(all_results))
    log.info("Journal : %s", JOURNAL_PATH)
    log.info("Figures : %s", FIGS_DIR)
    log.info("Export  : best_vege_calib_v2.png + .pgw")
    log.info("")


if __name__ == "__main__":
    run_campaign()
