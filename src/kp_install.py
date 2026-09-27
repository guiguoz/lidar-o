"""Localisation et installation automatique de Karttapullautin (pullauta)."""
from __future__ import annotations

import logging
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

log = logging.getLogger(__name__)

KP_PINNED_VERSION = "2.12.1"
_KP_REPO = "karttapullautin/karttapullautin"
_GITHUB_API = "https://api.github.com"


def asset_name() -> str:
    """Nom de l'asset GitHub selon la plateforme courante.

    Ex: karttapullautin-x86_64-win.tar.gz
    """
    machine = platform.machine().lower()
    arch = "x86_64" if machine in ("x86_64", "amd64") else machine

    if sys.platform == "win32":
        return f"karttapullautin-{arch}-win.tar.gz"
    if sys.platform == "darwin":
        return f"karttapullautin-{arch}-macos.tar.gz"
    return f"karttapullautin-{arch}-linux.tar.gz"


def download_url(version: str = KP_PINNED_VERSION) -> str:
    """URL de téléchargement de l'asset pour la version donnée."""
    return (
        f"https://github.com/{_KP_REPO}/releases/download/v{version}/{asset_name()}"
    )


def read_binary_version(binary: pathlib.Path) -> str | None:
    """Extrait la version semver de pullauta. Retourne None en cas d'échec.

    KP v2.x n'accepte pas --version : la version s'affiche sur stdout au démarrage
    sans argument. On lance depuis un dossier temporaire vide pour éviter de déclencher
    un vrai traitement (KP s'arrête si pullauta.ini est absent).
    """
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            r = subprocess.run(
                [str(binary)],
                capture_output=True, text=True, timeout=10, cwd=tmpdir,
            )
            m = re.search(r"(\d+\.\d+\.\d+)", r.stdout + r.stderr)
            if m:
                return m.group(1)
    except Exception:
        pass
    # Fallback --version pour les versions futures qui pourraient l'accepter
    try:
        r = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        m = re.search(r"(\d+\.\d+\.\d+)", r.stdout + r.stderr)
        return m.group(1) if m else None
    except Exception:
        return None


def query_latest_version() -> str | None:
    """Interroge l'API GitHub pour la dernière version. Silencieux si hors ligne."""
    url = f"{_GITHUB_API}/repos/{_KP_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lidar-o/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json
            data = json.loads(resp.read())
            tag = data.get("tag_name", "")
            m = re.search(r"(\d+\.\d+\.\d+)", tag)
            return m.group(1) if m else None
    except Exception:
        return None


def install_kp(install_dir: pathlib.Path, *, confirm: bool = True) -> pathlib.Path:
    """Télécharge et extrait KP dans install_dir. Retourne le chemin du binaire.

    Affiche l'URL et demande confirmation si confirm=True.
    """
    url = download_url()
    exe_name = "pullauta.exe" if sys.platform == "win32" else "pullauta"

    print(f"\nKarttapullautin v{KP_PINNED_VERSION}")
    print(f"  URL     : {url}")
    print(f"  Dossier : {install_dir}")
    print("  Taille  : ~2 Mo")

    if confirm:
        try:
            ans = input("\nTélécharger et installer ? [O/n] ").strip().lower()
        except EOFError:
            ans = ""
        if ans and ans not in ("o", "y", "oui", "yes"):
            raise RuntimeError("Installation annulée par l'utilisateur.")

    install_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = pathlib.Path(tmpdir) / asset_name()
        log.info("Téléchargement : %s", url)

        def _progress(block_count: int, block_size: int, total: int) -> None:
            if total > 0:
                pct = min(100, block_count * block_size * 100 // total)
                print(f"\r  Progression : {pct:3d}%", end="", flush=True)

        urllib.request.urlretrieve(url, str(archive_path), reporthook=_progress)
        print()

        if archive_path.suffix == ".gz" or ".tar" in archive_path.name:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(tmpdir)
        elif archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(tmpdir)

        found = list(pathlib.Path(tmpdir).rglob(exe_name))
        if not found:
            raise RuntimeError(
                f"Binaire '{exe_name}' introuvable après extraction de {asset_name()}"
            )

        src_bin = found[0]
        dest_bin = install_dir / exe_name
        shutil.copy2(src_bin, dest_bin)
        if sys.platform != "win32":
            dest_bin.chmod(dest_bin.stat().st_mode | 0o111)

    log.info("KP installé : %s", dest_bin)
    print(f"  Installé : {dest_bin}")
    return dest_bin


def locate_binary(
    cfg: dict | None = None,
    terrain: str | None = None,
) -> pathlib.Path | None:
    """Cherche le binaire KP. Retourne None si absent (ne lève pas).

    Ordre de recherche :
      1. config terrain kp_binary
      2. variable d'environnement KP_BINARY
      3. PATH (shutil.which)
    """
    if cfg is not None and terrain is not None:
        kp_binary_cfg = (
            cfg.get("terrains", {}).get(terrain, {}).get("kp_binary")
        )
        if kp_binary_cfg:
            p = pathlib.Path(kp_binary_cfg)
            if p.exists():
                return p
            log.warning("kp_binary configuré ('%s') mais absent", kp_binary_cfg)

    env_path = os.environ.get("KP_BINARY")
    if env_path:
        p = pathlib.Path(env_path)
        if p.exists():
            return p
        log.warning("KP_BINARY='%s' défini mais absent", env_path)

    which = shutil.which("pullauta")
    if which:
        return pathlib.Path(which)

    return None
