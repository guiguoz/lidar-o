"""Métriques de densité LiDAR pour classification végétation.

Phase 1 du plan PLAN_vegetation_406.md :
  - Étape B : compute_nrd  (NRD façon Blaze, exclut canopée du dénominateur)
  - Étape D : compute_nrd_bands  (NRD séparé bandes low 0.3–1.3 m / mid 1.3–4.0 m)
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import generic_filter


def compute_ratio(
    hag_count: np.ndarray,
    total_count: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """Ratio HAG/total (mode T8 actuel).

    Args:
        hag_count:   Retours HAG [min:max] par cellule.
        total_count: Total retours (toutes hauteurs) par cellule.
        mask:        True = cellule invalide (nodata source).

    Returns:
        Ratio float32 ∈ [0, 1]. Vaut 0.0 où mask ou total=0.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(
            (total_count > 0) & ~mask,
            hag_count / total_count,
            0.0,
        )
    return np.clip(ratio, 0.0, 1.0).astype(np.float32)


def compute_nrd(
    band_count: np.ndarray,
    below_count: np.ndarray,
    mask: np.ndarray,
    n_min: int = 8,
    fill_radius: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Normalized Relative Density (NRD) façon Blaze / foresterie.

    NRD = band / (band + below).
    Les retours au-dessus de la bande (canopée) sont exclus du dénominateur —
    propriété clé qui distingue NRD du simple ratio HAG/total.

    Cellules avec (band + below) < n_min → NoData, comblé par moyenne de
    voisinage dans un rayon fill_radius (cellules).

    Args:
        band_count:  Retours dans la bande cible par cellule.
        below_count: Retours sous la bande (sol/HAG<min) par cellule.
        mask:        True = cellule invalide (nodata source).
        n_min:       Impulsions pénétrantes minimales. Défaut 8.
        fill_radius: Rayon remplissage NoData (cellules). Défaut 2.

    Returns:
        (nrd, confidence) :
            nrd        float32 [0, 1], 0.0 où non calculable.
            confidence uint16  = band + below (nb impulsions pénétrantes).

    Note (pour plus tard) :
        Le garde-fou n_min est binaire : cellule valide OU NoData puis fill.
        Ce seuil dur est arbitraire et crée un artefact mesurable : avec médiane_HAG=1
        à 1 m, 73 % des cellules passent par le fill → NRD@1m mesure principalement
        la qualité du fill, pas la formule NRD elle-même.
        Alternative plus propre : remplacer le seuil dur par un lissage gaussien
        pondéré par confidence. Chaque cellule contribue proportionnellement à son
        nombre d'impulsions pénétrantes, sans binarisation NoData.
        Le « NRD peu fiable » mesuré à 1 m est peut-être un artefact du garde-fou
        choisi, pas de la métrique NRD. À tester séparément avant de conclure.
    """
    penetrating = (band_count + below_count).astype(np.float32)
    confidence = np.clip(penetrating, 0, 65535).astype(np.uint16)

    valid = (penetrating >= n_min) & ~mask
    with np.errstate(invalid="ignore", divide="ignore"):
        nrd = np.where(valid, band_count / penetrating, np.nan)

    if fill_radius > 0:
        size = 2 * fill_radius + 1

        def _mean_nonnan(values: np.ndarray) -> float:
            v = values[~np.isnan(values)]
            return float(np.mean(v)) if v.size > 0 else np.nan

        filled = generic_filter(
            nrd, _mean_nonnan, size=size, mode="constant", cval=np.nan
        )
        nrd = np.where(np.isnan(nrd) & ~mask, filled, nrd)

    nrd = np.nan_to_num(nrd, nan=0.0)
    return nrd.astype(np.float32), confidence


def compute_nrd_bands(
    low_count: np.ndarray,
    mid_count: np.ndarray,
    below_count: np.ndarray,
    mask: np.ndarray,
    n_min: int = 8,
    fill_radius: int = 2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NRD séparé pour bande basse (low) et bande moyenne (mid) — Étape D.

    Physique :
      nrd_low = low / (low + below)
          → fraction des impulsions atteignant la bande basse qui y sont stoppées
      nrd_mid = mid / (mid + low + below)
          → fraction des impulsions atteignant la bande mid qui y sont stoppées
          ("below" de mid = tout ce qui a traversé mid sans y être absorbé)

    Args:
        low_count:   Retours bande basse (0.3–low_h m).
        mid_count:   Retours bande moyenne (low_h–max m).
        below_count: Retours sous la bande basse (HAG < 0.3 m).
        mask:        True = cellule invalide.
        n_min:       Impulsions pénétrantes minimales.
        fill_radius: Rayon remplissage NoData (cellules).

    Returns:
        (nrd_low, nrd_mid, confidence) :
            nrd_low    float32 [0, 1]
            nrd_mid    float32 [0, 1]
            confidence uint16  = below + low + mid
    """
    nrd_low, _ = compute_nrd(low_count, below_count, mask, n_min, fill_radius)

    # Dénominateur mid : impulsions ayant atteint la bande mid sans être absorbées
    # = low + below (retours ayant traversé mid sans y rester)
    below_mid = (low_count + below_count).astype(np.float32)
    nrd_mid, _ = compute_nrd(mid_count, below_mid, mask, n_min, fill_radius)

    confidence = np.clip(
        below_count + low_count + mid_count, 0, 65535
    ).astype(np.uint16)

    return nrd_low, nrd_mid, confidence
