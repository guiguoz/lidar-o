"""4-fold LOTO pipeline — branche E (descripteurs enrichis T+E = 63 features).

Protocole identique à loto_pipeline.py (terrains, masques, anti-leak, sampling).
Seul changement : X = [X_T (30) ‖ X_E (33)] = 63 features.
Configuration unique : RF_leaf5 (n=300, depth=20, leaf=5, balanced).

Sorties :
  loto_v1/results_e/metrics_e.json
  loto_v1/results_e/summary_e.csv
  loto_v1/results_e/models/<fold>_E_RF_leaf5.pkl

Commande :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/loto_pipeline_e.py
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import pathlib
import pickle
import subprocess
import sys

import numpy as np
from sklearn.impute import SimpleImputer

_THIS = pathlib.Path(__file__).resolve().parent
_ROOT = _THIS.parents[1]
_BD_SV1 = _ROOT / "experiments" / "bois_dupont" / "supervised_v1"
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_BD_SV1))
sys.path.insert(0, str(_THIS))

from loto_pipeline import (          # noqa: E402
    load_bd, load_caen, load_montmirel, load_sainte_anne,
    build_clf, assemble_train, compute_metrics,
    DATA_DIR, RESULTS_DIR,
    NODATA_CODE, RANDOM_SEED, MAX_TRAIN_PX_PER_TERRAIN,
)
from descriptors import N_FEATURES as N_FEATURES_T         # noqa: E402
from descriptors_ext import (        # noqa: E402
    build_ext_descriptors, N_EXT_FEATURES, load_ext_strates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RESULTS_E_DIR = _THIS / "results_e"
RESULTS_E_DIR.mkdir(parents=True, exist_ok=True)
(RESULTS_E_DIR / "models").mkdir(exist_ok=True)

N_FEATURES_E: int = N_FEATURES_T + N_EXT_FEATURES  # 30 + 33 = 63

CFG_E = {
    "id": "E_RF_leaf5",
    "type": "RF",
    "n": 300,
    "depth": 20,
    "leaf": 5,
    "weight": "balanced",
}


# ── Chargement descripteurs E ─────────────────────────────────────────────

def _load_or_cache_ext(name: str) -> tuple[np.ndarray, np.ndarray]:
    """Retourne X_ext (H,W,33) et support_ext (H,W) depuis cache ou calcul."""
    cache = DATA_DIR / f"{name}_descriptors_ext.npz"
    if cache.exists():
        log.info("%s : descripteurs E depuis cache", name)
        d = np.load(str(cache))
        return d["X_ext"], d["support_ext"].astype(bool)

    strates_path = DATA_DIR / f"{name}_strates_ext.npz"
    if not strates_path.exists():
        raise FileNotFoundError(
            f"{name} : strates_ext manquant — lancer compute_ext_strates.py d'abord.\n"
            f"  Attendu : {strates_path}"
        )
    log.info("%s : calcul descripteurs E depuis %s...", name, strates_path.name)
    strates_ext = load_ext_strates(strates_path)
    X_ext, support_ext = build_ext_descriptors(strates_ext)
    np.savez_compressed(str(cache), X_ext=X_ext, support_ext=support_ext)
    log.info("%s : descripteurs E mis en cache %s", name, cache.name)
    return X_ext, support_ext.astype(bool)


def augment_terrain(name: str, td_t: dict) -> dict:
    """Ajoute X_ext au dict terrain T, retourne un nouveau dict avec X_grid (H,W,63)."""
    X_ext, support_ext = _load_or_cache_ext(name)

    H, W = td_t["h"], td_t["w"]
    assert X_ext.shape[:2] == (H, W), (
        f"{name} : forme X_ext {X_ext.shape} ≠ attendu ({H},{W})"
    )

    support_combined = td_t["support"] & support_ext

    X_full = np.concatenate([td_t["X_grid"], X_ext], axis=-1)   # (H,W,63)
    assert X_full.shape == (H, W, N_FEATURES_E), X_full.shape

    n_lost = int(td_t["support"].sum()) - int(support_combined.sum())
    if n_lost:
        log.info("%s : %d px support T perdus (absent dans E)", name, n_lost)

    log.info("%s : X_full=%s support=%d", name, X_full.shape, support_combined.sum())

    return {
        **td_t,
        "X_grid":  X_full,
        "support": support_combined,
    }


# ── LOTO E ────────────────────────────────────────────────────────────────

def run_fold_e(fold_test: str, terrains: dict) -> tuple[dict, np.ndarray]:
    log.info("── Fold=%-12s  Config=%s ──", fold_test, CFG_E["id"])

    X_train, y_train = assemble_train(fold_test, terrains)

    imputer = SimpleImputer(strategy="mean")
    X_tr_imp = imputer.fit_transform(X_train)

    clf = build_clf(CFG_E)
    clf.fit(X_tr_imp, y_train)
    log.info("  Modèle E entraîné  (n_train=%d)", len(X_tr_imp))

    td = terrains[fold_test]
    h, w    = td["h"], td["w"]
    support = td["support"]
    X_all   = td["X_grid"].reshape(-1, N_FEATURES_E)
    X_all_imp = imputer.transform(X_all)
    pred_flat = clf.predict(X_all_imp).astype(np.uint8)
    pred_flat[~support.reshape(-1)] = NODATA_CODE
    pred = pred_flat.reshape(h, w)

    metrics = compute_metrics(pred, td, fold_test)
    metrics["config"] = CFG_E["id"]

    log.info("  macro-IoU-veg=%.3f  IoU-prés-veg=%.3f  eval_px=%d  FP-unk=%d",
             metrics["macro_veg"], metrics["iou_veg"],
             metrics["eval_px"], metrics["n_fp_unknown"])

    pkl = RESULTS_E_DIR / "models" / f"{fold_test}_{CFG_E['id']}.pkl"
    with pkl.open("wb") as f:
        pickle.dump({"clf": clf, "imputer": imputer, "fold": fold_test,
                     "cfg": CFG_E, "metrics": metrics}, f)

    return metrics, pred


# ── Summary ───────────────────────────────────────────────────────────────

def print_and_save_summary_e(all_metrics: list[dict]) -> None:
    sep = "=" * 76
    lines = [sep,
             "RÉSULTATS LOTO E — 4 folds  (RF_leaf5, 63 features T+E)",
             sep,
             f"  {'Fold':>12s}  {'Config':>13s}  {'mIoU-veg':>9s}  "
             f"{'IoU-prés':>9s}  {'Prec-veg':>9s}  {'Rec-veg':>8s}"]
    for m in all_metrics:
        lines.append(
            f"  {m['fold']:>12s}  {m['config']:>13s}  "
            f"{m['macro_veg']:>9.3f}  {m['iou_veg']:>9.3f}  "
            f"{m['prec_veg']:>9.3f}  {m['rec_veg']:>8.3f}"
        )

    rows = all_metrics
    avg_veg  = float(np.mean([r["macro_veg"] for r in rows]))
    avg_pres = float(np.mean([r["iou_veg"]   for r in rows]))
    lines.append(f"\nMoyenne (4 folds) : macro-IoU-veg={avg_veg:.3f}  IoU-prés={avg_pres:.3f}")

    summary_txt = "\n".join(lines)
    print("\n" + summary_txt)

    csv_path = RESULTS_E_DIR / "summary_e.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("fold,config,macro_iou_veg,iou_veg_pres,prec_veg,rec_veg,macro_iou_all\n")
        for m in all_metrics:
            f.write(f"{m['fold']},{m['config']},"
                    f"{m['macro_veg']:.5f},{m['iou_veg']:.5f},"
                    f"{m['prec_veg']:.5f},{m['rec_veg']:.5f},"
                    f"{m['macro_all']:.5f}\n")
    log.info("CSV sauvegardé : %s", csv_path)


# ── Main ──────────────────────────────────────────────────────────────────

def _load_all_terrains_e() -> dict:
    log.info("=== LOTO E — chargement terrains T ===")
    terrains_t = {
        "bd":          load_bd(),
        "caen":        load_caen(),
        "montmirel":   load_montmirel(),
        "sainte_anne": load_sainte_anne(),
    }
    log.info("=== LOTO E — augmentation descripteurs E ===")
    return {name: augment_terrain(name, td) for name, td in terrains_t.items()}


def main() -> None:
    terrains = _load_all_terrains_e()
    all_metrics: list[dict] = []

    for fold_test in terrains:
        pkl = RESULTS_E_DIR / "models" / f"{fold_test}_{CFG_E['id']}.pkl"
        if pkl.exists():
            with pkl.open("rb") as f:
                saved = pickle.load(f)
            metrics = saved["metrics"]
            metrics.setdefault("config", CFG_E["id"])
            log.info("── Fold=%-12s  Config=%s  [cache] ──", fold_test, CFG_E["id"])
            log.info("  macro-IoU-veg=%.3f  IoU-prés-veg=%.3f  eval_px=%d  FP-unk=%d",
                     metrics["macro_veg"], metrics["iou_veg"],
                     metrics["eval_px"], metrics["n_fp_unknown"])
        else:
            log.info("── Fold=%-12s  Config=%s  [subprocess] ──", fold_test, CFG_E["id"])
            env = {**__import__("os").environ, "PYTHONUTF8": "1"}
            subprocess.run(
                [sys.executable, str(__file__), "--fold", fold_test],
                check=True, env=env,
            )
            with pkl.open("rb") as f:
                saved = pickle.load(f)
            metrics = saved["metrics"]
            metrics.setdefault("config", CFG_E["id"])
            log.info("  macro-IoU-veg=%.3f  IoU-prés-veg=%.3f  eval_px=%d  FP-unk=%d",
                     metrics["macro_veg"], metrics["iou_veg"],
                     metrics["eval_px"], metrics["n_fp_unknown"])

        all_metrics.append(metrics)
        gc.collect()

    metrics_path = RESULTS_E_DIR / "metrics_e.json"
    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2, ensure_ascii=False)
    log.info("Métriques JSON : %s", metrics_path)

    print_and_save_summary_e(all_metrics)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fold", default=None, help="Single fold (subprocess mode)")
    args = parser.parse_args()

    if args.fold:
        terrains = _load_all_terrains_e()
        run_fold_e(args.fold, terrains)
    else:
        main()
