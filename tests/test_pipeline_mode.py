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

    def test_legacy_no_key_returns_none(self):
        assert resolve_veg_source("t", self._cfg()) is None

    def test_legacy_emits_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.pipeline_mode"):
            resolve_veg_source("t", self._cfg())
        assert "vegetation_source" in caplog.text
        assert "comportement hérité" in caplog.text

    def test_unknown_value_falls_back_legacy(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.pipeline_mode"):
            result = resolve_veg_source("t", self._cfg(vegetation_source="pdal"))
        assert result is None
        assert "non reconnu" in caplog.text

    def test_absent_terrain_returns_none(self):
        assert resolve_veg_source("absent", {"terrains": {}}) is None

    def test_global_vegetation_source_ignored(self):
        """La clé globale vegetation.source ne doit pas influencer la résolution."""
        cfg = {
            "vegetation": {"source": "kp"},
            "terrains": {"t": {}},
        }
        assert resolve_veg_source("t", cfg) is None


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

    def test_legacy_emits_warning(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="src.pipeline_mode"):
            self._run(tmp_path, vegetation_source=None)
        assert "comportement hérité" in caplog.text

    def test_legacy_runs_vegetation_and_mask(self, tmp_path):
        mocks = self._run(tmp_path, vegetation_source=None)
        mocks["step_vegetation"].assert_called_once()
        mocks["step_mask"].assert_called_once()

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
