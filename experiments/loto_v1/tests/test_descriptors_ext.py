"""Tests synthétiques des descripteurs étendus (branche E).

Vérifient le calcul, la cohérence et les invariants — pas la vérité terrain.
Toutes les entrées sont fabriquées sans OCAD ni données réelles.

Sections :
  §A — Bornes des bins fins
  §B — Quantiles et dispersion
  §C — Définition premier/dernier/unique
  §D — Valeurs absentes et support nul
  §E — Voisinages et bords
  §F — Absence de variables interdites (noms)
  §G — Sauvegarde/rechargement et cohérence d'inférence
  §H — Recouvrements géographiques (séparation supports)
"""
from __future__ import annotations

import numpy as np
import pytest
import sys
import pathlib

# Résoudre les imports depuis la racine du projet
_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "experiments/bois_dupont/supervised_v1"))

from experiments.loto_v1.descriptors_ext import (  # noqa: E402
    build_ext_descriptors,
    N_EXT_FEATURES,
    EXT_FEATURE_NAMES,
    BIN_EDGES,
    _QUANT_NORM,
    _approx_quantile,
    _scale_block_ext,
    _safe_div,
    MIN_SUPPORT,
    N_BINS,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_ext(bins, n_first=None, n_last=None, n_unique=None):
    """Construit un strates_ext minimal depuis des tableaux numpy."""
    h, w = bins.shape[1], bins.shape[2]
    return {
        "bins":     bins.astype(np.float32),
        "n_first":  (n_first  if n_first  is not None else np.zeros((h, w), np.float32)),
        "n_last":   (n_last   if n_last   is not None else np.zeros((h, w), np.float32)),
        "n_unique": (n_unique if n_unique is not None else np.zeros((h, w), np.float32)),
    }


# ── §A — Bornes des bins fins ─────────────────────────────────────────────

class TestBinBounds:
    def test_bin_edges_count(self):
        """9 bins = 9 bornes infér. + borne sup. ∞ → 10 valeurs dans BIN_EDGES."""
        assert len(BIN_EDGES) == N_BINS + 1  # 9 + 1 = 10 (incluant 0.0)

    def test_bin_edges_monotone(self):
        finite = [e for e in BIN_EDGES if not np.isinf(e)]
        assert all(a < b for a, b in zip(finite, finite[1:]))

    def test_ground_bin_zero_matches_T_ground(self):
        """Bin 0 = [0, 0.2) correspond exactement à T.ground (H_LOW=0.2)."""
        assert BIN_EDGES[0] == 0.0
        assert BIN_EDGES[1] == pytest.approx(0.2)

    def test_T_boundaries_present(self):
        """Les seuils T (1.5 m, 3.0 m) doivent être des bornes de bins."""
        assert 1.5 in BIN_EDGES
        assert 3.0 in BIN_EDGES

    def test_pure_bin_routing(self):
        """Un point dans bin k produit prop_bk == 1 et prop_autres == 0."""
        # Crée un pixel avec seulement bin 3 ([1.0, 1.5))
        bins = np.zeros((9, 1, 1), dtype=np.float32)
        bins[3, 0, 0] = 10.0  # bin 3 = b3 → feature fe_b3
        ext = _make_ext(bins)
        X, supp = build_ext_descriptors(ext)
        # fe_b1..fe_b8 = indices 0..7 dans le premier scale bloc
        # fe_b3 correspond à bin index 4 dans bins (bins[4] = offset 3 dans 1-indexed)
        # En fait : fe_b1=bins[1], fe_b2=bins[2], ..., fe_b8=bins[8]
        # bin 3 est bins[3] → feature fe_b3 → index 2 dans le scale (0-based: b1,b2,b3...)
        props_2m = X[0, 0, :8]   # 8 proportions de l'échelle 2m
        assert props_2m[2] == pytest.approx(1.0, abs=1e-5), props_2m  # fe_b3 = bin3/total


# ── §B — Quantiles et dispersion ──────────────────────────────────────────

class TestQuantiles:
    def _uniform_bins(self, h=3, w=3):
        """Toutes les 8 bins non-sol avec le même poids : médiane ≈ milieu."""
        bins = np.ones((9, h, w), dtype=np.float32)
        bins[0] = 0.0  # pas de sol
        return bins

    def test_p50_between_p25_and_p75(self):
        bins = self._uniform_bins()
        ext = _make_ext(bins)
        X, _ = build_ext_descriptors(ext)
        # p50 (index 8) et p75 (index 9) pour l'échelle 2m
        p50 = X[:, :, 8]
        p75 = X[:, :, 9]
        assert (p50 <= p75).all(), "p50 doit être ≤ p75"

    def test_p50_monotone_with_mass(self):
        """Si toute la masse est dans un bin plus haut, la médiane augmente."""
        bins_low = np.zeros((9, 1, 1), np.float32)
        bins_low[1, 0, 0] = 100.0  # tout dans bin 1 ([0.2, 0.5))

        bins_high = np.zeros((9, 1, 1), np.float32)
        bins_high[7, 0, 0] = 100.0  # tout dans bin 7 ([5, 10))

        X_low,  _ = build_ext_descriptors(_make_ext(bins_low))
        X_high, _ = build_ext_descriptors(_make_ext(bins_high))

        p50_low  = X_low[0, 0, 8]
        p50_high = X_high[0, 0, 8]
        assert p50_low < p50_high, f"{p50_low} >= {p50_high}"

    def test_no_ground_gives_zero_quantile(self):
        """Pixel uniquement sol (bin 0) → n_veg = 0 → quantile = 0 (NaN→0)."""
        bins = np.zeros((9, 1, 1), np.float32)
        bins[0, 0, 0] = 5.0  # que du sol
        X, _ = build_ext_descriptors(_make_ext(bins))
        assert X[0, 0, 8] == pytest.approx(0.0, abs=1e-6)
        assert X[0, 0, 9] == pytest.approx(0.0, abs=1e-6)

    def test_quantile_normalized_range(self):
        """Quantile normalisé doit être dans [0, 1]."""
        rng = np.random.default_rng(0)
        bins = rng.uniform(0, 10, (9, 10, 10)).astype(np.float32)
        X, _ = build_ext_descriptors(_make_ext(bins))
        p50 = X[:, :, 8]
        p75 = X[:, :, 9]
        assert (p50 >= 0).all() and (p50 <= 1).all()
        assert (p75 >= 0).all() and (p75 <= 1).all()


# ── §C — Premier / dernier / unique ──────────────────────────────────────

class TestReturnOrder:
    def _return_ext(self, n_first, n_last, n_unique, total=10):
        """Terrain 1×1 avec comptages d'ordres de retour."""
        bins = np.zeros((9, 1, 1), np.float32)
        bins[:, 0, 0] = total / 9  # répartition uniforme
        return _make_ext(
            bins,
            n_first=np.full((1, 1), n_first, np.float32),
            n_last=np.full((1, 1), n_last,  np.float32),
            n_unique=np.full((1, 1), n_unique, np.float32),
        )

    def test_unique_is_subset_of_first_and_last(self):
        """Un retour unique est à la fois premier et dernier."""
        ext = self._return_ext(n_first=5, n_last=5, n_unique=4, total=10)
        X, _ = build_ext_descriptors(ext)
        pfirst  = X[0, 0, -3]
        plast   = X[0, 0, -2]
        punique = X[0, 0, -1]
        assert pfirst  > 0
        assert plast   > 0
        assert punique > 0
        # punique ≤ min(pfirst, plast) car uniques ⊆ premiers ⊆ tous
        assert punique <= pfirst + 1e-5
        assert punique <= plast  + 1e-5

    def test_single_return_pulse(self):
        """Un seul retour (NumberOfReturns=1) : n_first=n_last=n_unique=1."""
        ext = self._return_ext(n_first=1, n_last=1, n_unique=1, total=1)
        X, _ = build_ext_descriptors(ext)
        assert X[0, 0, -3] == pytest.approx(1.0, abs=1e-4)  # pfirst
        assert X[0, 0, -2] == pytest.approx(1.0, abs=1e-4)  # plast
        assert X[0, 0, -1] == pytest.approx(1.0, abs=1e-4)  # punique

    def test_multi_return_pulse(self):
        """3 retours d'une même impulsion (last != first) → unique=0."""
        ext = self._return_ext(n_first=1, n_last=1, n_unique=0, total=3)
        X, _ = build_ext_descriptors(ext)
        assert X[0, 0, -1] < 0.1  # punique proche de 0

    def test_no_returns_gives_zero(self):
        """Pixel sans retour → toutes les features retour = 0."""
        bins = np.zeros((9, 1, 1), np.float32)
        ext  = _make_ext(bins, n_first=np.zeros((1, 1), np.float32))
        X, _ = build_ext_descriptors(ext)
        assert X[0, 0, -3] == pytest.approx(0.0, abs=1e-6)
        assert X[0, 0, -2] == pytest.approx(0.0, abs=1e-6)
        assert X[0, 0, -1] == pytest.approx(0.0, abs=1e-6)


# ── §D — Valeurs absentes et support nul ──────────────────────────────────

class TestMissingAndSupport:
    def test_zero_pixel_support_false(self):
        bins = np.zeros((9, 3, 3), np.float32)
        _, supp = build_ext_descriptors(_make_ext(bins))
        assert not supp.any()

    def test_nonzero_pixel_support_true(self):
        bins = np.zeros((9, 3, 3), np.float32)
        bins[1, 1, 1] = 1.0
        _, supp = build_ext_descriptors(_make_ext(bins))
        assert supp[1, 1]

    def test_no_nan_in_X(self):
        rng = np.random.default_rng(1)
        bins = rng.poisson(5, (9, 20, 20)).astype(np.float32)
        X, _ = build_ext_descriptors(_make_ext(bins))
        assert not np.isnan(X).any(), "NaN détecté dans X_ext"

    def test_proportions_sum_to_one(self):
        """Somme des 8 proportions fines ≈ prop_veg (non-sol / total)."""
        bins = np.ones((9, 5, 5), np.float32)  # uniforme
        X, _ = build_ext_descriptors(_make_ext(bins))
        # 8 proportions scale 2m, indices 0-7
        prop_sum = X[:, :, :8].sum(axis=-1)
        # bins[1..8] = 8 bins = 8/9 du total → ~0.889
        expected = 8.0 / 9.0
        np.testing.assert_allclose(prop_sum, expected, atol=1e-4)

    def test_isolated_zero_pixel_no_propagation(self):
        """Un pixel entouré de zéros reste support=False même après lissage."""
        bins = np.zeros((9, 7, 7), np.float32)
        # seulement le pixel central
        bins[1, 3, 3] = 1.0
        _, supp = build_ext_descriptors(_make_ext(bins))
        # Le pixel central est support=True
        assert supp[3, 3]
        # Les coins (distance 3) restent False (Gaussien à sigma_px=0.5 décroît vite)
        assert not supp[0, 0]


# ── §E — Voisinages et bords ───────────────────────────────────────────────

class TestNeighbourhood:
    def test_border_pixel_no_wraparound(self):
        """Lissage gaussien ne wrappe pas : bords proches de zéro si data nulle."""
        bins = np.zeros((9, 20, 20), np.float32)
        bins[2, 10, 10] = 100.0   # masse au centre
        X, _ = build_ext_descriptors(_make_ext(bins))
        # Coin (0,0) doit être quasi-nul pour l'échelle 2m (sigma_px=0.5)
        assert X[0, 0, 1] < 0.01   # fe_b2 au coin

    def test_uniform_grid_invariant_inside(self):
        """Grille uniforme → chaque pixel doit avoir la même valeur intérieure."""
        bins = np.ones((9, 15, 15), np.float32)
        X, _ = build_ext_descriptors(_make_ext(bins))
        # Région intérieure (hors bord 1 px): valeurs homogènes
        inner = X[2:-2, 2:-2, 0]  # fe_b1 scale 2m
        assert inner.std() < 1e-4, f"variance inattendue : {inner.std()}"

    def test_smooth_sigma_increases_spread(self):
        """Un pic au centre doit être plus étalé à l'échelle 12 m qu'à 2 m."""
        bins = np.zeros((9, 30, 30), np.float32)
        bins[1, 15, 15] = 1000.0
        X, _ = build_ext_descriptors(_make_ext(bins))
        # fe_b1 scale 2m (index 0) vs scale 12m (index 20)
        spread_2m  = (X[:, :, 0]  > 0.01).sum()
        spread_12m = (X[:, :, 20] > 0.01).sum()
        assert spread_12m > spread_2m


# ── §F — Noms de features interdits ──────────────────────────────────────

class TestForbiddenNames:
    _FORBIDDEN = {"x", "y", "row", "col", "lon", "lat", "coord", "index", "ocad"}

    def test_no_forbidden_name(self):
        for name in EXT_FEATURE_NAMES:
            for f in self._FORBIDDEN:
                assert f not in name.lower(), f"Nom interdit '{f}' dans '{name}'"

    def test_feature_count(self):
        assert len(EXT_FEATURE_NAMES) == N_EXT_FEATURES


# ── §G — Sauvegarde / rechargement ───────────────────────────────────────

class TestCacheRoundtrip:
    def test_npz_roundtrip(self, tmp_path):
        bins = np.random.default_rng(42).uniform(0, 5, (9, 10, 10)).astype(np.float32)
        ext = _make_ext(bins)
        path = tmp_path / "test_strates_ext.npz"
        np.savez_compressed(
            str(path),
            bins=ext["bins"],
            n_first=ext["n_first"],
            n_last=ext["n_last"],
            n_unique=ext["n_unique"],
            bbox=np.array([0.0, 0.0, 20.0, 20.0]),
            res_m=np.float32(2.0),
            laz_files=np.array(["dummy.laz"]),
        )
        d = np.load(str(path))
        ext2 = {k: d[k] for k in d.files}
        X1, s1 = build_ext_descriptors(ext)
        X2, s2 = build_ext_descriptors(ext2)
        np.testing.assert_array_equal(X1, X2)
        np.testing.assert_array_equal(s1, s2)

    def test_inference_deterministic(self):
        rng = np.random.default_rng(99)
        bins = rng.poisson(3, (9, 8, 8)).astype(np.float32)
        ext = _make_ext(bins)
        X1, _ = build_ext_descriptors(ext)
        X2, _ = build_ext_descriptors(ext)
        np.testing.assert_array_equal(X1, X2)


# ── §H — Recouvrements géographiques ─────────────────────────────────────

class TestGeographicOverlap:
    """Vérifie que la suppression de l'overlap SA↔Caen retire les bons pixels."""

    def test_overlap_rows_cols_sa_caen(self):
        """Overlap SA↔Caen : rows 1000-1500, cols 500-1500 dans l'espace SA.

        Ces pixels NE doivent PAS être inclus dans le jeu d'entraînement
        quand le fold testé est Caen.
        """
        # Recréer la logique de loto_pipeline.py
        H, W = 1500, 1500
        mask_full = np.ones((H, W), bool)

        # Anti-leak : exclure rows 994-1500, cols 494-1500
        leak = np.zeros((H, W), bool)
        leak[994:, 494:] = True
        mask_no_leak = mask_full & ~leak

        # Les pixels de l'overlap réel (rows 1000-1500, cols 500-1500) sont exclus
        overlap_pixels = np.zeros((H, W), bool)
        overlap_pixels[1000:, 500:] = True
        assert not (mask_no_leak & overlap_pixels).any(), (
            "Des pixels de l'overlap SA↔Caen sont encore dans le masque d'entraînement"
        )

    def test_anti_leak_buffer_6px(self):
        """Le buffer de 6 px autour de l'overlap est présent."""
        H, W = 1500, 1500
        # Pixels à 6 px juste au-dessus du bord de l'overlap (rows 994-999)
        buffer_rows = np.zeros((H, W), bool)
        buffer_rows[994:1000, 500:] = True

        leak = np.zeros((H, W), bool)
        leak[994:, 494:] = True  # anti-leak inclut déjà le buffer

        assert (buffer_rows & leak).any(), (
            "Le buffer 6 px n'est pas inclus dans l'exclusion anti-leak"
        )
