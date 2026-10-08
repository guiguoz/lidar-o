"""Tests des briques pures de scripts/diag/diag_multilook.py (protocole L2).

Ne teste que les fonctions sans PDAL : construction du pipeline, fusion des
looks, contraste de bande. La partie PDAL est verifiee par --dry-run en prod.
"""
import importlib.util
import pathlib

import numpy as np
import pytest

pytest.importorskip("scipy")   # classify_like_process_hag importe scipy en interne

_MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "diag" / "diag_multilook.py"
_spec = importlib.util.spec_from_file_location("diag_multilook", _MOD_PATH)
ml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ml)


# ── build_multilook_pipeline ─────────────────────────────────────────────────

class TestPipeline:
    def test_stage_order(self):
        p = ml.build_multilook_pipeline(
            ["a.copc.laz"], "look_#.tif", 1.0, 0.3, 3.0
        )["pipeline"]
        types = [s.get("type") for s in p if isinstance(s, dict)]
        assert types == [
            "readers.copc", "filters.merge", "filters.hag_nn",
            "filters.assign", "filters.assign", "filters.sort",
            "filters.groupby", "writers.gdal",
        ]

    def test_groupby_on_point_source_id(self):
        p = ml.build_multilook_pipeline(["a.copc.laz"], "look_#.tif", 1.0, 0.3, 3.0)["pipeline"]
        groupby = next(s for s in p if isinstance(s, dict) and s["type"] == "filters.groupby")
        assert groupby["dimension"] == "PointSourceId"

    def test_flag_uses_the_band_bounds(self):
        p = ml.build_multilook_pipeline(["a.copc.laz"], "look_#.tif", 1.0, 0.5, 2.5)["pipeline"]
        assigns = [s for s in p if isinstance(s, dict) and s["type"] == "filters.assign"]
        assert assigns[0]["value"] == ["BandFlag = 0"]
        # Bornes fermees des deux cotes, comme filters.range [min:max]
        assert assigns[1]["value"] == [
            "BandFlag = 1 WHERE HeightAboveGround >= 0.5 && HeightAboveGround <= 2.5"
        ]

    def test_writer_matches_production_settings(self):
        w = ml.build_multilook_pipeline(["a.copc.laz"], "look_#.tif", 1.0, 0.3, 3.0)["pipeline"][-1]
        assert w["output_type"] == ["mean", "count"]
        assert w["binmode"] is False          # reglages du writer de production
        assert w["dimension"] == "BandFlag"

    def test_binmode_opt_in(self):
        w = ml.build_multilook_pipeline(
            ["a.copc.laz"], "look_#.tif", 1.0, 0.3, 3.0, binmode=True
        )["pipeline"][-1]
        assert w["binmode"] is True

    def test_placeholder_required(self):
        with pytest.raises(ValueError):
            ml.build_multilook_pipeline(["a.copc.laz"], "look.tif", 1.0, 0.3, 3.0)

    def test_bounds_option(self):
        p = ml.build_multilook_pipeline(
            ["a.copc.laz"], "look_#.tif", 1.0, 0.3, 3.0, bounds="([0, 10], [0, 10])"
        )["pipeline"]
        assert p[-1]["bounds"] == "([0, 10], [0, 10])"


# ── fuse_looks ───────────────────────────────────────────────────────────────

def _three_looks(f0, c0, f1, c1, f2, c2):
    """Construit trois looks d'une cellule unique (shape 3x1x1)."""
    fr = np.array([[[f0]], [[f1]], [[f2]]], dtype=float)
    ct = np.array([[[c0]], [[c1]], [[c2]]], dtype=float)
    return fr, ct


class TestFuseLooks:
    def test_pooled_is_count_weighted_mean(self):
        fr, ct = _three_looks(0.10, 100, 0.30, 20, 0.50, 5)
        out = ml.fuse_looks(fr, ct, n_min=1)
        expected = (0.10 * 100 + 0.30 * 20 + 0.50 * 5) / 125
        assert out["pooled"][0, 0] == pytest.approx(expected)

    def test_fused_is_median_and_ignores_weight(self):
        # Le look le plus dense est deviant : la mediane l'ignore, pas la moyenne.
        fr, ct = _three_looks(0.10, 1000, 0.30, 20, 0.32, 10)
        out = ml.fuse_looks(fr, ct, n_min=1)
        assert out["fused"][0, 0] == pytest.approx(0.30)
        assert out["pooled"][0, 0] > 0.10   # tire vers le look dense

    def test_n_min_excludes_sparse_looks(self):
        fr, ct = _three_looks(0.10, 3, 0.30, 20, 0.32, 10)
        out = ml.fuse_looks(fr, ct, n_min=4)
        assert out["n_used"][0, 0] == 2
        assert out["fused"][0, 0] == pytest.approx(0.31)
        assert out["n_looks"][0, 0] == 3   # present mais pas retenu

    def test_nodata_cells_are_ignored(self):
        fr = np.array([[[0.20]], [[0.99]]], dtype=float)   # 0.99 = valeur parasite
        ct = np.array([[[50.0]], [[-1.0]]])                # 2e look : cellule nodata
        out = ml.fuse_looks(fr, ct, n_min=1)
        assert out["n_looks"][0, 0] == 1
        assert out["fused"][0, 0] == pytest.approx(0.20)
        assert out["pooled"][0, 0] == pytest.approx(0.20)

    def test_all_nodata_gives_nan_without_crash(self):
        fr = np.full((2, 2, 2), -1.0)
        ct = np.full((2, 2, 2), -1.0)
        out = ml.fuse_looks(fr, ct, n_min=1)
        assert np.all(np.isnan(out["fused"]))
        assert np.all(np.isnan(out["pooled"]))
        assert np.all(out["n_looks"] == 0)

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            ml.fuse_looks(np.zeros((2, 3, 3)), np.zeros((3, 3, 3)), n_min=1)


# ── band_contrast ────────────────────────────────────────────────────────────

class TestBandContrast:
    def test_positive_contrast_detected(self):
        field = np.array([[0.60, 0.60, 0.20, 0.20]])
        n_looks = np.array([[3, 3, 1, 1]])
        out = ml.band_contrast(field, n_looks, looks_threshold=3)
        assert out["contrast"] == pytest.approx(0.40)
        assert out["n_band"] == 2 and out["n_out"] == 2

    def test_nan_ignored(self):
        field = np.array([[np.nan, 0.60, 0.20, 0.20]])
        n_looks = np.array([[3, 3, 1, 1]])
        out = ml.band_contrast(field, n_looks, looks_threshold=3)
        assert out["n_band"] == 1
        assert out["contrast"] == pytest.approx(0.40)

    def test_empty_population_gives_nan(self):
        field = np.array([[0.60, 0.60]])
        n_looks = np.array([[3, 3]])       # aucune cellule hors bande
        out = ml.band_contrast(field, n_looks, looks_threshold=3)
        assert np.isnan(out["contrast"])


# ── classify_like_process_hag ────────────────────────────────────────────────

def _cfg(thresholds=(0.20, 0.45, 0.85), sigma=1.0, median_m=9):
    return {
        "vegetation": {
            "active_preset": "t",
            "presets": {"t": {"thresholds": list(thresholds)}},
            "process_hag": {"gaussian_sigma": sigma, "median_size": median_m},
        }
    }


class TestClassify:
    def test_threshold_mapping(self):
        field = np.full((1, 30), 0.9)   # au-dessus des 3 seuils
        cls = ml.classify_like_process_hag(field, _cfg(), 1.0)
        assert set(np.unique(cls)) <= {85, 170, 255}
        assert (cls == 255).sum() > 0

    def test_low_field_stays_empty(self):
        field = np.zeros((10, 10))
        cls = ml.classify_like_process_hag(field, _cfg(), 1.0)
        assert cls.sum() == 0

    def test_nan_is_masked(self):
        field = np.full((10, 10), 0.9)
        field[:, :5] = np.nan
        cls = ml.classify_like_process_hag(field, _cfg(), 1.0)
        assert (cls[:, :5] == 0).all()


# ── class_surfaces ───────────────────────────────────────────────────────────

def test_class_surfaces_sum_to_100_or_zero():
    cls = np.array([[85, 85, 170, 255, 0]])
    s = ml.class_surfaces(cls)
    assert s[406] == pytest.approx(50.0)
    assert s[408] == pytest.approx(25.0)
    assert s[410] == pytest.approx(25.0)
    assert ml.class_surfaces(np.zeros((2, 2), dtype=np.uint8))[406] == 0.0
