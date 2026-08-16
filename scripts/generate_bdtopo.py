"""Phase 7 — Génère grimbosq_bdtopo.omap depuis le GPKG BD TOPO clippé.

Lit data/{terrain}_bdtopo.gpkg, applique le mapping scripts/mappings/bdtopo_isom.yaml,
et produit output/{terrain}_bdtopo.omap.

Usage :
    python scripts/generate_bdtopo.py grimbosq

Prérequis :
    - data/{terrain}_bdtopo.gpkg        (sortie fetch.py)
    - assets/ISOM 2017-2_10000.omap     (gabarit ISOM)
    - assets/georef_grimbosq.xml        (géoréférencement Lambert 93)
    - scripts/mappings/bdtopo_isom.yaml (mapping BD TOPO -> ISOM)
"""
from __future__ import annotations

import argparse
import collections
import logging
import pathlib
import sys

import geopandas as gpd
import yaml
from shapely.geometry import MultiPolygon, Polygon

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.omap_writer import LineLayer, PointLayer, Layer, load_georef, load_template, write_omap

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = pathlib.Path(".")
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
MAPPING_PATH = ROOT / "scripts" / "mappings" / "bdtopo_isom.yaml"
TEMPLATE_PATH = ASSETS / "ISOM 2017-2_10000.omap"


def load_mapping(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _match_row(row, match: dict) -> bool:
    """Vérifie que toutes les conditions du dict match sont satisfaites sur la ligne."""
    for attr, val in match.items():
        if str(row.get(attr, "")) != str(val):
            return False
    return True


def _apply_filter(gdf: gpd.GeoDataFrame, filter_expr: str | None) -> gpd.GeoDataFrame:
    if not filter_expr:
        return gdf
    return gdf.query(filter_expr)


def process_layer(
    gpkg_path: pathlib.Path,
    layer_name: str,
    layer_cfg: dict,
) -> tuple[
    dict[int, list[tuple[list[tuple[float, float]], bool]]],
    dict[int, list[Polygon]],
]:
    """Lit une couche GPKG et applique les règles de mapping.

    Retourne (line_segs_by_isom, polygons_by_isom).
    """
    try:
        gdf = gpd.read_file(str(gpkg_path), layer=layer_name)
    except Exception as exc:
        log.warning("Couche '%s' illisible : %s", layer_name, exc)
        return {}, {}

    if gdf.empty:
        log.info("  %s : vide", layer_name)
        return {}, {}

    filter_expr = layer_cfg.get("filter")
    if filter_expr:
        gdf = _apply_filter(gdf, filter_expr)
        log.info("  %s : %d après filtre '%s'", layer_name, len(gdf), filter_expr)

    rules: list[dict] = layer_cfg.get("rules", [])
    geom_type: str = layer_cfg.get("geometry", "line")

    line_segs: dict[int, list] = collections.defaultdict(list)
    polygons: dict[int, list] = collections.defaultdict(list)
    skipped = 0

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        # Chercher la première règle qui s'applique
        isom = None
        for rule in rules:
            if _match_row(row, rule.get("match", {})):
                isom = rule["isom"]
                break

        if isom is None:
            skipped += 1
            continue

        if geom_type == "line":
            # MultiLineString ou LineString → segments
            geoms = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
            for g in geoms:
                coords = list(g.coords)
                if len(coords) >= 2:
                    line_segs[isom].append(([(c[0], c[1]) for c in coords], False))

        elif geom_type == "area":
            # Polygon ou MultiPolygon
            if isinstance(geom, Polygon):
                polygons[isom].append(geom)
            elif isinstance(geom, MultiPolygon):
                polygons[isom].extend(geom.geoms)

    if skipped:
        log.info("  %s : %d entités sans règle correspondante (nature inconnue ou skip)", layer_name, skipped)

    return dict(line_segs), dict(polygons)


def build_bdtopo_layers(
    gpkg_path: pathlib.Path,
    mapping: dict,
) -> list[Layer | LineLayer | PointLayer]:
    """Lit le GPKG BD TOPO → liste d'objets omap (surfaces + lignes)."""
    from pyogrio import list_layers

    skip_layers: set[str] = set(mapping.get("skip", []))
    layers_cfg: dict[str, dict] = mapping.get("layers", {})
    all_lines: dict[int, list] = collections.defaultdict(list)
    all_polys: dict[int, list] = collections.defaultdict(list)
    available = {name for name, _ in list_layers(str(gpkg_path))}

    for layer_name, layer_cfg in layers_cfg.items():
        if layer_name in skip_layers:
            log.info("Skip : %s", layer_name)
            continue
        if layer_name not in available:
            log.warning("Couche '%s' absente du GPKG — ignorée", layer_name)
            continue
        log.info("Lecture %s …", layer_name)
        segs, polys = process_layer(gpkg_path, layer_name, layer_cfg)
        for code, entries in segs.items():
            all_lines[code].extend(entries)
            log.info("  → %d lignes ISOM %d", len(entries), code)
        for code, geoms in polys.items():
            all_polys[code].extend(geoms)
            log.info("  → %d polygones ISOM %d", len(geoms), code)

    omap_layers: list[Layer | LineLayer | PointLayer] = []
    for code in sorted(all_polys):
        omap_layers.append(Layer(f"area_{code}", code, all_polys[code]))
    for code in sorted(all_lines):
        omap_layers.append(LineLayer(f"line_{code}", code, all_lines[code]))
    return omap_layers


def main() -> None:
    parser = argparse.ArgumentParser(description="BD TOPO GPKG -> .omap ISOM")
    parser.add_argument("terrain", help="Nom du terrain (ex: grimbosq)")
    args = parser.parse_args()

    for p in [MAPPING_PATH, TEMPLATE_PATH]:
        if not p.exists():
            sys.exit(f"ABSENT : {p}")

    gpkg_path = DATA / f"{args.terrain}_bdtopo.gpkg"
    if not gpkg_path.exists():
        sys.exit(f"ABSENT : {gpkg_path} — lancer fetch.py d'abord")

    georef_path = ASSETS / f"georef_{args.terrain}.xml"
    if not georef_path.exists():
        georef_path = ASSETS / "georef_grimbosq.xml"
        log.warning("georef_%s.xml absent — utilisation de georef_grimbosq.xml", args.terrain)

    import yaml as _yaml
    _cfg = _yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    _tcfg = _cfg.get("terrains", {}).get(args.terrain, {})
    _out_dir_name = _tcfg.get("output_dir") or (
        f"output_{args.terrain}" if args.terrain != "grimbosq" else "output"
    )
    output = ROOT / _out_dir_name

    mapping = load_mapping(MAPPING_PATH)
    template = load_template(TEMPLATE_PATH)
    georef = load_georef(georef_path)

    omap_layers = build_bdtopo_layers(gpkg_path, mapping)

    total_polys = sum(len(l.geometries) for l in omap_layers if isinstance(l, Layer))
    total_lines = sum(len(l.segments) for l in omap_layers if isinstance(l, LineLayer))
    log.info("Total : %d polygones + %d lignes = %d objets", total_polys, total_lines, total_polys + total_lines)

    output.mkdir(parents=True, exist_ok=True)
    out_path = output / f"{args.terrain}_bdtopo.omap"
    write_omap(out_path, template, omap_layers, georef)
    log.info("Ecrit : %s", out_path)


if __name__ == "__main__":
    main()
