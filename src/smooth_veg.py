"""Lissage des contours végétation supervised_e — Variante B.

Lisse uniquement les frontières communes entre classes (arc gaussien).
Aucun vote raster, aucun filtrage par surface, grille native 2 m.

Paramètres du prototype validé (geometry verify_b.py : 3/3 OK) :
  ARC_SIGMA_M = 1.5   sigma du filtre gaussien le long des arcs
  ARC_STEP_M  = 0.5   pas de rééchantillonnage des arcs
  SIMPLIFY_M  = 0.5   tolérance coverage_simplify

ALGO_VERSION doit être incrémenté à chaque modification de paramètre ou
d'algorithme — il sert à invalider le cache GPKG.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import shapely
from affine import Affine
from rasterio.features import shapes
from rasterio.transform import rowcol
from scipy import ndimage
from shapely.geometry import LineString, Polygon, shape as _shape

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

UNKNOWN: int = 254       # pixels sans couverture LiDAR (hors export, arcs verrouillés)
NODATA_CODE: int = 255   # pixels hors emprise (traités comme UNKNOWN dans prepare_grid)

ARC_STEP_M: float = 0.5
ARC_SIGMA_M: float = 1.5
SIMPLIFY_M: float = 0.5
ALGO_VERSION: str = "B-sigma1.5-step0.5-simplify0.5"

# label raster → class_id exporté (0,2,3,4 — classe 1 = blanc non exportée)
_LABEL_TO_CLASS: dict[int, int] = {0: 0, 2: 2, 3: 3, 4: 4}

_TOL_M2: float = 1e-4  # tolérance numérique (bruit flottant shapely)


# ── Préparation de la grille ──────────────────────────────────────────────────

def prepare_grid(pred: np.ndarray, support: np.ndarray) -> np.ndarray:
    """Fusionne prédiction et masque de support en une grille de labels de travail.

    Pixels support==0 ou pred==NODATA_CODE → UNKNOWN=254.
    """
    labels = pred.copy().astype(np.uint8)
    labels[(support == 0) | (pred == NODATA_CODE)] = UNKNOWN
    return labels


# ── Polygonisation en couverture valide ──────────────────────────────────────

def _values_at(
    faces: np.ndarray, labels: np.ndarray, transform: Affine
) -> np.ndarray:
    """Label lu sous le point représentatif (intérieur) de chaque face."""
    pts = shapely.point_on_surface(faces)
    rows, cols = rowcol(transform, shapely.get_x(pts), shapely.get_y(pts))
    rows = np.clip(np.asarray(rows, dtype=int), 0, labels.shape[0] - 1)
    cols = np.clip(np.asarray(cols, dtype=int), 0, labels.shape[1] - 1)
    return labels[rows, cols]


def to_coverage(
    labels: np.ndarray, transform: Affine
) -> tuple[np.ndarray, np.ndarray]:
    """Polygonise toute la grille en couverture valide avec noding.

    rasterio.shapes() sans noding laisse des T-jonctions sans sommet commun.
    Union des frontières + repolygonisation garantit la topologie correcte.
    """
    geom_list = [_shape(g) for g, _ in shapes(labels, connectivity=4, transform=transform)]
    n_regions = len(geom_list)
    polys = np.array(geom_list, dtype=object)
    lines = shapely.union_all(shapely.boundary(polys))
    faces = shapely.get_parts(shapely.polygonize([lines]))
    if len(faces) != n_regions:
        raise ValueError(
            f"to_coverage: {n_regions} régions rasterio → {len(faces)} faces après noding "
            "(topologie inattendue)"
        )
    values = _values_at(faces, labels, transform)
    return faces, values


def _make_frame(labels: np.ndarray, transform: Affine) -> Polygon:
    """Rectangle englobant de la grille de labels."""
    h, w = labels.shape
    res = abs(float(transform.a))
    xmin = float(transform.c)
    ymax = float(transform.f)
    return shapely.box(xmin, ymax - h * res, xmin + w * res, ymax)


# ── Lissage des arcs ──────────────────────────────────────────────────────────

def _gauss_along(xy: np.ndarray, sigma_m: float, closed: bool) -> np.ndarray:
    """Rééchantillonne un arc tous les ARC_STEP_M m puis le filtre gaussien.

    Anneau fermé  : filtre circulaire (mode wrap), point final = point initial.
    Arc ouvert    : extrémités fixes, extension symétrique aux bords.
    Arcs trop courts (< 8 pas) : retournés tels quels.
    """
    seg = np.hypot(*np.diff(xy, axis=0).T)
    total = float(seg.sum())
    n = int(total / ARC_STEP_M)
    if n < 8:
        return xy
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    s = sigma_m / ARC_STEP_M
    if closed:
        t = total * np.arange(n) / n
        cols = [
            ndimage.gaussian_filter1d(np.interp(t, cum, xy[:, c]), s, mode="wrap")
            for c in (0, 1)
        ]
        return np.column_stack([np.append(c, c[0]) for c in cols])
    t = np.linspace(0.0, total, n + 1)
    cols = []
    for c in (0, 1):
        v = np.interp(t, cum, xy[:, c])
        k = min(len(v) - 1, int(4 * s) + 1)
        ext = np.concatenate([2 * v[0] - v[k:0:-1], v, 2 * v[-1] - v[-2 : -k - 2 : -1]])
        cols.append(ndimage.gaussian_filter1d(ext, s, mode="nearest")[k : k + len(v)])
    out = np.column_stack(cols)
    out[0], out[-1] = xy[0], xy[-1]
    return out


def _match_values(
    new: np.ndarray, faces: np.ndarray, values: np.ndarray
) -> np.ndarray | None:
    """Label de chaque face lissée = celui de la face d'origine avec le plus grand recouvrement.

    Retourne None si l'appariement n'est pas bijectif (deux nouvelles faces sur la même
    ancienne, ou une nouvelle face sans chevauchement).
    """
    i_new, i_old = shapely.STRtree(faces).query(new, predicate="intersects")
    if len(i_new) == 0:
        return None
    area = shapely.area(shapely.intersection(new[i_new], faces[i_old]))
    order = np.lexsort((area, i_new))
    i_new_s, i_old_s = i_new[order], i_old[order]
    boundary = np.r_[i_new_s[1:] != i_new_s[:-1], True]
    unique_new = i_new_s[boundary]
    best_old = i_old_s[boundary]
    if len(unique_new) != len(new):
        return None
    if len(np.unique(best_old)) != len(faces):
        return None
    out = np.empty(len(new), dtype=values.dtype)
    out[unique_new] = values[best_old]
    return out


def smooth_arcs(
    faces: np.ndarray,
    values: np.ndarray,
    frame: Polygon,
    sigma_m: float,
    simplify_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Lisse les frontières communes, verrouille celles adjacentes au cadre ou à UNKNOWN.

    Lève ValueError pour tout échec topologique — aucun repli silencieux.
    """
    on_frame = frame.boundary.buffer(1e-6)
    shapely.prepare(on_frame)

    unknown_mask = values == UNKNOWN
    if unknown_mask.any():
        unk_boundary = shapely.union_all(
            shapely.boundary(faces[unknown_mask])
        ).buffer(1e-6)
        shapely.prepare(unk_boundary)

        def _locked(arc: shapely.Geometry) -> bool:
            return on_frame.covers(arc) or unk_boundary.covers(arc)
    else:
        def _locked(arc: shapely.Geometry) -> bool:
            return on_frame.covers(arc)

    arcs = shapely.get_parts(
        shapely.line_merge(shapely.union_all(shapely.boundary(faces)))
    )
    smoothed_lines = []
    for a in arcs:
        if _locked(a):
            smoothed_lines.append(a)
        else:
            xy = np.asarray(a.coords)
            new_xy = _gauss_along(xy, sigma_m, bool(a.is_ring))
            smoothed_lines.append(LineString(new_xy))

    new_faces = shapely.get_parts(shapely.polygonize(smoothed_lines))
    if len(new_faces) != len(faces):
        raise ValueError(
            f"smooth_arcs: {len(faces)} faces avant lissage -> {len(new_faces)} apres "
            f"(topologie cassee, {len(smoothed_lines)} arcs)"
        )
    if not shapely.coverage_is_valid(new_faces):
        raise ValueError("smooth_arcs: coverage_is_valid() echoue apres lissage des arcs")

    new_values = _match_values(new_faces, faces, values)
    if new_values is None:
        raise ValueError("smooth_arcs: _match_values echoue apres lissage")

    simplified = shapely.coverage_simplify(new_faces, tolerance=simplify_m)
    if not shapely.coverage_is_valid(simplified):
        raise ValueError("smooth_arcs: coverage_is_valid() echoue apres coverage_simplify")

    final_values = _match_values(simplified, new_faces, new_values)
    if final_values is None:
        raise ValueError("smooth_arcs: _match_values echoue apres simplification")

    return simplified, final_values


# ── Point d'entrée vectorisation ─────────────────────────────────────────────

def smoothed_vectorize(
    pred: np.ndarray,
    support: np.ndarray,
    transform: Affine,
) -> dict[int, list[Polygon]]:
    """Vectorise le raster avec lissage des frontières communes (variante B validée).

    Paramètres : ARC_SIGMA_M=1.5, ARC_STEP_M=0.5, SIMPLIFY_M=0.5 (voir ALGO_VERSION).

    Retourne {class_id: [Polygon, ...]} avec class_id in {0, 2, 3, 4} (même format
    que vectorize_prediction en mode faithful/generalized).

    Lève ValueError en cas d'échec topologique — aucun repli silencieux.
    """
    labels = prepare_grid(pred, support)
    faces, values = to_coverage(labels, transform)
    if not shapely.coverage_is_valid(faces):
        raise ValueError("smoothed_vectorize: couverture invalide apres polygonisation")
    frame = _make_frame(labels, transform)
    faces_s, values_s = smooth_arcs(faces, values, frame, ARC_SIGMA_M, SIMPLIFY_M)

    result: dict[int, list[Polygon]] = {c: [] for c in _LABEL_TO_CLASS}
    for geom, value in zip(faces_s, values_s):
        class_id = _LABEL_TO_CLASS.get(int(value))
        if class_id is not None and not shapely.is_empty(geom):
            result[class_id].append(geom)

    n_total = sum(len(v) for v in result.values())
    log.info(
        "smoothed_vectorize: %d faces, %d polygones exportes {0:%d, 2:%d, 3:%d, 4:%d}",
        len(faces_s), n_total,
        len(result[0]), len(result[2]), len(result[3]), len(result[4]),
    )
    return result


# ── Validation géométrique ────────────────────────────────────────────────────

def validate_smoothed_coverage(
    polys_by_class: dict[int, list[Polygon]],
    support: np.ndarray,
    transform: Affine,
) -> None:
    """Vérifie la couverture complète, absence de recouvrements et de débordements.

    Contrôles (tolérances _TOL_M2 = 1e-4 m²) :
      1. Aucun débordement hors support
      2. Aucune invasion de la zone UNKNOWN
      3. union_B + blanc = non_unk (couverture complète, sans vide)
      4. Aucun recouvrement entre polygones exportés

    Lève ValueError avec description précise — aucun fallback silencieux.
    """
    supp_u8 = support.astype(np.uint8)
    supp_polys = [
        _shape(g) for g, v in shapes(supp_u8, mask=supp_u8, transform=transform) if v == 1
    ]
    if not supp_polys:
        raise ValueError("validate_smoothed_coverage: support vide")
    support_poly = shapely.union_all(np.array(supp_polys, dtype=object))

    nodata_u8 = (support == 0).astype(np.uint8)
    unk_polys = [
        _shape(g) for g, v in shapes(nodata_u8, mask=nodata_u8, transform=transform) if v == 1
    ]
    unknown_poly = shapely.union_all(np.array(unk_polys, dtype=object)) if unk_polys else None

    non_unk = shapely.difference(support_poly, unknown_poly) if unknown_poly else support_poly

    all_polys = [p for ps in polys_by_class.values() for p in ps]
    if not all_polys:
        log.info("validate_smoothed_coverage: aucun polygone veg (tout blanc) — OK")
        return

    arr = np.array(all_polys, dtype=object)
    union_b = shapely.union_all(arr)

    # 1. Débordement hors support
    overflow = float(shapely.area(shapely.difference(union_b, support_poly)))
    if overflow > _TOL_M2:
        raise ValueError(
            f"validate_smoothed_coverage: debordement hors support {overflow:.4f} m2 > {_TOL_M2}"
        )

    # 2. Invasion UNKNOWN
    invasion = 0.0
    if unknown_poly is not None and not shapely.is_empty(unknown_poly):
        invasion = float(shapely.area(shapely.intersection(union_b, unknown_poly)))
        if invasion > _TOL_M2:
            raise ValueError(
                f"validate_smoothed_coverage: invasion UNKNOWN {invasion:.4f} m2 > {_TOL_M2}"
            )

    # 3. Couverture complète
    blanc = shapely.difference(non_unk, union_b)
    residual = abs(
        float(shapely.area(union_b)) + float(shapely.area(blanc)) - float(shapely.area(non_unk))
    )
    if residual > _TOL_M2:
        raise ValueError(
            f"validate_smoothed_coverage: residu couverture {residual:.2e} m2 > {_TOL_M2} "
            "(vide entre exportes+blanc et support)"
        )

    # 4. Recouvrements
    i_a, i_b_idx = shapely.STRtree(arr).query(arr, predicate="overlaps")
    pairs = i_a < i_b_idx
    total_overlap = sum(
        float(shapely.area(shapely.intersection(arr[ia], arr[ib])))
        for ia, ib in zip(i_a[pairs], i_b_idx[pairs])
    )
    if total_overlap > _TOL_M2:
        raise ValueError(
            f"validate_smoothed_coverage: recouvrements {total_overlap:.4f} m2 > {_TOL_M2}"
        )

    log.info(
        "validate_smoothed_coverage: OK "
        "(overflow=%.2e, invasion=%.2e, residual=%.2e, overlaps=%.2e)",
        overflow, invasion, residual, total_overlap,
    )
