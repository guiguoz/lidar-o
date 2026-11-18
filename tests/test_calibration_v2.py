"""Tests unitaires pour le module de calibration v2.

Couvre :
- classify_ndvd : ordre des seuils, valeurs limites
- compute_zone_metrics : IoU parfait, IoU zéro, dénominateurs
- zone_slice : correspondance coordonnées Lambert 93 → pixels
- compute_ndvd : dénominateur nul, poids normalisés
- apply_gaussian : invariance sur signal constant
"""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

# Importation du module depuis experiments/
import sys
import pathlib
_CALIB = pathlib.Path(__file__).resolve().parents[1] / "experiments" / "bois_dupont" / "calibration_v2"
sys.path.insert(0, str(_CALIB))

from run_calibration_v2 import (
    classify_ndvd,
    compute_ndvd,
    compute_zone_metrics,
    zone_slice,
    apply_gaussian,
    OCAD_COLORS,
    OBJ_W,
    NODATA_CLS,
)


# ─────────────────────────────────────────────────────────────────────────────
# classify_ndvd
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyNdvd:
    def test_below_all_thresholds_gives_zero(self):
        sig = np.array([[0.0, 0.1, 0.29]])
        cls = classify_ndvd(sig, t406=0.30, t408=0.60, t410=0.80)
        assert (cls == 0).all()

    def test_above_406_only(self):
        sig = np.array([[0.35, 0.40, 0.45]])
        cls = classify_ndvd(sig, t406=0.30, t408=0.60, t410=0.80)
        assert (cls == 406).all()

    def test_above_408(self):
        sig = np.array([[0.65]])
        cls = classify_ndvd(sig, t406=0.30, t408=0.60, t410=0.80)
        assert cls[0, 0] == 408

    def test_above_410(self):
        sig = np.array([[0.85]])
        cls = classify_ndvd(sig, t406=0.30, t408=0.60, t410=0.80)
        assert cls[0, 0] == 410

    def test_exact_boundary_406(self):
        sig = np.array([[0.40]])
        cls = classify_ndvd(sig, t406=0.40, t408=0.60, t410=0.80)
        assert cls[0, 0] == 406

    def test_nodata_gives_nodata_cls(self):
        # signal=−9999 (V+g==0 après voisinage) → NODATA_CLS, distinct de classe 0
        sig = np.array([[-9999.0]])
        cls = classify_ndvd(sig, t406=0.30, t408=0.60, t410=0.80)
        assert cls[0, 0] == NODATA_CLS

    def test_zero_signal_gives_zero_not_nodata(self):
        # signal=0.0 (sol réel, retours présents) → classe 0, pas NODATA_CLS
        sig = np.array([[0.0]])
        cls = classify_ndvd(sig, t406=0.30, t408=0.60, t410=0.80)
        assert cls[0, 0] == 0

    def test_later_thresholds_override_earlier(self):
        # 0.9 >= 0.4, >= 0.6, >= 0.8 → doit être 410
        sig = np.full((3, 3), 0.9)
        cls = classify_ndvd(sig, t406=0.40, t408=0.60, t410=0.80)
        assert (cls == 410).all()

    def test_all_classes_in_one_array(self):
        sig = np.array([[0.1, 0.5, 0.7, 0.9]])
        cls = classify_ndvd(sig, t406=0.40, t408=0.60, t410=0.80)
        assert list(cls[0]) == [0, 406, 408, 410]


# ─────────────────────────────────────────────────────────────────────────────
# compute_ndvd
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeNdvd:
    def test_all_ground_gives_zero(self):
        strates = np.array([
            [[10.0]], [[0.0]], [[0.0]], [[0.0]]
        ])
        ndvd = compute_ndvd(strates, w_low=0.5, w_med=0.35, w_high=0.15)
        # V=0, g=10 → (0-10)/(0+10) = -1 → ((−1+1)/2) = 0.0
        assert ndvd[0, 0] == pytest.approx(0.0, abs=1e-5)

    def test_all_high_gives_one(self):
        strates = np.array([
            [[0.0]], [[0.0]], [[0.0]], [[10.0]]
        ])
        ndvd = compute_ndvd(strates, w_low=0.5, w_med=0.35, w_high=0.15)
        # V=1.5, g=0 → (1.5-0)/(1.5+0) = 1 → (1+1)/2 = 1.0
        assert ndvd[0, 0] == pytest.approx(1.0, abs=1e-5)

    def test_zero_denominator_gives_nodata(self):
        strates = np.zeros((4, 2, 2))
        ndvd = compute_ndvd(strates, w_low=0.5, w_med=0.35, w_high=0.15)
        assert (ndvd == -9999.0).all()

    def test_equal_veg_and_ground_gives_half(self):
        # V = g → (V-g)/(V+g) = 0 → NDVD = 0.5
        strates = np.array([
            [[1.0]], [[2.0]], [[0.0]], [[0.0]]
        ])
        # V = 0.5*2 + 0.35*0 + 0.15*0 = 1.0, g = 1.0
        ndvd = compute_ndvd(strates, w_low=0.5, w_med=0.35, w_high=0.15)
        assert ndvd[0, 0] == pytest.approx(0.5, abs=1e-5)

    def test_weights_sum_independent_of_scale(self):
        # Doubler tous les comptages ne change pas NDVD
        strates = np.array([
            [[2.0]], [[4.0]], [[2.0]], [[1.0]]
        ])
        strates2 = strates * 2.0
        ndvd1 = compute_ndvd(strates,  w_low=0.5, w_med=0.35, w_high=0.15)
        ndvd2 = compute_ndvd(strates2, w_low=0.5, w_med=0.35, w_high=0.15)
        assert ndvd1[0, 0] == pytest.approx(ndvd2[0, 0], abs=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# zone_slice
# ─────────────────────────────────────────────────────────────────────────────

class TestZoneSlice:
    def _make_transform(self, xmin=425000.0, ymax=6923000.0, res=2.0):
        return from_bounds(xmin, ymax - 500 * res, xmin + 500 * res, ymax, 500, 500)

    def test_full_bbox_gives_full_grid(self):
        t = self._make_transform()
        z = {"xmin": 425000.0, "ymin": 6922000.0, "xmax": 426000.0, "ymax": 6923000.0}
        r0, r1, c0, c1 = zone_slice(z, t, 500, 500)
        assert r0 == 0 and r1 == 500
        assert c0 == 0 and c1 == 500

    def test_ne_quadrant_coords(self):
        t = self._make_transform()
        z = {"xmin": 425510.0, "ymin": 6922510.0, "xmax": 426000.0, "ymax": 6923000.0}
        r0, r1, c0, c1 = zone_slice(z, t, 500, 500)
        assert c0 == 255 and c1 == 500
        assert r0 == 0 and r1 == 245

    def test_clamp_to_grid_boundaries(self):
        t = self._make_transform()
        z = {"xmin": 424900.0, "ymin": 6921900.0, "xmax": 426100.0, "ymax": 6923100.0}
        r0, r1, c0, c1 = zone_slice(z, t, 500, 500)
        assert r0 == 0 and r1 == 500
        assert c0 == 0 and c1 == 500


# ─────────────────────────────────────────────────────────────────────────────
# compute_zone_metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeZoneMetrics:
    def _make_masks(self, h: int, w: int, veg_code: str = "veg_406") -> dict:
        masks = {name: np.zeros((h, w), bool) for name in list(OCAD_COLORS.values()) + ["unknown"]}
        return masks

    def test_perfect_veg_prediction_iou_one(self):
        h, w = 10, 10
        masks = self._make_masks(h, w)
        masks["veg_406"][:5, :] = True   # référence : moitié veg_406
        pred = np.zeros((h, w), dtype=np.uint16)
        pred[:5, :] = 406   # prédiction parfaite

        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        assert m.iou_406 == pytest.approx(1.0, abs=1e-5)
        assert m.miou3 == pytest.approx(1.0 / 3, abs=1e-4)   # 406=1.0, 408=0.0, 410=0.0

    def test_no_veg_pred_gives_zero_recall(self):
        h, w = 10, 10
        masks = self._make_masks(h, w)
        masks["veg_406"][:, :] = True
        pred = np.zeros((h, w), dtype=np.uint16)   # aucune prédiction veg

        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        assert m.iou_presence == pytest.approx(0.0, abs=1e-5)
        assert m.recall_presence == pytest.approx(0.0, abs=1e-5)

    def test_all_fp_gives_zero_precision(self):
        h, w = 10, 10
        masks = self._make_masks(h, w)
        masks["decouvert"][:, :] = True   # tout est découvert dans la référence
        pred = np.full((h, w), 406, dtype=np.uint16)   # on prédit tout veg

        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        assert m.precision_presence == pytest.approx(0.0, abs=1e-5)
        assert m.spec_nonveg == pytest.approx(0.0, abs=1e-5)

    def test_all_unknown_gives_zero_known(self):
        h, w = 5, 5
        masks = self._make_masks(h, w)
        masks["unknown"][:, :] = True   # tout inconnu
        pred = np.full((h, w), 406, dtype=np.uint16)
        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        assert m.n_known == 0

    def test_score_range_zero_one(self):
        h, w = 20, 20
        masks = self._make_masks(h, w)
        masks["veg_406"][:10, :10] = True
        masks["decouvert"][10:, :] = True
        masks["blanc"][:10, 10:] = True
        pred = np.zeros((h, w), dtype=np.uint16)
        pred[:10, :10] = 406

        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        assert 0.0 <= m.score <= 1.0

    def test_score_weights_sum_to_one(self):
        assert sum(OBJ_W.values()) == pytest.approx(1.0, abs=1e-9)

    def test_nodata_cls_as_fn_on_veg_reference(self):
        # NODATA prédit sur référence végétation = FN de présence et de catégorie.
        h, w = 10, 10
        masks = self._make_masks(h, w)
        masks["veg_406"][:5, :] = True   # 50 pixels veg_406
        pred = np.zeros((h, w), dtype=np.uint16)
        pred[:5, :] = 406
        pred[0, 0] = NODATA_CLS   # 2 pixels NODATA sur veg
        pred[1, 0] = NODATA_CLS

        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        assert m.n_pred_unknown == 2
        # fn_p = 2 (NODATA sur ref_veg), tp_p = 48, fp_p = 0
        # IoU = 48 / (48+0+2) = 48/50 = 0.96
        assert m.iou_presence  == pytest.approx(48/50, abs=1e-5)
        assert m.recall_presence == pytest.approx(48/50, abs=1e-5)
        assert m.precision_presence == pytest.approx(1.0, abs=1e-5)
        # iou_406 : fn = 2 (NODATA sur veg_406), tp = 48, fp = 0
        assert m.iou_406 == pytest.approx(48/50, abs=1e-5)

    def test_spec_nonveg_excludes_nodata_from_denominator(self):
        # NODATA prédit sur référence decouvert : exclu du dénominateur des spécificités,
        # ne compte pas comme succès (n'est pas TN).
        h, w = 10, 10
        masks = self._make_masks(h, w)
        masks["decouvert"][:, :] = True   # 100 pixels decouvert
        pred = np.full((h, w), 406, dtype=np.uint16)   # 100 FP potentiels
        pred[0, 0] = 0           # 1 pixel sol → TN correct
        pred[1, 0] = NODATA_CLS  # 1 pixel NODATA → exclu du dénominateur

        sl = (0, h, 0, w)
        m = compute_zone_metrics(pred, masks, sl)
        # n_strict_eval = 100 − 1 (NODATA) = 99
        # fp_nonveg = 98 (pred=406 sur decouvert, hors NODATA et sol)
        # spec_nonveg = 1 − 98/99
        assert m.spec_nonveg == pytest.approx(1.0 - 98/99, abs=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# apply_gaussian
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyGaussian:
    def test_uniform_signal_unchanged(self):
        # Sur un signal uniforme, le filtre gaussien doit laisser les valeurs intérieures inchangées.
        strates = np.ones((4, 50, 50), dtype=np.float32) * 10.0
        smoothed = apply_gaussian(strates, sigma_m=2.0)
        # Pixels centraux (hors bords) doivent être ~= 10.0
        inner = smoothed[:, 10:-10, 10:-10]
        assert inner == pytest.approx(10.0, abs=0.01)

    def test_shape_preserved(self):
        strates = np.random.rand(4, 30, 30).astype(np.float32)
        smoothed = apply_gaussian(strates, sigma_m=1.0)
        assert smoothed.shape == strates.shape

    def test_larger_sigma_smoothes_more(self):
        # Signal à pic central : sigma plus grand → pic plus étalé
        strates = np.zeros((4, 50, 50), dtype=np.float32)
        strates[3, 25, 25] = 100.0

        s1 = apply_gaussian(strates, sigma_m=1.0)
        s2 = apply_gaussian(strates, sigma_m=4.0)
        # Le pic central est moins fort avec sigma plus grand
        assert s2[3, 25, 25] < s1[3, 25, 25]
        # Mais la somme totale est conservée (gaussien normalisé)
        assert s2[3].sum() == pytest.approx(s1[3].sum(), rel=0.05)
