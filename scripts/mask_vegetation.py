"""Applique le masque anthropique sur la végétation généralisée.

Soustrait de chaque couche végétation (406/408/410) :
  - zone_d_habitation (fictif=False) — enveloppe urbaine dense
  - batiment individuel bufférisé (BAT_BUFFER_M) — jardins périphériques
  - troncon_de_route (En service) bufférisé (ROAD_BUFFER_M)
  - polygones OSM landuse (farmland, orchard…) — parcelles agricoles

Paramètres lus depuis config.yaml → section `mask`.
Cache OSM : data/osm_landuse_{terrain}.json — auto-fetchéé si absent.

Usage :
    python scripts/mask_vegetation.py grimbosq
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import Sequence

import geopandas as gpd
import shapely.geometry as sg
import shapely.ops
import yaml
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.omap_writer import Layer, load_georef, load_template, write_omap

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = pathlib.Path(".")
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
TEMPLATE_PATH = ASSETS / "ISOM 2017-2_10000.omap"

_full_cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
_cfg = _full_cfg.get("mask", {})
ROAD_BUFFER_M: float = _cfg.get("road_buffer_m", 5.0)
HAB_BUFFER_M: float = _cfg.get("hab_buffer_m", 0.0)
BAT_BUFFER_M: float = _cfg.get("bat_buffer_m", 0.0)
_osm_cfg = _cfg.get("osm", {})
OSM_INCLUDE: frozenset[str] = frozenset(_osm_cfg.get("include", []))
OSM_WARN_HA: float = _osm_cfg.get("large_poly_warn_ha", 30.0)


# ── OSM helpers ───────────────────────────────────────────────────────────────

def _fetch_osm(
    bbox_l93: Sequence[float],
    cache_path: pathlib.Path,
    source_crs: str = "EPSG:2154",
) -> None:
    """Interroge Overpass API et sauvegarde le résultat dans cache_path."""
    import requests
    from pyproj import Transformer

    t = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    x1, y1 = t.transform(bbox_l93[0], bbox_l93[1])
    x2, y2 = t.transform(bbox_l93[2], bbox_l93[3])
    overpass_bbox = f"{y1},{x1},{y2},{x2}"
    query = (
        f'[out:json][timeout:30];'
        f'('
        f'way["landuse"]({overpass_bbox});'
        f'relation["landuse"]({overpass_bbox});'
        f'way["access"="private"]({overpass_bbox});'
        f'relation["access"="private"]({overpass_bbox});'
        f');'
        f'out body;>;out skel qt;'
    )
    log.info("Requête Overpass (bbox=%s) …", overpass_bbox)
    r = requests.get(
        "https://overpass-api.de/api/interpreter",
        params={"data": query},
        headers={"User-Agent": "lidar-o/1.0 (orienteering map research)"},
        timeout=60,
    )
    r.raise_for_status()
    cache_path.write_text(json.dumps(r.json(), ensure_ascii=False), encoding="utf-8")
    log.info("Cache OSM sauvegardé : %s", cache_path)


def _osm_mask_from_cache(
    cache_path: pathlib.Path,
    include_tags: frozenset[str],
    bbox_geom: BaseGeometry,
    warn_ha: float,
    target_crs: str = "EPSG:2154",
) -> BaseGeometry | None:
    """Parse le cache JSON Overpass → union des polygones landuse sélectionnés.

    Les polygones sont clippés à bbox_geom avant toute mesure de taille
    (évite les faux positifs pour les polygones qui débordent l'emprise).
    """
    from pyproj import Transformer

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in data["elements"] if e["type"] == "node"}
    t = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)

    parts: list[BaseGeometry] = []
    by_tag: dict[str, float] = {}

    for w in [e for e in data["elements"] if e["type"] == "way"]:
        lu = w.get("tags", {}).get("landuse", "")
        if lu not in include_tags:
            continue
        refs = w.get("nodes", [])
        pts = [t.transform(nodes[r][0], nodes[r][1]) for r in refs if r in nodes]
        if len(pts) < 3:
            continue
        try:
            poly = sg.Polygon(pts)
            if not poly.is_valid:
                poly = make_valid(poly)
                if not isinstance(poly, sg.Polygon):
                    continue
            clipped = poly.intersection(bbox_geom)
            if clipped.is_empty:
                continue
            clipped_ha = clipped.area / 10000
            if clipped_ha > warn_ha:
                log.warning(
                    "Polygone OSM landuse=%s taille=%.1f ha dans l'emprise (id=%s) — vérifier la source",
                    lu, clipped_ha, w["id"],
                )
            by_tag[lu] = by_tag.get(lu, 0.0) + clipped_ha
            parts.append(clipped)
        except Exception as e:
            log.debug("Polygone OSM ignoré (id=%s) : %s", w.get("id"), e)

    for tag, ha in sorted(by_tag.items()):
        log.info("  OSM landuse=%-14s %.2f ha", tag, ha)

    return shapely.ops.unary_union(parts) if parts else None


def _osm_geoms_by_tag(
    cache_path: pathlib.Path,
    tag_filters: dict[str, frozenset[str]],
    bbox_geom: BaseGeometry,
    target_crs: str = "EPSG:2154",
) -> dict[str, BaseGeometry]:
    """Parse le cache JSON Overpass → {"osm_key:osm_value": union_geom}.

    tag_filters : {osm_key: {allowed_values}}
    Ex. : {"landuse": frozenset({"farmland","orchard"}), "access": frozenset({"private"})}
    """
    from pyproj import Transformer

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in data["elements"] if e["type"] == "node"}
    t = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)

    by_tag: dict[str, list[BaseGeometry]] = {}
    for w in [e for e in data["elements"] if e["type"] == "way"]:
        osm_tags = w.get("tags", {})
        matched_key: str | None = None
        matched_val: str | None = None
        for key, allowed in tag_filters.items():
            val = osm_tags.get(key, "")
            if val in allowed:
                matched_key = key
                matched_val = val
                break
        if matched_key is None:
            continue
        refs = w.get("nodes", [])
        pts = [t.transform(nodes[r][0], nodes[r][1]) for r in refs if r in nodes]
        if len(pts) < 3:
            continue
        try:
            poly = sg.Polygon(pts)
            if not poly.is_valid:
                poly = make_valid(poly)
                if not isinstance(poly, sg.Polygon):
                    continue
            clipped = poly.intersection(bbox_geom)
            if not clipped.is_empty:
                composite = f"{matched_key}:{matched_val}"
                by_tag.setdefault(composite, []).append(clipped)
        except Exception as e:
            log.debug("Polygone OSM ignoré fill (id=%s) : %s", w.get("id"), e)

    return {key: shapely.ops.unary_union(geoms) for key, geoms in by_tag.items()}


# ── Masque ────────────────────────────────────────────────────────────────────

def _road_buffer(bdtopo_gpkg: pathlib.Path) -> BaseGeometry | None:
    """Buffer ROAD_BUFFER_M sur les routes en service (utilisé masque + découpage 520)."""
    try:
        routes = gpd.read_file(str(bdtopo_gpkg), layer="troncon_de_route")
        routes = routes[routes["etat_de_l_objet"] == "En service"]
        if not routes.empty:
            return shapely.ops.unary_union(routes.geometry.buffer(ROAD_BUFFER_M))
    except Exception as e:
        log.warning("troncon_de_route inaccessible : %s", e)
    return None


def build_mask(
    bdtopo_gpkg: pathlib.Path,
    osm_cache: pathlib.Path | None = None,
    bbox_geom: BaseGeometry | None = None,
    terrain_crs: str = "EPSG:2154",
) -> BaseGeometry:
    """Construit le masque : union de toutes les sources disponibles."""
    parts: list[BaseGeometry] = []

    # 1. Zone d'habitation (fictif=False, sans buffer par défaut)
    try:
        hab = gpd.read_file(str(bdtopo_gpkg), layer="zone_d_habitation")
        hab = hab[hab["fictif"] == False]
        if not hab.empty:
            geom = shapely.ops.unary_union(hab.geometry)
            if HAB_BUFFER_M > 0:
                geom = geom.buffer(HAB_BUFFER_M)
                log.info("Masque zone_d_habitation : %d poly + %.0fm buffer", len(hab), HAB_BUFFER_M)
            else:
                log.info("Masque zone_d_habitation : %d polygones (sans buffer)", len(hab))
            parts.append(geom)
    except Exception as e:
        log.warning("zone_d_habitation inaccessible : %s", e)

    # 2. Bâtiments individuels bufférisés
    if BAT_BUFFER_M > 0:
        try:
            bat = gpd.read_file(str(bdtopo_gpkg), layer="batiment")
            if not bat.empty:
                parts.append(shapely.ops.unary_union(bat.geometry.buffer(BAT_BUFFER_M)))
                log.info("Masque batiment : %d bâtiments × %.0fm", len(bat), BAT_BUFFER_M)
        except Exception as e:
            log.warning("batiment inaccessible : %s", e)

    # 3. Routes bufférisées
    road_buf = _road_buffer(bdtopo_gpkg)
    if road_buf is not None:
        parts.append(road_buf)
        log.info("Masque troncon_de_route : %.0fm buffer", ROAD_BUFFER_M)

    # 4. OSM landuse
    if OSM_INCLUDE and osm_cache is not None and bbox_geom is not None:
        if not osm_cache.exists():
            raise FileNotFoundError(
                f"Cache OSM absent : {osm_cache} — "
                "vérifier que fetch_osm a été lancé pour ce terrain"
            )
        log.info("Masque OSM landuse %s …", sorted(OSM_INCLUDE))
        osm_geom = _osm_mask_from_cache(osm_cache, OSM_INCLUDE, bbox_geom, OSM_WARN_HA, terrain_crs)
        if osm_geom and not osm_geom.is_empty:
            parts.append(osm_geom)
            log.info("Masque OSM total : %.2f ha", osm_geom.area / 10000)
        else:
            log.warning("Masque OSM vide — aucun polygone retenu dans l'emprise")
    elif OSM_INCLUDE:
        log.info("OSM désactivé (cache ou bbox manquants)")

    if not parts:
        raise ValueError("Masque vide — aucune source disponible")

    return shapely.ops.unary_union(parts)


def apply_mask(
    veg_gpkg: pathlib.Path,
    mask: BaseGeometry,
    out_gpkg: pathlib.Path,
) -> dict[str, int]:
    """Soustrait le masque de chaque couche végétation."""
    from pyogrio import list_layers
    layers = [name for name, _ in list_layers(str(veg_gpkg))]
    counts: dict[str, int] = {}

    for layer_name in layers:
        gdf = gpd.read_file(str(veg_gpkg), layer=layer_name)
        before = len(gdf)
        gdf["geometry"] = gdf.geometry.difference(mask)
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
        gdf = gdf[gdf.geometry.area > 1.0]
        after = len(gdf)
        log.info("%s : %d → %d polygones (-%d)", layer_name, before, after, before - after)
        counts[layer_name] = after
        gdf.to_file(str(out_gpkg), layer=layer_name, driver="GPKG")

    return counts


def build_fill_layers(
    bdtopo_gpkg: pathlib.Path | None,
    osm_cache: pathlib.Path | None,
    bbox_geom: BaseGeometry | None,
    terrain_crs: str = "EPSG:2154",
) -> list[Layer]:
    """Produit les couches de remplissage ISOM 520 / 401 / 403.

    520 (olive) : zone_d_habitation BD TOPO + OSM residential + access=private,
                  découpé par les routes (norme ISOM : interrompu aux chemins).
                  Choix carte de base : marquer large, affiner au terrain.
                  FFCO ref Grimbosq : 8.22 ha (11 polygones ciblés vs ~108 ha ici).
    401 (jaune) : OSM farmland, orchard, vineyard.
    403 (jaune+points) : OSM meadow.
    """
    parts_520: list[BaseGeometry] = []
    parts_401: list[BaseGeometry] = []
    parts_403: list[BaseGeometry] = []

    # zone_d_habitation BD TOPO → 520
    try:
        hab = gpd.read_file(str(bdtopo_gpkg), layer="zone_d_habitation")
        hab = hab[hab["fictif"] == False]
        if not hab.empty:
            geom = shapely.ops.unary_union([make_valid(g) for g in hab.geometry])
            if HAB_BUFFER_M > 0:
                geom = geom.buffer(HAB_BUFFER_M)
            parts_520.append(geom)
            log.info("520 source zone_d_habitation : %d polygones → %.2f ha", len(hab), geom.area / 10000)
    except Exception as e:
        log.warning("zone_d_habitation inaccessible pour 520 : %s", e)

    if osm_cache and osm_cache.exists() and bbox_geom is not None:
        tag_filters: dict[str, frozenset[str]] = {
            "access": frozenset({"private"}),
            "landuse": frozenset({"farmland", "orchard", "vineyard", "meadow", "residential"}),
        }
        by_tag = _osm_geoms_by_tag(osm_cache, tag_filters, bbox_geom, terrain_crs)

        if "access:private" in by_tag:
            parts_520.append(by_tag["access:private"])
        if "landuse:residential" in by_tag:
            parts_520.append(by_tag["landuse:residential"])
            log.info("520 source OSM residential : %.2f ha", by_tag["landuse:residential"].area / 10000)

        for tag_val in ("farmland", "orchard", "vineyard"):
            key = f"landuse:{tag_val}"
            if key in by_tag:
                parts_401.append(by_tag[key])

        if "landuse:meadow" in by_tag:
            parts_403.append(by_tag["landuse:meadow"])

    def _clip_and_layer(name: str, code: int, parts: list[BaseGeometry]) -> Layer | None:
        if not parts:
            return None
        geom = shapely.ops.unary_union(parts)
        if bbox_geom is not None:
            geom = geom.intersection(bbox_geom)
        if geom.is_empty:
            return None
        log.info("Couche %s (ISOM %d) : %.2f ha", name, code, geom.area / 10000)
        return Layer(name, code, [geom])

    layers: list[Layer] = []

    # Construire 520 : union des sources → clip bbox → découpage routes (norme ISOM)
    if parts_520:
        geom_520 = shapely.ops.unary_union(parts_520)
        if bbox_geom is not None:
            geom_520 = geom_520.intersection(bbox_geom)
        if not geom_520.is_empty:
            ha_avant = geom_520.area / 10000
            road_buf = _road_buffer(bdtopo_gpkg)
            if road_buf is not None:
                geom_520 = geom_520.difference(road_buf)
            ha_apres = geom_520.area / 10000
            pct = ha_apres / (bbox_geom.area / 10000) * 100 if bbox_geom is not None else 0.0
            log.info(
                "520 : %.2f ha avant routes → %.2f ha après (%.1f%% emprise)",
                ha_avant, ha_apres, pct,
            )
            log.info(
                "  Note : zone_d_habitation + OSM residential + access=private. "
                "FFCO ref : 8.22 ha (11 polygones ciblés). Carte de base : affiner au terrain."
            )
            if not geom_520.is_empty:
                layers.append(Layer("zone_520", 520, [geom_520]))
    else:
        log.warning("Couche 520 vide — aucune source disponible")

    for parts, name, code in [
        (parts_401, "zone_401", 401),
        (parts_403, "zone_403", 403),
    ]:
        layer = _clip_and_layer(name, code, parts)
        if layer:
            layers.append(layer)

    return layers


def build_veg_layers(masked_gpkg: pathlib.Path) -> list[Layer]:
    """Lit vegetation_masked.gpkg → liste de Layer ISOM 406/408/410."""
    from pyogrio import list_layers

    layer_codes = {"veg_406": 406, "veg_408": 408, "veg_410": 410}
    available = {n for n, _ in list_layers(str(masked_gpkg))}
    omap_layers: list[Layer] = []
    for layer_name, code in sorted(layer_codes.items(), key=lambda x: x[1]):
        if layer_name not in available:
            log.warning("Couche %s absente du GPKG masqué", layer_name)
            continue
        gdf = gpd.read_file(str(masked_gpkg), layer=layer_name)
        omap_layers.append(Layer(layer_name, code, list(gdf.geometry)))
        log.info("  %s : %d polygones → ISOM %d", layer_name, len(gdf), code)
    return omap_layers


def regenerate_omap(
    masked_gpkg: pathlib.Path,
    out_omap: pathlib.Path,
    fill_layers: list[Layer] | None = None,
    georef_xml: pathlib.Path | None = None,
) -> int:
    """Régénère le .omap végétation + couches de remplissage depuis le GPKG masqué."""
    template = load_template(TEMPLATE_PATH)
    _georef_path = georef_xml or (ASSETS / "georef_grimbosq.xml")
    georef = load_georef(_georef_path)

    omap_layers = build_veg_layers(masked_gpkg)
    total = sum(len(l.geometries) for l in omap_layers)

    if fill_layers:
        for fl in fill_layers:
            omap_layers.append(fl)
            log.info("  %s → ISOM %d", fl.name, fl.isom_code)
        total += len(fill_layers)

    write_omap(out_omap, template, omap_layers, georef)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Masque anthropique sur végétation")
    parser.add_argument("terrain", help="Nom du terrain (ex: grimbosq)")
    args = parser.parse_args()

    bdtopo_gpkg = DATA / f"{args.terrain}_bdtopo.gpkg"

    # Répertoire de sortie : config.yaml → output_dir, sinon output_{terrain}, sinon output/
    _tcfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    _terrain_cfg = _tcfg.get("terrains", {}).get(args.terrain, {})
    _out_dir_name = _terrain_cfg.get("output_dir") or (
        f"output_{args.terrain}" if args.terrain != "grimbosq" else "output"
    )
    terrain_out = ROOT / _out_dir_name

    veg_gpkg = terrain_out / "vegetation.gpkg"
    masked_gpkg = terrain_out / "vegetation_masked.gpkg"
    out_omap = terrain_out / f"{args.terrain}_veg.omap"
    osm_cache = DATA / f"osm_landuse_{args.terrain}.json"

    georef_path = ASSETS / f"georef_{args.terrain}.xml"
    if not georef_path.exists():
        georef_path = ASSETS / "georef_grimbosq.xml"
        log.warning("georef_%s.xml absent — utilisation de georef_grimbosq.xml (à corriger)", args.terrain)

    for p in [bdtopo_gpkg, veg_gpkg, TEMPLATE_PATH, georef_path]:
        if not p.exists():
            sys.exit(f"ABSENT : {p}")

    # Emprise terrain pour clip OSM
    terrain_cfg = _full_cfg.get("terrains", {}).get(args.terrain, {})
    bbox = terrain_cfg.get("bbox")
    bbox_geom = sg.box(*bbox) if bbox else None
    if bbox_geom is None:
        log.warning("Emprise terrain introuvable dans config.yaml — masque OSM désactivé")

    # Auto-fetch OSM si cache absent et bbox connue
    if OSM_INCLUDE and bbox_geom is not None and not osm_cache.exists():
        try:
            _fetch_osm(bbox, osm_cache)
        except Exception as e:
            sys.exit(f"ERREUR fetch OSM : {e}\nVérifier la connexion ou désactiver mask.osm.include dans config.yaml")

    log.info(
        "Construction du masque (road=%.0fm, hab=%.0fm, bat=%.0fm, osm=%s) …",
        ROAD_BUFFER_M, HAB_BUFFER_M, BAT_BUFFER_M, sorted(OSM_INCLUDE),
    )
    mask = build_mask(bdtopo_gpkg, osm_cache=osm_cache, bbox_geom=bbox_geom)
    log.info("Masque total : %.1f ha", mask.area / 10_000)

    log.info("Application du masque …")
    apply_mask(veg_gpkg, mask, masked_gpkg)

    log.info("Production couches de remplissage (520/401) …")
    fill_layers = build_fill_layers(bdtopo_gpkg, osm_cache=osm_cache, bbox_geom=bbox_geom)

    log.info("Régénération %s …", out_omap.name)
    total = regenerate_omap(masked_gpkg, out_omap, fill_layers=fill_layers, georef_xml=georef_path)
    log.info("Ecrit : %s (%d objets)", out_omap, total)


if __name__ == "__main__":
    main()
