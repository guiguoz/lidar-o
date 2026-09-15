"""Appel automatique de Karttapullautin (KP) en mode batch.

Localise le binaire, génère pullauta.ini avec chemins absolus,
lance KP sur le dossier de dalles, et vérifie les DXF produits.
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import time

import yaml

log = logging.getLogger(__name__)
logging.getLogger("ezdxf").setLevel(logging.WARNING)  # supprime le bruit ACAD_xxx à la lecture DXF

_KP_RELEASES_URL = "https://github.com/karttapullautin/karttapullautin/releases"


# ── Localisation du binaire ───────────────────────────────────────────────────

def locate_binary() -> pathlib.Path:
    """KP_BINARY env var → PATH → échec explicite avec lien releases."""
    env_path = os.environ.get("KP_BINARY")
    if env_path:
        p = pathlib.Path(env_path)
        if p.exists():
            return p
        raise FileNotFoundError(
            f"KP_BINARY={env_path} défini mais fichier absent.\n"
            f"Télécharger : {_KP_RELEASES_URL}"
        )

    which = shutil.which("pullauta")
    if which:
        return pathlib.Path(which)

    raise FileNotFoundError(
        "Karttapullautin (pullauta) introuvable.\n"
        f"  • Définir KP_BINARY=/chemin/vers/pullauta, ou\n"
        f"  • Ajouter le répertoire contenant pullauta au PATH.\n"
        f"  • Télécharger : {_KP_RELEASES_URL}"
    )


# ── Génération de pullauta.ini ────────────────────────────────────────────────

def _build_ini(
    lazfolder: pathlib.Path,
    batchoutfolder: pathlib.Path,
    base_ini: pathlib.Path | None,
    cliffheight: float | None = None,
    cliffangle: float | None = None,
    lightgreentone: int | None = None,
    medianboxsize2: int | None = None,
) -> str:
    """Construit le contenu de pullauta.ini.

    Si base_ini existe, l'utilise comme template et remplace uniquement les
    champs de chemin (batch, lazfolder, batchoutfolder) et les paramètres
    cliff/rendering explicitement configurés. Sinon génère un ini minimal.

    lightgreentone : ton du vert clair (0–255). Défaut KP : 200 (quasi-blanc).
    160 = fond lisible comme support de décalque à 50 % d'opacité (validé 2026-09).
    medianboxsize2 : 2e passe filtre médian végétation. 1=désactivé (défaut KP).
    16 = zones nettes et suivables à 1:10 000 (validé TEST A 2026-09).
    """
    laz_str = str(lazfolder).replace("\\", "/")
    out_str = str(batchoutfolder).replace("\\", "/")
    overrides: dict[str, str] = {"batch": "1", "lazfolder": laz_str, "batchoutfolder": out_str}
    if cliffheight is not None:
        overrides["cliffheight"] = str(cliffheight)
    if cliffangle is not None:
        overrides["cliffangle"] = str(cliffangle)
    if lightgreentone is not None:
        overrides["lightgreentone"] = str(lightgreentone)
    if medianboxsize2 is not None:
        overrides["medianboxsize2"] = str(medianboxsize2)

    if base_ini is not None and base_ini.exists():
        result: list[str] = []
        seen: set[str] = set()
        for line in base_ini.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in overrides:
                    result.append(f"{key}={overrides[key]}")
                    seen.add(key)
                    continue
            result.append(line)
        for key, val in overrides.items():
            if key not in seen:
                result.append(f"{key}={val}")
        return "\n".join(result)

    # ini minimal pour clone propre (pullauta.ini absent du dépôt).
    # Paramètres essentiels pour la CO — cohérents avec scripts/mappings/kp_relief.yaml.
    # cliff2/cliff3 restent générés par KP (pas de flag "désactiver") mais sont écartés
    # au niveau du mapping. cliffnosmallciffs=5.5 réduit les artefacts courts.
    return (
        f"batch=1\n"
        f"processes=2\n"
        f"lazfolder={laz_str}\n"
        f"batchoutfolder={out_str}\n"
        f"savetempfiles=1\n"
        f"output_dxf=1\n"
        f"# contours\n"
        f"contour_interval=5\n"
        f"formline=2\n"
        f"formlinesteepness=0.37\n"
        f"formlineaddition=17\n"
        f"minimumgap=30\n"
        f"dashlength=60\n"
        f"gaplength=12\n"
        f"depression_length=181\n"
        f"smoothing=0.7\n"
        f"curviness=1.1\n"
        f"knolls=0.6\n"
        f"thinfactor=1\n"
        f"# falaises — seuils confirmés sur Grimbosq/Port-en-Bessin\n"
        f"cliff1=1.15\n"
        f"cliff2=2.0\n"
        f"cliffthin=1\n"
        f"cliffsteepfactor=0.38\n"
        f"cliffflatplace=3.5\n"
        f"cliffnosmallciffs=5.5\n"
        + (f"cliffheight={cliffheight}\n" if cliffheight is not None else "")
        + (f"cliffangle={cliffangle}\n" if cliffangle is not None else "")
        f"# végétation\n"
        f"undergrowth=0.35\n"
        f"undergrowth2=0.56\n"
        f"greenground=0.9\n"
        f"greenhigh=2\n"
        f"topweight=0.80\n"
        f"greendetectsize=3\n"
        f"zone1=1.0|2.65|99|1\n"
        f"zone2=2.65|3.4|99|0.1\n"
        f"zone3=3.4|5.5|8|0.2\n"
        f"pointvolumefactor=0.1\n"
        f"pointvolumeexponent=1\n"
        f"parallel_laz_decompression=1\n"
    )


def generate_ini(
    tiles_dir: pathlib.Path,
    output_dir: pathlib.Path,
    work_dir: pathlib.Path,
    root: pathlib.Path,
    cliffheight: float | None = None,
    cliffangle: float | None = None,
    lightgreentone: int | None = None,
    medianboxsize2: int | None = None,
) -> pathlib.Path:
    """Génère pullauta.ini dans work_dir avec chemins absolus.

    Utilise root/pullauta.ini comme template s'il existe.
    cliffheight/cliffangle/lightgreentone/medianboxsize2 : injectés si renseignés.
    """
    base_ini = root / "pullauta.ini"
    content = _build_ini(
        tiles_dir.resolve(), output_dir.resolve(), base_ini,
        cliffheight=cliffheight, cliffangle=cliffangle,
        lightgreentone=lightgreentone, medianboxsize2=medianboxsize2,
    )
    ini_path = work_dir / "pullauta.ini"
    ini_path.write_text(content, encoding="utf-8")
    log.info("pullauta.ini → %s", ini_path)
    return ini_path


# ── Lancement KP ─────────────────────────────────────────────────────────────

def run_kp(binary: pathlib.Path, work_dir: pathlib.Path) -> None:
    """Lance KP en mode batch depuis work_dir (lit pullauta.ini dans ce répertoire)."""
    log.info("KP : %s  (cwd=%s)", binary.resolve(), work_dir)
    result = subprocess.run([str(binary.resolve())], cwd=str(work_dir))
    if result.returncode != 0:
        raise RuntimeError(f"KP a échoué (code retour {result.returncode})")


def run_kp_makevegenew(binary: pathlib.Path, work_dir: pathlib.Path) -> None:
    """Régénère uniquement la végétation (pullauta makevegenew) sans relancer KP complet.

    Lit pullauta.ini dans work_dir. Produit vegetation.png et les DXF vég.
    """
    log.info("KP makevegenew : %s  (cwd=%s)", binary.resolve(), work_dir)
    result = subprocess.run(
        [str(binary.resolve()), "makevegenew"], cwd=str(work_dir)
    )
    if result.returncode != 0:
        raise RuntimeError(f"KP makevegenew a échoué (code retour {result.returncode})")


def run_kp_pngmergevege(binary: pathlib.Path, work_dir: pathlib.Path) -> None:
    """Fusionne les tuiles PNG de végétation (pullauta pngmergevege) en un seul PNG.

    Lit pullauta.ini dans work_dir. Produit le PNG fusionné final.
    """
    log.info("KP pngmergevege : %s  (cwd=%s)", binary.resolve(), work_dir)
    result = subprocess.run(
        [str(binary.resolve()), "pngmergevege"], cwd=str(work_dir)
    )
    if result.returncode != 0:
        raise RuntimeError(f"KP pngmergevege a échoué (code retour {result.returncode})")


# ── Vérification des sorties ──────────────────────────────────────────────────

def _dxf_layers(dxf_path: pathlib.Path) -> set[str]:
    """Retourne l'ensemble des noms de calques d'un fichier DXF."""
    import ezdxf
    doc = ezdxf.readfile(str(dxf_path))
    return {e.dxf.layer for e in doc.modelspace()}


def verify_dxf_outputs(
    output_dir: pathlib.Path,
    mapping: dict[str, int],
    skip: set[str],
    launch_time: float,
) -> list[str]:
    """Vérifie les DXF produits par KP. Retourne une liste d'erreurs (vide = OK).

    Contrôles :
    - DXF présents
    - Plus récents que launch_time (sinon chemins relatifs non lus)
    - Aucun calque inconnu (absent mapping ET skip) — version KP différente ?
    - Au moins un calque du mapping trouvé
    """
    errors: list[str] = []

    dxf_files = sorted(output_dir.glob("*.dxf"))
    if not dxf_files:
        errors.append(f"Aucun DXF produit dans {output_dir}")
        return errors

    stale = [f.name for f in dxf_files if f.stat().st_mtime < launch_time]
    if stale:
        errors.append(
            f"DXF antérieurs au lancement (pullauta.ini mal lu — chemins relatifs ?) : "
            f"{stale}"
        )

    all_layers: set[str] = set()
    for dxf_path in dxf_files:
        try:
            layers = _dxf_layers(dxf_path)
        except Exception as exc:
            errors.append(f"Lecture échouée {dxf_path.name} : {exc}")
            continue
        unknown = layers - set(mapping) - skip
        if unknown:
            errors.append(
                f"{dxf_path.name} : calques inconnus (absents du mapping ET du skip) : "
                f"{sorted(unknown)} — version KP différente ?"
            )
        all_layers |= layers

    found = all_layers & set(mapping)
    missing = set(mapping) - all_layers
    if missing:
        log.warning(
            "Calques du mapping absents des DXF : %s "
            "(normal si terrain sans ces éléments ou version KP différente)",
            sorted(missing),
        )
    if not found:
        errors.append("Aucun calque du mapping trouvé dans les DXF — sortie KP anormale")

    return errors


def verify_dxf_extent(
    output_dir: pathlib.Path,
    bbox: tuple[float, float, float, float],
) -> bool:
    """Retourne True si au moins une géométrie DXF chevauche la bbox du terrain.

    False = mismatch probable (DXF issus d'un autre terrain).
    """
    import ezdxf

    x1, y1, x2, y2 = bbox

    for dxf_path in sorted(output_dir.glob("*.dxf")):
        try:
            doc = ezdxf.readfile(str(dxf_path))
            for entity in doc.modelspace():
                etype = entity.dxftype()
                if etype == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in entity.get_points()]
                elif etype == "POLYLINE":
                    pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                elif etype == "POINT":
                    pts = [(entity.dxf.location.x, entity.dxf.location.y)]
                else:
                    continue
                if not pts:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if max(xs) >= x1 and min(xs) <= x2 and max(ys) >= y1 and min(ys) <= y2:
                    return True
        except Exception:
            continue

    return False


# ── Point d'entrée principal ──────────────────────────────────────────────────

def run_engine(
    terrain: str,
    cfg: dict,
    tiles_dir: pathlib.Path,
    root: pathlib.Path,
) -> pathlib.Path:
    """Lance KP en mode batch et vérifie les sorties DXF.

    Retourne le répertoire contenant les DXF produits.
    Lève RuntimeError si la vérification échoue.
    """
    terrain_cfg = cfg.get("terrains", {}).get(terrain, {})
    bbox = terrain_cfg.get("bbox")

    binary = locate_binary()
    log.info("KP binaire : %s", binary)

    out_kp = root / f"out_kp_{terrain}"
    out_kp.mkdir(parents=True, exist_ok=True)

    kp_cliff = cfg.get("karttapullautin", {}).get("cliff", {}) or {}
    cliffheight = kp_cliff.get("cliffheight")
    cliffangle = kp_cliff.get("cliffangle")
    kp_rendering = cfg.get("karttapullautin", {}).get("rendering", {}) or {}
    lightgreentone = kp_rendering.get("lightgreentone")
    medianboxsize2 = kp_rendering.get("medianboxsize2")

    generate_ini(
        tiles_dir, out_kp, work_dir=out_kp, root=root,
        cliffheight=cliffheight, cliffangle=cliffangle,
        lightgreentone=lightgreentone, medianboxsize2=medianboxsize2,
    )

    launch_time = time.time()
    run_kp(binary, work_dir=out_kp)

    mapping_path = root / "scripts" / "mappings" / "kp_relief.yaml"
    raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    mapping: dict[str, int] = {k: int(v) for k, v in raw["mapping"].items()}
    skip: set[str] = set(str(s) for s in raw.get("skip", []))

    errors = verify_dxf_outputs(out_kp, mapping, skip, launch_time)
    if errors:
        for err in errors:
            log.error("KP vérification : %s", err)
        raise RuntimeError(f"Vérification DXF échouée ({len(errors)} erreur(s))")

    if bbox is not None:
        if not verify_dxf_extent(out_kp, tuple(bbox)):
            log.warning(
                "GARDE-FOU relief : aucune géométrie dans l'emprise du terrain %s "
                "— DXF issus d'un autre terrain ?",
                terrain,
            )

    log.info("KP terminé — DXF dans %s", out_kp)
    return out_kp
