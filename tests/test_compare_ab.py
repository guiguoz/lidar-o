"""Tests unitaires pour compare_ab_voisinage.py.

Couvre :
- compute_signal_a : cellule pure vég, cellule pure sol, invariance à l'échelle
- compute_signal_b : cellule pure vég, cellule pure sol, cellule vide avec voisins valides,
                    pas de contamination par sentinelle, différence A≠B avec densités inégales
- Vérification numérique A,sigma=1 == témoin best_v2 (sur tableau synthétique)
"""
from __future__ import annotations

import sys
import pathlib

import numpy as np
import pytest

_CALIB = pathlib.Path(__file__).resolve().parents[1] / "experiments" / "bois_dupont" / "calibration_v2"
sys.path.insert(0, str(_CALIB))

from compare_ab_voisinage import (
    compute_signal_a,
    compute_signal_b,
    MIN_SUPPORT_B,
    TRUNCATE,
)
from run_calibration_v2 import NODATA_CLS, compute_ndvd, apply_gaussian


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _uniform_strates(h: int, w: int, g: float, low: float, med: float, high: float) -> np.ndarray:
    arr = np.zeros((4, h, w), dtype=np.float32)
    arr[0] = g
    arr[1] = low
    arr[2] = med
    arr[3] = high
    return arr


# ─────────────────────────────────────────────────────────────────────────────
# compute_signal_a
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSignalA:
    def test_pure_veg_uniform_gives_one(self):
        # Toute la grille = végétation haute → signal ≈ 1.0 aux pixels centraux
        s = _uniform_strates(30, 30, g=0.0, low=0.0, med=0.0, high=10.0)
        sig = compute_signal_a(s, sigma_m=1.0)
        inner = sig[10:-10, 10:-10]
        assert inner == pytest.approx(1.0, abs=1e-4)

    def test_pure_sol_uniform_gives_zero(self):
        # Toute la grille = sol → signal ≈ 0.0 aux pixels centraux
        s = _uniform_strates(30, 30, g=10.0, low=0.0, med=0.0, high=0.0)
        sig = compute_signal_a(s, sigma_m=1.0)
        inner = sig[10:-10, 10:-10]
        assert inner == pytest.approx(0.0, abs=1e-4)

    def test_scale_invariance(self):
        # Doubler tous les comptages ne change pas le signal (NDVD normalisé)
        s1 = _uniform_strates(20, 20, g=2.0, low=3.0, med=1.0, high=0.5)
        s2 = s1 * 2.0
        sig1 = compute_signal_a(s1, sigma_m=1.0)
        sig2 = compute_signal_a(s2, sigma_m=1.0)
        np.testing.assert_allclose(sig1, sig2, atol=1e-5)

    def test_empty_grid_gives_nodata(self):
        # Grille entièrement vide (g=V=0) → signal = -9999 → classify → NODATA_CLS
        from run_calibration_v2 import classify_ndvd
        s = np.zeros((4, 10, 10), dtype=np.float32)
        sig = compute_signal_a(s, sigma_m=1.0)
        cls = classify_ndvd(sig, t406=0.38, t408=0.60, t410=0.75)
        assert (cls == NODATA_CLS).all()


# ─────────────────────────────────────────────────────────────────────────────
# compute_signal_b
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSignalB:
    def test_pure_veg_uniform_gives_one(self):
        s = _uniform_strates(30, 30, g=0.0, low=0.0, med=0.0, high=10.0)
        sig = compute_signal_b(s, sigma_m=1.0)
        inner = sig[10:-10, 10:-10]
        assert inner == pytest.approx(1.0, abs=1e-4)

    def test_pure_sol_uniform_gives_zero(self):
        s = _uniform_strates(30, 30, g=10.0, low=0.0, med=0.0, high=0.0)
        sig = compute_signal_b(s, sigma_m=1.0)
        inner = sig[10:-10, 10:-10]
        assert inner == pytest.approx(0.0, abs=1e-4)

    def test_empty_cell_evaluable_with_valid_neighbors(self):
        # Cellule centrale vide, entourée de voisins valides → signal != -9999
        h, w = 15, 15
        s = _uniform_strates(h, w, g=5.0, low=0.0, med=0.0, high=0.0)
        s[:, 7, 7] = 0.0   # cellule centrale complètement vide
        sig = compute_signal_b(s, sigma_m=2.0)
        # La cellule centrale doit avoir un support > MIN_SUPPORT_B grâce aux voisins
        assert sig[7, 7] != pytest.approx(-9999.0, abs=0.1)

    def test_no_sentinel_contamination(self):
        # Un îlot vide au centre ne doit pas "diffuser" des sentinelles -9999
        # dans les pixels voisins valides.
        h, w = 20, 20
        s = _uniform_strates(h, w, g=5.0, low=2.0, med=1.0, high=0.5)
        # Trouer un seul pixel
        s[:, 10, 10] = 0.0
        sig = compute_signal_b(s, sigma_m=1.0)
        # Les voisins immédiats ne doivent pas être -9999
        for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            assert sig[10 + di, 10 + dj] != pytest.approx(-9999.0, abs=0.1), \
                f"voisin ({10+di},{10+dj}) contaminé par -9999"

    def test_isolated_empty_grid_gives_nodata(self):
        # Grille entièrement vide → support = 0 partout → -9999
        s = np.zeros((4, 10, 10), dtype=np.float32)
        sig = compute_signal_b(s, sigma_m=1.0)
        assert (sig == np.float32(-9999.0)).all()

    def test_a_b_differ_with_unequal_density(self):
        # Grille avec densité variable : A et B doivent diverger aux frontières.
        # Si la densité est uniforme partout, A == B analytiquement.
        # On crée un gradient net : moitié gauche riche, moitié droite vide.
        h, w = 30, 30
        s = np.zeros((4, h, w), dtype=np.float32)
        s[3, :, :w//2] = 20.0   # vég haute à gauche
        s[0, :, w//2:] = 20.0   # sol à droite
        sig_a = compute_signal_a(s, sigma_m=2.0)
        sig_b = compute_signal_b(s, sigma_m=2.0)
        # À la frontière, les deux méthodes ne donnent pas le même signal
        diff = np.abs(sig_a[5:-5, w//2-2:w//2+2] - sig_b[5:-5, w//2-2:w//2+2])
        assert diff.max() > 0.01, "A et B sont identiques même avec densité hétérogène"


# ─────────────────────────────────────────────────────────────────────────────
# Cohérence A, sigma=1 avec le pipeline omapmaker (apply_gaussian + compute_ndvd)
# ─────────────────────────────────────────────────────────────────────────────

class TestAMatchesOmapmaker:
    """compute_signal_a(s, 1.0) doit être identique à apply_gaussian + compute_ndvd."""

    def test_a_sigma1_matches_apply_gaussian_compute_ndvd(self):
        rng = np.random.default_rng(42)
        s = rng.poisson(5, (4, 50, 50)).astype(np.float32)
        w_low, w_med, w_high = 0.35, 0.55, 0.10

        # Voie A via compare_ab
        sig_a = compute_signal_a(s, sigma_m=1.0, w_low=w_low, w_med=w_med, w_high=w_high)

        # Voie "témoin" via run_calibration_v2
        smooth = apply_gaussian(s, sigma_m=1.0)
        sig_ref = compute_ndvd(smooth, w_low=w_low, w_med=w_med, w_high=w_high)

        # Les deux routes doivent être bit-for-bit identiques
        np.testing.assert_array_equal(sig_a, sig_ref)
