"""QA légère — rapport métriques de production.

Fonction principale : report_hull_metrics(gdf, cfg, hull)
  Calcule le quadruplet (cov%, n, med mm2, %<1mm2, max%406) par classe,
  le compare aux cibles FFCO si le profil actif en contient, et affiche
  un rapport texte lisible d'un coup d'œil.

Si le profil n'a pas de qa_targets (nouveau terrain sans référence),
le rapport affiche les métriques seules — pas d'erreur.

Usage :
    from src.qa import report_hull_metrics, load_ffco_hull
    hull = load_ffco_hull("grimbosq.gpkg")
    report_hull_metrics(gdf, cfg, hull)
"""
from __future__ import annotations

import json
import logging
import pathlib
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import shapely.geometry as sg
from shapely.ops import unary_union

if TYPE_CHECKING:
    import geopandas as gpd

log = logging.getLogger(__name__)

SCALE = 10_000
MM2 = 1e6 / SCALE**2
_VEG_CLASSES = [406, 408, 410]


# ── Chargement du hull FFCO ───────────────────────────────────────────────────

def _load_hull_from_sqlite(
    path: pathlib.Path,
    veg_keywords: tuple[str, ...],
    exclude_keywords: tuple[str, ...],
) -> sg.Polygon | None:
    """Lit le hull FFCO depuis un GPKG latin-1 via les bindings OGR Python.

    ogr2ogr CLI échoue car la couche est spécifiée en UTF-8 mais stockée en
    latin-1. OGR Python accède aux couches par index et passe les noms au
    C sqlite3 comme bytes bruts — contournement transparent.
    """
    try:
        from osgeo import ogr as _ogr
        _ogr.UseExceptions()
    except ImportError:
        log.warning("hull FFCO (ogr) : osgeo.ogr non disponible")
        return None

    try:
        ds = _ogr.Open(str(path))
        if ds is None:
            log.warning("hull FFCO (ogr) : OGR ne peut pas ouvrir %s", path.name)
            return None

        areas_layer = None
        for i in range(ds.GetLayerCount()):
            lyr = ds.GetLayerByIndex(i)
            try:
                name_low = lyr.GetName().lower()
            except Exception:
                name_low = ""
            if "areas" in name_low:
                areas_layer = lyr
                log.info("hull FFCO (ogr) : couche [%d] '%s', %d features",
                         i, lyr.GetName(), lyr.GetFeatureCount())
                break

        if areas_layer is None:
            log.warning("hull FFCO (ogr) : aucune couche '*areas' dans %s", path.name)
            return None

        from shapely import wkb as shapely_wkb

        geoms: list[sg.base.BaseGeometry] = []
        areas_layer.ResetReading()
        feat = areas_layer.GetNextFeature()
        while feat is not None:
            raw_name = feat.GetField("Name") or ""
            name_low = raw_name.lower() if isinstance(raw_name, str) else str(raw_name).lower()
            if (any(kw in name_low for kw in veg_keywords)
                    and not any(ex in name_low for ex in exclude_keywords)):
                geom_ref = feat.GetGeometryRef()
                if geom_ref is not None:
                    try:
                        wkb = bytes(geom_ref.ExportToWkb())
                        g = shapely_wkb.loads(wkb)
                        geoms.append(g.buffer(0) if not g.is_valid else g)
                    except Exception as exc:
                        log.debug("hull FFCO (ogr) : géom ignorée — %s", exc)
            feat = areas_layer.GetNextFeature()

        if not geoms:
            log.warning("hull FFCO (ogr) : aucune géométrie végétation trouvée")
            return None
        return unary_union(geoms).convex_hull

    except Exception as exc:
        log.warning("hull FFCO (ogr) : échec — %s", exc)
        return None


def load_ffco_hull(
    ffco_gpkg: str | pathlib.Path,
    layer_name: str = "grimbosq_areas",
    veg_keywords: tuple[str, ...] = ("course lente", "marche", "progression",
                                     "slow running", "walk", "fight"),
    exclude_keywords: tuple[str, ...] = ("bonne", "good visibility"),
) -> sg.Polygon | None:
    """Charge le hull convexe depuis une carte de référence GPKG via ogr2ogr.

    layer_name    : nom exact de la couche dans le GPKG (configurable par terrain).
    veg_keywords  : sous-chaînes qui identifient une classe végétation (FR + EN).
    exclude_keywords : variantes à exclure (ex. "bonne visibilité").

    Retourne None si le fichier est absent, inaccessible ou sans géométrie extraite.
    Émet un log.error explicite si l'encodage est latin-1 (UnicodeDecodeError).
    """
    path = pathlib.Path(ffco_gpkg)
    if not path.exists():
        # Fallback glob : résout les noms de fichiers non-ASCII sur Windows
        # (path.exists() peut échouer même si le fichier existe — encodage NTFS)
        matches = sorted(path.parent.glob(f"{path.stem[:5]}*.gpkg"))
        if len(matches) == 1:
            path = matches[0]
            log.info("hull FFCO : résolution alternative → %s", path.name)
        else:
            log.warning("hull FFCO : %s absent — métriques sur emprise totale", path)
            return None
    try:
        r = subprocess.run(
            ["ogr2ogr", "-f", "GeoJSON", "/vsistdout/", str(path), layer_name],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace").strip()
            if "fetch requested layer" in stderr.lower() or "no such table" in stderr.lower():
                log.warning(
                    "hull FFCO : couche '%s' introuvable via GDAL (encodage latin-1 probable) "
                    "— tentative via sqlite3 direct",
                    layer_name,
                )
                return _load_hull_from_sqlite(path, veg_keywords, exclude_keywords)
            log.warning("hull FFCO : ogr2ogr échoué (%s)", stderr[:100])
            return None
        stdout = r.stdout.decode("utf-8", errors="replace")
        fc = json.loads(stdout)
    except UnicodeDecodeError:
        log.warning(
            "hull FFCO : '%s' contient des noms de couches non-UTF-8 — tentative via OGR Python",
            path.name,
        )
        return _load_hull_from_sqlite(path, veg_keywords, exclude_keywords)
    except FileNotFoundError:
        log.warning("hull FFCO : ogr2ogr introuvable — tentative via OGR Python")
        return _load_hull_from_sqlite(path, veg_keywords, exclude_keywords)
    except Exception as exc:
        log.warning("hull FFCO : échec — %s", exc)
        return None

    geoms: list[sg.base.BaseGeometry] = []
    for feat in fc["features"]:
        name = feat["properties"].get("Name", "").lower()
        if (any(kw in name for kw in veg_keywords)
                and not any(ex in name for ex in exclude_keywords)):
            try:
                g = sg.shape(feat["geometry"])
                geoms.append(g.buffer(0) if not g.is_valid else g)
            except Exception:
                pass
    if not geoms:
        log.warning("hull FFCO : aucune géométrie extraite (couche=%s, %d features)",
                    layer_name, len(fc.get("features", [])))
        return None
    return unary_union(geoms).convex_hull


# ── Calcul du quadruplet ──────────────────────────────────────────────────────

def _quadruplet(gdf: gpd.GeoDataFrame, hull: sg.base.BaseGeometry | None, cls: int) -> dict:
    import geopandas as gpd_mod
    sub = gdf[gdf["class"] == cls].copy()
    if hull is not None:
        sub = sub.clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return {"cov_pct": 0.0, "n": 0, "med_mm2": 0.0, "pct_small": 0.0, "max_pct": 0.0}
    areas = sub.geometry.area
    mm2 = areas * MM2
    cov_pct: float | None = (
        float(areas.sum() / hull.area * 100) if hull is not None else None
    )
    return {
        "cov_pct": cov_pct,
        "n": len(sub),
        "med_mm2": float(np.median(mm2)),
        "pct_small": float((mm2 < 1.0).mean() * 100),
        "max_pct": float(areas.max() / areas.sum() * 100),
    }


# ── Rapport ───────────────────────────────────────────────────────────────────

def report_hull_metrics(
    gdf: gpd.GeoDataFrame,
    cfg: dict,
    hull: sg.base.BaseGeometry | None,
) -> dict[int, dict]:
    """Affiche le rapport QA végétation et retourne les métriques calculées.

    Le rapport compare aux cibles FFCO si le profil actif contient qa_targets.
    Si hull est None, les métriques sont calculées sur l'emprise totale sans clip.
    Aucune exception levée : le rapport se dégrade si des données manquent.
    """
    gen = cfg.get("generalization", {})
    profile_name = gen.get("active_profile", "")
    profile = gen.get("profiles", {}).get(profile_name, {})
    targets: dict = profile.get("qa_targets", {})
    hull_ha = hull.area / 1e4 if hull is not None else None

    print()
    print(f"=== QA végétation — profil '{profile_name}' ===")
    if hull_ha:
        ref_desc = f"hull FFCO {hull_ha:.1f} ha"
        if "hull_ha" in targets:
            ref_desc += f" (attendu {targets['hull_ha']:.1f} ha)"
    else:
        ref_desc = "emprise totale (hull absent)"
    print(f"    Référence : {ref_desc}")
    print()

    has_targets = bool(targets and any(str(c) in targets or c in targets for c in _VEG_CLASSES))
    has_hull = hull is not None

    # En-tête selon disponibilité hull + cibles
    # Sans hull : cov% et dcov exclus (tautologie ou non mesurable)
    # dmed et d%<1 valides même sans hull (comparaison de tailles absolues)
    if has_hull and has_targets:
        hdr = f"  {'cls':>3}  {'cov%':>6}  {'dcov':>6}  {'n':>5}  {'med mm2':>8}  {'dmed':>6}  {'%<1mm2':>7}  {'d%<1':>6}  {'max%':>5}"
    elif has_hull:
        hdr = f"  {'cls':>3}  {'cov%':>6}  {'n':>5}  {'med mm2':>8}  {'%<1mm2':>7}  {'max%':>5}"
    elif has_targets:
        hdr = f"  {'cls':>3}  {'n':>5}  {'med mm2':>8}  {'dmed':>6}  {'%<1mm2':>7}  {'d%<1':>6}  {'max%':>5}"
    else:
        hdr = f"  {'cls':>3}  {'n':>5}  {'med mm2':>8}  {'%<1mm2':>7}  {'max%':>5}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    results: dict[int, dict] = {}
    for cls in _VEG_CLASSES:
        m = _quadruplet(gdf, hull, cls)
        results[cls] = m
        t = targets.get(cls) or targets.get(str(cls))

        if has_hull and has_targets and t:
            dcov = m["cov_pct"] - t["cov_pct"]
            dmed = m["med_mm2"] - t["med_mm2"]
            dpct = m["pct_small"] - t["pct_small"]
            print(
                f"  {cls:>3}  {m['cov_pct']:>6.1f}  {dcov:>+6.1f}  {m['n']:>5}  "
                f"{m['med_mm2']:>8.2f}  {dmed:>+6.2f}  {m['pct_small']:>7.1f}  {dpct:>+6.1f}  {m['max_pct']:>5.1f}"
            )
        elif has_hull:
            print(
                f"  {cls:>3}  {m['cov_pct']:>6.1f}  {m['n']:>5}  "
                f"{m['med_mm2']:>8.2f}  {m['pct_small']:>7.1f}  {m['max_pct']:>5.1f}"
            )
        elif has_targets and t:
            dmed = m["med_mm2"] - t["med_mm2"]
            dpct = m["pct_small"] - t["pct_small"]
            print(
                f"  {cls:>3}  {m['n']:>5}  "
                f"{m['med_mm2']:>8.2f}  {dmed:>+6.2f}  {m['pct_small']:>7.1f}  {dpct:>+6.1f}  {m['max_pct']:>5.1f}"
            )
        else:
            print(
                f"  {cls:>3}  {m['n']:>5}  "
                f"{m['med_mm2']:>8.2f}  {m['pct_small']:>7.1f}  {m['max_pct']:>5.1f}"
            )

    if has_targets:
        print()
        print("  Cibles FFCO :")
        for cls in _VEG_CLASSES:
            t = targets.get(cls) or targets.get(str(cls))
            if t:
                cov_s = f"cov={t['cov_pct']}%  " if has_hull else ""
                print(f"    {cls} : {cov_s}n={t['n']}  med={t['med_mm2']}mm2  %<1mm2={t['pct_small']}%")

    max406 = results[406]["max_pct"]
    plancher, seuil = 7.4, 15.0
    statut = "OK" if max406 < seuil else "ATTENTION percolation"
    print()
    print(f"  Garde-fou max%406 : {max406:.1f}%  (plancher {plancher}%, alerte >{seuil}%)  => {statut}")
    print()

    report_shape_metrics(gdf, cfg, hull)

    return results


# ── Métriques de forme ────────────────────────────────────────────────────────

def _iter_polygons(geom: sg.base.BaseGeometry) -> list[sg.Polygon]:
    """Aplatit une géométrie en liste de Polygons non vides."""
    if isinstance(geom, sg.Polygon):
        return [geom] if not geom.is_empty else []
    if hasattr(geom, "geoms"):
        result: list[sg.Polygon] = []
        for g in geom.geoms:
            result.extend(_iter_polygons(g))
        return result
    return []


def _shape_metrics(
    gdf: "gpd.GeoDataFrame",
    hull: sg.base.BaseGeometry | None,
    cls: int,
) -> dict:
    """Métriques de forme par classe : compacité, trous, périmètre/√aire."""
    import math
    sub = gdf[gdf["class"] == cls].copy()
    if hull is not None:
        sub = sub.clip(hull)
    sub = sub[~sub.geometry.is_empty]
    if sub.empty:
        return {
            "compacity_med": 0.0, "pct_holed": 0.0,
            "n_holes": 0, "hole_area_med_mm2": 0.0,
            "peri_over_sqrtarea_med": 0.0,
        }

    compacities: list[float] = []
    peri_sqrts: list[float] = []
    holed_features = 0
    hole_areas_mm2: list[float] = []

    for geom in sub.geometry:
        polys = _iter_polygons(geom)
        feature_has_holes = False
        for poly in polys:
            if poly.area <= 0 or poly.length <= 0:
                continue
            compacities.append(4 * math.pi * poly.area / poly.length ** 2)
            peri_sqrts.append(poly.length / math.sqrt(poly.area))
            for interior in poly.interiors:
                hole = sg.Polygon(interior)
                hole_areas_mm2.append(hole.area * MM2)
                feature_has_holes = True
        if feature_has_holes:
            holed_features += 1

    return {
        "compacity_med": float(np.median(compacities)) if compacities else 0.0,
        "pct_holed": float(holed_features / max(len(sub), 1) * 100),
        "n_holes": len(hole_areas_mm2),
        "hole_area_med_mm2": float(np.median(hole_areas_mm2)) if hole_areas_mm2 else 0.0,
        "peri_over_sqrtarea_med": float(np.median(peri_sqrts)) if peri_sqrts else 0.0,
    }


def report_shape_metrics(
    gdf: "gpd.GeoDataFrame",
    cfg: dict,
    hull: sg.base.BaseGeometry | None,
) -> dict[int, dict]:
    """Affiche les métriques de forme (compacité, trous, périmètre/√aire) par classe.

    Cibles FFCO attendues dans qa_targets[cls]['shape'] :
      compacity_med, pct_holed, peri_over_sqrtarea_med
    """
    gen = cfg.get("generalization", {})
    profile_name = gen.get("active_profile", "")
    profile = gen.get("profiles", {}).get(profile_name, {})
    targets: dict = profile.get("qa_targets", {})

    print("=== Forme des contours ===")
    hdr = (f"  {'cls':>3}  {'compact':>8}  {'%troues':>8}  "
           f"{'n_trous':>8}  {'trou_mm2':>9}  {'P/sqrtA':>8}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    results: dict[int, dict] = {}
    for cls in _VEG_CLASSES:
        m = _shape_metrics(gdf, hull, cls)
        results[cls] = m
        t = (targets.get(cls) or targets.get(str(cls))) or {}
        st: dict = t.get("shape", {})

        compact_tgt = f" ({st['compacity_med']:.3f})" if "compacity_med" in st else ""
        psa_tgt = f" ({st['peri_over_sqrtarea_med']:.2f})" if "peri_over_sqrtarea_med" in st else ""
        hole_mm2 = f"{m['hole_area_med_mm2']:.2f}" if m["n_holes"] > 0 else "   -"

        print(
            f"  {cls:>3}  {m['compacity_med']:.3f}{compact_tgt:<10}  "
            f"{m['pct_holed']:>6.1f}%  "
            f"{m['n_holes']:>8d}  {hole_mm2:>9}  "
            f"{m['peri_over_sqrtarea_med']:.2f}{psa_tgt}"
        )

    has_shape_targets = any(
        (targets.get(cls) or targets.get(str(cls)) or {}).get("shape")
        for cls in _VEG_CLASSES
    )
    if has_shape_targets:
        print()
        print("  Cibles FFCO forme :")
        for cls in _VEG_CLASSES:
            t = (targets.get(cls) or targets.get(str(cls))) or {}
            st = t.get("shape", {})
            if st:
                parts = []
                if "compacity_med" in st:
                    parts.append(f"compact={st['compacity_med']:.3f}")
                if "pct_holed" in st:
                    parts.append(f"%troues={st['pct_holed']:.1f}%")
                if "peri_over_sqrtarea_med" in st:
                    parts.append(f"P/sqrtA={st['peri_over_sqrtarea_med']:.2f}")
                print(f"    {cls} : " + "  ".join(parts))
    print()

    return results


# ── Recall par classe (optionnel — nécessite carte de référence) ─────────────

_FFCO_KEYWORDS_FR: dict[int, str] = {
    406: "course lente",
    408: "marche",
    410: "progression",
}


def _load_ffco_polygons_by_class(
    ffco_gpkg: pathlib.Path,
    layer_name: str = "grimbosq_areas",
    keywords: dict[int, str] | None = None,
) -> dict[int, list] | None:
    """Charge les polygones FFCO par classe via OGR (évite les problèmes d'encodage).

    Retourne None si le fichier est absent ou illisible.
    """
    kw = keywords if keywords is not None else _FFCO_KEYWORDS_FR
    try:
        from osgeo import ogr as _ogr
        import json as _json
    except ImportError:
        log.warning("recall FFCO : osgeo.ogr non disponible")
        return None

    if not ffco_gpkg.exists():
        log.warning("recall FFCO : %s absent", ffco_gpkg)
        return None

    try:
        ds = _ogr.Open(str(ffco_gpkg))
        if ds is None:
            return None
        lyr = None
        for i in range(ds.GetLayerCount()):
            candidate = ds.GetLayerByIndex(i)
            try:
                if "areas" in candidate.GetName().lower():
                    lyr = candidate
                    break
            except Exception:
                pass
        if lyr is None:
            return None

        by_class: dict[int, list] = {c: [] for c in kw}
        lyr.ResetReading()
        for feat in lyr:
            raw = feat.GetField("Name") or ""
            low = raw.lower() if isinstance(raw, str) else str(raw).lower()
            cls = next((c for c, kword in kw.items() if kword in low), None)
            if cls is None:
                continue
            geom_ref = feat.GetGeometryRef()
            if geom_ref is None:
                continue
            try:
                shp = sg.shape(_json.loads(geom_ref.ExportToJson()))
                if shp.is_valid and not shp.is_empty:
                    by_class[cls].append(shp)
            except Exception:
                pass
        return by_class
    except Exception as exc:
        log.warning("recall FFCO : echec chargement — %s", exc)
        return None


def report_recall_by_class(
    masked_gpkg: pathlib.Path,
    ffco_gpkg: pathlib.Path,
    ffco_layer: str = "grimbosq_areas",
) -> dict[int, float] | None:
    """Calcule et affiche le recall par classe pipeline vs reference FFCO.

    Recall cls = area(FFCO_cls inter pipeline_cls) / area(FFCO_cls).
    Retourne None si la reference est absente ou illisible.
    """
    try:
        import geopandas as gpd
    except ImportError:
        return None

    ffco_by_cls = _load_ffco_polygons_by_class(ffco_gpkg, ffco_layer)
    if ffco_by_cls is None:
        return None

    pipe_by_cls: dict[int, sg.base.BaseGeometry] = {}
    for cls, layer in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        try:
            gdf = gpd.read_file(str(masked_gpkg), layer=layer)
            pipe_by_cls[cls] = unary_union(list(gdf.geometry))
        except Exception:
            pipe_by_cls[cls] = sg.Point(0, 0)

    pipe_all = unary_union(list(pipe_by_cls.values()))

    print("  Recall par classe (reference FFCO) :")
    print(f"    {'cls':>3}  {'recall':>7}  {'recall_cls':>10}  {'FFCO ha':>7}  {'TP ha':>6}  {'TP_cls ha':>9}")
    recalls: dict[int, float] = {}
    for cls in _VEG_CLASSES:
        ffco_geoms = ffco_by_cls.get(cls, [])
        if not ffco_geoms:
            print(f"    {cls} : reference absente")
            continue
        ffco_u = unary_union(ffco_geoms)
        ffco_area = ffco_u.area
        if ffco_area <= 0:
            continue
        # any-class recall : fraction de FFCO_cls couverte par n'importe quelle classe pipeline
        tp_any  = pipe_all.intersection(ffco_u).area
        # class-specific recall : fraction couverte par la bonne classe
        tp_cls  = pipe_by_cls.get(cls, sg.Point(0, 0)).intersection(ffco_u).area
        recall_any = tp_any / ffco_area
        recall_cls = tp_cls / ffco_area
        recalls[cls] = recall_any
        print(f"    {cls:>3}  {recall_any:>7.0%}  {recall_cls:>10.0%}  {ffco_area/10000:>7.1f}  {tp_any/10000:>6.1f}  {tp_cls/10000:>9.1f}")
    print(f"    (recall=detection toutes classes ; recall_cls=bonne classe uniquement)")
    print()
    return recalls if recalls else None


# ── Snapshot config dans run_metadata ────────────────────────────────────────

def write_config_snapshot(cfg: dict, output_dir: str | pathlib.Path) -> None:
    """Ajoute un snapshot de la config de généralisation dans run_metadata.json.

    Complète (sans écraser) les métadonnées existantes avec les paramètres
    nécessaires pour reconstituer la config qui a produit le run courant.
    """
    meta_path = pathlib.Path(output_dir) / "run_metadata.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    gen = cfg.get("generalization", {})
    profile_name = gen.get("active_profile", "")
    profile = gen.get("profiles", {}).get(profile_name, {})
    veg = cfg.get("vegetation", {})
    preset_name = veg.get("active_preset", "")
    preset = veg.get("presets", {}).get(preset_name, {})

    dm = veg.get("density_metric", {})
    meta["config_snapshot"] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "generalization_profile": profile_name,
        "min_area_m2": profile.get("min_area_m2", {}),
        "fusion_distance_m": profile.get("fusion_distance_m", {}),
        "vegetation_preset": preset_name,
        "thresholds": preset.get("thresholds"),
        "gaussian_sigma": veg.get("process_hag", {}).get("gaussian_sigma"),
        "density_mode": dm.get("mode"),
        "grid_resolution_m": veg.get("grid_resolution_m"),
        "normalization_mode": veg.get("normalization", {}).get("mode"),
    }

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Snapshot config écrit dans %s", meta_path)
