"""Tests autonomes pour src/kp_vectorize.py — V2.

Synthétiques, déterministes, sans réseau, sans données LiDAR/FFCO réelles,
sans binaire KP/PDAL et sans exécution du pipeline complet.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest
import shapely.geometry as sg

from src.kp_vectorize import (
    CellSample,
    RoiCells,
    RoiRecord,
    _build_pred_arrays,
    _check_output_dir_empty,
    _commission_405,
    _diagnostic_matrix,
    _min_weighted_recall,
    _qa_layers,
    _require_ini,
    _validate_tile_sources,
    _weighted_macro_f1,
    calibrate_thresholds,
    check_max_pct,
    collect_roi_cells,
    compute_geometric_criteria,
    erode_roi,
    evaluate_mapping,
    load_fixed_mapping,
    polygonize_variant,
    read_greendetectsize,
    run_calibration,
    sample_semantic_cells,
    thresholds_to_mapping,
)
from src.kp_raster import ISOM_TO_DN, KP_FIRST_GREEN


# ── Helpers de construction de données synthétiques ──────────────────────────

def _make_roi_cells(
    roi_id, cls: int, split: str, shades: list,
    n_no_pred: int = 0, n_nodata: int = 0,
) -> RoiCells:
    sample = CellSample(
        cells_green=np.array(shades, dtype=np.uint8),
        n_nodata=n_nodata,
        n_no_prediction=n_no_pred,
        pct_non_constant=0.0,
    )
    return RoiCells(roi_id=roi_id, cls=cls, split=split, sample=sample)


def _make_cfg(shade_to_isom: dict | None = None) -> dict:
    s2i = shade_to_isom if shade_to_isom is not None else {
        2: 0, 3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410,
    }
    return {"karttapullautin": {"vectorization": {
        "shade_to_isom": s2i,
        "coverage_simplify_m": 2.0,
    }}}


# ── Préconditions runtime ────────────────────────────────────────────────────

class TestRequireIni:
    def test_raises_if_no_ini(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="pullauta.ini"):
            _require_ini(tmp_path)

    def test_returns_ini_path(self, tmp_path):
        ini = tmp_path / "pullauta.ini"
        ini.write_text("greendetectsize=3\n", encoding="utf-8")
        assert _require_ini(tmp_path) == ini


class TestValidateTileSources:
    def test_raises_for_vegetation_png(self, tmp_path):
        from unittest.mock import MagicMock
        tile = MagicMock()
        tile.path.name = "vegetation.png"
        tile.path.parent = tmp_path
        with pytest.raises(ValueError, match="vegetation.png"):
            _validate_tile_sources([tile])

    def test_raises_for_merged_file(self, tmp_path):
        from unittest.mock import MagicMock
        tile = MagicMock()
        tile.path.name = "merged_vege.png"
        tile.path.parent = tmp_path
        with pytest.raises(ValueError, match="merged"):
            _validate_tile_sources([tile])

    def test_passes_for_vege_tiles(self):
        from unittest.mock import MagicMock
        tile = MagicMock()
        tile.path.name = "tile1_vege.png"
        _validate_tile_sources([tile])  # aucune exception


class TestCheckOutputDirEmpty:
    def test_raises_if_not_empty(self, tmp_path):
        (tmp_path / "existing.txt").write_text("x", encoding="utf-8")
        with pytest.raises(FileExistsError):
            _check_output_dir_empty(tmp_path)

    def test_passes_for_empty_dir(self, tmp_path):
        _check_output_dir_empty(tmp_path)

    def test_passes_for_nonexistent_dir(self, tmp_path):
        _check_output_dir_empty(tmp_path / "nonexistent")


# ── Mapping fixe ─────────────────────────────────────────────────────────────

class TestLoadFixedMapping:
    def test_loads_correctly(self):
        cfg = _make_cfg({3: 406, 5: 408, 7: 410})
        m = load_fixed_mapping(cfg)
        assert m == {3: 406, 5: 408, 7: 410}

    def test_distinct_from_isom_to_dn(self):
        """shade_to_isom[bit_kp] = code ISOM ≠ ISOM_TO_DN[code ISOM] = DN raster."""
        s2i = load_fixed_mapping(_make_cfg({3: 406, 5: 408, 7: 410}))
        assert set(s2i.values()) - {0} == {406, 408, 410}
        assert set(s2i.keys()).isdisjoint(set(ISOM_TO_DN.values()))

    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="shade_to_isom"):
            load_fixed_mapping({"karttapullautin": {"vectorization": {}}})

    def test_invalid_isom_code_raises(self):
        """Un code ISOM invalide (ex. 999) lève ValueError — pas de silence."""
        with pytest.raises(ValueError, match="999"):
            load_fixed_mapping(_make_cfg({3: 999}))

    def test_zero_isom_code_valid(self):
        """0 est valide (blanc, aucune végétation)."""
        m = load_fixed_mapping(_make_cfg({2: 0, 5: 408, 7: 410}))
        assert m[2] == 0

    def test_reads_real_config_structure(self):
        m = load_fixed_mapping(_make_cfg())
        assert m[2] == 0
        assert m[3] == 406 and m[4] == 406
        assert m[5] == 408 and m[6] == 408
        assert m[7] == 410 and m[8] == 410


# ── Calibration monotone ─────────────────────────────────────────────────────

class TestCalibrateThresholds:
    def _make_clean_roi_cells(self) -> list[RoiCells]:
        return [
            _make_roi_cells("r406a", 406, "calibration", [3, 3, 4, 3]),
            _make_roi_cells("r406b", 406, "calibration", [3, 4, 4, 3]),
            _make_roi_cells("r408a", 408, "calibration", [5, 5, 6, 5]),
            _make_roi_cells("r408b", 408, "calibration", [5, 6, 6, 6]),
            _make_roi_cells("r410a", 410, "calibration", [7, 7, 8, 8]),
            _make_roi_cells("r410b", 410, "calibration", [7, 8, 8, 7]),
        ]

    def test_finds_correct_thresholds(self):
        t1, t2, report = calibrate_thresholds(
            self._make_clean_roi_cells(), valid_shades=[3, 4, 5, 6, 7, 8],
        )
        assert t1 == 4, f"t1 attendu 4, obtenu {t1}"
        assert t2 == 6, f"t2 attendu 6, obtenu {t2}"
        assert report["macro_f1"] == pytest.approx(1.0, abs=1e-4)

    def test_monotone_by_construction(self):
        t1, t2, _ = calibrate_thresholds(
            self._make_clean_roi_cells(), valid_shades=[3, 4, 5, 6, 7, 8],
        )
        assert t1 < t2

    def test_missing_class_raises(self):
        roi_cells = [
            _make_roi_cells("r406", 406, "calibration", [3, 3, 4]),
            _make_roi_cells("r408", 408, "calibration", [5, 6, 5]),
        ]
        with pytest.raises(ValueError, match="410"):
            calibrate_thresholds(roi_cells, valid_shades=[3, 4, 5, 6, 7, 8])

    def test_no_calibration_rois_raises(self):
        roi_cells = [_make_roi_cells("r406", 406, "validation", [3, 4])]
        with pytest.raises(ValueError, match="calibration"):
            calibrate_thresholds(roi_cells, valid_shades=[3, 4])


# ── Validation strictement séparée ───────────────────────────────────────────

class TestValidationSeparation:
    def _build_dataset(self):
        calib = [
            _make_roi_cells("c406", 406, "calibration", [3, 4, 3]),
            _make_roi_cells("c408", 408, "calibration", [5, 5, 6]),
            _make_roi_cells("c410", 410, "calibration", [7, 8, 7]),
        ]
        val_correct = [
            _make_roi_cells("v406", 406, "validation", [3, 3]),
            _make_roi_cells("v408", 408, "validation", [5, 6]),
            _make_roi_cells("v410", 410, "validation", [7, 8]),
        ]
        val_wrong = [
            _make_roi_cells("v406x", 406, "validation", [7, 8]),
            _make_roi_cells("v408x", 408, "validation", [3, 4]),
            _make_roi_cells("v410x", 410, "validation", [5, 6]),
        ]
        return calib, val_correct, val_wrong

    def test_thresholds_unchanged_by_validation(self):
        calib, val_correct, val_wrong = self._build_dataset()
        t1a, t2a, _ = calibrate_thresholds(
            calib + val_correct, [3, 4, 5, 6, 7, 8], split="calibration",
        )
        t1b, t2b, _ = calibrate_thresholds(
            calib + val_wrong, [3, 4, 5, 6, 7, 8], split="calibration",
        )
        assert t1a == t1b and t2a == t2b

    def test_evaluate_uses_frozen_thresholds(self):
        calib, val_correct, _ = self._build_dataset()
        all_cells = calib + val_correct
        t1, t2, _ = calibrate_thresholds(all_cells, [3, 4, 5, 6, 7, 8])
        mapping = thresholds_to_mapping(t1, t2, [3, 4, 5, 6, 7, 8])
        mapping_before = dict(mapping)
        evaluate_mapping(all_cells, mapping, split="validation")
        assert mapping == mapping_before


# ── Non-détections et NoData ─────────────────────────────────────────────────

class TestNonDetections:
    def test_n_covered_includes_no_prediction_not_nodata(self):
        """n_covered = green + no_prediction (nodata exclu)."""
        sample = CellSample(
            cells_green=np.array([3, 4], dtype=np.uint8),
            n_nodata=5,
            n_no_prediction=3,
            pct_non_constant=0.0,
        )
        assert sample.n_covered == 5  # 2 verts + 3 no_pred

    def test_no_prediction_contributes_to_fn(self):
        """Les cellules no_prediction ≡ FN — diminuent le rappel par rapport à baseline."""
        roi_with_nopred = [
            _make_roi_cells("r406", 406, "calibration", [3, 3], n_no_pred=3),
            _make_roi_cells("r408", 408, "calibration", [5, 5]),
            _make_roi_cells("r410", 410, "calibration", [7, 7]),
        ]
        roi_baseline = [
            _make_roi_cells("r406", 406, "calibration", [3, 3]),
            _make_roi_cells("r408", 408, "calibration", [5, 5]),
            _make_roi_cells("r410", 410, "calibration", [7, 7]),
        ]
        p_np, t_np, w_np = _build_pred_arrays(roi_with_nopred, t1=3, t2=5, split="calibration")
        p_bl, t_bl, w_bl = _build_pred_arrays(roi_baseline, t1=3, t2=5, split="calibration")
        f1_np = _weighted_macro_f1(p_np, t_np, w_np)
        f1_bl = _weighted_macro_f1(p_bl, t_bl, w_bl)
        assert f1_np < f1_bl

    def test_nodata_excluded_from_weight(self):
        """n_nodata ne modifie pas n_covered donc pas le poids."""
        r408 = _make_roi_cells("r408", 408, "calibration", [5, 5])
        r410 = _make_roi_cells("r410", 410, "calibration", [7, 7])
        r_with_nd = _make_roi_cells("r406a", 406, "calibration", [3, 3], n_nodata=100)
        r_without_nd = _make_roi_cells("r406b", 406, "calibration", [3, 3], n_nodata=0)

        _, t1, w1 = _build_pred_arrays([r_with_nd, r408, r410], 3, 5, "calibration")
        _, t2, w2 = _build_pred_arrays([r_without_nd, r408, r410], 3, 5, "calibration")
        wts1_406 = w1[t1 == 406]
        wts2_406 = w2[t2 == 406]
        assert np.allclose(wts1_406, wts2_406)


# ── Commission 405 ────────────────────────────────────────────────────────────

class TestCommission405:
    def test_green_in_405_is_commission(self):
        mapping = {3: 406, 5: 408, 7: 410}
        rois = [_make_roi_cells("r405", 405, "calibration", [3, 3])]
        result = _commission_405(rois, mapping, "calibration")
        assert result["n_commission"] == 2
        assert result["commission_rate_raw"] == pytest.approx(1.0)
        assert result["commission_rate_weighted"] == pytest.approx(1.0)

    def test_yellow_in_405_is_correct_rejection(self):
        mapping = {3: 406}
        rois = [_make_roi_cells("r405", 405, "calibration", [], n_no_pred=3)]
        result = _commission_405(rois, mapping, "calibration")
        assert result["n_correct_rejection"] == 3
        assert result["commission_rate_raw"] == pytest.approx(0.0)
        assert result["commission_rate_weighted"] == pytest.approx(0.0)

    def test_green_mapped_to_zero_not_commission_but_in_denominator(self):
        """Un shade vert mappé à 0 = rejet sans prédiction, mais reste dans le dénominateur."""
        mapping = {3: 0}  # shade 3 → blanc, pas de végétation
        rois = [_make_roi_cells("r405", 405, "calibration", [3, 3])]
        result = _commission_405(rois, mapping, "calibration")
        assert result["n_commission"] == 0
        assert result["n_correct_rejection"] == 2  # in denominator
        assert result["commission_rate_raw"] == pytest.approx(0.0)

    def test_mixed_405(self):
        mapping = {3: 406}
        rois = [_make_roi_cells("r405", 405, "calibration", [3], n_no_pred=1)]
        result = _commission_405(rois, mapping, "calibration")
        assert result["n_commission"] == 1
        assert result["n_correct_rejection"] == 1
        assert result["commission_rate_raw"] == pytest.approx(0.5)

    def test_weighted_rate_not_dominated_by_large_roi(self):
        """Taux pondéré : petite et grande ROI contribuent à parts égales."""
        mapping = {3: 406}
        # Grande ROI : 100% commission ; petite ROI : 0% commission
        rois = [
            _make_roi_cells("large", 405, "calibration", [3] * 100),   # rate=1.0
            _make_roi_cells("small", 405, "calibration", [], n_no_pred=2),  # rate=0.0
        ]
        result = _commission_405(rois, mapping, "calibration")
        # raw = 100/102 ≈ 0.98 ; weighted = (1.0+0.0)/2 = 0.5
        assert result["commission_rate_raw"] == pytest.approx(100 / 102, rel=1e-3)
        assert result["commission_rate_weighted"] == pytest.approx(0.5)

    def test_no_405_rois(self):
        rois = [_make_roi_cells("r406", 406, "calibration", [3])]
        result = _commission_405(rois, {3: 406}, "calibration")
        assert result["n_rois_405"] == 0


# ── Pondération par ROI ───────────────────────────────────────────────────────

class TestRoiWeighting:
    def test_large_roi_does_not_dominate(self):
        roi_cells = [
            _make_roi_cells("big406", 406, "calibration", [3] * 100),
            _make_roi_cells("sml406", 406, "calibration", [5] * 5),
            _make_roi_cells("r408", 408, "calibration", [5, 5, 5, 6, 5]),
            _make_roi_cells("r410", 410, "calibration", [7, 7, 8, 8, 7]),
        ]
        preds, truths, wts = _build_pred_arrays(roi_cells, t1=4, t2=6, split="calibration")
        wts_big = wts[truths == 406][:100]
        wts_sml = wts[truths == 406][100:]
        # big406 : w = 1/(3×2×100) = 1/600 ; sml406 : w = 1/(3×2×5) = 1/30
        assert wts_sml[0] > wts_big[0]


# ── Érosion et rejet de ROI vide ─────────────────────────────────────────────

class TestErosion:
    def test_erode_reduces_area(self):
        square = sg.box(0, 0, 100, 100)
        eroded = erode_roi(square, margin_m=10.0)
        assert eroded is not None
        assert eroded.area < square.area

    def test_erode_small_roi_returns_none(self):
        tiny = sg.box(0, 0, 5, 5)
        assert erode_roi(tiny, margin_m=10.0) is None

    def test_erode_none_input_returns_none(self):
        assert erode_roi(None, margin_m=6.0) is None

    def test_collect_skips_empty_roi(self):
        tiny_rec = RoiRecord(roi_id="tiny", cls=406, split="calibration", eroded=None)
        labels = np.array([[3, 3, 3], [3, 3, 3], [3, 3, 3]], dtype=np.uint8)
        cells = collect_roi_cells(
            [tiny_rec], labels, res_m=1.0, west=0.0, north=3.0,
            cell_size_m=3, valid_shades=[3],
        )
        assert len(cells) == 0


# ── Cellules sémantiques 3 m ─────────────────────────────────────────────────

class TestSemanticCells:
    def test_3m_cells_not_9_pixels(self):
        """Un raster 9×9 à 1 m/px → 9 cellules 3×3, pas 81 pixels."""
        labels = np.full((9, 9), 3, dtype=np.uint8)
        roi = sg.box(0, 0, 9, 9)
        sample = sample_semantic_cells(labels, res_m=1.0, west=0.0, north=9.0,
                                       roi_geom=roi, cell_size_m=3)
        assert len(sample.cells_green) == 9

    def test_cell_mode_applied(self):
        labels = np.array([
            [3, 3, 3,  5, 5, 5],
            [3, 5, 3,  5, 5, 5],
            [3, 3, 3,  5, 5, 5],
        ], dtype=np.uint8)
        roi = sg.box(0, 0, 6, 3)
        sample = sample_semantic_cells(labels, res_m=1.0, west=0.0, north=3.0,
                                       roi_geom=roi, cell_size_m=3)
        assert len(sample.cells_green) == 2
        assert int(sample.cells_green[0]) == 3
        assert int(sample.cells_green[1]) == 5
        assert sample.pct_non_constant == pytest.approx(50.0)

    def test_empty_roi_returns_empty(self):
        labels = np.full((6, 6), 3, dtype=np.uint8)
        sample = sample_semantic_cells(labels, 1.0, 0.0, 6.0, None)
        assert len(sample.cells_green) == 0

    def test_yellow_cells_counted_as_no_prediction(self):
        """Pixels avec mode=1 (KP_YELLOW) → n_no_prediction, pas cells_green."""
        from src.kp_raster import KP_YELLOW
        labels = np.full((3, 3), KP_YELLOW, dtype=np.uint8)
        roi = sg.box(0, 0, 3, 3)
        sample = sample_semantic_cells(labels, res_m=1.0, west=0.0, north=3.0,
                                       roi_geom=roi, cell_size_m=3)
        assert sample.n_no_prediction == 1
        assert len(sample.cells_green) == 0
        assert sample.n_covered == 1

    def test_partial_cells_at_border_ignored(self):
        """Fenêtres partielles en bord de raster sont ignorées (pas de cellule incomplète)."""
        # 7×7 raster, cell_size=3 → 4 cellules 3×3 complètes ; la bordure partielle est ignorée
        labels = np.full((7, 7), 3, dtype=np.uint8)
        roi = sg.box(0, 0, 7, 7)
        sample = sample_semantic_cells(labels, res_m=1.0, west=0.0, north=7.0,
                                       roi_geom=roi, cell_size_m=3)
        assert len(sample.cells_green) == 4, (
            f"Attendu 4 cellules complètes, obtenu {len(sample.cells_green)}"
        )

    def test_nodata_cell_not_counted_in_pct_non_constant(self):
        """Une cellule de mode NoData ne contribue pas à pct_non_constant."""
        from src.kp_raster import KP_NO_DATA
        # Cellule gauche : mode=NoData (8 NoData + 1 shade=3) — mixte mais exclue de n_covered
        # Cellule droite : pure shade=3
        labels = np.array([
            [KP_NO_DATA, KP_NO_DATA, KP_NO_DATA,  3, 3, 3],
            [KP_NO_DATA,           3, KP_NO_DATA,  3, 3, 3],
            [KP_NO_DATA, KP_NO_DATA, KP_NO_DATA,  3, 3, 3],
        ], dtype=np.uint8)
        roi = sg.box(0, 0, 6, 3)
        sample = sample_semantic_cells(labels, res_m=1.0, west=0.0, north=3.0,
                                       roi_geom=roi, cell_size_m=3)
        assert sample.n_nodata == 1
        assert len(sample.cells_green) == 1
        assert sample.pct_non_constant == pytest.approx(0.0)


# ── Codes inconnus / invalides ────────────────────────────────────────────────

class TestUnknownTones:
    def test_missing_shade_to_isom_raises(self):
        with pytest.raises(ValueError, match="shade_to_isom"):
            load_fixed_mapping({"karttapullautin": {}})

    def test_empty_shade_to_isom_raises(self):
        with pytest.raises(ValueError, match="shade_to_isom"):
            load_fixed_mapping(_make_cfg({}))

    def test_invalid_isom_code_raises_explicit_error(self):
        """Un code ISOM invalide doit lever une erreur explicite, pas être ignoré."""
        with pytest.raises(ValueError, match="999"):
            load_fixed_mapping(_make_cfg({3: 999}))

    def test_zero_mapped_shade_skipped_in_polygonize(self):
        """Shade mappé à 0 (blanc) → ignoré dans polygonize_variant (pas dans ISOM_TO_DN)."""
        labels = np.array([[3, 3], [3, 3]], dtype=np.uint8)
        layers = polygonize_variant(labels, {3: 0}, res_m=1.0, west=0.0, north=2.0,
                                    crs="EPSG:2154", tol=0.0)
        assert all(len(v) == 0 for v in layers.values())


# ── Statuts reject_3class / inconclusive ─────────────────────────────────────

class TestStatusCodes:
    def test_reject_hard_max_pct(self):
        assert check_max_pct(60.0, 30.0, 406)["reject_hard"] is True

    def test_no_reject_below_50(self):
        r = check_max_pct(49.9, 10.0, 408)
        assert r["reject_hard"] is False
        assert r["alert_relative"] is True

    def test_inconclusive_threshold_not_assigned_without_porteur(self):
        roi_cells = [
            _make_roi_cells("v406", 406, "validation", [3, 4]),
            _make_roi_cells("v408", 408, "validation", [5, 6]),
            _make_roi_cells("v410", 410, "validation", [7, 8]),
        ]
        mapping = {3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410}
        result = evaluate_mapping(roi_cells, mapping, split="validation")
        assert "status_note" in result
        assert "porteur" in result["status_note"].lower()
        assert "validé" not in json.dumps(result)


# ── Polygonisation ────────────────────────────────────────────────────────────

class TestPolygonize:
    def _make_labels(self) -> np.ndarray:
        labels = np.zeros((9, 9), dtype=np.uint8)
        labels[:, :4] = 3
        labels[:, 5:] = 7
        return labels

    def test_two_classes_produced(self):
        layers = polygonize_variant(self._make_labels(), {3: 406, 7: 410},
                                    res_m=1.0, west=0.0, north=9.0, crs="EPSG:2154", tol=0.0)
        assert len(layers[406]) > 0
        assert len(layers[410]) > 0
        assert len(layers[408]) == 0

    def test_gpkg_valid_geometries(self, tmp_path):
        import geopandas as gpd
        layers = polygonize_variant(self._make_labels(), {3: 406, 7: 410},
                                    res_m=1.0, west=0.0, north=9.0, crs="EPSG:2154", tol=0.0)
        gpkg = tmp_path / "test.gpkg"
        for code, geoms in layers.items():
            if geoms:
                gdf = gpd.GeoDataFrame({"geometry": geoms, "class": [code] * len(geoms)},
                                       crs="EPSG:2154")
                gdf.to_file(str(gpkg), layer=f"veg_{code}", driver="GPKG")
        for code in (406, 410):
            g = gpd.read_file(str(gpkg), layer=f"veg_{code}")
            assert g.crs.to_epsg() == 2154
            assert g.geometry.is_valid.all()

    def test_same_geometry_treatment_both_variants(self):
        labels = self._make_labels()
        la = polygonize_variant(labels, {3: 406, 7: 410}, 1.0, 0.0, 9.0, "EPSG:2154", 0.0)
        lb = polygonize_variant(labels, {3: 406, 7: 410}, 1.0, 0.0, 9.0, "EPSG:2154", 0.0)
        assert len(la[406]) == len(lb[406])
        assert len(la[410]) == len(lb[410])

    def test_invalid_coverage_raises_value_error(self):
        """coverage_is_valid=False → ValueError (jamais ignoré silencieusement)."""
        import shapely as shp
        from unittest.mock import patch
        labels = np.array([[3, 3], [3, 3]], dtype=np.uint8)
        mapping = {3: 406}
        with patch.object(shp, "coverage_is_valid", return_value=False), \
             patch.object(shp, "coverage_invalid_edges",
                          return_value=[sg.LineString([(0, 0), (1, 1)])]):
            with pytest.raises(ValueError, match="couverture invalide"):
                polygonize_variant(labels, mapping, 1.0, 0.0, 2.0, "EPSG:2154", 0.0)


# ── Critères géométriques ─────────────────────────────────────────────────────

class TestComputeGeometricCriteria:
    def test_single_square_component(self):
        geom = sg.box(0, 0, 10, 10)
        result = compute_geometric_criteria({406: [geom], 408: [], 410: []}, ffco_ref=None)
        assert result["n_components"] == 1
        assert result["median_component_length_m"] == pytest.approx(10.0, rel=1e-3)
        assert result["legacy_comparability"] is False

    def test_no_geometries(self):
        result = compute_geometric_criteria({406: [], 408: [], 410: []}, ffco_ref=None)
        assert result["n_components"] == 0
        assert result["median_component_length_m"] is None

    def test_coverage_recall_with_ffco_ref(self):
        """Résultat = ref exacte → recall ≈ 100%."""
        geom = sg.box(0, 0, 100, 100)
        ref = sg.box(0, 0, 100, 100)
        result = compute_geometric_criteria({406: [geom], 408: [], 410: []}, ffco_ref=ref)
        assert result["coverage_10m_recall_pct"] == pytest.approx(100.0, abs=0.1)

    def test_legacy_comparability_always_false(self):
        geom = sg.box(0, 0, 50, 50)
        result = compute_geometric_criteria({406: [geom], 408: [], 410: []}, ffco_ref=None)
        assert result["legacy_comparability"] is False


# ── QA par couche ─────────────────────────────────────────────────────────────

class TestGeometricMetrics:
    def test_max_pct_single_polygon(self):
        qa = _qa_layers({406: [sg.box(0, 0, 100, 100)], 408: [], 410: []})
        assert qa[406]["max_pct"] == pytest.approx(100.0)

    def test_max_pct_two_equal_polygons(self):
        qa = _qa_layers({406: [sg.box(0, 0, 10, 10), sg.box(20, 0, 30, 10)], 408: [], 410: []})
        assert qa[406]["max_pct"] == pytest.approx(50.0)

    def test_total_ha_unit(self):
        qa = _qa_layers({406: [sg.box(0, 0, 100, 100)], 408: [], 410: []})
        assert qa[406]["total_ha"] == pytest.approx(1.0, rel=1e-3)

    def test_empty_class(self):
        qa = _qa_layers({406: [], 408: [], 410: []})
        assert qa[406]["n"] == 0
        assert qa[406]["max_pct"] == pytest.approx(0.0)

    def test_med_mm2_present(self):
        """med_mm2 est calculé et cohérent avec l'aire : 100 m² = 1 mm² à 1:10 000."""
        geom = sg.box(0, 0, 10, 10)  # 100 m² → 100 × 0.01 = 1.0 mm²
        qa = _qa_layers({406: [geom], 408: [], 410: []})
        assert qa[406]["med_mm2"] is not None
        assert qa[406]["med_mm2"] == pytest.approx(1.0, rel=1e-3)


# ── Règles max_pct ────────────────────────────────────────────────────────────

class TestMaxPct:
    def test_hard_cap_50_independent_of_fixed(self):
        r = check_max_pct(55.0, 60.0, 408)
        assert r["reject_hard"] is True
        assert r["alert_relative"] is False  # 55 < 1.5×60=90

    def test_alert_relative_triggered(self):
        r = check_max_pct(25.0, 10.0, 408)
        assert r["alert_relative"] is True
        assert r["reject_hard"] is False

    def test_alert_406_threshold(self):
        assert check_max_pct(16.0, 5.0, 406)["alert_406"] is True
        assert check_max_pct(14.9, 5.0, 406)["alert_406"] is False

    def test_no_alert_406_for_other_classes(self):
        for cls in (408, 410):
            assert check_max_pct(20.0, 5.0, cls)["alert_406"] is False

    def test_reject_hard_50_exact_boundary(self):
        assert check_max_pct(50.0, 10.0, 408)["reject_hard"] is False
        assert check_max_pct(50.01, 10.0, 408)["reject_hard"] is True


# ── Départage déterministe ────────────────────────────────────────────────────

class TestTiebreaking:
    def test_deterministic_on_same_data(self):
        roi_cells = [
            _make_roi_cells("r406", 406, "calibration", [3, 4]),
            _make_roi_cells("r408", 408, "calibration", [5, 6]),
            _make_roi_cells("r410", 410, "calibration", [7, 8]),
        ]
        t1a, t2a, _ = calibrate_thresholds(roi_cells, [3, 4, 5, 6, 7, 8])
        t1b, t2b, _ = calibrate_thresholds(roi_cells, [3, 4, 5, 6, 7, 8])
        assert t1a == t1b and t2a == t2b

    def test_min_recall_key_present_in_candidates(self):
        """_min_weighted_recall retourne une valeur dans [0, 1]."""
        preds = np.array([406, 408, 410], dtype=np.int32)
        truths = np.array([406, 408, 410], dtype=np.int32)
        wts = np.ones(3, dtype=np.float64)
        mr = _min_weighted_recall(preds, truths, wts)
        assert 0.0 <= mr <= 1.0
        assert mr == pytest.approx(1.0)

    def test_min_recall_zero_for_missed_class(self):
        """Classe entièrement manquée → rappel minimal = 0."""
        preds = np.array([406, 406, 406], dtype=np.int32)
        truths = np.array([406, 408, 410], dtype=np.int32)
        wts = np.ones(3, dtype=np.float64)
        assert _min_weighted_recall(preds, truths, wts) == pytest.approx(0.0)


# ── Isolation des sorties ─────────────────────────────────────────────────────

class TestOutputIsolation:
    def test_file_exists_error_prevents_overwrite(self, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "kp_vectorize_fixed.gpkg").write_text("existing", encoding="utf-8")
        with pytest.raises(FileExistsError):
            run_calibration(
                out_kp=tmp_path,
                cfg=_make_cfg(),
                crs="EPSG:2154",
                rois_gpkg=tmp_path / "rois.gpkg",
                rois_layer="rois",
                class_field="class",
                split_field="split",
                id_field="roi_id",
                out_dir=out_dir,
            )

    def test_ini_required_before_run(self, tmp_path):
        """FileNotFoundError si pullauta.ini absent — avant toute lecture de tuile."""
        out_kp = tmp_path / "out_kp"
        out_kp.mkdir()
        with pytest.raises(FileNotFoundError, match="pullauta.ini"):
            run_calibration(
                out_kp=out_kp,
                cfg=_make_cfg(),
                crs="EPSG:2154",
                rois_gpkg=tmp_path / "rois.gpkg",
                rois_layer="rois",
                class_field="class",
                split_field="split",
                id_field="roi_id",
                out_dir=tmp_path / "out",
            )


# ── Runner principal (test d'intégration avec mocks) ─────────────────────────

class TestRunCalibration:
    def test_writes_exactly_three_files(self, tmp_path):
        """run_calibration crée exactement kp_vectorize_fixed.gpkg,
        kp_vectorize_calibrated.gpkg et kp_vectorize_report.json dans out_dir."""
        from unittest.mock import MagicMock, patch

        out_kp = tmp_path / "out_kp"
        out_kp.mkdir()
        (out_kp / "pullauta.ini").write_text("greendetectsize=3\n", encoding="utf-8")
        out_dir = tmp_path / "out"

        labels = np.zeros((9, 9), dtype=np.uint8)
        labels[0:3, :] = 3
        labels[3:6, :] = 5
        labels[6:9, :] = 7

        tile_mock = MagicMock()
        tile_mock.path.name = "tile1_vege.png"

        roi_cells = [
            _make_roi_cells("c406", 406, "calibration", [3, 4, 3]),
            _make_roi_cells("c408", 408, "calibration", [5, 5, 6]),
            _make_roi_cells("c410", 410, "calibration", [7, 7, 8]),
        ]

        with patch("src.kp_raster.load_tiles", return_value=[tile_mock]), \
             patch("src.kp_raster.mosaic", return_value=(labels, 1.0, 0.0, 9.0)), \
             patch("src.kp_raster.read_ini_vege_params",
                   return_value={"lightgreentone": 160, "n_shades": 8}), \
             patch("src.kp_vectorize.load_rois", return_value=[]), \
             patch("src.kp_vectorize.collect_roi_cells", return_value=roi_cells):
            report = run_calibration(
                out_kp=out_kp,
                cfg=_make_cfg(),
                crs="EPSG:2154",
                rois_gpkg=tmp_path / "rois.gpkg",
                rois_layer="rois",
                class_field="class",
                split_field="split",
                id_field="roi_id",
                out_dir=out_dir,
            )

        created = {p.name for p in out_dir.iterdir()}
        assert created == {
            "kp_vectorize_fixed.gpkg",
            "kp_vectorize_calibrated.gpkg",
            "kp_vectorize_report.json",
        }
        assert report["status"] in {"candidate_for_review", "reject_3class", "inconclusive"}
        assert (out_dir / "kp_vectorize_report.json").stat().st_size > 0

    def test_vegetation_png_fallback_rejected(self, tmp_path):
        """ValueError si load_tiles retourne vegetation.png."""
        from unittest.mock import MagicMock, patch

        out_kp = tmp_path / "out_kp"
        out_kp.mkdir()
        (out_kp / "pullauta.ini").write_text("greendetectsize=3\n", encoding="utf-8")

        tile_mock = MagicMock()
        tile_mock.path.name = "vegetation.png"
        tile_mock.path.parent = out_kp

        labels = np.full((3, 3), 3, dtype=np.uint8)

        with patch("src.kp_raster.load_tiles", return_value=[tile_mock]), \
             patch("src.kp_raster.mosaic", return_value=(labels, 1.0, 0.0, 3.0)), \
             patch("src.kp_raster.read_ini_vege_params",
                   return_value={"lightgreentone": 160, "n_shades": 8}):
            with pytest.raises(ValueError, match="vegetation.png"):
                run_calibration(
                    out_kp=out_kp,
                    cfg=_make_cfg(),
                    crs="EPSG:2154",
                    rois_gpkg=tmp_path / "rois.gpkg",
                    rois_layer="rois",
                    class_field="class",
                    split_field="split",
                    id_field="roi_id",
                    out_dir=tmp_path / "out",
                )


# ── Lecture greendetectsize ───────────────────────────────────────────────────

class TestReadGreendetectsize:
    def test_default_when_no_ini(self, tmp_path):
        assert read_greendetectsize(tmp_path / "nonexistent.ini") == 3

    def test_reads_value_from_ini(self, tmp_path):
        ini = tmp_path / "pullauta.ini"
        ini.write_text("greendetectsize=5\nlightgreentone=160\n", encoding="utf-8")
        assert read_greendetectsize(ini) == 5

    def test_default_none_path(self):
        assert read_greendetectsize(None) == 3
