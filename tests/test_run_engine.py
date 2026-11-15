"""Tests pour src/run_engine.py — ini minimal et build_ini_content.

Bug 2 : _build_ini branche minimale (sans base_ini) omettait lightgreentone
et medianboxsize2 même quand ils étaient fournis.

Bug 1 : build_ini_content (ex-_build_ini) permet à step_relief de détecter
qu'un changement de config.yaml rend les DXF existants périmés même si
leur mtime est postérieur aux LAZ.
"""
from __future__ import annotations

import pathlib
import textwrap

import pytest

from src.run_engine import _build_ini, _resolve_base_ini, build_ini_content, generate_ini, run_kp


# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_ini(tmp_path: pathlib.Path, content: str) -> pathlib.Path:
    p = tmp_path / "pullauta.ini"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ── Bug 2 : branche minimale (pas de base_ini) ───────────────────────────────

class TestBuildIniMinimal:
    """_build_ini sans base_ini — paramètres de rendu propagés."""

    def test_lightgreentone_absent_when_none(self):
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"), base_ini=None)
        assert "lightgreentone" not in content

    def test_lightgreentone_present_when_provided(self):
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"),
                             base_ini=None, lightgreentone=160)
        assert "lightgreentone=160" in content

    def test_medianboxsize2_absent_when_none(self):
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"), base_ini=None)
        assert "medianboxsize2" not in content

    def test_medianboxsize2_present_when_provided(self):
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"),
                             base_ini=None, medianboxsize2=16)
        assert "medianboxsize2=16" in content

    def test_both_provided(self):
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"),
                             base_ini=None, lightgreentone=160, medianboxsize2=16)
        assert "lightgreentone=160" in content
        assert "medianboxsize2=16" in content

    def test_mandatory_keys_always_present(self):
        content = _build_ini(pathlib.Path("lazdir"), pathlib.Path("outdir"), base_ini=None)
        assert "batch=1" in content
        assert "lazfolder" in content
        assert "batchoutfolder" in content


# ── Bug 2 : branche base_ini ─────────────────────────────────────────────────

class TestBuildIniWithBase:
    """_build_ini avec base_ini — overrides appliqués."""

    def test_lightgreentone_replaced(self, tmp_path):
        base = _base_ini(tmp_path, """\
            batch=0
            lazfolder=/old
            batchoutfolder=/old
            lightgreentone=200
        """)
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"),
                             base_ini=base, lightgreentone=160)
        assert "lightgreentone=160" in content
        assert "lightgreentone=200" not in content

    def test_medianboxsize2_replaced(self, tmp_path):
        base = _base_ini(tmp_path, """\
            batch=0
            lazfolder=/old
            batchoutfolder=/old
            medianboxsize2=1
        """)
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"),
                             base_ini=base, medianboxsize2=16)
        assert "medianboxsize2=16" in content
        assert "medianboxsize2=1\n" not in content

    def test_unrelated_lines_preserved(self, tmp_path):
        base = _base_ini(tmp_path, """\
            batch=0
            lazfolder=/old
            batchoutfolder=/old
            greenground=0.9
            medianboxsize=9
        """)
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"), base_ini=base)
        assert "greenground=0.9" in content
        assert "medianboxsize=9" in content

    def test_base_ini_not_found_falls_to_minimal(self, tmp_path):
        missing = tmp_path / "nonexistent.ini"
        content = _build_ini(pathlib.Path("laz"), pathlib.Path("out"),
                             base_ini=missing, lightgreentone=160)
        assert "lightgreentone=160" in content
        assert "batch=1" in content


# ── Bug 1 : build_ini_content ─────────────────────────────────────────────────

class TestBuildIniContent:
    """build_ini_content — wrapper sans écriture disque.

    Permet à step_relief de comparer l'ini existant avec ce que le run
    produirait, et de détecter les changements de config.yaml.
    """

    def test_returns_string(self, tmp_path):
        result = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                   root=tmp_path)
        assert isinstance(result, str)

    def test_deterministic(self, tmp_path):
        r1 = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                               root=tmp_path, lightgreentone=160, medianboxsize2=16)
        r2 = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                               root=tmp_path, lightgreentone=160, medianboxsize2=16)
        assert r1 == r2

    def test_changes_with_lightgreentone(self, tmp_path):
        r160 = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                  root=tmp_path, lightgreentone=160)
        r200 = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                  root=tmp_path, lightgreentone=200)
        assert r160 != r200

    def test_changes_with_medianboxsize2(self, tmp_path):
        r1 = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                root=tmp_path, medianboxsize2=1)
        r16 = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                 root=tmp_path, medianboxsize2=16)
        assert r1 != r16

    def test_same_as_generate_ini_content(self, tmp_path):
        """build_ini_content == contenu que generate_ini écrirait.

        root et work_dir sont distincts pour éviter que generate_ini crée
        root/pullauta.ini qui serait ensuite lu par build_ini_content comme base.
        """
        from src.run_engine import generate_ini
        root_dir = tmp_path / "root"
        work_dir = tmp_path / "work"
        root_dir.mkdir(); work_dir.mkdir()
        # Calcule le contenu AVANT d'écrire le fichier
        expected = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                      root=root_dir,
                                      lightgreentone=160, medianboxsize2=16)
        ini_path = generate_ini(
            pathlib.Path("laz"), pathlib.Path("out"),
            work_dir=work_dir, root=root_dir,
            lightgreentone=160, medianboxsize2=16,
        )
        assert ini_path.read_text(encoding="utf-8") == expected

    def test_ini_comparison_detects_config_change(self, tmp_path):
        """Scénario Bug 1 : ini écrit avec medianboxsize2=1, config modifié à 16.

        Le cache relief doit comparer l'ini existant avec ce que le run
        produirait : les deux chaînes diffèrent → pas de skip.
        """
        # Simuler un ini issu d'un run précédent (medianboxsize2=1)
        old_ini_content = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                             root=tmp_path, medianboxsize2=1)
        ini_file = tmp_path / "out_kp" / "pullauta.ini"
        ini_file.parent.mkdir()
        ini_file.write_text(old_ini_content, encoding="utf-8")

        # Config actuelle : medianboxsize2=16
        new_ini_content = build_ini_content(pathlib.Path("laz"), pathlib.Path("out"),
                                             root=tmp_path, medianboxsize2=16)
        assert ini_file.read_text(encoding="utf-8") != new_ini_content, (
            "L'ini devrait différer après changement de medianboxsize2 — cache doit être invalidé"
        )


# ── _resolve_base_ini ────────────────────────────────────────────────────────

class TestResolveBaseIni:
    def test_prefers_pullauta_ini_over_default(self, tmp_path):
        (tmp_path / "pullauta.ini").write_text("batch=0\n", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "pullauta_default.ini").write_text("batch=0\n", encoding="utf-8")
        assert _resolve_base_ini(tmp_path) == tmp_path / "pullauta.ini"

    def test_falls_back_to_default(self, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "pullauta_default.ini").write_text("batch=0\n", encoding="utf-8")
        assert _resolve_base_ini(tmp_path) == tmp_path / "assets" / "pullauta_default.ini"

    def test_returns_none_when_absent(self, tmp_path):
        assert _resolve_base_ini(tmp_path) is None

    def test_ignores_assets_dir_without_ini(self, tmp_path):
        (tmp_path / "assets").mkdir()
        assert _resolve_base_ini(tmp_path) is None


# ── generate_ini — nouveau comportement ──────────────────────────────────────

class TestGenerateIniWithDefault:
    def test_uses_default_template_when_present(self, tmp_path):
        """assets/pullauta_default.ini : paramètres du template inclus dans l'ini généré."""
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "pullauta_default.ini").write_text(
            "batch=0\nundergrowth=0.35\nthresold1=0.20|3|0.1\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        ini = generate_ini(
            tiles_dir=tmp_path / "laz",
            output_dir=out_dir,
            work_dir=out_dir,
            root=tmp_path,
        )
        content = ini.read_text(encoding="utf-8")
        assert "undergrowth=0.35" in content
        assert "thresold1=0.20|3|0.1" in content
        assert "batch=1" in content

    def test_overrides_paths_in_template(self, tmp_path):
        """lazfolder/batchoutfolder sont remplacés par les chemins absolus."""
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "pullauta_default.ini").write_text(
            "batch=0\nlazfolder=./in\nbatchoutfolder=./out\n",
            encoding="utf-8",
        )
        laz_dir = tmp_path / "laz"
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        ini = generate_ini(
            tiles_dir=laz_dir,
            output_dir=out_dir,
            work_dir=out_dir,
            root=tmp_path,
        )
        content = ini.read_text(encoding="utf-8")
        assert "lazfolder=./in" not in content
        assert str(laz_dir.resolve()).replace("\\", "/") in content

    def test_warns_when_no_template(self, tmp_path, caplog):
        """Sans template : avertissement logué."""
        import logging
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with caplog.at_level(logging.WARNING, logger="src.run_engine"):
            generate_ini(
                tiles_dir=tmp_path / "laz",
                output_dir=out_dir,
                work_dir=out_dir,
                root=tmp_path,
            )
        assert any("pullauta_default.ini" in r.message for r in caplog.records)


# ── run_kp — capture stdout/stderr + détection panique ───────────────────────

class TestRunKp:
    from types import SimpleNamespace

    def _mock_result(self, returncode=0, stdout="", stderr=""):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def test_success_writes_log(self, tmp_path):
        """Succès : kp_run.log écrit avec sortie KP."""
        from unittest.mock import patch
        ok_output = "Karttapullautin v2.12.1\nAll done!\n"
        with patch("subprocess.run", return_value=self._mock_result(stdout=ok_output)):
            run_kp(tmp_path / "pullauta.exe", tmp_path)
        log = (tmp_path / "kp_run.log").read_text(encoding="utf-8")
        assert "All done!" in log

    def test_nonzero_returncode_raises(self, tmp_path):
        """Code retour ≠ 0 → RuntimeError mentionnant le code."""
        from unittest.mock import patch
        with patch("subprocess.run", return_value=self._mock_result(returncode=1, stdout="err")):
            with pytest.raises(RuntimeError, match="code retour 1"):
                run_kp(tmp_path / "pullauta.exe", tmp_path)

    def test_panic_on_stdout_raises(self, tmp_path):
        """Panique sur stdout avec exit=0 → RuntimeError signalant la panique."""
        from unittest.mock import patch
        panic = (
            "thread 'main' panicked at src/config.rs:174:63:\n"
            "called `Option::unwrap()` on a `None` value\n"
        )
        with patch("subprocess.run", return_value=self._mock_result(stdout=panic)):
            with pytest.raises(RuntimeError, match="paniqué"):
                run_kp(tmp_path / "pullauta.exe", tmp_path)

    def test_panic_on_stderr_raises(self, tmp_path):
        """Panique sur stderr avec exit=0 → RuntimeError."""
        from unittest.mock import patch
        panic = "thread 'main' panicked at src/config.rs:174:63:\n"
        with patch("subprocess.run", return_value=self._mock_result(stderr=panic)):
            with pytest.raises(RuntimeError, match="paniqué"):
                run_kp(tmp_path / "pullauta.exe", tmp_path)

    def test_panic_log_path_in_message(self, tmp_path):
        """Le message d'erreur panique mentionne kp_run.log."""
        from unittest.mock import patch
        panic = "thread 'main' panicked at src/config.rs:1:\n"
        with patch("subprocess.run", return_value=self._mock_result(stdout=panic)):
            with pytest.raises(RuntimeError) as exc_info:
                run_kp(tmp_path / "pullauta.exe", tmp_path)
        assert "kp_run.log" in str(exc_info.value)

    def test_panic_writes_log_before_raising(self, tmp_path):
        """kp_run.log est écrit même en cas de panique."""
        from unittest.mock import patch
        panic = "thread 'main' panicked at src/config.rs:1:\ncalled unwrap on None\n"
        with patch("subprocess.run", return_value=self._mock_result(stdout=panic)):
            with pytest.raises(RuntimeError):
                run_kp(tmp_path / "pullauta.exe", tmp_path)
        log = (tmp_path / "kp_run.log").read_text(encoding="utf-8")
        assert "panicked" in log

    def test_returncode_in_log(self, tmp_path):
        """kp_run.log contient le code de retour."""
        from unittest.mock import patch
        with patch("subprocess.run", return_value=self._mock_result(returncode=0, stdout="ok\n")):
            run_kp(tmp_path / "pullauta.exe", tmp_path)
        log = (tmp_path / "kp_run.log").read_text(encoding="utf-8")
        assert "returncode: 0" in log
