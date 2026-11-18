"""Descripteurs étendus (branche E) depuis les strates fines LAZ.

33 features par pixel = 24 proportions fines + 6 quantiles + 3 ordres retour.

Conventions identiques à descriptors.py (branche T) :
  - résolution 2 m/px
  - gaussien 2D avec TRUNCATE=2.0 (convention omapmaker)
  - _safe_div fill=0.0 sur dénominateur nul
  - support natif : n_total > MIN_SUPPORT

Features par échelle S (3 échelles = 2 m, 6 m, 12 m) :

A. Proportions fines des bins 1-8 (bin 0 = quasi-sol, déjà couvert par T.prop_g) :
   Dénominateur = total tous retours lissé à l'échelle S.
   fe_b1_S .. fe_b8_S  (8 proportions × 3 échelles = 24 features)

B. Quantiles de hauteur approchés des retours non-sol (non-sol = bins 1-8) :
   Méthode : interpolation linéaire dans la distribution cumulée lissée.
   Résultat normalisé par 15 m (borne pratique haute) → [0, 1].
   fe_p50_S, fe_p75_S  (2 quantiles × 3 échelles = 6 features)

C. Ordres de retour (échelle 2 m uniquement, dénominateur = total lissé 2 m) :
   fe_pfirst, fe_plast, fe_punique  (3 features)

Descripteurs interdits (vérification explicite) :
  - coordonnées X/Y absolues ou indices grille
  - toute information issue du raster OCAD
  - informations calculées depuis les étiquettes cibles
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

# ── Constantes (identiques à descriptors.py branche T) ───────────────────
RES_M: float = 2.0
TRUNCATE: float = 2.0
MIN_SUPPORT: float = 1e-9

SCALES: list[tuple[str, float]] = [
    ("2m",  1.0),
    ("6m",  3.0),
    ("12m", 6.0),
]

BIN_EDGES: list[float] = [0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, np.inf]  # 10 bornes → 9 bins
N_BINS: int = 9  # bins 0..8 (bin 8 = 10 m–∞)
# Bornes utilisées pour l'interpolation des quantiles (bin 8 = 10m–15m)
_BIN_LOWER = np.array([0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0], dtype=np.float32)
_BIN_UPPER = np.array([0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 15.0], dtype=np.float32)
_QUANT_NORM: float = 15.0  # valeur de normalisation des quantiles (m)

# Features par échelle : 8 proportions + 2 quantiles = 10
# Features retour : 3 (échelle 2 m uniquement)
N_EXT_PER_SCALE: int = 10
N_EXT_RETURN: int = 3
N_EXT_FEATURES: int = N_EXT_PER_SCALE * len(SCALES) + N_EXT_RETURN  # = 33


# ── Noms des features ─────────────────────────────────────────────────────

def _scale_ext_names(scale_name: str) -> list[str]:
    names = [f"fe_b{k}_{scale_name}" for k in range(1, 9)]   # 8 proportions
    names += [f"fe_p50_{scale_name}", f"fe_p75_{scale_name}"]  # 2 quantiles
    return names


EXT_FEATURE_NAMES: list[str] = []
for _sname, _ in SCALES:
    EXT_FEATURE_NAMES.extend(_scale_ext_names(_sname))
EXT_FEATURE_NAMES += ["fe_pfirst", "fe_plast", "fe_punique"]

assert len(EXT_FEATURE_NAMES) == N_EXT_FEATURES, len(EXT_FEATURE_NAMES)

_FORBIDDEN = {"x", "y", "row", "col", "lon", "lat", "coord", "index", "ocad"}
assert not any(any(f in n.lower() for f in _FORBIDDEN) for n in EXT_FEATURE_NAMES)


# ── Utilitaires ───────────────────────────────────────────────────────────

def _safe_div(num: np.ndarray, den: np.ndarray, fill: float = 0.0) -> np.ndarray:
    return np.where(den > 0.0, num / np.maximum(den, 1e-30), fill).astype(np.float32)


def _smooth(band: np.ndarray, sigma_m: float) -> np.ndarray:
    sigma_px = sigma_m / RES_M
    return gaussian_filter(band.astype(np.float32), sigma=sigma_px, truncate=TRUNCATE)


def _approx_quantile(
    cum_counts: np.ndarray,  # (8, H, W) cumulative from bins 1..8
    total_veg: np.ndarray,   # (H, W) total non-ground
    q: float,
) -> np.ndarray:
    """Quantile q ∈ (0,1) approché par interpolation linéaire dans les bins.

    Paramètre : cum_counts[k] = somme lissée des bins 1..(k+1)
    Résultat : hauteur en mètres, NaN si total_veg == 0.
    Les valeurs absentes (NaN) sont remplacées par 0 dans la feature finale.
    """
    H, W = total_veg.shape
    target = q * total_veg  # (H, W)
    out = np.full((H, W), np.nan, dtype=np.float32)

    for k in range(8):  # bin 1..8
        lo, hi = _BIN_LOWER[k + 1], _BIN_UPPER[k + 1]
        cum_k  = cum_counts[k]           # cumul après bin k+1
        cum_prev = cum_counts[k - 1] if k > 0 else np.zeros_like(cum_k)

        # Pixel pour lequel le quantile tombe dans ce bin
        in_bin = (cum_prev < target) & (target <= cum_k) & np.isnan(out)
        width  = cum_k - cum_prev  # compte dans le bin
        t_frac = np.where(
            width > 0,
            (target - cum_prev) / np.maximum(width, 1e-30),
            0.5,
        )
        out = np.where(in_bin, lo + t_frac * (hi - lo), out)

    return out  # NaN où total_veg == 0


# ── Bloc par échelle ──────────────────────────────────────────────────────

def _scale_block_ext(
    bins: np.ndarray,   # (9, H, W) float32 — comptes bruts, dim 0 = bin 0..8
    sigma_m: float,
) -> np.ndarray:
    """Retourne (H, W, 10) : 8 proportions + 2 quantiles normalisés."""
    # Lisser chaque bin
    s = np.stack([_smooth(bins[k], sigma_m) for k in range(9)], axis=0)  # (9,H,W)

    n_total = s.sum(axis=0)   # (H, W) — tous retours
    n_veg   = s[1:].sum(axis=0)  # (H, W) — non-sol (bins 1-8)

    # A. 8 proportions (bins 1..8 / total)
    props = np.stack(
        [_safe_div(s[k + 1], n_total) for k in range(8)], axis=-1
    )  # (H, W, 8)

    # B. Quantiles approchés sur non-sol
    cum = np.cumsum(s[1:], axis=0)  # (8, H, W) — cumul bins 1..8

    p50_raw = _approx_quantile(cum, n_veg, 0.50)  # (H, W) m
    p75_raw = _approx_quantile(cum, n_veg, 0.75)

    # Normaliser par 15 m et remplacer NaN par 0
    p50 = np.nan_to_num(p50_raw / _QUANT_NORM, nan=0.0).astype(np.float32)
    p75 = np.nan_to_num(p75_raw / _QUANT_NORM, nan=0.0).astype(np.float32)

    quants = np.stack([p50, p75], axis=-1)  # (H, W, 2)

    return np.concatenate([props, quants], axis=-1)  # (H, W, 10)


# ── Point d'entrée principal ──────────────────────────────────────────────

def build_ext_descriptors(
    strates_ext: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Calcule les 33 features E depuis strates_ext.

    strates_ext : dict avec clés 'bins' (9,H,W), 'n_first', 'n_last', 'n_unique'.

    Retourne :
      X_ext       : (H, W, N_EXT_FEATURES) float32
      support_ext : (H, W) bool  — même critère que branche T (n_total native > 0)
    """
    bins    = strates_ext["bins"].astype(np.float32)   # (9, H, W)
    n_first = strates_ext["n_first"].astype(np.float32)
    n_last  = strates_ext["n_last"].astype(np.float32)
    n_uniq  = strates_ext["n_unique"].astype(np.float32)

    H, W = bins.shape[1], bins.shape[2]

    # Support natif (au moins 1 retour brut dans la cellule)
    n_native = bins.sum(axis=0)
    support  = n_native > MIN_SUPPORT  # (H, W)

    X_ext = np.zeros((H, W, N_EXT_FEATURES), dtype=np.float32)

    offset = 0
    for _sname, sigma_m in SCALES:
        block = _scale_block_ext(bins, sigma_m)   # (H, W, 10)
        X_ext[:, :, offset:offset + N_EXT_PER_SCALE] = block
        offset += N_EXT_PER_SCALE

    # C. Ordres de retour (échelle 2 m = sigma_m=1.0)
    s_first = _smooth(n_first, 1.0)
    s_last  = _smooth(n_last,  1.0)
    s_uniq  = _smooth(n_uniq,  1.0)
    n_tot_2m = _smooth(n_native, 1.0)

    X_ext[:, :, offset]     = _safe_div(s_first, n_tot_2m)
    X_ext[:, :, offset + 1] = _safe_div(s_last,  n_tot_2m)
    X_ext[:, :, offset + 2] = _safe_div(s_uniq,  n_tot_2m)

    return X_ext, support


def load_ext_strates(npz_path: pathlib.Path | str) -> dict:  # type: ignore[name-defined]
    """Charge un fichier strates_ext.npz → dict."""
    import pathlib as _pl
    d = np.load(str(_pl.Path(npz_path)))
    return {k: d[k] for k in d.files}


# ── Vérification des noms de features ────────────────────────────────────

if __name__ == "__main__":
    print(f"N_EXT_FEATURES = {N_EXT_FEATURES}")
    for i, name in enumerate(EXT_FEATURE_NAMES):
        print(f"  [{i:2d}] {name}")
