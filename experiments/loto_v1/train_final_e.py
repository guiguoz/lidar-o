"""Entraîne le modèle E final sur les 4 terrains LOTO.

Utilise tous les pixels étiquetés des 4 terrains, après :
  - exclusions de qualité (partial_ctx, classe inconnue)
  - déduplication géographique SA↔Caen (zone commune → Caen prioritaire)
  - sous-échantillonnage uniforme par terrain si > MAX_TRAIN_PX_PER_TERRAIN

Produit dans experiments/loto_v1/final_model/ :
  model_e_final.pkl   — clf + imputer + config + categories
  manifeste.json       — sources, effectifs par terrain/classe, SHA-256
  method_e_spec.yaml   — copie de la spec figée

Les performances sur ces terrains sont des résultats de réemploi.
Les scores LOTO (results_e/metrics_e.json) restent la référence externe.

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/train_final_e.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import pickle
import shutil
import sys

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer

_THIS = pathlib.Path(__file__).resolve().parent
_ROOT = _THIS.parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "experiments/bois_dupont/supervised_v1"))
sys.path.insert(0, str(_THIS))

from loto_pipeline import (  # noqa: E402
    load_bd, load_caen, load_montmirel, load_sainte_anne,
    RANDOM_SEED, MAX_TRAIN_PX_PER_TERRAIN, N_FEATURES, NODATA_CODE,
)
from loto_pipeline_e import augment_terrain, N_FEATURES_E, CFG_E  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

FINAL_DIR = _THIS / "final_model"

# SA overlap zone dans l'espace SA : rows 1000-1500, cols 500-1500
# Correspond à Y=[6888000,6889000], X=[448000,450000] (zone Caen)
_SA_OVERLAP = (1000, 1500, 500, 1500)

CATEGORIES: dict[int, dict] = {
    0: {"code": "decouvert", "ocad": 401, "rgb": [255, 201,  15]},
    1: {"code": "blanc",     "ocad": 405, "rgb": [255, 255, 255]},
    2: {"code": "veg_406",   "ocad": 406, "rgb": [204, 255, 179]},
    3: {"code": "veg_408",   "ocad": 408, "rgb": [153, 255, 102]},
    4: {"code": "veg_410",   "ocad": 410, "rgb": [ 51, 255,   0]},
}


def _assemble_all_terrains() -> tuple[np.ndarray, np.ndarray, dict]:
    """Charge et concatène les pixels d'entraînement des 4 terrains."""
    loaders = {
        "bd":          load_bd,
        "caen":        load_caen,
        "montmirel":   load_montmirel,
        "sainte_anne": load_sainte_anne,
    }
    X_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    counts: dict[str, dict] = {}

    for name, loader in loaders.items():
        log.info("=== %s : chargement + augmentation ===", name)
        td_t = loader()
        td_e = augment_terrain(name, td_t)
        del td_t

        mask = td_e["support"] & ~td_e["partial_ctx"] & (td_e["ref_cat"] >= 0)

        # Déduplication géographique : exclure de SA la zone commune avec Caen
        if name == "sainte_anne":
            r0, r1, c0, c1 = _SA_OVERLAP
            overlap = np.zeros(mask.shape, dtype=bool)
            overlap[r0:r1, c0:c1] = True
            n_before = int(mask.sum())
            mask &= ~overlap
            log.info(
                "sainte_anne : overlap Caen exclu — %d px masqués / %d disponibles",
                n_before - int(mask.sum()), n_before,
            )

        X_flat = td_e["X_grid"][mask]
        y_flat = td_e["ref_cat"][mask].astype(np.uint8)
        total_px = int(len(X_flat))
        del td_e

        # Sous-échantillonnage uniforme si dépassement
        if len(X_flat) > MAX_TRAIN_PX_PER_TERRAIN:
            rng = np.random.default_rng(RANDOM_SEED)
            idx = rng.choice(len(X_flat), MAX_TRAIN_PX_PER_TERRAIN, replace=False)
            X_flat = X_flat[idx]
            y_flat = y_flat[idx]

        counts[name] = {
            "total_eligible_px": total_px,
            "train_px": int(len(X_flat)),
            "by_class": {
                CATEGORIES[c]["code"]: int((y_flat == c).sum())
                for c in range(5)
            },
        }
        log.info("%s : %d px retenus en train", name, len(X_flat))
        X_parts.append(X_flat)
        y_parts.append(y_flat)

    X_all = np.concatenate(X_parts, axis=0)
    y_all = np.concatenate(y_parts, axis=0)
    log.info("Total assemblé : %d px × %d features", X_all.shape[0], X_all.shape[1])
    return X_all, y_all, counts


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    out_pkl = FINAL_DIR / "model_e_final.pkl"
    if out_pkl.exists():
        log.warning(
            "Modèle final déjà présent : %s\n"
            "Supprimer ce fichier pour recalculer.",
            out_pkl,
        )
        return

    log.info("=== Assemblage données d'entraînement ===")
    X_train, y_train, counts = _assemble_all_terrains()

    log.info("=== Imputation (mean, appris sur train uniquement) ===")
    imputer = SimpleImputer(strategy="mean")
    X_imp = imputer.fit_transform(X_train)
    del X_train

    log.info("=== Entraînement RF_leaf5 (n=%d, depth=%d, leaf=%d) ===",
             CFG_E["n"], CFG_E["depth"], CFG_E["leaf"])
    clf = RandomForestClassifier(
        n_estimators=CFG_E["n"],
        max_depth=CFG_E["depth"],
        min_samples_leaf=CFG_E["leaf"],
        class_weight=CFG_E["weight"],
        n_jobs=-1,
        random_state=RANDOM_SEED,
    )
    clf.fit(X_imp, y_train)
    log.info("Entraînement terminé.")

    # Écriture atomique : tmp → validation → rename
    tmp_pkl = FINAL_DIR / "model_e_final.tmp.pkl"
    if tmp_pkl.exists():
        tmp_pkl.unlink()

    payload = {
        "clf": clf,
        "imputer": imputer,
        "config": {**CFG_E, "random_seed": RANDOM_SEED},
        "n_features": N_FEATURES_E,
        "n_features_t": N_FEATURES,
        "categories": CATEGORIES,
        "nodata_code": NODATA_CODE,
    }
    log.info("Sauvegarde temporaire %s...", tmp_pkl.name)
    with tmp_pkl.open("wb") as f:
        pickle.dump(payload, f, protocol=5)

    # Validation : rechargement + vérification
    log.info("Validation rechargement...")
    with tmp_pkl.open("rb") as f:
        v = pickle.load(f)  # noqa: S301 — provenance locale contrôlée
    assert v["n_features"] == N_FEATURES_E, "n_features incohérent après rechargement"
    assert hasattr(v["clf"], "predict"), "clf non rechargeable"
    del v

    tmp_pkl.replace(out_pkl)
    log.info("Modèle sauvegardé : %s", out_pkl)

    # Manifeste
    sha = _sha256(out_pkl)
    total_train_px = sum(c["train_px"] for c in counts.values())
    manifeste = {
        "model_file": out_pkl.name,
        "sha256": sha,
        "config": payload["config"],
        "n_features_total": N_FEATURES_E,
        "n_features_t": N_FEATURES,
        "n_features_e_added": N_FEATURES_E - N_FEATURES,
        "max_px_per_terrain": MAX_TRAIN_PX_PER_TERRAIN,
        "geographic_deduplication": (
            "SA rows 1000-1500 cols 500-1500 exclus (zone commune avec Caen)"
        ),
        "training_data": counts,
        "total_train_px": total_train_px,
        "categories": {str(k): v for k, v in CATEGORIES.items()},
        "note": (
            "Les performances sur ces 4 terrains après entraînement final sont des résultats "
            "de réemploi (données d'apprentissage), pas une validation externe. "
            "Scores LOTO disponibles dans results/ et results_e/."
        ),
    }
    mf_path = FINAL_DIR / "manifeste.json"
    with mf_path.open("w", encoding="utf-8") as f:
        json.dump(manifeste, f, ensure_ascii=False, indent=2)
    log.info("Manifeste : %s  (SHA-256 : %s…)", mf_path.name, sha[:16])

    # Copie spec figée
    spec_src = _THIS / "method_e_spec.yaml"
    if spec_src.exists():
        shutil.copy(str(spec_src), str(FINAL_DIR / "method_e_spec.yaml"))
        log.info("Spec figée copiée.")

    log.info("=== Modèle final E prêt. ===")
    log.info("SHA-256 : %s", sha)


if __name__ == "__main__":
    main()
