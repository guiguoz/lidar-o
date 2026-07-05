"""Phase 6 — CO Generalization Engine.

Architecture pipeline : chaque étape est une transformation indépendante
  (gdf, config) → (gdf, log_dict)
avec logging automatique avant/après (count, surface totale, delta).

Ordre verrouillé (cf. docs/iof_generalization_rules.md §8) :
  0. Polygonize
  1. Dissolve
  2. Remove holes        [TODO Sprint 2]
  3. Remove small        [TODO Sprint 2]
  4. Merge proximity     [TODO Sprint 3]
  5. Simplify (DP)       [TODO Sprint 4]
  6. Smooth (Chaikin ×1) [TODO Sprint 4]

Usage :
  from src.vegetation import run_pipeline
  import yaml, pathlib
  cfg = yaml.safe_load(open("config.yaml"))
  gdf, logs = run_pipeline("output/density_hag_classified.tif", cfg,
                            debug_dir=pathlib.Path("debug/"))
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
from osgeo import gdal, ogr, osr
from shapely.geometry import MultiPolygon, Polygon
from shapely.strtree import STRtree
from shapely.wkt import loads as _wkt_loads

gdal.UseExceptions()

log = logging.getLogger(__name__)

# Valeur DN raster → code ISOM
_HAG_CLASS_MAP: dict[int, int] = {85: 406, 170: 408, 255: 410}


# --------------------------------------------------------------------------- #
# Utilitaires internes                                                         #
# --------------------------------------------------------------------------- #

def _gen_cfg(config: dict) -> dict:
    """Extrait le profil de généralisation actif depuis la config globale."""
    active = config["generalization"]["active_profile"]
    return config["generalization"]["profiles"][active]


def _stage_stats(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Stats synthétiques d'un GeoDataFrame pour logging inter-étapes."""
    if gdf.empty:
        return {"count": 0, "total_area_m2": 0.0, "by_class": {}}
    by_class = {
        str(cls): int(n)
        for cls, n in gdf["class"].value_counts().sort_index().items()
    }
    return {
        "count": len(gdf),
        "total_area_m2": round(float(gdf.geometry.area.sum()), 1),
        "by_class": by_class,
    }


def _debug_export(gdf: gpd.GeoDataFrame, step: int, name: str, debug_dir: Path | None) -> None:
    """Exporte un GeoJSON numéroté si debug_dir est fourni."""
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{step:02d}_{name}.geojson"
    out = gdf.copy()
    out["class"] = out["class"].astype(str)
    out.to_file(path, driver="GeoJSON")
    log.debug("Debug → %s (%d features)", path.name, len(gdf))


# --------------------------------------------------------------------------- #
# Étapes du pipeline                                                           #
# --------------------------------------------------------------------------- #

def stage_polygonize(tif_path: str | Path, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 0 — GDAL Polygonize du raster classifié 8-bit → GeoDataFrame."""
    ds = gdal.Open(str(tif_path))
    if ds is None:
        raise FileNotFoundError(f"Raster introuvable : {tif_path}")

    band = ds.GetRasterBand(1)
    crs_wkt = ds.GetProjection()

    srs = osr.SpatialReference()
    if crs_wkt:
        srs.ImportFromWkt(crs_wkt)

    drv = ogr.GetDriverByName("MEM")
    mem_ds = drv.CreateDataSource("")
    lyr = mem_ds.CreateLayer("polys", srs=srs)
    lyr.CreateField(ogr.FieldDefn("DN", ogr.OFTInteger))
    gdal.Polygonize(band, None, lyr, 0, [], callback=None)
    n_raw = lyr.GetFeatureCount()

    rows = []
    for feat in lyr:
        dn = feat.GetField("DN")
        if dn == 0:
            continue
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        rows.append({
            "class": _HAG_CLASS_MAP.get(dn, dn),
            "geometry": _wkt_loads(geom_ref.ExportToWkt()),
        })

    mem_ds = None
    ds = None

    epsg = srs.GetAuthorityCode(None) if crs_wkt else None
    crs: str | None = f"EPSG:{epsg}" if epsg else (crs_wkt or None)

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    stats = _stage_stats(gdf)
    log.info("polygonize : %d brutes → %d non-nulles", n_raw, stats["count"])
    return gdf, {"stage": "polygonize", "output": stats}


def stage_dissolve(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 1 — Dissolve par classe : fusionne les polygones adjacents de même classe."""
    before = _stage_stats(gdf)

    dissolved = gdf.dissolve(by="class", as_index=False)
    dissolved = dissolved.explode(index_parts=False).reset_index(drop=True)

    after = _stage_stats(dissolved)
    log.info(
        "dissolve : %d → %d polygones (−%d)",
        before["count"], after["count"], before["count"] - after["count"],
    )
    return dissolved, {"stage": "dissolve", "before": before, "after": after}


def _drop_holes(geom: Polygon | MultiPolygon, min_area: float) -> Polygon | MultiPolygon:
    """Supprime les trous (anneaux intérieurs) dont l'aire < min_area."""
    if isinstance(geom, Polygon):
        kept = [h for h in geom.interiors if Polygon(h).area >= min_area]
        return Polygon(geom.exterior, kept)
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([_drop_holes(p, min_area) for p in geom.geoms])
    return geom


def stage_remove_holes(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 2 — Suppression des trous < min_hole_area_m2."""
    gen = _gen_cfg(config)
    min_area: float = float(gen["min_hole_area_m2"])
    before = _stage_stats(gdf)

    n_holes_before = sum(
        len(list(geom.interiors)) if isinstance(geom, Polygon)
        else sum(len(list(p.interiors)) for p in geom.geoms)
        for geom in gdf.geometry
    )

    result = gdf.copy()
    result["geometry"] = result["geometry"].apply(lambda g: _drop_holes(g, min_area))

    n_holes_after = sum(
        len(list(geom.interiors)) if isinstance(geom, Polygon)
        else sum(len(list(p.interiors)) for p in geom.geoms)
        for geom in result.geometry
    )

    after = _stage_stats(result)
    removed = n_holes_before - n_holes_after
    log.info("remove_holes : %d trous supprimés (seuil %.0f m²)", removed, min_area)
    return result, {
        "stage": "remove_holes",
        "holes_before": n_holes_before,
        "holes_after": n_holes_after,
        "holes_removed": removed,
        "before": before,
        "after": after,
    }


def stage_remove_small(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 3 — Suppression des polygones < min_area_m2 par classe."""
    gen = _gen_cfg(config)
    min_areas: dict = gen["min_area_m2"]
    before = _stage_stats(gdf)

    # Seuil vectorisé : évite apply() pixel par pixel
    threshold = gdf["class"].map(
        lambda c: float(min_areas.get(str(c), min_areas.get(c, 0)))
    )
    mask = gdf.geometry.area >= threshold
    result = gdf[mask].reset_index(drop=True)

    after = _stage_stats(result)
    log.info(
        "remove_small : %d → %d polygones (−%d)",
        before["count"], after["count"], before["count"] - after["count"],
    )
    return result, {"stage": "remove_small", "before": before, "after": after}


def _min_width(poly: Polygon) -> float:
    """Largeur minimale d'un Polygon via rectangle englobant minimal (MRR)."""
    mrr = poly.minimum_rotated_rectangle
    if not isinstance(mrr, Polygon) or mrr.is_empty:
        return 0.0
    coords = list(mrr.exterior.coords)
    d1 = ((coords[1][0] - coords[0][0]) ** 2 + (coords[1][1] - coords[0][1]) ** 2) ** 0.5
    d2 = ((coords[2][0] - coords[1][0]) ** 2 + (coords[2][1] - coords[1][1]) ** 2) ** 0.5
    return min(d1, d2)


def _geom_min_width(geom: Polygon | MultiPolygon) -> float:
    """Largeur minimale via MRR (mesure globale, pas les étranglements locaux)."""
    if isinstance(geom, Polygon):
        return _min_width(geom)
    if isinstance(geom, MultiPolygon):
        widths = [_min_width(p) for p in geom.geoms if not p.is_empty]
        return min(widths) if widths else 0.0
    return 0.0


def stage_close_corridors(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 4 — Suppression des polygones dont la largeur MRR < min_corridor_width_m."""
    gen = _gen_cfg(config)
    min_w = float(gen["min_corridor_width_m"])
    before = _stage_stats(gdf)

    widths = gdf.geometry.apply(_geom_min_width)
    narrow_mask = widths < min_w
    result = gdf[~narrow_mask].reset_index(drop=True)

    after = _stage_stats(result)
    n_narrow = int(narrow_mask.sum())
    log.info(
        "close_corridors widths MRR — p10=%.1fm  p50=%.1fm  p90=%.1fm  <%.0fm: %d/%d",
        float(widths.quantile(0.10)), float(widths.quantile(0.50)), float(widths.quantile(0.90)),
        min_w, n_narrow, len(widths),
    )
    log.info(
        "close_corridors (≥ %.1f m) : %d → %d polygones (−%d supprimés)",
        min_w, before["count"], after["count"], n_narrow,
    )
    return result, {
        "stage": "close_corridors",
        "before": before,
        "after": after,
        "narrow_removed": n_narrow,
        "width_p10": float(widths.quantile(0.10)),
        "width_p50": float(widths.quantile(0.50)),
        "width_p90": float(widths.quantile(0.90)),
    }


def stage_merge_proximity(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 5 — Fusion îlots proches < fusion_distance_m (buffer+dissolve+débuffer par classe)."""
    gen = _gen_cfg(config)
    fusion_dists: dict = gen["fusion_distance_m"]
    before = _stage_stats(gdf)

    rows: list[dict] = []
    for cls in sorted(gdf["class"].unique()):
        sub = gdf[gdf["class"] == cls]
        d = float(fusion_dists.get(str(cls), fusion_dists.get(cls, 0.0)))

        if d <= 0.0 or sub.empty:
            for geom in sub.geometry:
                rows.append({"class": cls, "geometry": geom})
            continue

        half = d / 2.0
        unioned = sub.geometry.buffer(half).unary_union
        debuffered = unioned.buffer(-half)

        if debuffered.is_empty:
            continue

        polys = (
            list(debuffered.geoms)
            if isinstance(debuffered, MultiPolygon)
            else [debuffered]
        )
        for p in polys:
            if not p.is_empty and p.area > 0.1:
                rows.append({"class": cls, "geometry": p})

    result = gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf.crs)
    after = _stage_stats(result)
    log.info(
        "merge_proximity : %d → %d polygones (−%d)",
        before["count"], after["count"], before["count"] - after["count"],
    )
    return result, {"stage": "merge_proximity", "before": before, "after": after}


def _count_vertices(gdf: gpd.GeoDataFrame) -> int:
    total = 0
    for geom in gdf.geometry:
        if isinstance(geom, Polygon):
            total += len(geom.exterior.coords) - 1
        elif isinstance(geom, MultiPolygon):
            for p in geom.geoms:
                total += len(p.exterior.coords) - 1
    return total


def stage_remove_isolated(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 5 — Suppression des petits polygones isolés.

    Règle : aire < max_area_m2[classe] ET aucun voisin de même classe à < search_distance_m.
    Les grands polygones isolés sont conservés (condition d'aire protège les îlots réels).
    """
    gen = _gen_cfg(config)
    ri_cfg = gen.get("remove_isolated", {})
    if not ri_cfg.get("enabled", True):
        stats = _stage_stats(gdf)
        return gdf, {"stage": "remove_isolated", "before": stats, "after": stats, "isolated_removed": 0}

    max_areas: dict = ri_cfg.get("max_area_m2", {})
    search_dists: dict = ri_cfg.get("search_distance_m", {})
    before = _stage_stats(gdf)
    to_remove: list[int] = []

    for cls in sorted(gdf["class"].unique()):
        max_a = float(max_areas.get(str(cls), max_areas.get(cls, 0.0)))
        d = float(search_dists.get(str(cls), search_dists.get(cls, 0.0)))
        if max_a <= 0.0 or d <= 0.0:
            continue

        sub = gdf[gdf["class"] == cls]
        small = sub[sub.geometry.area < max_a]
        if small.empty:
            continue

        # STRtree sur tous les polygones de la classe pour accélération spatiale
        sub_geoms = list(sub.geometry)
        sub_positions = list(sub.index)
        tree = STRtree(sub_geoms)

        for local_i, (pos, geom) in enumerate(zip(sub_positions, sub_geoms)):
            if geom.area >= max_a:
                continue
            buffered = geom.buffer(d)
            candidates = tree.query(buffered)
            has_neighbor = any(
                int(j) != local_i and buffered.intersects(sub_geoms[int(j)])
                for j in candidates
            )
            if not has_neighbor:
                to_remove.append(pos)

    result = gdf.drop(index=to_remove).reset_index(drop=True)
    after = _stage_stats(result)
    n_removed = before["count"] - after["count"]
    log.info(
        "remove_isolated : %d → %d polygones (−%d supprimés)",
        before["count"], after["count"], n_removed,
    )
    return result, {
        "stage": "remove_isolated",
        "before": before,
        "after": after,
        "isolated_removed": n_removed,
    }


def stage_simplify(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 5 — Douglas-Peucker avec tolérance douglas_peucker_tolerance_m."""
    gen = _gen_cfg(config)
    tol = float(gen["douglas_peucker_tolerance_m"])
    before = _stage_stats(gdf)
    v_before = _count_vertices(gdf)

    result = gdf.copy()
    result["geometry"] = result["geometry"].simplify(tol, preserve_topology=True)
    result = result[~result.geometry.is_empty & result.geometry.is_valid].reset_index(drop=True)

    after = _stage_stats(result)
    v_after = _count_vertices(result)
    log.info(
        "simplify (DP %.1f m) : %d polygones, sommets %d → %d (−%d%%)",
        tol, after["count"], v_before, v_after,
        round(100 * (v_before - v_after) / max(v_before, 1)),
    )
    return result, {
        "stage": "simplify",
        "before": before,
        "after": after,
        "vertices_before": v_before,
        "vertices_after": v_after,
    }


def _chaikin_ring(coords: list, passes: int) -> list[tuple[float, float]]:
    pts = [c[:2] for c in coords[:-1]]  # retire le doublon de fermeture
    for _ in range(passes):
        n = len(pts)
        new_pts: list[tuple[float, float]] = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            new_pts.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            new_pts.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = new_pts
    return pts + [pts[0]]


def _chaikin_geom(geom: Polygon | MultiPolygon, passes: int) -> Polygon | MultiPolygon:
    if isinstance(geom, Polygon):
        if len(geom.exterior.coords) < 4:
            return geom
        ext = _chaikin_ring(list(geom.exterior.coords), passes)
        holes = [_chaikin_ring(list(h.coords), passes) for h in geom.interiors]
        smoothed = Polygon(ext, holes)
        return smoothed if smoothed.is_valid else geom
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([_chaikin_geom(p, passes) for p in geom.geoms])
    return geom


def stage_smooth(gdf: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    """Étape 6 — Lissage Chaikin (chaikin_passes passes)."""
    gen = _gen_cfg(config)
    passes = int(gen["chaikin_passes"])
    before = _stage_stats(gdf)
    v_before = _count_vertices(gdf)

    result = gdf.copy()
    result["geometry"] = result["geometry"].apply(lambda g: _chaikin_geom(g, passes))
    result = result[~result.geometry.is_empty].reset_index(drop=True)

    after = _stage_stats(result)
    v_after = _count_vertices(result)
    log.info(
        "smooth (Chaikin ×%d) : sommets %d → %d (+%d%%)",
        passes, v_before, v_after,
        round(100 * (v_after - v_before) / max(v_before, 1)),
    )
    return result, {
        "stage": "smooth",
        "before": before,
        "after": after,
        "vertices_before": v_before,
        "vertices_after": v_after,
    }


# --------------------------------------------------------------------------- #
# Orchestrateur                                                                #
# --------------------------------------------------------------------------- #

_STAGES = [
    (1, "dissolved",         stage_dissolve),
    (2, "holes_removed",     stage_remove_holes),
    (3, "small_removed",     stage_remove_small),
    (4, "merged",            stage_merge_proximity),
    # close_corridors : 2/496 candidats sur Grimbosq → inactif (optionnel sur terrain bruité)
    # (x, "corridors_closed",  stage_close_corridors),
    (5, "isolated_removed",  stage_remove_isolated),
    (6, "simplified",        stage_simplify),
    (7, "smoothed",          stage_smooth),
]


def run_pipeline(
    tif_path: str | Path,
    config: dict,
    debug_dir: Path | None = None,
) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """Pipeline CO Generalization Engine complet.

    Args:
        tif_path:   Raster classifié 8-bit (valeurs 85/170/255).
        config:     Config globale chargée depuis config.yaml.
        debug_dir:  Si fourni, exporte un GeoJSON par étape pour diagnostic.

    Returns:
        (gdf_final, logs) — logs = liste de dict par étape avec stats avant/après.
    """
    logs: list[dict] = []

    gdf, log0 = stage_polygonize(tif_path, config)
    logs.append(log0)
    _debug_export(gdf, 0, "polygonized", debug_dir)

    for step_num, name, stage_fn in _STAGES:
        gdf, stage_log = stage_fn(gdf, config)
        logs.append(stage_log)
        _debug_export(gdf, step_num, name, debug_dir)

    return gdf, logs
