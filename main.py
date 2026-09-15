"""Orchestrateur du pipeline CO — produit un seul output/{terrain}.omap.

Usage :
    python main.py init mon_terrain --center 49.043 -0.421
    python main.py tiles mon_terrain
    python main.py check mon_terrain
    python main.py grimbosq --skip-pdal
    python main.py grimbosq --tiles-dir LIDAR/ [--reader readers.copc]
    python main.py run grimbosq --from-step mask --force

Sous-commandes :
  init   — crée config.yaml + georef XML depuis coordonnées géographiques
  tiles  — liste les dalles LiDAR nécessaires (connecteur IGN pour EPSG:2154)
  check  — vérifie dalles, recouvrement, CRS, georef XML avant traitement
  run    — lance le pipeline (alias : positional terrain, backward-compatible)

Étapes du pipeline :
  0  check_config  — détecte les diffs de config depuis le dernier run (non bloquant)
  1  fetch         — BD TOPO → data/{terrain}_bdtopo.gpkg
  2  pdal          — LiDAR → output/density_hag.tif + total_count.tif
  3  process_hag   — classify → output/density_hag_classified.tif
  3b relief        — Karttapullautin batch → out_kp_{terrain}/*.dxf (optionnel, KP absent = ignoré)
  4  vegetation    — run_pipeline → output/vegetation.gpkg
  5  mask          — masque anthropique → output/vegetation_masked.gpkg
  6  assemble      — assemblage final → output/{terrain}.omap
  7  qa            — métriques hull → console + output/run_metadata.json
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

STEPS = ["fetch", "pdal", "process_hag", "relief", "vegetation", "mask", "assemble", "qa"]
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


# ── Étape 3b : relief (optionnel — KP absent = avertissement + continue) ──────

def step_relief(
    terrain: str,
    cfg: dict,
    tiles_dir: pathlib.Path | None,
    force: bool,
) -> str:
    """Retourne un statut court décrivant ce qui s'est passé (affiché en fin de run)."""
    try:
        from src.run_engine import locate_binary
        locate_binary()
    except FileNotFoundError:
        log.warning("relief : KP (pullauta) introuvable — étape ignorée")
        return "ignoré : KP absent (définir KP_BINARY ou ajouter pullauta au PATH)"

    if tiles_dir is None:
        log.warning("relief : --tiles-dir requis pour lancer KP — étape ignorée")
        return "ignoré : --tiles-dir manquant"

    from src.run_engine import run_engine

    out_kp = ROOT / f"out_kp_{terrain}"
    dxf_files = sorted(out_kp.glob("*.dxf")) if out_kp.exists() else []

    if not force and dxf_files:
        laz_files = list(tiles_dir.glob("*.copc.laz")) + list(tiles_dir.glob("*.laz"))
        ref_mtime = _newest_mtime(*laz_files)
        if ref_mtime and all(f.stat().st_mtime >= ref_mtime for f in dxf_files):
            log.info("SKIP relief — DXF à jour")
            return f"skip : DXF à jour ({len(dxf_files)} fichiers dans {out_kp.name}/)"
        log.warning("relief : DXF périmés — relance KP")

    try:
        run_engine(terrain, cfg, tiles_dir, ROOT)
        dxf_count = len(sorted(out_kp.glob("*.dxf")))
        return f"ok : {dxf_count} DXF dans {out_kp.name}/"
    except Exception as exc:
        log.warning("relief : KP échoué — étape ignorée (%s)", exc)
        return f"ignoré : KP échoué ({exc})"


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


# ── Helpers template KP ──────────────────────────────────────────────────────

def _read_pgw(pgw_path: pathlib.Path) -> tuple[float, float, float]:
    """Retourne (res_m, top_left_x, top_left_y) depuis un world file PGW."""
    lines = pgw_path.read_text(encoding="utf-8").strip().splitlines()
    return abs(float(lines[0])), float(lines[4]), float(lines[5])


def _png_wh(png_path: pathlib.Path) -> tuple[int, int]:
    """Lit width/height depuis le header PNG sans décompresser l'image."""
    import struct
    with open(png_path, "rb") as f:
        f.read(8)   # signature PNG
        f.read(4)   # longueur chunk IHDR
        f.read(4)   # type 'IHDR'
        w = struct.unpack(">I", f.read(4))[0]
        h = struct.unpack(">I", f.read(4))[0]
    return w, h


def _merge_vege_tiles(
    out_kp: pathlib.Path,
    lightgreentone: int = 200,
) -> pathlib.Path | None:
    """Mosaïque les tuiles *_vege.png en un seul vegetation.png + vegetation.pgw.

    lightgreentone : ton du vert clair dans le PNG (0–255, défaut KP : 200).
    160 = fond lisible à 50 % d'opacité (validé 2026-09).
    Si != 200, un étirement de canal R/B est appliqué sur les pixels verts
    pour simuler le rendu qu'un vrai `makevegenew` produirait avec ce paramètre.
    Les tuiles sources (*_vege.png) ne sont jamais modifiées.

    Retourne le chemin du fichier produit, ou None si aucune tuile ou PIL absent.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        log.warning("PIL/numpy absent — vegetation.png non mosaïqué (pip install Pillow numpy)")
        return None

    tiles = sorted(out_kp.glob("*_vege.png"))
    if not tiles:
        return None

    info = []
    for tile in tiles:
        pgw = tile.with_suffix(".pgw")
        if not pgw.exists():
            continue
        res, tlx, tly = _read_pgw(pgw)
        w, h = _png_wh(tile)
        info.append((tile, res, tlx, tly, w, h))

    if not info:
        return None

    res_m = info[0][1]
    xmin = min(tlx for _, _, tlx, _, _, _ in info)
    ymax = max(tly for _, _, _, tly, _, _ in info)
    xmax = max(tlx + (w - 1) * res_m for _, _, tlx, _, w, _ in info)
    ymin = min(tly - (h - 1) * res_m for _, _, _, tly, _, h in info)

    canvas_w = round((xmax - xmin) / res_m) + 1
    canvas_h = round((ymax - ymin) / res_m) + 1
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    for tile_path, _, tlx, tly, _, _ in info:
        col = round((tlx - xmin) / res_m)
        row = round((ymax - tly) / res_m)
        with Image.open(tile_path) as img:
            canvas.paste(img.convert("RGB"), (col, row))

    # Remapping tone si différent du défaut KP (200)
    if lightgreentone != 200:
        arr = np.array(canvas, dtype=np.float32)
        # Pixels verts : G est le canal dominant, non-blanc
        is_green = (arr[:,:,1] > arr[:,:,0]) & (arr[:,:,1] > arr[:,:,2]) & (arr[:,:,0] < 248)
        factor = (255 - lightgreentone) / (255 - 200)
        for ch in (0, 2):  # R et B seulement — G reste 255
            arr[:,:,ch] = np.where(
                is_green,
                (255 + (arr[:,:,ch] - 255) * factor).clip(0, 255),
                arr[:,:,ch],
            )
        canvas = Image.fromarray(arr.astype(np.uint8))
        log.info("vegetation.png : tone remapping %d→%d appliqué", 200, lightgreentone)

    veg_png = out_kp / "vegetation.png"
    canvas.save(str(veg_png), "PNG")
    (out_kp / "vegetation.pgw").write_text(
        f"{res_m}\n0.0\n0.0\n-{res_m}\n{xmin}\n{ymax}\n",
        encoding="utf-8",
    )
    log.info(
        "vegetation.png mosaïqué : %d×%d px  (%.0f×%.0f m)",
        canvas_w, canvas_h, canvas_w * res_m, canvas_h * res_m,
    )
    return veg_png


def _png_to_template(
    png_path: pathlib.Path,
    omap_path: pathlib.Path,
    opacity_pct: int = 100,
):
    """Lit PNG + PGW et retourne un TemplateImage positionné en Lambert 93.

    Le chemin du fichier est exprimé relatif au .omap pour la portabilité.
    """
    from src.omap_writer import TemplateImage

    pgw_path = png_path.with_suffix(".pgw")
    if not pgw_path.exists():
        log.warning("PGW absent pour %s — template ignoré", png_path.name)
        return None

    res_m, top_left_x, top_left_y = _read_pgw(pgw_path)
    width_px, height_px = _png_wh(png_path)

    # Copie le PNG (+ PGW) dans le répertoire du .omap pour un chemin sans ../
    import shutil
    dest_png = omap_path.parent / png_path.name
    dest_pgw = dest_png.with_suffix(".pgw")
    if dest_png.resolve() != png_path.resolve():
        shutil.copy2(png_path, dest_png)
        shutil.copy2(pgw_path, dest_pgw)

    return TemplateImage(
        file=png_path.name,  # chemin relatif = juste le nom, même répertoire que le .omap
        top_left_x=top_left_x,
        top_left_y=top_left_y,
        width_px=width_px,
        height_px=height_px,
        res_m=res_m,
        name="vegetation.png",
        opacity_pct=opacity_pct,
    )


# ── Étape 6 : assemble ────────────────────────────────────────────────────────

def step_assemble(terrain: str, cfg: dict, force: bool) -> None:
    import shapely.geometry as sg
    from scripts.generate_bdtopo import build_bdtopo_layers, load_mapping as load_bd_mapping
    from scripts.generate_relief import build_relief_layers, load_relief_mapping
    from scripts.mask_vegetation import build_fill_layers
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
    # Végétation : fournie par le fond KP (vegetation.png en template).
    # Les couches 406/408/410 ne sont plus injectées dans le .omap.

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


    template = load_template(ASSETS / "ISOM 2017-2_10000.omap")
    georef = load_georef(ASSETS / f"georef_{terrain}.xml")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # Template KP végétation
    kp_rendering = cfg.get("karttapullautin", {}).get("rendering", {}) or {}
    lightgreentone: int = kp_rendering.get("lightgreentone", 200) or 200
    template_opacity_pct: int = kp_rendering.get("template_opacity_pct", 100) or 100

    veg_png = out_kp / "vegetation.png"
    if out_kp.exists() and list(out_kp.glob("*_vege.png")):
        # Re-mosaïque toujours : applique le tone mapping courant
        merged = _merge_vege_tiles(out_kp, lightgreentone=lightgreentone)
        if merged is not None:
            veg_png = merged
    img_templates = []
    if veg_png.exists():
        tmpl = _png_to_template(veg_png, out, opacity_pct=template_opacity_pct)
        if tmpl is not None:
            img_templates.append(tmpl)
            log.info(
                "Template KP végétation : %s (%d×%d px, tone=%d, opacité=%d%%)",
                veg_png.name, tmpl.width_px, tmpl.height_px, lightgreentone, template_opacity_pct,
            )
    else:
        log.info("vegetation.png absent dans %s — template omis", out_kp.name)

    write_omap(out, template, all_layers, georef, image_templates=img_templates or None)
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

    # Compte livrable total (sans clip hull) — valeur reproductible pour les releases
    total_by_class = gdf.groupby("class").size().to_dict()
    log.info(
        "Polygones livrables (vegetation_masked.gpkg, sans clip hull) : %s",
        "  ".join(f"{cls}={total_by_class.get(cls, 0)}" for cls in [406, 408, 410]),
    )
    print()
    print("=== Livrable — polygones vegetation_masked.gpkg (emprise totale) ===")
    for cls in [406, 408, 410]:
        print(f"    {cls} : {total_by_class.get(cls, 0):,} polygones")

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


# ── Sous-commande : init ──────────────────────────────────────────────────────

def _cmd_init() -> None:
    from src.init_terrain import cmd_init

    parser = argparse.ArgumentParser(
        prog="main.py init",
        description="Initialise un terrain : config.yaml + georef XML depuis coordonnées géo.",
    )
    parser.add_argument("terrain", help="Nom du terrain (ex: my_forest)")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--center", nargs=2, type=float, metavar=("LAT", "LON"),
        help="Centre géographique WGS84 (ex: 49.043 -0.421)",
    )
    grp.add_argument(
        "--bbox", nargs=4, type=float, metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        help="Bbox projetée (requiert --crs)",
    )
    parser.add_argument("--size", type=float, metavar="M", help="Côté du carré en mètres (défaut 2000)")
    parser.add_argument("--crs", metavar="EPSG:XXXX", help="CRS projeté (déduit si --center)")
    parser.add_argument("--force", action="store_true", help="Écrase le terrain s'il existe déjà")
    cmd_init(parser.parse_args())


# ── Sous-commande : tiles ─────────────────────────────────────────────────────

def _cmd_tiles() -> None:
    from src.providers import find_tiles

    parser = argparse.ArgumentParser(
        prog="main.py tiles",
        description="Liste les dalles LiDAR nécessaires pour couvrir la bbox du terrain.",
    )
    parser.add_argument("terrain", help="Nom du terrain")
    args = parser.parse_args()

    cfg = _load_config()
    terrain_cfg = (cfg.get("terrains") or {}).get(args.terrain)
    if terrain_cfg is None:
        sys.exit(f"ERREUR : terrain '{args.terrain}' introuvable dans config.yaml — lancer init d'abord")

    bbox = terrain_cfg.get("bbox")
    crs = terrain_cfg.get("crs", "")
    if bbox is None:
        sys.exit("ERREUR : bbox manquante dans config.yaml pour ce terrain")

    terrain = args.terrain
    tiles, source = find_tiles(tuple(bbox), crs)
    if not tiles:
        print(f"Pas de connecteur pour CRS {crs}.")
        print(f"Placez vos dalles LiDAR (LAZ/COPC) couvrant la bbox dans LIDAR/{terrain}/")
        print(f"  bbox : {bbox}")
        return

    print(f"Tuiles LiDAR HD à télécharger ({len(tiles)}) :")
    for t in tiles:
        print(f"  {t}")
    print(f"Source : {source}")
    print(f"À placer dans : LIDAR/{terrain}/")


# ── Sous-commande : check ─────────────────────────────────────────────────────

def _cmd_check() -> None:
    from src.check_terrain import cmd_check

    parser = argparse.ArgumentParser(
        prog="main.py check",
        description="Vérifie dalles, recouvrement, georef XML avant le pipeline.",
    )
    parser.add_argument("terrain", help="Nom du terrain")
    args = parser.parse_args()

    cfg = _load_config()
    ok = cmd_check(args.terrain, cfg, ROOT)
    if not ok:
        sys.exit(1)
    print("check : tous les contrôles OK")


# ── Sous-commande : run (pipeline principal) ───────────────────────────────────

def _cmd_run() -> None:
    from src.check_terrain import cmd_check

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
    parser.add_argument("--skip-check", action="store_true", help="Ignore les vérifications pré-run (check)")
    args = parser.parse_args()

    global OUTPUT

    cfg = _load_config()

    if not args.skip_check:
        tiles_path = pathlib.Path(args.tiles_dir) if args.tiles_dir else None
        if not cmd_check(args.terrain, cfg, ROOT, lidar_dir=tiles_path):
            sys.exit("ERREUR pré-run — corriger les problèmes ci-dessus ou relancer avec --skip-check")

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
            run_tiles: list[str] = []
            if args.tiles_dir:
                td = pathlib.Path(args.tiles_dir)
                run_tiles = [str(p) for p in sorted(td.glob("*.copc.laz"))]
                if not run_tiles:
                    run_tiles = [str(p) for p in sorted(td.glob("*.laz"))]
            elif args.tiles:
                run_tiles = args.tiles
            if not run_tiles:
                sys.exit("--tiles-dir ou --tiles requis pour l'étape pdal (ou utiliser --skip-pdal)")
            step_pdal(args.terrain, cfg, run_tiles, args.reader, args.force)

        if should_run("process_hag"):
            step_process_hag(cfg, args.force)

    relief_status = "non lancé"
    if should_run("relief"):
        relief_tiles_dir = pathlib.Path(args.tiles_dir) if args.tiles_dir else None
        relief_status = step_relief(args.terrain, cfg, relief_tiles_dir, args.force)

    if should_run("vegetation"):
        step_vegetation(args.terrain, cfg, args.force)

    if should_run("mask"):
        step_mask(args.terrain, cfg, args.force)

    if should_run("assemble"):
        step_assemble(args.terrain, cfg, args.force)

    if should_run("qa"):
        step_qa(args.terrain, cfg)

    log.info("──────────────────────────────────────────")
    log.info("Pipeline terminé — terrain : %s", args.terrain)
    log.info("  relief  : %s", relief_status)
    out_omap = OUTPUT / f"{args.terrain}.omap"
    if out_omap.exists():
        log.info("  sortie  : %s", out_omap)


# ── CLI ───────────────────────────────────────────────────────────────────────

_SUBCOMMANDS = {"init", "tiles", "check", "run"}


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] in _SUBCOMMANDS:
        subcmd = sys.argv.pop(1)
        {"init": _cmd_init, "tiles": _cmd_tiles, "check": _cmd_check, "run": _cmd_run}[subcmd]()
    else:
        _cmd_run()


if __name__ == "__main__":
    main()
