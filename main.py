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
  3c vegetation_kp — PNG KP → source_kp_classified.tif → vegetation_kp.gpkg (coverage_simplify 2 m)
  4  vegetation    — run_pipeline → output/vegetation.gpkg
  5  mask          — masque anthropique → output/vegetation_masked.gpkg
  6  assemble      — assemblage final → output/{terrain}.omap
  7  qa            — métriques hull → console + output/run_metadata.json
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import subprocess
import sys

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).parent.resolve()
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
OUTPUT = ROOT / "output"  # remplacé dans main() selon output_dir du terrain
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable

STEPS = ["fetch", "pdal", "process_hag", "relief", "vegetation_kp", "supervised_e", "vegetation", "mask", "assemble", "qa"]
_STEP_IDX = {s: i for i, s in enumerate(STEPS)}


def _add_pipeline_log_handler(output_dir: pathlib.Path) -> None:
    """Ajoute un FileHandler sur le logger racine → OUTPUT/pipeline.log."""
    log_path = output_dir / "pipeline.log"
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
    logging.getLogger().addHandler(fh)
    log.info("Journal pipeline : %s", log_path)


def _count_omap_objects(omap_path: pathlib.Path) -> dict:
    """Compte les objets placés par famille ISOM dans le .omap produit.

    Utilise les codes ISOM des définitions de symboles du gabarit, non des
    indices de position qui varient d'un gabarit à l'autre.
    Seuls les objets réellement placés (dans <parts>) sont comptés —
    les prototypes internes aux définitions de symboles sont exclus.
    """
    import xml.etree.ElementTree as ET
    NS = "{http://openorienteering.org/apps/mapper/xml/v2}"
    try:
        root = ET.parse(str(omap_path)).getroot()
        barrier = root.find(f"{NS}barrier")
        if barrier is None:
            raise ValueError("élément <barrier> absent")

        # 1. Table symbole_id → code ISOM (float pour comparaison de plages)
        sym_map: dict[str, float] = {}
        sym_root = barrier.find(f"{NS}symbols")
        if sym_root is not None:
            for sym in sym_root:
                sid = sym.get("id")
                code_str = sym.get("code", "")
                if sid and code_str:
                    try:
                        sym_map[sid] = float(code_str)
                    except ValueError:
                        pass

        # 2. Objets placés uniquement (pas les prototypes dans <symbols>)
        placed_total = 0
        placed_codes: list[float] = []
        parts_root = barrier.find(f"{NS}parts")
        if parts_root is not None:
            for part in parts_root.findall(f"{NS}part"):
                objs_el = part.find(f"{NS}objects")
                if objs_el is None:
                    continue
                for obj in objs_el.findall(f"{NS}object"):
                    placed_total += 1
                    sym_ref = obj.get("symbol")
                    if sym_ref and sym_ref in sym_map:
                        placed_codes.append(sym_map[sym_ref])

        def _n(lo: float, hi: float) -> int:
            return sum(1 for c in placed_codes if lo <= c < hi)

        return {
            "total":           placed_total,
            "vegetation":      _n(400, 420),
            "routes":          _n(500, 520),
            "batiments":       _n(521, 560),  # ISOM 521+ uniquement (bâtiments individuels)
            "zones_interdites": _n(520, 521), # ISOM 520 : zone à ne pas pénétrer
            "eau":             _n(300, 400),
            "relief":          _n(100, 200),
        }
    except Exception as exc:
        return {"erreur": str(exc)}


def _load_config(config_path: "pathlib.Path | None" = None) -> dict:
    from src.paths import get_config_path
    cfg = yaml.safe_load(get_config_path(explicit=config_path).read_text(encoding="utf-8")) or {}
    terrains = cfg.get("terrains")
    if terrains is not None and not isinstance(terrains, dict):
        raise TypeError(
            f"config.yaml : 'terrains' doit être un dictionnaire (trouvé : {type(terrains).__name__})"
        )
    return cfg


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

def _run_fetch_script(terrain: str) -> None:
    subprocess.run(
        [PYTHON, "-m", "scripts.fetch", terrain],
        cwd=ROOT,
        check=True,
    )


def step_fetch(terrain: str, cfg: dict, force: bool) -> None:
    tcfg = (cfg.get("terrains") or {}).get(terrain, {})
    bdtopo_path = tcfg.get("bdtopo_path")
    dept = tcfg.get("departement")

    # Résoudre la source avec la même priorité que scripts/fetch.py :
    # 1. bdtopo_path explicite → erreur si absent
    # 2. departement → find_gpkg dans data/bdtopo/ (même sélection que fetch.py)
    # 3. aucun des deux → terrain sans BD TOPO, étape ignorée
    source: pathlib.Path | None = None
    if bdtopo_path:
        source = pathlib.Path(bdtopo_path)
        if not source.exists():
            log.error("fetch : bdtopo_path configuré mais fichier absent : %s", source)
            sys.exit(1)
    elif dept:
        from scripts.fetch import find_gpkg
        try:
            source = find_gpkg(DATA / "bdtopo", dept)
        except FileNotFoundError:
            source = None  # SKIP si sortie existe, sinon fetch produira son erreur
    else:
        log.info(
            "fetch : ni 'bdtopo_path' ni 'departement' pour '%s' — étape ignorée",
            terrain,
        )
        return

    out = DATA / f"{terrain}_bdtopo.gpkg"
    if not force and out.exists():
        if source is None or _is_fresh(out, source):
            log.info("SKIP fetch — %s à jour", out.name)
            return
        log.warning("fetch : %s périmé (< %s) — relance", out.name, source.name)

    _run_fetch_script(terrain)


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
        [PYTHON, "-m", "scripts.process_hag", "--src", str(hag_tif), "--dst", str(OUTPUT)],
        cwd=ROOT,
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
        locate_binary(cfg, terrain)
    except FileNotFoundError:
        log.warning("relief : KP (pullauta) introuvable — étape ignorée")
        return "ignoré : KP absent (définir KP_BINARY ou ajouter pullauta au PATH)"

    if tiles_dir is None:
        log.warning("relief : --tiles-dir requis pour lancer KP — étape ignorée")
        return "ignoré : --tiles-dir manquant"

    from src.run_engine import build_ini_content, run_engine

    out_kp = OUTPUT / f"out_kp_{terrain}"
    dxf_files = sorted(out_kp.glob("*.dxf")) if out_kp.exists() else []

    if not force and dxf_files:
        laz_files = list(tiles_dir.glob("*.copc.laz")) + list(tiles_dir.glob("*.laz"))
        ref_mtime = _newest_mtime(*laz_files)
        if ref_mtime and all(f.stat().st_mtime >= ref_mtime for f in dxf_files):
            # DXF frais vs LAZ — vérifier aussi que l'ini n'a pas changé.
            kp_cliff = cfg.get("karttapullautin", {}).get("cliff", {}) or {}
            kp_rendering = cfg.get("karttapullautin", {}).get("rendering", {}) or {}
            expected_ini = build_ini_content(
                tiles_dir, out_kp, ROOT,
                cliffheight=kp_cliff.get("cliffheight"),
                cliffangle=kp_cliff.get("cliffangle"),
                lightgreentone=kp_rendering.get("lightgreentone"),
                medianboxsize2=kp_rendering.get("medianboxsize2"),
            )
            existing_ini = out_kp / "pullauta.ini"
            if existing_ini.exists() and existing_ini.read_text(encoding="utf-8") == expected_ini:
                log.info("SKIP relief — DXF à jour, ini inchangé")
                return f"skip : DXF à jour ({len(dxf_files)} fichiers dans {out_kp.name}/)"
            log.warning(
                "relief : DXF à jour mais ini différent (config.yaml modifié ?) — relance KP"
            )
        else:
            log.warning("relief : DXF périmés — relance KP")

    try:
        run_engine(terrain, cfg, tiles_dir, ROOT, output_root=OUTPUT)
        dxf_count = len(sorted(out_kp.glob("*.dxf")))
        return f"ok : {dxf_count} DXF dans {out_kp.name}/"
    except Exception as exc:
        log.warning("relief : KP échoué — étape ignorée (%s)", exc)
        return f"ignoré : KP échoué ({exc})"


# ── Étape 3c : vegetation_kp ─────────────────────────────────────────────────

def step_vegetation_kp(terrain: str, cfg: dict, force: bool) -> None:
    """PNG KP → vegetation_kp.gpkg via classification + polygonisation + coverage_simplify.

    Fraîcheur sur les *_vege*.png, pas les DXF (piège §5 PLAN 3 + commit ecf62e7).
    Couverture validée AVANT coverage_simplify (§6.1 PLAN 3).
    """
    import geopandas as gpd
    import numpy as np
    import shapely
    import shapely.geometry as sg

    out_kp = OUTPUT / f"out_kp_{terrain}"
    veg_kp_gpkg = OUTPUT / "vegetation_kp.gpkg"

    png_files: list[pathlib.Path] = []
    if out_kp.exists():
        png_files = [
            p for p in sorted(out_kp.glob("*_vege*.png"))
            if not p.name.startswith("merged")
        ]

    if not png_files:
        if not out_kp.exists():
            from src.pipeline_mode import resolve_veg_source

            if resolve_veg_source(terrain, cfg) == "kp":
                raise RuntimeError(
                    f"vegetation_kp : mode KP (défaut ou explicite) mais {out_kp.name}/ absent — "
                    "lancer Karttapullautin (étape relief) avant, ou déclarer "
                    "vegetation_source: \"hag\" explicitement pour ce terrain."
                )
            # Mode HAG explicite et KP non lancé : étape ignorée, végétation KP omise de l'OMAP.
            log.info("vegetation_kp : %s absent — étape ignorée (mode hag)", f"out_kp_{terrain}/")
            return
        raise RuntimeError(
            f"vegetation_kp : {out_kp.name}/ existe mais aucun *_vege*.png trouvé — "
            "vérifier vege_bitmode dans pullauta.ini ou relancer step_relief."
        )

    vect_cfg = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {})
    cfg_hash_file = OUTPUT / ".vege_kp_cfg_hash"

    def _vect_cfg_hash() -> str:
        import hashlib, json as _json
        return hashlib.md5(_json.dumps(vect_cfg, sort_keys=True).encode()).hexdigest()

    if not force and veg_kp_gpkg.exists():
        ref_mtime = _newest_mtime(*png_files)
        cfg_ok = cfg_hash_file.exists() and cfg_hash_file.read_text() == _vect_cfg_hash()
        if ref_mtime and veg_kp_gpkg.stat().st_mtime >= ref_mtime and cfg_ok:
            log.info("SKIP vegetation_kp — vegetation_kp.gpkg à jour")
            return
        if not cfg_ok:
            log.warning(
                "vegetation_kp : configuration vectorisation modifiée (shade_to_isom, "
                "coverage_simplify_m, input…) — relance"
            )
        else:
            log.warning("vegetation_kp : vegetation_kp.gpkg périmé — relance")

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
    terrain_crs: str = terrain_cfg.get("crs", "EPSG:2154")
    bbox = terrain_cfg.get("bbox")
    tol = float(vect_cfg.get("coverage_simplify_m", 2.0))

    # P5 — raster classifié KP
    from src.kp_raster import ISOM_TO_DN, build_class_raster
    source_tif = OUTPUT / "source_kp_classified.tif"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    build_class_raster(
        out_kp, cfg, terrain_crs, source_tif,
        bbox=tuple(bbox) if bbox else None,
    )

    # P6 — polygonisation RAW (raster → vecteur lossless avant simplification)
    import rasterio
    from rasterio.features import shapes as rasterio_shapes
    dn_to_isom = {v: k for k, v in ISOM_TO_DN.items()}
    with rasterio.open(source_tif) as ds:
        data = ds.read(1)
        transform = ds.transform
        crs_raster = ds.crs.to_string()

    # P6/P7 — polygonisation + coverage_is_valid intra-classe + coverage_simplify global.
    # Les T-junctions inter-classes sont structurelles (polygonisation séparée par masque,
    # diagnostiquées sur V1). coverage_is_valid est appliqué par classe pour détecter les
    # overlaps intra-classe réels. coverage_simplify est appelé sur l'ensemble 406+408+410 :
    # les T-junctions y sont tolérées et les frontières inter-classes sont résolues
    # conjointement, évitant les overlaps inter-classes qu'un simplify per-classe produirait.
    all_geoms: list = []
    all_codes: list[int] = []

    for dn, isom in sorted(dn_to_isom.items()):
        mask_arr = (data == dn).astype(np.uint8)
        geoms: list = []
        for geom_dict, _ in rasterio_shapes(mask_arr, mask=mask_arr, transform=transform):
            geom = sg.shape(geom_dict)
            if not geom.is_empty:
                geoms.append(geom)

        if not geoms:
            continue

        geom_arr_cls = np.array(geoms, dtype=object)
        if not shapely.coverage_is_valid(geom_arr_cls):
            invalid_edges = shapely.coverage_invalid_edges(geom_arr_cls)
            n_invalid = int(sum(1 for e in invalid_edges if e is not None and not e.is_empty))
            raise ValueError(
                f"vegetation_kp : couverture invalide avant coverage_simplify "
                f"pour la classe {isom} ({n_invalid} arete(s) invalide(s)) — "
                "verifier la polygonisation."
            )

        all_geoms.extend(geoms)
        all_codes.extend([isom] * len(geoms))

    if not all_geoms:
        log.warning("vegetation_kp : aucun polygone produit — vegetation_kp.gpkg vide")
        for code in [406, 408, 410]:
            gpd.GeoDataFrame({"geometry": []}, crs=crs_raster).to_file(
                veg_kp_gpkg, layer=f"veg_{code}", driver="GPKG",
            )
        cfg_hash_file.write_text(_vect_cfg_hash())
        return

    geom_arr = np.array(all_geoms, dtype=object)
    simplified = shapely.coverage_simplify(geom_arr, tolerance=tol, simplify_boundary=True)

    layers: dict[int, list] = {406: [], 408: [], 410: []}
    for geom, code in zip(simplified, all_codes):
        if geom is not None and not geom.is_empty:
            layers[code].append(geom)

    for code in [406, 408, 410]:
        gdf = gpd.GeoDataFrame({"geometry": layers[code]}, crs=crs_raster)
        gdf.to_file(veg_kp_gpkg, layer=f"veg_{code}", driver="GPKG")

    counts = {c: len(v) for c, v in layers.items()}
    log.info("vegetation_kp : 406=%d 408=%d 410=%d polygones -> %s",
             counts[406], counts[408], counts[410], veg_kp_gpkg.name)
    cfg_hash_file.write_text(_vect_cfg_hash())


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


# ── Étape : supervised_e (expérimental) ───────────────────────────────────────

def step_supervised_e(
    terrain: str,
    cfg: dict,
    laz_files: list[str],
    force: bool,
) -> pathlib.Path:
    """Inférence végétation supervised_e depuis LAZ bruts.

    Produit :
      output/supervised_e_prediction.tif    (uint8, 2 bandes)
      output/vegetation_supervised_e.gpkg   (veg_401/406/408/410)
      output/supervised_e_coverage.tif      (masque couverture LiDAR)
    """
    from src.supervised_e import run_supervised_e, EXPORT_MODE_FAITHFUL

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
    bbox = terrain_cfg.get("bbox")
    if bbox is None:
        sys.exit(
            f"ERREUR supervised_e : bbox manquant pour le terrain {terrain!r}.\n"
            f"Ajouter terrains.{terrain}.bbox: [xmin, ymin, xmax, ymax] dans config.yaml"
        )

    _pred_tif = OUTPUT / "supervised_e_prediction.tif"
    if not laz_files and not _pred_tif.exists():
        sys.exit(
            "ERREUR supervised_e : aucun fichier LAZ et aucun raster de prédiction existant.\n"
            "Passer --tiles-dir ou --tiles pour l'inférence."
        )
    if not laz_files:
        log.info("supervised_e : raster existant détecté — revectorisation sans réinférence.")

    export_mode = cfg.get("vegetation_export_mode", EXPORT_MODE_FAITHFUL)

    cache_dir = OUTPUT / "supervised_e_cache"
    result = run_supervised_e(
        laz_files=[pathlib.Path(f) for f in laz_files],
        bbox=list(bbox),
        output_dir=OUTPUT,
        cache_dir=cache_dir,
        force=force,
        export_mode=export_mode,
    )
    pred_tif = result["prediction_tif"]
    veg_gpkg = result.get("vegetation_gpkg")
    try:
        log.info("supervised_e : prédiction dans %s", pred_tif.relative_to(ROOT))
    except ValueError:
        log.info("supervised_e : prédiction dans %s", pred_tif)
    if veg_gpkg and veg_gpkg.exists():
        try:
            log.info("supervised_e : vegetation dans %s", veg_gpkg.relative_to(ROOT))
        except ValueError:
            log.info("supervised_e : vegetation dans %s", veg_gpkg)
    return pred_tif


# ── Étape 5 : mask ────────────────────────────────────────────────────────────

def step_mask(terrain: str, cfg: dict, force: bool) -> None:
    import shapely.geometry as sg
    from scripts.mask_vegetation import _fetch_osm, apply_mask, build_mask

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
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


def _build_ocad_veg_template(
    src_png: pathlib.Path,
    omap_out: pathlib.Path,
) -> "TemplateImage | None":
    """Prépare le VegetationBaseMap OCAD comme template OOM.

    Rend transparent le fond jaune OCAD (255,201,15) — terrain courable en dehors
    de la forêt. Toutes les autres couleurs (verts, blanc, noir) sont conservées.
    Résolution native préservée — aucun rééchantillonnage.
    """
    from src.omap_writer import TemplateImage
    try:
        from PIL import Image as _PILImage
        import numpy as _np
    except ImportError:
        log.warning("PIL absent — template OCAD végétation ignoré (pip install Pillow)")
        return None

    pgw_path = src_png.with_suffix(".pgw")
    if not pgw_path.exists():
        log.warning("PGW absent pour %s — template OCAD ignoré", src_png.name)
        return None
    if not src_png.exists():
        log.warning("PNG absent : %s — template OCAD ignoré", src_png)
        return None

    arr = _np.array(_PILImage.open(src_png).convert("RGB"))
    rgba = _np.zeros((*arr.shape[:2], 4), dtype=_np.uint8)
    rgba[:, :, :3] = arr
    rgba[:, :, 3] = 255

    # Fond jaune OCAD (terrain courable hors-forêt) → transparent
    is_yellow = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 201) & (arr[:, :, 2] == 15)
    rgba[is_yellow, 3] = 0
    n_transparent = int(is_yellow.sum())

    dest_name = "ocad_vegetation.png"
    dest_png = omap_out.parent / dest_name
    _PILImage.fromarray(rgba).save(str(dest_png), "PNG")
    import shutil as _shutil
    _shutil.copy2(pgw_path, dest_png.with_suffix(".pgw"))

    res_m, top_left_x, top_left_y = _read_pgw(pgw_path)
    h, w = arr.shape[:2]
    log.info(
        "Template OCAD végétation : %s (%d×%d px, %.0f m/px, %d px transparents / %d total)",
        dest_name, w, h, res_m, n_transparent, h * w,
    )
    return TemplateImage(
        file=dest_name,
        top_left_x=top_left_x,
        top_left_y=top_left_y,
        width_px=w,
        height_px=h,
        res_m=res_m,
        name="OCAD végétation",
        opacity_pct=100,
    )


def _build_img_templates(
    out_kp: pathlib.Path,
    kp_cfg: dict,
    omap_out: pathlib.Path,
) -> list:
    """Construit la liste des TemplateImage KP végétation selon keep_template.

    Retourne [] si keep_template=False ou si aucun PNG disponible.
    """
    kp_rendering = kp_cfg.get("rendering", {}) or {}
    kp_vect = kp_cfg.get("vectorization", {}) or {}
    lightgreentone: int = kp_rendering.get("lightgreentone", 200) or 200
    template_opacity_pct: int = kp_rendering.get("template_opacity_pct", 100) or 100
    keep_template: bool = bool(kp_vect.get("keep_template", True))

    if not keep_template:
        log.info("keep_template=false — template végétation exclu de l'OMAP")
        return []

    veg_png = out_kp / "vegetation.png"
    if out_kp.exists() and list(out_kp.glob("*_vege.png")):
        merged = _merge_vege_tiles(out_kp, lightgreentone=lightgreentone)
        if merged is not None:
            veg_png = merged

    if not veg_png.exists():
        log.info("vegetation.png absent dans %s — template omis", out_kp.name)
        return []

    tmpl = _png_to_template(veg_png, omap_out, opacity_pct=template_opacity_pct)
    if tmpl is None:
        return []

    log.info(
        "Template KP végétation : %s (%d×%d px, tone=%d, opacité=%d%%)",
        veg_png.name, tmpl.width_px, tmpl.height_px, lightgreentone, template_opacity_pct,
    )
    return [tmpl]


# ── Étape 6 : assemble ────────────────────────────────────────────────────────

def step_assemble(terrain: str, cfg: dict, force: bool, veg_mode: str = "kp") -> None:
    import shapely.geometry as sg
    from scripts.generate_bdtopo import build_bdtopo_layers, load_mapping as load_bd_mapping
    from scripts.generate_relief import build_relief_layers, load_relief_mapping
    from scripts.mask_vegetation import build_fill_layers
    from src.omap_writer import load_georef, load_template, write_omap

    import geopandas as gpd
    import numpy as np
    import shapely
    from src.omap_writer import Layer

    from src.supervised_e import EXPORT_MODE_FAITHFUL as _SE_FAITHFUL
    _se_export_mode = cfg.get("vegetation_export_mode", _SE_FAITHFUL)

    out = OUTPUT / f"{terrain}.omap"
    veg_kp_gpkg = OUTPUT / "vegetation_kp.gpkg"
    veg_se_gpkg = OUTPUT / f"vegetation_supervised_e_{_se_export_mode}.gpkg"
    bdtopo_gpkg = DATA / f"{terrain}_bdtopo.gpkg"
    out_kp = OUTPUT / f"out_kp_{terrain}"
    osm_cache = DATA / f"osm_landuse_{terrain}.json"

    # Verrou supprimé : vegetation_masked.gpkg n'est plus une dépendance de l'assemblage.
    # La végétation vient de vegetation_kp.gpkg (branche KP) ou vegetation_supervised_e.gpkg.
    if not bdtopo_gpkg.exists():
        log.warning("assemble : %s absent — couches BD TOPO ignorées (fill OSM conservé)", bdtopo_gpkg.name)
        bdtopo_gpkg = None  # type: ignore[assignment]

    dxf_files = sorted(out_kp.glob("*.dxf")) if out_kp.exists() else []
    veg_ref = veg_se_gpkg if veg_mode == "supervised_e" else veg_kp_gpkg
    ref_sources = [p for p in [veg_ref, bdtopo_gpkg] if p is not None]
    ref_mtime = _newest_mtime(*ref_sources, *dxf_files)

    if not force and out.exists() and ref_mtime and out.stat().st_mtime >= ref_mtime:
        log.info("SKIP assemble — %s à jour", out.name)
        return
    if out.exists():
        log.warning("assemble : %s périmé — relance", out.name)

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
    terrain_crs = terrain_cfg.get("crs", "EPSG:2154")
    bbox = terrain_cfg.get("bbox")
    bbox_geom = sg.box(*bbox) if bbox else None
    ocad_veg_png_str = terrain_cfg.get("ocad_vegetation_png")
    ocad_veg_path = pathlib.Path(ocad_veg_png_str) if ocad_veg_png_str else None

    def _clip(layers: list, family: str) -> list:
        return _clip_layers_to_bbox(layers, bbox_geom, family) if bbox_geom is not None else layers

    all_layers: list = []

    if ocad_veg_path:
        # Source OCAD active : végétation vectorielle ignorée — raster template à la place.
        log.info("assemble : source végétation OCAD (%s) — vegetation ignorée", ocad_veg_path.name)
    elif veg_mode == "supervised_e":
        # Végétation supervised_e (401/406/408/410) depuis vegetation_supervised_e.gpkg.
        # Pas de contrôle d'overlap : la vectorisation pixel-par-pixel garantit l'exclusivité.
        veg_layers_clipped: list = []
        if veg_se_gpkg.exists():
            for veg_code in [401, 406, 408, 410]:
                layer_name = f"veg_{veg_code}"
                try:
                    gdf_veg = gpd.read_file(str(veg_se_gpkg), layer=layer_name)
                    if not gdf_veg.empty:
                        lyr = Layer(layer_name, veg_code, list(gdf_veg.geometry))
                        veg_layers_clipped.append(lyr)
                        log.info("vegetation_supervised_e %d : %d polygones", veg_code, len(gdf_veg))
                except Exception as exc:
                    log.warning("vegetation_supervised_e %d ignorée : %s", veg_code, exc)
            veg_layers_clipped = _clip(veg_layers_clipped, "vegetation_supervised_e")
            all_layers += veg_layers_clipped
        else:
            raise RuntimeError(
                "assemble mode supervised_e : vegetation_supervised_e.gpkg absent — "
                "relancer step_supervised_e d'abord."
            )
    else:
        # Végétation KP (406/408/410) depuis vegetation_kp.gpkg — branche KP §8 PLAN 3
        veg_layers_clipped: list = []
        if veg_kp_gpkg.exists():
            for veg_code in [406, 408, 410]:
                layer_name = f"veg_{veg_code}"
                try:
                    gdf_veg = gpd.read_file(str(veg_kp_gpkg), layer=layer_name)
                    if not gdf_veg.empty:
                        lyr = Layer(layer_name, veg_code, list(gdf_veg.geometry))
                        veg_layers_clipped.append(lyr)
                        log.info("vegetation_kp %d : %d polygones", veg_code, len(gdf_veg))
                except Exception as exc:
                    log.warning("vegetation_kp %d ignorée : %s", veg_code, exc)
            veg_layers_clipped = _clip(veg_layers_clipped, "vegetation_kp")

            # Contrôle topologique overlaps==0 APRÈS clip (§8 PLAN 3).
            # On vérifie l'absence d'overlap surfacique (sum_area - union_area > seuil).
            # coverage_is_valid n'est pas utilisé ici : les T-junctions inter-classes
            # sont structurelles et ne constituent pas un overlap (cf. diagnostic V1).
            all_veg_geoms = [g for lyr in veg_layers_clipped for g in lyr.geometries]
            if all_veg_geoms:
                union_area = shapely.unary_union(all_veg_geoms).area
                sum_area = sum(g.area for g in all_veg_geoms)
                overlap_area = sum_area - union_area
                if overlap_area > 0.01:
                    raise ValueError(
                        f"assemble : overlaps detectes dans la vegetation KP apres clip "
                        f"({overlap_area:.2f} m2 recouverts) — verifier step_vegetation_kp."
                    )
            all_layers += veg_layers_clipped
        else:
            # Si out_kp/ existe, KP a tourné et vegetation_kp doit être présent — état anormal.
            # Sinon, KP n'a jamais été lancé : carte sans végétation vectorielle est attendue.
            if (OUTPUT / f"out_kp_{terrain}").exists():
                raise RuntimeError(
                    f"assemble : out_kp_{terrain}/ présent mais vegetation_kp.gpkg absent — "
                    "relancer step_vegetation_kp (--from-step vegetation_kp) avant step_assemble."
                )
            log.info("assemble : vegetation_kp.gpkg absent (KP non lancé) — végétation omise du .omap")

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

    if ocad_veg_path:
        img_templates = [t for t in [_build_ocad_veg_template(ocad_veg_path, out)] if t is not None]
    elif veg_mode == "supervised_e":
        img_templates = []
        log.info("supervised_e : template KP végétation désactivé par défaut")
    else:
        kp_cfg = cfg.get("karttapullautin", {}) or {}
        img_templates = _build_img_templates(out_kp, kp_cfg, out)
    write_omap(out, template, all_layers, georef, image_templates=img_templates or None)
    log.info("Assemblé : %s (%d couches)", out, len(all_layers))


# ── Étape 7 : qa ─────────────────────────────────────────────────────────────

def step_qa(terrain: str, cfg: dict) -> None:
    import geopandas as gpd
    import pandas as pd
    from src.qa import load_ffco_hull, report_hull_metrics, report_recall_by_class, write_config_snapshot

    # QA KP par défaut (livrable) ; QA HAG en fallback si vegetation_kp.gpkg absent.
    # §9 PLAN 3 : la source est nommée dans les logs et dans run_metadata.json.
    veg_kp_gpkg = OUTPUT / "vegetation_kp.gpkg"
    masked_gpkg = OUTPUT / "vegetation_masked.gpkg"

    if veg_kp_gpkg.exists():
        qa_gpkg = veg_kp_gpkg
        qa_source = "vegetation_kp.gpkg (branche KP)"
    elif masked_gpkg.exists():
        qa_gpkg = masked_gpkg
        qa_source = "vegetation_masked.gpkg (branche HAG — vegetation_kp.gpkg absent)"
        log.warning("QA : vegetation_kp.gpkg absent — QA HAG utilisée (%s)", masked_gpkg.name)
    else:
        log.warning("QA : vegetation_kp.gpkg et vegetation_masked.gpkg absents — QA ignorée")
        write_config_snapshot(cfg, OUTPUT, extra={"qa_vegetation_source": None})
        return

    log.info("QA source : %s", qa_source)

    parts = []
    for cls in [406, 408, 410]:
        layer = f"veg_{cls}"
        try:
            sub = gpd.read_file(str(qa_gpkg), layer=layer)
            sub["class"] = cls
            parts.append(sub)
        except Exception:
            pass
    if not parts:
        log.warning("QA : aucune couche veg_* lisible dans %s", qa_gpkg.name)
        write_config_snapshot(cfg, OUTPUT, extra={"qa_vegetation_source": qa_source})
        return
    gdf = pd.concat(parts, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=parts[0].crs)

    # Compte livrable total (sans clip hull) — valeur reproductible pour les releases
    total_by_class = gdf.groupby("class").size().to_dict()
    log.info(
        "Polygones livrables (%s, sans clip hull) : %s",
        qa_gpkg.name,
        "  ".join(f"{cls}={total_by_class.get(cls, 0)}" for cls in [406, 408, 410]),
    )
    print()
    print(f"=== QA — polygones {qa_gpkg.name} (emprise totale) ===")
    for cls in [406, 408, 410]:
        print(f"    {cls} : {total_by_class.get(cls, 0):,} polygones")

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
    ffco_gpkg_path = terrain_cfg.get("ffco_gpkg")
    ffco_layer = terrain_cfg.get("ffco_layer", "grimbosq_areas")
    hull = load_ffco_hull(ffco_gpkg_path, layer_name=ffco_layer) if ffco_gpkg_path else None

    report_hull_metrics(gdf, cfg, hull)

    if ffco_gpkg_path:
        report_recall_by_class(
            masked_gpkg=qa_gpkg,
            ffco_gpkg=ROOT / ffco_gpkg_path,
            ffco_layer=ffco_layer,
        )

    # P12 — contrôle structural de l'OMAP assemblé
    omap_path = OUTPUT / f"{terrain}.omap"
    if omap_path.exists():
        from tools.ctrl_omap import count_objects, load_code_to_id
        isom_tpl = ASSETS / "ISOM 2017-2_10000.omap"
        code_to_id = load_code_to_id(isom_tpl) if isom_tpl.exists() else None
        omap_counts = count_objects(omap_path, code_to_id=code_to_id)
        veg_counts = {cls: omap_counts.counts.get(str(cls), 0) for cls in [406, 408, 410]}
        log.info(
            "ctrl_omap %s : 406=%d  408=%d  410=%d  (total=%d objs)",
            omap_path.name,
            veg_counts[406], veg_counts[408], veg_counts[410],
            omap_counts.actual,
        )
        if not omap_counts.count_match:
            log.warning(
                "ctrl_omap : declared=%d != actual=%d dans %s",
                omap_counts.declared, omap_counts.actual, omap_path.name,
            )
    else:
        log.warning("QA ctrl_omap : %s absent — contrôle OMAP ignoré", omap_path.name)

    write_config_snapshot(cfg, OUTPUT, extra={"qa_vegetation_source": qa_source})


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

    print(f"Dalles LiDAR HD à télécharger ({len(tiles)}) :")
    for t in tiles:
        print(f"  {t}")
    print(f"\nFichiers attendus dans : LIDAR/{terrain}/")
    print("Format : .copc.laz")
    print("\nSource : consulter la documentation officielle IGN LiDAR HD")


# ── Sous-commande : check ─────────────────────────────────────────────────────

def _cmd_check() -> None:
    from src.check_terrain import cmd_check

    parser = argparse.ArgumentParser(
        prog="main.py check",
        description="Vérifie dalles, recouvrement, georef XML avant le pipeline.",
    )
    parser.add_argument("terrain", help="Nom du terrain")
    parser.add_argument(
        "--force-kp", action="store_true",
        help="Ignore la vérification de version KP (utiliser avec précaution)",
    )
    args = parser.parse_args()

    cfg = _load_config()
    from src.pipeline_mode import resolve_veg_source
    veg_mode = resolve_veg_source(args.terrain, cfg)
    ok = cmd_check(args.terrain, cfg, ROOT, force_kp_version=args.force_kp, veg_mode=veg_mode)
    if not ok:
        sys.exit(1)


# ── Sous-commande : setup ─────────────────────────────────────────────────────

def _cmd_setup() -> None:
    from src.setup_terrain import cmd_setup

    parser = argparse.ArgumentParser(
        prog="main.py setup",
        description="Configuration interactive : LiDAR, BD TOPO, KP.",
    )
    parser.add_argument("terrain", help="Nom du terrain")
    args = parser.parse_args()

    cfg = _load_config()
    ok = cmd_setup(args.terrain, cfg, ROOT)
    if not ok:
        sys.exit(1)


# ── Sous-commande : gui ───────────────────────────────────────────────────────

def _cmd_gui() -> None:
    from gui.app import main as gui_main
    gui_main()


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
    parser.add_argument(
        "--force-kp", action="store_true",
        help="Ignore la vérification de version KP (utiliser avec précaution)",
    )
    args = parser.parse_args()

    global OUTPUT

    cfg = _load_config()

    from src.pipeline_mode import resolve_veg_source
    veg_mode = resolve_veg_source(args.terrain, cfg)

    if not args.tiles_dir and not args.tiles:
        lidar_dir_cfg = (cfg.get("terrains") or {}).get(args.terrain, {}).get("lidar_dir")
        if lidar_dir_cfg:
            args.tiles_dir = lidar_dir_cfg

    if not args.skip_check:
        tiles_path = pathlib.Path(args.tiles_dir) if args.tiles_dir else None
        if not cmd_check(args.terrain, cfg, ROOT, lidar_dir=tiles_path, force_kp_version=args.force_kp, veg_mode=veg_mode):
            sys.exit(
                "\nProjet incomplet — corriger les points ci-dessus.\n"
                f"  python main.py setup {args.terrain}"
            )

    terrain_cfg = (cfg.get("terrains") or {}).get(args.terrain, {})
    output_dir = terrain_cfg.get("output_dir") or (
        f"output_{args.terrain}" if args.terrain != "grimbosq" else "output"
    )
    output_dir_root = (
        terrain_cfg.get("output_dir_root")
        or cfg.get("output_dir_root")
        or os.environ.get("LIDAR_OUTPUT_ROOT")
    )
    if output_dir_root:
        OUTPUT = pathlib.Path(output_dir_root) / output_dir
    else:
        OUTPUT = ROOT / output_dir

    start_idx = _STEP_IDX[args.from_step] if args.from_step else 0

    def should_run(step: str) -> bool:
        return _STEP_IDX[step] >= start_idx

    OUTPUT.mkdir(parents=True, exist_ok=True)
    _add_pipeline_log_handler(OUTPUT)

    step_check_config(cfg)

    if should_run("fetch"):
        step_fetch(args.terrain, cfg, args.force)

    if veg_mode == "kp":
        if args.skip_pdal:
            log.info("--skip-pdal ignoré : mode kp")
        if args.from_step in ("pdal", "process_hag", "vegetation", "mask"):
            sys.exit(
                f"ERREUR : --from-step {args.from_step!r} incompatible avec mode kp "
                f"(vegetation_source: kp ne planifie pas les étapes HAG)."
            )
    elif veg_mode == "supervised_e":
        log.info("SKIP pdal — mode supervised_e (lit les LAZ directement)")
        log.info("SKIP process_hag — mode supervised_e")
    elif args.skip_pdal:
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

    if veg_mode != "supervised_e" and should_run("vegetation_kp"):
        step_vegetation_kp(args.terrain, cfg, args.force)

    if veg_mode == "supervised_e":
        if should_run("supervised_e"):
            # Collecte des LAZ (mêmes sources que l'étape pdal)
            _se_tiles: list[str] = []
            if args.tiles_dir:
                td = pathlib.Path(args.tiles_dir)
                _se_tiles = [str(p) for p in sorted(td.glob("*.copc.laz"))]
                if not _se_tiles:
                    _se_tiles = [str(p) for p in sorted(td.glob("*.laz"))]
            elif getattr(args, "tiles", None):
                _se_tiles = args.tiles
            step_supervised_e(args.terrain, cfg, _se_tiles, args.force)
        else:
            # Reprise depuis une étape ultérieure — vérifier que les sorties existent
            from src.supervised_e import EXPORT_MODE_FAITHFUL
            _export_mode = cfg.get("vegetation_export_mode", EXPORT_MODE_FAITHFUL)
            _veg_gpkg = OUTPUT / f"vegetation_supervised_e_{_export_mode}.gpkg"
            if not _veg_gpkg.exists():
                sys.exit(
                    f"ERREUR : reprise depuis '{args.from_step}' avec moteur supervised_e, "
                    f"mais {_veg_gpkg.name!r} absent dans {OUTPUT}.\n"
                    f"Relancer depuis supervised_e (--from-step supervised_e) ou depuis le début."
                )

    if veg_mode not in ("kp", "supervised_e") and should_run("vegetation"):
        step_vegetation(args.terrain, cfg, args.force)

    if veg_mode not in ("kp", "supervised_e") and should_run("mask"):
        step_mask(args.terrain, cfg, args.force)

    omap_counts: dict = {}
    if should_run("assemble"):
        step_assemble(args.terrain, cfg, args.force, veg_mode=veg_mode)
        omap_counts = _count_omap_objects(OUTPUT / f"{args.terrain}.omap")
        log.info("Objets .omap : %s", omap_counts)

    if should_run("qa"):
        step_qa(args.terrain, cfg)

    # Persiste relief_status + comptes .omap dans run_metadata.json (écrit par step_qa)
    _meta_path = OUTPUT / "run_metadata.json"
    if _meta_path.exists():
        import json as _json
        _meta = _json.loads(_meta_path.read_text(encoding="utf-8"))
        _meta["relief_status"] = relief_status
        if omap_counts:
            _meta["omap_object_counts"] = omap_counts
        _meta_path.write_text(_json.dumps(_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("──────────────────────────────────────────")
    log.info("Pipeline terminé — terrain : %s", args.terrain)
    log.info("  relief  : %s", relief_status)
    out_omap = OUTPUT / f"{args.terrain}.omap"
    if out_omap.exists():
        log.info("  sortie  : %s", out_omap)


# ── CLI ───────────────────────────────────────────────────────────────────────

_SUBCOMMANDS = {"init", "tiles", "check", "run", "setup", "gui"}


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] in _SUBCOMMANDS:
        subcmd = sys.argv.pop(1)
        {
            "init": _cmd_init,
            "tiles": _cmd_tiles,
            "check": _cmd_check,
            "run": _cmd_run,
            "setup": _cmd_setup,
            "gui": _cmd_gui,
        }[subcmd]()
    else:
        _cmd_run()


if __name__ == "__main__":
    main()
