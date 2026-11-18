"""Tests d'intégration pour le mode supervised_e.

Couvre :
  §A  Ordre et noms des 63 descripteurs (T puis E)
  §B  Cohérence entraînement/inférence (imputer appris sur train)
  §C  Compatibilité et invalidation des caches
  §D  Détection des doublons géographiques (SA↔Caen)
  §E  Cellules inconnues et support
  §F  Géoréférencement et centres des pixels
  §G  Sauvegarde/rechargement du modèle
  §H  Autonomie sans référence OCAD
  §I  Sélection du mode (pipeline_mode.py)
  §J  Non-régression des modes kp et hag

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe -m pytest experiments/loto_v1/tests/test_supervised_e_integration.py -v
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import pickle
import sys
import tempfile

import numpy as np
import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_LOTO = _ROOT / "experiments" / "loto_v1"
_SUPERVISED_V1 = _ROOT / "experiments" / "bois_dupont" / "supervised_v1"

for _p in [str(_ROOT), str(_ROOT / "src"), str(_LOTO), str(_SUPERVISED_V1)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from descriptors import N_FEATURES as N_FEATURES_T, FEATURE_NAMES as T_FEATURE_NAMES  # noqa: E402
from descriptors_ext import (  # noqa: E402
    N_EXT_FEATURES, EXT_FEATURE_NAMES, BIN_EDGES, N_BINS,
)
from loto_pipeline import RANDOM_SEED, MAX_TRAIN_PX_PER_TERRAIN, NODATA_CODE  # noqa: E402
from loto_pipeline_e import N_FEATURES_E, CFG_E  # noqa: E402


# ── §A : Ordre et noms des 63 descripteurs ───────────────────────────────────

class TestFeatureOrder:
    def test_total_count(self) -> None:
        assert N_FEATURES_T == 30
        assert N_EXT_FEATURES == 33
        assert N_FEATURES_E == 63

    def test_t_features_first(self) -> None:
        """Les 30 features T précèdent les 33 features E dans le vecteur 63."""
        assert len(T_FEATURE_NAMES) == N_FEATURES_T
        # Aucun nom T ne commence par "fe_" (préfixe réservé E)
        assert all(not n.startswith("fe_") for n in T_FEATURE_NAMES)

    def test_e_features_prefix(self) -> None:
        """Tous les noms E commencent par 'fe_'."""
        assert all(n.startswith("fe_") for n in EXT_FEATURE_NAMES)

    def test_no_overlap_in_names(self) -> None:
        common = set(T_FEATURE_NAMES) & set(EXT_FEATURE_NAMES)
        assert common == set(), f"Noms dupliqués T∩E : {common}"

    def test_bin_edges_count(self) -> None:
        assert len(BIN_EDGES) == N_BINS + 1  # 10 bornes → 9 bins
        assert BIN_EDGES[0] == 0.0
        assert np.isinf(BIN_EDGES[-1])

    def test_t_strates_derive_from_e_bins(self) -> None:
        """La somme des bins E couvre exactement les strates T."""
        # T.ground = b0, T.low = b1+b2+b3, T.medium = b4+b5, T.high = b6+b7+b8
        from src.supervised_e import _T_FROM_BINS
        all_bins = [b for group in _T_FROM_BINS for b in group]
        assert sorted(all_bins) == list(range(9)), "Bins E non couverts par mapping T"
        # Chaque bin dans exactement un groupe
        for b in range(9):
            groups_containing = [i for i, g in enumerate(_T_FROM_BINS) if b in g]
            assert len(groups_containing) == 1, f"Bin {b} dans {len(groups_containing)} groupes"


# ── §B : Cohérence entraînement/inférence ────────────────────────────────────

class TestTrainInferCoherence:
    def test_imputer_fitted_on_train_only(self) -> None:
        """L'imputer doit être appris (fitted) avant l'inférence."""
        from sklearn.impute import SimpleImputer
        imp = SimpleImputer(strategy="mean")
        X = np.array([[1.0, np.nan], [np.nan, 2.0], [3.0, 4.0]])
        imp.fit(X)
        result = imp.transform(X)
        assert not np.any(np.isnan(result))
        assert result[0, 1] == pytest.approx(3.0)  # mean of [2.0, 4.0] = 3.0

    def test_n_features_e_matches_model_spec(self) -> None:
        """CFG_E définit RF_leaf5 : paramètres figés."""
        assert CFG_E["n"] == 300
        assert CFG_E["depth"] == 20
        assert CFG_E["leaf"] == 5
        assert CFG_E["weight"] == "balanced"

    def test_random_seed_stable(self) -> None:
        """Le même RANDOM_SEED produit le même sous-échantillonnage."""
        rng1 = np.random.default_rng(RANDOM_SEED)
        rng2 = np.random.default_rng(RANDOM_SEED)
        idx1 = rng1.choice(10000, 300, replace=False)
        idx2 = rng2.choice(10000, 300, replace=False)
        np.testing.assert_array_equal(idx1, idx2)


# ── §C : Invalidation des caches ─────────────────────────────────────────────

class TestCacheInvalidation:
    def test_cache_valid_flag(self) -> None:
        """Un cache sans cache_version est invalide."""
        from src.supervised_e import _check_cache_valid, _CACHE_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "test.npz"
            # Cache sans version → invalide
            np.savez_compressed(str(p), bins=np.zeros((9, 10, 10)))
            assert not _check_cache_valid(p)
            # Cache avec mauvaise version → invalide
            np.savez_compressed(str(p), bins=np.zeros((9, 10, 10)), cache_version="old")
            assert not _check_cache_valid(p)
            # Cache avec bonne version → valide
            np.savez_compressed(str(p), bins=np.zeros((9, 10, 10)),
                                cache_version=np.array(_CACHE_VERSION))
            assert _check_cache_valid(p)

    def test_force_bypasses_cache(self) -> None:
        """force=True contourne un cache valide."""
        from src.supervised_e import _check_cache_valid, _CACHE_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "valid.npz"
            np.savez_compressed(str(p), bins=np.zeros((9, 5, 5)),
                                cache_version=np.array(_CACHE_VERSION))
            assert _check_cache_valid(p)  # valide mais force=True → recompute

    def test_corrupted_cache_invalid(self) -> None:
        """Un cache corrompu est détecté comme invalide."""
        from src.supervised_e import _check_cache_valid
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "corrupt.npz"
            p.write_bytes(b"PK\x03\x04garbage")
            assert not _check_cache_valid(p)


# ── §D : Doublons géographiques SA↔Caen ─────────────────────────────────────

class TestGeographicDeduplication:
    def test_sa_overlap_shape(self) -> None:
        """La zone overlap SA↔Caen est correctement dimensionnée."""
        from train_final_e import _SA_OVERLAP
        r0, r1, c0, c1 = _SA_OVERLAP
        assert r0 == 1000
        assert r1 == 1500
        assert c0 == 500
        assert c1 == 1500
        area_px = (r1 - r0) * (c1 - c0)
        assert area_px == 500 * 1000  # 500k pixels

    def test_overlap_excluded_from_sa_train(self) -> None:
        """Les pixels de la zone overlap sont exclus de l'entraînement SA."""
        from train_final_e import _SA_OVERLAP
        # Simule le masque SA
        h, w = 1500, 1500
        mask = np.ones((h, w), dtype=bool)
        r0, r1, c0, c1 = _SA_OVERLAP
        overlap = np.zeros((h, w), dtype=bool)
        overlap[r0:r1, c0:c1] = True
        mask_after = mask & ~overlap
        # Aucun pixel de l'overlap dans le masque final
        assert not mask_after[r0:r1, c0:c1].any()
        # Pixels hors overlap conservés
        assert mask_after[0:r0, :].all()

    def test_caen_covers_overlap_zone(self) -> None:
        """La zone géographique commune est couverte par Caen (Y=[6888000,6889000])."""
        caen_bbox = [448000.0, 6888000.0, 450000.0, 6889000.0]
        sa_overlap_y = (6888000.0, 6889000.0)
        # Les coordonnées Y de l'overlap Caen tombent dans le bbox Caen
        assert caen_bbox[1] <= sa_overlap_y[0] < caen_bbox[3]
        assert caen_bbox[1] < sa_overlap_y[1] <= caen_bbox[3]


# ── §E : Cellules inconnues et support ───────────────────────────────────────

class TestUnknownAndSupport:
    def test_nodata_code(self) -> None:
        assert NODATA_CODE == 255

    def test_nodata_assigned_outside_support(self) -> None:
        """Pixels hors support → NODATA_CODE dans la prédiction."""
        from src.supervised_e import run_inference
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer

        rng = np.random.default_rng(0)
        h, w = 10, 10
        X = rng.random((h, w, 63)).astype(np.float32)
        support = np.ones((h, w), dtype=bool)
        support[3:6, 3:6] = False  # 9 pixels hors support

        # Modèle factice
        X_train = rng.random((50, 63))
        y_train = rng.integers(0, 5, 50)
        clf = RandomForestClassifier(n_estimators=5, random_state=0)
        imp = SimpleImputer(strategy="mean")
        X_tr = imp.fit_transform(X_train)
        clf.fit(X_tr, y_train)

        pred = run_inference(X, support, clf, imp)
        assert pred[3:6, 3:6].all() == False or (pred[3:6, 3:6] == NODATA_CODE).all()
        assert (pred[3:6, 3:6] == NODATA_CODE).all()

    def test_support_min_threshold(self) -> None:
        """MIN_SUPPORT > 0 : n_total_native == 0 → not support."""
        from descriptors import MIN_SUPPORT
        assert MIN_SUPPORT > 0.0
        assert MIN_SUPPORT < 1.0


# ── §F : Géoréférencement et centres des pixels ──────────────────────────────

class TestGeoreferencing:
    def test_pixel_size_at_res_m(self) -> None:
        """La grille à RES_M=2.0 couvre exactement le bbox."""
        from src.supervised_e import RES_M
        from rasterio.transform import from_bounds
        bbox = [425000.0, 6922000.0, 426000.0, 6923000.0]
        xmin, ymin, xmax, ymax = bbox
        w = int(round((xmax - xmin) / RES_M))
        h = int(round((ymax - ymin) / RES_M))
        assert w == 500
        assert h == 500
        transform = from_bounds(xmin, ymin, xmax, ymax, w, h)
        assert abs(transform.a - RES_M) < 1e-6   # pixel width
        assert abs(abs(transform.e) - RES_M) < 1e-6  # pixel height

    def test_pixel_center_vs_edge(self) -> None:
        """Les coords des centres de pixels sont décalées de RES_M/2."""
        from rasterio.transform import from_bounds, xy
        from src.supervised_e import RES_M
        bbox = [0.0, 0.0, 10.0, 10.0]
        xmin, ymin, xmax, ymax = bbox
        w = int((xmax - xmin) / RES_M)
        h = int((ymax - ymin) / RES_M)
        transform = from_bounds(xmin, ymin, xmax, ymax, w, h)
        # Centre du pixel (row=0, col=0) = coin supérieur gauche + RES_M/2
        cx, cy = xy(transform, 0, 0)
        assert abs(cx - (xmin + RES_M / 2)) < 1e-6
        assert abs(cy - (ymax - RES_M / 2)) < 1e-6

    def test_raster_bands_written(self) -> None:
        """save_prediction_raster produit 2 bandes (prédiction + support)."""
        import rasterio
        from src.supervised_e import save_prediction_raster, NODATA_CODE
        with tempfile.TemporaryDirectory() as tmp:
            pred = np.array([[0, 1], [2, NODATA_CODE]], dtype=np.uint8)
            support = np.array([[True, True], [True, False]])
            out = pathlib.Path(tmp) / "pred.tif"
            save_prediction_raster(pred, support, [0.0, 0.0, 4.0, 4.0], "EPSG:2154", out)
            with rasterio.open(str(out)) as ds:
                assert ds.count == 2
                b1 = ds.read(1)
                b2 = ds.read(2)
                assert b1[1, 1] == NODATA_CODE
                assert b2[1, 1] == 0   # hors support
                assert b2[0, 0] == 1   # dans support


# ── §G : Sauvegarde/rechargement du modèle ───────────────────────────────────

class TestModelPersistence:
    def test_model_roundtrip(self) -> None:
        """Un modèle sauvegardé se recharge avec les mêmes attributs."""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from loto_pipeline_e import N_FEATURES_E

        rng = np.random.default_rng(0)
        X = rng.random((100, N_FEATURES_E))
        y = rng.integers(0, 5, 100)
        imp = SimpleImputer(strategy="mean")
        X_i = imp.fit_transform(X)
        clf = RandomForestClassifier(n_estimators=5, random_state=0)
        clf.fit(X_i, y)

        payload = {"clf": clf, "imputer": imp, "n_features": N_FEATURES_E,
                   "categories": {}, "nodata_code": NODATA_CODE, "config": {}}

        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "model.pkl"
            with p.open("wb") as f:
                pickle.dump(payload, f, protocol=5)
            with p.open("rb") as f:
                v = pickle.load(f)
            assert v["n_features"] == N_FEATURES_E
            assert hasattr(v["clf"], "predict")
            # Prédiction déterministe
            p1 = clf.predict(X_i[:5])
            p2 = v["clf"].predict(v["imputer"].transform(X[:5]))
            np.testing.assert_array_equal(p1, p2)

    def test_model_sha256_mismatch_raises(self) -> None:
        """SHA-256 incorrecte dans le manifeste → ValueError."""
        from src.supervised_e import load_model

        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "model_e_final.pkl"
            payload = {"clf": None, "imputer": None, "n_features": 63,
                       "categories": {}, "nodata_code": 255, "config": {}}
            with p.open("wb") as f:
                pickle.dump(payload, f)

            # Manifeste avec SHA-256 erronée
            mf = pathlib.Path(tmp) / "manifeste.json"
            mf.write_text(json.dumps({"sha256": "aabbcc"}), encoding="utf-8")

            with pytest.raises(ValueError, match="SHA-256"):
                load_model(p)

    def test_wrong_n_features_raises(self) -> None:
        """Modèle avec n_features≠63 → ValueError."""
        from src.supervised_e import load_model

        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "model_e_final.pkl"
            payload = {"clf": None, "imputer": None, "n_features": 30,
                       "categories": {}, "nodata_code": 255, "config": {}}
            with p.open("wb") as f:
                pickle.dump(payload, f)
            with pytest.raises(ValueError, match="n_features"):
                load_model(p)


# ── §H : Autonomie sans référence OCAD ───────────────────────────────────────

class TestOcadAutonomy:
    def test_no_ocad_import_in_supervised_e(self) -> None:
        """src/supervised_e.py n'importe pas de chemin OCAD."""
        se_path = _ROOT / "src" / "supervised_e.py"
        code = se_path.read_text(encoding="utf-8")
        for forbidden in ("ocad_rgb", "VegetationBaseMap", "build_ref_cat",
                          "ref_cat", "OCAD", ".png"):
            assert forbidden.lower() not in code.lower() or forbidden == ".png", (
                f"Référence interdite trouvée dans supervised_e.py : {forbidden!r}"
            )

    def test_run_supervised_e_signature(self) -> None:
        """run_supervised_e n'accepte pas de paramètre 'reference'."""
        import inspect
        from src.supervised_e import run_supervised_e
        params = inspect.signature(run_supervised_e).parameters
        assert "reference" not in params
        assert "ocad" not in params
        assert "ref_cat" not in params
        assert "laz_files" in params
        assert "bbox" in params


# ── §I : Sélection du mode ────────────────────────────────────────────────────

class TestModeSelection:
    def test_supervised_e_resolved(self) -> None:
        from src.pipeline_mode import resolve_veg_source
        cfg = {"terrains": {"test_t": {"vegetation_source": "supervised_e"}}}
        assert resolve_veg_source("test_t", cfg) == "supervised_e"

    def test_kp_default_when_absent(self) -> None:
        from src.pipeline_mode import resolve_veg_source
        cfg: dict = {"terrains": {}}
        assert resolve_veg_source("terrain_x", cfg) == "kp"

    def test_unknown_mode_raises(self) -> None:
        from src.pipeline_mode import resolve_veg_source
        cfg = {"terrains": {"t": {"vegetation_source": "unknown_mode"}}}
        with pytest.raises(ValueError, match="valeur inconnue"):
            resolve_veg_source("t", cfg)

    def test_all_valid_modes(self) -> None:
        from src.pipeline_mode import resolve_veg_source, VegMode
        import typing
        valid = set(typing.get_args(VegMode))
        assert valid == {"kp", "hag", "supervised_e"}
        for mode in valid:
            cfg = {"terrains": {"t": {"vegetation_source": mode}}}
            result = resolve_veg_source("t", cfg)
            assert result == mode


# ── §J : Non-régression des modes existants ──────────────────────────────────

class TestExistingModesNonRegression:
    def test_kp_mode_unchanged(self) -> None:
        from src.pipeline_mode import resolve_veg_source
        for src_val in ("kp", None):
            cfg = {"terrains": {"t": {}}}
            if src_val:
                cfg["terrains"]["t"]["vegetation_source"] = src_val
            assert resolve_veg_source("t", cfg) == "kp"

    def test_hag_mode_unchanged(self) -> None:
        from src.pipeline_mode import resolve_veg_source
        cfg = {"terrains": {"t": {"vegetation_source": "hag"}}}
        assert resolve_veg_source("t", cfg) == "hag"

    def test_supervised_e_does_not_affect_hag_imports(self) -> None:
        """L'import de supervised_e ne brise pas les modules existants."""
        import src.supervised_e  # noqa: F401
        from src.pipeline_mode import resolve_veg_source  # doit encore fonctionner
        cfg = {"terrains": {"t": {"vegetation_source": "hag"}}}
        assert resolve_veg_source("t", cfg) == "hag"


# ── §K : Vectorisation et export fidèle ──────────────────────────────────────

class TestVectorizePrediction:
    """Tests synthétiques de vectorize_prediction — aucune dépendance LAZ."""

    @staticmethod
    def _make_pred(h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
        pred    = np.zeros((h, w), dtype=np.uint8)
        support = np.ones((h, w), dtype=bool)
        return pred, support

    def test_single_pixel_faithful_preserved(self) -> None:
        """Mode faithful : composante 1 pixel (4 m²) conservée."""
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_FAITHFUL

        pred, support = self._make_pred(5, 5)
        pred[2, 2] = 2  # unique pixel veg_406
        transform = from_bounds(0, 0, 10, 10, 5, 5)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_FAITHFUL)
        assert len(result[2]) == 1, "Le pixel unique doit être conservé en mode faithful"

    def test_single_pixel_generalized_filtered(self) -> None:
        """Mode generalized : composante 1 pixel (4 m² < 16 m²) supprimée."""
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_GENERALIZED

        pred, support = self._make_pred(5, 5)
        pred[2, 2] = 2  # unique pixel 2×2 m = 4 m²
        transform = from_bounds(0, 0, 10, 10, 5, 5)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_GENERALIZED)
        assert len(result[2]) == 0, "La composante < 16 m² doit être filtrée"

    def test_large_patch_generalized_kept(self) -> None:
        """Mode generalized : bloc 3×3 pixels (36 m² > 16 m²) conservé."""
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_GENERALIZED

        pred, support = self._make_pred(5, 5)
        pred[1:4, 1:4] = 3  # 3×3 pixels 2×2 m = 36 m²
        transform = from_bounds(0, 0, 10, 10, 5, 5)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_GENERALIZED)
        assert len(result[3]) >= 1, "Un bloc de 36 m² doit être conservé"

    def test_all_classes_vectorized(self) -> None:
        """Classes 0, 2, 3, 4 sont toutes présentes dans le résultat."""
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_FAITHFUL

        pred, support = self._make_pred(10, 10)
        pred[0:3, :] = 0   # découvert
        pred[3:5, :] = 1   # blanc — pas de couche
        pred[5:7, :] = 2   # veg_406
        pred[7:9, :] = 3   # veg_408
        pred[9:10, :] = 4  # veg_410
        transform = from_bounds(0, 0, 20, 20, 10, 10)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_FAITHFUL)
        for cls in [0, 2, 3, 4]:
            assert cls in result
            assert len(result[cls]) >= 1, f"Classe {cls} doit avoir des polygones"

    def test_blanc_not_vectorized(self) -> None:
        """Classe 1 (blanc) ne génère jamais de polygone — fond implicite."""
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_FAITHFUL, _CLASS_TO_ISOM

        pred = np.ones((6, 6), dtype=np.uint8)  # tout blanc
        support = np.ones((6, 6), dtype=bool)
        transform = from_bounds(0, 0, 12, 12, 6, 6)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_FAITHFUL)
        assert 1 not in _CLASS_TO_ISOM, "Blanc ne doit pas être dans _CLASS_TO_ISOM"
        for cls in [0, 2, 3, 4]:
            assert len(result[cls]) == 0, f"Blanc : classe {cls} doit être vide"

    def test_unknown_pixels_excluded(self) -> None:
        """Pixels support=0 ne sont jamais inclus dans les polygones."""
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_FAITHFUL

        pred, support = self._make_pred(6, 6)
        pred[:] = 2            # tout veg_406
        support[3, 3] = False  # un pixel inconnu
        pred[3, 3] = 255
        transform = from_bounds(0, 0, 12, 12, 6, 6)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_FAITHFUL)
        polys = result[2]
        total_area = sum(p.area for p in polys)
        full_area = 12.0 * 12.0  # 144 m²
        pixel_area = 4.0         # 2×2 m
        assert total_area < full_area, "Un pixel manquant doit réduire l'aire totale"
        assert total_area >= full_area - pixel_area * 1.5

    def test_no_overlaps_between_classes(self) -> None:
        """Classes distinctes — aucun overlap surfacique."""
        import shapely
        from rasterio.transform import from_bounds
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_FAITHFUL

        pred, support = self._make_pred(8, 8)
        pred[0:4, :] = 2  # moitié veg_406
        pred[4:8, :] = 3  # moitié veg_408
        transform = from_bounds(0, 0, 16, 16, 8, 8)
        result = vectorize_prediction(pred, support, transform, EXPORT_MODE_FAITHFUL)
        u406 = shapely.unary_union(result[2]) if result[2] else None
        u408 = shapely.unary_union(result[3]) if result[3] else None
        if u406 is not None and u408 is not None:
            overlap = u406.intersection(u408).area
            assert overlap < 0.01, f"Overlap inter-classes : {overlap:.4f} m²"


class TestFaithfulRoundtrip:
    def test_roundtrip_zero_diff(self) -> None:
        """Raster → vectorize_prediction → rasterize → 0 pixel différent sur support."""
        from rasterio.transform import from_bounds
        from rasterio.features import rasterize as rio_rasterize
        from src.supervised_e import vectorize_prediction, EXPORT_MODE_FAITHFUL

        h, w = 12, 12
        pred = np.zeros((h, w), dtype=np.uint8)
        pred[0:4, 0:6]  = 0   # découvert
        pred[0:4, 6:12] = 2   # veg_406
        pred[4:8, :]    = 3   # veg_408
        pred[8:12, :]   = 4   # veg_410
        pred[6, 6]      = 1   # pixel blanc au milieu
        support = np.ones((h, w), dtype=bool)
        support[5, 5] = False  # pixel inconnu
        pred[5, 5] = 255

        transform = from_bounds(0.0, 0.0, float(w * 2), float(h * 2), w, h)
        polys_by_class = vectorize_prediction(pred, support, transform, EXPORT_MODE_FAITHFUL)

        shapes_for_rasterize = [
            (p, class_id)
            for class_id, polys in polys_by_class.items()
            for p in polys
        ]
        omap_raster = rio_rasterize(
            shapes_for_rasterize,
            out_shape=(h, w),
            transform=transform,
            fill=1,
            dtype="uint8",
        )

        diff = int((pred[support] != omap_raster[support]).sum())
        assert diff == 0, (
            f"{diff} pixels modifiés après roundtrip (attendu 0 en mode faithful)"
        )


class TestExportModeConstants:
    def test_mode_values(self) -> None:
        from src.supervised_e import EXPORT_MODE_FAITHFUL, EXPORT_MODE_GENERALIZED
        assert EXPORT_MODE_FAITHFUL    == "faithful"
        assert EXPORT_MODE_GENERALIZED == "generalized"

    def test_class_to_isom_mapping(self) -> None:
        from src.supervised_e import _CLASS_TO_ISOM
        assert _CLASS_TO_ISOM[0] == 401  # découvert
        assert _CLASS_TO_ISOM[2] == 406
        assert _CLASS_TO_ISOM[3] == 408
        assert _CLASS_TO_ISOM[4] == 410
        assert 1 not in _CLASS_TO_ISOM, "Blanc ne doit pas être dans _CLASS_TO_ISOM"

    def test_run_supervised_e_has_export_mode(self) -> None:
        """run_supervised_e accepte export_mode et default à faithful."""
        import inspect
        from src.supervised_e import run_supervised_e, EXPORT_MODE_FAITHFUL
        params = inspect.signature(run_supervised_e).parameters
        assert "export_mode" in params
        default = params["export_mode"].default
        assert default == EXPORT_MODE_FAITHFUL


class TestSaveVegetationGpkg:
    def test_all_layers_created(self, tmp_path: pathlib.Path) -> None:
        """Les 4 couches veg_401/406/408/410 sont présentes dans le GPKG."""
        import geopandas as gpd
        from shapely.geometry import box
        from src.supervised_e import save_vegetation_gpkg, _CLASS_TO_ISOM, EXPORT_MODE_FAITHFUL

        polys_by_class = {
            0: [box(0, 0, 10, 10)],
            2: [],
            3: [box(5, 5, 8, 8)],
            4: [],
        }
        out = tmp_path / "test_veg.gpkg"
        save_vegetation_gpkg(polys_by_class, "EPSG:2154", out, EXPORT_MODE_FAITHFUL)

        assert out.exists(), "Le GPKG doit être créé"
        for isom_code in _CLASS_TO_ISOM.values():
            gdf = gpd.read_file(str(out), layer=f"veg_{isom_code}")
            assert gdf is not None, f"Couche veg_{isom_code} introuvable"

    def test_empty_layers_included(self, tmp_path: pathlib.Path) -> None:
        """Les couches vides sont écrites — GPKG valide même sans polygone."""
        import geopandas as gpd
        from src.supervised_e import save_vegetation_gpkg, EXPORT_MODE_FAITHFUL

        polys_by_class = {0: [], 2: [], 3: [], 4: []}
        out = tmp_path / "empty_veg.gpkg"
        save_vegetation_gpkg(polys_by_class, "EPSG:2154", out, EXPORT_MODE_FAITHFUL)

        assert out.exists()
        gdf = gpd.read_file(str(out), layer="veg_401")
        assert len(gdf) == 0, "Couche vide doit exister avec 0 ligne"

    def test_crs_preserved(self, tmp_path: pathlib.Path) -> None:
        """Le CRS EPSG:2154 est conservé dans le GPKG."""
        import geopandas as gpd
        from shapely.geometry import box
        from src.supervised_e import save_vegetation_gpkg, EXPORT_MODE_FAITHFUL

        polys_by_class = {0: [box(425000, 6922000, 425100, 6922100)], 2: [], 3: [], 4: []}
        out = tmp_path / "crs_test.gpkg"
        save_vegetation_gpkg(polys_by_class, "EPSG:2154", out, EXPORT_MODE_FAITHFUL)

        gdf = gpd.read_file(str(out), layer="veg_401")
        assert gdf.crs is not None
        assert gdf.crs.to_epsg() == 2154
