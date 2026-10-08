"""Tests des briques raster de scripts/diag/sweep_ordre_lissage.py (protocole L1).

La vectorisation (stage_polygonize) exige GDAL/osgeo : elle n'est pas testee ici,
seulement les fonctions raster pures (variantes d'ordre, seuillage, metriques).
"""
import importlib.util
import pathlib

import numpy as np
import pytest

pytest.importorskip("rasterio")

_MOD_PATH = (pathlib.Path(__file__).resolve().parents[1]
             / "scripts" / "diag" / "sweep_ordre_lissage.py")
_spec = importlib.util.spec_from_file_location("sweep_ordre", _MOD_PATH)
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)


def _blob(shape=(64, 64), centre=None, rayon=8.0, valeur=1.0) -> np.ndarray:
    """Disque de valeur constante sur fond nul — champ test reproductible."""
    h, w = shape
    cy, cx = centre or (h / 2, w / 2)
    yy, xx = np.mgrid[0:h, 0:w]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= rayon ** 2
    return np.where(mask, valeur, 0.0).astype(np.float64)


# ── build_variants ───────────────────────────────────────────────────────────

class TestVariants:
    def test_all_five_variants_present(self):
        ratio = np.random.default_rng(0).random((64, 64))
        mask = np.zeros_like(ratio, dtype=bool)
        out = sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)
        assert set(out) == {
            "V0_gauss_med", "V1_med_gauss", "V2_med_med",
            "V3_gauss_med_med", "V4_norm_before",
        }

    def test_normalised_between_0_and_1(self):
        ratio = _blob(valeur=4.0)      # volontairement hors [0, 1]
        mask = np.zeros_like(ratio, dtype=bool)
        for name, field in sw.build_variants(ratio, mask, 1.0, 1.0, 9.0).items():
            assert field.min() >= 0.0, name
            assert field.max() <= 1.0 + 1e-9, name

    def test_masked_cells_forced_to_zero(self):
        ratio = _blob()
        mask = np.zeros_like(ratio, dtype=bool)
        mask[:8, :] = True
        out = sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)
        for name, field in out.items():
            assert np.all(field[mask] == 0.0), name

    def test_order_matters(self):
        """L'ordre gauss/mediane doit changer le resultat (operations non lineaires)."""
        rng = np.random.default_rng(1)
        ratio = _blob() + 0.15 * rng.random((64, 64))   # bruit moucheté
        mask = np.zeros_like(ratio, dtype=bool)
        out = sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)
        assert not np.allclose(out["V0_gauss_med"], out["V1_med_gauss"], atol=1e-6)

    def test_cascade_differs_from_single_big_median(self):
        rng = np.random.default_rng(2)
        ratio = _blob(valeur=0.8) + 0.2 * rng.random((64, 64))
        mask = np.zeros_like(ratio, dtype=bool)
        out = sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)
        assert not np.allclose(out["V2_med_med"], out["V0_gauss_med"], atol=1e-6)

    def test_norm_before_differs_from_norm_after(self):
        ratio = _blob(valeur=3.0)
        mask = np.zeros_like(ratio, dtype=bool)
        out = sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)
        assert not np.allclose(out["V4_norm_before"], out["V0_gauss_med"], atol=1e-6)

    def test_resolution_scales_windows(self):
        """A 2 m, sigma=1 m => sigma_px=0.5 : lissage plus court qu'a 1 m."""
        ratio = _blob(rayon=12.0)
        mask = np.zeros_like(ratio, dtype=bool)
        f1 = sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)["V0_gauss_med"]
        f2 = sw.build_variants(ratio, mask, 2.0, 1.0, 9.0)["V0_gauss_med"]
        # Un lissage plus court conserve un bord plus raide : gradient max plus fort
        g1 = np.abs(np.gradient(f1)[0]).max()
        g2 = np.abs(np.gradient(f2)[0]).max()
        assert g2 >= g1


# ── classify ─────────────────────────────────────────────────────────────────

class TestClassify:
    def test_thresholds_map_to_85_170_255(self):
        field = np.array([[0.10, 0.30, 0.60, 0.95]])
        out = sw.classify(field, np.zeros_like(field, dtype=bool), (0.20, 0.45, 0.85))
        assert list(out[0]) == [0, 85, 170, 255]

    def test_mask_wins_over_threshold(self):
        field = np.array([[0.95, 0.95]])
        mask = np.array([[True, False]])
        out = sw.classify(field, mask, (0.20, 0.45, 0.85))
        assert list(out[0]) == [0, 255]


# ── metriques ────────────────────────────────────────────────────────────────

class TestRasterMetrics:
    def test_empty_class(self):
        cls = np.zeros((10, 10), dtype=np.uint8)
        m = sw.raster_metrics(cls, 406, 1.0)
        assert m == {"pct": 0.0, "ha": 0.0, "max_comp_pct": 0.0}

    def test_single_component_is_100_pct(self):
        cls = np.zeros((10, 10), dtype=np.uint8)
        cls[2:5, 2:5] = 85
        m = sw.raster_metrics(cls, 406, 1.0)
        assert m["max_comp_pct"] == pytest.approx(100.0)
        assert m["ha"] == pytest.approx(9 / 10_000)

    def test_two_components_split(self):
        cls = np.zeros((10, 10), dtype=np.uint8)
        cls[0:1, 0:1] = 85       # 1 px
        cls[5:9, 5:9] = 85       # 16 px (8-connexe)
        m = sw.raster_metrics(cls, 406, 1.0)
        assert m["max_comp_pct"] == pytest.approx(100.0 * 16 / 17)

    def test_pct_is_share_of_classified_pixels(self):
        cls = np.zeros((4, 4), dtype=np.uint8)
        cls[0, :] = 85
        cls[1, :] = 170
        m406 = sw.raster_metrics(cls, 406, 1.0)
        m408 = sw.raster_metrics(cls, 408, 1.0)
        assert m406["pct"] == pytest.approx(50.0)
        assert m408["pct"] == pytest.approx(50.0)


# ── Ordres « seuiller puis filtrer » (V5 KP, V6 Trier) ───────────────────────

class TestThresholdThenFilter:
    def _ratio(self):
        """Champ synthetique : deux masses nettes + moucheture isolee."""
        return _blob(shape=(64, 64), centre=(20, 20), rayon=10, valeur=0.95) + \
               _blob(shape=(64, 64), centre=(45, 45), rayon=6, valeur=0.5)

    def test_values_stay_in_class_set(self):
        ratio = self._ratio()
        mask = np.zeros_like(ratio, dtype=bool)
        cls = sw.classify_threshold_then_filter(ratio, mask, (0.20, 0.45, 0.85), 1.0)
        assert set(np.unique(cls)) <= {0, 85, 170, 255}

    def test_masked_cells_stay_zero(self):
        ratio = self._ratio()
        mask = np.zeros_like(ratio, dtype=bool)
        mask[:, :8] = True
        cls = sw.classify_threshold_then_filter(ratio, mask, (0.20, 0.45, 0.85), 1.0)
        assert (cls[mask] == 0).all()

    def test_order_differs_from_production(self):
        rng = np.random.default_rng(7)
        ratio = self._ratio() * (1 + 0.3 * rng.random((64, 64)))
        mask = np.zeros_like(ratio, dtype=bool)
        prod = sw.classify(sw.build_variants(ratio, mask, 1.0, 1.0, 9.0)["V0_gauss_med"],
                           mask, (0.20, 0.45, 0.85))
        kp = sw.classify_threshold_then_filter(ratio, mask, (0.20, 0.45, 0.85), 1.0)
        assert not np.array_equal(prod, kp)


class TestTrierCascade:
    def test_disk_shape(self):
        d = sw._disk(2)
        assert d.shape == (5, 5)
        assert d[2, 2] and d[0, 2]      # centre et bord cardinal
        assert not d[0, 0]              # coin exclu

    def test_small_blob_removed_big_blob_survives(self):
        binary = np.zeros((60, 60), dtype=bool)
        binary[5:7, 5:7] = True          # 2x2 px : plus fin que le plus petit noyau
        binary[30:50, 30:50] = True      # 20x20 px : masse franche
        out = sw._apply_cascade(binary, 1.0)
        assert not out[5:7, 5:7].any()
        assert out[35:45, 35:45].mean() > 0.9

    def test_cascade_never_invents_far_away_pixels(self):
        binary = np.zeros((80, 80), dtype=bool)
        binary[38:42, 38:42] = True
        out = sw._apply_cascade(binary, 1.0)
        assert out[:10, :10].sum() == 0

    def test_class_map_is_exclusive(self):
        """Une carte de classes : chaque pixel porte une classe et une seule."""
        ratio = _blob(shape=(80, 80), rayon=30, valeur=0.99)
        mask = np.zeros_like(ratio, dtype=bool)
        cls = sw.classify_threshold_then_morphology(ratio, mask, (0.20, 0.45, 0.85), 1.0)
        assert set(np.unique(cls)) <= {0, 85, 170, 255}

    def test_morphology_does_not_amplify_beyond_kernel(self):
        """La fermeture peut grossir, mais pas au-dela du plus grand noyau (11 px)."""
        from scipy.ndimage import binary_dilation
        ratio = _blob(shape=(120, 120), centre=(60, 60), rayon=25, valeur=0.99)
        mask = np.zeros_like(ratio, dtype=bool)
        cls = sw.classify_threshold_then_morphology(ratio, mask, (0.20, 0.45, 0.85), 1.0)

        # Masque brut de la classe la plus severe, avant morphologie
        valid = ratio[~mask]
        normed = np.clip(ratio / np.percentile(valid, 95), 0.0, 1.0)
        raw410 = sw.classify(normed, mask, (0.20, 0.45, 0.85)) == 255
        bound = binary_dilation(raw410, structure=sw._disk(7))
        assert ((cls == 255) & ~bound).sum() == 0

    def test_custom_cascade_is_used(self):
        binary = np.zeros((40, 40), dtype=bool)
        binary[19:21, 19:21] = True      # disparait avec un noyau de 7
        out = sw._apply_cascade(binary, 1.0, cascade=(("opening", 7),))
        assert out.sum() == 0
