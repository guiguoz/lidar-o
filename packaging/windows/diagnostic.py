"""Diagnostic LidarO — vérifie l'environnement avant le test sur Windows propre.

Usage : appelé par LidarO_diagnostic.bat (double-clic).
Sortie : LIDAR_O_DIAGNOSTIC_<date>.txt sur le Bureau et en console.
Retour : 0 = tout OK, 1 = au moins un contrôle échoué.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import pathlib
import platform
import struct
import subprocess
import sys
import tempfile
import traceback

# ── Chemins relatifs à l'archive ────────────────────────────────────────────
# Ce script tourne depuis app/ (cd /d "%APP%" dans le lanceur).
# La structure attendue :
#   <ROOT>/
#     python/           ← env extrait
#     app/              ← cwd de ce script
#     models/
#     bin/
#     test_data/
_APP_DIR  = pathlib.Path(__file__).parent.parent  # diagnostic.py est dans app/scripts/
_ROOT     = _APP_DIR.parent                        # racine du paquet

MODEL_PATH     = _ROOT / "models" / "model_e_final.pkl"
MODEL_SHA256   = "48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5"
MODEL_REF_PREDS = [1, 1, 1, 1, 1]
MODEL_REF_P0    = [0.2532, 0.3606, 0.238, 0.0924, 0.0557]

PULLAUTA_PATH  = _ROOT / "bin" / "pullauta.exe"
LAZ_PATH       = _ROOT / "test_data" / "LHD_FXX_0500_6800_PTS_LAMB93_IGN69.copc.laz"
GPKG_PATH      = _ROOT / "test_data" / "test_bdtopo.gpkg"
PROJ_DATA      = _ROOT / "python" / "Library" / "share" / "proj"
GDAL_DATA      = _ROOT / "python" / "Library" / "share" / "gdal"

# ── Journal ──────────────────────────────────────────────────────────────────
_lines: list[str] = []

def _log(line: str = "") -> None:
    print(line)
    _lines.append(line)

def _ok(label: str, detail: str = "") -> None:
    _log(f"  [OK]  {label}" + (f" — {detail}" if detail else ""))

def _fail(label: str, detail: str = "") -> None:
    _log(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))

def _skip(label: str, reason: str = "") -> None:
    _log(f"  [SKIP] {label}" + (f" — {reason}" if reason else ""))

# ── Sections ─────────────────────────────────────────────────────────────────

def check_system() -> bool:
    _log("\n=== Système ===")
    ok = True
    _ok("Python", sys.version.replace("\n", " "))
    _ok("Exécutable", sys.executable)
    _ok("Plateforme", platform.platform())
    _ok("CWD", str(pathlib.Path.cwd()))
    _ok("ROOT paquet", str(_ROOT))

    # Vérifier que python.exe est bien dans le paquet (pas un Python système)
    py = pathlib.Path(sys.executable).resolve()
    expected_prefix = (_ROOT / "python").resolve()
    if py.is_relative_to(expected_prefix):
        _ok("Python paquet", "chemin dans python/ du paquet")
    else:
        _fail("Python paquet", f"inattendu : {py} — pas dans {expected_prefix}")
        ok = False

    return ok


def check_gdal_proj() -> bool:
    _log("\n=== GDAL / PROJ ===")
    ok = True

    if PROJ_DATA.exists():
        db = PROJ_DATA / "proj.db"
        _ok("PROJ_DATA", str(PROJ_DATA)) if db.exists() else _fail("proj.db", f"absent dans {PROJ_DATA}")
        ok = ok and db.exists()
    else:
        _fail("PROJ_DATA", f"dossier absent : {PROJ_DATA}")
        ok = False

    if GDAL_DATA.exists():
        _ok("GDAL_DATA", str(GDAL_DATA))
    else:
        _fail("GDAL_DATA", f"dossier absent : {GDAL_DATA}")
        ok = False

    gdal_env = os.environ.get("GDAL_DATA", "")
    proj_env = os.environ.get("PROJ_DATA", os.environ.get("PROJ_LIB", ""))
    _ok("GDAL_DATA env", gdal_env or "(non défini — rasterio utilisera ses valeurs intégrées)")
    _ok("PROJ_DATA env", proj_env or "(non défini)")

    return ok


def check_imports() -> bool:
    _log("\n=== Imports Python ===")
    ok = True
    pkgs = [
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("sklearn", "sklearn"),
        ("rasterio", "rasterio"),
        ("pdal", "pdal"),
        ("geopandas", "geopandas"),
        ("pyogrio", "pyogrio"),
        ("PIL (Pillow)", "PIL"),
        ("ezdxf", "ezdxf"),
        ("yaml (PyYAML)", "yaml"),
        ("tkinter", "tkinter"),
        ("osgeo.gdal", "osgeo.gdal"),
        ("osgeo.osr", "osgeo.osr"),
    ]
    import importlib, warnings
    for label, mod in pkgs:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "?")
            _ok(label, ver)
        except Exception as e:
            _fail(label, str(e))
            ok = False
    return ok


def check_rasterio() -> bool:
    _log("\n=== Rasterio — écriture/lecture raster ===")
    try:
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from rasterio.crs import CRS
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "test.tif"
            arr = np.ones((50, 50), dtype=np.float32) * 0.5
            t = from_origin(500000, 6801000, 1.0, 1.0)
            with rasterio.open(p, "w", driver="GTiff", height=50, width=50,
                               count=1, dtype="float32",
                               crs=CRS.from_epsg(2154), transform=t) as ds:
                ds.write(arr, 1)
            with rasterio.open(p) as ds:
                epsg = ds.crs.to_epsg()
                val = float(ds.read(1)[25, 25])
        if epsg == 2154 and abs(val - 0.5) < 1e-6:
            _ok("Rasterio write/read EPSG:2154", f"val={val:.1f}")
            return True
        else:
            _fail("Rasterio", f"epsg={epsg} val={val}")
            return False
    except Exception as e:
        _fail("Rasterio", traceback.format_exc(limit=3))
        return False


def check_pdal() -> bool:
    _log("\n=== PDAL — lecture LAZ ===")
    if not LAZ_PATH.exists():
        _skip("PDAL", f"test_data/LHD_FXX_0500_6800_PTS_LAMB93_IGN69.copc.laz absent")
        return True  # non bloquant si fichier absent
    try:
        import pdal, json as _json
        pipeline = pdal.Pipeline(_json.dumps({
            "pipeline": [
                {"type": "readers.copc", "filename": str(LAZ_PATH), "count": 200},
            ]
        }))
        n = pipeline.execute()
        pts = pipeline.arrays[0]
        z_min, z_max = float(pts["Z"].min()), float(pts["Z"].max())
        _ok("PDAL COPC", f"{n} pts lus, Z={z_min:.0f}–{z_max:.0f} m")
        return True
    except Exception as e:
        _fail("PDAL", traceback.format_exc(limit=3))
        return False


def check_gpkg() -> bool:
    _log("\n=== GPKG — lecture via pyogrio ===")
    if not GPKG_PATH.exists():
        _skip("GPKG", "test_data/test_bdtopo.gpkg absent")
        return True
    try:
        import geopandas as gpd
        import pyogrio
        layers = pyogrio.list_layers(str(GPKG_PATH))
        gdf = gpd.read_file(str(GPKG_PATH), layer=layers[0][0], engine="pyogrio")
        epsg = gdf.crs.to_epsg() if gdf.crs else None
        _ok("GPKG pyogrio", f"{len(layers)} couches, couche 0 = {layers[0][0]}, epsg={epsg}")
        return True
    except Exception as e:
        _fail("GPKG", traceback.format_exc(limit=3))
        return False


def check_model() -> bool:
    _log("\n=== Modèle RandomForest ===")
    if not MODEL_PATH.exists():
        _fail("Modèle", f"absent : {MODEL_PATH}")
        return False
    try:
        sha = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
        if sha == MODEL_SHA256:
            _ok("SHA-256", sha[:16] + "…")
        else:
            _fail("SHA-256", f"obtenu={sha[:16]}… attendu={MODEL_SHA256[:16]}…")
            return False

        import pickle, warnings, numpy as np
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            model = pickle.load(open(MODEL_PATH, "rb"))
            sk_warns = [str(x.message) for x in w
                        if "InconsistentVersionWarning" in str(x.category)
                        or "version" in str(x.message).lower()]
        if sk_warns:
            _fail("Version sklearn", "; ".join(sk_warns))
            return False
        else:
            _ok("Chargement", "sans avertissement de version")

        rng = np.random.default_rng(42)
        X = rng.normal(size=(5, 63)).astype(np.float32)
        X[1, :] = np.nan
        X_imp = model["imputer"].transform(X)
        preds = model["clf"].predict(X_imp).tolist()
        p0 = [round(float(p), 4) for p in model["clf"].predict_proba(X_imp)[0]]

        if preds == MODEL_REF_PREDS:
            _ok("Prédictions", str(preds))
        else:
            _fail("Prédictions", f"obtenu={preds} attendu={MODEL_REF_PREDS}")
            return False

        if p0 == MODEL_REF_P0:
            _ok("Probabilités ligne 0", str(p0))
        else:
            _fail("Probabilités ligne 0", f"obtenu={p0} attendu={MODEL_REF_P0}")
            return False

        return True
    except Exception as e:
        _fail("Modèle", traceback.format_exc(limit=5))
        return False


def check_pullauta() -> bool:
    _log("\n=== Pullauta (KP) ===")
    if not PULLAUTA_PATH.exists():
        _fail("pullauta.exe", f"absent : {PULLAUTA_PATH}")
        return False
    try:
        result = subprocess.run(
            [str(PULLAUTA_PATH), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        out = (result.stdout + result.stderr).strip()
        _ok("pullauta.exe", out[:80] if out else f"exit={result.returncode}")
        return True
    except Exception as e:
        _fail("pullauta.exe", str(e))
        return False


def check_supervised_e() -> bool:
    _log("\n=== supervised_e — pipeline inférence ===")
    if not MODEL_PATH.exists():
        _skip("supervised_e", "modèle absent (voir section modèle ci-dessus)")
        return True  # check_model aura déjà signalé l'erreur

    # Ajouter app/ à sys.path pour que `import src.supervised_e` fonctionne
    _app_str = str(_APP_DIR)
    if _app_str not in sys.path:
        sys.path.insert(0, _app_str)

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import src.supervised_e as se
        _ok("import src.supervised_e", "")
    except Exception:
        _fail("import src.supervised_e", traceback.format_exc(limit=6))
        return False

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = se.load_model(MODEL_PATH)
        _ok("load_model", f"n_features={model.get('n_features', '?')}")
    except Exception:
        _fail("load_model", traceback.format_exc(limit=3))
        return False

    try:
        import numpy as np
        H, W = 4, 4
        rng = np.random.default_rng(7)
        X_grid = rng.normal(size=(H, W, se.N_FEATURES_E_TOTAL)).astype(np.float32)
        support = np.ones((H, W), dtype=bool)
        support[0, 0] = False  # simuler un pixel hors couverture LiDAR

        pred = se.run_inference(X_grid, support, model["clf"], model["imputer"])
        assert pred.shape == (H, W), f"shape {pred.shape}"
        assert pred.dtype == np.uint8
        assert pred[0, 0] == se.NODATA_CODE, (
            f"pixel hors support = {pred[0, 0]} (attendu {se.NODATA_CODE})"
        )
        n_valid = int((pred != se.NODATA_CODE).sum())
        _ok("run_inference", f"grille {H}×{W}, {n_valid}/{H*W - 1} pixels classifiés")
    except Exception:
        _fail("run_inference", traceback.format_exc(limit=5))
        return False

    try:
        import numpy as np
        from rasterio.transform import from_bounds
        transform = from_bounds(500000.0, 6800000.0, 500008.0, 6800008.0, W, H)
        polys = se.vectorize_prediction(pred, support, transform, se.EXPORT_MODE_FAITHFUL)
        n_polys = sum(len(v) for v in polys.values())
        _ok("vectorize_prediction", f"{n_polys} polygones, classes={sorted(polys.keys())}")
    except Exception:
        _fail("vectorize_prediction", traceback.format_exc(limit=5))
        return False

    try:
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "veg_diag.gpkg"
            se.save_vegetation_gpkg(polys, "EPSG:2154", out, se.EXPORT_MODE_FAITHFUL)
            size = out.stat().st_size
        _ok("save_vegetation_gpkg", f"{size} octets écrits")
    except Exception:
        _fail("save_vegetation_gpkg", traceback.format_exc(limit=5))
        return False

    return True


def check_osgeo() -> bool:
    _log("\n=== osgeo.osr — reprojection Lambert 93 ===")
    try:
        from osgeo import osr
        srs = osr.SpatialReference()
        rc = srs.ImportFromEPSG(2154)
        if rc != 0:
            _fail("osgeo.osr ImportFromEPSG(2154)", f"code retour {rc}")
            return False
        proj4 = srs.ExportToProj4()
        _ok("osgeo.osr EPSG:2154", proj4[:60])
        return True
    except Exception:
        _fail("osgeo.osr", traceback.format_exc(limit=3))
        return False


def check_config() -> bool:
    _log("\n=== Configuration utilisateur ===")
    ok = True
    # config_default.yaml dans app/
    default_cfg = _APP_DIR / "config_default.yaml"
    if default_cfg.exists():
        _ok("config_default.yaml", str(default_cfg))
    else:
        _fail("config_default.yaml", f"absent : {default_cfg}")
        ok = False

    # %APPDATA%\LidarO\ — doit être créable sans droits admin
    appdata = pathlib.Path(os.environ.get("APPDATA", "~")).expanduser() / "LidarO"
    try:
        appdata.mkdir(parents=True, exist_ok=True)
        (appdata / "_diag_write_test.tmp").write_text("ok")
        (appdata / "_diag_write_test.tmp").unlink()
        _ok("APPDATA\\LidarO\\", str(appdata) + " (inscriptible sans admin)")
    except Exception as e:
        _fail("APPDATA\\LidarO\\", str(e))
        ok = False

    return ok


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log("=" * 60)
    _log(f"  LidarO — Diagnostic  {ts}")
    _log("=" * 60)

    results = {
        "système":      check_system(),
        "GDAL/PROJ":    check_gdal_proj(),
        "imports":      check_imports(),
        "rasterio":     check_rasterio(),
        "PDAL":         check_pdal(),
        "GPKG":         check_gpkg(),
        "modèle":       check_model(),
        "supervised_e": check_supervised_e(),
        "osgeo":        check_osgeo(),
        "pullauta":     check_pullauta(),
        "config":       check_config(),
    }

    _log("\n" + "=" * 60)
    _log("  RÉSUMÉ")
    _log("=" * 60)
    all_ok = True
    for name, passed in results.items():
        status = "OK  " if passed else "FAIL"
        _log(f"  [{status}]  {name}")
        if not passed:
            all_ok = False

    _log("")
    if all_ok:
        _log("  STATUT GLOBAL : OK — environnement opérationnel")
    else:
        _log("  STATUT GLOBAL : ÉCHEC — voir détails ci-dessus")
    _log("=" * 60)

    # Écriture du journal — Bureau
    log_dir = pathlib.Path.home() / "Desktop"
    if not log_dir.exists():
        log_dir = pathlib.Path(tempfile.gettempdir())
    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"LIDAR_O_DIAGNOSTIC_{ts_str}.txt"
    log_content = "\n".join(_lines)
    try:
        log_file.write_text(log_content, encoding="utf-8")
        print(f"\nJournal : {log_file}")
    except Exception as e:
        print(f"\nImpossible d'écrire le journal : {e}")

    # Journal Sandbox — C:\sandbox_logs\ (dossier partagé R/W dans Windows Sandbox)
    sandbox_log_dir = pathlib.Path(r"C:\sandbox_logs")
    if sandbox_log_dir.exists() and sandbox_log_dir.is_dir():
        sl = sandbox_log_dir / f"LIDAR_O_DIAGNOSTIC_{ts_str}.txt"
        try:
            sl.write_text(log_content, encoding="utf-8")
            print(f"Journal Sandbox  : {sl}")
        except Exception as e:
            print(f"Impossible d'écrire journal Sandbox : {e}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
