"""Fixtures communes à tous les tests."""
import numpy as np
import pytest
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def bbox_lambert93():
    """Emprise de test en EPSG:2154 (Lambert-93) — petite zone forestière."""
    # Forêt de Fontainebleau, ~1 km²
    return (651_000.0, 6_840_000.0, 652_000.0, 6_841_000.0)


@pytest.fixture
def bbox_too_large():
    """Emprise dépassant le plafond v1 (> 9 km²)."""
    return (651_000.0, 6_840_000.0, 655_000.0, 6_845_000.0)


@pytest.fixture
def synthetic_density_raster(tmp_path):
    """Raster de densité synthétique 100×100 px avec motifs connus."""
    try:
        from osgeo import gdal, osr
    except ImportError:
        pytest.skip("GDAL non disponible")

    data = np.zeros((100, 100), dtype=np.float32)
    # Bloc dense en haut à gauche (>0.6 → vert foncé)
    data[0:30, 0:30] = 0.8
    # Bloc moyen au centre (0.3-0.6 → vert clair)
    data[35:65, 35:65] = 0.45
    # Bande étroite (2 px) → doit disparaître après ouverture morphologique
    data[70:72, 10:90] = 0.7
    # Bande large (6 px) → doit survivre
    data[80:86, 10:90] = 0.7

    out = tmp_path / "density.tif"
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(out), 100, 100, 1, gdal.GDT_Float32)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(2154)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform([651_000.0, 1.0, 0.0, 6_841_000.0, 0.0, -1.0])
    ds.GetRasterBand(1).WriteArray(data)
    ds.FlushCache()
    return out


@pytest.fixture
def two_adjacent_density_rasters(tmp_path):
    """Deux rasters de densité adjacents (même motif) pour tester l'absence de couture."""
    try:
        from osgeo import gdal, osr
    except ImportError:
        pytest.skip("GDAL non disponible")

    results = []
    for i, x_origin in enumerate([651_000.0, 651_500.0]):
        data = np.full((100, 50), 0.5, dtype=np.float32)
        out = tmp_path / f"density_tile_{i}.tif"
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(str(out), 50, 100, 1, gdal.GDT_Float32)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(2154)
        ds.SetProjection(srs.ExportToWkt())
        ds.SetGeoTransform([x_origin, 1.0, 0.0, 6_841_000.0, 0.0, -1.0])
        ds.GetRasterBand(1).WriteArray(data)
        ds.FlushCache()
        results.append(out)
    return results
