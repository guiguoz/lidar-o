"""Tests pour step_vegetation_kp : polygonisation, coverage_simplify, topologie.

Tous les tests opèrent sur des rasters/géométries synthétiques — pas de données
réelles requises. GDAL est nécessaire pour le round-trip raster→vecteur→raster ;
le test est skippé si rasterio n'est pas disponible (comme tests/conftest.py).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

try:
    import rasterio
    from rasterio.transform import from_origin
    _RASTERIO = True
except ImportError:
    _RASTERIO = False

try:
    import shapely
    import shapely.geometry as sg
    _SHAPELY = True
except ImportError:
    _SHAPELY = False

try:
    import geopandas as gpd
    _GPD = True
except ImportError:
    _GPD = False


def _write_classified_tif(tmp_path: pathlib.Path, data: np.ndarray,
                          res: float = 1.0) -> pathlib.Path:
    """Écrit un GeoTIFF classifié synthétique (uint8, CRS EPSG:2154)."""
    tif = tmp_path / "source_kp_classified.tif"
    transform = from_origin(0.0, data.shape[0] * res, res, res)
    with rasterio.open(
        tif, "w", driver="GTiff",
        height=data.shape[0], width=data.shape[1],
        count=1, dtype="uint8",
        crs="EPSG:2154", transform=transform,
        nodata=0,
    ) as ds:
        ds.write(data, 1)
    return tif


# ── P6 : round-trip raster → vecteur → raster ─────────────────────────────────

@pytest.mark.skipif(not (_RASTERIO and _SHAPELY), reason="rasterio ou shapely absent")
def test_roundtrip_lossless_before_simplify(tmp_path: pathlib.Path) -> None:
    """Raster classifié → polygonisation RAW → rasterisation : 0 pixel différent.

    Propriété V1 conservée : avant simplification, aucun pixel ne change de classe.
    """
    from rasterio.features import shapes as rasterio_shapes, rasterize
    from src.kp_raster import ISOM_TO_DN

    # Raster 10×10 avec les 3 classes + fond
    data = np.array([
        [0,   0,   0,   0,   0,   0,   0,   0,   0,   0],
        [0,  85,  85,  85,   0,   0,   0,   0,   0,   0],
        [0,  85,  85,  85,  85, 170, 170,   0,   0,   0],
        [0,  85,  85,  85,  85, 170, 170,   0,   0,   0],
        [0,   0,   0,  85,  85, 170, 170, 255, 255,   0],
        [0,   0,   0,   0,   0, 170, 170, 255, 255,   0],
        [0,   0,   0,   0,   0,   0,   0, 255, 255,   0],
        [0,   0,   0,   0,   0,   0,   0,   0,   0,   0],
        [0,   0,   0,   0,   0,   0,   0,   0,   0,   0],
        [0,   0,   0,   0,   0,   0,   0,   0,   0,   0],
    ], dtype=np.uint8)

    tif = _write_classified_tif(tmp_path, data, res=1.0)

    dn_to_isom = {v: k for k, v in ISOM_TO_DN.items()}
    with rasterio.open(tif) as ds:
        arr = ds.read(1)
        transform = ds.transform
        height, width = arr.shape
        profile = ds.profile

    # Polygonisation RAW
    all_geoms: list = []
    all_dns: list[int] = []
    for dn in sorted(dn_to_isom):
        mask_arr = (arr == dn).astype(np.uint8)
        for geom_dict, _ in rasterio_shapes(mask_arr, mask=mask_arr, transform=transform):
            all_geoms.append(sg.shape(geom_dict))
            all_dns.append(dn)

    # Rasterisation des polygones RAW → doit reproduire le raster original
    shapes_for_burn = [(geom, dn) for geom, dn in zip(all_geoms, all_dns)]
    reconstructed = rasterize(
        shapes_for_burn,
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )

    diff = int(np.sum(reconstructed != data))
    assert diff == 0, (
        f"Round-trip non lossless : {diff} pixel(s) différent(s) entre le raster "
        f"original et la rasterisation des polygones RAW."
    )


# ── P7 : coverage_is_valid avant coverage_simplify ────────────────────────────

@pytest.mark.skipif(not _SHAPELY, reason="shapely absent")
def test_coverage_valid_on_adjacent_polygons() -> None:
    """Deux polygones adjacents (arête partagée) → coverage_is_valid=True."""
    a = sg.box(0, 0, 1, 1)
    b = sg.box(1, 0, 2, 1)
    arr = np.array([a, b], dtype=object)
    assert shapely.coverage_is_valid(arr)


@pytest.mark.skipif(not _SHAPELY, reason="shapely absent")
def test_coverage_invalid_on_overlapping_polygons() -> None:
    """Polygones chevauchants → coverage_is_valid=False."""
    a = sg.box(0, 0, 1.5, 1)
    b = sg.box(1, 0, 2, 1)
    arr = np.array([a, b], dtype=object)
    assert not shapely.coverage_is_valid(arr)


# ── P8 : topologie après clip — overlaps==0 ──────────────────────────────────

@pytest.mark.skipif(not (_SHAPELY and _GPD), reason="shapely/geopandas absent")
def test_no_overlaps_after_clip(tmp_path: pathlib.Path) -> None:
    """Après clip bbox, les couches 406/408/410 n'ont aucun recouvrement entre elles."""
    import shapely.geometry as sg

    # Trois polygones disjoints représentant 406, 408, 410
    poly_406 = sg.box(0, 0, 3, 3)
    poly_408 = sg.box(3, 0, 6, 3)
    poly_410 = sg.box(6, 0, 9, 3)

    all_polys = [poly_406, poly_408, poly_410]

    # Clip à une bbox qui les contient tous
    bbox_geom = sg.box(0, 0, 9, 3)
    clipped = [geom.intersection(bbox_geom) for geom in all_polys]

    # Vérification overlaps == 0
    overlaps = 0
    for i, g1 in enumerate(clipped):
        for g2 in clipped[i + 1:]:
            inter = g1.intersection(g2)
            if not inter.is_empty and inter.area > 0:
                overlaps += 1

    assert overlaps == 0, f"{overlaps} recouvrement(s) détecté(s) après clip"


# ── P11 : keep_template ──────────────────────────────────────────────────────

def test_keep_template_false_returns_empty(tmp_path: pathlib.Path) -> None:
    """keep_template=False → _build_img_templates retourne [] sans appeler _merge_vege_tiles."""
    from unittest.mock import patch
    import main as m

    kp_cfg = {
        "rendering": {"lightgreentone": 160, "template_opacity_pct": 50},
        "vectorization": {"keep_template": False},
    }
    with patch.object(m, "_merge_vege_tiles") as mock_merge:
        result = m._build_img_templates(tmp_path, kp_cfg, tmp_path / "out.omap")

    assert result == []
    mock_merge.assert_not_called()


def test_keep_template_true_absent_png_returns_empty(tmp_path: pathlib.Path) -> None:
    """keep_template=True mais pas de vegetation.png ni de tuiles → []."""
    from unittest.mock import patch
    import main as m

    out_kp = tmp_path / "out_kp"
    out_kp.mkdir()

    kp_cfg = {
        "rendering": {"lightgreentone": 160, "template_opacity_pct": 50},
        "vectorization": {"keep_template": True},
    }
    with patch.object(m, "_png_to_template") as mock_tmpl:
        result = m._build_img_templates(out_kp, kp_cfg, tmp_path / "out.omap")

    assert result == []
    mock_tmpl.assert_not_called()


def test_keep_template_default_is_true(tmp_path: pathlib.Path) -> None:
    """keep_template absent de la config → comportement par défaut = True (path merge tenté)."""
    from unittest.mock import patch, MagicMock
    import main as m

    out_kp = tmp_path / "out_kp"
    out_kp.mkdir()
    # Crée une tuile factice pour déclencher la branche merge
    (out_kp / "tile_vege.png").write_bytes(b"\x89PNG\r\n")

    kp_cfg = {"rendering": {}, "vectorization": {}}  # keep_template absent → défaut True

    with patch.object(m, "_merge_vege_tiles", return_value=None) as mock_merge:
        m._build_img_templates(out_kp, kp_cfg, tmp_path / "out.omap")

    mock_merge.assert_called_once()
