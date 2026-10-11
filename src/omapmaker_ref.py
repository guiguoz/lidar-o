"""Reproduction fidèle de la méthode omapmaker — référence expérimentale V0.

Paramètres figés (§1.1, PLAN_TECHNIQUE_V0.md v1.0) :
  résolution  : 0.5 m/px
  strates     : ground < 0.2 m · low [0.2, 1.5[ · medium [1.5, 3.0[ · high ≥ 3.0 m
  pondération : V = 0.50·low + 0.35·medium + 0.15·high
  NDVD        : ((V − G) / (V + G) + 1) / 2
  voisinage   : gaussien, rayon 2 m, σ = 1 m
  seuils      : 0.4 → 406 · 0.6 → 408 · 0.8 → 410
  retours     : TOUS les points non-withheld (aucun filtre LAS)

Définition du sol (§2) :
  DTM depuis class 2 (Ground) + class 9 (Water)
  g = densité de TOUS les retours à HAG < 0.2 m (pas seulement les classés sol)

ÉCARTS SIGNALÉS À LA CHAÎNE OMAPMAKER ORIGINALE :
  [DEVIATION-DTM] DTM par minimum de points sol par cellule + hole-fill nearest-neighbor.
                  Omapmaker utilise triangulation de Delaunay + natural-neighbor (crate spade).
                  Négligeable à 15 impl/m² (quasi-absence de cellules vides).
  [DEVIATION-OUT] Pas de sortie vecteur .omap (binaire Rust non disponible).
                  Sortie raster uniquement. classes_gen.tif = classes.tif car omapmaker
                  n'applique aucune morphologie raster post-seuillage (généralisation
                  vectorielle seulement : simplification + buffer dans compute_vegetation.rs).
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

import numpy as np
import pdal
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds, rowcol
from scipy.ndimage import distance_transform_edt, gaussian_filter

log = logging.getLogger(__name__)

# ── Paramètres figés §1.1 ─────────────────────────────────────────────────────
_RES_M: float = 0.5
_SIGMA_M: float = 1.0
_RADIUS_M: float = 2.0
_H_LOW: float = 0.2    # borne ground / low
_H_MED: float = 1.5    # borne low / medium
_H_HIGH: float = 3.0   # borne medium / high
_W_LOW: float = 0.50
_W_MED: float = 0.35
_W_HIGH: float = 0.15
_T_406: float = 0.4
_T_408: float = 0.6
_T_410: float = 0.8

# ── Définition du sol §2 ──────────────────────────────────────────────────────
_GROUND_LAS_CLASSES: frozenset[int] = frozenset({2, 9})  # Ground + Water


# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read_points(
    copc_paths: list[str | pathlib.Path],
    bbox: tuple[float, float, float, float],
    expression: str | None = None,
) -> np.ndarray:
    """Lit tous les points non-withheld depuis les fichiers COPC.

    expression : filtre PDAL optionnel avant le crop (ex. "Classification == 2").
    Retourne un tableau structuré numpy avec au moins X, Y, Z, Classification.
    """
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
    log.debug("PDAL : %d points lus (expr=%s)", n_pts, expression or "none")

    arrays = pipe.arrays
    if not arrays:
        return np.empty(0)
    pts = np.concatenate(arrays) if len(arrays) > 1 else arrays[0]

    if "Withheld" in pts.dtype.names:
        pts = pts[~pts["Withheld"].astype(bool)]
    else:
        log.warning("[DEVIATION] Dimension 'Withheld' absente — aucun filtrage")

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
    profile = {
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

    log.info("Écrit : %s (%s, %d bande(s))", path.name, arr.dtype, count)


# ─────────────────────────────────────────────────────────────────────────────
# Étapes du pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _update_dtm(
    dtm: np.ndarray,
    gx: np.ndarray,
    gy: np.ndarray,
    gz: np.ndarray,
    rows: int,
    cols: int,
    transform: Any,
) -> None:
    """Met à jour dtm (minimum par cellule) avec les points sol d'une tuile."""
    ri, ci = rowcol(transform, gx, gy)
    ri = np.asarray(ri, dtype=np.intp)
    ci = np.asarray(ci, dtype=np.intp)
    valid = (ri >= 0) & (ri < rows) & (ci >= 0) & (ci < cols)
    np.minimum.at(dtm, (ri[valid], ci[valid]), gz[valid].astype(np.float32))


def _finalize_dtm(dtm: np.ndarray) -> None:
    """Hole-fill nearest-neighbor sur les cellules sans point sol.

    [DEVIATION-DTM] Approximation de natural-neighbor. Négligeable à haute densité.
    """
    holes = dtm == np.inf
    n_holes = int(holes.sum())
    if n_holes:
        _, idx = distance_transform_edt(holes, return_indices=True)
        dtm[holes] = dtm[idx[0][holes], idx[1][holes]]
        log.info("DTM : %d cellules sans point sol comblées", n_holes)
    log.info(
        "DTM : min=%.1f m, max=%.1f m, median=%.1f m",
        float(dtm.min()), float(dtm.max()), float(np.median(dtm)),
    )


def _compute_hag(
    pts_x: np.ndarray,
    pts_y: np.ndarray,
    pts_z: np.ndarray,
    dtm: np.ndarray,
    transform: Any,
) -> np.ndarray:
    """HAG = Z − DTM(x, y) pour tous les points."""
    rows, cols = dtm.shape
    ri, ci = rowcol(transform, pts_x, pts_y)
    ri = np.asarray(ri, dtype=np.intp)
    ci = np.asarray(ci, dtype=np.intp)

    hag = np.full(len(pts_z), np.nan, dtype=np.float32)
    valid = (ri >= 0) & (ri < rows) & (ci >= 0) & (ci < cols)
    hag[valid] = pts_z[valid].astype(np.float32) - dtm[ri[valid], ci[valid]]

    log.info(
        "HAG : p1=%.2f m, p50=%.2f m, p99=%.2f m (sur %d pts valides / %d)",
        float(np.nanpercentile(hag, 1)), float(np.nanmedian(hag)),
        float(np.nanpercentile(hag, 99)), int(valid.sum()), len(hag),
    )
    return hag


def _accumulate_counts(
    counts: np.ndarray,
    pts_x: np.ndarray,
    pts_y: np.ndarray,
    hag: np.ndarray,
    rows: int,
    cols: int,
    transform: Any,
) -> None:
    """Accumule les comptages bruts d'une tuile dans counts (4, rows, cols).

    Bandes : 0=ground, 1=low, 2=medium, 3=high.
    g (bande 0) = TOUS les retours à HAG < 0.2 m, aucun filtre LAS.
    """
    ri, ci = rowcol(transform, pts_x, pts_y)
    ri = np.asarray(ri, dtype=np.intp)
    ci = np.asarray(ci, dtype=np.intp)

    valid = (ri >= 0) & (ri < rows) & (ci >= 0) & (ci < cols) & ~np.isnan(hag)
    ri, ci, h = ri[valid], ci[valid], hag[valid]

    for band, mask in enumerate([
        h < _H_LOW,
        (h >= _H_LOW) & (h < _H_MED),
        (h >= _H_MED) & (h < _H_HIGH),
        h >= _H_HIGH,
    ]):
        np.add.at(counts[band], (ri[mask], ci[mask]), 1)


def _gaussian_density(raw_counts: np.ndarray) -> np.ndarray:
    """Voisinage gaussien σ=1 m, rayon=2 m, résolution 0.5 m/px.

    sigma_px = σ / résolution = 2.0 px
    truncate = rayon / (sigma_px × résolution) = 2.0  →  rayon effectif = 4 px = 2 m
    """
    sigma_px = _SIGMA_M / _RES_M      # 2.0 pixels
    truncate = _RADIUS_M / _SIGMA_M   # 2.0 (en unités sigma)
    result = np.empty_like(raw_counts, dtype=np.float32)
    for i in range(4):
        result[i] = gaussian_filter(
            raw_counts[i].astype(np.float32),
            sigma=sigma_px,
            truncate=truncate,
        )
    return result


def _ndvd(densities: np.ndarray) -> np.ndarray:
    """NDVD = ((V − g) / (V + g) + 1) / 2  avec V = 0.50·low + 0.35·med + 0.15·high.

    Retourne NaN quand V+g=0 (aucun retour) — ces pixels restent classe 0 après seuillage.
    """
    g = densities[0]
    V = _W_LOW * densities[1] + _W_MED * densities[2] + _W_HIGH * densities[3]
    denom = V + g
    valid = denom > 0.0
    raw = np.full_like(denom, np.nan, dtype=np.float32)
    raw[valid] = (V[valid] - g[valid]) / denom[valid]
    return ((raw + 1.0) / 2.0).astype(np.float32)


def _classify(ndvd: np.ndarray) -> np.ndarray:
    """Seuillage : 0.4→406 · 0.6→408 · 0.8→410."""
    cls = np.zeros(ndvd.shape, dtype=np.uint16)
    cls[ndvd >= _T_406] = 406
    cls[ndvd >= _T_408] = 408
    cls[ndvd >= _T_410] = 410
    return cls


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────────────────────────────────────

def run(
    copc_paths: list[str | pathlib.Path],
    bbox: tuple[float, float, float, float],
    output_dir: str | pathlib.Path,
    crs: str = "EPSG:2154",
) -> dict[str, pathlib.Path]:
    """Pipeline complet : reproduction fidèle d'omapmaker.

    Traitement en deux passes tuile par tuile pour limiter la mémoire peak.
    270 M retours sur l'emprise complète de Grimbosq (6 km²) seraient
    ~38 GB en tableau monolithique ; chaque tuile COPC ~45 M pts ≈ 6 GB.

    Sorties conservées (§3) :
      omapmaker_dtm.tif                        DTM artefact de contrôle
      omapmaker_strates.tif                    comptages bruts (4 bandes)
      omapmaker_signal_brut.tif                NDVD avant voisinage gaussien
      omapmaker_signal_apres_voisinage.tif     NDVD après voisinage gaussien
      omapmaker_classes.tif                    0/406/408/410 après seuillage
      omapmaker_classes_gen.tif                idem (aucune généralisation raster)
    """
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copc_paths = [pathlib.Path(p) for p in copc_paths]

    xmin, ymin, xmax, ymax = bbox
    cols = int(np.ceil((xmax - xmin) / _RES_M))
    rows = int(np.ceil((ymax - ymin) / _RES_M))
    transform = from_bounds(xmin, ymin, xmax, ymax, cols, rows)
    log.info("Grille : %d x %d px (%.0f x %.0f m)", cols, rows, xmax - xmin, ymax - ymin)

    # ── Passe 1 : DTM depuis class 2 + 9 (une tuile à la fois) ─────────────
    log.info("Passe 1/%d : DTM (class 2+9)...", len(copc_paths))
    dtm = np.full((rows, cols), np.inf, dtype=np.float32)
    ground_expr = " || ".join(f"Classification == {c}" for c in sorted(_GROUND_LAS_CLASSES))
    total_ground = 0
    for i, path in enumerate(copc_paths, 1):
        pts = _read_points([path], bbox, expression=ground_expr)
        if len(pts) == 0:
            log.info("  tuile %d/%d : 0 point sol", i, len(copc_paths))
            continue
        gx = pts["X"].astype(np.float32)
        gy = pts["Y"].astype(np.float32)
        gz = pts["Z"].astype(np.float32)
        del pts
        _update_dtm(dtm, gx, gy, gz, rows, cols, transform)
        total_ground += len(gx)
        log.info("  tuile %d/%d : %d points sol (cumul=%d)", i, len(copc_paths), len(gx), total_ground)
        del gx, gy, gz

    _finalize_dtm(dtm)
    _write_tif(dtm, output_dir / "omapmaker_dtm.tif", transform, crs, nodata=-9999.0)

    # ── Passe 2 : HAG + comptages (une tuile à la fois) ─────────────────────
    log.info("Passe 2/%d : HAG + strates...", len(copc_paths))
    raw_counts = np.zeros((4, rows, cols), dtype=np.float32)
    total_pts = 0
    for i, path in enumerate(copc_paths, 1):
        pts = _read_points([path], bbox)
        if len(pts) == 0:
            log.info("  tuile %d/%d : 0 point", i, len(copc_paths))
            continue
        pts_x = pts["X"].astype(np.float32)
        pts_y = pts["Y"].astype(np.float32)
        pts_z = pts["Z"].astype(np.float32)
        del pts
        hag = _compute_hag(pts_x, pts_y, pts_z, dtm, transform)
        _accumulate_counts(raw_counts, pts_x, pts_y, hag, rows, cols, transform)
        total_pts += len(pts_x)
        log.info("  tuile %d/%d : %d points (cumul=%d)", i, len(copc_paths), len(pts_x), total_pts)
        del pts_x, pts_y, pts_z, hag

    totals = [int(raw_counts[b].sum()) for b in range(4)]
    log.info("Strates totales : g=%d low=%d med=%d high=%d", *totals)

    _write_tif(
        raw_counts, output_dir / "omapmaker_strates.tif", transform, crs, nodata=-1.0,
        descriptions=["ground_raw_lt0.2m", "low_raw_0.2-1.5m",
                       "med_raw_1.5-3.0m", "high_raw_ge3.0m"],
    )

    # ── NDVD brut (avant voisinage) ──────────────────────────────────────────
    ndvd_brut = _ndvd(raw_counts)
    _write_tif(ndvd_brut, output_dir / "omapmaker_signal_brut.tif",
               transform, crs, nodata=-9999.0)

    # ── Voisinage gaussien ───────────────────────────────────────────────────
    log.info("Voisinage gaussien (sigma=%.1f m, r=%.1f m)...", _SIGMA_M, _RADIUS_M)
    smooth = _gaussian_density(raw_counts)
    del raw_counts

    ndvd_smooth = _ndvd(smooth)
    _write_tif(ndvd_smooth, output_dir / "omapmaker_signal_apres_voisinage.tif",
               transform, crs, nodata=-9999.0)
    del smooth

    # ── Seuillage → classes ──────────────────────────────────────────────────
    classes = _classify(ndvd_smooth)
    del ndvd_smooth
    _write_tif(classes, output_dir / "omapmaker_classes.tif", transform, crs, nodata=0)
    # classes_gen = classes (aucune morphologie raster dans omapmaker)
    _write_tif(classes, output_dir / "omapmaker_classes_gen.tif", transform, crs, nodata=0)

    paths = {
        "dtm": output_dir / "omapmaker_dtm.tif",
        "strates": output_dir / "omapmaker_strates.tif",
        "signal_brut": output_dir / "omapmaker_signal_brut.tif",
        "signal_apres_voisinage": output_dir / "omapmaker_signal_apres_voisinage.tif",
        "classes": output_dir / "omapmaker_classes.tif",
        "classes_gen": output_dir / "omapmaker_classes_gen.tif",
    }
    log.info("omapmaker_ref termine -> %s", output_dir)
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Mesure d'empreinte par perturbation (§4)
# ─────────────────────────────────────────────────────────────────────────────

def measure_empreinte(
    output_dir: str | pathlib.Path,
    perturb_x: float,
    perturb_y: float,
    crs: str = "EPSG:2154",
) -> dict[str, Any]:
    """Mesure l'empreinte spatiale effective d'omapmaker par perturbation.

    Protocole (§4) :
      Perturbe un pixel dans omapmaker_strates.tif (avant voisinage),
      relance depuis le voisinage gaussien, mesure la propagation dans le
      raster de classes.

    Point de perturbation : fournir une coordonnée Lambert-93 (perturb_x, perturb_y)
    proche du bord S de la zone validation (split_y + buffer_half_width_m).

    Sauvegarde omapmaker_empreinte_diff.tif dans output_dir.
    """
    output_dir = pathlib.Path(output_dir)

    base_strates_path = output_dir / "omapmaker_strates.tif"
    base_classes_path = output_dir / "omapmaker_classes.tif"
    for p in (base_strates_path, base_classes_path):
        if not p.exists():
            raise FileNotFoundError(f"Lancer run() avant measure_empreinte() : {p}")

    with rasterio.open(base_strates_path) as src:
        raw_counts = src.read().astype(np.float32)   # (4, rows, cols)
        transform = src.transform
        rows, cols = src.height, src.width

    with rasterio.open(base_classes_path) as src:
        base_classes = src.read(1)

    pr, pc = rowcol(transform, perturb_x, perturb_y)
    pr, pc = int(pr), int(pc)
    if not (0 <= pr < rows and 0 <= pc < cols):
        raise ValueError(
            f"Point de perturbation ({perturb_x}, {perturb_y}) hors grille "
            f"(row={pr}, col={pc}, grille={rows}×{cols})"
        )

    # Perturbation : +1000 points dans la strate high pour garantir un flip de classe.
    # (forêt dense : signal >> 1; +1000 ~= 15 impl/m² × 4px² × poids kernel ≈ assez fort)
    perturbed = raw_counts.copy()
    perturbed[3, pr, pc] += 1000.0

    sigma_px = _SIGMA_M / _RES_M
    truncate = _RADIUS_M / _SIGMA_M
    smooth_p = np.empty_like(perturbed)
    for i in range(4):
        smooth_p[i] = gaussian_filter(perturbed[i], sigma=sigma_px, truncate=truncate)

    classes_p = _classify(_ndvd(smooth_p))
    diff = (classes_p != base_classes).astype(np.uint8)

    changed = int(diff.sum())
    if changed == 0:
        log.info("Empreinte : perturbation sans effet visible (0 cellules)")
        max_dist_m = 0.0
    else:
        dr, dc = np.where(diff)
        max_dist_m = float(
            np.sqrt(((dr - pr) * _RES_M) ** 2 + ((dc - pc) * _RES_M) ** 2).max()
        )
        log.info(
            "Empreinte omapmaker : rayon max = %.2f m, cellules changées = %d",
            max_dist_m, changed,
        )

    _write_tif(diff, output_dir / "omapmaker_empreinte_diff.tif", transform, crs)

    # Rayon théorique circulaire = _RADIUS_M (2 m).
    # Sur grille carrée la diagonale du noyau = RADIUS × √2 ≈ 2.83 m ;
    # theoretical_max_m expose la diagonale carrée pour le contrôle.
    import math
    result: dict[str, Any] = {
        "max_dist_m": max_dist_m,
        "changed_cells": changed,
        "perturb_x": perturb_x,
        "perturb_y": perturb_y,
        "perturb_row": pr,
        "perturb_col": pc,
        "theoretical_max_m": _RADIUS_M * math.sqrt(2),
        "theoretical_radius_m": _RADIUS_M,
    }
    log.info("Résultat empreinte : %s", result)
    return result
