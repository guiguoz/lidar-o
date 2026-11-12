"""4-fold LOTO pipeline — généralisation du moteur A4.

Terrains :
  bd          — Bois Dupont (500×500 px, EPSG:2154)
  caen        — Forêt de Caen, zone éval (500×1000 px)
  montmirel   — Bois de Montmirel (1500×1500 px)
  sainte_anne — Route de Sainte-Anne (1500×1500 px)

3 configurations :
  RF_leaf5  : RF n=300, depth=20, leaf=5,  weight="balanced"  (≡ clf_A4)
  RF_leaf10 : RF n=300, depth=20, leaf=10, weight="balanced"
  ET_leaf5  : ExtraTrees n=300, depth=None, leaf=5, weight="balanced"

4 folds × 3 configs = 12 runs.

Marge anti-leak = 6 px = 12 m (rayon descripteur max).
SA↔Caen overlap :
  fold SA=test   : exclure rows 1000-1500 / cols 500-1500 de l'éval SA
  fold Caen=test : exclure rows 994-1500  / cols 494-1500 du train SA (+6px buffer)

Sorties :
  loto_v1/results/metrics.json
  loto_v1/results/summary.csv
  loto_v1/results/models/<fold>_<cfg>.pkl

Commande :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/loto_pipeline.py
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
import rasterio
from PIL import Image
from scipy.ndimage import binary_dilation
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.impute import SimpleImputer

_THIS = pathlib.Path(__file__).resolve().parent
_ROOT = _THIS.parents[1]
_BD_SV1 = _ROOT / "experiments" / "bois_dupont" / "supervised_v1"
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_BD_SV1))

from descriptors import build_descriptors, N_FEATURES   # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Directories ───────────────────────────────────────────────────────────
DATA_DIR    = _THIS / "data"
RESULTS_DIR = _THIS / "results"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────────
CLASS_NAMES = ["decouvert", "blanc", "veg_406", "veg_408", "veg_410"]
VEG_CLASSES = [2, 3, 4]
NODATA_CODE = 255
N_CLASSES   = 5
BORDER_PX   = 6   # rayon descripteur max = 2.0 × 3.0 px = 6 px = 12 m

OCAD_TO_CLASS: dict[tuple[int,int,int], int] = {
    (255, 201,  15): 0,
    (255, 255, 255): 1,
    (204, 255, 179): 2,
    (153, 255, 102): 3,
    ( 51, 255,   0): 4,
}
OCAD_EXCLUDE: set[tuple[int,int,int]] = {(255, 0, 0), (25, 25, 25)}

CONFIGS = [
    {"id": "RF_leaf5",  "type": "RF", "n": 300, "depth": 20,   "leaf": 5,  "weight": "balanced"},
    {"id": "RF_leaf10", "type": "RF", "n": 300, "depth": 20,   "leaf": 10, "weight": "balanced"},
    {"id": "ET_leaf5",  "type": "ET", "n": 300, "depth": None, "leaf": 5,  "weight": "balanced"},
]

RANDOM_SEED = 42

# Sous-échantillonnage par terrain : cap à 300K px pour maîtriser le temps de calcul.
# La RF d'origine (clf_A4) a été entraînée sur ~750K px (BD+Caen) → 900K total par fold
# est dans le même ordre de grandeur.  Seed fixe → reproductible.
MAX_TRAIN_PX_PER_TERRAIN = 300_000

# ── OCAD helpers ──────────────────────────────────────────────────────────

def build_ref_cat(ocad_rgb: np.ndarray) -> np.ndarray:
    """RGB (H,W,3) uint8 → ref_cat (H,W) int8 : 0-4 classes, -1 exclu, -2 inconnu."""
    result = np.full(ocad_rgb.shape[:2], -2, dtype=np.int8)
    for color, cat in OCAD_TO_CLASS.items():
        result[np.all(ocad_rgb == color, axis=2)] = cat
    for color in OCAD_EXCLUDE:
        result[np.all(ocad_rgb == color, axis=2)] = -1
    return result


def partial_ctx_from_support(support: np.ndarray) -> np.ndarray:
    """True où support==True mais à ≤BORDER_PX px d'un pixel NODATA."""
    nodata = ~support
    return binary_dilation(nodata, structure=np.ones((3, 3)), iterations=BORDER_PX) & support


# ── Terrain data loading ───────────────────────────────────────────────────

def _load_or_cache_descriptors(name: str, strates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cache = DATA_DIR / f"{name}_descriptors.npz"
    if cache.exists():
        log.info("%s : descripteurs depuis cache", name)
        d = np.load(str(cache))
        return d["X_grid"], d["support_grid"].astype(bool)
    log.info("%s : calcul descripteurs %dx%d...", name, strates.shape[1], strates.shape[2])
    X_grid, support_grid = build_descriptors(strates)
    np.savez_compressed(str(cache), X_grid=X_grid, support_grid=support_grid)
    log.info("%s : descripteurs mis en cache %s", name, cache.name)
    return X_grid, support_grid.astype(bool)


def load_bd() -> dict:
    """Bois Dupont : charge descripteurs existants + ref_cat depuis OCAD PNG."""
    npz_path = _ROOT / "experiments/bois_dupont/supervised_v1/data/descriptors.npz"
    d = np.load(str(npz_path))
    X_grid  = d["X_grid"]                   # (500,500,30)
    support = d["support_grid"].astype(bool)  # (500,500)

    ocad_path = pathlib.Path(
        r"E:\RunningRaid\Cartographie\ça te dit 2027\bois Dupont"
        r"\LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc_VegetationBaseMap.png"
    )
    ocad_rgb = np.array(Image.open(str(ocad_path)).convert("RGB"))
    ref_cat  = build_ref_cat(ocad_rgb)       # (500,500)
    partial_ctx = partial_ctx_from_support(support)

    log.info("BD : X=%s support=%d ref_valid=%d", X_grid.shape,
             support.sum(), int((ref_cat >= 0).sum()))
    return {"X_grid": X_grid, "support": support, "ref_cat": ref_cat,
            "partial_ctx": partial_ctx, "h": 500, "w": 500, "caen_overlap": None}


def load_caen() -> dict:
    """Forêt de Caen : zone éval (500×1000) avec partial_ctx correct sur grille complète."""
    caen_npz = _ROOT / "experiments/multi_terrain_v1/data/caen_descriptors.npz"
    d = np.load(str(caen_npz))
    X_eval       = d["X_eval"]                   # (500,1000,30)
    support_eval = d["support_eval"].astype(bool)  # (500,1000)

    # Reconstruire support_full (1000×1000) pour partial_ctx correct au bord nord
    # Rows 0-500 : zones NODATA (pas de données LiDAR → False)
    # Rows 500-1000 : zone d'évaluation → support_eval
    support_full = np.zeros((1000, 1000), dtype=bool)
    support_full[500:1000, :] = support_eval
    partial_ctx_full = partial_ctx_from_support(support_full)
    partial_ctx = partial_ctx_full[500:1000, :]   # (500,1000) extrait

    # Ref OCAD : OCAD TIF rows 0-500 = Y=[6888000,6889000] = zone eval
    caen_ocad = _ROOT / "travail_caen" / "ocad_auto_vegetation.tif"
    with rasterio.open(str(caen_ocad)) as src:
        rgb_full = src.read()[:3]   # (3,1000,1000)
    ocad_rgb = rgb_full[:, :500, :].transpose(1, 2, 0).astype(np.uint8)  # (500,1000,3)
    ref_cat  = build_ref_cat(ocad_rgb)   # (500,1000)

    log.info("Caen : X=%s support=%d ref_valid=%d", X_eval.shape,
             support_eval.sum(), int((ref_cat >= 0).sum()))
    return {"X_grid": X_eval, "support": support_eval, "ref_cat": ref_cat,
            "partial_ctx": partial_ctx, "h": 500, "w": 1000, "caen_overlap": None}


def _load_from_strates(name: str, strates_tif: pathlib.Path,
                        ocad_png: pathlib.Path, h_exp: int, w_exp: int) -> dict:
    with rasterio.open(str(strates_tif)) as src:
        strates = src.read().astype(np.float32)   # (4,H,W)
    assert strates.shape == (4, h_exp, w_exp), f"{name} strates: {strates.shape}"

    X_grid, support = _load_or_cache_descriptors(name, strates)
    partial_ctx = partial_ctx_from_support(support)

    ocad_rgb = np.array(Image.open(str(ocad_png)).convert("RGB"))
    assert ocad_rgb.shape[:2] == (h_exp, w_exp), f"{name} OCAD shape: {ocad_rgb.shape}"
    ref_cat = build_ref_cat(ocad_rgb)

    log.info("%s : X=%s support=%d ref_valid=%d", name, X_grid.shape,
             support.sum(), int((ref_cat >= 0).sum()))
    return {"X_grid": X_grid, "support": support, "ref_cat": ref_cat,
            "partial_ctx": partial_ctx, "h": h_exp, "w": w_exp, "caen_overlap": None}


def load_montmirel() -> dict:
    return _load_from_strates(
        "montmirel",
        _ROOT / "experiments/montmirel/output/omapmaker_strates.tif",
        _ROOT / "bois de montmirel/Sans titre_VegetationBaseMap.png",
        1500, 1500,
    )


def load_sainte_anne() -> dict:
    d = _load_from_strates(
        "sainte_anne",
        _ROOT / "experiments/sainte_anne/output/omapmaker_strates.tif",
        _ROOT / "la route de sainte anne/Sans titre_VegetationBaseMap.png",
        1500, 1500,
    )
    # Overlap SA↔Caen : rows 1000-1500, cols 500-1500 dans l'espace SA
    d["caen_overlap"] = (1000, 1500, 500, 1500)
    return d


# ── Classifier ────────────────────────────────────────────────────────────

def build_clf(cfg: dict):
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
    elif cfg["type"] == "ET":
        return ExtraTreesClassifier(**kwargs)
    raise ValueError(f"type inconnu : {cfg['type']}")


# ── Training data ─────────────────────────────────────────────────────────

def assemble_train(fold_test: str, terrains: dict) -> tuple[np.ndarray, np.ndarray]:
    """Concatène les pixels d'entraînement des 3 terrains hors test."""
    X_parts, y_parts = [], []

    for name, td in terrains.items():
        if name == fold_test:
            continue

        # Masque de base : support & ~partial_ctx & classe connue
        mask = td["support"] & ~td["partial_ctx"] & (td["ref_cat"] >= 0)

        # Anti-leak : fold Caen=test → exclure de SA la zone qui recouvre Caen
        # (rows 1000-1499, cols 494-1499) = zone Caen + 6px buffer dans l'espace SA
        if fold_test == "caen" and name == "sainte_anne":
            leak = np.zeros(mask.shape, dtype=bool)
            leak[994:, 494:] = True
            mask &= ~leak

        X_flat = td["X_grid"][mask]
        y_flat = td["ref_cat"][mask].astype(np.uint8)

        # Sous-échantillonnage si terrain trop grand
        if len(X_flat) > MAX_TRAIN_PX_PER_TERRAIN:
            rng = np.random.default_rng(RANDOM_SEED)
            idx = rng.choice(len(X_flat), MAX_TRAIN_PX_PER_TERRAIN, replace=False)
            X_flat = X_flat[idx]
            y_flat = y_flat[idx]

        X_parts.append(X_flat)
        y_parts.append(y_flat)

    X_train = np.concatenate(X_parts, axis=0)
    y_train = np.concatenate(y_parts, axis=0)
    log.info("fold=%s train=%d px (%s)", fold_test, len(X_train),
             "+".join(str(len(p)) for p in X_parts))
    return X_train, y_train


# ── Metrics ───────────────────────────────────────────────────────────────

def compute_metrics(pred: np.ndarray, td: dict, fold_test: str) -> dict:
    """Métriques sur le terrain de test.

    Protocole cohérent avec eval_a4.py :
      - support==0, partial_ctx, rouge/bâti : exclus
      - SA↔Caen overlap exclu si fold_test=='sainte_anne'
      - Prédictions sur ref_cat==-2 (inconnu OCAD) pénalisées comme FP
    """
    support = td["support"]
    ref_cat = td["ref_cat"]
    partial = td["partial_ctx"]
    h, w    = td["h"], td["w"]

    exclude = ~support | partial | (ref_cat == -1)

    if fold_test == "sainte_anne" and td["caen_overlap"] is not None:
        r0, r1, c0, c1 = td["caen_overlap"]
        caen_m = np.zeros((h, w), bool)
        caen_m[r0:r1, c0:c1] = True
        exclude |= caen_m

    evaluable   = ~exclude & (ref_cat >= 0)
    unknown_ref = ~exclude & (ref_cat == -2) & support

    # FP additionnels depuis pixels OCAD inconnus
    pred_unk = pred[unknown_ref & (pred != NODATA_CODE)]
    fp_unk   = np.bincount(pred_unk.astype(np.int64).clip(0, N_CLASSES-1),
                            minlength=N_CLASSES)
    n_fp_unk = int(fp_unk.sum())

    pred_e = pred[evaluable].astype(np.int32)
    ref_e  = ref_cat[evaluable].astype(np.int32)

    abs_mask   = pred_e == NODATA_CODE
    pred_clean = pred_e[~abs_mask]
    ref_clean  = ref_e[~abs_mask]

    conf = np.zeros((N_CLASSES, N_CLASSES), dtype=np.int64)
    for r in range(N_CLASSES):
        for c in range(N_CLASSES):
            conf[r, c] = int(((ref_clean == r) & (pred_clean == c)).sum())

    abs_by_cls = (np.bincount(ref_e[abs_mask].clip(0, N_CLASSES-1), minlength=N_CLASSES)
                  if abs_mask.any() else np.zeros(N_CLASSES, int))

    ious: dict[str, float] = {}
    precs: dict[str, float] = {}
    recs: dict[str, float] = {}
    for ci, cn in enumerate(CLASS_NAMES):
        tp   = int(conf[ci, ci])
        fn   = int(conf[ci, :].sum() - tp + abs_by_cls[ci])
        fp   = int(conf[:, ci].sum() - tp + fp_unk[ci])
        denom_iou  = tp + fp + fn
        denom_prec = tp + fp
        denom_rec  = tp + fn
        ious[cn]  = tp / denom_iou  if denom_iou  > 0 else float("nan")
        precs[cn] = tp / denom_prec if denom_prec > 0 else float("nan")
        recs[cn]  = tp / denom_rec  if denom_rec  > 0 else float("nan")

    veg_ious = [ious[k] for k in ["veg_406","veg_408","veg_410"] if not np.isnan(ious[k])]
    all_ious = [v for v in ious.values() if not np.isnan(v)]

    pred_veg = np.isin(pred_clean, VEG_CLASSES)
    ref_veg  = np.isin(ref_clean,  VEG_CLASSES)
    abs_veg  = int(np.isin(ref_e[abs_mask], VEG_CLASSES).sum()) if abs_mask.any() else 0
    tp_v = int((pred_veg & ref_veg).sum())
    fp_v = int((pred_veg & ~ref_veg).sum()) + int(np.isin(pred_unk, VEG_CLASSES).sum())
    fn_v = int((~pred_veg & ref_veg).sum()) + abs_veg
    iou_v  = tp_v / (tp_v+fp_v+fn_v) if (tp_v+fp_v+fn_v) > 0 else float("nan")
    prec_v = tp_v / (tp_v+fp_v)       if (tp_v+fp_v)      > 0 else float("nan")
    rec_v  = tp_v / (tp_v+fn_v)       if (tp_v+fn_v)      > 0 else float("nan")

    return {
        "fold": fold_test,
        "conf": conf.tolist(),
        "iou":  {k: round(v, 5) for k, v in ious.items()},
        "prec": {k: round(v, 5) for k, v in precs.items()},
        "rec":  {k: round(v, 5) for k, v in recs.items()},
        "macro_veg": float(np.mean(veg_ious)) if veg_ious else float("nan"),
        "macro_all": float(np.mean(all_ious)) if all_ious else float("nan"),
        "iou_veg":  round(iou_v, 5),
        "prec_veg": round(prec_v, 5),
        "rec_veg":  round(rec_v, 5),
        "eval_px":  int(evaluable.sum()),
        "n_fp_unknown": n_fp_unk,
        "abs_px": int(abs_mask.sum()),
    }


# ── LOTO run ──────────────────────────────────────────────────────────────

def run_fold_config(fold_test: str, cfg: dict, terrains: dict) -> tuple[dict, np.ndarray]:
    log.info("── Fold=%-12s  Config=%s ──", fold_test, cfg["id"])

    X_train, y_train = assemble_train(fold_test, terrains)

    imputer = SimpleImputer(strategy="mean")
    X_tr_imp = imputer.fit_transform(X_train)

    clf = build_clf(cfg)
    clf.fit(X_tr_imp, y_train)
    log.info("  Modèle entraîné  (n_train=%d)", len(X_tr_imp))

    # Prédiction sur tout le terrain de test
    td = terrains[fold_test]
    h, w = td["h"], td["w"]
    support = td["support"]
    X_all   = td["X_grid"].reshape(-1, N_FEATURES)
    X_all_imp = imputer.transform(X_all)
    pred_flat = clf.predict(X_all_imp).astype(np.uint8)
    pred_flat[~support.reshape(-1)] = NODATA_CODE
    pred = pred_flat.reshape(h, w)

    metrics = compute_metrics(pred, td, fold_test)
    metrics["config"] = cfg["id"]

    log.info("  macro-IoU-veg=%.3f  IoU-prés-veg=%.3f  eval_px=%d  FP-unk=%d",
             metrics["macro_veg"], metrics["iou_veg"],
             metrics["eval_px"], metrics["n_fp_unknown"])

    # Sauvegarde du modèle
    model_dir = RESULTS_DIR / "models"
    model_dir.mkdir(exist_ok=True)
    pkl = model_dir / f"{fold_test}_{cfg['id']}.pkl"
    with pkl.open("wb") as f:
        pickle.dump({"clf": clf, "imputer": imputer, "fold": fold_test,
                     "cfg": cfg, "metrics": metrics}, f)

    return metrics, pred


# ── Summary ───────────────────────────────────────────────────────────────

def print_and_save_summary(all_metrics: list[dict]) -> None:
    sep = "=" * 76
    lines = [sep,
             "RÉSULTATS LOTO — 4 folds × 3 configs",
             sep,
             f"  {'Fold':>12s}  {'Config':>10s}  {'mIoU-veg':>9s}  "
             f"{'IoU-prés':>9s}  {'Prec-veg':>9s}  {'Rec-veg':>8s}"]
    for m in all_metrics:
        lines.append(
            f"  {m['fold']:>12s}  {m['config']:>10s}  "
            f"{m['macro_veg']:>9.3f}  {m['iou_veg']:>9.3f}  "
            f"{m['prec_veg']:>9.3f}  {m['rec_veg']:>8.3f}"
        )

    lines.append("\nMoyenne par config (sur 4 folds) :")
    for cfg_id in [c["id"] for c in CONFIGS]:
        rows = [m for m in all_metrics if m["config"] == cfg_id]
        avg_veg  = float(np.mean([r["macro_veg"] for r in rows]))
        avg_pres = float(np.mean([r["iou_veg"]   for r in rows]))
        lines.append(f"  {cfg_id}: macro-IoU-veg={avg_veg:.3f}  IoU-prés={avg_pres:.3f}")

    summary_txt = "\n".join(lines)
    print("\n" + summary_txt)

    # CSV
    csv_path = RESULTS_DIR / "summary.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("fold,config,macro_iou_veg,iou_veg_pres,prec_veg,rec_veg,macro_iou_all\n")
        for m in all_metrics:
            f.write(f"{m['fold']},{m['config']},"
                    f"{m['macro_veg']:.5f},{m['iou_veg']:.5f},"
                    f"{m['prec_veg']:.5f},{m['rec_veg']:.5f},"
                    f"{m['macro_all']:.5f}\n")
    log.info("CSV sauvegardé : %s", csv_path)


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== LOTO pipeline — chargement terrains ===")
    terrains = {
        "bd":          load_bd(),
        "caen":        load_caen(),
        "montmirel":   load_montmirel(),
        "sainte_anne": load_sainte_anne(),
    }

    all_metrics: list[dict] = []

    for fold_test in terrains:
        for cfg in CONFIGS:
            pkl = RESULTS_DIR / "models" / f"{fold_test}_{cfg['id']}.pkl"
            if pkl.exists():
                with pkl.open("rb") as f:
                    saved = pickle.load(f)
                metrics = saved["metrics"]
                metrics.setdefault("config", cfg["id"])
                log.info("── Fold=%-12s  Config=%s  [cache] ──", fold_test, cfg["id"])
                log.info("  macro-IoU-veg=%.3f  IoU-prés-veg=%.3f  eval_px=%d  FP-unk=%d",
                         metrics["macro_veg"], metrics["iou_veg"],
                         metrics["eval_px"], metrics["n_fp_unknown"])
            else:
                # Sous-processus isolé : mémoire propre après chaque ET_leaf5 (~2 Go)
                log.info("── Fold=%-12s  Config=%s  [subprocess] ──", fold_test, cfg["id"])
                env = {**__import__("os").environ, "PYTHONUTF8": "1"}
                subprocess.run(
                    [sys.executable, str(__file__), "--fold", fold_test, "--cfg", cfg["id"]],
                    check=True, env=env,
                )
                with pkl.open("rb") as f:
                    saved = pickle.load(f)
                metrics = saved["metrics"]
                metrics.setdefault("config", cfg["id"])
                log.info("  macro-IoU-veg=%.3f  IoU-prés-veg=%.3f  eval_px=%d  FP-unk=%d",
                         metrics["macro_veg"], metrics["iou_veg"],
                         metrics["eval_px"], metrics["n_fp_unknown"])
            all_metrics.append(metrics)
            gc.collect()

    # Métriques JSON
    metrics_path = RESULTS_DIR / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2, ensure_ascii=False)
    log.info("Métriques JSON : %s", metrics_path)

    print_and_save_summary(all_metrics)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fold", default=None, help="Single fold (subprocess mode)")
    parser.add_argument("--cfg",  default=None, help="Single config id (subprocess mode)")
    args = parser.parse_args()

    if args.fold and args.cfg:
        # Mode subprocess : charge tous les terrains, entraîne un seul run, sauvegarde pkl
        terrains = {
            "bd":          load_bd(),
            "caen":        load_caen(),
            "montmirel":   load_montmirel(),
            "sainte_anne": load_sainte_anne(),
        }
        cfg = next(c for c in CONFIGS if c["id"] == args.cfg)
        run_fold_config(args.fold, cfg, terrains)
    else:
        main()
