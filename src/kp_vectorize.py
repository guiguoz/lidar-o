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


def load_fixed_mapping(cfg: dict) -> dict[int, int]:
    """Charge shade_to_isom depuis config.yaml.

    Retourne {bit_kp: isom_code} où isom_code ∈ {0, 406, 408, 410}.
    Lève ValueError si la clé est absente.
    """
    raw = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {}).get("shade_to_isom")
    if not raw:
        raise ValueError(
            "karttapullautin.vectorization.shade_to_isom absent de config.yaml — "
            "impossible de charger le mapping fixe."
        )
    return {int(k): int(v) for k, v in raw.items()}


# ── ROIs ──────────────────────────────────────────────────────────────────────

@dataclass
class RoiRecord:
    roi_id: Any
    cls: int       # 406, 408, 410 (voire 405)
    split: str     # "calibration" | "validation"
    eroded: Any    # shapely geometry ou None


def _validate_rois_fields(
    columns: list[str],
    class_field: str,
    split_field: str,
    id_field: str,
) -> None:
    missing = [f for f in (class_field, split_field, id_field) if f not in columns]
    if missing:
        raise ValueError(
            f"Champs manquants dans les ROIs : {missing}. "
            f"Attendu : class_field='{class_field}', split_field='{split_field}', "
            f"id_field='{id_field}'. Champs disponibles : {columns}"
        )


def _validate_rois_values(
    gdf: Any,
    class_field: str,
    split_field: str,
) -> None:
    invalid_cls = set(int(v) for v in gdf[class_field].unique()) - {405, 406, 408, 410}
    if invalid_cls:
        raise ValueError(
            f"Valeurs inconnues dans '{class_field}' : {sorted(invalid_cls)}. "
            f"Valeurs autorisées : 405, 406, 408, 410."
        )
    invalid_split = set(str(v) for v in gdf[split_field].unique()) - {"calibration", "validation"}
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
) -> tuple[np.ndarray, float]:
    """Échantillonne les cellules sémantiques de `cell_size_m` m dans une ROI érodée.

    Aligne la grille de cellules sur l'origine (west, north) du raster.
    Une cellule est retenue uniquement si tous ses pixels sont dans la ROI.

    Retourne (cell_modes, pct_non_constant) :
    - cell_modes  : valeurs modales de chaque cellule retenue (uint8)
    - pct_non_constant : proportion de cellules dont les pixels ne sont pas tous identiques
    """
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin
    import shapely.geometry as sg

    if roi_geom is None or roi_geom.is_empty:
        return np.array([], dtype=np.uint8), 0.0

    height, width = labels.shape
    transform = from_origin(west, north, res_m, res_m)

    mask = ~geometry_mask(
        [sg.mapping(roi_geom)], out_shape=(height, width),
        transform=transform, all_touched=False,
    )

    scale = max(1, int(round(cell_size_m / res_m)))
    cell_modes: list[int] = []
    non_constant = 0

    for r0 in range(0, height, scale):
        for c0 in range(0, width, scale):
            r1 = min(r0 + scale, height)
            c1 = min(c0 + scale, width)
            # Cellule entière dans la ROI uniquement
            if not mask[r0:r1, c0:c1].all():
                continue
            cell_vals = labels[r0:r1, c0:c1].flatten()
            # Ignorer les cellules entièrement fond
            if int(cell_vals.max()) == 0:
                continue
            vals, cnts = np.unique(cell_vals, return_counts=True)
            mode_val = int(vals[cnts.argmax()])
            cell_modes.append(mode_val)
            if len(vals) > 1:
                non_constant += 1

    arr = np.array(cell_modes, dtype=np.uint8)
    pct_nc = float(non_constant / len(arr) * 100) if len(arr) > 0 else 0.0
    return arr, pct_nc


# ── Données par ROI pour la calibration ──────────────────────────────────────

@dataclass
class RoiCells:
    roi_id: Any
    cls: int
    split: str
    cells: np.ndarray   # valeurs de shade (bit KP) dans cette ROI


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

    Les shades hors de valid_shades (fond=0, jaune=1) sont filtrés.
    """
    valid_set = np.array(valid_shades, dtype=np.uint8)
    result: list[RoiCells] = []
    for rec in records:
        if rec.eroded is None:
            continue
        cells, pct_nc = sample_semantic_cells(
            labels, res_m, west, north, rec.eroded, cell_size_m=cell_size_m,
        )
        cells = cells[np.isin(cells, valid_set)]
        if len(cells) == 0:
            log.warning("ROI %s (cls=%d, split=%s) : aucune cellule verte après filtrage",
                        rec.roi_id, rec.cls, rec.split)
            continue
        if pct_nc > 0:
            log.info("ROI %s : %.1f%% cellules non-constantes (mode appliqué)", rec.roi_id, pct_nc)
        result.append(RoiCells(roi_id=rec.roi_id, cls=rec.cls, split=rec.split, cells=cells))
    return result


# ── Calibration ───────────────────────────────────────────────────────────────

def _weighted_macro_f1(
    predictions: np.ndarray,
    truths: np.ndarray,
    weights: np.ndarray,
    classes: tuple[int, ...] = _ISOM_CLASSES,
) -> float:
    """Macro-F1 pondéré sur un vecteur de prédictions/vérités."""
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


def _build_pred_arrays(
    roi_cells: list[RoiCells],
    t1: int,
    t2: int,
    split: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Construit (prédictions, vérités, poids) pour un split et deux seuils donnés.

    Poids : 1 / (n_classes × n_rois_de_la_classe × n_cells_dans_la_roi).
    """
    subset = [r for r in roi_cells if r.split == split]
    rois_per_cls: dict[int, int] = {
        cls: sum(1 for r in subset if r.cls == cls) for cls in _ISOM_CLASSES
    }
    n_classes = sum(1 for n in rois_per_cls.values() if n > 0)

    preds: list[int] = []
    truths: list[int] = []
    wts: list[float] = []
    for r in subset:
        n_rois = rois_per_cls.get(r.cls, 1)
        n_cells = len(r.cells)
        if n_cells == 0 or n_rois == 0 or n_classes == 0:
            continue
        w = 1.0 / (n_classes * n_rois * n_cells)
        for shade in r.cells:
            s = int(shade)
            pred = 406 if s <= t1 else (408 if s <= t2 else 410)
            preds.append(pred)
            truths.append(r.cls)
            wts.append(w)

    return (
        np.array(preds, dtype=np.int32),
        np.array(truths, dtype=np.int32),
        np.array(wts, dtype=np.float64),
    )


def calibrate_thresholds(
    roi_cells: list[RoiCells],
    valid_shades: list[int],
    split: str = "calibration",
) -> tuple[int, int, dict]:
    """Calibre deux seuils monotones sur les ROIs du split indiqué.

    Mapping résultant : shade ≤ t1 → 406 ; t1 < shade ≤ t2 → 408 ; shade > t2 → 410.
    Optimise le macro-F1 pondéré. En cas d'égalité, le couple (t1, t2) le plus petit
    est retenu (ordre lexicographique).

    Retourne (t1, t2, rapport_de_calibration).
    """
    calib = [r for r in roi_cells if r.split == split]
    if not calib:
        raise ValueError(f"Aucune ROI de split '{split}' disponible pour la calibration.")

    present_cls = {r.cls for r in calib} & set(_ISOM_CLASSES)
    if len(present_cls) < 3:
        missing = sorted(set(_ISOM_CLASSES) - present_cls)
        raise ValueError(
            f"Classes ISOM manquantes dans les ROIs de calibration : {missing}. "
            f"Classes présentes : {sorted(present_cls)}."
        )

    s_min, s_max = min(valid_shades), max(valid_shades)
    best_f1 = -1.0
    best_t1, best_t2 = s_min, s_max

    for t1 in range(s_min, s_max):
        for t2 in range(t1 + 1, s_max + 1):
            preds, truths, wts = _build_pred_arrays(calib, t1, t2, split)
            if len(preds) == 0:
                continue
            f1 = _weighted_macro_f1(preds, truths, wts)
            if f1 > best_f1:
                best_f1 = f1
                best_t1, best_t2 = t1, t2

    preds, truths, wts = _build_pred_arrays(calib, best_t1, best_t2, split)
    rois_per_cls = {cls: sum(1 for r in calib if r.cls == cls) for cls in _ISOM_CLASSES}
    per_class: dict[str, dict] = {}
    for cls in _ISOM_CLASSES:
        tp = float(wts[(preds == cls) & (truths == cls)].sum())
        fp = float(wts[(preds == cls) & (truths != cls)].sum())
        fn = float(wts[(preds != cls) & (truths == cls)].sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2.0 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        per_class[str(cls)] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

    report = {
        "t1": best_t1,
        "t2": best_t2,
        "macro_f1": round(best_f1, 4),
        "per_class": per_class,
        "n_calib_rois": len(calib),
        "rois_per_class": {str(k): v for k, v in rois_per_cls.items()},
    }
    return best_t1, best_t2, report


def thresholds_to_mapping(
    t1: int, t2: int, valid_shades: list[int],
) -> dict[int, int]:
    """Convertit deux seuils en table shade → code ISOM (identique pour toutes les cellules)."""
    mapping: dict[int, int] = {}
    for shade in valid_shades:
        if shade <= t1:
            mapping[shade] = 406
        elif shade <= t2:
            mapping[shade] = 408
        else:
            mapping[shade] = 410
    return mapping


def evaluate_mapping(
    roi_cells: list[RoiCells],
    mapping: dict[int, int],
    split: str,
) -> dict:
    """Évalue un mapping gelé sur les ROIs d'un split. Ne modifie pas le mapping."""
    subset = [r for r in roi_cells if r.split == split]
    if not subset:
        return {"error": f"Aucune ROI de split '{split}'."}

    present_cls = {r.cls for r in subset} & set(_ISOM_CLASSES)
    rois_per_cls = {cls: sum(1 for r in subset if r.cls == cls) for cls in _ISOM_CLASSES}
    n_classes = len(present_cls)

    preds: list[int] = []
    truths: list[int] = []
    wts: list[float] = []
    for r in subset:
        n_rois = rois_per_cls.get(r.cls, 0)
        n_cells = len(r.cells)
        if n_cells == 0 or n_rois == 0 or n_classes == 0:
            continue
        w = 1.0 / (n_classes * n_rois * n_cells)
        for shade in r.cells:
            pred = mapping.get(int(shade), 0)
            preds.append(pred)
            truths.append(r.cls)
            wts.append(w)

    if not preds:
        return {"error": "Aucune cellule disponible."}

    preds_arr = np.array(preds, dtype=np.int32)
    truths_arr = np.array(truths, dtype=np.int32)
    wts_arr = np.array(wts, dtype=np.float64)
    macro_f1 = _weighted_macro_f1(preds_arr, truths_arr, wts_arr)

    per_class: dict[str, dict] = {}
    for cls in _ISOM_CLASSES:
        tp = float(wts_arr[(preds_arr == cls) & (truths_arr == cls)].sum())
        fp = float(wts_arr[(preds_arr == cls) & (truths_arr != cls)].sum())
        fn = float(wts_arr[(preds_arr != cls) & (truths_arr == cls)].sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2.0 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        per_class[str(cls)] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

    return {
        "split": split,
        "n_rois": len(subset),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "status_note": "diagnostic disponible — seuils d'acceptation à fixer par le porteur",
    }


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

    Retourne {406: [geoms], 408: [geoms], 410: [geoms]}.
    Ne modifie pas `labels`.
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
            continue
        dn_raster[labels == shade] = ISOM_TO_DN[isom]

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
        if shapely.coverage_is_valid(geom_arr_cls):
            all_geoms.extend(geoms)
            all_codes.extend([isom] * len(geoms))
        else:
            log.warning("polygonize_variant : couverture invalide pour classe %d — ignorée", isom)

    layers: dict[int, list] = {406: [], 408: [], 410: []}
    if not all_geoms:
        return layers

    geom_arr = np.array(all_geoms, dtype=object)
    simplified = shapely.coverage_simplify(geom_arr, tolerance=tol, simplify_boundary=True)
    for geom, code in zip(simplified, all_codes):
        if geom is not None and not geom.is_empty:
            layers[code].append(geom)

    return layers


# ── Métriques max_pct §5.3 ────────────────────────────────────────────────────

def check_max_pct(max_pct: float, max_pct_fixed: float, cls: int) -> dict:
    """Applique les trois règles max_pct (§5.3) et retourne un dict de statuts.

    - reject_hard    : max_pct > 50 % (plafond absolu, indépendant de la baseline)
    - alert_relative : max_pct > 1,5 × max_pct_fixed (alerte relative)
    - alert_406      : cls==406 et max_pct > 15 % (alerte percolation)
    """
    reject_hard = max_pct > 50.0
    alert_relative = (max_pct_fixed > 0.0) and (max_pct > 1.5 * max_pct_fixed)
    alert_406 = (cls == 406) and (max_pct > 15.0)
    return {
        "reject_hard": reject_hard,
        "alert_relative": alert_relative,
        "alert_406": alert_406,
        "max_pct": round(max_pct, 2),
        "max_pct_fixed": round(max_pct_fixed, 2),
    }


def _qa_layers(layers: dict[int, list]) -> dict[int, dict]:
    """Surface totale, n et max_pct par classe ISOM."""
    result: dict[int, dict] = {}
    for cls in _ISOM_CLASSES:
        geoms = layers.get(cls, [])
        n = len(geoms)
        areas = np.array([g.area for g in geoms]) if geoms else np.array([], dtype=float)
        total_area = float(areas.sum()) if len(areas) > 0 else 0.0
        max_pct_val = float(areas.max() / total_area * 100) if total_area > 0 else 0.0
        result[cls] = {
            "n": n,
            "total_ha": round(total_area / 1e4, 4),
            "max_pct": round(max_pct_val, 2),
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
) -> dict:
    """Point d'entrée principal — ne touche aucun fichier de production.

    Lève FileExistsError si un fichier de sortie existe déjà.
    """
    import geopandas as gpd

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _OUT_NAMES = (
        "kp_vectorize_fixed.gpkg",
        "kp_vectorize_calibrated.gpkg",
        "kp_vectorize_report.json",
    )
    for name in _OUT_NAMES:
        if (out_dir / name).exists():
            raise FileExistsError(
                f"{out_dir / name} existe déjà — choisir un autre répertoire de sortie."
            )

    # 1 — Paramètres KP
    from src.kp_raster import KP_FIRST_GREEN, load_tiles, mosaic, read_ini_vege_params

    ini_path = pathlib.Path(out_kp) / "pullauta.ini"
    params = read_ini_vege_params(ini_path if ini_path.exists() else None)
    cell_size_m = read_greendetectsize(ini_path if ini_path.exists() else None)
    vect_cfg = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {})
    tol = float(vect_cfg.get("coverage_simplify_m", 2.0))

    log.info("KP params : n_shades=%d tone=%d greendetectsize=%d",
             params["n_shades"], params["lightgreentone"], cell_size_m)

    # 2 — Mosaïque
    tiles = load_tiles(pathlib.Path(out_kp), params, prefer=vect_cfg.get("input", "auto"))
    labels, res_m, west, north = mosaic(tiles, bbox=bbox)

    all_shades = list(range(KP_FIRST_GREEN, KP_FIRST_GREEN + params["n_shades"]))
    observed_shades = [s for s in all_shades if int(np.sum(labels == s)) > 0]
    log.info("Shades verts observés : %s", observed_shades)

    if not observed_shades:
        raise ValueError("Aucun shade vert observé dans la mosaïque KP.")

    # 3 — Mapping fixe
    fixed_mapping = load_fixed_mapping(cfg)

    # 4 — ROIs + cellules
    records = load_rois(rois_gpkg, rois_layer, class_field, split_field, id_field, crs)
    roi_cells = collect_roi_cells(
        records, labels, res_m, west, north, cell_size_m, observed_shades,
    )

    n_calib = sum(1 for r in roi_cells if r.split == "calibration")
    n_val = sum(1 for r in roi_cells if r.split == "validation")
    if n_calib == 0:
        raise ValueError("Aucune ROI de calibration avec des cellules valides.")
    log.info("ROIs utilisables : %d calibration, %d validation", n_calib, n_val)

    # 5 — Calibration (sur calibration uniquement, seuils gelés pour validation)
    t1, t2, calib_report = calibrate_thresholds(roi_cells, observed_shades, split="calibration")
    calibrated_mapping = thresholds_to_mapping(t1, t2, observed_shades)
    log.info("Seuils calibrés : t1=%d t2=%d  macro-F1_calib=%.4f", t1, t2, calib_report["macro_f1"])

    val_report = evaluate_mapping(roi_cells, calibrated_mapping, split="validation") \
        if n_val > 0 else {"note": "Aucune ROI de validation disponible."}

    # 6 — Polygonisation des deux variantes (même traitement géométrique)
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
    fixed_qa = _qa_layers(fixed_layers)
    calib_qa = _qa_layers(calibrated_layers)

    max_pct_checks: dict[str, dict] = {}
    for cls in _ISOM_CLASSES:
        max_pct_checks[str(cls)] = check_max_pct(
            calib_qa[cls]["max_pct"], fixed_qa[cls]["max_pct"], cls,
        )

    # 9 — Statut
    has_hard_reject = any(v["reject_hard"] for v in max_pct_checks.values())
    has_absent_class = any(calib_qa[cls]["n"] == 0 for cls in _ISOM_CLASSES)
    degenerate = sum(1 for cls in _ISOM_CLASSES if calibrated_mapping and
                     all(v == list(calibrated_mapping.values())[0]
                         for v in calibrated_mapping.values())) > 0

    if has_hard_reject or has_absent_class:
        status = "reject_3class"
        status_reason: list[str] = []
        if has_hard_reject:
            bad = [c for c in _ISOM_CLASSES if max_pct_checks[str(c)]["reject_hard"]]
            status_reason.append(f"max_pct > 50% pour classes {bad}")
        if has_absent_class:
            absent = [c for c in _ISOM_CLASSES if calib_qa[c]["n"] == 0]
            status_reason.append(f"classes absentes du résultat calibré : {absent}")
    elif degenerate:
        status = "inconclusive"
        status_reason = ["le mapping calibré est dégénéré (toutes les cellules assignées à une seule classe)"]
    else:
        status = "candidate_for_review"
        status_reason = ["diagnostic disponible — seuils d'acceptation à fixer par le porteur"]

    report: dict = {
        "module": "kp_vectorize",
        "out_kp": str(out_kp),
        "crs": crs,
        "res_m": res_m,
        "kp_params": params,
        "greendetectsize": cell_size_m,
        "fixed_mapping": {str(k): v for k, v in fixed_mapping.items()},
        "observed_shades": observed_shades,
        "calibration": {
            "t1": t1,
            "t2": t2,
            "calibrated_mapping": {str(k): v for k, v in calibrated_mapping.items()},
            "calib_report": calib_report,
            "validation_report": val_report,
        },
        "qa": {
            "fixed": {str(k): v for k, v in fixed_qa.items()},
            "calibrated": {str(k): v for k, v in calib_qa.items()},
        },
        "max_pct_checks": max_pct_checks,
        "status": status,
        "status_reason": status_reason,
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
    parser.add_argument("rois_gpkg", help="fichier GPKG des ROIs FFCO")
    parser.add_argument("out_dir", help="répertoire de sortie (ne doit pas contenir les fichiers de sortie)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--terrain", required=True)
    parser.add_argument("--layer", default=None, help="nom de couche ROIs dans le GPKG")
    parser.add_argument("--class-field", default="class")
    parser.add_argument("--split-field", default="split")
    parser.add_argument("--id-field", default="roi_id")
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
                "Impossible de détecter la couche ROIs automatiquement — "
                "utiliser --layer pour la spécifier."
            )

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
    )


if __name__ == "__main__":
    main()
