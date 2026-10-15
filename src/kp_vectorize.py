"""kp_vectorize — calibration expérimentale du mapping KP → ISOM 406/408/410.

Module strictement expérimental — aucun appel depuis le pipeline normal.
Lit les tuiles KP originales via src.kp_raster, calibre deux seuils monotones
sur des ROIs FFCO étiquetées calibration/validation, et produit :

- kp_vectorize_fixed.gpkg      : variante mapping actuel (config.yaml)
- kp_vectorize_calibrated.gpkg : variante mapping calibré
- kp_vectorize_report.json     : métriques, seuils, garde-fous, statut

Aucun fichier de production n'est modifié.

Usage :
    python -m src.kp_vectorize out_kp_grimbosq rois.gpkg out/exp1 \\
        --config config.yaml --terrain grimbosq \\
        --layer rois --class-field class --split-field split --id-field roi_id
"""
from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

_ISOM_CLASSES: tuple[int, ...] = (406, 408, 410)
_EROSION_M: dict[int, float] = {406: 6.0, 408: 8.0, 410: 10.0, 405: 10.0}
_DEFAULT_GREENDETECTSIZE = 3
_NO_PRED = 0          # prédit « aucune végétation » (cellule couverte mais sans ton vert)
_VALID_ISOM_OUTPUTS = frozenset({0, 406, 408, 410})
_MM2 = 1e6 / 10_000**2  # m² → mm² à 1:10 000


# ── Structures de données ─────────────────────────────────────────────────────

@dataclass
class CellSample:
    """Résultat du sondage d'une ROI érodée à la résolution sémantique."""
    cells_green: np.ndarray    # valeurs de shade ≥ KP_FIRST_GREEN (mode des cellules vertes)
    n_nodata: int              # cellules avec mode=0 (pas de couverture)
    n_no_prediction: int       # cellules avec mode=1 (jaune, couvert, pas de végétation)
    pct_non_constant: float    # % de cellules non-constantes parmi les cellules couverts

    @property
    def n_covered(self) -> int:
        """Cellules couvertes = vertes + jaunes (hors NoData)."""
        return len(self.cells_green) + self.n_no_prediction


@dataclass
class RoiRecord:
    roi_id: Any
    cls: int       # 406, 408, 410 ou 405 (contrôle négatif)
    split: str     # "calibration" | "validation"
    eroded: Any    # géométrie shapely ou None


@dataclass
class RoiCells:
    roi_id: Any
    cls: int
    split: str
    sample: CellSample


# ── Lecture de paramètres ─────────────────────────────────────────────────────

def read_greendetectsize(ini_path: pathlib.Path | None) -> int:
    """Lit `greendetectsize` dans un pullauta.ini. Retourne 3 par défaut."""
    if ini_path is None or not pathlib.Path(ini_path).exists():
        return _DEFAULT_GREENDETECTSIZE
    for line in pathlib.Path(ini_path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("greendetectsize") and "=" in stripped:
            parts = stripped.split("=", 1)
            if len(parts) == 2:
                try:
                    return int(float(parts[1].strip()))
                except ValueError:
                    pass
    return _DEFAULT_GREENDETECTSIZE


def _read_greendetectsize_verbose(ini_path: pathlib.Path) -> tuple[int, str]:
    """Retourne (valeur, source) où source ∈ {'ini', 'default_karttapullautin', 'default_parse_error'}.

    Contrairement à read_greendetectsize(), documente explicitement si la valeur a été
    lue dans l'INI ou si c'est la valeur par défaut de Karttapullautin (3).
    """
    if ini_path is None or not pathlib.Path(ini_path).exists():
        return _DEFAULT_GREENDETECTSIZE, "default_karttapullautin"
    for line in pathlib.Path(ini_path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("greendetectsize") and "=" in stripped:
            parts = stripped.split("=", 1)
            if len(parts) == 2:
                try:
                    return int(float(parts[1].strip())), "ini"
                except ValueError:
                    log.warning(
                        "greendetectsize invalide dans %s — valeur par défaut %d appliquée",
                        pathlib.Path(ini_path).name, _DEFAULT_GREENDETECTSIZE,
                    )
                    return _DEFAULT_GREENDETECTSIZE, "default_parse_error"
    return _DEFAULT_GREENDETECTSIZE, "default_karttapullautin"


def load_fixed_mapping(cfg: dict) -> dict[int, int]:
    """Charge shade_to_isom depuis config.yaml.

    Retourne {bit_kp: isom_code} où isom_code ∈ {0, 406, 408, 410}.
    Lève ValueError si la clé est absente ou si un code ISOM est invalide.
    """
    raw = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {}).get("shade_to_isom")
    if not raw:
        raise ValueError(
            "karttapullautin.vectorization.shade_to_isom absent de config.yaml — "
            "impossible de charger le mapping fixe."
        )
    mapping = {int(k): int(v) for k, v in raw.items()}
    invalid = set(mapping.values()) - _VALID_ISOM_OUTPUTS
    if invalid:
        raise ValueError(
            f"Codes ISOM invalides dans shade_to_isom : {sorted(invalid)}. "
            f"Codes autorisés : {sorted(_VALID_ISOM_OUTPUTS)} "
            f"(0 = volontairement blanc, pas une classe végétation)."
        )
    return mapping


# ── Préconditions du runner ───────────────────────────────────────────────────

def _require_ini(out_kp: pathlib.Path) -> pathlib.Path:
    """Exige la présence de pullauta.ini dans out_kp/. Lève FileNotFoundError sinon."""
    ini = pathlib.Path(out_kp) / "pullauta.ini"
    if not ini.exists():
        raise FileNotFoundError(
            f"pullauta.ini absent dans {out_kp}/ — "
            "impossible de déterminer les paramètres réels du run KP. "
            "Lancer l'étape relief avant d'utiliser ce module, ou vérifier "
            "que out_kp pointe vers le bon répertoire."
        )
    return ini


def _validate_tile_sources(tiles: list) -> None:
    """Interdit les sources de substitution : vegetation.png et tout fichier merged*."""
    bad = [
        t for t in tiles
        if t.path.name == "vegetation.png" or t.path.name.lower().startswith("merged")
    ]
    if bad:
        names = [t.path.name for t in bad]
        raise ValueError(
            f"Source(s) de substitution interdite(s) : {names}. "
            "Ces fichiers sont des rendus ou des fusions et peuvent avoir "
            "subi un remappage de couleur. "
            "Les tuiles originales *_vege.png ou *_vege_bit.png doivent être présentes."
        )


def _check_output_dir_empty(out_dir: pathlib.Path) -> None:
    """Refuse de démarrer si out_dir contient déjà des fichiers."""
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(
            f"Le répertoire de sortie '{out_dir}' n'est pas vide. "
            "Choisir un répertoire vide ou inexistant pour éviter d'écraser "
            "des résultats existants."
        )


# ── ROIs ──────────────────────────────────────────────────────────────────────

def _validate_rois_fields(
    columns: list[str], class_field: str, split_field: str, id_field: str,
) -> None:
    missing = [f for f in (class_field, split_field, id_field) if f not in columns]
    if missing:
        raise ValueError(
            f"Champs manquants dans les ROIs : {missing}. "
            f"Attendu : class_field='{class_field}', split_field='{split_field}', "
            f"id_field='{id_field}'. Champs disponibles : {columns}"
        )


def _validate_rois_values(gdf: Any, class_field: str, split_field: str) -> None:
    invalid_cls = {int(v) for v in gdf[class_field].unique()} - {405, 406, 408, 410}
    if invalid_cls:
        raise ValueError(
            f"Valeurs inconnues dans '{class_field}' : {sorted(invalid_cls)}. "
            f"Valeurs autorisées : 405, 406, 408, 410."
        )
    invalid_split = {str(v) for v in gdf[split_field].unique()} - {"calibration", "validation"}
    if invalid_split:
        raise ValueError(
            f"Valeurs inconnues dans '{split_field}' : {sorted(invalid_split)}. "
            f"Valeurs autorisées : 'calibration', 'validation'."
        )


def load_rois(
    gpkg_path: pathlib.Path,
    layer: str,
    class_field: str,
    split_field: str,
    id_field: str,
    crs: str,
) -> list[RoiRecord]:
    """Charge et valide les ROIs depuis un GPKG. Effectue l'érosion par classe."""
    import geopandas as gpd

    gdf = gpd.read_file(str(gpkg_path), layer=layer)
    _validate_rois_fields(list(gdf.columns), class_field, split_field, id_field)
    _validate_rois_values(gdf, class_field, split_field)

    if gdf.crs is None:
        raise ValueError(f"Les ROIs de '{gpkg_path}' n'ont pas de CRS défini.")
    if gdf.crs.to_string() != crs:
        gdf = gdf.to_crs(crs)
        log.info("ROIs reprojetées → %s", crs)

    records: list[RoiRecord] = []
    for _, row in gdf.iterrows():
        cls = int(row[class_field])
        split = str(row[split_field])
        roi_id = row[id_field]
        margin_m = _EROSION_M.get(cls, 6.0)
        eroded = erode_roi(row.geometry, margin_m)
        if eroded is None:
            log.warning("ROI %s (cls=%d) : vide après érosion %.0f m — ignorée",
                        roi_id, cls, margin_m)
        records.append(RoiRecord(roi_id=roi_id, cls=cls, split=split, eroded=eroded))

    return records


def erode_roi(geom: Any, margin_m: float) -> Any:
    """Érode une géométrie de `margin_m` mètres. Retourne None si vide."""
    if geom is None:
        return None
    eroded = geom.buffer(-margin_m)
    if eroded is None or eroded.is_empty:
        return None
    return eroded


# ── Cellules sémantiques ─────────────────────────────────────────────────────

def sample_semantic_cells(
    labels: np.ndarray,
    res_m: float,
    west: float,
    north: float,
    roi_geom: Any,
    cell_size_m: int = _DEFAULT_GREENDETECTSIZE,
) -> CellSample:
    """Échantillonne les cellules sémantiques de `cell_size_m` m dans une ROI érodée.

    Aligne la grille de cellules sur l'origine (west, north) du raster.
    Une cellule est retenue uniquement si tous ses pixels sont dans la ROI (strictement).

    Distinctions :
    - mode=0 (KP_NO_DATA) → n_nodata (pas de couverture)
    - mode=1 (KP_YELLOW)  → n_no_prediction (couvert, aucune végétation détectée)
    - mode≥2              → cells_green (shade vert)
    """
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin
    import shapely.geometry as sg

    if roi_geom is None or roi_geom.is_empty:
        return CellSample(np.array([], dtype=np.uint8), 0, 0, 0.0)

    height, width = labels.shape
    transform = from_origin(west, north, res_m, res_m)
    mask = ~geometry_mask(
        [sg.mapping(roi_geom)], out_shape=(height, width),
        transform=transform, all_touched=False,
    )

    scale = max(1, int(round(cell_size_m / res_m)))
    cells_green: list[int] = []
    n_nodata = 0
    n_no_pred = 0
    non_constant = 0

    from src.kp_raster import KP_FIRST_GREEN, KP_NO_DATA, KP_YELLOW

    for r0 in range(0, height, scale):
        for c0 in range(0, width, scale):
            r1 = min(r0 + scale, height)
            c1 = min(c0 + scale, width)
            if (r1 - r0) < scale or (c1 - c0) < scale:
                continue  # fenêtre partielle en bord de raster — ignorée
            cell_mask = mask[r0:r1, c0:c1]
            if not cell_mask.all():
                continue  # cellule hors ROI
            cell_vals = labels[r0:r1, c0:c1].flatten()
            vals, cnts = np.unique(cell_vals, return_counts=True)
            mode_val = int(vals[cnts.argmax()])
            if mode_val == KP_NO_DATA:
                n_nodata += 1
                # Cellule nodata exclue de n_covered → exclue de pct_non_constant
            elif mode_val == KP_YELLOW:
                n_no_pred += 1
                if len(vals) > 1:
                    non_constant += 1
            else:
                cells_green.append(mode_val)
                if len(vals) > 1:
                    non_constant += 1

    arr = np.array(cells_green, dtype=np.uint8)
    n_covered = len(arr) + n_no_pred
    pct_nc = float(non_constant / n_covered * 100) if n_covered > 0 else 0.0
    return CellSample(arr, n_nodata, n_no_pred, pct_nc)


def collect_roi_cells(
    records: list[RoiRecord],
    labels: np.ndarray,
    res_m: float,
    west: float,
    north: float,
    cell_size_m: int,
    valid_shades: list[int],
) -> list[RoiCells]:
    """Extrait les cellules sémantiques pour chaque ROI avec géométrie érodée valide.

    Les shades hors de valid_shades sont filtrés des cells_green.
    Les cellules no_prediction restent dans le compte (non-détections).
    """
    valid_set = np.array(valid_shades, dtype=np.uint8)
    result: list[RoiCells] = []
    for rec in records:
        if rec.eroded is None:
            continue
        sample = sample_semantic_cells(
            labels, res_m, west, north, rec.eroded, cell_size_m=cell_size_m,
        )
        # Filtrer les shades non-observés (hors valid_shades)
        green_filtered = sample.cells_green[np.isin(sample.cells_green, valid_set)]
        sample_filtered = CellSample(
            cells_green=green_filtered,
            n_nodata=sample.n_nodata,
            n_no_prediction=sample.n_no_prediction,
            pct_non_constant=sample.pct_non_constant,
        )
        if sample_filtered.n_covered == 0:
            log.warning("ROI %s (cls=%d, split=%s) : aucune cellule couverte après filtrage",
                        rec.roi_id, rec.cls, rec.split)
            continue
        if sample_filtered.pct_non_constant > 0:
            log.info("ROI %s : %.1f%% cellules non-constantes (mode appliqué)",
                     rec.roi_id, sample_filtered.pct_non_constant)
        result.append(RoiCells(roi_id=rec.roi_id, cls=rec.cls, split=rec.split,
                                sample=sample_filtered))
    return result


# ── Calibration ───────────────────────────────────────────────────────────────

def _build_pred_arrays(
    roi_cells: list[RoiCells],
    t1: int,
    t2: int,
    split: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Construit (prédictions, vérités, poids) pour les ROIs 406/408/410 d'un split.

    Inclut les cellules no_prediction (prédites comme _NO_PRED = 0).
    Pondération : 1 / (n_classes × n_rois_de_la_classe × n_covered_dans_la_roi).
    ROIs 405 exclues (traitement séparé dans _commission_405).
    """
    subset = [r for r in roi_cells if r.split == split and r.cls in _ISOM_CLASSES]
    rois_per_cls = {cls: sum(1 for r in subset if r.cls == cls) for cls in _ISOM_CLASSES}
    n_classes = sum(1 for n in rois_per_cls.values() if n > 0)

    preds: list[int] = []
    truths: list[int] = []
    wts: list[float] = []
    for r in subset:
        n_rois = rois_per_cls.get(r.cls, 0)
        n_cov = r.sample.n_covered
        if n_cov == 0 or n_rois == 0 or n_classes == 0:
            continue
        w = 1.0 / (n_classes * n_rois * n_cov)
        for shade in r.sample.cells_green:
            s = int(shade)
            pred = 406 if s <= t1 else (408 if s <= t2 else 410)
            preds.append(pred)
            truths.append(r.cls)
            wts.append(w)
        for _ in range(r.sample.n_no_prediction):
            preds.append(_NO_PRED)
            truths.append(r.cls)
            wts.append(w)

    return (
        np.array(preds, dtype=np.int32),
        np.array(truths, dtype=np.int32),
        np.array(wts, dtype=np.float64),
    )


def _weighted_macro_f1(
    predictions: np.ndarray,
    truths: np.ndarray,
    weights: np.ndarray,
    classes: tuple[int, ...] = _ISOM_CLASSES,
) -> float:
    """Macro-F1 pondéré. pred=0 (_NO_PRED) contribue aux FN, jamais aux FP."""
    if weights.sum() == 0:
        return 0.0
    f1s: list[float] = []
    for cls in classes:
        tp = float(weights[(predictions == cls) & (truths == cls)].sum())
        fp = float(weights[(predictions == cls) & (truths != cls)].sum())
        fn = float(weights[(predictions != cls) & (truths == cls)].sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2.0 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        f1s.append(f1)
    return float(np.mean(f1s))


def _min_weighted_recall(
    predictions: np.ndarray,
    truths: np.ndarray,
    weights: np.ndarray,
    classes: tuple[int, ...] = _ISOM_CLASSES,
) -> float:
    """Rappel pondéré minimal parmi les classes. Utilisé pour le départage des seuils."""
    recalls: list[float] = []
    for cls in classes:
        total = float(weights[truths == cls].sum())
        if total == 0:
            recalls.append(0.0)
            continue
        tp = float(weights[(truths == cls) & (predictions == cls)].sum())
        recalls.append(tp / total)
    return min(recalls) if recalls else 0.0


def calibrate_thresholds(
    roi_cells: list[RoiCells],
    valid_shades: list[int],
    split: str = "calibration",
) -> tuple[int, int, dict]:
    """Calibre deux seuils monotones sur les ROIs 406/408/410 du split indiqué.

    Mapping résultant : shade ≤ t1 → 406 ; t1 < shade ≤ t2 → 408 ; shade > t2 → 410.
    Objectif : macro-F1 pondéré incluant les non-détections.

    Départage (en cas d'égalité de F1) :
    1. Rappel pondéré minimal maximal.
    2. Ordre lexicographique (t1, t2) croissant.
    """
    calib = [r for r in roi_cells if r.split == split and r.cls in _ISOM_CLASSES]
    if not calib:
        raise ValueError(f"Aucune ROI {_ISOM_CLASSES} de split '{split}'.")

    present_cls = {r.cls for r in calib} & set(_ISOM_CLASSES)
    if len(present_cls) < 3:
        missing = sorted(set(_ISOM_CLASSES) - present_cls)
        raise ValueError(
            f"Classes ISOM manquantes dans les ROIs de calibration : {missing}. "
            f"Classes présentes : {sorted(present_cls)}."
        )

    s_min, s_max = min(valid_shades), max(valid_shades)
    candidates: list[tuple[float, float, int, int]] = []  # (-f1, -min_rec, t1, t2)

    for t1 in range(s_min, s_max):
        for t2 in range(t1 + 1, s_max + 1):
            preds, truths, wts = _build_pred_arrays(calib, t1, t2, split)
            if len(preds) == 0:
                continue
            f1 = _weighted_macro_f1(preds, truths, wts)
            min_rec = _min_weighted_recall(preds, truths, wts)
            candidates.append((-f1, -min_rec, t1, t2))  # sort ascending → best first

    if not candidates:
        raise ValueError("Aucune paire (t1, t2) valide trouvée.")

    candidates.sort()
    _, _, best_t1, best_t2 = candidates[0]
    best_f1 = -candidates[0][0]

    preds, truths, wts = _build_pred_arrays(calib, best_t1, best_t2, split)
    rois_per_cls = {cls: sum(1 for r in calib if r.cls == cls) for cls in _ISOM_CLASSES}
    per_class: dict[str, dict] = {}
    for cls in _ISOM_CLASSES:
        tot = float(wts[truths == cls].sum())
        tp = float(wts[(truths == cls) & (preds == cls)].sum())
        fp = float(wts[(preds == cls) & (truths != cls)].sum())
        fn = float(wts[(truths == cls) & (preds != cls)].sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / tot if tot > 0 else 0.0
        f1 = 2.0 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        per_class[str(cls)] = {
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
        }

    report = {
        "t1": best_t1, "t2": best_t2,
        "macro_f1": round(best_f1, 4),
        "per_class": per_class,
        "n_calib_rois": len(calib),
        "rois_per_class": {str(k): v for k, v in rois_per_cls.items()},
    }
    return best_t1, best_t2, report


def thresholds_to_mapping(t1: int, t2: int, valid_shades: list[int]) -> dict[int, int]:
    """Convertit deux seuils en table shade → code ISOM."""
    return {
        shade: (406 if shade <= t1 else (408 if shade <= t2 else 410))
        for shade in valid_shades
    }


def evaluate_mapping(
    roi_cells: list[RoiCells],
    mapping: dict[int, int],
    split: str,
) -> dict:
    """Évalue un mapping gelé sur les ROIs 406/408/410 d'un split. Ne modifie pas mapping."""
    subset = [r for r in roi_cells if r.split == split and r.cls in _ISOM_CLASSES]
    if not subset:
        return {"error": f"Aucune ROI {_ISOM_CLASSES} de split '{split}'."}

    present_cls = {r.cls for r in subset} & set(_ISOM_CLASSES)
    rois_per_cls = {cls: sum(1 for r in subset if r.cls == cls) for cls in _ISOM_CLASSES}
    n_classes = len(present_cls)

    preds: list[int] = []
    truths: list[int] = []
    wts: list[float] = []
    for r in subset:
        n_rois = rois_per_cls.get(r.cls, 0)
        n_cov = r.sample.n_covered
        if n_cov == 0 or n_rois == 0 or n_classes == 0:
            continue
        w = 1.0 / (n_classes * n_rois * n_cov)
        for shade in r.sample.cells_green:
            pred = mapping.get(int(shade), _NO_PRED)
            preds.append(pred)
            truths.append(r.cls)
            wts.append(w)
        for _ in range(r.sample.n_no_prediction):
            preds.append(_NO_PRED)
            truths.append(r.cls)
            wts.append(w)

    if not preds:
        return {"error": "Aucune cellule couverte disponible."}

    preds_a = np.array(preds, dtype=np.int32)
    truths_a = np.array(truths, dtype=np.int32)
    wts_a = np.array(wts, dtype=np.float64)
    macro_f1 = _weighted_macro_f1(preds_a, truths_a, wts_a)

    per_class: dict[str, dict] = {}
    for cls in _ISOM_CLASSES:
        tot = float(wts_a[truths_a == cls].sum())
        tp = float(wts_a[(truths_a == cls) & (preds_a == cls)].sum())
        fp = float(wts_a[(preds_a == cls) & (truths_a != cls)].sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / tot if tot > 0 else 0.0
        f1 = 2.0 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        per_class[str(cls)] = {
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
        }

    return {
        "split": split,
        "n_rois": len(subset),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "status_note": "diagnostic disponible — seuils d'acceptation à fixer par le porteur",
    }


def _commission_405(
    roi_cells: list[RoiCells],
    mapping: dict[int, int],
    split: str,
) -> dict:
    """Calcule les statistiques de commission dans les ROIs 405 (contrôle négatif).

    Commission : cellule verte prédite végétation (code ISOM).
    Rejet correct : cellule couverte sans prédiction végétation — que ce soit une
                    cellule jaune (no_prediction) OU un shade volontairement mappé à 0.
    Cellules NoData : exclues du dénominateur.

    Deux taux sont rapportés :
    - commission_rate_raw     : n_commission / n_covered (toutes cellules)
    - commission_rate_weighted : moyenne des taux par ROI (résistant aux ROIs de taille variable)
    """
    rois_405 = [r for r in roi_cells if r.cls == 405 and r.split == split]
    if not rois_405:
        return {"split": split, "n_rois_405": 0,
                "note": f"Aucune ROI 405 de split '{split}'."}

    n_commission = 0
    n_correct_rejection = 0
    n_nodata = 0
    pred_dist: dict[str, int] = {str(c): 0 for c in _ISOM_CLASSES}
    pred_dist["no_pred"] = 0
    roi_rates: list[float] = []

    for r in rois_405:
        n_comm_r = 0
        n_rej_r = 0
        for shade in r.sample.cells_green:
            pred = mapping.get(int(shade), _NO_PRED)
            if pred in _ISOM_CLASSES:
                n_comm_r += 1
                pred_dist[str(pred)] = pred_dist.get(str(pred), 0) + 1
            else:
                # shade mappé à 0 (blanc) ou absent du mapping : rejet sans prédiction
                n_rej_r += 1
                pred_dist["no_pred"] += 1
        n_rej_r += r.sample.n_no_prediction  # cellules jaunes : rejet correct
        n_nodata += r.sample.n_nodata
        n_commission += n_comm_r
        n_correct_rejection += n_rej_r
        n_cov_r = n_comm_r + n_rej_r
        if n_cov_r > 0:
            roi_rates.append(n_comm_r / n_cov_r)

    n_covered = n_commission + n_correct_rejection
    rate_raw = float(n_commission / n_covered) if n_covered > 0 else 0.0
    rate_weighted = float(sum(roi_rates) / len(roi_rates)) if roi_rates else 0.0

    return {
        "split": split,
        "n_rois_405": len(rois_405),
        "n_commission": n_commission,
        "n_correct_rejection": n_correct_rejection,
        "n_nodata_405": n_nodata,
        "commission_rate_raw": round(rate_raw, 4),
        "commission_rate_weighted": round(rate_weighted, 4),
        "pred_distribution": pred_dist,
    }


def _diagnostic_matrix(
    roi_cells: list[RoiCells],
    mapping: dict[int, int],
    split: str,
) -> dict:
    """Matrice de diagnostic : lignes = classes référence (405, 406, 408, 410),
    colonnes = (no_pred, 406, 408, 410). Comptes non pondérés."""
    ref_classes = (405,) + _ISOM_CLASSES
    pred_labels = ("no_pred",) + tuple(str(c) for c in _ISOM_CLASSES)

    matrix: dict[str, dict[str, int]] = {
        str(rc): {pl: 0 for pl in pred_labels} for rc in ref_classes
    }

    for r in roi_cells:
        if r.split != split:
            continue
        row_key = str(r.cls)
        if row_key not in matrix:
            continue
        for shade in r.sample.cells_green:
            pred = mapping.get(int(shade), _NO_PRED)
            col = "no_pred" if pred == _NO_PRED else str(pred)
            if col in matrix[row_key]:
                matrix[row_key][col] += 1
        matrix[row_key]["no_pred"] += r.sample.n_no_prediction

    return {"split": split, "ref_classes": [str(c) for c in ref_classes],
            "pred_labels": list(pred_labels), "counts": matrix}


# ── Polygonisation ─────────────────────────────────────────────────────────────

def polygonize_variant(
    labels: np.ndarray,
    shade_to_isom: dict[int, int],
    res_m: float,
    west: float,
    north: float,
    crs: str,
    tol: float = 2.0,
) -> dict[int, list]:
    """Applique un mapping shade→ISOM et polygonise — même chaîne que step_vegetation_kp.

    Lève ValueError si la couverture est invalide pour une classe (jamais ignoré).
    Retourne {406: [geoms], 408: [geoms], 410: [geoms]}.
    """
    import shapely
    import shapely.geometry as sg
    from rasterio.features import shapes as rasterio_shapes
    from rasterio.transform import from_origin

    from src.kp_raster import ISOM_TO_DN

    transform = from_origin(west, north, res_m, res_m)
    dn_raster = np.zeros(labels.shape, dtype=np.uint8)
    for shade, isom in shade_to_isom.items():
        if isom not in ISOM_TO_DN:
            continue  # shades mappés à 0 (blanc) : ignorés
        dn_raster[labels == shade] = ISOM_TO_DN[isom]

    # Shades de la variante non couverts par shade_to_isom ni par une règle explicite
    all_present = set(int(v) for v in np.unique(labels) if int(v) > 1)
    not_in_mapping = all_present - set(shade_to_isom.keys())
    if not_in_mapping:
        log.warning(
            "polygonize_variant : %d shade(s) présents mais absents du mapping "
            "et ignorés : %s", len(not_in_mapping), sorted(not_in_mapping),
        )

    dn_to_isom = {v: k for k, v in ISOM_TO_DN.items()}
    all_geoms: list = []
    all_codes: list[int] = []

    for dn, isom in sorted(dn_to_isom.items()):
        mask_arr = (dn_raster == dn).astype(np.uint8)
        geoms: list = []
        for geom_dict, _ in rasterio_shapes(mask_arr, mask=mask_arr, transform=transform):
            geom = sg.shape(geom_dict)
            if not geom.is_empty:
                geoms.append(geom)
        if not geoms:
            continue
        geom_arr_cls = np.array(geoms, dtype=object)
        if not shapely.coverage_is_valid(geom_arr_cls):
            invalid_edges = shapely.coverage_invalid_edges(geom_arr_cls)
            n_inv = sum(1 for e in invalid_edges if e is not None and not e.is_empty)
            raise ValueError(
                f"polygonize_variant : couverture invalide pour la classe {isom} "
                f"({n_inv} arête(s) invalide(s)) — résultat non exploitable."
            )
        all_geoms.extend(geoms)
        all_codes.extend([isom] * len(geoms))

    layers: dict[int, list] = {406: [], 408: [], 410: []}
    if not all_geoms:
        return layers

    geom_arr = np.array(all_geoms, dtype=object)
    simplified = shapely.coverage_simplify(geom_arr, tolerance=tol, simplify_boundary=True)
    for geom, code in zip(simplified, all_codes):
        if geom is not None and not geom.is_empty:
            layers[code].append(geom)

    return layers


# ── Critères géométriques §3.1 ────────────────────────────────────────────────

def compute_geometric_criteria(
    layers: dict[int, list],
    ffco_ref: Any | None,
) -> dict:
    """Calcule les deux critères géométriques du plan (§3.1).

    Longueur d'une composante : plus grand côté du rectangle englobant minimal rotatif.
    Couverture ≤ 10 m : rappel FFCO→résultat, et ratio_utile résultat→FFCO.

    IMPORTANT : `legacy_comparability` est False tant que la définition exacte des
    métriques historiques n'a pas été validée par le porteur sur le dépôt réel.
    """
    from shapely.ops import unary_union

    all_geoms = [g for cls in _ISOM_CLASSES for g in layers.get(cls, [])]
    if not all_geoms:
        return {
            "n_components": 0,
            "median_component_length_m": None,
            "coverage_10m_recall_pct": None,
            "ratio_utile_pct": None,
            "legacy_comparability": False,
            "legacy_note": "Aucune géométrie produite.",
        }

    union = unary_union(all_geoms)
    comps: list = list(union.geoms) if hasattr(union, "geoms") else [union]

    lengths: list[float] = []
    for comp in comps:
        if comp.is_empty:
            continue
        mrr = comp.minimum_rotated_rectangle
        if mrr is None or mrr.is_empty:
            continue
        coords = list(mrr.exterior.coords)
        sides: list[float] = []
        for i in range(len(coords) - 1):
            dx = coords[i + 1][0] - coords[i][0]
            dy = coords[i + 1][1] - coords[i][1]
            sides.append((dx**2 + dy**2) ** 0.5)
        if sides:
            lengths.append(max(sides))

    median_len = float(np.median(lengths)) if lengths else None

    recall_10m = None
    ratio_utile = None
    if ffco_ref is not None and not ffco_ref.is_empty and ffco_ref.area > 0:
        buf_result = union.buffer(10.0) if not union.is_empty else union
        recall_10m = float(ffco_ref.intersection(buf_result).area / ffco_ref.area * 100)
        result_area = union.area if not union.is_empty else 0.0
        if result_area > 0:
            buf_ref = ffco_ref.buffer(10.0)
            ratio_utile = float(union.intersection(buf_ref).area / result_area * 100)

    return {
        "n_components": len(comps),
        "median_component_length_m": round(median_len, 1) if median_len is not None else None,
        "length_definition": (
            "plus grand côté du rectangle englobant minimal rotatif — "
            "non comparé aux valeurs historiques sans validation porteur"
        ),
        "coverage_10m_recall_pct": round(recall_10m, 1) if recall_10m is not None else None,
        "ratio_utile_pct": round(ratio_utile, 1) if ratio_utile is not None else None,
        "legacy_comparability": False,
        "legacy_note": (
            "Définition exacte des métriques historiques non retrouvée sans ambiguïté "
            "dans le dépôt — validation porteur requise avant comparaison."
        ),
    }


# ── Métriques max_pct §5.3 ────────────────────────────────────────────────────

def check_max_pct(max_pct: float, max_pct_fixed: float, cls: int) -> dict:
    """Applique les trois règles max_pct (§5.3).

    - reject_hard    : max_pct > 50 % (plafond absolu, indépendant de la baseline)
    - alert_relative : max_pct > 1,5 × max_pct_fixed
    - alert_406      : cls==406 et max_pct > 15 %
    """
    return {
        "reject_hard": max_pct > 50.0,
        "alert_relative": (max_pct_fixed > 0.0) and (max_pct > 1.5 * max_pct_fixed),
        "alert_406": (cls == 406) and (max_pct > 15.0),
        "max_pct": round(max_pct, 2),
        "max_pct_fixed": round(max_pct_fixed, 2),
    }


def _qa_layers(layers: dict[int, list], ffco_ref: Any | None = None) -> dict[int, dict]:
    """Métriques QA par classe : n, total_ha, max_pct, med_mm2, pct_small, cov_pct."""
    from shapely.ops import unary_union

    result: dict[int, dict] = {}
    for cls in _ISOM_CLASSES:
        geoms = layers.get(cls, [])
        n = len(geoms)
        areas = np.array([g.area for g in geoms]) if geoms else np.array([], dtype=float)
        total_m2 = float(areas.sum()) if len(areas) > 0 else 0.0
        max_pct = float(areas.max() / total_m2 * 100) if total_m2 > 0 else 0.0
        mm2 = areas * _MM2
        med_mm2 = float(np.median(mm2)) if len(mm2) > 0 else None
        pct_small = float((mm2 < 1.0).mean() * 100) if len(mm2) > 0 else None
        cov_pct = None
        if ffco_ref is not None and ffco_ref.area > 0 and geoms:
            cls_union = unary_union(geoms)
            if not cls_union.is_empty:
                cov_pct = float(ffco_ref.intersection(cls_union).area / ffco_ref.area * 100)
            else:
                cov_pct = 0.0
        result[cls] = {
            "n": n,
            "total_ha": round(total_m2 / 1e4, 4),
            "max_pct": round(max_pct, 2),
            "med_mm2": round(med_mm2, 4) if med_mm2 is not None else None,
            "pct_small": round(pct_small, 2) if pct_small is not None else None,
            "cov_pct": round(cov_pct, 2) if cov_pct is not None else None,
        }
    return result


# ── Runner principal ──────────────────────────────────────────────────────────

def run_calibration(
    out_kp: pathlib.Path,
    cfg: dict,
    crs: str,
    rois_gpkg: pathlib.Path,
    rois_layer: str,
    class_field: str,
    split_field: str,
    id_field: str,
    out_dir: pathlib.Path,
    bbox: tuple[float, float, float, float] | None = None,
    ffco_ref: Any | None = None,
) -> dict:
    """Point d'entrée principal — ne touche aucun fichier de production.

    Exige la présence de pullauta.ini dans out_kp/.
    Refuse si out_dir contient déjà des fichiers.
    """
    import geopandas as gpd

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _check_output_dir_empty(out_dir)

    # 1 — INI obligatoire
    ini_path = _require_ini(pathlib.Path(out_kp))
    from src.kp_raster import KP_FIRST_GREEN, load_tiles, mosaic, read_ini_vege_params

    params = read_ini_vege_params(ini_path)
    cell_size_m, cell_size_source = _read_greendetectsize_verbose(ini_path)
    vect_cfg = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {})
    tol = float(vect_cfg.get("coverage_simplify_m", 2.0))

    log.info("KP params : n_shades=%d tone=%d greendetectsize=%d (source=%s) ini=%s",
             params["n_shades"], params["lightgreentone"], cell_size_m, cell_size_source,
             ini_path.name)

    # 2 — Tuiles (interdiction vegetation.png et merged*)
    tiles = load_tiles(pathlib.Path(out_kp), params, prefer=vect_cfg.get("input", "auto"))
    _validate_tile_sources(tiles)
    tile_sources = [str(t.path) for t in tiles]
    log.info("Sources KP validées : %d tuile(s)", len(tiles))

    labels, res_m, west, north = mosaic(tiles, bbox=bbox)

    all_shades = list(range(KP_FIRST_GREEN, KP_FIRST_GREEN + params["n_shades"]))
    observed_shades = [s for s in all_shades if int(np.sum(labels == s)) > 0]
    if not observed_shades:
        raise ValueError("Aucun shade vert observé dans la mosaïque KP.")
    log.info("Shades verts observés : %s", observed_shades)

    # 3 — Mapping fixe (validation des codes)
    fixed_mapping = load_fixed_mapping(cfg)

    # Analyse structurée de la couverture des shades (remplace log.warning seul)
    n_pixels_per_shade = {s: int(np.sum(labels == s)) for s in observed_shades}
    total_green_pixels = sum(n_pixels_per_shade.values())
    shade_coverage: dict = {
        "total_green_pixels": total_green_pixels,
        "covered_by_mapping": [],
        "explicitly_white": [],
        "absent_from_mapping": [],
    }
    for _s in observed_shades:
        _n_px = n_pixels_per_shade[_s]
        _pct = round(_n_px / total_green_pixels * 100, 2) if total_green_pixels > 0 else None
        _entry: dict = {"shade": _s, "n_pixels": _n_px, "pct_of_green": _pct}
        if _s in fixed_mapping:
            if fixed_mapping[_s] == 0:
                shade_coverage["explicitly_white"].append(
                    {**_entry, "status": "explicitly_white_no_vegetation_class"}
                )
            else:
                shade_coverage["covered_by_mapping"].append(_s)
        else:
            shade_coverage["absent_from_mapping"].append(
                {**_entry, "status": "absent_from_shade_to_isom"}
            )
            log.warning("Shade %d (%d px, %.1f%% des verts) absent de shade_to_isom",
                        _s, _n_px, _pct or 0.0)

    # 4 — ROIs + cellules
    records = load_rois(rois_gpkg, rois_layer, class_field, split_field, id_field, crs)
    roi_cells = collect_roi_cells(
        records, labels, res_m, west, north, cell_size_m, observed_shades,
    )

    n_calib = sum(1 for r in roi_cells if r.split == "calibration" and r.cls in _ISOM_CLASSES)
    n_val = sum(1 for r in roi_cells if r.split == "validation" and r.cls in _ISOM_CLASSES)
    if n_calib == 0:
        raise ValueError("Aucune ROI 406/408/410 de calibration avec des cellules valides.")
    log.info("ROIs utilisables : %d calibration, %d validation (406/408/410)", n_calib, n_val)

    # 5 — Calibration (seuils gelés avant évaluation validation)
    t1, t2, calib_report = calibrate_thresholds(roi_cells, observed_shades, split="calibration")
    calibrated_mapping = thresholds_to_mapping(t1, t2, observed_shades)
    log.info("Seuils calibrés : t1=%d t2=%d  macro-F1_calib=%.4f", t1, t2, calib_report["macro_f1"])

    val_report = (
        evaluate_mapping(roi_cells, calibrated_mapping, split="validation")
        if n_val > 0 else {"note": "Aucune ROI 406/408/410 de validation disponible."}
    )

    # Commission 405 (split validation — évaluation hors données de calibration)
    commission_fixed = _commission_405(roi_cells, fixed_mapping, "validation")
    commission_calib = _commission_405(roi_cells, calibrated_mapping, "validation")

    # Matrice de diagnostic
    matrix_calib = _diagnostic_matrix(roi_cells, calibrated_mapping, "calibration")
    matrix_val = (_diagnostic_matrix(roi_cells, calibrated_mapping, "validation")
                  if n_val > 0 else None)

    # Taux de non-détection par classe de référence (split validation §4.6)
    non_detection: dict = {}
    if n_val > 0:
        for cls in _ISOM_CLASSES:
            rois_cls = [r for r in roi_cells if r.cls == cls and r.split == "validation"]
            n_green = sum(len(r.sample.cells_green) for r in rois_cls)
            n_no_pred = sum(r.sample.n_no_prediction for r in rois_cls)
            n_covered = n_green + n_no_pred
            non_detection[str(cls)] = {
                "split": "validation",
                "n_no_prediction": n_no_pred,
                "n_covered": n_covered,
                "non_detection_rate": round(n_no_pred / n_covered, 4) if n_covered > 0 else None,
            }
    else:
        non_detection = {
            "note": "Aucune ROI de validation disponible — taux de non-détection non calculé.",
        }

    # 6 — Polygonisation des deux variantes
    fixed_layers = polygonize_variant(labels, fixed_mapping, res_m, west, north, crs, tol=tol)
    calibrated_layers = polygonize_variant(
        labels, calibrated_mapping, res_m, west, north, crs, tol=tol,
    )

    # 7 — Écriture GPKG
    for out_name, lyr_dict in (
        ("kp_vectorize_fixed.gpkg", fixed_layers),
        ("kp_vectorize_calibrated.gpkg", calibrated_layers),
    ):
        for code, geoms in lyr_dict.items():
            gdf = gpd.GeoDataFrame(
                {"geometry": geoms, "class": [code] * len(geoms)}, crs=crs,
            )
            gdf.to_file(str(out_dir / out_name), layer=f"veg_{code}", driver="GPKG")
        log.info("GPKG écrit : %s", out_name)

    # 8 — QA + max_pct
    fixed_qa = _qa_layers(fixed_layers, ffco_ref)
    calib_qa = _qa_layers(calibrated_layers, ffco_ref)

    max_pct_checks: dict[str, dict] = {}
    for cls in _ISOM_CLASSES:
        max_pct_checks[str(cls)] = check_max_pct(
            calib_qa[cls]["max_pct"], fixed_qa[cls]["max_pct"], cls,
        )

    # 9 — Critères géométriques
    geo_fixed = compute_geometric_criteria(fixed_layers, ffco_ref)
    geo_calib = compute_geometric_criteria(calibrated_layers, ffco_ref)

    # 10 — Taux pct_non_constant par classe (calibration)
    pct_nc_by_cls: dict[str, float | None] = {}
    for cls in _ISOM_CLASSES:
        vals = [r.sample.pct_non_constant for r in roi_cells
                if r.cls == cls and r.split == "calibration"]
        pct_nc_by_cls[str(cls)] = round(float(np.mean(vals)), 2) if vals else None

    # 11 — Statut
    has_hard_reject = any(v["reject_hard"] for v in max_pct_checks.values())
    has_absent_class = any(calib_qa[cls]["n"] == 0 for cls in _ISOM_CLASSES)
    all_same_pred = len(set(calibrated_mapping.values())) == 1 if calibrated_mapping else True

    if has_hard_reject or has_absent_class:
        status = "reject_3class"
        reasons: list[str] = []
        if has_hard_reject:
            bad = [c for c in _ISOM_CLASSES if max_pct_checks[str(c)]["reject_hard"]]
            reasons.append(f"max_pct > 50% pour classes {bad}")
        if has_absent_class:
            absent = [c for c in _ISOM_CLASSES if calib_qa[c]["n"] == 0]
            reasons.append(f"classes absentes du résultat calibré : {absent}")
    elif all_same_pred:
        status = "inconclusive"
        reasons = ["mapping calibré dégénéré — toutes les cellules assignées à une seule classe"]
    else:
        status = "candidate_for_review"
        reasons = ["diagnostic disponible — seuils d'acceptation à fixer par le porteur"]

    report: dict = {
        "module": "kp_vectorize",
        "out_kp": str(out_kp),
        "crs": crs,
        "res_m": res_m,
        "kp_params": params,
        "greendetectsize": cell_size_m,
        "greendetectsize_source": cell_size_source,
        "tile_sources": tile_sources,
        "fixed_mapping": {str(k): v for k, v in fixed_mapping.items()},
        "observed_shades": observed_shades,
        "shade_coverage": shade_coverage,
        "ffco_ref": {
            "provided": ffco_ref is not None,
            **(
                {
                    "unavailable_metrics": [
                        "geometric_criteria.*.coverage_10m_recall_pct",
                        "geometric_criteria.*.ratio_utile_pct",
                        "qa.*.*.cov_pct",
                    ],
                    "note": (
                        "Fournir --ffco pour les métriques de couverture FFCO. "
                        "Ces métriques sont None (pas 0) quand ffco_ref est absent."
                    ),
                }
                if ffco_ref is None else {}
            ),
        },
        "calibration": {
            "t1": t1, "t2": t2,
            "calibrated_mapping": {str(k): v for k, v in calibrated_mapping.items()},
            "calib_report": calib_report,
            "validation_report": val_report,
            "commission_405_fixed": commission_fixed,
            "commission_405_calibrated": commission_calib,
            "diagnostic_matrix_calibration": matrix_calib,
            "diagnostic_matrix_validation": matrix_val,
            "non_detection_by_class": non_detection,
            "pct_non_constant_by_class": pct_nc_by_cls,
        },
        "qa": {
            "fixed": {str(k): v for k, v in fixed_qa.items()},
            "calibrated": {str(k): v for k, v in calib_qa.items()},
        },
        "geometric_criteria": {
            "fixed": geo_fixed,
            "calibrated": geo_calib,
        },
        "max_pct_checks": max_pct_checks,
        "status": status,
        "status_reason": reasons,
    }

    report_path = out_dir / "kp_vectorize_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Rapport : %s  statut=%s", report_path.name, status)
    return report


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    import yaml

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_kp", help="répertoire out_kp_{terrain}/")
    parser.add_argument("rois_gpkg", help="GPKG des ROIs FFCO")
    parser.add_argument("out_dir", help="répertoire de sortie vide ou inexistant")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--terrain", required=True)
    parser.add_argument("--layer", default=None)
    parser.add_argument("--class-field", default="class")
    parser.add_argument("--split-field", default="split")
    parser.add_argument("--id-field", default="roi_id")
    parser.add_argument(
        "--ffco", default=None,
        help="GPKG ou GeoJSON contenant la géométrie FFCO de référence. "
             "Si fourni, calcule les métriques de couverture (recall à 10 m, ratio utile). "
             "Plusieurs entités sont réunies par union géométrique.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    cfg = yaml.safe_load(pathlib.Path(args.config).read_text(encoding="utf-8"))
    terrain_cfg = cfg.get("terrains", {}).get(args.terrain, {})
    crs: str = terrain_cfg.get("crs", "EPSG:2154")
    bbox = terrain_cfg.get("bbox")

    rois_gpkg = pathlib.Path(args.rois_gpkg)
    if not rois_gpkg.exists():
        raise SystemExit(f"ROIs GPKG introuvable : {rois_gpkg}")

    layer = args.layer
    if layer is None:
        import geopandas as gpd
        try:
            layers = gpd.list_layers(str(rois_gpkg))
            layer = str(layers.iloc[0]["name"])
            log.info("Couche ROIs auto-détectée : %s", layer)
        except Exception:
            raise SystemExit(
                "Impossible de détecter la couche ROIs — utiliser --layer pour la spécifier."
            )

    ffco_ref = None
    if args.ffco:
        import geopandas as gpd
        from shapely.ops import unary_union
        ffco_path = pathlib.Path(args.ffco)
        if not ffco_path.exists():
            raise SystemExit(f"--ffco : fichier introuvable : {ffco_path}")
        ffco_gdf = gpd.read_file(str(ffco_path))
        if ffco_gdf.crs is None:
            raise SystemExit("--ffco : la couche FFCO n'a pas de CRS défini.")
        if ffco_gdf.crs.to_string() != crs:
            ffco_gdf = ffco_gdf.to_crs(crs)
        ffco_ref = unary_union(ffco_gdf.geometry.values)
        if not hasattr(ffco_ref, "is_empty") or ffco_ref.is_empty:
            raise SystemExit("--ffco : la géométrie FFCO est vide après union.")
        log.info("FFCO chargée : %d entité(s), aire=%.1f ha",
                 len(ffco_gdf), ffco_ref.area / 1e4)

    run_calibration(
        out_kp=pathlib.Path(args.out_kp),
        cfg=cfg,
        crs=crs,
        rois_gpkg=rois_gpkg,
        rois_layer=layer,
        class_field=args.class_field,
        split_field=args.split_field,
        id_field=args.id_field,
        out_dir=pathlib.Path(args.out_dir),
        bbox=tuple(bbox) if bbox else None,
        ffco_ref=ffco_ref,
    )


if __name__ == "__main__":
    main()
