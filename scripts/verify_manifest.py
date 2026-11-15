"""Generation et verification du manifeste SHA-256 du paquet LidarO.

Genere un manifest.json a la racine du paquet listant l'empreinte SHA-256
de tous les fichiers sources distribues :
  - fichiers .py de app/ (cle "sources")
  - binaires critiques (cle "binaries")
  - ressources de distribution hors-Python (cle "resources")

Fichiers EXCLUS du manifeste (crees au moment de l'installation/execution,
pas des fichiers sources de distribution) :
  - python/           : extraction de l'environnement Python embarque
  - python.tar.gz     : archive Python embarquee avant extraction
  - python_new/       : dossier temporaire de mise a jour Python
  - manifest.json     : le manifeste lui-meme (ne peut pas se hacher lui-meme)

Usage depuis la racine du paquet :
    python app/scripts/verify_manifest.py --generate
    python app/scripts/verify_manifest.py --verify
    python app/scripts/verify_manifest.py --verify --strict  (exit 1 si divergence)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

APP_DIR = pathlib.Path(__file__).parent.parent.resolve()
PACK_ROOT = APP_DIR.parent  # LidarO-Windows-x64/ ou C:\LidarO-test-propre\


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_sources(root: pathlib.Path) -> dict[str, str]:
    """Retourne {chemin_relatif: sha256} pour tous les .py de app/."""
    result: dict[str, str] = {}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(PACK_ROOT).as_posix()
        result[rel] = _sha256(p)
    return result


def _collect_binaries() -> dict[str, str]:
    """SHA-256 des binaires critiques (optionnel si absent)."""
    candidates = {
        "models/model_e_final.pkl": PACK_ROOT / "models" / "model_e_final.pkl",
        "bin/pullauta.exe": PACK_ROOT / "bin" / "pullauta.exe",
    }
    result: dict[str, str] = {}
    for rel, path in candidates.items():
        if path.exists():
            result[rel] = _sha256(path)
    return result


def _collect_resources() -> dict[str, str]:
    """SHA-256 des ressources de distribution non-Python (optionnel si absent).

    Couvre les fichiers distribues qui ne sont ni du code Python ni des
    binaires : scripts BAT, fichiers de configuration, assets cartographiques.
    LidarO_test.bat est exclu (Sandbox uniquement, non distribue).
    """
    # Fichiers individuels a la racine du paquet
    root_files = [
        "setup.bat",
        "LidarO.bat",
        "LidarO_cli.bat",
        "LidarO_diagnostic.bat",
        "VERSION.txt",
        "COMMIT.txt",
        "python_env_version.txt",
    ]
    # Fichiers individuels dans app/
    app_files = [
        "app/config_default.yaml",
        "app/metadata.json",
    ]
    # Extensions retenues dans app/assets/ (non-recursif)
    assets_extensions = {".xml", ".ini", ".omap", ".crt", ".md"}

    result: dict[str, str] = {}

    for name in root_files:
        path = PACK_ROOT / name
        if path.exists():
            result[name] = _sha256(path)

    for name in app_files:
        path = PACK_ROOT / name
        if path.exists():
            result[name] = _sha256(path)

    # app/assets/ — un seul niveau, extensions selectionnees
    assets_dir = PACK_ROOT / "app" / "assets"
    if assets_dir.is_dir():
        for p in sorted(assets_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in assets_extensions:
                rel = p.relative_to(PACK_ROOT).as_posix()
                result[rel] = _sha256(p)

    # docs/DEMARRER.html — obligatoire en distribution ; cmd_generate() avertit si absent
    demarrer = PACK_ROOT / "docs" / "DEMARRER.html"
    if demarrer.exists():
        result["docs/DEMARRER.html"] = _sha256(demarrer)

    # python.tar.gz — archive runtime distribuée ; couvre son SHA-256 si présente au staging
    tar_gz = PACK_ROOT / "python.tar.gz"
    if tar_gz.exists():
        result["python.tar.gz"] = _sha256(tar_gz)

    return result


_MANDATORY_RESOURCES = ("docs/DEMARRER.html", "python.tar.gz")


def cmd_generate() -> None:
    manifest = {
        "sources": _collect_sources(APP_DIR),
        "binaries": _collect_binaries(),
        "resources": _collect_resources(),
    }
    out = PACK_ROOT / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    n_py = len(manifest["sources"])
    n_bin = len(manifest["binaries"])
    n_res = len(manifest["resources"])
    print(
        f"manifest.json genere : {n_py} fichiers .py + {n_bin} binaires"
        f" + {n_res} ressources -> {out}"
    )
    all_entries = set(manifest["resources"]) | set(manifest["binaries"])
    missing = [m for m in _MANDATORY_RESOURCES if m not in all_entries]
    for m in missing:
        print(f"ERREUR : {m} absent — obligatoire pour la distribution.", file=sys.stderr)
    if missing:
        sys.exit(1)


def cmd_verify(strict: bool = False) -> int:
    manifest_path = PACK_ROOT / "manifest.json"
    if not manifest_path.exists():
        print("ERREUR : manifest.json absent — lancer --generate d'abord.", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    ok = 0

    for section in ("sources", "binaries", "resources"):
        for rel, expected in manifest.get(section, {}).items():
            path = PACK_ROOT / rel
            if not path.exists():
                errors.append(f"  MANQUANT  {rel}")
                continue
            actual = _sha256(path)
            if actual != expected:
                errors.append(f"  MODIFIE   {rel}")
            else:
                ok += 1

    if errors:
        print(f"Verification manifeste : {ok} OK, {len(errors)} divergence(s) :")
        for e in errors:
            print(e)
        return 1 if strict else 0
    else:
        print(f"Verification manifeste : {ok} fichiers OK — paquet conforme aux sources.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true", help="Générer manifest.json")
    group.add_argument("--verify", action="store_true", help="Vérifier le paquet vs manifest.json")
    parser.add_argument("--strict", action="store_true",
                        help="Avec --verify : exit 1 si divergence (pour CI/scripts)")
    args = parser.parse_args()

    if args.generate:
        cmd_generate()
        return 0
    return cmd_verify(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
