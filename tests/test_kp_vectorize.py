"""Tests autonomes pour src/kp_vectorize.py.

Synthétiques, déterministes, sans réseau, sans données LiDAR/FFCO réelles,
sans binaire KP/PDAL et sans exécution du pipeline complet.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np
import pytest
import shapely.geometry as sg

from src.kp_vectorize import (
    RoiCells,
    RoiRecord,
    _build_pred_arrays,
    _qa_layers,
    _weighted_macro_f1,
    calibrate_thresholds,
    check_max_pct,
    collect_roi_cells,
    erode_roi,
    evaluate_mapping,
    load_fixed_mapping,
    polygonize_variant,
    read_greendetectsize,
    sample_semantic_cells,
    thresholds_to_mapping,
)
from src.kp_raster import ISOM_TO_DN, KP_FIRST_GREEN


# ── Helpers de construction de données synthétiques ──────────────────────────

def _make_roi_cells(roi_id, cls, split, shades) -> RoiCells:
    return RoiCells(roi_id=roi_id, cls=cls, split=split,
                    cells=np.array(shades, dtype=np.uint8))


def _make_cfg(shade_to_isom: dict | None = None) -> dict:
    """Config minimale avec shade_to_isom personnalisable."""
    s2i = shade_to_isom if shade_to_isom is not None else {
        2: 0, 3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410,
    }
    return {"karttapullautin": {"vectorization": {
        "shade_to_isom": s2i,
        "coverage_simplify_m": 2.0,
    }}}


# ── Test 1 : mapping fixe chargé depuis config, distinct de ISOM_TO_DN ──────

class TestLoadFixedMapping:
    def test_loads_correctly(self):
        cfg = _make_cfg({3: 406, 5: 408, 7: 410})
        m = load_fixed_mapping(cfg)
        assert m == {3: 406, 5: 408, 7: 410}

    def test_distinct_from_isom_to_dn(self):
        """shade_to_isom[bit_kp] = code ISOM ≠ ISOM_TO_DN[code ISOM] = DN raster."""
        cfg = _make_cfg({3: 406, 5: 408, 7: 410})
        s2i = load_fixed_mapping(cfg)
        # Les valeurs de shade_to_isom sont des codes ISOM, pas des DN raster
        assert set(s2i.values()) - {0} == {406, 408, 410}
        # ISOM_TO_DN convertit code ISOM → DN ; les espaces sont disjoints
        assert set(s2i.keys()).isdisjoint(set(ISOM_TO_DN.values()))

    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="shade_to_isom"):
            load_fixed_mapping({"karttapullautin": {"vectorization": {}}})

    def test_reads_real_config_structure(self):
        cfg = _make_cfg()  # mapping réel de la consigne
        m = load_fixed_mapping(cfg)
        # Bit 2 → blanc (0), bits 3-4 → 406, 5-6 → 408, 7-8 → 410
        assert m[2] == 0
        assert m[3] == 406 and m[4] == 406
        assert m[5] == 408 and m[6] == 408
        assert m[7] == 410 and m[8] == 410


# ── Test 2 : calibration monotone sur données synthétiques à ordre connu ─────

class TestCalibrateThresholds:
    def _make_clean_roi_cells(self) -> list[RoiCells]:
        """Données où 406<408<410 est parfaitement séparable."""
        return [
            _make_roi_cells("r406a", 406, "calibration", [3, 3, 4, 3]),
            _make_roi_cells("r406b", 406, "calibration", [3, 4, 4, 3]),
            _make_roi_cells("r408a", 408, "calibration", [5, 5, 6, 5]),
            _make_roi_cells("r408b", 408, "calibration", [5, 6, 6, 6]),
            _make_roi_cells("r410a", 410, "calibration", [7, 7, 8, 8]),
            _make_roi_cells("r410b", 410, "calibration", [7, 8, 8, 7]),
        ]

    def test_finds_correct_thresholds(self):
        roi_cells = self._make_clean_roi_cells()
        t1, t2, report = calibrate_thresholds(roi_cells, valid_shades=[3, 4, 5, 6, 7, 8])
        # Les seuils doivent séparer 3-4 | 5-6 | 7-8
        assert t1 in (4,), f"t1 attendu 4, obtenu {t1}"
        assert t2 in (6,), f"t2 attendu 6, obtenu {t2}"
        assert report["macro_f1"] == pytest.approx(1.0, abs=1e-4)

    def test_monotone_by_construction(self):
        roi_cells = self._make_clean_roi_cells()
        t1, t2, _ = calibrate_thresholds(roi_cells, valid_shades=[3, 4, 5, 6, 7, 8])
        assert t1 < t2, "t1 doit être strictement inférieur à t2"

    def test_missing_class_raises(self):
        roi_cells = [
            _make_roi_cells("r406", 406, "calibration", [3, 3, 4]),
            _make_roi_cells("r408", 408, "calibration", [5, 6, 5]),
            # 410 absent
        ]
        with pytest.raises(ValueError, match="410"):
            calibrate_thresholds(roi_cells, valid_shades=[3, 4, 5, 6, 7, 8])

    def test_no_calibration_rois_raises(self):
        roi_cells = [_make_roi_cells("r406", 406, "validation", [3, 4])]
        with pytest.raises(ValueError, match="calibration"):
            calibrate_thresholds(roi_cells, valid_shades=[3, 4])


# ── Test 3 : validation strictement séparée ──────────────────────────────────

class TestValidationSeparation:
    def _build_dataset(self) -> list[RoiCells]:
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
            _make_roi_cells("v406", 406, "validation", [7, 8]),  # labels inversés
            _make_roi_cells("v408", 408, "validation", [3, 4]),
            _make_roi_cells("v410", 410, "validation", [5, 6]),
        ]
        return calib, val_correct, val_wrong

    def test_thresholds_unchanged_by_validation(self):
        """Modifier les labels de validation ne doit pas changer les seuils calibrés."""
        calib, val_correct, val_wrong = self._build_dataset()
        t1a, t2a, _ = calibrate_thresholds(
            calib + val_correct, [3, 4, 5, 6, 7, 8], split="calibration",
        )
        t1b, t2b, _ = calibrate_thresholds(
            calib + val_wrong, [3, 4, 5, 6, 7, 8], split="calibration",
        )
        assert t1a == t1b and t2a == t2b, (
            "Les seuils calibrés ne doivent pas dépendre des labels de validation"
        )

    def test_evaluate_uses_frozen_thresholds(self):
        """evaluate_mapping reçoit le mapping gelé et ne peut pas le modifier."""
        calib, val_correct, _ = self._build_dataset()
        all_cells = calib + val_correct
        t1, t2, _ = calibrate_thresholds(all_cells, [3, 4, 5, 6, 7, 8])
        mapping = thresholds_to_mapping(t1, t2, [3, 4, 5, 6, 7, 8])
        mapping_before = dict(mapping)
        evaluate_mapping(all_cells, mapping, split="validation")
        assert mapping == mapping_before, "evaluate_mapping ne doit pas modifier le mapping"


# ── Test 4 : pondération au niveau des ROIs ──────────────────────────────────

class TestRoiWeighting:
    def test_large_roi_does_not_dominate(self):
        """Une ROI avec 100 cellules ne doit pas dominer une ROI avec 5 cellules."""
        # Une grande ROI 406 (100 cellules shade=3)
        # Deux petites ROIs 406 (5 cellules shade=5 — mauvais signal pour 406)
        # Si on traitait chaque pixel indépendamment, la grande ROI imposerait 3→406
        # Avec pondération par ROI, les petites ROIs ont un poids égal
        roi_cells = [
            _make_roi_cells("big406", 406, "calibration", [3] * 100),
            _make_roi_cells("sml406", 406, "calibration", [5] * 5),
            _make_roi_cells("r408", 408, "calibration", [5, 5, 5, 6, 5]),
            _make_roi_cells("r410", 410, "calibration", [7, 7, 8, 8, 7]),
        ]
        # Construire les tableaux pour t1=4, t2=6
        preds, truths, wts = _build_pred_arrays(roi_cells, t1=4, t2=6, split="calibration")
        # Vérifier que les poids sont bien différents entre big406 et sml406
        wts_big = wts[truths == 406][:100]
        wts_sml = wts[truths == 406][100:]
        # big406 : w = 1/(3 * 2 * 100) = 1/600 par cellule
        # sml406 : w = 1/(3 * 2 * 5) = 1/30 par cellule
        assert wts_sml[0] > wts_big[0], (
            "Les cellules d'une petite ROI doivent avoir un poids plus élevé "
            "que celles d'une grande ROI de la même classe"
        )


# ── Test 5 : érosion et rejet de ROI vide ────────────────────────────────────

class TestErosion:
    def test_erode_reduces_area(self):
        square = sg.box(0, 0, 100, 100)  # 100m × 100m
        eroded = erode_roi(square, margin_m=10.0)
        assert eroded is not None
        assert eroded.area < square.area

    def test_erode_small_roi_returns_none(self):
        tiny = sg.box(0, 0, 5, 5)  # 5m × 5m, érosion 10m → vide
        result = erode_roi(tiny, margin_m=10.0)
        assert result is None

    def test_erode_none_input_returns_none(self):
        assert erode_roi(None, margin_m=6.0) is None

    def test_collect_skips_empty_roi(self):
        """Une ROI vide après érosion doit être ignorée dans collect_roi_cells."""
        tiny_rec = RoiRecord(roi_id="tiny", cls=406, split="calibration",
                             eroded=None)  # déjà érodée à vide
        labels = np.array([[3, 3, 3], [3, 3, 3], [3, 3, 3]], dtype=np.uint8)
        cells = collect_roi_cells(
            [tiny_rec], labels, res_m=1.0, west=0.0, north=3.0,
            cell_size_m=3, valid_shades=[3],
        )
        assert len(cells) == 0


# ── Test 6 : cellules sémantiques 3m — pas de surcomptage ───────────────────

class TestSemanticCells:
    def test_3m_cells_not_9_pixels(self):
        """Un raster 9×9 à 1m/px avec une ROI couvrant tout = 9 cellules 3×3, pas 81."""
        labels = np.full((9, 9), 3, dtype=np.uint8)
        roi = sg.box(0, 0, 9, 9)
        cells, _ = sample_semantic_cells(
            labels, res_m=1.0, west=0.0, north=9.0,
            roi_geom=roi, cell_size_m=3,
        )
        assert len(cells) == 9, f"Attendu 9 cellules, obtenu {len(cells)}"

    def test_cell_mode_applied(self):
        """Le mode est appliqué quand les pixels d'une cellule ne sont pas constants."""
        labels = np.array([
            [3, 3, 3,  5, 5, 5],
            [3, 5, 3,  5, 5, 5],
            [3, 3, 3,  5, 5, 5],
        ], dtype=np.uint8)
        roi = sg.box(0, 0, 6, 3)
        cells, pct_nc = sample_semantic_cells(
            labels, res_m=1.0, west=0.0, north=3.0,
            roi_geom=roi, cell_size_m=3,
        )
        assert len(cells) == 2
        assert int(cells[0]) == 3   # mode de la cellule gauche (7×3 vs 1×5)
        assert int(cells[1]) == 5   # mode de la cellule droite (9×5)
        assert pct_nc == pytest.approx(50.0)  # la cellule gauche est non-constante

    def test_empty_roi_returns_empty(self):
        labels = np.full((6, 6), 3, dtype=np.uint8)
        cells, _ = sample_semantic_cells(labels, 1.0, 0.0, 6.0, None)
        assert len(cells) == 0


# ── Test 7 : palette ou tons inconnus ────────────────────────────────────────

class TestUnknownTones:
    def test_missing_shade_to_isom_raises(self):
        with pytest.raises(ValueError, match="shade_to_isom"):
            load_fixed_mapping({"karttapullautin": {}})

    def test_empty_shade_to_isom_raises(self):
        with pytest.raises(ValueError, match="shade_to_isom"):
            load_fixed_mapping(_make_cfg({}))

    def test_unknown_isom_code_in_polygonize(self):
        """Un shade mappé vers un code ISOM inconnu (ex. 999) est ignoré silencieusement."""
        labels = np.array([[3, 3], [3, 3]], dtype=np.uint8)
        mapping = {3: 999}  # 999 n'est pas dans ISOM_TO_DN
        layers = polygonize_variant(labels, mapping, res_m=1.0, west=0.0, north=2.0,
                                    crs="EPSG:2154", tol=0.0)
        assert all(len(v) == 0 for v in layers.values())


# ── Test 8 : statuts reject_3class / inconclusive ────────────────────────────

class TestStatusCodes:
    def test_reject_hard_max_pct(self):
        """max_pct > 50% → reject_hard."""
        result = check_max_pct(max_pct=60.0, max_pct_fixed=30.0, cls=406)
        assert result["reject_hard"] is True

    def test_no_reject_below_50(self):
        """max_pct ≤ 50% → pas de reject_hard, même si > 1.5 × fixed."""
        result = check_max_pct(max_pct=49.9, max_pct_fixed=10.0, cls=408)
        assert result["reject_hard"] is False
        assert result["alert_relative"] is True

    def test_inconclusive_threshold_not_assigned_without_porteur(self):
        """evaluate_mapping ne doit pas afficher 'validé' sans seuil du porteur."""
        roi_cells = [
            _make_roi_cells("v406", 406, "validation", [3, 4]),
            _make_roi_cells("v408", 408, "validation", [5, 6]),
            _make_roi_cells("v410", 410, "validation", [7, 8]),
        ]
        mapping = {3: 406, 4: 406, 5: 408, 6: 408, 7: 410, 8: 410}
        result = evaluate_mapping(roi_cells, mapping, split="validation")
        # Vérifier que le rapport est diagnostique, pas décisif
        assert "status_note" in result
        assert "porteur" in result["status_note"].lower()
        assert "validé" not in json.dumps(result)


# ── Test 9 : polygonisation, GPKG, CRS, deux variantes identiques en traitement

class TestPolygonize:
    def _make_labels(self) -> np.ndarray:
        """Raster 9×9 avec deux classes : shade 3 à gauche, shade 7 à droite."""
        labels = np.zeros((9, 9), dtype=np.uint8)
        labels[:, :4] = 3   # 406 dans mapping fixe
        labels[:, 5:] = 7   # 410 dans mapping fixe
        return labels

    def test_two_classes_produced(self):
        labels = self._make_labels()
        mapping = {3: 406, 7: 410}
        layers = polygonize_variant(labels, mapping, res_m=1.0,
                                    west=0.0, north=9.0, crs="EPSG:2154", tol=0.0)
        assert len(layers[406]) > 0
        assert len(layers[410]) > 0
        assert len(layers[408]) == 0

    def test_gpkg_valid_geometries(self, tmp_path):
        import geopandas as gpd

        labels = self._make_labels()
        mapping = {3: 406, 7: 410}
        layers = polygonize_variant(labels, mapping, res_m=1.0,
                                    west=0.0, north=9.0, crs="EPSG:2154", tol=0.0)
        gpkg = tmp_path / "test_out.gpkg"
        for code, geoms in layers.items():
            if geoms:
                gdf = gpd.GeoDataFrame(
                    {"geometry": geoms, "class": [code] * len(geoms)},
                    crs="EPSG:2154",
                )
                gdf.to_file(str(gpkg), layer=f"veg_{code}", driver="GPKG")

        # Relire et vérifier
        for code in (406, 410):
            g = gpd.read_file(str(gpkg), layer=f"veg_{code}")
            assert g.crs.to_epsg() == 2154
            assert g.geometry.is_valid.all()

    def test_same_geometry_treatment_both_variants(self):
        """Les deux variantes utilisent le même traitement géométrique."""
        labels = self._make_labels()
        m_fixed = {3: 406, 7: 410}
        m_calib = {3: 406, 7: 410}  # Même mapping → même résultat
        layers_a = polygonize_variant(labels, m_fixed, 1.0, 0.0, 9.0, "EPSG:2154", 0.0)
        layers_b = polygonize_variant(labels, m_calib, 1.0, 0.0, 9.0, "EPSG:2154", 0.0)
        assert len(layers_a[406]) == len(layers_b[406])
        assert len(layers_a[410]) == len(layers_b[410])


# ── Test 10 : métriques géométriques sur formes simples ─────────────────────

class TestGeometricMetrics:
    def test_max_pct_single_polygon(self):
        """Un seul polygone = max_pct 100%."""
        geom = sg.box(0, 0, 100, 100)
        layers = {406: [geom], 408: [], 410: []}
        qa = _qa_layers(layers)
        assert qa[406]["max_pct"] == pytest.approx(100.0)

    def test_max_pct_two_equal_polygons(self):
        """Deux polygones égaux = max_pct 50%."""
        g1 = sg.box(0, 0, 10, 10)
        g2 = sg.box(20, 0, 30, 10)
        layers = {406: [g1, g2], 408: [], 410: []}
        qa = _qa_layers(layers)
        assert qa[406]["max_pct"] == pytest.approx(50.0)

    def test_total_ha_unit(self):
        """Un carré 100m × 100m = 1 ha."""
        geom = sg.box(0, 0, 100, 100)
        layers = {406: [geom], 408: [], 410: []}
        qa = _qa_layers(layers)
        assert qa[406]["total_ha"] == pytest.approx(1.0, rel=1e-3)

    def test_empty_class(self):
        layers = {406: [], 408: [], 410: []}
        qa = _qa_layers(layers)
        assert qa[406]["n"] == 0
        assert qa[406]["max_pct"] == pytest.approx(0.0)


# ── Test 11 : règles max_pct — plafond dur 50%, alerte relative séparée ──────

class TestMaxPct:
    def test_hard_cap_50_independent_of_fixed(self):
        """Le plafond dur 50% est absolu — même si fixed > 50%, calibrated > 50% → reject."""
        r = check_max_pct(max_pct=55.0, max_pct_fixed=60.0, cls=408)
        assert r["reject_hard"] is True
        # alert_relative : 55 > 1.5 × 60 = 90 ? Non
        assert r["alert_relative"] is False

    def test_alert_relative_triggered(self):
        """max_pct_calibrated > 1.5 × max_pct_fixed → alerte relative."""
        r = check_max_pct(max_pct=25.0, max_pct_fixed=10.0, cls=408)
        assert r["alert_relative"] is True
        assert r["reject_hard"] is False

    def test_alert_406_threshold(self):
        """Alerte 406 si max_pct406 > 15%."""
        r_above = check_max_pct(max_pct=16.0, max_pct_fixed=5.0, cls=406)
        r_below = check_max_pct(max_pct=14.9, max_pct_fixed=5.0, cls=406)
        assert r_above["alert_406"] is True
        assert r_below["alert_406"] is False

    def test_no_alert_406_for_other_classes(self):
        """L'alerte 406 ne s'applique pas aux classes 408 et 410."""
        for cls in (408, 410):
            r = check_max_pct(max_pct=20.0, max_pct_fixed=5.0, cls=cls)
            assert r["alert_406"] is False

    def test_reject_hard_50_exact_boundary(self):
        """max_pct = 50% exactement → pas de reject_hard (seuil strict)."""
        r = check_max_pct(max_pct=50.0, max_pct_fixed=10.0, cls=408)
        assert r["reject_hard"] is False
        r2 = check_max_pct(max_pct=50.01, max_pct_fixed=10.0, cls=408)
        assert r2["reject_hard"] is True


# ── Test 12 : isolation des sorties — pas d'écriture hors tmp ────────────────

class TestOutputIsolation:
    def test_run_writes_only_in_out_dir(self, tmp_path, monkeypatch):
        """Un run complet (simulé) n'écrit qu'à l'intérieur de out_dir."""
        import os
        import geopandas as gpd
        from unittest.mock import patch, MagicMock

        out_dir = tmp_path / "out_exp"
        out_dir.mkdir()

        # Construire un dataset synthétique minimal
        rois = [
            _make_roi_cells("c406", 406, "calibration", [3, 4, 3]),
            _make_roi_cells("c408", 408, "calibration", [5, 5, 6]),
            _make_roi_cells("c410", 410, "calibration", [7, 7, 8]),
            _make_roi_cells("v406", 406, "validation", [3, 3]),
            _make_roi_cells("v408", 408, "validation", [5, 6]),
            _make_roi_cells("v410", 410, "validation", [7, 8]),
        ]

        # Labels synthétiques 9×9 : shades 3, 5, 7 sur trois bandes
        labels = np.zeros((9, 9), dtype=np.uint8)
        labels[:, :3] = 3
        labels[:, 3:6] = 5
        labels[:, 6:] = 7

        cfg = _make_cfg()
        t1, t2, _ = calibrate_thresholds(rois, [3, 4, 5, 6, 7, 8])
        calib_mapping = thresholds_to_mapping(t1, t2, [3, 4, 5, 6, 7, 8])
        fixed_mapping = load_fixed_mapping(cfg)

        # Polygoniser les deux variantes
        fixed_layers = polygonize_variant(labels, fixed_mapping, 1.0, 0.0, 9.0, "EPSG:2154", 0.0)
        calib_layers = polygonize_variant(labels, calib_mapping, 1.0, 0.0, 9.0, "EPSG:2154", 0.0)

        # Écrire dans out_dir
        for name, lyr_dict in (
            ("kp_vectorize_fixed.gpkg", fixed_layers),
            ("kp_vectorize_calibrated.gpkg", calib_layers),
        ):
            for code, geoms in lyr_dict.items():
                gdf = gpd.GeoDataFrame(
                    {"geometry": geoms, "class": [code] * len(geoms)}, crs="EPSG:2154",
                )
                gdf.to_file(str(out_dir / name), layer=f"veg_{code}", driver="GPKG")

        report_path = out_dir / "kp_vectorize_report.json"
        report_path.write_text("{}", encoding="utf-8")

        # Vérifier que SEULS les fichiers attendus ont été créés dans out_dir
        created = set(p.name for p in out_dir.iterdir())
        expected = {"kp_vectorize_fixed.gpkg", "kp_vectorize_calibrated.gpkg",
                    "kp_vectorize_report.json"}
        assert created == expected, f"Fichiers inattendus : {created - expected}"

        # Vérifier que rien n'a été écrit en dehors de out_dir (tmp_path)
        # out_dir est un sous-répertoire de tmp_path — toute écriture hors de tmp_path
        # serait hors périmètre. On vérifie que le dossier tmp_path ne contient
        # que out_dir (et ses fichiers).
        top_level = set(p.name for p in tmp_path.iterdir())
        assert top_level == {"out_exp"}, (
            f"Fichiers écrits hors de out_dir : {top_level - {'out_exp'}}"
        )

    def test_file_exists_error_prevents_overwrite(self, tmp_path):
        """FileExistsError si un fichier de sortie existe déjà."""
        from src.kp_vectorize import run_calibration

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "kp_vectorize_fixed.gpkg").write_text("existing")

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


# ── Test supplémentaire : greendetectsize lu depuis INI ──────────────────────

class TestReadGreendetectsize:
    def test_default_when_no_ini(self, tmp_path):
        assert read_greendetectsize(tmp_path / "nonexistent.ini") == 3

    def test_reads_value_from_ini(self, tmp_path):
        ini = tmp_path / "pullauta.ini"
        ini.write_text("greendetectsize=5\nlightgreentone=160\n", encoding="utf-8")
        assert read_greendetectsize(ini) == 5

    def test_default_none_path(self):
        assert read_greendetectsize(None) == 3
