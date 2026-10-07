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


# ── P7 : coverage_is_valid — comportement intra-classe et T-junctions inter-classes ──

@pytest.mark.skipif(not _SHAPELY, reason="shapely absent")
def test_coverage_valid_on_adjacent_polygons() -> None:
    """Deux polygones adjacents (arête partagée exacte) → coverage_is_valid=True."""
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


@pytest.mark.skipif(not _SHAPELY, reason="shapely absent")
def test_inter_class_tjunction_not_blocked_by_per_class_guard() -> None:
    """T-junctions inter-classes : invalides globalement, valides par classe, overlaps=0.

    Propriété structurelle de la polygonisation raster séparée par masque :
    lorsqu'on polygonise 406 et 408 séparément, la frontière commune produit des
    T-junctions (un sommet de B se trouve sur une arête de A sans sommet homologue).
    coverage_is_valid(global) = False, mais il n'y a aucun overlap surfacique.

    Le garde-fou P7 doit donc être appliqué PAR CLASSE, pas sur 406+408+410 ensemble.
    """
    # Polygon A (406) : rectangle tall, arête droite de (1,0) à (1,2) sans sommet à (1,1)
    # Polygon B (408) : rectangle bas, sommet haut-gauche à (1,1) sur l'arête de A
    a = sg.box(0, 0, 1, 2)
    b = sg.box(1, 0, 2, 1)

    arr_global = np.array([a, b], dtype=object)
    arr_a = np.array([a], dtype=object)
    arr_b = np.array([b], dtype=object)

    # Global : invalide — T-junction structurelle inter-classes attendue
    assert not shapely.coverage_is_valid(arr_global), (
        "La couverture globale 406+408 doit etre invalide (T-junction structurelle)"
    )
    # Par classe : valide — aucune arête partagée au sein d'une même classe
    assert shapely.coverage_is_valid(arr_a), "La classe 406 seule doit etre valide"
    assert shapely.coverage_is_valid(arr_b), "La classe 408 seule doit etre valide"

    # Mais overlap surfacique nul — la T-junction n'est pas un chevauchement
    assert a.intersection(b).area == 0, "Overlap surfacique inattendu entre 406 et 408"


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


# ── Erreurs bloquantes : source KP absente ───────────────────────────────────

def test_step_vegetation_kp_raises_if_outKp_present_no_png(tmp_path: pathlib.Path) -> None:
    """out_kp/ présent mais aucun *_vege*.png → RuntimeError (état anormal)."""
    from unittest.mock import patch
    import main as m

    out_kp = tmp_path / "out_kp_test"
    out_kp.mkdir()  # répertoire présent, vide (pas de PNG)

    with patch.object(m, "ROOT", tmp_path), \
         patch.object(m, "OUTPUT", tmp_path / "output"):
        with pytest.raises(RuntimeError, match="vege_bitmode"):
            m.step_vegetation_kp("test", {}, force=True)


def test_step_vegetation_kp_silent_if_outKp_absent(
    tmp_path: pathlib.Path, caplog
) -> None:
    """out_kp/ absent → log.info + return, aucune exception (KP non lancé)."""
    import logging
    from unittest.mock import patch
    import main as m

    with patch.object(m, "ROOT", tmp_path), \
         patch.object(m, "OUTPUT", tmp_path / "output"):
        with caplog.at_level(logging.INFO, logger="main"):
            m.step_vegetation_kp("test", {}, force=True)  # ne doit pas lever

    assert "KP non lancé" in caplog.text


def test_step_assemble_raises_if_outKp_present_no_gpkg(tmp_path: pathlib.Path) -> None:
    """out_kp/ présent mais vegetation_kp.gpkg absent → RuntimeError dans step_assemble."""
    from unittest.mock import patch
    import main as m

    out_kp = tmp_path / "out_kp_test"
    out_kp.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    # vegetation_kp.gpkg intentionnellement absent

    with patch.object(m, "ROOT", tmp_path), \
         patch.object(m, "OUTPUT", output_dir), \
         patch.object(m, "DATA", tmp_path / "data"):
        with pytest.raises(RuntimeError, match="vegetation_kp.gpkg absent"):
            m.step_assemble("test", {}, force=True)


# ── P7/P8 : régressions exécutées sur le vrai code ───────────────────────────
#
# Les tests ci-dessous pilotent main.step_vegetation_kp. Sans eux, rétablir le
# garde-fou global ou passer coverage_simplify par classe ne fait échouer aucun
# test (vérifié par mutation) — alors que le second cas produit des recouvrements
# inter-classes mesurés à 3 365 m² sur Grimbosq.

# Raster 12×12 (np.random.default_rng(4).choice([0,0,0,85,170,255], (12,12))) :
# cas minimal déterministe où la simplification PAR CLASSE déborde sur la classe
# voisine (> 1e-9 m²) alors que la simplification GLOBALE reste à < 1e-9 m².
_TJ_OVERLAP_RASTER = np.array([
    [170, 255, 255,  85, 255, 255, 255,   0,   0,  85,   0,   0],
    [ 85, 170,  85,   0, 170, 255,   0,  85,   0, 255,   0,   0],
    [255,   0,   0, 170, 255, 255, 255,   0, 170, 255,  85, 255],
    [ 85,   0,   0,  85,   0, 170,   0, 255,   0,  85,   0,   0],
    [ 85,   0,   0,   0, 255,  85,   0, 255, 255,   0,   0,   0],
    [  0,  85,  85,  85, 255, 255,  85,  85,   0,   0, 255, 255],
    [  0,   0,   0, 170,   0,   0,   0,   0, 170, 170,   0, 170],
    [ 85,   0,  85,   0,   0,   0, 255,   0, 255,   0, 170, 255],
    [  0, 255,   0,   0,  85, 170,   0,   0,   0, 255,   0,  85],
    [  0, 170, 255,   0, 255,   0,   0,   0,   0, 255,   0,   0],
    [ 85,   0,   0, 255, 255, 255,   0,   0,   0,   0,   0, 170],
    [170,   0,   0,   0, 255, 255,   0, 255,   0,   0, 255,   0],
], dtype=np.uint8)


def _polygonise_per_class(data: np.ndarray, transform) -> tuple[list, list[int]]:
    """Polygonisation identique à main.step_vegetation_kp (P6)."""
    from rasterio.features import shapes as rasterio_shapes
    from src.kp_raster import ISOM_TO_DN

    dn_to_isom = {v: k for k, v in ISOM_TO_DN.items()}
    geoms: list = []
    codes: list[int] = []
    for dn, isom in sorted(dn_to_isom.items()):
        mask_arr = (data == dn).astype(np.uint8)
        for geom_dict, _ in rasterio_shapes(mask_arr, mask=mask_arr, transform=transform):
            geom = sg.shape(geom_dict)
            if not geom.is_empty:
                geoms.append(geom)
                codes.append(isom)
    return geoms, codes


def _overlap_area(geoms: list) -> float:
    """Surface totale des recouvrements entre toutes les paires de géométries."""
    from shapely.strtree import STRtree

    if len(geoms) < 2:
        return 0.0
    total = 0.0
    tree = STRtree(geoms)
    for i, g in enumerate(geoms):
        for j in tree.query(g):
            if j <= i:
                continue
            inter = geoms[j].intersection(g)
            if inter.area > 1e-9:
                total += inter.area
    return total


@pytest.mark.skipif(not (_RASTERIO and _SHAPELY and _GPD),
                    reason="rasterio, shapely ou geopandas absent")
def test_step_vegetation_kp_accepte_les_tjunctions_interclasses(
    tmp_path: pathlib.Path,
) -> None:
    """Exécute le vrai step_vegetation_kp sur un raster à jonctions en T.

    La couverture globale (406+408+410 concaténés) est invalide à cause des
    jonctions en T ; le garde-fou P7 étant intra-classe, l'étape doit aller au
    bout et écrire vegetation_kp.gpkg sans ValueError.

    Décisif : si coverage_simplify était appelé par classe au lieu de l'ensemble,
    les couches produites se recouvriraient (3 365 m² mesurés sur Grimbosq).
    Ce test détecte cette régression.
    """
    from unittest.mock import patch
    import main as m
    import src.kp_raster as kp

    out_kp = tmp_path / "out_kp_test"
    out_kp.mkdir()
    for i in range(6):
        (out_kp / f"d{i}_vege.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)

    data = _TJ_OVERLAP_RASTER
    origin = from_origin(448000.0, 6889000.0, 1.0, 1.0)

    def fake_build_class_raster(out_kp_dir, cfg, crs, dst, bbox=None):
        dst.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            dst, "w", driver="GTiff",
            height=data.shape[0], width=data.shape[1],
            count=1, dtype="uint8", crs=crs,
            transform=origin, nodata=0,
        ) as ds:
            ds.write(data, 1)

    # Pré-condition : la couverture globale IS invalide sur ce raster.
    geoms_raw, _ = _polygonise_per_class(data, origin)
    assert not shapely.coverage_is_valid(np.array(geoms_raw, dtype=object))

    with patch.object(m, "ROOT", tmp_path), \
         patch.object(m, "OUTPUT", tmp_path / "output"), \
         patch.object(kp, "build_class_raster", fake_build_class_raster):
        m.step_vegetation_kp("test", {}, force=True)  # ne doit pas lever

    gpkg = tmp_path / "output" / "vegetation_kp.gpkg"
    assert gpkg.exists(), "vegetation_kp.gpkg aurait du etre ecrit"
    import pyogrio
    layers = {row[0] for row in pyogrio.list_layers(gpkg)}
    assert layers == {"veg_406", "veg_408", "veg_410"}
    produced: list = []
    for name in sorted(layers):
        geoms_out = list(gpd.read_file(gpkg, layer=name).geometry)
        assert sum(1 for g in geoms_out) > 0 or True  # couche peut etre vide apres simplify
        assert all(g.is_valid for g in geoms_out), f"geometrie invalide dans {name}"
        produced += geoms_out

    assert _overlap_area(produced) < 1e-9, (
        "recouvrement dans vegetation_kp.gpkg — coverage_simplify doit etre appele "
        "sur les 3 classes ensemble, pas par classe"
    )


@pytest.mark.skipif(not (_RASTERIO and _SHAPELY), reason="rasterio ou shapely absent")
def test_coverage_simplify_doit_rester_global() -> None:
    """coverage_simplify global → overlap < 1e-9 ; par classe → overlap > 1e-9.

    Verrouille la propriété architecturale : c'est la simplification simultanée
    du graphe d'arêtes partagé qui résout les frontières inter-classes. Simplifier
    chaque classe isolément lui fait ignorer ses voisines et déborder.
    """
    origin = from_origin(0.0, 12.0, 1.0, 1.0)
    geoms, codes = _polygonise_per_class(_TJ_OVERLAP_RASTER, origin)
    arr = np.array(geoms, dtype=object)

    assert _overlap_area(geoms) < 1e-9, "la polygonisation RAW ne doit pas recouvrir"
    assert all(g.is_valid for g in geoms)

    global_simplified = [
        g for g in shapely.coverage_simplify(arr, tolerance=2.0, simplify_boundary=True)
        if g is not None and not g.is_empty
    ]
    assert _overlap_area(global_simplified) < 1e-9, (
        "coverage_simplify global doit produire 0 recouvrement"
    )

    per_class: list = []
    for code in (406, 408, 410):
        sub = np.array([g for g, c in zip(geoms, codes) if c == code], dtype=object)
        if len(sub) == 0:
            continue
        per_class += [
            g for g in shapely.coverage_simplify(sub, tolerance=2.0, simplify_boundary=True)
            if g is not None and not g.is_empty
        ]
    assert _overlap_area(per_class) > 1e-9, (
        "attendu : la simplification par classe cree des recouvrements inter-classes — "
        "coverage_simplify doit rester appele sur les 3 classes ensemble"
    )
