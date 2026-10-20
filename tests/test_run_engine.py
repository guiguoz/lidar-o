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

from src.run_engine import _build_ini, build_ini_content


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
