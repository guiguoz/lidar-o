"""Entraînement supervisé — 12 configurations RF/ET.

Protocole :
  1. Charge descripteurs + labels + split
  2. Exclut pixels LABEL_NODATA ET pixels sans support LiDAR de tous les ensembles
  3. Ajuste imputation (médiane train) + modèle sur train uniquement
  4. Évalue sur train, val, test (test reporté séparément — pas de retouche après)
  5. Sélection sur val macro-IoU
  6. Sauvegarde journal, modèle retenu, best.json
  7. Compare avec témoin best_v2 NDVD (réévalué sur mêmes masques)

Données interdites dans X :
  - coordonnées X/Y absolues ou indices ligne/colonne (vérification explicite)
  - informations dérivées des labels OCAD (vérification explicite)
"""
from __future__ import annotations

import json
import logging
import pathlib
import pickle
import sys
import time
import warnings

import numpy as np
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.impute import SimpleImputer

_THIS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))

from config import (
    MODEL_GRID, RANDOM_SEED, LABEL_NODATA, N_CLASSES, CLASS_NAMES,
    MODELS_DIR, DATA_DIR, SPLIT_CFG, NDVD_BEST_CFG_PATH, DESCRIPTORS_FILE,
    GRID_H, GRID_W,
)
from descriptors import load_descriptors, FEATURE_NAMES, N_FEATURES
from labels import load_labels
from spatial_split import build_split_masks
from metrics import evaluate, print_eval, eval_to_dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

JOURNAL_FILE = MODELS_DIR / "journal.jsonl"
BEST_FILE    = MODELS_DIR / "best.json"


# ── Vérification des features : aucune coordonnée absolue ────────────────

def _assert_no_forbidden_features(feature_names: list[str]) -> None:
    forbidden = {"x", "y", "row", "col", "lon", "lat", "coord", "index", "ocad"}
    bad = [n for n in feature_names if any(f in n.lower() for f in forbidden)]
    assert not bad, f"Features interdites : {bad}"


# ── Construction du modèle sklearn ───────────────────────────────────────

def _build_clf(cfg: dict):
    kwargs = dict(
        n_estimators=cfg["n"],
        max_depth=cfg["depth"],
        min_samples_leaf=cfg["leaf"],
        class_weight=cfg["weight"],
        n_jobs=-1,
        random_state=RANDOM_SEED,
    )
    if cfg["type"] == "RF":
        return RandomForestClassifier(**kwargs)
    return ExtraTreesClassifier(**kwargs)


# ── Préparation des données ───────────────────────────────────────────────

def _prepare_split(
    X_grid: np.ndarray,       # (H, W, F)
    labels: np.ndarray,       # (H, W)
    support_grid: np.ndarray, # (H, W) bool
    mask: np.ndarray,         # (H, W) bool — bloc spatial
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Retourne (X, y, pixel_index) pour le bloc donné.

    Exclus :
      - pixels hors du bloc spatial
      - pixels avec label == LABEL_NODATA
      - pixels sans support LiDAR
    """
    # Masque d'inclusion : dans le bloc ET label évaluable ET support
    eligible = mask & (labels != LABEL_NODATA) & support_grid
    idx = np.flatnonzero(eligible)  # indices 1D dans la grille aplatie

    X_flat = X_grid.reshape(-1, N_FEATURES)
    y_flat = labels.reshape(-1)

    return X_flat[idx], y_flat[idx].astype(np.int32), idx


# ── Témoin NDVD best_v2 ───────────────────────────────────────────────────

def _ndvd_predictions(
    strates: np.ndarray,  # (4, H, W)
    cfg_ndvd: dict,
) -> np.ndarray:
    """Reproduit la prédiction best_v2 NDVD sur toute la grille."""
    sys.path.insert(0, str(_THIS.parent / "calibration_v2"))
    from run_calibration_v2 import (
        compute_ndvd, classify_ndvd, apply_gaussian, NODATA_CLS,
    )
    smooth = apply_gaussian(strates, cfg_ndvd["sigma_m"])
    signal = compute_ndvd(smooth, cfg_ndvd["w_low"], cfg_ndvd["w_med"], cfg_ndvd["w_high"])
    cls_map = classify_ndvd(signal, cfg_ndvd["t406"], cfg_ndvd["t408"], cfg_ndvd["t410"])

    # Convertit codes NDVD {0, 406, 408, 410, NODATA_CLS} → codes supervised_v1
    # {0=decouvert, 1=blanc, 2=veg_406, 3=veg_408, 4=veg_410, 255=nodata}
    pred = np.full((GRID_H, GRID_W), LABEL_NODATA, dtype=np.uint8)
    pred[cls_map == 0]        = 0   # sol/découvert
    pred[cls_map == 406]      = 2   # veg_406
    pred[cls_map == 408]      = 3   # veg_408
    pred[cls_map == 410]      = 4   # veg_410
    # NDVD ne prédit pas "blanc" (1) → les blanc OCAD seront FN veg ou FN blanc
    # NODATA_CLS → reste LABEL_NODATA
    return pred


# ── Boucle d'entraînement ─────────────────────────────────────────────────

def run_training() -> None:
    _assert_no_forbidden_features(FEATURE_NAMES)

    log.info("Chargement des données …")
    X_grid, support_grid, feat_names = load_descriptors()
    labels = load_labels()
    masks = build_split_masks()

    # Applique nodata sur cellules sans support dans les labels
    # (force exclusion pendant l'évaluation)
    labels_masked = labels.copy()
    labels_masked[~support_grid] = LABEL_NODATA

    # Données d'entraînement (train uniquement)
    X_tr, y_tr, _ = _prepare_split(X_grid, labels_masked, support_grid, masks["train"])
    X_va, y_va, _ = _prepare_split(X_grid, labels_masked, support_grid, masks["val"])
    X_te, y_te, _ = _prepare_split(X_grid, labels_masked, support_grid, masks["test"])

    log.info("Train %d px | Val %d px | Test %d px", len(y_tr), len(y_va), len(y_te))

    # Imputation médiane apprise sur le train (au cas où NaN subsistent)
    imputer = SimpleImputer(strategy="median")
    X_tr = imputer.fit_transform(X_tr)
    X_va = imputer.transform(X_va)
    X_te = imputer.transform(X_te)

    # Prédictions sur toute la grille (pour évaluation et visualisation)
    # On garde les prédictions grille entière pour chaque config candidate
    X_all = imputer.transform(X_grid.reshape(-1, N_FEATURES))

    # Chargement config NDVD témoin + strates (sauvegardées dans descriptors.npz)
    ndvd_cfg = json.loads(NDVD_BEST_CFG_PATH.read_text())["params"]
    _d = np.load(str(DESCRIPTORS_FILE))
    strates = _d["strates"]  # (4, H, W) — sauvegardé par save_descriptors()

    # ── Journal ──────────────────────────────────────────────────────────
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_FILE.unlink(missing_ok=True)

    best_macro_iou_val = -1.0
    best_cfg_id = -1
    best_pred_grid: np.ndarray | None = None

    for cfg in MODEL_GRID:
        cfg_id = cfg["id"]
        log.info("Config %2d/%d : %s n=%d depth=%s leaf=%d weight=%s",
                 cfg_id, len(MODEL_GRID), cfg["type"], cfg["n"],
                 cfg["depth"], cfg["leaf"], cfg["weight"])

        t0 = time.perf_counter()
        clf = _build_clf(cfg)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            clf.fit(X_tr, y_tr)
        t_fit = time.perf_counter() - t0

        # Prédictions sur grille complète
        pred_flat = clf.predict(X_all).astype(np.uint8)
        # Cellules sans support → LABEL_NODATA (écrase toute prédiction)
        pred_flat[~support_grid.reshape(-1)] = LABEL_NODATA
        pred_grid = pred_flat.reshape(GRID_H, GRID_W)

        # Évaluation (block_mask = restreint au bloc spatial du split)
        res_tr = evaluate(pred_grid, labels_masked, "train",
                          block_mask=masks["train"], support_grid=support_grid)
        res_va = evaluate(pred_grid, labels_masked, "val",
                          block_mask=masks["val"], support_grid=support_grid)

        log.info("  → train macro-IoU=%.4f  val macro-IoU=%.4f  (%.1fs)",
                 res_tr.macro_iou, res_va.macro_iou, t_fit)

        entry = {
            "id": cfg_id, "config": cfg,
            "t_fit_s": round(t_fit, 2),
            "train": eval_to_dict(res_tr),
            "val":   eval_to_dict(res_va),
        }
        with JOURNAL_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        # Sauvegarde du modèle
        model_path = MODELS_DIR / f"clf_{cfg_id:02d}.pkl"
        with model_path.open("wb") as f:
            pickle.dump({"clf": clf, "imputer": imputer, "feature_names": feat_names}, f)

        if res_va.macro_iou > best_macro_iou_val:
            best_macro_iou_val = res_va.macro_iou
            best_cfg_id = cfg_id
            best_pred_grid = pred_grid.copy()

    log.info("Meilleure config (val macro-IoU=%.4f) : config %d", best_macro_iou_val, best_cfg_id)

    # ── Évaluation finale sur test (consultation unique) ─────────────────
    log.info("Chargement meilleur modèle pour évaluation test …")
    best_model_path = MODELS_DIR / f"clf_{best_cfg_id:02d}.pkl"
    with best_model_path.open("rb") as f:
        saved = pickle.load(f)
    clf_best = saved["clf"]
    imputer_best = saved["imputer"]

    pred_best_flat = clf_best.predict(X_all).astype(np.uint8)
    pred_best_flat[~support_grid.reshape(-1)] = LABEL_NODATA
    pred_best_grid = pred_best_flat.reshape(GRID_H, GRID_W)

    res_tr_b = evaluate(pred_best_grid, labels_masked, "train", block_mask=masks["train"])
    res_va_b = evaluate(pred_best_grid, labels_masked, "val",   block_mask=masks["val"])
    res_te_b = evaluate(pred_best_grid, labels_masked, "test",  block_mask=masks["test"])

    for res in (res_tr_b, res_va_b, res_te_b):
        print_eval(res)

    # ── Témoin NDVD ───────────────────────────────────────────────────────
    log.info("Évaluation témoin NDVD best_v2 …")
    pred_ndvd = _ndvd_predictions(strates, ndvd_cfg)
    res_tr_nd = evaluate(pred_ndvd, labels_masked, "train_ndvd", block_mask=masks["train"])
    res_va_nd = evaluate(pred_ndvd, labels_masked, "val_ndvd",   block_mask=masks["val"])
    res_te_nd = evaluate(pred_ndvd, labels_masked, "test_ndvd",  block_mask=masks["test"])
    for res in (res_tr_nd, res_va_nd, res_te_nd):
        print_eval(res)

    # ── Tableau comparatif ────────────────────────────────────────────────
    print("\n=== TABLEAU COMPARATIF ===")
    print(f"{'':34} {'train':>7} {'val':>7} {'test':>7}")
    for label_m, r_tr, r_va, r_te in [
        ("NDVD best_v2  macro-IoU", res_tr_nd, res_va_nd, res_te_nd),
        (f"RF_v1 cfg{best_cfg_id:02d}  macro-IoU", res_tr_b, res_va_b, res_te_b),
        ("NDVD         IoU_pres",  res_tr_nd, res_va_nd, res_te_nd),
        (f"RF_v1        IoU_pres",  res_tr_b, res_va_b, res_te_b),
    ]:
        attr = "macro_iou" if "macro" in label_m else "iou_presence"
        print(f"  {label_m:30}  {getattr(r_tr, attr):.4f}  {getattr(r_va, attr):.4f}  {getattr(r_te, attr):.4f}")
    print("=" * 48)

    # ── Sauvegarde best.json ──────────────────────────────────────────────
    best_record = {
        "best_cfg_id": best_cfg_id,
        "best_cfg": MODEL_GRID[best_cfg_id - 1],
        "feature_names": feat_names,
        "train": eval_to_dict(res_tr_b),
        "val":   eval_to_dict(res_va_b),
        "test":  eval_to_dict(res_te_b),
        "ndvd_train": eval_to_dict(res_tr_nd),
        "ndvd_val":   eval_to_dict(res_va_nd),
        "ndvd_test":  eval_to_dict(res_te_nd),
    }
    BEST_FILE.write_text(json.dumps(best_record, indent=2))
    log.info("Résultats : %s", BEST_FILE)

    # Sauvegarde prediction grid du meilleur modèle
    pred_path = MODELS_DIR / "pred_best.npy"
    np.save(str(pred_path), pred_best_grid)
    pred_ndvd_path = MODELS_DIR / "pred_ndvd.npy"
    np.save(str(pred_ndvd_path), pred_ndvd)
    log.info("Prédictions sauvegardées : %s, %s", pred_path.name, pred_ndvd_path.name)

    # Importance des variables (diagnostic uniquement)
    if hasattr(clf_best, "feature_importances_"):
        fi = clf_best.feature_importances_
        top_idx = np.argsort(fi)[::-1][:10]
        print("\n-- Importance des variables (top 10, diagnostic) --")
        for rank, i in enumerate(top_idx):
            print(f"  {rank+1:2d}. {feat_names[i]:25}  {fi[i]:.4f}")
        # Sauvegarde
        fi_path = MODELS_DIR / "feature_importance.json"
        fi_path.write_text(json.dumps(
            {feat_names[i]: round(float(fi[i]), 6) for i in np.argsort(fi)[::-1]},
            indent=2,
        ))


if __name__ == "__main__":
    run_training()
