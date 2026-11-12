"""Mode supervised_e — inférence végétation depuis LAZ bruts.

Pipeline :
  1. Calcul strates étendues (9 bins HAG + ordres de retour) depuis LAZ
  2. Dérivation strates T (4 bandes) depuis les bins E (correspondance exacte)
  3. Construction descripteurs T (30) + E (33) = 63 features
  4. Chargement modèle final + imputation + inférence
  5. Sauvegarde raster de prédiction géoréférencé

Aucune dépendance vers des chemins de référence cartographiques, identifiants de terrain
ou étiquettes supervisées à l'inférence.

Le mode reste expérimental et ne prétend pas à une exactitude identique aux cartes de référence.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
import pickle
import sys
from typing import Any, Iterator

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import shapes
from rasterio.transform import from_bounds, rowcol
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import make_valid
from scipy.ndimage import distance_transform_edt

_SRC = pathlib.Path(__file__).resolve().parent
_ROOT = _SRC.parent
_LOTO = _ROOT / "experiments" / "loto_v1"
_SUPERVISED_V1 = _ROOT / "experiments" / "bois_dupont" / "supervised_v1"

for _p in [str(_ROOT), str(_SRC), str(_LOTO), str(_SUPERVISED_V1)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from omapmaker_ref import _read_points  # noqa: E402  (src/omapmaker_ref.py)
from descriptors import (              # noqa: E402  (supervised_v1/descriptors.py)
    build_descriptors, N_FEATURES as N_FEATURES_T, MIN_SUPPORT, SCALES,
)
from descriptors_ext import (          # noqa: E402  (loto_v1/descriptors_ext.py)
    build_ext_descriptors, N_EXT_FEATURES, load_ext_strates,
)

log = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
RES_M: float = 2.0
CRS_DEFAULT: str = "EPSG:2154"

# 9 bins HAG (mêmes bornes que compute_ext_strates.py)
_BIN_EDGES: list[float] = [0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, np.inf]
N_BINS: int = 9

# Correspondance bins E → strates T
# T.ground = b0, T.low = b1+b2+b3, T.medium = b4+b5, T.high = b6+b7+b8
_T_FROM_BINS: list[list[int]] = [[0], [1, 2, 3], [4, 5], [6, 7, 8]]

_GROUND_CLASSES: frozenset[int] = frozenset({2, 9})
N_FEATURES_E_TOTAL: int = N_FEATURES_T + N_EXT_FEATURES  # 30 + 33 = 63

# Modèle final par défaut
DEFAULT_MODEL_PATH: pathlib.Path = _LOTO / "final_model" / "model_e_final.pkl"

NODATA_CODE: int = 255
PALETTE: dict[int, tuple[int, int, int]] = {
    0: (255, 201,  15),  # découvert
    1: (255, 255, 255),  # blanc
    2: (204, 255, 179),  # veg_406
    3: (153, 255, 102),  # veg_408
    4: ( 51, 255,   0),  # veg_410
}

# Cache invalidation : ces paramètres changent ↔ cache invalide
_CACHE_VERSION = "v1-res2m-9bins"

EXPORT_MODE_FAITHFUL    = "faithful"
EXPORT_MODE_GENERALIZED = "generalized"
_GENERALIZED_MIN_AREA_M2 = 16.0  # supprime composantes < 1 pixel (2×2 m)

# classe 1 (blanc) = fond implicite — pas de polygone créé
_CLASS_TO_ISOM: dict[int, int] = {0: 401, 2: 406, 3: 408, 4: 410}


# ── DTM ───────────────────────────────────────────────────────────────────────

def _compute_dtm(
    pts_ground: np.ndarray,
    bbox: list[float],
    h: int,
    w: int,
) -> np.ndarray:
    dtm = np.full((h, w), np.nan, dtype=np.float64)
    if len(pts_ground) == 0:
        log.warning("DTM : aucun point sol")
        return dtm

    xmin, ymin, xmax, ymax = bbox
    transform = from_bounds(xmin, ymin, xmax, ymax, w, h)
    rows, cols = rowcol(transform, pts_ground["X"], pts_ground["Y"])
    valid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    rows, cols, zs = rows[valid], cols[valid], pts_ground["Z"][valid]

    for r, c, z in zip(rows, cols, zs):
        if np.isnan(dtm[r, c]) or z < dtm[r, c]:
            dtm[r, c] = z

    nodata = np.isnan(dtm)
    if nodata.any():
        indices = distance_transform_edt(nodata, return_distances=False, return_indices=True)
        dtm = dtm[tuple(indices)]
    return dtm


# ── Strates ───────────────────────────────────────────────────────────────────

def _check_cache_valid(cache_path: pathlib.Path) -> bool:
    """Vérifie qu'un cache .npz est lisible et contient la bonne version."""
    if not cache_path.exists():
        return False
    try:
        with np.load(str(cache_path)) as d:
            version = str(d.get("cache_version", b"")).strip("b'\"")
            return version == _CACHE_VERSION
    except Exception:
        return False


def compute_ext_strates(
    laz_files: list[pathlib.Path],
    bbox: list[float],
    h: int,
    w: int,
    cache_path: pathlib.Path | None = None,
    force: bool = False,
) -> dict[str, np.ndarray]:
    """Calcule les strates étendues depuis les LAZ.

    Retourne un dict avec :
      bins     (9, H, W) float32  — comptes bruts par tranche HAG
      n_first  (H, W)   float32
      n_last   (H, W)   float32
      n_unique (H, W)   float32

    Si cache_path est fourni et valide : recharge directement.
    Écriture atomique si cache_path est fourni.
    """
    if cache_path and not force and _check_cache_valid(cache_path):
        log.info("Strates ext : cache valide rechargé (%s)", cache_path.name)
        with np.load(str(cache_path)) as d:
            return {k: d[k] for k in ("bins", "n_first", "n_last", "n_unique")}

    missing = [f for f in laz_files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"LAZ manquants : {missing}")

    transform = from_bounds(*bbox[:2], *bbox[2:], w, h)

    # Passe 1 : DTM
    log.info("Strates ext : lecture sol (classes 2+9)...")
    ground_expr = "Classification == 2 || Classification == 9"
    pts_ground = _read_points(laz_files, tuple(bbox), expression=ground_expr)
    dtm = _compute_dtm(pts_ground, bbox, h, w)
    del pts_ground

    # Passe 2 : strates fines + ordres de retour
    log.info("Strates ext : lecture tous retours non-withheld...")
    pts = _read_points(laz_files, tuple(bbox))
    if len(pts) == 0:
        log.warning("Aucun point — strates vides")
        return {
            "bins": np.zeros((N_BINS, h, w), dtype=np.float32),
            "n_first": np.zeros((h, w), dtype=np.float32),
            "n_last": np.zeros((h, w), dtype=np.float32),
            "n_unique": np.zeros((h, w), dtype=np.float32),
        }

    log.info("Strates ext : %d points — calcul HAG...", len(pts))
    xs = pts["X"].astype(np.float64)
    ys = pts["Y"].astype(np.float64)
    zs = pts["Z"].astype(np.float64)

    rows, cols = rowcol(transform, xs, ys)
    in_grid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    rows_g = rows[in_grid].astype(np.int32)
    cols_g = cols[in_grid].astype(np.int32)
    hag = np.maximum(0.0, zs[in_grid] - dtm[rows_g, cols_g])

    bins_grid = np.zeros((N_BINS, h, w), dtype=np.float32)
    for k in range(N_BINS):
        lo, hi = _BIN_EDGES[k], _BIN_EDGES[k + 1]
        in_bin = hag >= lo if np.isinf(hi) else (hag >= lo) & (hag < hi)
        np.add.at(bins_grid[k], (rows_g[in_bin], cols_g[in_bin]), 1.0)

    del hag, in_grid, xs, ys, zs

    # Ordres de retour
    pts_in = pts[np.nonzero(
        (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    )[0]]
    rows2, cols2 = rowcol(transform, pts_in["X"], pts_in["Y"])
    rows2 = rows2.astype(np.int32)
    cols2 = cols2.astype(np.int32)

    rn  = pts_in["ReturnNumber"].astype(np.int32)
    nor = pts_in["NumberOfReturns"].astype(np.int32)

    n_first    = np.zeros((h, w), dtype=np.float32)
    n_last_arr = np.zeros((h, w), dtype=np.float32)
    n_unique   = np.zeros((h, w), dtype=np.float32)

    is_first  = rn == 1
    is_last   = rn == nor
    is_unique = nor == 1

    np.add.at(n_first,    (rows2[is_first],  cols2[is_first]),  1.0)
    np.add.at(n_last_arr, (rows2[is_last],   cols2[is_last]),   1.0)
    np.add.at(n_unique,   (rows2[is_unique], cols2[is_unique]), 1.0)

    del pts, pts_in, rn, nor, rows2, cols2

    result = {
        "bins": bins_grid,
        "n_first": n_first,
        "n_last": n_last_arr,
        "n_unique": n_unique,
    }

    if cache_path is not None:
        _save_strates_atomic(result, cache_path, bbox, h, w, laz_files)

    return result


def _save_strates_atomic(
    data: dict[str, np.ndarray],
    out_path: pathlib.Path,
    bbox: list[float],
    h: int,
    w: int,
    laz_files: list[pathlib.Path],
) -> None:
    tmp = out_path.with_suffix(".tmp.npz")
    if tmp.exists():
        tmp.unlink()
    np.savez_compressed(
        str(tmp),
        bins=data["bins"],
        n_first=data["n_first"],
        n_last=data["n_last"],
        n_unique=data["n_unique"],
        bbox=np.array(bbox),
        res_m=np.float32(RES_M),
        laz_files=np.array([str(f) for f in laz_files]),
        cache_version=np.array(_CACHE_VERSION),
    )
    # Validation
    with np.load(str(tmp)) as v:
        assert v["bins"].shape == (N_BINS, h, w), "bins shape invalide"
        assert not np.any(np.isnan(v["bins"])), "bins NaN"
    tmp.replace(out_path)
    log.info("Cache strates ext sauvegardé : %s", out_path.name)


# ── Strates T dérivées depuis strates E ──────────────────────────────────────

def derive_t_strates(bins: np.ndarray) -> np.ndarray:
    """Dérive les 4 strates T depuis les 9 bins E.

    Correspondance :
      T.ground (0) = bin_0 [0, 0.2)
      T.low    (1) = bin_1 + bin_2 + bin_3  [0.2, 1.5)
      T.medium (2) = bin_4 + bin_5          [1.5, 3.0)
      T.high   (3) = bin_6 + bin_7 + bin_8  [3.0, +∞)

    Retourne (4, H, W) float32.
    """
    strates_t = np.stack(
        [bins[idx].sum(axis=0) for idx in _T_FROM_BINS],
        axis=0,
    ).astype(np.float32)
    return strates_t


# ── Features 63 ───────────────────────────────────────────────────────────────

def build_features(strates_data: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Construit les 63 features combinées T+E.

    Retourne :
      X_grid  (H, W, 63) float32
      support (H, W) bool
    """
    bins = strates_data["bins"]  # (9, H, W)

    # Strates T dérivées
    strates_t = derive_t_strates(bins)  # (4, H, W)

    # Descripteurs T (30 features)
    X_t, support_t = build_descriptors(strates_t)  # (H,W,30), (H,W)

    # Descripteurs E (33 features)
    X_e, support_e = build_ext_descriptors(strates_data)  # (H,W,33), (H,W)

    # Support combiné
    support = support_t & support_e

    # Concaténation
    X_all = np.concatenate([X_t, X_e], axis=-1)  # (H,W,63)

    return X_all, support


# ── Modèle ────────────────────────────────────────────────────────────────────

def load_model(model_path: pathlib.Path | None = None) -> dict[str, Any]:
    """Charge le modèle final depuis son PKL.

    Vérifie la cohérence (n_features=63) avant de retourner.
    Ne charge que depuis un chemin local explicite (pas de réseau).
    """
    path = pathlib.Path(model_path or DEFAULT_MODEL_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Modèle E final introuvable : {path}\n"
            "Exécuter experiments/loto_v1/train_final_e.py d'abord."
        )

    # Vérification empreinte optionnelle (manifeste.json dans même dossier)
    manifeste_path = path.parent / "manifeste.json"
    if manifeste_path.exists():
        import json
        with manifeste_path.open(encoding="utf-8") as f:
            manifeste = json.load(f)
        expected_sha = manifeste.get("sha256", "")
        if expected_sha:
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_sha != expected_sha:
                raise ValueError(
                    f"Empreinte SHA-256 du modèle invalide.\n"
                    f"  attendu  : {expected_sha}\n"
                    f"  calculé  : {actual_sha}\n"
                    "Le fichier a peut-être été modifié après entraînement."
                )

    with path.open("rb") as f:
        payload = pickle.load(f)  # noqa: S301 — chemin local contrôlé

    n = payload.get("n_features", -1)
    if n != N_FEATURES_E_TOTAL:
        raise ValueError(
            f"Modèle incompatible : n_features={n}, attendu {N_FEATURES_E_TOTAL}"
        )
    return payload


# ── Inférence ─────────────────────────────────────────────────────────────────

def run_inference(
    X_grid: np.ndarray,
    support: np.ndarray,
    clf: Any,
    imputer: Any,
) -> np.ndarray:
    """Prédit les catégories sur toute la grille.

    Retourne pred (H, W) uint8, NODATA_CODE=255 hors support.
    """
    h, w = support.shape
    X_flat = X_grid.reshape(-1, N_FEATURES_E_TOTAL)
    X_imp = imputer.transform(X_flat)
    pred_flat = clf.predict(X_imp).astype(np.uint8)
    pred_flat[~support.reshape(-1)] = NODATA_CODE
    return pred_flat.reshape(h, w)


# ── Export raster ─────────────────────────────────────────────────────────────

def save_prediction_raster(
    pred: np.ndarray,
    support: np.ndarray,
    bbox: list[float],
    crs: str,
    out_path: pathlib.Path,
) -> pathlib.Path:
    """Sauvegarde le raster de prédiction géoréférencé (uint8, palette).

    Canaux :
      1 : catégorie  (0-4 = classes, 255 = NODATA)
      2 : support    (1 = pixel évaluable, 0 = hors couverture LiDAR)
    """
    h, w = pred.shape
    xmin, ymin, xmax, ymax = bbox
    transform = from_bounds(xmin, ymin, xmax, ymax, w, h)

    # Écriture atomique
    tmp = out_path.with_suffix(".tmp.tif")
    if tmp.exists():
        tmp.unlink()

    with rasterio.open(
        str(tmp),
        "w",
        driver="GTiff",
        height=h, width=w,
        count=2,
        dtype=rasterio.uint8,
        crs=CRS.from_string(crs),
        transform=transform,
        compress="lzw",
        nodata=NODATA_CODE,
    ) as dst:
        dst.write(pred.astype(np.uint8), 1)
        dst.write(support.astype(np.uint8), 2)
        dst.update_tags(
            band_1="prediction (0=decouvert 1=blanc 2=veg_406 3=veg_408 4=veg_410 255=nodata)",
            band_2="support (1=evaluable 0=nodata)",
            method="supervised_e",
            n_features=str(N_FEATURES_E_TOTAL),
        )

    tmp.replace(out_path)
    log.info("Raster prédiction sauvegardé : %s  (%dx%d px)", out_path.name, h, w)
    return out_path


# ── Vectorisation ─────────────────────────────────────────────────────────────

def _iter_valid_polygons(geom, min_area_m2: float) -> Iterator[Polygon]:
    """Itère sur les Polygons valides (> min_area_m2) depuis une géométrie quelconque."""
    if isinstance(geom, Polygon):
        if not geom.is_empty and geom.is_valid and geom.area > min_area_m2:
            yield geom
    elif isinstance(geom, MultiPolygon):
        for p in geom.geoms:
            if isinstance(p, Polygon) and not p.is_empty and p.is_valid and p.area > min_area_m2:
                yield p


def vectorize_prediction(
    pred: np.ndarray,
    support: np.ndarray,
    transform,
    export_mode: str = EXPORT_MODE_FAITHFUL,
) -> dict[int, list[Polygon]]:
    """Vectorise le raster de prédiction en polygones par classe.

    Mode faithful     : min_area=0.0 — aucun filtrage, roundtrip pixel-perfect.
    Mode generalized  : min_area=16 m² — supprime composantes < 1 pixel (2×2 m).

    Classe 1 (blanc) = fond implicite — aucun polygone créé.
    Pixels support=0 exclus de tous les polygones.

    Retourne dict {class_id: [Polygon, ...]} pour class_id in {0, 2, 3, 4}.
    """
    min_area = 0.0 if export_mode == EXPORT_MODE_FAITHFUL else _GENERALIZED_MIN_AREA_M2
    polys_by_class: dict[int, list[Polygon]] = {}

    for class_id in _CLASS_TO_ISOM:
        mask = ((pred == class_id) & support).astype("uint8")
        if mask.sum() == 0:
            polys_by_class[class_id] = []
            continue
        polys: list[Polygon] = []
        for geom_dict, val in shapes(mask, mask=mask, transform=transform):
            if val != 1:
                continue
            geom = make_valid(shape(geom_dict))
            polys.extend(_iter_valid_polygons(geom, min_area))
        polys_by_class[class_id] = polys

    return polys_by_class


def save_vegetation_gpkg(
    polys_by_class: dict[int, list[Polygon]],
    crs: str,
    out_path: pathlib.Path,
    export_mode: str = EXPORT_MODE_FAITHFUL,
) -> pathlib.Path:
    """Exporte les polygones de végétation dans un GeoPackage.

    Couches : veg_401, veg_406, veg_408, veg_410.
    Compatible avec step_assemble (mode supervised_e).

    Écriture atomique : fichier temporaire renommé en fin de succès.
    Un sidecar JSON (même base, extension .json) stocke le mode durablement.
    """
    import geopandas as gpd
    import json as _json

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.gpkg")
    if tmp.exists():
        tmp.unlink()

    first = True
    n_by_layer: dict[str, int] = {}
    for class_id, isom_code in _CLASS_TO_ISOM.items():
        polys = polys_by_class.get(class_id, [])
        layer_name = f"veg_{isom_code}"
        gdf = gpd.GeoDataFrame(geometry=polys, crs=crs)
        gdf.to_file(str(tmp), layer=layer_name, driver="GPKG", mode="w" if first else "a")
        first = False
        n_by_layer[layer_name] = len(polys)
        log.info("  %s : %d polygones", layer_name, len(polys))

    tmp.rename(out_path)

    # Métadonnées durables : sidecar JSON (nom fichier encode déjà le mode)
    meta = {
        "export_mode": export_mode,
        "crs": crs,
        "n_polygons": n_by_layer,
        "source": "supervised_e",
    }
    out_path.with_suffix(".json").write_text(
        _json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info(
        "%s  mode=%s  (%d couches)",
        out_path.name, export_mode, len(_CLASS_TO_ISOM),
    )
    return out_path


def save_coverage_raster(
    support: np.ndarray,
    bbox: list[float],
    crs: str,
    out_path: pathlib.Path,
) -> pathlib.Path:
    """Exporte le masque de couverture LiDAR (uint8, 1=couvert, 0=inconnu).

    Les pixels inconnus (support=0) ne sont ni prédits ni courables.
    Ils apparaissent comme fond blanc dans le .omap mais n'ont pas de classe.
    """
    h, w = support.shape
    xmin, ymin, xmax, ymax = bbox
    transform = from_bounds(xmin, ymin, xmax, ymax, w, h)

    tmp = out_path.with_suffix(".tmp.tif")
    if tmp.exists():
        tmp.unlink()

    with rasterio.open(
        str(tmp), "w",
        driver="GTiff", height=h, width=w,
        count=1, dtype="uint8",
        crs=CRS.from_string(crs), transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(support.astype("uint8"), 1)
        dst.update_tags(
            description="Masque couverture LiDAR supervised_e",
            value_1="pixel evalue (couvert)",
            value_0="pixel hors couverture — ni predit ni courable",
        )

    tmp.replace(out_path)
    n_unknown = int((~support).sum())
    log.info(
        "Coverage mask : %s  (%d inconnus = %.2f%%)",
        out_path.name, n_unknown, 100.0 * n_unknown / support.size,
    )
    return out_path


# ── Point d'entrée principal ──────────────────────────────────────────────────

def run_supervised_e(
    laz_files: list[pathlib.Path],
    bbox: list[float],
    output_dir: pathlib.Path,
    cache_dir: pathlib.Path | None = None,
    model_path: pathlib.Path | None = None,
    crs: str = CRS_DEFAULT,
    force: bool = False,
    export_mode: str = EXPORT_MODE_FAITHFUL,
) -> dict[str, pathlib.Path]:
    """Pipeline complet supervised_e sur un terrain.

    Paramètres :
      laz_files   : liste des fichiers LAZ/COPC du terrain
      bbox        : [xmin, ymin, xmax, ymax] en coordonnées crs
      output_dir  : dossier de sortie
      cache_dir   : dossier cache strates ext (None = output_dir)
      model_path  : PKL modèle final (None = DEFAULT_MODEL_PATH)
      crs         : EPSG string
      force       : recalculer même si cache valide
      export_mode : EXPORT_MODE_FAITHFUL (défaut) ou EXPORT_MODE_GENERALIZED

    Contrat fidèle (export_mode="faithful") :
      Aucun filtrage de composante, aucune simplification. Roundtrip
      raster → vecteur → raster identique sur tous les pixels support.

    Retourne un dict :
      "prediction_tif"  : raster de prédiction (uint8, 2 bandes)
      "vegetation_gpkg" : GeoPackage veg_401/406/408/410
      "coverage_tif"    : masque de couverture LiDAR (1=couvert, 0=inconnu)
    """
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = pathlib.Path(cache_dir or output_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    xmin, ymin, xmax, ymax = bbox
    w = int(round((xmax - xmin) / RES_M))
    h = int(round((ymax - ymin) / RES_M))
    log.info(
        "supervised_e : bbox=[%.0f,%.0f,%.0f,%.0f]  grille=%dx%d px  mode=%s",
        xmin, ymin, xmax, ymax, h, w, export_mode,
    )

    pred_path = output_dir / "supervised_e_prediction.tif"
    veg_gpkg  = output_dir / f"vegetation_supervised_e_{export_mode}.gpkg"
    cov_tif   = output_dir / "supervised_e_coverage.tif"

    if pred_path.exists() and not force:
        log.info("Raster prédiction déjà présent — rechargement pour vectorisation.")
        with rasterio.open(str(pred_path)) as ds:
            pred      = ds.read(1)
            support   = ds.read(2).astype(bool)
            transform = ds.transform
    else:
        # 1. Strates étendues depuis LAZ (ou cache)
        cache_npz = cache_dir / "supervised_e_strates_ext.npz"
        strates_data = compute_ext_strates(laz_files, bbox, h, w, cache_npz, force)

        # 2. Descripteurs 63 features
        log.info("Construction descripteurs T+E (63 features)...")
        X_grid, support = build_features(strates_data)
        del strates_data

        # 3. Chargement modèle (avec vérification empreinte)
        log.info("Chargement modèle...")
        payload = load_model(model_path)
        clf     = payload["clf"]
        imputer = payload["imputer"]

        # 4. Inférence
        log.info("Inférence sur %d px (%d évaluables)...", h * w, int(support.sum()))
        pred = run_inference(X_grid, support, clf, imputer)
        del X_grid

        # 5. Export raster géoréférencé
        transform = from_bounds(xmin, ymin, xmax, ymax, w, h)
        save_prediction_raster(pred, support, bbox, crs, pred_path)

    # 6. Masque de couverture (toujours recalculé pour cohérence)
    save_coverage_raster(support, bbox, crs, cov_tif)

    # 7. Vectorisation + GPKG végétation
    log.info("Vectorisation (mode=%s)...", export_mode)
    polys_by_class = vectorize_prediction(pred, support, transform, export_mode)
    save_vegetation_gpkg(polys_by_class, crs, veg_gpkg, export_mode)

    return {
        "prediction_tif": pred_path,
        "vegetation_gpkg": veg_gpkg,
        "coverage_tif": cov_tif,
    }
