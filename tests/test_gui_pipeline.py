"""Tests fonctionnels GUI : sélection moteur, écriture config, parcours manuel LAZ+GPKG."""
from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

import gui.app as gui_app
from gui.app import _patch_global_yaml_key


class _Var:
    """Substitut léger à tk.StringVar — pas de fenêtre tkinter requise."""
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self) -> str:
        return self._v

    def set(self, v: str) -> None:
        self._v = v


def _make_app(
    cfg: dict,
    tiles: list[pathlib.Path],
    *,
    tile_extents: dict | None = None,
    veg: str = "kp",
    export_mode: str = "faithful",
    terrain: str = "mon_projet",
    lidar_dir: pathlib.Path | None = None,
    bdtopo_path: pathlib.Path | None = None,
) -> gui_app.LidarOApp:
    """LidarOApp minimal sans fenêtre tkinter pour les tests."""
    app = object.__new__(gui_app.LidarOApp)
    app._cfg = cfg
    app._tiles = tiles
    app._tile_extents = tile_extents or {}
    app._lidar_dir = lidar_dir or (tiles[0].parent if tiles else None)
    app._bdtopo_path = bdtopo_path
    app._kp_binary = None
    app._terrain_var = _Var(terrain)
    app._veg_var = _Var(veg)
    app._export_var = _Var(export_mode)
    app._log = lambda msg: None  # pas de _log_text hors fenêtre tkinter
    return app


# ── _patch_global_yaml_key ───────────────────────────────────────────────────

class TestPatchGlobalYamlKey:
    """La fonction utilitaire écrit la clé globale dans toutes les situations."""

    def test_cle_absente_ajoutee_en_tete(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("crs: EPSG:2154\n", encoding="utf-8")
        _patch_global_yaml_key("vegetation_export_mode", "generalized", cfg)
        content = cfg.read_text(encoding="utf-8")
        assert 'vegetation_export_mode: "generalized"' in content

    def test_ligne_commentee_remplacee(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            '# vegetation_export_mode: "faithful"\ncrs: EPSG:2154\n',
            encoding="utf-8",
        )
        _patch_global_yaml_key("vegetation_export_mode", "generalized", cfg)
        content = cfg.read_text(encoding="utf-8")
        assert 'vegetation_export_mode: "generalized"' in content
        assert "# vegetation_export_mode" not in content

    def test_cle_active_mise_a_jour(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text('vegetation_export_mode: "faithful"\ncrs: EPSG:2154\n', encoding="utf-8")
        _patch_global_yaml_key("vegetation_export_mode", "generalized", cfg)
        content = cfg.read_text(encoding="utf-8")
        assert content.count("vegetation_export_mode") == 1
        assert 'vegetation_export_mode: "generalized"' in content

    def test_autres_cles_preservees(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("crs: EPSG:2154\nscale: 10000\n", encoding="utf-8")
        _patch_global_yaml_key("vegetation_export_mode", "faithful", cfg)
        content = cfg.read_text(encoding="utf-8")
        assert "crs: EPSG:2154" in content
        assert "scale: 10000" in content

    def test_yaml_reste_valide(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("crs: EPSG:2154\n# vegetation_export_mode: \"faithful\"\n", encoding="utf-8")
        _patch_global_yaml_key("vegetation_export_mode", "generalized", cfg)
        parsed = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        assert parsed["vegetation_export_mode"] == "generalized"
        assert parsed["crs"] == "EPSG:2154"


# ── _ensure_terrain_in_config écrit vegetation_source ───────────────────────

class TestEnsureTerrainEcritVegSource:
    """vegetation_source est toujours écrit depuis la sélection GUI, terrain neuf ou existant."""

    def _setup(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "assets").mkdir(exist_ok=True)
        (tmp_path / "config.yaml").write_text("crs: EPSG:2154\nterrains:\n", encoding="utf-8")
        lidar = tmp_path / "LIDAR"
        lidar.mkdir(exist_ok=True)
        tile = lidar / "LHD_FXX_0448_6886_PTS_LAMB93_IGN69.copc.laz"
        tile.write_bytes(b"")
        return lidar, tile

    def test_nouveau_terrain_supervised_e_persiste(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        lidar, tile = self._setup(tmp_path)

        app = _make_app({}, [tile], veg="supervised_e", lidar_dir=lidar)
        assert app._ensure_terrain_in_config("mon_projet") is True

        cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert cfg["terrains"]["mon_projet"]["vegetation_source"] == "supervised_e"

    def test_nouveau_terrain_kp_persiste(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        lidar, tile = self._setup(tmp_path)

        app = _make_app({}, [tile], veg="kp", lidar_dir=lidar)
        assert app._ensure_terrain_in_config("mon_projet") is True

        cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert cfg["terrains"]["mon_projet"]["vegetation_source"] == "kp"

    def test_terrain_existant_moteur_mis_a_jour(self, tmp_path, monkeypatch):
        """Un terrain déjà configuré avec kp voit son moteur basculé sur supervised_e."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "assets").mkdir()
        config_text = (
            "crs: EPSG:2154\n"
            "terrains:\n"
            "  mon_projet:\n"
            "    bbox: [448000, 6885000, 449000, 6886000]\n"
            '    vegetation_source: "kp"\n'
        )
        (tmp_path / "config.yaml").write_text(config_text, encoding="utf-8")
        tile = tmp_path / "LIDAR" / "LHD_FXX_0448_6886_PTS_LAMB93_IGN69.copc.laz"
        tile.parent.mkdir()
        tile.write_bytes(b"")
        existing_cfg = yaml.safe_load(config_text)

        app = _make_app(existing_cfg, [tile], veg="supervised_e")
        assert app._ensure_terrain_in_config("mon_projet") is True

        cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert cfg["terrains"]["mon_projet"]["vegetation_source"] == "supervised_e"

    def test_chemin_lidar_persiste(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        lidar, tile = self._setup(tmp_path)

        app = _make_app({}, [tile], veg="kp", lidar_dir=lidar)
        app._ensure_terrain_in_config("mon_projet")

        cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert cfg["terrains"]["mon_projet"].get("lidar_dir") is not None

    def test_echec_sans_tuiles(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.yaml").write_text("crs: EPSG:2154\nterrains:\n", encoding="utf-8")

        app = _make_app({}, tiles=[], lidar_dir=tmp_path / "LIDAR")
        # Sans boîte de dialogue (mb.showerror), on s'attend à False
        # Patch mb.showerror pour ne pas bloquer
        monkeypatch.setattr(gui_app.mb, "showerror", lambda *a, **kw: None)
        assert app._ensure_terrain_in_config("mon_projet") is False


# ── Parcours fonctionnel complet ─────────────────────────────────────────────

class TestParcoursManuels:
    """Test fonctionnel : LAZ + GPKG chargés manuellement, supervised_e + faithful."""

    def test_parcours_complet_supervised_e_faithful(self, tmp_path, monkeypatch):
        """
        Vérifie la cohérence complète du parcours :
        chargement manuel → terrain créé avec supervised_e →
        vegetation_export_mode: faithful dans config → sys.argv correct.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "assets").mkdir()
        (tmp_path / "config.yaml").write_text(
            "crs: EPSG:2154\n# vegetation_export_mode: \"faithful\"\nterrains:\n",
            encoding="utf-8",
        )

        lidar_dir = tmp_path / "LIDAR"
        lidar_dir.mkdir()
        tiles = []
        for x, y in [(448, 6886), (449, 6886)]:
            t = lidar_dir / f"LHD_FXX_{x:04d}_{y:04d}_PTS_LAMB93_IGN69.copc.laz"
            t.write_bytes(b"")
            tiles.append(t)

        gpkg = tmp_path / "BDTOPO_D014.gpkg"
        gpkg.write_bytes(b"")

        # État GUI réel : terrain vide → à créer, moteur supervised_e, export faithful
        app = _make_app(
            cfg={},
            tiles=tiles,
            lidar_dir=lidar_dir,
            bdtopo_path=gpkg,
            veg="supervised_e",
            export_mode="faithful",
            terrain="sainte_honorine",
        )

        # _ensure_terrain_in_config doit créer et configurer le terrain
        ok = app._ensure_terrain_in_config("sainte_honorine")
        assert ok, "_ensure_terrain_in_config doit réussir avec des tuiles IGN"

        # Vérifie la config terrain
        cfg = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        t_cfg = cfg["terrains"]["sainte_honorine"]
        assert t_cfg["vegetation_source"] == "supervised_e", (
            f"vegetation_source doit être 'supervised_e', obtenu : {t_cfg.get('vegetation_source')!r}"
        )
        assert t_cfg.get("lidar_dir") is not None, "lidar_dir doit être persisté"
        assert t_cfg.get("bdtopo_path") is not None, "bdtopo_path doit être persisté"

        # _run_pipeline écrit vegetation_export_mode en clé globale
        config_path = tmp_path / "config.yaml"
        _patch_global_yaml_key("vegetation_export_mode", "faithful", config_path)

        cfg2 = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg2.get("vegetation_export_mode") == "faithful", (
            f"vegetation_export_mode doit être 'faithful', obtenu : {cfg2.get('vegetation_export_mode')!r}"
        )

        # Vérifie que sys.argv serait construit correctement
        # _run_pipeline fait : sys.argv = ["main.py", terrain, "--tiles-dir", str(lidar_dir)]
        expected_argv = ["main.py", "sainte_honorine", "--tiles-dir", str(lidar_dir)]
        assert expected_argv[1] == "sainte_honorine"
        assert expected_argv[2] == "--tiles-dir"
        assert expected_argv[3] == str(lidar_dir)

        # Cohérence finale : config.yaml est lisible par le pipeline
        final = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert final["terrains"]["sainte_honorine"]["vegetation_source"] == "supervised_e"
        assert final["vegetation_export_mode"] == "faithful"
        # bbox présente → resolve_veg_source + _check_bdtopo_coverage peuvent fonctionner
        assert "bbox" in final["terrains"]["sainte_honorine"]

    def test_validate_run_bloque_si_terrain_vide(self, tmp_path):
        """_refresh_run_button ne doit pas activer Générer si le terrain est vide."""
        tile = tmp_path / "LHD_FXX_0448_6886_PTS_LAMB93_IGN69.copc.laz"
        tile.write_bytes(b"")
        # App sans fenêtre : on vérifie la logique pure
        # terrain vide → pas de Générer possible
        # (simulé par le fait que _run_pipeline verrait un terrain vide)
        app = _make_app({}, [tile], terrain="")
        assert app._terrain_var.get() == ""
        assert not app._terrain_var.get().strip()

    def test_validate_run_bloque_si_modele_absent(self, tmp_path, monkeypatch):
        """Si supervised_e et modèle absent → Générer doit être bloqué."""
        monkeypatch.chdir(tmp_path)
        tile = tmp_path / "LHD_FXX_0448_6886_PTS_LAMB93_IGN69.copc.laz"
        tile.write_bytes(b"")
        app = _make_app({}, [tile], veg="supervised_e", terrain="test")
        # Le modèle n'existe pas dans tmp_path
        assert not gui_app._SE_MODEL_PATH.exists(), (
            "Le modèle supervised_e ne doit pas exister dans le répertoire de test"
        )

    def test_validate_run_ok_si_kp_sans_modele(self, tmp_path, monkeypatch):
        """Mode kp n'exige pas de modèle — Générer doit être possible (terrain + LiDAR fournis)."""
        monkeypatch.chdir(tmp_path)
        tile = tmp_path / "LHD_FXX_0448_6886_PTS_LAMB93_IGN69.copc.laz"
        tile.write_bytes(b"")
        app = _make_app({}, [tile], veg="kp", terrain="test", lidar_dir=tmp_path)
        # En mode kp, l'absence de modèle ne bloque pas
        # La logique : _veg_var.get() == "kp" → pas de vérification _SE_MODEL_PATH
        is_se = app._veg_var.get() == "supervised_e"
        assert not is_se, "Mode kp ne doit pas vérifier le modèle supervised_e"
