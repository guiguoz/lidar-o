"""Résolution des chemins portables — dev et distribution Windows.

Priorités pour get_config_path() :
  1. Chemin explicite (CLI --config ou tests)
  2. %APPDATA%\\LidarO\\config.yaml si config_default.yaml présent (distribution)
  3. APP_DIR/config.yaml (utilisation depuis les sources)
"""
from __future__ import annotations

import os
import pathlib

_SRC_DIR = pathlib.Path(__file__).parent.resolve()   # src/
_APP_DIR = _SRC_DIR.parent                            # racine du projet (dev) ou app/ (distrib)
_DIST_ROOT = _APP_DIR.parent                          # LidarO-Windows-x64/ ou identique en dev


def get_config_path(explicit: pathlib.Path | None = None) -> pathlib.Path:
    """Retourne le chemin vers config.yaml selon le contexte d'exécution."""
    if explicit is not None:
        return explicit
    dist_default = _APP_DIR / "config_default.yaml"
    if dist_default.exists():
        p = _get_user_data_dir() / "config.yaml"
        if not p.exists():
            tmp = p.with_suffix(".tmp")
            tmp.write_text(dist_default.read_text(encoding="utf-8"), encoding="utf-8")
            tmp.rename(p)
        return p
    dev_path = _APP_DIR / "config.yaml"
    if not dev_path.exists():
        raise FileNotFoundError(f"config.yaml introuvable ({dev_path})")
    return dev_path


def is_distribution() -> bool:
    """True si le code tourne dans le paquet distribué (setup.bat présent adjacent à app/)."""
    return (_DIST_ROOT / "setup.bat").exists()


def get_model_path() -> pathlib.Path:
    """Retourne le chemin vers model_e_final.pkl selon le contexte d'exécution.

    En distribution (is_distribution()) : toujours models/ adjacent à app/,
    même si le fichier est absent — le chemin est correct pour le message d'erreur.
    En développement : experiments/loto_v1/final_model/ (ou models/ si présent en test).
    """
    dist = _DIST_ROOT / "models" / "model_e_final.pkl"
    if is_distribution() or dist.exists():
        return dist
    return _APP_DIR / "experiments" / "loto_v1" / "final_model" / "model_e_final.pkl"


def get_assets_dir() -> pathlib.Path:
    """Répertoire assets/ — lecture seule en distribution, inscriptible en dev."""
    return _APP_DIR / "assets"


def get_app_version() -> str:
    """Version applicative depuis VERSION.txt (distribution) ou 'dev'."""
    version_file = _DIST_ROOT / "VERSION.txt"
    if version_file.exists():
        v = version_file.read_text(encoding="utf-8").strip()
        return v if v else "dev"
    return "dev"


def get_build_commit() -> str | None:
    """Hash court du commit de build : COMMIT.txt (distribution) ou git live (dev)."""
    commit_file = _DIST_ROOT / "COMMIT.txt"
    if commit_file.exists():
        v = commit_file.read_text(encoding="utf-8").strip()
        return v if v else None
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "-C", str(_APP_DIR), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=5,
            text=True,
        ).strip()
        return sha or None
    except Exception:
        return None


def get_runtime_version() -> str | None:
    """Version du runtime Python embarqué (python_env_version.txt) ou None."""
    rv = _DIST_ROOT / "python_env_version.txt"
    if rv.exists():
        v = rv.read_text(encoding="utf-8").strip()
        return v if v else None
    return None


def _get_user_data_dir() -> pathlib.Path:
    base = pathlib.Path(os.environ.get("APPDATA", "~")).expanduser() / "LidarO"
    base.mkdir(parents=True, exist_ok=True)
    return base
