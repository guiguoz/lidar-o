"""Tests unitaires de src/omapmaker_ref.py — tous sans PDAL.

L'import en tête de fichier est lui-même un garde-fou : si les fonctions de
calcul deviennent inaccessibles sans PDAL, ce module échoue à la collection.
"""
import math
import pathlib
import subprocess
import sys
import textwrap

import numpy as np
import pytest
import rasterio

from src.omapmaker_ref import _classify, _finalize_dtm, _grid, _ndvd, _write_tif


# ── Grille ────────────────────────────────────────────────────────────────────

def test_grid_pixel_size_exact() -> None:
    """bbox non multiple de 0,5 m → pixel exactement 0,5 m sur les deux axes."""
    bbox = (100.0, 200.0, 100.7, 200.9)  # 0.7 m × 0.9 m → 2 × 2 px
    rows, cols, transform = _grid(bbox)
    assert abs(transform.a - 0.5) < 1e-9, f"pixel x={transform.a}"
    assert abs(abs(transform.e) - 0.5) < 1e-9, f"pixel y={abs(transform.e)}"


def test_grid_covers_bbox() -> None:
    """La grille couvre intégralement la bbox d'origine."""
    xmin, ymin, xmax, ymax = 100.0, 200.0, 100.7, 200.9
    rows, cols, transform = _grid((xmin, ymin, xmax, ymax))
    # coin SO = (xmin, ymin) conservé
    assert transform.c == pytest.approx(xmin)
    # ymax de la grille = transform.f (convention rasterio : y haut du pixel 0)
    assert transform.f >= ymax - 1e-9
    # xmax de la grille
    grid_xmax = transform.c + cols * transform.a
    assert grid_xmax >= xmax - 1e-9


def test_grid_dimensions_match_extended_extent() -> None:
    """cols et rows correspondent à l'extension exacte en multiples de _RES_M."""
    from src.omapmaker_ref import _RES_M
    xmin, ymin, xmax, ymax = 0.0, 0.0, 1.3, 2.7
    rows, cols, transform = _grid((xmin, ymin, xmax, ymax))
    assert cols == math.ceil((xmax - xmin) / _RES_M)
    assert rows == math.ceil((ymax - ymin) / _RES_M)


# ── DTM ───────────────────────────────────────────────────────────────────────

def test_finalize_dtm_all_nonfinite_raises() -> None:
    """DTM entièrement non fini → RuntimeError explicite."""
    dtm = np.full((4, 4), np.inf, dtype=np.float32)
    with pytest.raises(RuntimeError, match="Aucun point sol"):
        _finalize_dtm(dtm)


def test_finalize_dtm_fills_holes() -> None:
    """DTM avec trous (inf et NaN) → tous comblés, aucune valeur non finie."""
    dtm = np.array([[1.0, np.inf], [np.nan, 2.0]], dtype=np.float32)
    _finalize_dtm(dtm)
    assert np.isfinite(dtm).all(), f"Valeurs non finies restantes : {dtm}"


# ── Écriture rasters ──────────────────────────────────────────────────────────

def _simple_transform():
    from rasterio.transform import from_bounds
    return from_bounds(0, 0, 1, 1, 2, 2)


def test_write_tif_nan_replaced_by_nodata(tmp_path: pathlib.Path) -> None:
    """Float avec NaN + nodata=-9999 → NaN remplacé, tag NoData correct."""
    arr = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
    out = tmp_path / "test.tif"
    _write_tif(arr, out, _simple_transform(), "EPSG:2154", nodata=-9999.0)
    with rasterio.open(out) as src:
        data = src.read(1)
        nd = src.nodata
    assert nd == pytest.approx(-9999.0), f"nodata={nd}"
    assert not np.any(np.isnan(data)), "NaN encore présents"
    assert data[0, 1] == pytest.approx(-9999.0), f"pixel NaN={data[0, 1]}"


def test_write_tif_uint16_no_nodata(tmp_path: pathlib.Path) -> None:
    """uint16 sans nodata → aucun tag NoData, valeurs 0/406/408/410 préservées."""
    arr = np.array([[0, 406], [408, 410]], dtype=np.uint16)
    out = tmp_path / "cls.tif"
    _write_tif(arr, out, _simple_transform(), "EPSG:2154")
    with rasterio.open(out) as src:
        data = src.read(1)
        nd = src.nodata
    assert nd is None, f"nodata inattendu : {nd}"
    assert list(np.unique(data)) == [0, 406, 408, 410]


def test_write_tif_inf_not_silently_converted(tmp_path: pathlib.Path) -> None:
    """Un +inf flottant sans nodata passe tel quel dans le fichier (non converti)."""
    arr = np.array([[1.0, np.inf], [3.0, 4.0]], dtype=np.float32)
    out = tmp_path / "inf.tif"
    _write_tif(arr, out, _simple_transform(), "EPSG:2154")
    with rasterio.open(out) as src:
        data = src.read(1)
    assert np.isinf(data[0, 1]), f"inf converti en {data[0, 1]}"


# ── Import sans PDAL ──────────────────────────────────────────────────────────

def test_import_without_pdal() -> None:
    """src.omapmaker_ref importable dans un processus où pdal est bloqué."""
    script = textwrap.dedent("""
        import sys
        sys.modules["pdal"] = None
        import src.omapmaker_ref
        print("ok")
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(pathlib.Path(__file__).parent.parent),
    )
    assert result.returncode == 0, (
        f"Import échoué (rc={result.returncode}):\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ok" in result.stdout
