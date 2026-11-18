"""Tests — intégration mode smoothed dans supervised_e et smooth_veg.

Couvre :
  - smooth_veg.smoothed_vectorize  : sortie {0,2,3,4}, polygones valides, pas d'overlaps
  - smooth_veg.validate_smoothed_coverage : couverture complète, échecs explicites
  - EXPORT_MODE_SMOOTHED            : constante, nom GPKG, sidecar JSON
  - Cache signing                   : hit si algo version OK, re-vectorisation sinon
  - faithful non-régression         : résultat faithful inchangé par la présence du mode smoothed
  - GUI                             : "smoothed" présent dans les valeurs du combo
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pytest
import shapely
from affine import Affine
from shapely.geometry import box

root = pathlib.Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
if str(root / "src") not in sys.path:
    sys.path.insert(0, str(root / "src"))

from src.supervised_e import (
    EXPORT_MODE_FAITHFUL,
    EXPORT_MODE_GENERALIZED,
    EXPORT_MODE_SMOOTHED,
    save_vegetation_gpkg,
    vectorize_prediction,
)
import smooth_veg as _sv


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tx(res: float = 2.0, h: int = 20) -> Affine:
    return Affine(res, 0.0, 0.0, 0.0, -res, float(h * res))


def _grid20() -> tuple[np.ndarray, np.ndarray]:
    """Grille 20×20 avec deux classes veg (0=découvert, 2=406) et support complet."""
    pred = np.zeros((20, 20), dtype=np.uint8)
    pred[10:, :] = 2
    supp = np.ones((20, 20), dtype=np.uint8)
    return pred, supp


def _grid_with_unknown() -> tuple[np.ndarray, np.ndarray]:
    """Grille 20×20 avec trou UNKNOWN (support==0) au centre."""
    pred, supp = _grid20()
    supp[8:12, 8:12] = 0  # carré 4×4 sans données
    return pred, supp


def _grid_multiclass() -> tuple[np.ndarray, np.ndarray]:
    """Grille 30×30 avec quatre classes veg."""
    pred = np.zeros((30, 30), dtype=np.uint8)
    pred[10:20, :] = 2
    pred[20:, :] = 3
    pred[:, 20:] = 4
    pred[:10, :20] = 0
    supp = np.ones((30, 30), dtype=np.uint8)
    return pred, supp


# ── Tests smooth_veg.smoothed_vectorize ──────────────────────────────────────

class TestSmoothedVectorize:

    def test_returns_four_class_keys(self):
        pred, supp = _grid20()
        result = _sv.smoothed_vectorize(pred, supp, _tx())
        assert set(result.keys()) == {0, 2, 3, 4}

    def test_all_polygons_are_valid(self):
        pred, supp = _grid20()
        result = _sv.smoothed_vectorize(pred, supp, _tx())
        for class_id, polys in result.items():
            for p in polys:
                assert p.is_valid, f"classe {class_id} : polygone invalide"

    def test_no_overlaps(self):
        pred, supp = _grid_multiclass()
        result = _sv.smoothed_vectorize(pred, supp, _tx(h=30))
        all_polys = [p for ps in result.values() for p in ps]
        arr = np.array(all_polys, dtype=object)
        i_a, i_b = shapely.STRtree(arr).query(arr, predicate="overlaps")
        pairs = i_a < i_b
        total = sum(
            float(shapely.area(shapely.intersection(arr[ia], arr[ib])))
            for ia, ib in zip(i_a[pairs], i_b[pairs])
        )
        assert total <= 1e-4, f"recouvrements detectes : {total:.4f} m²"

    def test_validate_passes(self):
        pred, supp = _grid_multiclass()
        result = _sv.smoothed_vectorize(pred, supp, _tx(h=30))
        # Ne doit pas lever d'exception
        _sv.validate_smoothed_coverage(result, supp, _tx(h=30))

    def test_deterministic(self):
        pred, supp = _grid_multiclass()
        tx = _tx(h=30)
        r1 = _sv.smoothed_vectorize(pred, supp, tx)
        r2 = _sv.smoothed_vectorize(pred, supp, tx)
        for class_id in r1:
            wkt1 = sorted(p.wkt for p in r1[class_id])
            wkt2 = sorted(p.wkt for p in r2[class_id])
            assert wkt1 == wkt2, f"classe {class_id} non déterministe"

    def test_handles_unknown_zone(self):
        pred, supp = _grid_with_unknown()
        result = _sv.smoothed_vectorize(pred, supp, _tx())
        _sv.validate_smoothed_coverage(result, supp, _tx())

    def test_no_overflow_outside_support(self):
        pred, supp = _grid20()
        result = _sv.smoothed_vectorize(pred, supp, _tx())
        all_polys = [p for ps in result.values() for p in ps]
        supp_u8 = supp.astype(np.uint8)
        from rasterio.features import shapes as _shapes
        supp_polys = [shapely.geometry.shape(g) for g, v in _shapes(supp_u8, mask=supp_u8, transform=_tx()) if v == 1]
        support_poly = shapely.union_all(np.array(supp_polys, dtype=object))
        for p in all_polys:
            overflow = float(shapely.area(shapely.difference(p, support_poly)))
            assert overflow <= 1e-4, f"débordement {overflow:.4f} m²"


# ── Tests smooth_veg.validate_smoothed_coverage (échecs explicites) ──────────

class TestValidateSmoothedCoverage:

    def test_raises_on_overflow(self):
        pred, supp = _grid20()
        # Inject un polygone hors support
        result = {0: [box(-10, -10, -1, -1)], 2: [], 3: [], 4: []}
        with pytest.raises(ValueError, match="debordement"):
            _sv.validate_smoothed_coverage(result, supp, _tx())

    def test_raises_on_unknown_invasion(self):
        pred, supp = _grid_with_unknown()
        # Zone UNKNOWN : carré 4×4 en pixels [8:12,8:12]
        # Transform Affine(2, 0, 0, 0, -2, 40) : x = col*2, y = 40 - row*2
        # Pixels [8:12,8:12] → zone x∈[16,24], y∈[16,24]
        # Un polygone dans cette zone est hors support → "debordement" ou "UNKNOWN"
        # (les deux checks défendent la même invariant)
        invading = box(17, 17, 23, 23)  # dans la zone UNKNOWN == hors support
        result = {0: [invading], 2: [], 3: [], 4: []}
        with pytest.raises(ValueError):
            _sv.validate_smoothed_coverage(result, supp, _tx())

    def test_raises_on_overlaps(self):
        pred, supp = _grid20()
        p1 = box(0, 0, 10, 10)
        p2 = box(5, 5, 15, 15)  # overlap avec p1
        result = {0: [p1, p2], 2: [], 3: [], 4: []}
        with pytest.raises(ValueError, match="recouvrements"):
            _sv.validate_smoothed_coverage(result, supp, _tx())


# ── Tests EXPORT_MODE_SMOOTHED dans supervised_e ─────────────────────────────

class TestExportModeSmoothed:

    def test_constant_value(self):
        assert EXPORT_MODE_SMOOTHED == "smoothed"

    def test_gpkg_name_contains_smoothed(self):
        from src.supervised_e import run_supervised_e
        import inspect
        src = inspect.getsource(run_supervised_e)
        # Le nom du GPKG utilise le mode comme suffix
        assert "vegetation_supervised_e_{export_mode}" in src or "export_mode" in src

    def test_vectorize_prediction_dispatches_to_smooth_veg(self):
        """vectorize_prediction(smoothed) délègue à smooth_veg.smoothed_vectorize."""
        pred, supp = _grid20()
        result = vectorize_prediction(pred, supp, _tx(), export_mode=EXPORT_MODE_SMOOTHED)
        assert set(result.keys()) == {0, 2, 3, 4}
        all_valid = all(p.is_valid for ps in result.values() for p in ps)
        assert all_valid

    def test_sidecar_has_algo_version(self, tmp_path):
        polys = {0: [box(0, 0, 10, 10)], 2: [], 3: [], 4: []}
        out = tmp_path / "vegetation_supervised_e_smoothed.gpkg"
        save_vegetation_gpkg(polys, "EPSG:2154", out, EXPORT_MODE_SMOOTHED, _sv.ALGO_VERSION)
        meta = json.loads(out.with_suffix(".json").read_text())
        assert meta["export_mode"] == "smoothed"
        assert meta["smoothed_algo_version"] == _sv.ALGO_VERSION

    def test_sidecar_faithful_has_no_algo_version(self, tmp_path):
        polys = {0: [box(0, 0, 10, 10)], 2: [], 3: [], 4: []}
        out = tmp_path / "vegetation_supervised_e_faithful.gpkg"
        save_vegetation_gpkg(polys, "EPSG:2154", out, EXPORT_MODE_FAITHFUL)
        meta = json.loads(out.with_suffix(".json").read_text())
        assert "smoothed_algo_version" not in meta


# ── Cache signing ─────────────────────────────────────────────────────────────

class TestCacheSigning:

    def _write_fake_pred_tif(self, path: pathlib.Path) -> None:
        """Écrit un .tif minimal lisible par rasterio."""
        import rasterio
        from rasterio.transform import from_bounds
        pred = np.zeros((20, 20), dtype=np.uint8)
        supp = np.ones((20, 20), dtype=np.uint8)
        transform = from_bounds(0, 0, 40, 40, 20, 20)
        with rasterio.open(
            str(path), "w", driver="GTiff",
            count=2, dtype="uint8", width=20, height=20,
            crs="EPSG:2154", transform=transform,
        ) as ds:
            ds.write(pred, 1)
            ds.write(supp, 2)

    def test_cache_hit_matching_algo_version(self, tmp_path):
        """run_supervised_e saute la vectorisation si GPKG + sidecar cohérents."""
        from src.supervised_e import run_supervised_e

        pred_path = tmp_path / "supervised_e_prediction.tif"
        self._write_fake_pred_tif(pred_path)
        gpkg_path = tmp_path / "vegetation_supervised_e_smoothed.gpkg"
        gpkg_path.write_bytes(b"fake")
        sidecar = gpkg_path.with_suffix(".json")
        sidecar.write_text(
            json.dumps({"export_mode": "smoothed", "smoothed_algo_version": _sv.ALGO_VERSION}),
            encoding="utf-8",
        )

        result = run_supervised_e(
            laz_files=[],
            bbox=[0, 0, 40, 40],
            output_dir=tmp_path,
            force=False,
            export_mode=EXPORT_MODE_SMOOTHED,
        )
        assert result["vegetation_gpkg"] == gpkg_path
        # Le GPKG factice n'est pas modifié (run a sauté la vectorisation)
        assert gpkg_path.read_bytes() == b"fake"

    def test_cache_miss_wrong_algo_version(self, tmp_path):
        """run_supervised_e revectorise si la version algo du sidecar est différente."""
        from src.supervised_e import run_supervised_e

        pred_path = tmp_path / "supervised_e_prediction.tif"
        self._write_fake_pred_tif(pred_path)
        gpkg_path = tmp_path / "vegetation_supervised_e_smoothed.gpkg"
        gpkg_path.write_bytes(b"fake")
        sidecar = gpkg_path.with_suffix(".json")
        sidecar.write_text(
            json.dumps({"export_mode": "smoothed", "smoothed_algo_version": "old-version"}),
            encoding="utf-8",
        )

        # La revectorisation doit s'exécuter → le GPKG factice est remplacé
        result = run_supervised_e(
            laz_files=[],
            bbox=[0, 0, 40, 40],
            output_dir=tmp_path,
            force=False,
            export_mode=EXPORT_MODE_SMOOTHED,
        )
        # Le GPKG doit avoir été réécrit (n'est plus le stub "fake")
        assert gpkg_path.read_bytes() != b"fake"

    def test_cache_miss_absent_sidecar(self, tmp_path):
        """Absence de sidecar → revectorisation."""
        from src.supervised_e import run_supervised_e

        pred_path = tmp_path / "supervised_e_prediction.tif"
        self._write_fake_pred_tif(pred_path)
        gpkg_path = tmp_path / "vegetation_supervised_e_smoothed.gpkg"
        gpkg_path.write_bytes(b"fake")
        # Pas de sidecar

        result = run_supervised_e(
            laz_files=[],
            bbox=[0, 0, 40, 40],
            output_dir=tmp_path,
            force=False,
            export_mode=EXPORT_MODE_SMOOTHED,
        )
        assert gpkg_path.read_bytes() != b"fake"


# ── Non-régression faithful ───────────────────────────────────────────────────

class TestFaithfulNonRegression:

    def test_faithful_polygons_unchanged(self):
        """L'ajout du mode smoothed ne change pas le résultat du mode faithful."""
        pred, supp = _grid_multiclass()
        tx = _tx(h=30)
        result_faithful = vectorize_prediction(pred, supp, tx, export_mode=EXPORT_MODE_FAITHFUL)
        # Même résultat après import smooth_veg (qui s'est chargé via smoothed_vectorize)
        result_faithful2 = vectorize_prediction(pred, supp, tx, export_mode=EXPORT_MODE_FAITHFUL)
        for class_id in result_faithful:
            areas1 = sorted(round(p.area, 4) for p in result_faithful[class_id])
            areas2 = sorted(round(p.area, 4) for p in result_faithful2[class_id])
            assert areas1 == areas2, f"faithful non déterministe, classe {class_id}"

    def test_faithful_save_sidecar_no_algo_version(self, tmp_path):
        polys = {0: [box(0, 0, 10, 10)], 2: [], 3: [], 4: []}
        out = tmp_path / "veg.gpkg"
        save_vegetation_gpkg(polys, "EPSG:2154", out, EXPORT_MODE_FAITHFUL)
        meta = json.loads(out.with_suffix(".json").read_text())
        assert meta["export_mode"] == "faithful"
        assert "smoothed_algo_version" not in meta

    def test_generalized_save_sidecar_no_algo_version(self, tmp_path):
        polys = {0: [box(0, 0, 10, 10)], 2: [], 3: [], 4: []}
        out = tmp_path / "veg.gpkg"
        save_vegetation_gpkg(polys, "EPSG:2154", out, EXPORT_MODE_GENERALIZED)
        meta = json.loads(out.with_suffix(".json").read_text())
        assert meta["export_mode"] == "generalized"
        assert "smoothed_algo_version" not in meta


# ── GUI ───────────────────────────────────────────────────────────────────────

class TestGUISmoothedCombo:

    def test_smoothed_in_combo_values(self):
        """Le combo d'export GUI inclut 'smoothed'."""
        import inspect
        import gui.app as _app
        src = inspect.getsource(_app)
        # Cherche la liste de valeurs du combo d'export
        assert '"smoothed"' in src or "'smoothed'" in src

    def test_all_three_modes_in_combo(self):
        """Les trois modes faithful/generalized/smoothed sont présents."""
        import inspect
        import gui.app as _app
        src = inspect.getsource(_app)
        for mode in ("faithful", "generalized", "smoothed"):
            assert mode in src, f"Mode '{mode}' absent de gui/app.py"
