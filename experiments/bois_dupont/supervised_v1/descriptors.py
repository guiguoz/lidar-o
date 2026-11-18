"""Calcul des descripteurs LiDAR multi-échelles depuis le raster de strates.

Descripteurs interdits (vérification explicite) :
  - coordonnées X/Y absolues ou indices ligne/colonne
  - toute information dérivée du raster OCAD
  - informations calculées depuis les étiquettes cibles

30 features = 3 échelles × 10 descripteurs par échelle :
  n, support, prop_g, prop_lo, prop_me, prop_hi, prop_veg,
  ndvd (best_v2 weights), frac_hi_veg, frac_me_veg

Toutes les features sont reproductibles depuis le raster de strates uniquement.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter
import rasterio

from config import (
    STRATES_PATH, RES_M,
    SCALES, TRUNCATE, MIN_SUPPORT,
    W_LOW, W_MED, W_HIGH,
    DESCRIPTORS_FILE,
)


# ── Noms des features ─────────────────────────────────────────────────────

def _scale_feature_names(scale_name: str) -> list[str]:
    return [
        f"n_{scale_name}",             # densité totale lissée (proxy)
        f"support_{scale_name}",       # 1 si n > MIN_SUPPORT, sinon 0
        f"prop_g_{scale_name}",        # proportion retours sol
        f"prop_lo_{scale_name}",       # proportion vég basse [H_LOW, H_MED)
        f"prop_me_{scale_name}",       # proportion vég moyenne [H_MED, H_HIGH)
        f"prop_hi_{scale_name}",       # proportion vég haute [H_HIGH, ∞)
        f"prop_veg_{scale_name}",      # proportion toute végétation
        f"ndvd_{scale_name}",          # NDVD normalisé [0,1] (poids best_v2)
        f"frac_hi_veg_{scale_name}",   # haute vég / (lo+me+hi)
        f"frac_me_veg_{scale_name}",   # moy vég / (lo+me+hi)
    ]


FEATURE_NAMES: list[str] = []
for _sname, _ in SCALES:
    FEATURE_NAMES.extend(_scale_feature_names(_sname))

N_FEATURES = len(FEATURE_NAMES)   # 30

# Vérification : aucun nom interdit
_FORBIDDEN = {"x", "y", "row", "col", "lon", "lat", "coord", "index", "ocad"}
assert not any(any(f in name.lower() for f in _FORBIDDEN) for name in FEATURE_NAMES), \
    "Descripteur interdit détecté"


# ── Fonctions utilitaires ─────────────────────────────────────────────────

def _safe_div(num: np.ndarray, den: np.ndarray, fill: float = 0.0) -> np.ndarray:
    """num / den avec fill là où den ≤ 0. Toujours float32."""
    return np.where(den > 0.0, num / np.maximum(den, 1e-30), fill).astype(np.float32)


def _smooth(band: np.ndarray, sigma_m: float) -> np.ndarray:
    """Gaussien 2D avec convention omapmaker (truncate=2.0)."""
    sigma_px = sigma_m / RES_M
    return gaussian_filter(band.astype(np.float32), sigma=sigma_px, truncate=TRUNCATE)


# ── Calcul par échelle ────────────────────────────────────────────────────

def compute_scale_block(
    strates: np.ndarray,  # (4, H, W) float32 — g, lo, me, hi
    sigma_m: float,
) -> np.ndarray:
    """Retourne (H, W, 10) float32 pour l'échelle sigma_m."""
    g_s  = _smooth(strates[0], sigma_m)
    lo_s = _smooth(strates[1], sigma_m)
    me_s = _smooth(strates[2], sigma_m)
    hi_s = _smooth(strates[3], sigma_m)

    n_s   = g_s + lo_s + me_s + hi_s
    veg_s = lo_s + me_s + hi_s

    # NDVD poids best_v2
    V_s = W_LOW * lo_s + W_MED * me_s + W_HIGH * hi_s
    ndvd_raw = _safe_div(V_s - g_s, V_s + g_s, fill=0.0)
    ndvd_01  = ((ndvd_raw + 1.0) / 2.0).astype(np.float32)

    feats = np.stack([
        n_s,
        (n_s > MIN_SUPPORT).astype(np.float32),
        _safe_div(g_s,  n_s),
        _safe_div(lo_s, n_s),
        _safe_div(me_s, n_s),
        _safe_div(hi_s, n_s),
        _safe_div(veg_s, n_s),
        ndvd_01,
        _safe_div(hi_s, veg_s),
        _safe_div(me_s, veg_s),
    ], axis=0)  # (10, H, W)

    return np.moveaxis(feats, 0, -1)  # (H, W, 10)


# ── Point d'entrée principal ─────────────────────────────────────────────

def build_descriptors(
    strates: np.ndarray,  # (4, H, W)
) -> tuple[np.ndarray, np.ndarray]:
    """
    Retourne :
      X_grid      : (H, W, N_FEATURES) float32  — features pour chaque pixel
      support_grid: (H, W) bool — True si n_total natif > 0
                    Cellules sans support → prédiction NODATA_CLS

    Toutes les features des cellules avec support natif sont finies (pas de NaN).
    Les proportions valent 0 là où le dénominateur est nul après lissage.
    """
    H, W = strates.shape[1], strates.shape[2]

    # Support natif : au moins 1 retour dans la cellule 2 m × 2 m
    n_native = (strates[0] + strates[1] + strates[2] + strates[3])
    support_grid = n_native > MIN_SUPPORT  # (H, W) bool

    X_grid = np.zeros((H, W, N_FEATURES), dtype=np.float32)
    offset = 0
    for _sname, sigma_m in SCALES:
        block = compute_scale_block(strates, sigma_m)  # (H, W, 10)
        X_grid[:, :, offset:offset + 10] = block
        offset += 10

    return X_grid, support_grid


def load_strates() -> np.ndarray:
    """Charge le raster de strates bois_dupont → (4, H, W) float32."""
    with rasterio.open(STRATES_PATH) as src:
        strates = src.read().astype(np.float32)
    assert strates.shape == (4, 500, 500), f"Strates shape inattendu : {strates.shape}"
    return strates


def save_descriptors() -> None:
    """Calcule et sauvegarde descriptors.npz."""
    strates = load_strates()
    X_grid, support_grid = build_descriptors(strates)

    np.savez_compressed(
        str(DESCRIPTORS_FILE),
        X_grid=X_grid,
        feature_names=np.array(FEATURE_NAMES),
        support_grid=support_grid,
        strates=strates,
    )
    print(f"Descripteurs : {DESCRIPTORS_FILE}")
    print(f"  Shape   : {X_grid.shape}  (H × W × {N_FEATURES} features)")
    print(f"  Support : {support_grid.sum()} / {support_grid.size} px "
          f"({100 * support_grid.mean():.1f} %)")
    print(f"  NaN     : {np.isnan(X_grid).sum()} (doit être 0)")
    print(f"  Features: {FEATURE_NAMES}")


def load_descriptors() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Charge descriptors.npz → (X_grid, support_grid, feature_names)."""
    d = np.load(str(DESCRIPTORS_FILE))
    return d["X_grid"], d["support_grid"].astype(bool), list(d["feature_names"])


if __name__ == "__main__":
    save_descriptors()
