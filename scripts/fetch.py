"""Extrait les couches BD TOPO d'un GPKG département pour une emprise terrain.

Source : GPKG BD TOPO département IGN (téléchargement unique).
    Téléchargement : https://geoservices.ign.fr/bdtopo
    → onglet "Téléchargement par département" → sélectionner le département → Format GPKG.
    Placer le fichier dans le répertoire configuré sous bd_topo.gpkg_dir (config.yaml).

Usage :
    python scripts/fetch.py grimbosq
    python scripts/fetch.py grimbosq --layers priority        # seulement les couches prioritaires
    python scripts/fetch.py grimbosq --layers priority masque # prioritaires + masque

Sortie :
    data/{terrain}_bdtopo.gpkg  (une couche par calque BD TOPO)
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys
from typing import Literal

import geopandas as gpd
import yaml
from shapely.geometry import box

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = pathlib.Path(".")
CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"

LayerGroup = Literal["priority", "masque", "optionnel"]
ALL_GROUPS: list[LayerGroup] = ["priority", "masque", "optionnel"]


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def find_gpkg(gpkg_dir: pathlib.Path, departement: str) -> pathlib.Path:
    """Cherche le GPKG du département dans gpkg_dir.

    Conventions IGN : le fichier contient 'D0{dept}' ou 'D{dept}' dans son nom.
    Si plusieurs fichiers correspondent, retourne le plus récent.
    """
    dept_padded = departement.zfill(3)  # "14" → "014"
    candidates = sorted(
        list(gpkg_dir.glob(f"*D{dept_padded}*.gpkg")) + list(gpkg_dir.glob(f"*D{departement}*.gpkg")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # Dédupliquer (glob peut retourner les deux formes si elles matchent)
    seen: set[pathlib.Path] = set()
    unique = [p for p in candidates if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]

    if not unique:
        raise FileNotFoundError(
            f"Aucun GPKG BD TOPO pour le département {departement} dans {gpkg_dir}.\n"
            f"  Téléchargement : https://geoservices.ign.fr/bdtopo\n"
            f"  → Téléchargement par département → {departement} → Format GPKG\n"
            f"  → Placer le fichier dans : {gpkg_dir.resolve()}"
        )
    if len(unique) > 1:
        log.warning("Plusieurs GPKGs trouvés pour D%s — utilisation du plus récent : %s", departement, unique[0].name)
    return unique[0]


def clip_layer(
    gpkg_path: pathlib.Path,
    layer: str,
    bbox: tuple[float, float, float, float],
    crs: str,
) -> gpd.GeoDataFrame | None:
    """Clip une couche BD TOPO sur l'emprise bbox.

    Retourne None si la couche est absente du GPKG (warning, pas d'erreur).
    """
    try:
        gdf = gpd.read_file(str(gpkg_path), layer=layer, bbox=bbox)
    except Exception as exc:
        log.warning("Calque '%s' absent ou illisible : %s", layer, exc)
        return None

    if gdf.empty:
        log.info("  %s : 0 objets dans l'emprise", layer)
        return gdf

    if gdf.crs is None or str(gdf.crs) != crs:
        gdf = gdf.to_crs(crs)

    log.info("  %s : %d objets", layer, len(gdf))
    return gdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Clip BD TOPO département sur emprise terrain")
    parser.add_argument("terrain", help="Nom du terrain défini dans config.yaml (ex: grimbosq)")
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=ALL_GROUPS,
        default=["priority", "masque"],
        help="Groupes de calques à extraire (défaut: priority masque)",
    )
    args = parser.parse_args()

    cfg = load_config()

    # Terrain
    terrains = cfg.get("terrains", {})
    if args.terrain not in terrains:
        sys.exit(
            f"Terrain '{args.terrain}' absent de config.yaml.\n"
            f"Terrains disponibles : {list(terrains.keys())}"
        )
    terrain_cfg = terrains[args.terrain]
    bbox: tuple[float, float, float, float] = tuple(terrain_cfg["bbox"])  # type: ignore[assignment]
    crs: str = terrain_cfg["crs"]
    departement: str = str(terrain_cfg["departement"])

    # GPKG source
    gpkg_dir = ROOT / cfg["bd_topo"]["gpkg_dir"]
    gpkg_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = find_gpkg(gpkg_dir, departement)
    log.info("Source : %s", gpkg_path.name)
    log.info("Emprise : %s (bbox=%s)", crs, bbox)

    # Calques demandés
    layers_cfg: dict[str, list[str]] = cfg["bd_topo"]["layers"]
    requested_layers: list[str] = []
    for group in args.layers:
        requested_layers.extend(layers_cfg.get(group, []))

    # Clip
    results: dict[str, gpd.GeoDataFrame] = {}
    for layer in requested_layers:
        gdf = clip_layer(gpkg_path, layer, bbox, crs)
        if gdf is not None:
            results[layer] = gdf

    if not results:
        sys.exit("Aucun calque extrait — vérifier le GPKG et les noms de calques.")

    # Écriture
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"{args.terrain}_bdtopo.gpkg"
    for layer, gdf in results.items():
        gdf.to_file(str(out_path), layer=layer, driver="GPKG")
        log.info("Ecrit : %s (%d objets)", layer, len(gdf))

    log.info("Sortie : %s", out_path)


if __name__ == "__main__":
    main()
