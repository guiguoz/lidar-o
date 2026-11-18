"""Reproduction fidèle de la méthode Trier 2015 — référence expérimentale V0.

Référence : Trier, Ø.D. (2015). Automatic mapping of forest density from
airborne lidar data. Geodesy and Cartography, 41(2): 49-65.
DOI: 10.3846/20296991.2015.1051342

Paramètres figés d'après le papier :
  résolution NDVD     : 0.5 m/px (§2 "0.5 m pixel size")
  résolution finale   : 1.0 m/px (§2.2 "Aggregate... to 1.0 m")
  V                   : retours non-ground HAG in [0.2, 2.0) m (§2 + §2 artefact)
  G                   : retours ground (class 2), tous ReturnNumber (§2)
  ReturnNumber        : non filtré — tous les retours comptés (§1.1 §2)
  DTM                 : class 2 uniquement (§1.3 "ground points")
  noyau               : circulaire r=2 m, poids=1 pour d<=1 m, linéaire->0
                        pour d in (1, 2] m (§2 Fig.3)
  NDVD                : (V-G)/(V+G) -> [-1, 1] (Eq. 1)
  seuils 10/m2        : slow=0.00, walk=0.35, fight=0.70 (Table 5)
  seuils 2/m2         : slow=-0.20, walk=0.20, fight=0.60 (Table 5)
  morphologie         : séquence close/open kernels croissants (§2.2)
  aire minimale       : 225 m2 slow/walk, 112.5 m2 fight (§2.2)
  seuil ouverture     : nDSM < 0.75 m -> zone ouverte (§2.1)

STATUT DES PARAMÈTRES (SOURCE / IMPLÉMENTATION / ÉCART) :

  Construction terrain :
    SOURCE : "TRIGRID was used to produce a DTM of the 'ground' points" (§1.3)
    IMPL   : min par cellule + NN hole-fill
    ÉCART  : [TRIER-DEV-DTM] approximation, négligeable à ~10-15 impl/m²

  Définition de V :
    SOURCE : "number of vegetation and ground hits" (§2). Données Trier = 2 classes
             uniquement : 'ground' (class 2) et 'other' (class != 2).
             "returns from 0.2-2.0 m above ground" (§2, artefact stripes -> 0.2m)
    IMPL   : V = tous retours non-class2, HAG in [0.2, 2.0) m
    ÉCART  : [TRIER-DEV-V-UNRESOLVED]
             Grimbosq contient des classes supplémentaires (6=bâtiment, 9=eau,
             7=bruit bas) non présentes dans les données Trier (2 classes seulement).
             Hypothèse : ces classes sont traitées comme 'other' (incluses dans V
             si HAG convient). L'article ne permet pas de trancher.
             Ambiguïté non résolue — hypothèse conservée.

  Politique des retours :
    SOURCE : ReturnNumber présent dans les données (§1.1 "return number 1,2,3 or 4")
             mais aucun filtrage par ReturnNumber mentionné pour NDVD.
    IMPL   : tous les retours comptés (ReturnNumber non filtré)
    STATUT : FIDÈLE

  Noyau :
    SOURCE : "circular neighbourhood with radius = 2.0 m, giving equal weight to
             all hits within a 1.0 m radius from the centre, and linearly decreasing
             weight from 1.0 m to 2.0 m from the centre" (§2, Fig.3)
    IMPL   : noyau 9x9, poids=1 pour d<=2px=1m, linéaire->0 pour d in (2,4] px
    STATUT : FIDÈLE

  Densité :
    SOURCE : 2 impl/m² et 10 impl/m² (Table 1, Table 5)
    GRIMBOSQ : ~15 impl/m²
    IMPL run principal : sous-échantillonnage par impulsion (GpsTime) -> ~10 impl/m²
             seuils 10/m² utilisés
    STATUT run principal : ADAPTATION DOCUMENTÉE (hors domaine publié)

  Masque zones ouvertes :
    SOURCE : séquence morphologique complète §2.1
    IMPL   : [TRIER-DEV-OPENMAP] simplifié: seuil nDSM + filtre aire uniquement
    STATUT : DÉVIATION TECHNIQUE

  Généralisation §2.2 :
    SOURCE : "closing 7x7, opening 3x3, closing 9x9, opening 5x5, closing 11x11,
             opening 7x7, remove open areas mask, opening square 3x3,
             remove objects < min_area" (§2.2)
    IMPL   : séquence identique
    STATUT : FIDÈLE
"""
from __future__ import annotations

import json
import logging
import math
import pathlib
from typing import Any

import numpy as np
import pdal
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine, from_bounds, rowcol
from scipy.ndimage import (
    binary_closing,
    binary_opening,
    convolve,
    distance_transform_edt,
    label as ndlabel,
)

log = logging.getLogger(__name__)

# ── Paramètres figés (Trier 2015) ────────────────────────────────────────────
_RES_M: float = 0.5
_AGGR_M: float = 1.0
_AGGR: int = int(_AGGR_M / _RES_M)   # 2
_H_VEG_MIN: float = 0.2              # borne inférieure V (inclusive)
_H_VEG_MAX: float = 2.0              # borne supérieure V (exclusive)
_H_OPEN: float = 0.75                # seuil nDSM zones ouvertes (§2.1)
_INNER_R_M: float = 1.0
_OUTER_R_M: float = 2.0
_GROUND_CLASS: int = 2

# [TRIER-DEV-V-UNRESOLVED] : voir docstring module
# Trier data = 2 classes (ground/other). Grimbosq a des classes supplémentaires.
# Hypothèse : V = tous non-class2 dans HAG [0.2, 2.0).
_V_DEFINITION = "non-class2 HAG[0.2,2.0)  [TRIER-DEV-V-UNRESOLVED]"

# (slow_run, walk, fight) pour chaque densité documentée (Table 5)
_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "2":  (-0.20, 0.20, 0.60),
    "10": ( 0.00, 0.35, 0.70),
}
_DEFAULT_DENSITY_KEY: str = "10"

_MIN_AREA_SLOW_WALK_PX: int = 225   # 225 m2 à 1 m/px
_MIN_AREA_FIGHT_PX: int = 112        # 112.5 m2 arrondi
_MIN_OPEN_AREA_PX: int = 22          # 22.5 m2 arrondi


# ── Noyau Trier (plat-conique, Fig.3) ────────────────────────────────────────

def _trier_kernel() -> np.ndarray:
    r_i = _INNER_R_M / _RES_M   # 2.0 px
    r_o = _OUTER_R_M / _RES_M   # 4.0 px
    size = int(r_o) * 2 + 1     # 9
    half = size // 2
    k = np.zeros((size, size), dtype=np.float32)
    for i in range(size):
        for j in range(size):
            d = math.sqrt((i - half) ** 2 + (j - half) ** 2)
            if d <= r_i:
                k[i, j] = 1.0
            elif d <= r_o:
                k[i, j] = (r_o - d) / (r_o - r_i)
    return k


def _disk_struct(diameter: int) -> np.ndarray:
    radius = diameter // 2
    center = radius
    s = np.zeros((diameter, diameter), dtype=bool)
    for i in range(diameter):
        for j in range(diameter):
            if (i - center) ** 2 + (j - center) ** 2 <= radius ** 2:
                s[i, j] = True
    return s


# ── Sous-échantillonnage par impulsion ────────────────────────────────────────

def subsample_impulses(
    pts: np.ndarray,
    fraction: float,
    seed: int = 42,
) -> np.ndarray:
    """Sous-échantillonne les points par impulsion (GpsTime unique).

    Conserve TOUS les retours d'une impulsion retenue.
    Ne modifie pas la proportion retours multiples/simples (rapport V/G préservé).
    fraction = target_density / actual_density (ex. 10/15 pour Grimbosq).
    """
    if "GpsTime" not in pts.dtype.names or len(pts) == 0:
        log.warning("GpsTime absent — sous-échantillonnage impossible, pts inchangés")
        return pts
    gps_times = pts["GpsTime"]
    unique_times, inverse = np.unique(gps_times, return_inverse=True)
    n_keep = max(1, int(round(len(unique_times) * fraction)))
    rng = np.random.default_rng(seed)
    kept_idx = rng.choice(len(unique_times), size=n_keep, replace=False)
    kept_mask = np.zeros(len(unique_times), dtype=bool)
    kept_mask[kept_idx] = True
    result = pts[kept_mask[inverse]]
    log.debug(
        "Subsample: %d impulsions -> %d gardées (%.1f %%), %d pts -> %d pts",
        len(unique_times), n_keep, 100 * n_keep / len(unique_times),
        len(pts), len(result),
    )
    return result


def check_gpstime(
    copc_paths: list[str | pathlib.Path],
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """Vérifie disponibilité et cohérence de GpsTime pour le sous-échantillonnage."""
    pts = _read_points(list(copc_paths[:1]), bbox)
    if len(pts) == 0:
        return {"available": False, "reason": "aucun point lu"}
    if "GpsTime" not in pts.dtype.names:
        return {"available": False, "reason": "GpsTime absent des champs PDAL"}

    gps_times = pts["GpsTime"]
    unique_times, inverse = np.unique(gps_times, return_inverse=True)
    n_pts = len(pts)
    n_unique = len(unique_times)
    ratio = n_pts / max(1, n_unique)

    has_return_fields = (
        "ReturnNumber" in pts.dtype.names
        and "NumberOfReturns" in pts.dtype.names
    )
    multi_ratio = 0.0
    if has_return_fields:
        multi_mask = pts["NumberOfReturns"] > 1
        multi_ratio = float(multi_mask.mean())

    # Vérifier que les points d'une même impulsion partagent le même GpsTime
    gpstime_range = float(gps_times.max() - gps_times.min())
    gpstime_precision = float(np.diff(np.sort(unique_times[:1000])).min()) if n_unique > 1 else 0.0

    del pts
    return {
        "available": True,
        "n_pts_first_tile": n_pts,
        "n_unique_gpstime": n_unique,
        "ratio_pts_per_impulse": ratio,
        "fraction_multi_return": multi_ratio,
        "has_return_fields": has_return_fields,
        "gpstime_range_s": gpstime_range,
        "gpstime_min_interval_s": gpstime_precision,
        "ok": ratio > 1.0 and ratio < 10.0,
        "comment": (
            f"ratio={ratio:.2f} pts/impulsion "
            f"(attendu ~1.5-3 pour 10-15 impl/m², retours multiples inclus)"
        ),
    }


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _read_points(
    copc_paths: list[str | pathlib.Path],
    bbox: tuple[float, float, float, float],
    expression: str | None = None,
) -> np.ndarray:
    xmin, ymin, xmax, ymax = bbox
    stages: list[dict] = []
    for p in copc_paths:
        stages.append({"type": "readers.copc", "filename": str(p)})
    if len(copc_paths) > 1:
        stages.append({"type": "filters.merge"})
    if expression:
        stages.append({"type": "filters.expression", "expression": expression})
    stages.append({
        "type": "filters.crop",
        "bounds": f"([{xmin},{xmax}],[{ymin},{ymax}])",
    })
    pipe = pdal.Pipeline(json.dumps({"pipeline": stages}))
    n_pts = pipe.execute()
    log.debug("PDAL : %d points (expr=%s)", n_pts, expression or "none")
    arrays = pipe.arrays
    if not arrays:
        return np.empty(0, dtype=[("X", "f8"), ("Y", "f8"), ("Z", "f8")])
    pts = np.concatenate(arrays) if len(arrays) > 1 else arrays[0]
    if "Withheld" in pts.dtype.names:
        pts = pts[~pts["Withheld"].astype(bool)]
    return pts


def _write_tif(
    arr: np.ndarray,
    path: pathlib.Path,
    transform: Any,
    crs: str,
    nodata: float | None = None,
    descriptions: list[str] | None = None,
) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if arr.ndim == 2:
        arr = arr[np.newaxis, :]
    count, height, width = arr.shape
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "dtype": arr.dtype,
        "width": width,
        "height": height,
        "count": count,
        "crs": CRS.from_string(crs),
        "transform": transform,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        for i in range(count):
            dst.write(arr[i], i + 1)
        if descriptions:
            for i, desc in enumerate(descriptions, 1):
                dst.update_tags(i, DESCRIPTION=desc)
    log.info("Ecrit : %s (%s, %d bande(s))", path.name, arr.dtype, count)


# ── DTM ───────────────────────────────────────────────────────────────────────

def _update_dtm(
    dtm: np.ndarray,
    gx: np.ndarray,
    gy: np.ndarray,
    gz: np.ndarray,
    rows: int,
    cols: int,
    transform: Any,
) -> None:
    ri, ci = rowcol(transform, gx, gy)
    ri = np.asarray(ri, dtype=np.intp)
    ci = np.asarray(ci, dtype=np.intp)
    valid = (ri >= 0) & (ri < rows) & (ci >= 0) & (ci < cols)
    np.minimum.at(dtm, (ri[valid], ci[valid]), gz[valid].astype(np.float32))


def _finalize_dtm(dtm: np.ndarray) -> None:
    """[TRIER-DEV-DTM] NN hole-fill à la place du TIN TRIGRID (ENVI)."""
    holes = dtm == np.inf
    n = int(holes.sum())
    if n:
        _, idx = distance_transform_edt(holes, return_indices=True)
        dtm[holes] = dtm[idx[0][holes], idx[1][holes]]
        log.info("DTM : %d cellules vides comblées (NN)", n)
    log.info("DTM : min=%.1f m, max=%.1f m", float(dtm.min()), float(dtm.max()))


def _compute_hag(
    pts_x: np.ndarray,
    pts_y: np.ndarray,
    pts_z: np.ndarray,
    dtm: np.ndarray,
    transform: Any,
) -> np.ndarray:
    rows, cols = dtm.shape
    ri, ci = rowcol(transform, pts_x, pts_y)
    ri = np.asarray(ri, dtype=np.intp)
    ci = np.asarray(ci, dtype=np.intp)
    hag = np.full(len(pts_z), np.nan, dtype=np.float32)
    valid = (ri >= 0) & (ri < rows) & (ci >= 0) & (ci < cols)
    hag[valid] = pts_z[valid].astype(np.float32) - dtm[ri[valid], ci[valid]]
    return hag


# ── Accumulation V, G, nDSM ───────────────────────────────────────────────────

def _accumulate_vg(
    V_raw: np.ndarray,
    G_raw: np.ndarray,
    dsm_max: np.ndarray,
    pts_cls: np.ndarray,
    pts_x: np.ndarray,
    pts_y: np.ndarray,
    hag: np.ndarray,
    rows: int,
    cols: int,
    transform: Any,
) -> None:
    """Accumule V (non-ground HAG [0.2,2.0)), G (ground class 2), nDSM (max HAG).

    [TRIER-DEV-V-UNRESOLVED] : classes != 2 traitées comme 'other' (V).
    """
    ri, ci = rowcol(transform, pts_x, pts_y)
    ri = np.asarray(ri, dtype=np.intp)
    ci = np.asarray(ci, dtype=np.intp)
    in_grid = (ri >= 0) & (ri < rows) & (ci >= 0) & (ci < cols)
    valid = in_grid & ~np.isnan(hag)
    ri_v, ci_v = ri[valid], ci[valid]
    h_v = hag[valid]
    cls_v = pts_cls[valid]

    # G : class 2, tous ReturnNumber (§2 "ground hits")
    g_mask = cls_v == _GROUND_CLASS
    np.add.at(G_raw, (ri_v[g_mask], ci_v[g_mask]), 1)

    # V : non-class2, HAG in [0.2, 2.0) (§2 bornes, 0.2m pour supprimer artefacts)
    v_mask = (cls_v != _GROUND_CLASS) & (h_v >= _H_VEG_MIN) & (h_v < _H_VEG_MAX)
    np.add.at(V_raw, (ri_v[v_mask], ci_v[v_mask]), 1)

    # nDSM : max HAG tous retours (pour masque zones ouvertes)
    np.maximum.at(dsm_max, (ri_v, ci_v), h_v)


# ── Noyau + NDVD ─────────────────────────────────────────────────────────────

def _apply_kernel(
    V_raw: np.ndarray,
    G_raw: np.ndarray,
    kernel: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    V_k = convolve(V_raw.astype(np.float32), kernel, mode="reflect")
    G_k = convolve(G_raw.astype(np.float32), kernel, mode="reflect")
    return V_k, G_k


def _ndvd_from_vg(V: np.ndarray, G: np.ndarray) -> np.ndarray:
    denom = V + G
    out = np.full_like(denom, np.nan, dtype=np.float32)
    valid = denom > 0.0
    out[valid] = (V[valid] - G[valid]) / denom[valid]
    return out


def _aggregate_to_1m(arr_05: np.ndarray) -> np.ndarray:
    rows, cols = arr_05.shape
    nr = rows // _AGGR
    nc = cols // _AGGR
    sub = arr_05[:nr * _AGGR, :nc * _AGGR]
    with np.errstate(all="ignore"):
        return np.nanmean(
            sub.reshape(nr, _AGGR, nc, _AGGR), axis=(1, 3)
        ).astype(np.float32)


def _transform_1m(t05: Any) -> Affine:
    return Affine(t05.a * _AGGR, t05.b, t05.c, t05.d, t05.e * _AGGR, t05.f)


# ── Masque zones ouvertes (simplifié §2.1) ────────────────────────────────────

def _open_areas_mask(dsm_max_05: np.ndarray) -> np.ndarray:
    """Masque 1 m des zones sans végétation arborée. [TRIER-DEV-OPENMAP]"""
    rows, cols = dsm_max_05.shape
    nr, nc = rows // _AGGR, cols // _AGGR
    dsm_1m = dsm_max_05[:nr * _AGGR, :nc * _AGGR].reshape(
        nr, _AGGR, nc, _AGGR
    ).max(axis=(1, 3))
    open_land = dsm_1m < _H_OPEN
    open_land = binary_opening(open_land, structure=_disk_struct(3))
    labeled, _ = ndlabel(open_land)
    sizes = np.bincount(labeled.ravel())
    too_small = sizes < _MIN_OPEN_AREA_PX
    too_small[0] = False
    open_land[too_small[labeled]] = False
    return open_land.astype(bool)


# ── Classification + morphologie ─────────────────────────────────────────────

def _classify_threshold(
    ndvd_1m: np.ndarray,
    t_slow: float,
    t_walk: float,
    t_fight: float,
) -> np.ndarray:
    cls = np.zeros(ndvd_1m.shape, dtype=np.uint16)
    valid = np.isfinite(ndvd_1m)
    cls[valid & (ndvd_1m >= t_slow)] = 406
    cls[valid & (ndvd_1m >= t_walk)] = 408
    cls[valid & (ndvd_1m >= t_fight)] = 410
    return cls


def _morpho_gen_binary(
    binary: np.ndarray,
    open_mask: np.ndarray,
    min_area_px: int,
) -> np.ndarray:
    """Séquence morphologique §2.2 exacte : close/open croissants + masque + aire."""
    b = binary.copy()
    b = binary_closing(b,  structure=_disk_struct(7))
    b = binary_opening(b,  structure=_disk_struct(3))
    b = binary_closing(b,  structure=_disk_struct(9))
    b = binary_opening(b,  structure=_disk_struct(5))
    b = binary_closing(b,  structure=_disk_struct(11))
    b = binary_opening(b,  structure=_disk_struct(7))
    b = b & ~open_mask
    b = binary_opening(b,  structure=np.ones((3, 3), dtype=bool))
    labeled, _ = ndlabel(b)
    sizes = np.bincount(labeled.ravel())
    too_small = sizes < min_area_px
    too_small[0] = False
    b[too_small[labeled]] = False
    return b


def _morpho_gen_full(
    ndvd_1m: np.ndarray,
    open_mask: np.ndarray,
    t_slow: float,
    t_walk: float,
    t_fight: float,
) -> np.ndarray:
    log.info("  morpho slow run (406)...")
    slow_bin = _morpho_gen_binary(
        np.isfinite(ndvd_1m) & (ndvd_1m >= t_slow), open_mask, _MIN_AREA_SLOW_WALK_PX
    )
    log.info("  morpho walk (408)...")
    walk_bin = _morpho_gen_binary(
        np.isfinite(ndvd_1m) & (ndvd_1m >= t_walk), open_mask, _MIN_AREA_SLOW_WALK_PX
    )
    log.info("  morpho fight (410)...")
    fight_bin = _morpho_gen_binary(
        np.isfinite(ndvd_1m) & (ndvd_1m >= t_fight), open_mask, _MIN_AREA_FIGHT_PX
    )
    cls = np.zeros(ndvd_1m.shape, dtype=np.uint16)
    cls[slow_bin] = 406
    cls[walk_bin] = 408
    cls[fight_bin] = 410
    return cls


# ── Pipeline principal ────────────────────────────────────────────────────────

def run(
    copc_paths: list[str | pathlib.Path],
    bbox: tuple[float, float, float, float],
    output_dir: str | pathlib.Path,
    crs: str = "EPSG:2154",
    density_key: str = _DEFAULT_DENSITY_KEY,
    subsample_fraction: float | None = None,
) -> dict[str, pathlib.Path]:
    """Pipeline complet Trier 2015.

    subsample_fraction : fraction des impulsions à conserver (None = pas de sous-échantillonnage).
        Pour run principal Grimbosq : 10/15 = 0.6667.
        None -> [TRIER-ADAPTATION] run hors domaine à ~15 impl/m².

    Sorties :
      trier_dtm.tif                        DTM à 0.5 m (class 2 only)
      trier_strates.tif                    V_raw (b1) + G_raw (b2) à 0.5 m
      trier_signal_brut.tif                NDVD brut (V-G)/(V+G) à 0.5 m (avant noyau)
      trier_signal_apres_voisinage.tif     NDVD après noyau conique à 0.5 m
      trier_classes.tif                    0/406/408/410 à 1.0 m (avant morpho)
      trier_classes_gen.tif                idem après séquence morphologique §2.2
    """
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copc_paths = [pathlib.Path(p) for p in copc_paths]

    t_slow, t_walk, t_fight = _THRESHOLDS[density_key]
    xmin, ymin, xmax, ymax = bbox
    cols = int(np.ceil((xmax - xmin) / _RES_M))
    rows = int(np.ceil((ymax - ymin) / _RES_M))
    transform_05 = from_bounds(xmin, ymin, xmax, ymax, cols, rows)
    log.info(
        "Grille 0.5 m : %d x %d px | density_key=%s | subsample=%.3f",
        cols, rows, density_key,
        subsample_fraction if subsample_fraction is not None else 1.0,
    )

    # ── Passe 1 : DTM (class 2, avec sous-échantillonnage cohérent) ──────────
    log.info("Passe 1 : DTM (class 2)...")
    dtm = np.full((rows, cols), np.inf, dtype=np.float32)
    total_ground = 0
    for i, path in enumerate(copc_paths, 1):
        if subsample_fraction is not None:
            # Lire tous les points pour sous-échantillonner par impulsion
            pts = _read_points([path], bbox)
            if len(pts) == 0:
                continue
            pts = subsample_impulses(pts, subsample_fraction, seed=42 + i)
            g_mask = pts["Classification"].astype(np.int32) == _GROUND_CLASS
            if not g_mask.any():
                continue
            gx = pts["X"][g_mask].astype(np.float32)
            gy = pts["Y"][g_mask].astype(np.float32)
            gz = pts["Z"][g_mask].astype(np.float32)
            del pts
        else:
            # Efficacité : lire uniquement class 2 si pas de sous-échantillonnage
            pts = _read_points([path], bbox, expression="Classification == 2")
            if len(pts) == 0:
                continue
            gx = pts["X"].astype(np.float32)
            gy = pts["Y"].astype(np.float32)
            gz = pts["Z"].astype(np.float32)
            del pts
        _update_dtm(dtm, gx, gy, gz, rows, cols, transform_05)
        total_ground += len(gx)
        log.info("  tuile %d/%d : %d pts sol (cumul=%d)", i, len(copc_paths), len(gx), total_ground)
        del gx, gy, gz

    _finalize_dtm(dtm)
    _write_tif(dtm, output_dir / "trier_dtm.tif", transform_05, crs, nodata=-9999.0)

    # ── Passe 2 : V, G, nDSM ─────────────────────────────────────────────────
    log.info("Passe 2 : V/G/nDSM...")
    V_raw = np.zeros((rows, cols), dtype=np.float32)
    G_raw = np.zeros((rows, cols), dtype=np.float32)
    dsm_max = np.zeros((rows, cols), dtype=np.float32)
    total_pts = 0
    for i, path in enumerate(copc_paths, 1):
        pts = _read_points([path], bbox)
        if len(pts) == 0:
            continue
        if subsample_fraction is not None:
            pts = subsample_impulses(pts, subsample_fraction, seed=42 + i)
        pts_x = pts["X"].astype(np.float32)
        pts_y = pts["Y"].astype(np.float32)
        pts_z = pts["Z"].astype(np.float32)
        pts_cls = pts["Classification"].astype(np.int32)
        del pts
        hag = _compute_hag(pts_x, pts_y, pts_z, dtm, transform_05)
        _accumulate_vg(
            V_raw, G_raw, dsm_max, pts_cls,
            pts_x, pts_y, hag, rows, cols, transform_05,
        )
        total_pts += len(pts_x)
        log.info("  tuile %d/%d : %d pts (cumul=%d)", i, len(copc_paths), len(pts_x), total_pts)
        del pts_x, pts_y, pts_z, pts_cls, hag

    log.info("V total=%.0f  G total=%.0f", float(V_raw.sum()), float(G_raw.sum()))
    _write_tif(
        np.stack([V_raw, G_raw]),
        output_dir / "trier_strates.tif",
        transform_05, crs, nodata=-1.0,
        descriptions=["V_raw_0.2-2.0m", "G_raw_class2"],
    )

    # ── Signal brut (avant noyau) ─────────────────────────────────────────────
    ndvd_brut = _ndvd_from_vg(V_raw, G_raw)
    _write_tif(ndvd_brut, output_dir / "trier_signal_brut.tif", transform_05, crs, nodata=np.nan)
    del ndvd_brut

    # ── Noyau + NDVD à 0.5 m ─────────────────────────────────────────────────
    log.info("Application noyau conique Trier (9x9)...")
    kernel = _trier_kernel()
    V_k, G_k = _apply_kernel(V_raw, G_raw, kernel)
    del V_raw, G_raw
    ndvd_05 = _ndvd_from_vg(V_k, G_k)
    del V_k, G_k
    _write_tif(
        ndvd_05,
        output_dir / "trier_signal_apres_voisinage.tif",
        transform_05, crs, nodata=np.nan,
    )

    # ── Agrégation 1 m + classification sans morpho ───────────────────────────
    log.info("Agrégation 0.5 m -> 1.0 m + classification...")
    ndvd_1m = _aggregate_to_1m(ndvd_05)
    del ndvd_05
    transform_1m = _transform_1m(transform_05)

    cls_raw = _classify_threshold(ndvd_1m, t_slow, t_walk, t_fight)
    _write_tif(
        cls_raw.astype(np.uint16),
        output_dir / "trier_classes.tif",
        transform_1m, crs, nodata=65535,
    )
    del cls_raw

    # ── Masque open land ──────────────────────────────────────────────────────
    open_mask = _open_areas_mask(dsm_max)
    del dsm_max

    # ── Généralisation morphologique ──────────────────────────────────────────
    log.info("Généralisation morphologique §2.2...")
    cls_gen = _morpho_gen_full(ndvd_1m, open_mask, t_slow, t_walk, t_fight)
    del ndvd_1m, open_mask
    _write_tif(
        cls_gen.astype(np.uint16),
        output_dir / "trier_classes_gen.tif",
        transform_1m, crs, nodata=65535,
    )

    paths = {
        "dtm": output_dir / "trier_dtm.tif",
        "strates": output_dir / "trier_strates.tif",
        "signal_brut": output_dir / "trier_signal_brut.tif",
        "signal_apres_voisinage": output_dir / "trier_signal_apres_voisinage.tif",
        "classes": output_dir / "trier_classes.tif",
        "classes_gen": output_dir / "trier_classes_gen.tif",
    }
    log.info("Pipeline Trier terminé. Sorties dans %s", output_dir)
    return paths


# ── Mesure d'empreinte ────────────────────────────────────────────────────────

def measure_empreinte(
    output_dir: str | pathlib.Path,
    perturb_x: float,
    perturb_y: float,
    crs: str = "EPSG:2154",
) -> dict[str, Any]:
    """Rayon d'influence du noyau Trier par perturbation de +1000 sur V_raw.

    Produit trier_empreinte_diff.tif (différence NDVD avant/après perturbation).
    Retourne max_dist_m, theoretical_max_m, changed_cells.
    """
    output_dir = pathlib.Path(output_dir)
    strates_path = output_dir / "trier_strates.tif"

    with rasterio.open(strates_path) as src:
        V_raw = src.read(1).astype(np.float32)
        G_raw = src.read(2).astype(np.float32)
        transform = src.transform
        rows, cols = src.height, src.width

    pr, pc = rowcol(transform, perturb_x, perturb_y)
    pr, pc = int(pr), int(pc)
    if not (0 <= pr < rows and 0 <= pc < cols):
        log.warning("Point de perturbation hors grille")
        return {
            "max_dist_m": 0.0,
            "theoretical_max_m": _OUTER_R_M * math.sqrt(2),
            "changed_cells": 0,
        }

    V_pert = V_raw.copy()
    V_pert[pr, pc] += 1000.0

    kernel = _trier_kernel()
    V_k_orig, G_k = _apply_kernel(V_raw, G_raw, kernel)
    V_k_pert, _ = _apply_kernel(V_pert, G_raw, kernel)

    ndvd_orig = _ndvd_from_vg(V_k_orig, G_k)
    ndvd_pert = _ndvd_from_vg(V_k_pert, G_k)
    diff = ndvd_pert - ndvd_orig
    changed = np.isfinite(diff) & (np.abs(diff) > 1e-6)

    # Sauvegarder le raster de différence
    _write_tif(
        diff.astype(np.float32),
        output_dir / "trier_empreinte_diff.tif",
        transform, crs, nodata=np.nan,
    )

    changed_cells = int(changed.sum())
    if changed_cells == 0:
        log.warning("Aucune cellule changée — perturbation insuffisante")
        return {
            "max_dist_m": 0.0,
            "theoretical_max_m": _OUTER_R_M * math.sqrt(2),
            "theoretical_radius_m": _OUTER_R_M,
            "changed_cells": 0,
        }

    ri_chg, ci_chg = np.where(changed)
    dy = (ri_chg - pr) * _RES_M
    dx = (ci_chg - pc) * _RES_M
    max_dist = float(np.sqrt(dx**2 + dy**2).max())

    return {
        "max_dist_m": max_dist,
        "theoretical_max_m": _OUTER_R_M * math.sqrt(2),
        "theoretical_radius_m": _OUTER_R_M,
        "changed_cells": changed_cells,
        "perturb_x": perturb_x,
        "perturb_y": perturb_y,
    }
