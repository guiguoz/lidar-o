"""Tests du résolveur de mode pipeline et du routage P1a."""
from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from src.pipeline_mode import resolve_veg_source


# ── Résolveur ─────────────────────────────────────────────────────────────────

class TestResolveVegSource:
    def _cfg(self, **kw):
        return {"terrains": {"t": kw}}

    def test_kp(self):
        assert resolve_veg_source("t", self._cfg(vegetation_source="kp")) == "kp"

    def test_hag(self):
        assert resolve_veg_source("t", self._cfg(vegetation_source="hag")) == "hag"

    def test_absent_key_returns_kp(self):
        assert resolve_veg_source("t", self._cfg()) == "kp"

    def test_absent_key_emits_info_kp_defaut(self, caplog):
        with caplog.at_level(logging.INFO, logger="src.pipeline_mode"):
            resolve_veg_source("t", self._cfg())
        assert "KP par défaut" in caplog.text
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError, match="valeur inconnue"):
            resolve_veg_source("t", self._cfg(vegetation_source="pdal"))

    def test_absent_terrain_returns_kp(self):
        assert resolve_veg_source("absent", {"terrains": {}}) == "kp"

    def test_global_vegetation_source_ignored(self):
        """La clé globale vegetation.source ne doit pas influencer la résolution."""
        cfg = {
            "vegetation": {"source": "kp"},
            "terrains": {"t": {}},
        }
        assert resolve_veg_source("t", cfg) == "kp"


# ── Routage _cmd_run (Test 3 et Test 8 du plan) ───────────────────────────────

def _build_cfg(tmp_path, vegetation_source=None):
    terrain_cfg: dict = {"output_dir": str(tmp_path / "output")}
    if vegetation_source is not None:
        terrain_cfg["vegetation_source"] = vegetation_source
    return {"terrains": {"demo": terrain_cfg}}


class TestCmdRunRouting:
    def _run(self, tmp_path, vegetation_source=None, extra_argv=None):
        """Lance _cmd_run avec étapes mockées. Retourne le dict de mocks."""
        import main as m

        cfg = _build_cfg(tmp_path, vegetation_source)
        # _cmd_run parse sys.argv directement (main() retire "run" avant de l'appeler)
        argv = ["main.py", "demo", "--skip-check", "--from-step", "relief"]
        if extra_argv:
            argv += extra_argv

        mocks: dict[str, MagicMock] = {
            name: MagicMock()
            for name in [
                "step_fetch", "step_pdal", "step_process_hag",
                "step_vegetation_kp", "step_vegetation", "step_mask",
                "step_assemble", "step_qa", "step_check_config",
            ]
        }
        mocks["step_relief"] = MagicMock(return_value="ok")

        with (
            patch.object(m, "_load_config", return_value=cfg),
            patch("src.check_terrain.cmd_check", return_value=True),
            patch.object(sys, "argv", argv),
            patch.multiple("main", **mocks),
        ):
            m._cmd_run()

        return mocks

    def test_kp_mode_skips_pdal_and_hag(self, tmp_path):
        mocks = self._run(tmp_path, vegetation_source="kp")
        mocks["step_pdal"].assert_not_called()
        mocks["step_process_hag"].assert_not_called()

    def test_kp_mode_skips_vegetation_and_mask(self, tmp_path):
        mocks = self._run(tmp_path, vegetation_source="kp")
        mocks["step_vegetation"].assert_not_called()
        mocks["step_mask"].assert_not_called()

    def test_kp_mode_runs_vegetation_kp(self, tmp_path):
        mocks = self._run(tmp_path, vegetation_source="kp")
        mocks["step_vegetation_kp"].assert_called_once()

    def test_absent_key_emits_info_kp_defaut(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="src.pipeline_mode"):
            self._run(tmp_path, vegetation_source=None)
        assert "KP par défaut" in caplog.text

    def test_absent_key_routes_to_kp_not_hag(self, tmp_path):
        mocks = self._run(tmp_path, vegetation_source=None)
        mocks["step_vegetation"].assert_not_called()
        mocks["step_mask"].assert_not_called()
        mocks["step_pdal"].assert_not_called()
        mocks["step_vegetation_kp"].assert_called_once()

    def test_kp_skip_pdal_is_noop(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO):
            mocks = self._run(
                tmp_path, vegetation_source="kp", extra_argv=["--skip-pdal"]
            )
        assert "--skip-pdal ignoré" in caplog.text
        mocks["step_pdal"].assert_not_called()

    def test_kp_from_step_pdal_exits(self, tmp_path):
        import main as m

        cfg = _build_cfg(tmp_path, vegetation_source="kp")
        mocks: dict[str, MagicMock] = {
            name: MagicMock()
            for name in [
                "step_fetch", "step_pdal", "step_process_hag", "step_relief",
                "step_vegetation_kp", "step_vegetation", "step_mask",
                "step_assemble", "step_qa", "step_check_config",
            ]
        }
        with (
            patch.object(m, "_load_config", return_value=cfg),
            patch("src.check_terrain.cmd_check", return_value=True),
            patch.object(sys, "argv", ["main.py", "demo", "--skip-check", "--from-step", "pdal"]),
            patch.multiple("main", **mocks),
        ):
            with pytest.raises(SystemExit):
                m._cmd_run()

    def test_hag_mode_runs_all_steps(self, tmp_path):
        mocks = self._run(tmp_path, vegetation_source="hag")
        mocks["step_vegetation"].assert_called_once()
        mocks["step_mask"].assert_called_once()
        mocks["step_vegetation_kp"].assert_called_once()


# ── P1b : suppression de la clé globale vestigiale vegetation.source ──────────

_ETATS = {
    "kp": {"vegetation_source": "kp"},
    "hag": {"vegetation_source": "hag"},
    "defaut": {},  # pas de clé terrain → KP par défaut
}


class TestP1bCleGlobaleSupprimee:
    """Retirer vegetation.source ne doit changer la résolution d'aucun état."""

    @pytest.mark.parametrize("etat", sorted(_ETATS))
    @pytest.mark.parametrize("ancienne_valeur", [None, "pdal", "kp", "hag"])
    def test_resolution_independante_de_la_cle_globale(self, etat, ancienne_valeur):
        terrain_cfg = dict(_ETATS[etat])
        base = {"terrains": {"t": dict(terrain_cfg)}, "vegetation": {"resolution_m": 1.0}}
        avec_globale = {
            "terrains": {"t": dict(terrain_cfg)},
            "vegetation": {"resolution_m": 1.0},
        }
        if ancienne_valeur is not None:
            avec_globale["vegetation"]["source"] = ancienne_valeur
        assert resolve_veg_source("t", avec_globale) == resolve_veg_source("t", base)

    def test_trois_etats_resolus_sans_cle_globale(self):
        cfg = {"vegetation": {"resolution_m": 1.0}, "terrains": {
            "k": {"vegetation_source": "kp"},
            "h": {"vegetation_source": "hag"},
            "l": {},
        }}
        assert resolve_veg_source("k", cfg) == "kp"
        assert resolve_veg_source("h", cfg) == "hag"
        assert resolve_veg_source("l", cfg) == "kp"

    def test_config_reelle_sans_vegetation_source(self):
        import pathlib
        import yaml

        racine = pathlib.Path(__file__).resolve().parents[1]
        cfg = yaml.safe_load((racine / "config.yaml").read_text(encoding="utf-8"))
        assert "source" not in cfg["vegetation"], "clé globale vegetation.source réintroduite"

    def test_config_reelle_inventaire_arbitre(self):
        """Tous les terrains restants sont en KP (explicite ou par défaut)."""
        import pathlib
        import yaml

        racine = pathlib.Path(__file__).resolve().parents[1]
        cfg = yaml.safe_load((racine / "config.yaml").read_text(encoding="utf-8"))
        terrains = cfg.get("terrains") or {}
        attendu = {n: "kp" for n in terrains}
        assert {n: resolve_veg_source(n, cfg) for n in terrains} == attendu


# ── PLAN 4 (option A) : contrat figé des trois états ─────────────────────────
#
# KP par défaut (clé absente = kp). hag = chaîne HAG explicite, message INFO.
# vegetation_source: "hag" ne signifie PAS « HAG
# uniquement » et ne fait PAS alimenter l'OMAP par HAG.

_LOGGER = "src.pipeline_mode"


class TestContratModesPlan4:
    def test_hag_emet_info_et_pas_de_warning(self, caplog):
        cfg = {"terrains": {"t": {"vegetation_source": "hag"}}}
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            assert resolve_veg_source("t", cfg) == "hag"
        niveaux = [r.levelno for r in caplog.records if r.name == _LOGGER]
        assert logging.INFO in niveaux
        assert logging.WARNING not in niveaux
        assert "mode HAG explicite" in caplog.text
        assert "migration en attente" not in caplog.text

    def test_absente_emet_info_kp_defaut_et_pas_de_message_hag(self, caplog):
        cfg = {"terrains": {"t": {}}}
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            assert resolve_veg_source("t", cfg) == "kp"
        niveaux = [r.levelno for r in caplog.records if r.name == _LOGGER]
        assert logging.WARNING not in niveaux
        assert "KP par défaut" in caplog.text
        assert "mode HAG explicite" not in caplog.text

    def test_kp_silencieux(self, caplog):
        cfg = {"terrains": {"t": {"vegetation_source": "kp"}}}
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            assert resolve_veg_source("t", cfg) == "kp"
        assert [r for r in caplog.records if r.name == _LOGGER] == []

    def test_hag_chaine_hag_et_absente_routee_kp(self, tmp_path):
        """hag exécute la chaîne HAG ; une clé absente (KP par défaut) ne l'exécute pas.
        Les deux appellent step_vegetation_kp (qui décide ensuite selon le mode)."""
        run = TestCmdRunRouting()._run
        mocks_hag = run(tmp_path / "hag", vegetation_source="hag")
        mocks_abs = run(tmp_path / "abs", vegetation_source=None)
        assert mocks_hag["step_vegetation"].call_count == 1
        assert mocks_hag["step_mask"].call_count == 1
        assert mocks_abs["step_vegetation"].call_count == 0
        assert mocks_abs["step_mask"].call_count == 0
        assert mocks_hag["step_vegetation_kp"].call_count == 1
        assert mocks_abs["step_vegetation_kp"].call_count == 1

    def test_kp_desactive_la_branche_hag_seule(self, tmp_path):
        mocks = TestCmdRunRouting()._run(tmp_path, vegetation_source="kp")
        assert mocks["step_vegetation"].call_count == 0
        assert mocks["step_mask"].call_count == 0
        assert mocks["step_pdal"].call_count == 0
        assert mocks["step_process_hag"].call_count == 0
        assert mocks["step_vegetation_kp"].call_count == 1

    def test_docstring_module_fige_le_contrat(self):
        import src.pipeline_mode as pm

        doc = pm.__doc__
        assert "ne signifie PAS" in doc
        assert "HAG uniquement" in doc
        assert "vegetation_kp.gpkg" in doc
        assert "KP par défaut" in doc
        assert "erreur explicite" in doc

    def test_assemble_lit_vegetation_kp_et_non_hag(self):
        """L'OMAP ne lit que vegetation_kp.gpkg ; vegetation.gpkg (HAG) n'y entre pas."""
        import inspect
        import main as m

        src = inspect.getsource(m.step_assemble)
        assert "vegetation_kp.gpkg" in src
        assert "vegetation.gpkg" not in src

    def test_documentation_fige_le_contrat(self):
        import pathlib

        racine = pathlib.Path(__file__).resolve().parents[1]
        doc = (racine / "docs" / "pipeline_vegetation_kp.md").read_text(encoding="utf-8")
        assert "## Contrat des modes `vegetation_source` (PLAN 4, KP par défaut)" in doc
        assert "ne signifie pas HAG uniquement" in doc
        assert "HAG n'alimente pas l'OMAP" in doc


class TestGardeStepVegetationKp:
    """Mode KP sans out_kp_<terrain>/ : erreur explicite (et non passage silencieux)."""

    def test_kp_sans_out_kp_leve_erreur(self):
        import main as m

        cfg = {"terrains": {"zz_test_kp": {"vegetation_source": "kp"}}}
        with pytest.raises(RuntimeError, match="mode KP"):
            m.step_vegetation_kp("zz_test_kp", cfg, force=False)

    def test_defaut_sans_out_kp_leve_erreur(self):
        import main as m

        cfg = {"terrains": {"zz_test_def": {}}}
        with pytest.raises(RuntimeError, match="mode KP"):
            m.step_vegetation_kp("zz_test_def", cfg, force=False)

    def test_hag_sans_out_kp_ignore_silencieusement(self, caplog):
        import main as m

        cfg = {"terrains": {"zz_test_hag": {"vegetation_source": "hag"}}}
        with caplog.at_level(logging.INFO):
            m.step_vegetation_kp("zz_test_hag", cfg, force=False)
        assert "étape ignorée (mode hag)" in caplog.text
