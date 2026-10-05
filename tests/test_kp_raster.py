"""Tests unitaires pour src/kp_raster.py.

Aucune donnée réelle requise : tous les tests opèrent sur des tableaux
numpy ou des fichiers temporaires synthétiques.

Couverture :
  - kp_green_rgb   (formule palette)
  - read_ini_vege_params
  - _labels_from_gray / _labels_from_rgb
  - mosaic (placement, bbox, régression clipping)
  - shade_to_dn
"""
from __future__ import annotations

import pathlib
import textwrap

import numpy as np
import pytest

from src.kp_raster import (
    KP_FIRST_GREEN,
    KP_NO_DATA,
    KP_YELLOW,
    Tile,
    _UNMATCHED,
    _labels_from_gray,
    _labels_from_rgb,
    kp_green_rgb,
    mosaic,
    read_ini_vege_params,
    shade_to_dn,
)

# ── kp_green_rgb ──────────────────────────────────────────────────────────────

def test_kp_green_rgb_lightest_shade_is_tone():
    """shade i=0 : R=B=tone, G=254."""
    shades = kp_green_rgb(n_shades=11, lightgreentone=200)
    assert shades[0] == (200, 254, 200)


def test_kp_green_rgb_darkest_shade():
    """shade i=N-1 : R=B=0, G=254-74=180."""
    shades = kp_green_rgb(n_shades=11, lightgreentone=200)
    assert shades[-1] == (0, 180, 0)


def test_kp_green_rgb_count():
    shades = kp_green_rgb(n_shades=11, lightgreentone=200)
    assert len(shades) == 11


def test_kp_green_rgb_tone160():
    """Vérifie les valeurs exactes pour la config Grimbosq (tone=160, n=11)."""
    shades = kp_green_rgb(n_shades=11, lightgreentone=160)
    assert shades[0] == (160, 254, 160)
    assert shades[-1] == (0, 180, 0)
    # i=1 : rb = int(160 - 160/10) = int(144) = 144, g = int(254 - 7.4) = 246
    r, g, b = shades[1]
    assert r == b == 144
    assert g == 246


def test_kp_green_rgb_single_shade():
    shades = kp_green_rgb(n_shades=1, lightgreentone=160)
    assert shades == [(160, 254, 160)]


# ── read_ini_vege_params ──────────────────────────────────────────────────────

def test_read_ini_missing_returns_defaults():
    result = read_ini_vege_params(None)
    assert result["n_shades"] == 11
    assert result["lightgreentone"] == 200
    assert result["vege_bitmode"] is False
    assert result["ini"] is None


def test_read_ini_parses_greenshades(tmp_path):
    ini = tmp_path / "pullauta.ini"
    ini.write_text(textwrap.dedent("""\
        greenshades=0.2|0.35|0.5|0.7|1.3|2.6|4|99|99|99|99
        lightgreentone=160
        vege_bitmode=1
    """), encoding="utf-8")
    result = read_ini_vege_params(ini)
    assert result["n_shades"] == 11
    assert result["lightgreentone"] == 160
    assert result["vege_bitmode"] is True


def test_read_ini_nonexistent_path_returns_defaults(tmp_path):
    result = read_ini_vege_params(tmp_path / "absent.ini")
    assert result["n_shades"] == 11


# ── _labels_from_gray ─────────────────────────────────────────────────────────

def test_labels_from_gray_passthrough():
    params = {"n_shades": 7, "lightgreentone": 160}
    arr = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8]], dtype=np.uint8)
    result = _labels_from_gray(arr, params, pathlib.Path("test.png"))
    np.testing.assert_array_equal(result, arr)


def test_labels_from_gray_overflow_raises():
    params = {"n_shades": 7, "lightgreentone": 160}
    # max_expected = 2 + 7 - 1 = 8 ; on met 9
    arr = np.array([[0, 1, 2, 9]], dtype=np.uint8)
    with pytest.raises(ValueError, match="raster bit KP"):
        _labels_from_gray(arr, params, pathlib.Path("bad.png"))


# ── _labels_from_rgb ──────────────────────────────────────────────────────────

def test_labels_from_rgb_exact_palette_match():
    """Chaque couleur exacte de la palette est correctement décodée."""
    params = {"n_shades": 3, "lightgreentone": 200}
    # Couleurs attendues : (200,254,200), (100,217,100), (0,180,0)
    shades = kp_green_rgb(3, 200)
    rgb_img = np.array(
        [[[255, 255, 255],           # blanc → 0
          [255, 219, 166],           # jaune → 1
          list(shades[0]),           # vert 0 → 2
          list(shades[1]),           # vert 1 → 3
          list(shades[2])]],         # vert 2 → 4
        dtype=np.uint8
    )
    labels, unmatched = _labels_from_rgb(rgb_img, params, pathlib.Path("t.png"))
    assert unmatched == 0
    expected = np.array([[KP_NO_DATA, KP_YELLOW, 2, 3, 4]], dtype=np.uint8)
    np.testing.assert_array_equal(labels, expected)


def test_labels_from_rgb_unknown_color_sets_unmatched(caplog):
    """Couleur inconnue → pixel _UNMATCHED et warning loggé."""
    import logging
    params = {"n_shades": 3, "lightgreentone": 200}
    rgb_img = np.array([[[10, 20, 30]]], dtype=np.uint8)  # inconnue
    with caplog.at_level(logging.WARNING, logger="src.kp_raster"):
        labels, unmatched = _labels_from_rgb(rgb_img, params, pathlib.Path("t.png"))
    assert unmatched == 1
    assert labels[0, 0] == _UNMATCHED


# ── mosaic ────────────────────────────────────────────────────────────────────

def _make_tile(labels: np.ndarray, west: float, north: float, res: float = 1.0) -> Tile:
    return Tile(path=pathlib.Path("t.png"), labels=labels, res_m=res, west=west, north=north)


def test_mosaic_single_tile_identity():
    lab = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    canvas, res, w, n = mosaic([_make_tile(lab, 0.0, 2.0)])
    assert res == 1.0
    assert w == 0.0
    assert n == 2.0
    np.testing.assert_array_equal(canvas, lab)


def test_mosaic_two_tiles_side_by_side():
    """Deux tuiles adjacentes : canal de jonction correct."""
    left = np.full((2, 3), 1, dtype=np.uint8)
    right = np.full((2, 3), 2, dtype=np.uint8)
    t_left = _make_tile(left, 0.0, 2.0)
    t_right = _make_tile(right, 3.0, 2.0)
    canvas, res, w, n = mosaic([t_left, t_right])
    assert canvas.shape == (2, 6)
    assert np.all(canvas[:, :3] == 1)
    assert np.all(canvas[:, 3:] == 2)


def test_mosaic_bbox_no_clip():
    """bbox contenant la tuile entière → résultat identique sans bbox."""
    lab = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
    t = _make_tile(lab, 10.0, 20.0)
    canvas_full, _, _, _ = mosaic([t])
    canvas_bbox, _, _, _ = mosaic([t], bbox=(10.0, 18.0, 13.0, 20.0))
    np.testing.assert_array_equal(canvas_full, canvas_bbox)


def test_mosaic_bbox_east_clip():
    """bbox plus étroite à l'est : les colonnes est sont éliminées."""
    lab = np.arange(6, dtype=np.uint8).reshape(1, 6)  # [0,1,2,3,4,5]
    t = _make_tile(lab, 0.0, 1.0)
    canvas, _, w, _ = mosaic([t], bbox=(0.0, 0.0, 4.0, 1.0))
    assert canvas.shape == (1, 4)
    np.testing.assert_array_equal(canvas[0], [0, 1, 2, 3])


def test_mosaic_bbox_west_overflow_regression():
    """Régression : tuile débordant à l'ouest de la bbox.

    Bug d'origine : lab[:h, :w] ignorait le décalage col_src dans la tuile,
    écrivant les premières colonnes de la tuile là où les colonnes centrales
    étaient attendues.
    """
    # Tuile : 10 colonnes, labels = indice de colonne [0,1,2,...,9]
    lab = np.tile(np.arange(10, dtype=np.uint8), (2, 1))
    t = _make_tile(lab, west=0.0, north=2.0)

    # bbox [3, 0, 7, 2] : on veut les colonnes 3-6 de la tuile
    canvas, res, west_out, _ = mosaic([t], bbox=(3.0, 0.0, 7.0, 2.0))

    assert west_out == 3.0
    assert canvas.shape == (2, 4)
    # Sans le correctif, canvas[0] = [0,1,2,3] (colonnes du début de la tuile).
    # Avec le correctif, canvas[0] = [3,4,5,6] (colonnes 3-6 de la tuile).
    np.testing.assert_array_equal(canvas[0], [3, 4, 5, 6])


def test_mosaic_bbox_north_overflow_regression():
    """Régression : tuile débordant au nord de la bbox."""
    # Tuile : 4 lignes, labels = indice de ligne sur chaque colonne
    lab = np.tile(np.arange(4, dtype=np.uint8).reshape(4, 1), (1, 2))
    # t.north=4, tuile couvre y=[0,4] ; bbox [0, 1, 2, 3] → lignes 1-2 de la tuile
    t = _make_tile(lab, west=0.0, north=4.0)

    canvas, _, _, north_out = mosaic([t], bbox=(0.0, 1.0, 2.0, 3.0))

    assert north_out == 3.0
    assert canvas.shape == (2, 2)
    np.testing.assert_array_equal(canvas[:, 0], [1, 2])


def test_mosaic_bbox_disjoint_raises():
    lab = np.ones((2, 2), dtype=np.uint8)
    t = _make_tile(lab, 0.0, 2.0)
    with pytest.raises(ValueError):
        mosaic([t], bbox=(100.0, 100.0, 200.0, 200.0))


# ── shade_to_dn ───────────────────────────────────────────────────────────────

def test_shade_to_dn_basic_mapping():
    labels = np.array([[0, KP_YELLOW, 2, 3, 4]], dtype=np.uint8)
    mapping = {2: 406, 3: 406, 4: 408}
    out, counts = shade_to_dn(labels, mapping)
    assert out[0, 0] == 0    # blanc
    assert out[0, 1] == 0    # jaune ignoré
    assert out[0, 2] == 85   # 406
    assert out[0, 3] == 85   # 406
    assert out[0, 4] == 170  # 408
    assert counts == {406: 2, 408: 1}


def test_shade_to_dn_zero_code_skipped():
    """mapping code=0 : la teinte reste blanche, pas d'erreur."""
    labels = np.array([[2]], dtype=np.uint8)
    out, counts = shade_to_dn(labels, {2: 0})
    assert out[0, 0] == 0
    assert counts == {}


def test_shade_to_dn_invalid_isom_raises():
    labels = np.array([[2]], dtype=np.uint8)
    with pytest.raises(ValueError, match="moteur de généralisation"):
        shade_to_dn(labels, {2: 999})


def test_shade_to_dn_unmatched_sentinel_raises():
    """_UNMATCHED dans les labels → erreur explicite avant toute écriture."""
    labels = np.array([[_UNMATCHED]], dtype=np.uint8)
    with pytest.raises(ValueError, match="palette KP attendue"):
        shade_to_dn(labels, {2: 406})


def test_shade_to_dn_returns_per_class_counts():
    labels = np.array([[2, 2, 3, 4]], dtype=np.uint8)
    _, counts = shade_to_dn(labels, {2: 406, 3: 408, 4: 410})
    assert counts[406] == 2
    assert counts[408] == 1
    assert counts[410] == 1
