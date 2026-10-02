"""Tests du pont Karttapullautin → raster classifié (src/kp_raster.py)
et de l'étape de partition plane (src/vegetation.stage_coverage_partition).

Les tuiles KP sont synthétisées ici depuis la formule de palette lue dans le
source Rust (src/palette.rs), pas depuis un run réel : les fichiers de sortie
KP ne sont pas versionnés (trop lourds) mais leur contenu est déterministe.
"""
from __future__ import annotations

import pathlib

import pytest

# Les PNG synthétiques n'ont pas de géoréférencement interne (KP pose un .pgw à
# côté) : le pilote rasterio émet un avertissement attendu, sans portée ici.
pytestmark = pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")

import numpy as np
import pytest
import rasterio
import yaml

from src.kp_raster import (
    ISOM_TO_DN,
    KP_FIRST_GREEN,
    KP_YELLOW,
    build_class_raster,
    kp_green_rgb,
    load_tiles,
    mosaic,
    read_ini_vege_params,
    shade_to_dn,
    tile_origin,
)

CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.yaml"


# ── Fabrique de tuiles KP synthétiques ────────────────────────────────────────

def _write_pgw(png: pathlib.Path, west: float, north: float, res: float = 1.0) -> None:
    """World file à la convention KP : centre du pixel haut-gauche (src/process.rs)."""
    png.with_suffix(".pgw").write_text(
        f"{res}\n0.0\n0.0\n-{res}\n{west + res / 2}\n{north - res / 2}\n",
        encoding="utf-8",
    )


def _write_bit_tile(path: pathlib.Path, labels: np.ndarray, west: float, north: float,
                    res: float = 1.0) -> pathlib.Path:
    """Tuile `*_vege_bit.png` : niveaux de gris, valeurs = classes (0/1/2+i)."""
    h, w = labels.shape
    with rasterio.open(path, "w", driver="PNG", height=h, width=w, count=1,
                       dtype="uint8") as ds:
        ds.write(labels.astype(np.uint8), 1)
    _write_pgw(path, west, north, res)
    return path


def _write_rgb_tile(path: pathlib.Path, labels: np.ndarray, west: float, north: float,
                    n_shades: int, tone: int, res: float = 1.0) -> pathlib.Path:
    """Tuile `*_vege.png` telle que KP l'écrit en mode batch : RGB, palette étendue."""
    greens = kp_green_rgb(n_shades, tone)
    rgb_of = {0: (255, 255, 255), KP_YELLOW: (255, 219, 166)}
    for i, g in enumerate(greens):
        rgb_of[KP_FIRST_GREEN + i] = g
    h, w = labels.shape
    arr = np.zeros((3, h, w), dtype=np.uint8)
    for value, color in rgb_of.items():
        mask = labels == value
        for band in range(3):
            arr[band][mask] = color[band]
    with rasterio.open(path, "w", driver="PNG", height=h, width=w, count=3,
                       dtype="uint8") as ds:
        ds.write(arr)
    _write_pgw(path, west, north, res)
    return path


@pytest.fixture
def cfg() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def labels_forest() -> np.ndarray:
    """Motif forestier lisible : taches de densités croissantes + une lucarne."""
    lab = np.zeros((60, 80), dtype=np.uint8)
    lab[5:25, 5:35] = KP_FIRST_GREEN + 1        # vert 2 → 406
    lab[10:20, 45:70] = KP_FIRST_GREEN + 3      # vert 4 → 408
    lab[35:55, 20:40] = KP_FIRST_GREEN + 5      # vert 6 → 410
    lab[40:45, 25:30] = 0                       # lucarne blanche dans le 410
    lab[30:38, 60:75] = KP_YELLOW               # jaune (ignoré)
    return lab


# ── Palette : reproduction exacte de src/palette.rs ───────────────────────────

def test_palette_reproduit_la_formule_rust():
    """R = B = tone − tone/(N−1)·i ; G = 254 − 74/(N−1)·i (KP v2.12.1)."""
    greens = kp_green_rgb(11, 200)              # défaut KP : 11 entrées, tone 200
    assert greens[0] == (200, 254, 200)         # vert le plus clair
    assert greens[10] == (0, 180, 0)            # vert le plus foncé
    assert len(greens) == 11
    # Monotonie : R/B décroissent, G décroît, R == B toujours
    for a, b in zip(greens, greens[1:]):
        assert b[0] <= a[0] and b[1] <= a[1]
    assert all(r == b for r, _, b in greens)


def test_palette_depend_du_tone_et_du_nombre_de_teintes():
    """Le tone du dépôt (160) ne donne pas les mêmes couleurs que le défaut KP (200)."""
    assert kp_green_rgb(11, 160)[0] == (160, 254, 160)
    assert kp_green_rgb(4, 200)[3] == (0, 180, 0)     # N=4 → diviseur 3
    assert kp_green_rgb(11, 200)[3] != kp_green_rgb(4, 200)[3]


def test_ini_lu_donne_la_palette_du_run(tmp_path):
    ini = tmp_path / "pullauta.ini"
    ini.write_text("greenshades=0.4|0.8|1.3|2.6\nlightgreentone=175\nvege_bitmode=1\n",
                   encoding="utf-8")
    params = read_ini_vege_params(ini)
    assert params["n_shades"] == 4
    assert params["lightgreentone"] == 175
    assert params["vege_bitmode"] is True


def test_ini_absent_replie_sur_les_defauts_kp(tmp_path):
    params = read_ini_vege_params(tmp_path / "inexistant.ini")
    assert params["n_shades"] == 11 and params["lightgreentone"] == 200
    assert params["vege_bitmode"] is False


# ── Convention géoréférencement ───────────────────────────────────────────────

def test_pgw_donne_des_centres_de_pixels_pas_des_coins():
    """KP écrit minx+0.5 / maxy−0.5 : le coin se déduit d'un demi-pixel."""
    assert tile_origin(1.0, 448000.5, 6889000.5) == (448000.0, 6889001.0)
    assert tile_origin(2.0, 448001.0, 6888999.0) == (448000.0, 6889000.0)


# ── Lecture des deux présentations ────────────────────────────────────────────

def test_route_bit_et_route_rgb_donnent_les_memes_classes(tmp_path, labels_forest):
    """La classification ne doit dépendre ni du tone, ni du mode de sortie de KP."""
    bit = tmp_path / "bit"
    rgb = tmp_path / "rgb"
    bit.mkdir(); rgb.mkdir()
    _write_bit_tile(bit / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    _write_rgb_tile(rgb / "dalle_vege.png", labels_forest, 448000.0, 6889000.0,
                    n_shades=11, tone=160)
    (rgb / "pullauta.ini").write_text(
        "greenshades=0.2|0.35|0.5|0.7|1.3|2.6|4|99|99|99|99\nlightgreentone=160\n",
        encoding="utf-8")

    lab_bit, res_b, w_b, n_b = mosaic(load_tiles(bit))
    lab_rgb, res_r, w_r, n_r = mosaic(load_tiles(rgb))

    assert (res_b, w_b, n_b) == (res_r, w_r, n_r) == (1.0, 448000.0, 6889000.0)
    np.testing.assert_array_equal(lab_bit, lab_rgb)


def test_auto_prefere_les_tuiles_bit(tmp_path, labels_forest):
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    _write_rgb_tile(tmp_path / "dalle_vege.png", np.zeros_like(labels_forest),
                    448000.0, 6889000.0, n_shades=11, tone=160)
    tiles = load_tiles(tmp_path)                     # prefer="auto"
    assert [t.path.name for t in tiles] == ["dalle_vege_bit.png"]
    tiles_rgb = load_tiles(tmp_path, prefer="rgb")
    assert [t.path.name for t in tiles_rgb] == ["dalle_vege.png"]


def test_couleur_hors_palette_est_signalee(tmp_path, labels_forest):
    """Un PNG dont les couleurs ne viennent pas de la palette KP doit être refusé,
    pas silencieusement interprété (le piège du run avec un autre lightgreentone)."""
    _write_rgb_tile(tmp_path / "dalle_vege.png", labels_forest, 448000.0, 6889000.0,
                    n_shades=11, tone=160)
    # ini déclarant un tone différent de celui du rendu → aucune couleur ne correspond
    (tmp_path / "pullauta.ini").write_text(
        "greenshades=0.4|0.8|1.3\nlightgreentone=230\n", encoding="utf-8")
    tiles = load_tiles(tmp_path)
    labels, *_ = mosaic(tiles)
    assert np.any(labels == 255)                     # sentinelle "non apparié"
    with pytest.raises(ValueError, match="palette KP attendue"):
        shade_to_dn(labels, {KP_FIRST_GREEN: 406})


def test_mosaique_de_deux_tuiles_adjacentes(tmp_path):
    """Deux dalles de 1 km se recollent sans couture ni décalage d'un pixel."""
    left = np.full((40, 40), KP_FIRST_GREEN, dtype=np.uint8)
    right = np.full((40, 40), KP_FIRST_GREEN + 4, dtype=np.uint8)
    _write_bit_tile(tmp_path / "a_vege_bit.png", left, 448000.0, 6889000.0)
    _write_bit_tile(tmp_path / "b_vege_bit.png", right, 448040.0, 6889000.0)
    labels, res, west, north = mosaic(load_tiles(tmp_path))
    assert (res, west, north) == (1.0, 448000.0, 6889000.0)
    assert labels.shape == (40, 80)
    assert set(np.unique(labels[:, :40])) == {KP_FIRST_GREEN}
    assert set(np.unique(labels[:, 40:])) == {KP_FIRST_GREEN + 4}


def test_mosaique_recadree_sur_la_bbox_du_terrain(tmp_path, labels_forest):
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    labels, res, west, north = mosaic(load_tiles(tmp_path),
                                      bbox=(448010.0, 6888950.0, 448050.0, 6888990.0))
    assert (west, north) == (448010.0, 6888990.0)
    assert labels.shape == (40, 40)


def test_mosaique_bbox_clipee_contenu_non_decale(tmp_path):
    """Bbox rognant la tuile à l'ouest ET au nord : le contenu doit suivre.

    Régression : l'offset source dans la tuile n'était pas calculé — le canvas
    recevait `lab[:h, :w]` au lieu de `lab[row_src:, col_src:]`, donc un contenu
    décalé d'autant de pixels que la tuile déborde du canvas. Le test voisin
    `test_mosaique_recadree_sur_la_bbox_du_terrain` ne regardait que la forme.
    """
    lab = ((np.arange(40 * 40).reshape(40, 40) // 7) % 6 + KP_FIRST_GREEN
           ).astype(np.uint8)
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", lab, 448000.0, 6889000.0)
    labels, res, west, north = mosaic(load_tiles(tmp_path),
                                      bbox=(448013.0, 6888960.0, 448033.0, 6888987.0))
    assert (res, west, north) == (1.0, 448013.0, 6888987.0)
    assert labels.shape == (27, 20)       # 6888987-6888960 x 448033-448013
    np.testing.assert_array_equal(labels, lab[13:40, 13:33])


def test_bbox_disjointe_est_une_erreur(tmp_path, labels_forest):
    """Garde-fou du bug de Port-en-Bessin : dalles et bbox qui ne se croisent pas."""
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    with pytest.raises(ValueError, match="disjointe"):
        mosaic(load_tiles(tmp_path), bbox=(424000.0, 6920000.0, 427000.0, 6922000.0))


def test_repertoire_sans_tuile_message_explicite(tmp_path):
    with pytest.raises(FileNotFoundError, match="vege_bitmode"):
        load_tiles(tmp_path)


# ── Raster classifié produit ──────────────────────────────────────────────────

def test_build_class_raster_produit_le_contrat_attendu_par_le_moteur(tmp_path, cfg,
                                                                     labels_forest):
    """Même artefact que scripts/process_hag.py : uint8, DN 85/170/255, 0 = blanc."""
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    out = tmp_path / "out" / "kp_vege_classified.tif"
    report = build_class_raster(tmp_path, cfg, "EPSG:2154", out,
                                prefer="bit")

    assert out.exists()
    with rasterio.open(out) as ds:
        arr = ds.read(1)
        assert ds.dtypes[0] == "uint8"
        assert str(ds.crs).upper().endswith("2154")
        assert ds.transform.c == 448000.0 and ds.transform.f == 6889000.0
        assert ds.transform.a == 1.0 and ds.transform.e == -1.0

    # La table de la config du dépôt doit retrouver les trois classes du motif.
    assert set(np.unique(arr)) <= {0, *ISOM_TO_DN.values()}
    assert np.any(arr == ISOM_TO_DN[406])
    assert np.any(arr == ISOM_TO_DN[408])
    assert np.any(arr == ISOM_TO_DN[410])

    # Le jaune KP n'est jamais écrit : le 401 vient de BD TOPO/OSM.
    assert report["yellow_ha_ignored"] > 0
    assert 401 not in {int(k) for k in report["pixels"]}

    # La lucarne blanche dans le 410 est conservée (pas de remplissage arbitraire).
    assert arr[40, 25] == 0


def test_config_expediaire_refuse_un_code_hors_moteur(tmp_path, labels_forest):
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    bad_cfg = {"karttapullautin": {"vectorization": {
        "shade_to_isom": {KP_FIRST_GREEN + 1: 401},   # 401 non géré par le moteur
    }}}
    with pytest.raises(ValueError, match="généralisation"):
        build_class_raster(tmp_path, bad_cfg, "EPSG:2154", tmp_path / "x.tif", prefer="bit")


def test_config_expediaire_refuse_de_produire_du_jaune(tmp_path, labels_forest):
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    cfg_jaune = {"karttapullautin": {"vectorization": {
        "shade_to_isom": {KP_FIRST_GREEN + 1: 406}, "yellow_to": 401,
    }}}
    with pytest.raises(ValueError, match="yellow_to"):
        build_class_raster(tmp_path, cfg_jaune, "EPSG:2154", tmp_path / "y.tif", prefer="bit")


def test_table_absente_en_config_est_une_erreur(tmp_path, labels_forest):
    _write_bit_tile(tmp_path / "dalle_vege_bit.png", labels_forest, 448000.0, 6889000.0)
    with pytest.raises(ValueError, match="shade_to_isom"):
        build_class_raster(tmp_path, {"karttapullautin": {}}, "EPSG:2154",
                           tmp_path / "z.tif", prefer="bit")


def test_shipped_config_couvre_toutes_les_teintes_atteignables(cfg):
    """La table livrée doit couvrir les teintes du ini par défaut (11 entrées → valeurs 2..12)."""
    mapping = cfg["karttapullautin"]["vectorization"]["shade_to_isom"]
    values = {int(k) for k in mapping}
    assert values >= {2, 3, 4, 5, 6, 7, 8}
    assert all(int(v) in (0, *ISOM_TO_DN) for v in mapping.values())
    assert cfg["karttapullautin"]["vectorization"]["bitmode"] is True
    assert cfg["vegetation"]["source"] in ("kp", "pdal")


# ── Partition plane (végétation modifiable) ───────────────────────────────────

def _two_overlapping_classes():
    import geopandas as gpd
    from shapely.geometry import box

    return gpd.GeoDataFrame(
        {"class": [406, 410], "geometry": [box(0, 0, 100, 100), box(50, 50, 150, 150)]},
        geometry="geometry", crs="EPSG:2154",
    )


def _cfg_partition(enabled: bool) -> dict:
    return {"generalization": {"active_profile": "p", "profiles": {"p": {
        "planar_partition": enabled,
    }}}}


def test_partition_plane_supprime_les_chevauchements():
    from src.vegetation import _total_overlap, stage_coverage_partition

    gdf = _two_overlapping_classes()
    assert _total_overlap(gdf) == pytest.approx(2500.0)

    out, log = stage_coverage_partition(gdf, _cfg_partition(True))
    assert log["overlap_ha_after"] == 0.0
    assert _total_overlap(out) == pytest.approx(0.0, abs=1e-6)

    dense = out[out["class"] == 410].geometry.unary_union
    light = out[out["class"] == 406].geometry.unary_union
    # La classe la plus dense garde tout ; la plus claire est amputée.
    assert dense.area == pytest.approx(10_000.0)
    assert light.area == pytest.approx(7_500.0)


def test_partition_plane_desactivee_laisse_l_etat_anterieur():
    from src.vegetation import _total_overlap, stage_coverage_partition

    gdf = _two_overlapping_classes()
    out, log = stage_coverage_partition(gdf, _cfg_partition(False))
    assert log["enabled"] is False
    assert _total_overlap(out) == pytest.approx(2500.0)


def test_partition_plane_active_par_defaut_dans_la_config_livree(cfg):
    profile = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
    assert profile.get("planar_partition", True) is True
