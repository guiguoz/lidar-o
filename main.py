"""Orchestrateur du pipeline CO — produit un seul output/{terrain}.omap.

Usage :
    python main.py grimbosq --skip-pdal
    python main.py grimbosq --tiles-dir LIDAR/ [--reader readers.copc]
    python main.py grimbosq --from-step mask --force

Étapes canoniques :
  0  check_config  — détecte les diffs de config depuis le dernier run (non bloquant)
  1  fetch         — BD TOPO → data/{terrain}_bdtopo.gpkg
  2  pdal          — LiDAR → output/density_hag.tif + total_count.tif
  3  process_hag   — classify → output/density_hag_classified.tif
  4  vegetation    — run_pipeline → output/vegetation.gpkg
  5  mask          — masque anthropique → output/vegetation_masked.gpkg
  6  assemble      — assemblage final → output/{terrain}.omap
  7  qa            — métriques hull → console + output/run_metadata.json

Prérequis non orchestrés :
  - data/bdtopo/*D0{dept}*.gpkg    (téléchargé IGN)
  - LIDAR/*.copc.laz               (dalles LiDAR IGN HD)
  - out_kp/*.dxf                   (sortie Karttapullautin, optionnel — relief)
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import subprocess
import sys

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = pathlib.Path(".")
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
OUTPUT = ROOT / "output"  # remplacé dans main() selon output_dir du terrain
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable

STEPS = ["fetch", "pdal", "process_hag", "vegetation", "mask", "assemble", "qa"]
_STEP_IDX = {s: i for i, s in enumerate(STEPS)}


def _load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _is_fresh(artifact: pathlib.Path, reference: pathlib.Path) -> bool:
    """True si artifact existe et est plus récent ou à égalité avec reference."""
    return artifact.exists() and artifact.stat().st_mtime >= reference.stat().st_mtime


def _newest_mtime(*paths: pathlib.Path) -> float:
    """Mtime la plus récente parmi les paths existants."""
    mtimes = [p.stat().st_mtime for p in paths if p.exists()]
    return max(mtimes) if mtimes else 0.0


# ── Étape 0 : check_config ────────────────────────────────────────────────────

def step_check_config(cfg: dict) -> None:
    metadata = OUTPUT / "run_metadata.json"
    if not metadata.exists():
        return
    from src.guards import check_config_snapshot
    diffs = check_config_snapshot(cfg, metadata)
    for d in diffs:
        log.warning("CONFIG MODIFIÉE depuis dernier run : %s", d)


# ── Étape 1 : fetch ───────────────────────────────────────────────────────────

def step_fetch(terrain: str, cfg: dict, force: bool) -> None:
    dept = cfg.get("terrains", {}).get(terrain, {}).get("departement")
    if not dept:
        log.info("fetch : pas de 'departement' pour '%s' — étape ignorée (terrain non français ?)", terrain)
        return

    out = DATA / f"{terrain}_bdtopo.gpkg"
    gpkg_sources = sorted((DATA / "bdtopo").glob(f"*D0{dept}*.gpkg"))
    ref = gpkg_sources[-1] if gpkg_sources else None

    if not force and out.exists():
        if ref is None or _is_fresh(out, ref):
            log.info("SKIP fetch — %s à jour", out.name)
            return
        log.warning("fetch : %s périmé (< %s) — relance", out.name, ref.name)

    subprocess.run([PYTHON, str(SCRIPTS / "fetch.py"), terrain], check=True)


# ── Étape 2 : pdal ────────────────────────────────────────────────────────────

def step_pdal(terrain: str, cfg: dict, tiles: list[str], reader: str, force: bool) -> None:
    hag_tif = OUTPUT / "density_hag.tif"
    ref_mtime = _newest_mtime(*[pathlib.Path(t) for t in tiles])

    if not force and hag_tif.exists() and hag_tif.stat().st_mtime >= ref_mtime:
        log.info("SKIP pdal — density_hag.tif à jour")
        return
    if hag_tif.exists():
        log.warning("pdal : density_hag.tif périmé — relance")

    from scripts.run_terrain import build_pdal_hag, build_pdal_total, run_pdal

    OUTPUT.mkdir(parents=True, exist_ok=True)
    pdal_cfg = cfg.get("pdal", {})
    resolution: float = pdal_cfg.get("resolution", 0.5)
    min_h: float = pdal_cfg.get("min_h", 0.5)
    max_h: float = pdal_cfg.get("max_h", 50.0)

    log.info("PDAL HAG (%d dalles) …", len(tiles))
    run_pdal(build_pdal_hag(tiles, str(OUTPUT / "density_hag.tif"), resolution, min_h, max_h, reader), "density_hag")

    log.info("PDAL total count …")
    run_pdal(build_pdal_total(tiles, str(OUTPUT / "total_count.tif"), resolution, reader), "total_count")


# ── Étape 3 : process_hag ────────────────────────────────────────────────────

def step_process_hag(cfg: dict, force: bool) -> None:
    hag_tif = OUTPUT / "density_hag.tif"
    classified_tif = OUTPUT / "density_hag_classified.tif"

    if not hag_tif.exists():
        sys.exit("ABSENT : output/density_hag.tif — lancer l'étape pdal d'abord")

    if not force and _is_fresh(classified_tif, hag_tif):
        log.info("SKIP process_hag — density_hag_classified.tif à jour")
        return
    if classified_tif.exists():
        log.warning("process_hag : density_hag_classified.tif périmé — relance")

    subprocess.run(
        [PYTHON, str(SCRIPTS / "process_hag.py"), "--src", str(hag_tif), "--dst", str(OUTPUT)],
        check=True,
    )


# ── Étape 4 : vegetation ──────────────────────────────────────────────────────

def step_vegetation(terrain: str, cfg: dict, force: bool) -> None:
    import geopandas as gpd
    from src.vegetation import run_pipeline

    classified_tif = OUTPUT / "density_hag_classified.tif"
    veg_gpkg = OUTPUT / "vegetation.gpkg"

    if not classified_tif.exists():
        sys.exit("ABSENT : output/density_hag_classified.tif — lancer process_hag d'abord")

    if not force and _is_fresh(veg_gpkg, classified_tif):
        log.info("SKIP vegetation — vegetation.gpkg à jour")
        return
    if veg_gpkg.exists():
        log.warning("vegetation : vegetation.gpkg périmé — relance")

    gdf, _ = run_pipeline(classified_tif, cfg)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for cls in [406, 408, 410]:
        subset = gdf[gdf["class"] == cls].copy()
        subset.to_file(str(veg_gpkg), layer=f"veg_{cls}", driver="GPKG")
        log.info("  veg_%d : %d polygones", cls, len(subset))
    log.info("vegetation.gpkg écrit")


# ── Étape 5 : mask ────────────────────────────────────────────────────────────

def step_mask(terrain: str, cfg: dict, force: bool) -> None:
    import shapely.geometry as sg
    from scripts.mask_vegetation import _fetch_osm, apply_mask, build_mask

    terrain_cfg = cfg.get("terrains", {}).get(terrain, {})
    terrain_crs = terrain_cfg.get("crs", "EPSG:2154")

    bdtopo_gpkg = DATA / f"{terrain}_bdtopo.gpkg"
    veg_gpkg = OUTPUT / "vegetation.gpkg"
    masked_gpkg = OUTPUT / "vegetation_masked.gpkg"
    osm_cache = DATA / f"osm_landuse_{terrain}.json"

    if not bdtopo_gpkg.exists():
        log.warning("mask : %s absent — masquage BD TOPO désactivé (OSM uniquement)", bdtopo_gpkg.name)
        bdtopo_gpkg = None  # type: ignore[assignment]
    if not veg_gpkg.exists():
        sys.exit("ABSENT : output/vegetation.gpkg — lancer vegetation d'abord")

    ref_sources = [p for p in [veg_gpkg, bdtopo_gpkg] if p is not None]
    ref_mtime = _newest_mtime(*ref_sources)
    if not force and masked_gpkg.exists() and masked_gpkg.stat().st_mtime >= ref_mtime:
        log.info("SKIP mask — vegetation_masked.gpkg à jour")
        return
    if masked_gpkg.exists():
        log.warning("mask : vegetation_masked.gpkg périmé — relance")

    bbox = terrain_cfg.get("bbox")
    bbox_geom = sg.box(*bbox) if bbox else None

    osm_include = cfg.get("mask", {}).get("osm", {}).get("include", [])
    if osm_include and not osm_cache.exists() and bbox_geom is not None:
        try:
            log.info("Auto-fetch OSM pour '%s' (CRS=%s) …", terrain, terrain_crs)
            _fetch_osm(list(bbox), osm_cache, source_crs=terrain_crs)
        except Exception as e:
            log.warning("Fetch OSM échoué — masquage OSM désactivé : %s", e)
            osm_cache = None  # type: ignore[assignment]

    mask = build_mask(bdtopo_gpkg, osm_cache=osm_cache, bbox_geom=bbox_geom, terrain_crs=terrain_crs)
    log.info("Masque total : %.1f ha", mask.area / 10_000)
    apply_mask(veg_gpkg, mask, masked_gpkg)


# ── Clip bbox centralisé ─────────────────────────────────────────────────────

def _clip_layers_to_bbox(layers: list, bbox_geom, family_name: str) -> list:
    """Clip/filtre toutes les géométries d'une famille à l'emprise bbox_geom.

    Layer (polygones) : intersection shapely — clip réel.
    LineLayer (segments) : filtre bbox rapide.
    PointLayer : filtre bbox.
    Loggue n_rejetées/n_total par famille. Warn si n_out==0 et n_in>0.
    """
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    from src.omap_writer import Layer, LineLayer, PointLayer

    x1, y1, x2, y2 = bbox_geom.bounds
    clipped: list = []
    n_in = n_out = 0

    for layer in layers:
        if isinstance(layer, Layer):
            n_in += len(layer.geometries)
            kept = []
            for g in layer.geometries:
                c = make_valid(g).intersection(bbox_geom)
                if c.is_empty:
                    continue
                if c.geom_type in ("MultiPolygon", "GeometryCollection"):
                    polys = [p for p in c.geoms if "Polygon" in p.geom_type]
                    c = unary_union(polys) if polys else c
                if not c.is_empty:
                    kept.append(c)
            n_out += len(kept)
            clipped.append(Layer(layer.name, layer.isom_code, kept))

        elif isinstance(layer, LineLayer):
            n_in += len(layer.segments)
            kept = [
                seg for seg in layer.segments
                if (max(v[0] for v in seg[0]) >= x1 and min(v[0] for v in seg[0]) <= x2
                    and max(v[1] for v in seg[0]) >= y1 and min(v[1] for v in seg[0]) <= y2)
            ]
            n_out += len(kept)
            if kept:
                clipped.append(LineLayer(layer.name, layer.isom_code, kept))

        elif isinstance(layer, PointLayer):
            n_in += len(layer.points)
            kept = [(x, y) for x, y in layer.points if x1 <= x <= x2 and y1 <= y <= y2]
            n_out += len(kept)
            if kept:
                clipped.append(PointLayer(layer.name, layer.isom_code, kept))

    if n_in > 0:
        n_rej = n_in - n_out
        if n_out == 0:
            log.warning(
                "Clip %s : 0/%d géométries dans l'emprise — données hors terrain ?",
                family_name, n_in,
            )
        elif n_rej > 0:
            log.info(
                "Clip %s : %d/%d conservées (%d rejetées hors bbox)",
                family_name, n_out, n_in, n_rej,
            )
    return clipped


# ── Étape 6 : assemble ────────────────────────────────────────────────────────

def step_assemble(terrain: str, cfg: dict, force: bool) -> None:
    import shapely.geometry as sg
    from scripts.generate_bdtopo import build_bdtopo_layers, load_mapping as load_bd_mapping
    from scripts.generate_relief import build_relief_layers, load_relief_mapping
    from scripts.mask_vegetation import build_fill_layers, build_veg_layers
    from src.omap_writer import load_georef, load_template, write_omap

    out = OUTPUT / f"{terrain}.omap"
    masked_gpkg = OUTPUT / "vegetation_masked.gpkg"
    bdtopo_gpkg = DATA / f"{terrain}_bdtopo.gpkg"
    _kp_terrain = ROOT / f"out_kp_{terrain}"
    out_kp = _kp_terrain if _kp_terrain.exists() else ROOT / "out_kp"
    osm_cache = DATA / f"osm_landuse_{terrain}.json"

    if not masked_gpkg.exists():
        sys.exit("ABSENT : output/vegetation_masked.gpkg — lancer mask d'abord")
    if not bdtopo_gpkg.exists():
        log.warning("assemble : %s absent — couches BD TOPO ignorées (fill OSM conservé)", bdtopo_gpkg.name)
        bdtopo_gpkg = None  # type: ignore[assignment]

    dxf_files = sorted(out_kp.glob("*.dxf")) if out_kp.exists() else []
    ref_sources = [p for p in [masked_gpkg, bdtopo_gpkg] if p is not None]
    ref_mtime = _newest_mtime(*ref_sources, *dxf_files)

    if not force and out.exists() and out.stat().st_mtime >= ref_mtime:
        log.info("SKIP assemble — %s à jour", out.name)
        return
    if out.exists():
        log.warning("assemble : %s périmé — relance", out.name)

    terrain_cfg = cfg.get("terrains", {}).get(terrain, {})
    terrain_crs = terrain_cfg.get("crs", "EPSG:2154")
    bbox = terrain_cfg.get("bbox")
    bbox_geom = sg.box(*bbox) if bbox else None

    def _clip(layers: list, family: str) -> list:
        return _clip_layers_to_bbox(layers, bbox_geom, family) if bbox_geom is not None else layers

    all_layers: list = []
    all_layers += _clip(build_veg_layers(masked_gpkg), "végétation")

    fill: list = []
    if bdtopo_gpkg is not None:
        fill = build_fill_layers(bdtopo_gpkg, osm_cache, bbox_geom, terrain_crs=terrain_crs)
    elif osm_cache.exists() and bbox_geom is not None:
        fill = build_fill_layers(None, osm_cache, bbox_geom, terrain_crs=terrain_crs)
    fill = _clip(fill, "fill")
    all_layers += fill

    if bdtopo_gpkg is not None:
        bd_mapping = load_bd_mapping(SCRIPTS / "mappings" / "bdtopo_isom.yaml")
        all_layers += _clip(build_bdtopo_layers(bdtopo_gpkg, bd_mapping), "anthropique")

    if out_kp.exists() and dxf_files:
        rel_mapping, rel_skip = load_relief_mapping(SCRIPTS / "mappings" / "kp_relief.yaml")
        relief_bbox = tuple(bbox) if bbox else None  # type: ignore[arg-type]
        all_layers += _clip(build_relief_layers(out_kp, rel_mapping, rel_skip, bbox=relief_bbox), "relief")
    else:
        log.info("out_kp/ absent ou vide — relief non inclus dans %s", out.name)

    # Vérification : végétation sous 520 doit être nulle (sinon vert visible sous olive)
    from src.omap_writer import Layer as _Layer
    import shapely.ops as _sops
    zone_520_layers = [l for l in fill if isinstance(l, _Layer) and l.isom_code == 520]
    veg_layers_check = [l for l in all_layers if isinstance(l, _Layer) and l.isom_code in (406, 408, 410)]
    if zone_520_layers and veg_layers_check:
        geom_520 = _sops.unary_union([g for l in zone_520_layers for g in l.geometries])
        geom_veg = _sops.unary_union([g for l in veg_layers_check for g in l.geometries])
        veg_under_520_ha = geom_veg.intersection(geom_520).area / 10000
        if veg_under_520_ha > 0.01:
            log.warning("ATTENTION : %.4f ha de végétation sous 520 — revoir l'ordre de masquage", veg_under_520_ha)
        else:
            log.info("Contrôle 520 : %.4f ha végétation sous 520 (OK)", veg_under_520_ha)

    template = load_template(ASSETS / "ISOM 2017-2_10000.omap")
    georef = load_georef(ASSETS / f"georef_{terrain}.xml")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_omap(out, template, all_layers, georef)
    log.info("Assemblé : %s (%d couches)", out, len(all_layers))


# ── Étape 7 : qa ─────────────────────────────────────────────────────────────

def step_qa(terrain: str, cfg: dict) -> None:
    import geopandas as gpd
    import pandas as pd
    from src.qa import load_ffco_hull, report_hull_metrics, report_recall_by_class, write_config_snapshot

    masked_gpkg = OUTPUT / "vegetation_masked.gpkg"
    if not masked_gpkg.exists():
        log.warning("QA : vegetation_masked.gpkg absent — QA ignorée")
        return

    parts = []
    for cls in [406, 408, 410]:
        layer = f"veg_{cls}"
        try:
            sub = gpd.read_file(str(masked_gpkg), layer=layer)
            sub["class"] = cls
            parts.append(sub)
        except Exception:
            pass
    if not parts:
        log.warning("QA : aucune couche veg_* lisible")
        return
    gdf = pd.concat(parts, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=parts[0].crs)

    terrain_cfg = cfg.get("terrains", {}).get(terrain, {})
    ffco_gpkg_path = terrain_cfg.get("ffco_gpkg")
    ffco_layer = terrain_cfg.get("ffco_layer", "grimbosq_areas")
    hull = load_ffco_hull(ffco_gpkg_path, layer_name=ffco_layer) if ffco_gpkg_path else None

    report_hull_metrics(gdf, cfg, hull)

    if ffco_gpkg_path:
        report_recall_by_class(
            masked_gpkg=OUTPUT / "vegetation_masked.gpkg",
            ffco_gpkg=ROOT / ffco_gpkg_path,
            ffco_layer=ffco_layer,
        )

    write_config_snapshot(cfg, OUTPUT)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline CO — orchestre les 7 étapes")
    parser.add_argument("terrain", help="Nom du terrain (ex: grimbosq)")
    tiles_grp = parser.add_mutually_exclusive_group()
    tiles_grp.add_argument("--tiles-dir", metavar="DIR", help="Répertoire des dalles LiDAR")
    tiles_grp.add_argument("--tiles", nargs="+", metavar="FILE", help="Dalles LiDAR explicites")
    parser.add_argument("--skip-pdal", action="store_true", help="Saute les étapes pdal + process_hag")
    parser.add_argument(
        "--from-step", metavar="STEP", choices=STEPS,
        help=f"Reprend à cette étape ({', '.join(STEPS)})",
    )
    parser.add_argument("--force", action="store_true", help="Ignore les vérifications de fraîcheur")
    parser.add_argument("--reader", default="readers.copc", help="Lecteur PDAL (default: readers.copc)")
    args = parser.parse_args()

    global OUTPUT

    cfg = _load_config()
    terrain_cfg = cfg.get("terrains", {}).get(args.terrain, {})
    output_dir = terrain_cfg.get("output_dir") or (
        f"output_{args.terrain}" if args.terrain != "grimbosq" else "output"
    )
    OUTPUT = ROOT / output_dir

    start_idx = _STEP_IDX[args.from_step] if args.from_step else 0

    def should_run(step: str) -> bool:
        return _STEP_IDX[step] >= start_idx

    OUTPUT.mkdir(parents=True, exist_ok=True)

    step_check_config(cfg)

    if should_run("fetch"):
        step_fetch(args.terrain, cfg, args.force)

    if args.skip_pdal:
        log.info("SKIP pdal (--skip-pdal)")
        log.info("SKIP process_hag (--skip-pdal)")
        hag = OUTPUT / "density_hag.tif"
        classified = OUTPUT / "density_hag_classified.tif"
        if hag.exists() and classified.exists() and classified.stat().st_mtime < hag.stat().st_mtime:
            sys.exit(
                "ERREUR : density_hag_classified.tif plus vieux que density_hag.tif "
                "avec --skip-pdal — relancer sans --skip-pdal ou supprimer density_hag.tif"
            )
    else:
        if should_run("pdal"):
            tiles: list[str] = []
            if args.tiles_dir:
                td = pathlib.Path(args.tiles_dir)
                tiles = [str(p) for p in sorted(td.glob("*.copc.laz"))]
                if not tiles:
                    tiles = [str(p) for p in sorted(td.glob("*.laz"))]
            elif args.tiles:
                tiles = args.tiles
            if not tiles:
                sys.exit("--tiles-dir ou --tiles requis pour l'étape pdal (ou utiliser --skip-pdal)")
            step_pdal(args.terrain, cfg, tiles, args.reader, args.force)

        if should_run("process_hag"):
            step_process_hag(cfg, args.force)

    if should_run("vegetation"):
        step_vegetation(args.terrain, cfg, args.force)

    if should_run("mask"):
        step_mask(args.terrain, cfg, args.force)

    if should_run("assemble"):
        step_assemble(args.terrain, cfg, args.force)

    if should_run("qa"):
        step_qa(args.terrain, cfg)


if __name__ == "__main__":
    main()
