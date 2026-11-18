"""Tests unitaires de main.step_fetch().

main.py est importable sans effet de bord (constantes module + garde __main__).
Tous les tests sont autonomes : monkeypatch main.DATA vers tmp_path,
main._run_fetch_script intercepté — subprocess n'est jamais réellement exécuté.
"""
import pathlib
import time

import pytest

import main


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _cfg(bdtopo_path: str | None = None, departement: str | None = None) -> dict:
    t: dict = {}
    if bdtopo_path is not None:
        t["bdtopo_path"] = bdtopo_path
    if departement is not None:
        t["departement"] = departement
    return {"terrains": {"mon_terrain": t}}


@pytest.fixture()
def fetch_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Redirige main.DATA vers tmp_path et intercepte _run_fetch_script."""
    monkeypatch.setattr(main, "DATA", tmp_path)
    calls: list[str] = []

    def _fake_run(terrain: str) -> None:
        calls.append(terrain)

    monkeypatch.setattr(main, "_run_fetch_script", _fake_run)
    return tmp_path, calls


# ── Cas 1 : bdtopo_path valide + departement absent → fetch lancé ─────────────

def test_bdtopo_path_no_dept_fetch_launched(
    fetch_env, tmp_path: pathlib.Path
) -> None:
    """bdtopo_path valide, departement absent, sortie inexistante → fetch lancé (cas critique)."""
    data_dir, calls = fetch_env
    source = tmp_path / "BDTOPO_D014.gpkg"
    source.write_text("gpkg")

    main.step_fetch("mon_terrain", _cfg(bdtopo_path=str(source)), force=False)
    assert calls == ["mon_terrain"]


# ── Cas 2 : bdtopo_path valide + sortie à jour → SKIP ────────────────────────

def test_bdtopo_path_output_fresh_skip(
    fetch_env, tmp_path: pathlib.Path
) -> None:
    """bdtopo_path valide + sortie plus récente que source → SKIP, pas d'appel subprocess."""
    data_dir, calls = fetch_env
    source = tmp_path / "BDTOPO_D014.gpkg"
    source.write_text("gpkg")

    out = data_dir / "mon_terrain_bdtopo.gpkg"
    out.write_text("out")
    # Forcer la sortie plus récente que source
    t = source.stat().st_mtime + 10
    import os; os.utime(out, (t, t))

    main.step_fetch("mon_terrain", _cfg(bdtopo_path=str(source)), force=False)
    assert calls == []


# ── Cas 3 : bdtopo_path valide + sortie périmée → relance ─────────────────────

def test_bdtopo_path_output_stale_relaunched(
    fetch_env, tmp_path: pathlib.Path
) -> None:
    """bdtopo_path valide + sortie plus ancienne que source → relance."""
    data_dir, calls = fetch_env
    source = tmp_path / "BDTOPO_D014.gpkg"
    source.write_text("gpkg")

    out = data_dir / "mon_terrain_bdtopo.gpkg"
    out.write_text("old")
    # Forcer la sortie plus ancienne que source
    import os; os.utime(out, (0, 0))

    main.step_fetch("mon_terrain", _cfg(bdtopo_path=str(source)), force=False)
    assert calls == ["mon_terrain"]


# ── Cas 4 : bdtopo_path configuré mais fichier absent → erreur, pas de subprocess

def test_bdtopo_path_absent_file_exits(
    fetch_env, tmp_path: pathlib.Path
) -> None:
    """bdtopo_path configuré mais le fichier n'existe pas → sys.exit, aucun appel subprocess."""
    data_dir, calls = fetch_env
    absent = tmp_path / "nonexistent.gpkg"

    with pytest.raises(SystemExit):
        main.step_fetch("mon_terrain", _cfg(bdtopo_path=str(absent)), force=False)
    assert calls == []


# ── Cas 5 : departement seul → source résolue via find_gpkg ───────────────────

def test_departement_only_find_gpkg_used(
    fetch_env, tmp_path: pathlib.Path
) -> None:
    """departement seul → find_gpkg cherche dans data/bdtopo/, sortie périmée → fetch lancé."""
    data_dir, calls = fetch_env
    bdtopo_dir = data_dir / "bdtopo"
    bdtopo_dir.mkdir()
    source = bdtopo_dir / "BDTOPO_3-5_D014_2026.gpkg"
    source.write_text("gpkg")

    out = data_dir / "mon_terrain_bdtopo.gpkg"
    out.write_text("old")
    import os; os.utime(out, (0, 0))

    main.step_fetch("mon_terrain", _cfg(departement="14"), force=False)
    assert calls == ["mon_terrain"]


def test_departement_only_output_fresh_skip(
    fetch_env, tmp_path: pathlib.Path
) -> None:
    """departement seul + sortie à jour → SKIP."""
    data_dir, calls = fetch_env
    bdtopo_dir = data_dir / "bdtopo"
    bdtopo_dir.mkdir()
    source = bdtopo_dir / "BDTOPO_3-5_D014_2026.gpkg"
    source.write_text("gpkg")

    out = data_dir / "mon_terrain_bdtopo.gpkg"
    out.write_text("out")
    import os
    t = source.stat().st_mtime + 10
    os.utime(out, (t, t))

    main.step_fetch("mon_terrain", _cfg(departement="14"), force=False)
    assert calls == []


# ── Cas 6 : ni bdtopo_path ni departement → skip ──────────────────────────────

def test_no_bdtopo_no_dept_skip(fetch_env) -> None:
    """Ni bdtopo_path ni departement → étape ignorée, pas d'appel subprocess."""
    data_dir, calls = fetch_env
    main.step_fetch("mon_terrain", _cfg(), force=False)
    assert calls == []
