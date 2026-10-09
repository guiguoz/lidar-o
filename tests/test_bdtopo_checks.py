"""Tests pour les contrôles BD TOPO — faux succès supprimés.

Aucun réseau, aucune donnée réelle. Pyogrio injecté via monkeypatch.
"""
from __future__ import annotations

import pathlib
import sys
import textwrap
import types
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers — faux module pyogrio
# ---------------------------------------------------------------------------

def _make_pyogrio(
    *,
    layers: list[str] | None = None,
    list_layers_raises: Exception | None = None,
    total_bounds: tuple | None = (0.0, 0.0, 10.0, 10.0),
    read_info_raises: Exception | None = None,
) -> types.ModuleType:
    """Fabrique un faux module pyogrio contrôlable."""
    mod = types.ModuleType("pyogrio")

    def list_layers(path):
        if list_layers_raises is not None:
            raise list_layers_raises
        names = layers if layers is not None else []
        arr = np.array([[name, "MultiPolygon"] for name in names], dtype=object)
        return arr

    def read_info(path, *, layer=None, **kwargs):
        if read_info_raises is not None:
            raise read_info_raises
        return {"total_bounds": total_bounds, "crs": "EPSG:2154", "features": 1}

    mod.list_layers = list_layers
    mod.read_info = read_info
    return mod


_ALL_REQUIRED = [
    "troncon_de_route",
    "batiment",
    "surface_hydrographique",
    "troncon_hydrographique",
]

_BBOX_INSIDE = (1.0, 1.0, 9.0, 9.0)     # total_bounds (0,0,10,10) la couvre
_BBOX_OUTSIDE = (5.0, 5.0, 20.0, 20.0)  # total_bounds (0,0,10,10) ne la couvre pas


# ---------------------------------------------------------------------------
# check_terrain._check_bdtopo_layers
# ---------------------------------------------------------------------------

class TestCheckTerrainLayers:

    def test_pyogrio_absent_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Pyogrio absent → non_verifie, aucun ✓."""
        monkeypatch.setitem(sys.modules, "pyogrio", None)  # type: ignore[arg-type]

        from src.check_terrain import _check_bdtopo_layers

        result = _check_bdtopo_layers(tmp_path / "fake.gpkg")
        assert result.status == "non_verifie"
        assert result.missing == []
        assert "pyogrio" in result.reason

    def test_lecture_echouee_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Lecture GPKG en échec → non_verifie."""
        fake_pyogrio = _make_pyogrio(list_layers_raises=OSError("gpkg illisible"))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_layers

        result = _check_bdtopo_layers(tmp_path / "bad.gpkg")
        assert result.status == "non_verifie"
        assert "lecture GPKG" in result.reason or "gpkg illisible" in result.reason

    def test_couche_requise_absente_retourne_anomalie(self, monkeypatch, tmp_path):
        """Couche requise absente → anomalie avec la couche manquante."""
        layers_present = [l for l in _ALL_REQUIRED if l != "batiment"]
        fake_pyogrio = _make_pyogrio(layers=layers_present)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_layers

        result = _check_bdtopo_layers(tmp_path / "partial.gpkg")
        assert result.status == "anomalie"
        assert "batiment" in result.missing

    def test_toutes_couches_presentes_retourne_ok(self, monkeypatch, tmp_path):
        """Toutes les couches présentes → ok."""
        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED + ["extra_layer"])
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_layers

        result = _check_bdtopo_layers(tmp_path / "full.gpkg")
        assert result.status == "ok"
        assert result.missing == []


# ---------------------------------------------------------------------------
# check_terrain._check_bdtopo_coverage
# ---------------------------------------------------------------------------

class TestCheckTerrainCoverage:

    def test_pyogrio_absent_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Pyogrio absent → non_verifie."""
        monkeypatch.setitem(sys.modules, "pyogrio", None)  # type: ignore[arg-type]

        from src.check_terrain import _check_bdtopo_coverage

        result = _check_bdtopo_coverage(tmp_path / "fake.gpkg", _BBOX_INSIDE)
        assert result.status == "non_verifie"
        assert "pyogrio" in result.reason

    def test_read_info_echoue_retourne_non_verifie(self, monkeypatch, tmp_path):
        """read_info en échec → non_verifie."""
        fake_pyogrio = _make_pyogrio(read_info_raises=RuntimeError("erreur lecture"))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_coverage

        result = _check_bdtopo_coverage(tmp_path / "bad.gpkg", _BBOX_INSIDE)
        assert result.status == "non_verifie"
        assert "lecture échouée" in result.reason

    def test_total_bounds_none_retourne_non_verifie(self, monkeypatch, tmp_path):
        """total_bounds=None → non_verifie."""
        fake_pyogrio = _make_pyogrio(total_bounds=None)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_coverage

        result = _check_bdtopo_coverage(tmp_path / "notopo.gpkg", _BBOX_INSIDE)
        assert result.status == "non_verifie"
        assert "total_bounds" in result.reason

    def test_couverture_insuffisante_retourne_anomalie(self, monkeypatch, tmp_path):
        """Bbox hors des bornes → anomalie."""
        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED, total_bounds=(0.0, 0.0, 10.0, 10.0))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_coverage

        result = _check_bdtopo_coverage(tmp_path / "small.gpkg", _BBOX_OUTSIDE)
        assert result.status == "anomalie"

    def test_couverture_ok_retourne_ok(self, monkeypatch, tmp_path):
        """Bbox incluse dans les bornes → ok."""
        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED, total_bounds=(0.0, 0.0, 10.0, 10.0))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import _check_bdtopo_coverage

        result = _check_bdtopo_coverage(tmp_path / "full.gpkg", _BBOX_INSIDE)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_terrain.cmd_check — cas conforme et blocage bdtopo_path absent
# ---------------------------------------------------------------------------

class TestCmdCheckBdtopo:

    def _minimal_cfg(self, tmp_path: pathlib.Path, bdtopo_p: pathlib.Path) -> dict:
        return {
            "terrains": {
                "test": {
                    "bbox": list(_BBOX_INSIDE),
                    "crs": "EPSG:2154",
                    "bdtopo_path": str(bdtopo_p),
                }
            }
        }

    def test_bdtopo_path_absent_bloque_all_ok(self, tmp_path, capsys):
        """bdtopo_path déclaré mais absent → all_ok=False, message ✗."""
        absent = tmp_path / "absent.gpkg"
        cfg = self._minimal_cfg(tmp_path, absent)

        from src.check_terrain import cmd_check

        with (
            patch("src.check_terrain.check_deps", return_value=True),
            patch("src.check_terrain._laz_metadata", return_value=None),
            patch("src.kp_install.locate_binary", return_value=None),
        ):
            result = cmd_check("test", cfg, tmp_path, verbose=True)

        out = capsys.readouterr().out
        assert result is False
        assert "bdtopo_path déclaré mais absent" in out or "✗" in out

    def test_pyogrio_absent_affiche_non_verifie_pas_coche(self, monkeypatch, tmp_path, capsys):
        """Pyogrio absent avec fichier présent → ⚠ non vérifié, pas de ✓ GPKG."""
        gpkg = tmp_path / "fake.gpkg"
        gpkg.touch()
        cfg = self._minimal_cfg(tmp_path, gpkg)

        monkeypatch.setitem(sys.modules, "pyogrio", None)  # type: ignore[arg-type]

        from src.check_terrain import cmd_check

        with (
            patch("src.check_terrain.check_deps", return_value=True),
            patch("src.check_terrain._laz_metadata", return_value=None),
            patch("src.kp_install.locate_binary", return_value=None),
        ):
            cmd_check("test", cfg, tmp_path, verbose=True)

        out = capsys.readouterr().out
        # Aucun ✓ pour le GPKG (le ✓ global n'est affiché que si couches ET couverture sont ok)
        assert "non vérifié" in out
        # Le ✓ global du GPKG n'est pas là
        assert f"✓ {gpkg.name}" not in out

    def test_cas_conforme_affiche_coche_gpkg(self, monkeypatch, tmp_path, capsys):
        """Couches OK + couverture OK → ✓ nom_du_fichier.gpkg."""
        gpkg = tmp_path / "bdtopo.gpkg"
        gpkg.touch()
        cfg = self._minimal_cfg(tmp_path, gpkg)

        fake_pyogrio = _make_pyogrio(
            layers=_ALL_REQUIRED,
            total_bounds=(0.0, 0.0, 10.0, 10.0),
        )
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import cmd_check

        with (
            patch("src.check_terrain.check_deps", return_value=True),
            patch("src.check_terrain._laz_metadata", return_value=None),
            patch("src.kp_install.locate_binary", return_value=None),
        ):
            cmd_check("test", cfg, tmp_path, verbose=True)

        out = capsys.readouterr().out
        assert f"✓ {gpkg.name}" in out

    def test_bbox_absente_affiche_non_verifie_couverture(self, monkeypatch, tmp_path, capsys):
        """Bbox absente → couverture non vérifiée affichée."""
        gpkg = tmp_path / "bdtopo.gpkg"
        gpkg.touch()
        cfg = {
            "terrains": {
                "test": {
                    "crs": "EPSG:2154",
                    "bdtopo_path": str(gpkg),
                    # pas de bbox
                }
            }
        }
        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.check_terrain import cmd_check

        with (
            patch("src.check_terrain.check_deps", return_value=True),
            patch("src.check_terrain._laz_metadata", return_value=None),
            patch("src.kp_install.locate_binary", return_value=None),
        ):
            cmd_check("test", cfg, tmp_path, verbose=True)

        out = capsys.readouterr().out
        assert "non vérifié (couverture)" in out
        assert "bbox absente" in out


# ---------------------------------------------------------------------------
# setup_terrain._validate_bdtopo_layers
# ---------------------------------------------------------------------------

class TestSetupTerrainLayers:

    def test_pyogrio_absent_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Pyogrio absent → non_verifie."""
        monkeypatch.setitem(sys.modules, "pyogrio", None)  # type: ignore[arg-type]

        from src.setup_terrain import _validate_bdtopo_layers

        result = _validate_bdtopo_layers(tmp_path / "fake.gpkg")
        assert result.status == "non_verifie"
        assert "pyogrio" in result.reason

    def test_lecture_echouee_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Lecture GPKG en échec → non_verifie."""
        fake_pyogrio = _make_pyogrio(list_layers_raises=OSError("erreur"))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _validate_bdtopo_layers

        result = _validate_bdtopo_layers(tmp_path / "bad.gpkg")
        assert result.status == "non_verifie"

    def test_couche_requise_absente_retourne_anomalie(self, monkeypatch, tmp_path):
        """Couche manquante → anomalie."""
        layers_present = [l for l in _ALL_REQUIRED if l != "troncon_de_route"]
        fake_pyogrio = _make_pyogrio(layers=layers_present)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _validate_bdtopo_layers

        result = _validate_bdtopo_layers(tmp_path / "partial.gpkg")
        assert result.status == "anomalie"
        assert "troncon_de_route" in result.missing

    def test_toutes_couches_presentes_retourne_ok(self, monkeypatch, tmp_path):
        """Toutes couches présentes → ok."""
        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _validate_bdtopo_layers

        result = _validate_bdtopo_layers(tmp_path / "full.gpkg")
        assert result.status == "ok"
        assert result.missing == []


# ---------------------------------------------------------------------------
# setup_terrain._bdtopo_covers_bbox
# ---------------------------------------------------------------------------

class TestSetupTerrainCoverage:

    def test_pyogrio_absent_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Pyogrio absent → non_verifie (pas True)."""
        monkeypatch.setitem(sys.modules, "pyogrio", None)  # type: ignore[arg-type]

        from src.setup_terrain import _bdtopo_covers_bbox

        result = _bdtopo_covers_bbox(tmp_path / "fake.gpkg", _BBOX_INSIDE)
        assert result.status == "non_verifie"
        assert "pyogrio" in result.reason

    def test_exception_retourne_non_verifie(self, monkeypatch, tmp_path):
        """Exception sur read_info → non_verifie (pas True)."""
        fake_pyogrio = _make_pyogrio(read_info_raises=RuntimeError("crash"))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _bdtopo_covers_bbox

        result = _bdtopo_covers_bbox(tmp_path / "bad.gpkg", _BBOX_INSIDE)
        assert result.status == "non_verifie"
        # Vérifier que ce n'est PAS un succès silencieux
        assert result.status != "ok"

    def test_total_bounds_none_retourne_non_verifie(self, monkeypatch, tmp_path):
        """total_bounds None → non_verifie."""
        fake_pyogrio = _make_pyogrio(total_bounds=None)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _bdtopo_covers_bbox

        result = _bdtopo_covers_bbox(tmp_path / "notopo.gpkg", _BBOX_INSIDE)
        assert result.status == "non_verifie"

    def test_bbox_hors_bornes_retourne_anomalie(self, monkeypatch, tmp_path):
        """Bbox non couverte → anomalie."""
        fake_pyogrio = _make_pyogrio(total_bounds=(0.0, 0.0, 10.0, 10.0))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _bdtopo_covers_bbox

        result = _bdtopo_covers_bbox(tmp_path / "small.gpkg", _BBOX_OUTSIDE)
        assert result.status == "anomalie"

    def test_bbox_incluse_retourne_ok(self, monkeypatch, tmp_path):
        """Bbox incluse dans les bornes → ok."""
        fake_pyogrio = _make_pyogrio(total_bounds=(0.0, 0.0, 10.0, 10.0))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _bdtopo_covers_bbox

        result = _bdtopo_covers_bbox(tmp_path / "full.gpkg", _BBOX_INSIDE)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# setup_terrain._setup_bdtopo — affichage libellé neutre
# ---------------------------------------------------------------------------

class TestSetupBdtopoAffichage:

    def test_libelle_neutre_pas_coche_deja_configure(self, monkeypatch, tmp_path, capsys):
        """'Chemin déjà configuré' affiché au lieu de '✓ déjà configuré'."""
        gpkg = tmp_path / "bdtopo.gpkg"
        gpkg.touch()
        terrain_cfg = {
            "crs": "EPSG:2154",
            "bdtopo_path": str(gpkg),
            "bbox": list(_BBOX_INSIDE),
        }
        cfg = {"terrains": {"test": terrain_cfg}}

        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED, total_bounds=(0.0, 0.0, 10.0, 10.0))
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _setup_bdtopo

        _setup_bdtopo("test", terrain_cfg, tmp_path, cfg)
        out = capsys.readouterr().out

        assert "Chemin déjà configuré" in out
        assert "✓ déjà configuré" not in out

    def test_pyogrio_absent_affiche_non_verifie_couches(self, monkeypatch, tmp_path, capsys):
        """Pyogrio absent → ⚠ non vérifié dans l'affichage setup."""
        gpkg = tmp_path / "bdtopo.gpkg"
        gpkg.touch()
        terrain_cfg = {
            "crs": "EPSG:2154",
            "bdtopo_path": str(gpkg),
            "bbox": list(_BBOX_INSIDE),
        }
        cfg = {"terrains": {"test": terrain_cfg}}

        monkeypatch.setitem(sys.modules, "pyogrio", None)  # type: ignore[arg-type]

        from src.setup_terrain import _setup_bdtopo

        _setup_bdtopo("test", terrain_cfg, tmp_path, cfg)
        out = capsys.readouterr().out

        assert "non vérifié" in out

    def test_bbox_absente_affiche_non_verifie_couverture(self, monkeypatch, tmp_path, capsys):
        """Bbox absente → couverture non vérifiée affichée dans setup."""
        gpkg = tmp_path / "bdtopo.gpkg"
        gpkg.touch()
        terrain_cfg = {
            "crs": "EPSG:2154",
            "bdtopo_path": str(gpkg),
            # pas de bbox
        }
        cfg = {"terrains": {"test": terrain_cfg}}

        fake_pyogrio = _make_pyogrio(layers=_ALL_REQUIRED)
        monkeypatch.setitem(sys.modules, "pyogrio", fake_pyogrio)

        from src.setup_terrain import _setup_bdtopo

        _setup_bdtopo("test", terrain_cfg, tmp_path, cfg)
        out = capsys.readouterr().out

        assert "non vérifié (couverture)" in out
        assert "bbox absente" in out
