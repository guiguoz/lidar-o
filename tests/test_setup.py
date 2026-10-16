"""Tests pour le plan d'installabilité V2 — sans réseau ni données réelles."""
from __future__ import annotations

import pathlib
import re
import sys
import textwrap
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ── test_patch_terrain_yaml ───────────────────────────────────────────────────

def test_patch_terrain_yaml_new_fields_do_not_overwrite_existing(tmp_path: pathlib.Path) -> None:
    """Les nouveaux champs s'ajoutent sans écraser bbox/crs existants."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent("""\
        terrains:
          grimbosq:
            bbox: [446000, 6883000, 448000, 6885000]
            crs: EPSG:2154
        """),
        encoding="utf-8",
    )

    from src.init_terrain import patch_terrain_yaml

    patch_terrain_yaml(
        "grimbosq",
        {"lidar_dir": "E:/data/lidar", "kp_version": "2.12.1"},
        config_path,
    )

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    t = cfg["terrains"]["grimbosq"]
    assert t["bbox"] == [446000, 6883000, 448000, 6885000]
    assert t["crs"] == "EPSG:2154"
    assert t["lidar_dir"] == "E:/data/lidar"
    assert t["kp_version"] == "2.12.1"


def test_patch_terrain_yaml_none_values_omitted(tmp_path: pathlib.Path) -> None:
    """Les champs à None ne sont pas écrits dans le YAML."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent("""\
        terrains:
          test:
            bbox: [0, 0, 1000, 1000]
            crs: EPSG:2154
        """),
        encoding="utf-8",
    )

    from src.init_terrain import patch_terrain_yaml

    patch_terrain_yaml("test", {"bdtopo_path": None, "lidar_dir": "E:/lidar"}, config_path)

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    t = cfg["terrains"]["test"]
    assert "bdtopo_path" not in t
    assert t["lidar_dir"] == "E:/lidar"


def test_patch_terrain_yaml_normalises_backslashes(tmp_path: pathlib.Path) -> None:
    """Les backslash Windows sont normalisés en forward slashes."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "terrains:\n  t:\n    bbox: [0,0,1,1]\n    crs: EPSG:2154\n",
        encoding="utf-8",
    )

    from src.init_terrain import patch_terrain_yaml

    patch_terrain_yaml("t", {"lidar_dir": r"E:\data\lidar"}, config_path)

    text = config_path.read_text(encoding="utf-8")
    assert r"E:\data\lidar" not in text
    assert "E:/data/lidar" in text


def test_patch_terrain_yaml_overwrites_same_field(tmp_path: pathlib.Path) -> None:
    """Un appel ultérieur met à jour un champ déjà présent."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent("""\
        terrains:
          t:
            bbox: [0, 0, 1, 1]
            crs: EPSG:2154
            lidar_dir: "old/path"
        """),
        encoding="utf-8",
    )

    from src.init_terrain import patch_terrain_yaml

    patch_terrain_yaml("t", {"lidar_dir": "new/path"}, config_path)

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert cfg["terrains"]["t"]["lidar_dir"] == "new/path"


# ── test_asset_name_windows ───────────────────────────────────────────────────

def test_asset_name_windows_x64() -> None:
    """Sur Windows x86_64, l'asset doit se terminer par -win.tar.gz."""
    with (
        patch("src.kp_install.sys") as mock_sys,
        patch("src.kp_install.platform") as mock_platform,
    ):
        mock_sys.platform = "win32"
        mock_platform.machine.return_value = "AMD64"

        import src.kp_install as kp_mod
        name = kp_mod.asset_name()

    assert name.endswith("-win.tar.gz")
    assert "x86_64" in name


def test_asset_name_linux_x64() -> None:
    """Sur Linux x86_64, l'asset doit se terminer par -linux.tar.gz."""
    with (
        patch("src.kp_install.sys") as mock_sys,
        patch("src.kp_install.platform") as mock_platform,
    ):
        mock_sys.platform = "linux"
        mock_platform.machine.return_value = "x86_64"

        import src.kp_install as kp_mod
        name = kp_mod.asset_name()

    assert name.endswith("-linux.tar.gz")


# ── test_read_binary_version ──────────────────────────────────────────────────

def test_read_binary_version_parses_semver() -> None:
    """read_binary_version extrait correctement un semver depuis la sortie."""
    from src.kp_install import read_binary_version

    mock_result = MagicMock()
    mock_result.stdout = "pullauta 2.12.1\n"
    mock_result.stderr = ""

    with patch("src.kp_install.subprocess.run", return_value=mock_result):
        version = read_binary_version(pathlib.Path("/fake/pullauta"))

    assert version == "2.12.1"


def test_read_binary_version_returns_none_on_failure() -> None:
    """read_binary_version retourne None si le processus lève une exception."""
    from src.kp_install import read_binary_version

    with patch("src.kp_install.subprocess.run", side_effect=FileNotFoundError):
        version = read_binary_version(pathlib.Path("/nonexistent/pullauta"))

    assert version is None


def test_read_binary_version_returns_none_if_no_semver() -> None:
    """read_binary_version retourne None si aucun semver dans la sortie."""
    from src.kp_install import read_binary_version

    mock_result = MagicMock()
    mock_result.stdout = "Karttapullautin"
    mock_result.stderr = ""

    with patch("src.kp_install.subprocess.run", return_value=mock_result):
        version = read_binary_version(pathlib.Path("/fake/pullauta"))

    assert version is None


# ── test_locate_binary_config ─────────────────────────────────────────────────

def test_locate_binary_config_takes_priority(tmp_path: pathlib.Path) -> None:
    """kp_binary dans la config terrain est prioritaire sur KP_BINARY env et PATH."""
    fake_bin = tmp_path / "pullauta.exe"
    fake_bin.touch()

    cfg = {"terrains": {"myterrain": {"kp_binary": str(fake_bin)}}}

    from src.kp_install import locate_binary

    with patch.dict("os.environ", {"KP_BINARY": "/other/pullauta"}, clear=False):
        result = locate_binary(cfg, "myterrain")

    assert result == fake_bin


def test_locate_binary_falls_back_to_env(tmp_path: pathlib.Path) -> None:
    """Sans config kp_binary, KP_BINARY env est utilisé."""
    fake_bin = tmp_path / "pullauta"
    fake_bin.touch()

    cfg: dict = {}

    from src.kp_install import locate_binary

    with patch.dict("os.environ", {"KP_BINARY": str(fake_bin)}, clear=False):
        result = locate_binary(cfg, None)

    assert result == fake_bin


def test_locate_binary_returns_none_if_absent() -> None:
    """Retourne None si KP introuvable partout."""
    from src.kp_install import locate_binary

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("src.kp_install.shutil.which", return_value=None),
    ):
        result = locate_binary({}, "terrain")

    assert result is None


# ── test_bdtopo_dept_extraction ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "filename, expected",
    [
        ("BDT_3-3_GPKG_LAMB93-IGN69_D014-ED2023-12-15.gpkg", "14"),
        ("BDT_3-3_GPKG_LAMB93-IGN69_D70-ED2023-12-15.gpkg", "70"),
        ("BDT_GPKG_D088-ED2024.gpkg", "88"),
        ("BDT_GPKG_D976-ED2024.gpkg", "976"),
        ("no_dept_here.gpkg", None),
    ],
)
def test_bdtopo_dept_extraction(filename: str, expected: str | None) -> None:
    """Extraction du département depuis un nom de fichier type IGN."""
    from src.setup_terrain import _extract_dept_from_filename

    result = _extract_dept_from_filename(filename)
    assert result == expected


# ── Tests Grimbosq ────────────────────────────────────────────────────────────
#
# Les 6 dalles Grimbosq couvrent x ∈ [448000, 450000) et y ∈ [6886000, 6889000).
# L'union des dalles est donc [448000, 6886000, 450000, 6889000].
# La bbox écrite par `init --center` est [448000, 6886000, 450001, 6889001]
# (arrondi de bbox_from_center) — un écart de 1 m sur xmax et ymax.
# Ces deux valeurs sont intentionnellement différentes.

_GRIMBOSQ_TILES = [
    "LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz",
    "LHD_FXX_0448_6888_PTS_LAMB93_IGN69.copc.laz",
    "LHD_FXX_0448_6889_PTS_LAMB93_IGN69.copc.laz",
    "LHD_FXX_0449_6887_PTS_LAMB93_IGN69.copc.laz",
    "LHD_FXX_0449_6888_PTS_LAMB93_IGN69.copc.laz",
    "LHD_FXX_0449_6889_PTS_LAMB93_IGN69.copc.laz",
]

_GRIMBOSQ_CONFIG_BBOX = (448000, 6886000, 450001, 6889001)


def test_grimbosq_tiles_union() -> None:
    """L'union des 6 dalles IGN donne exactement [448000, 6886000, 450000, 6889000]."""
    from src.check_terrain import _ign_tile_extent, _tiles_union

    extents = [_ign_tile_extent(t) for t in _GRIMBOSQ_TILES]
    assert all(e is not None for e in extents), "Toutes les dalles doivent être reconnues"
    union = _tiles_union(extents)  # type: ignore[arg-type]
    assert union == (448000, 6886000, 450000, 6889000)


def test_grimbosq_coverage_against_config_bbox() -> None:
    """La couverture des dalles par rapport à la bbox config est > 99 % (≈99.92 %)."""
    from src.check_terrain import _ign_tile_extent, _tiles_union, _coverage_pct

    extents = [_ign_tile_extent(t) for t in _GRIMBOSQ_TILES]
    tiles_union = _tiles_union(extents)  # type: ignore[arg-type]
    cov = _coverage_pct(_GRIMBOSQ_CONFIG_BBOX, tiles_union)
    assert cov > 99.0, f"Couverture attendue > 99 %, obtenu {cov:.2f} %"


def test_grimbosq_setup_preserves_config_bbox(tmp_path: pathlib.Path) -> None:
    """patch_terrain_yaml ne modifie pas la bbox existante (invariant clé Grimbosq)."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent("""\
        terrains:
          grimbosq:
            bbox: [448000, 6886000, 450001, 6889001]
            crs: EPSG:2154
            departement: "14"
        """),
        encoding="utf-8",
    )

    from src.init_terrain import patch_terrain_yaml

    patch_terrain_yaml(
        "grimbosq",
        {"lidar_dir": "D:/Lidar/grimbosq", "kp_binary": "bin/pullauta.exe", "kp_version": "2.12.1"},
        config_path,
    )

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    t = cfg["terrains"]["grimbosq"]
    assert t["bbox"] == [448000, 6886000, 450001, 6889001], (
        "La bbox Grimbosq ne doit pas être modifiée par setup — "
        "un décalage de 1 m rendrait les sorties incomparables"
    )
