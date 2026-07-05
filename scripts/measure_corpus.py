"""Phase 5.5 — Mesure statistiques corpus pour calibration CO Generalization Engine.

Compare une carte FFCO réelle (vecteur) et/ou la sortie HAG raster classifiée.
Les valeurs de config.yaml (seuils IOF) doivent émerger de ces mesures, pas être supposées.

Modes :
  ffco     Analyse une carte FFCO vectorielle (GeoJSON/Shapefile/GPKG)
  hag      Analyse un raster HAG classifié (GeoTIFF 8-bit, valeurs 85/170/255)
  compare  Compare les deux côte-à-côte

Usage :
  python scripts/measure_corpus.py ffco carte.geojson [--class-col symbol] [--out-dir rapports/]
  python scripts/measure_corpus.py hag output/density_hag_classified.tif [--out-dir rapports/]
  python scripts/measure_corpus.py compare carte.geojson density_hag_classified.tif [--out-dir rapports/]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

import yaml

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.wkt import loads as _wkt_loads

try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    _MATPLOTLIB = True
except ImportError:
    _MATPLOTLIB = False

from osgeo import gdal, ogr, osr

gdal.UseExceptions()

# --------------------------------------------------------------------------- #
# Constantes                                                                   #
# --------------------------------------------------------------------------- #

# Raster DN → code ISOM végétation
_HAG_CLASS_MAP: dict[int, int] = {85: 406, 170: 408, 255: 410}

# Noms OOM/OCAD (FR + EN) → code ISOM — couvre les exports courants
# Clés : texte exact après _decode_surrogate() + strip()
_OOM_VEGE_NAMES: dict[str, str] = {
    # 406
    "Végétation : course lente": "406",
    "Terrain boisé,course ralentie": "406",   # pas d'espace après virgule (OCAD export)
    "Terrain boisé, course ralentie": "406",
    "Végétation - course ralentie": "406",
    "Vegetation: slow running": "406",
    # 408
    "Végétation : marche": "408",
    "Forêt - course difficile": "408",
    "Végétation - course difficile": "408",
    "Vegetation: walk": "408",
    # 410
    "Végétation : combat": "410",
    "Végétation impénétrable": "410",
    "Vegetation: fight": "410",
}


def _decode_surrogate(s: str) -> str:
    """Convertit les surrogates GDAL U+DC80-DCFF en caractères latin-1 correspondants.
    GDAL encode les bytes 0x80-0xFF comme surrogates U+DC80-DCFF dans les chaînes Python."""
    result = []
    for ch in s:
        code = ord(ch)
        if 0xDC80 <= code <= 0xDCFF:
            result.append(chr(code - 0xDC00))
        else:
            result.append(ch)
    return "".join(result)


def _load_name_map(mapping_file: str | None) -> dict[str, str]:
    """Charge le mapping nom→classe depuis un fichier YAML ou retourne le dict intégré."""
    if mapping_file is None:
        return _OOM_VEGE_NAMES
    with open(mapping_file, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {str(k): str(v) for k, v in raw.items()}

# Seuils candidats pour l'élimination de polygones (m²)
_AREA_THRESHOLDS = [5, 10, 20, 30, 50, 75, 100, 150, 200, 500]

# Seuils candidats pour la largeur minimale (m)
_WIDTH_THRESHOLDS = [1, 2, 3, 5, 7, 10, 15]

# Seuils candidats pour la distance de fusion (m)
_FUSION_THRESHOLDS = [2, 3, 5, 8, 10, 15, 20]


# --------------------------------------------------------------------------- #
# Métriques géométriques                                                       #
# --------------------------------------------------------------------------- #

def _flat_polygons(geom: Any) -> list[Polygon]:
    """Retourne la liste des Polygon non-vides d'une géométrie quelconque."""
    if isinstance(geom, Polygon) and not geom.is_empty and geom.area > 1e-9:
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty and g.area > 1e-9]
    return []


def _min_width(poly: Polygon) -> float:
    """Largeur minimale via rectangle englobant minimal (MRR)."""
    mrr = poly.minimum_rotated_rectangle
    if not isinstance(mrr, Polygon) or mrr.is_empty:
        return 0.0
    coords = list(mrr.exterior.coords)
    d1 = ((coords[1][0] - coords[0][0]) ** 2 + (coords[1][1] - coords[0][1]) ** 2) ** 0.5
    d2 = ((coords[2][0] - coords[1][0]) ** 2 + (coords[2][1] - coords[1][1]) ** 2) ** 0.5
    return min(d1, d2)


def _compactness(poly: Polygon) -> float:
    """Indice ISO normalisé : 4π·aire / périmètre² (= 1.0 pour cercle parfait)."""
    if poly.length < 1e-9:
        return 0.0
    return 4.0 * np.pi * poly.area / (poly.length ** 2)


def _vertex_count(poly: Polygon) -> int:
    """Nombre de sommets de l'anneau extérieur (dernier = premier, non compté)."""
    return len(poly.exterior.coords) - 1


# --------------------------------------------------------------------------- #
# Statistiques                                                                 #
# --------------------------------------------------------------------------- #

def _pcts(arr: np.ndarray) -> dict[str, float]:
    return {
        "min":    float(np.min(arr)),
        "p05":    float(np.percentile(arr, 5)),
        "p10":    float(np.percentile(arr, 10)),
        "p25":    float(np.percentile(arr, 25)),
        "median": float(np.median(arr)),
        "p75":    float(np.percentile(arr, 75)),
        "p90":    float(np.percentile(arr, 90)),
        "p95":    float(np.percentile(arr, 95)),
        "max":    float(np.max(arr)),
        "mean":   float(np.mean(arr)),
        "std":    float(np.std(arr)),
    }


def _elimination(arr: np.ndarray, thresholds: list[float | int]) -> dict[str, float]:
    """Fraction des polygones éliminés à chaque seuil."""
    return {str(t): round(float(np.mean(arr < t)), 3) for t in thresholds}


def _nearest_dists(polys: list[Polygon], max_n: int = 200) -> list[float]:
    """Distance au plus proche voisin pour un échantillon de polygones (O(n²), n ≤ max_n)."""
    n = min(len(polys), max_n)
    sample = random.sample(polys, n) if len(polys) > n else list(polys)
    dists = []
    for i in range(n):
        best = float("inf")
        for j in range(n):
            if i == j:
                continue
            d = sample[i].distance(sample[j])
            if d < best:
                best = d
            if d == 0.0:
                break
        if best < float("inf"):
            dists.append(best)
    return dists


def compute_class_stats(polys: list[Polygon]) -> dict[str, Any]:
    """Stats complètes (aire, largeur, compacité, sommets, voisinage) pour une classe."""
    if not polys:
        return {"count": 0}

    areas = np.array([p.area for p in polys])
    widths = np.array([_min_width(p) for p in polys])
    compacts = np.array([_compactness(p) for p in polys])
    vertices = np.array([_vertex_count(p) for p in polys], dtype=float)

    result: dict[str, Any] = {
        "count": len(polys),
        "area_m2": _pcts(areas),
        "min_width_m": _pcts(widths),
        "compactness": _pcts(compacts),
        "vertex_count": _pcts(vertices),
        "elimination_at_area_m2": _elimination(areas, _AREA_THRESHOLDS),
        "elimination_at_width_m": _elimination(widths, _WIDTH_THRESHOLDS),
    }

    if len(polys) >= 2:
        nd = _nearest_dists(polys)
        if nd:
            arr = np.array(nd)
            result["nearest_neighbor_m"] = _pcts(arr)
            result["fusion_candidates_at_dist_m"] = _elimination(arr, _FUSION_THRESHOLDS)

    return result


def compute_hole_stats(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Mesure les trous (anneaux intérieurs) de tous les polygones."""
    holes: list[Polygon] = []
    for geom in gdf.geometry:
        for poly in _flat_polygons(geom):
            for interior in poly.interiors:
                hole = Polygon(interior)
                if hole.area > 0.5:
                    holes.append(hole)

    if not holes:
        return {"count": 0}
    return compute_class_stats(holes)


# --------------------------------------------------------------------------- #
# Analyse GeoDataFrame                                                         #
# --------------------------------------------------------------------------- #

def analyze_gdf(gdf: gpd.GeoDataFrame, class_col: str) -> dict[str, Any]:
    """Analyse complète d'un GeoDataFrame vectoriel par classe."""
    if class_col not in gdf.columns:
        cols = list(gdf.columns)
        raise ValueError(f"Colonne '{class_col}' absente. Colonnes disponibles : {cols}")

    n_null = gdf[class_col].isna().sum()
    if n_null > 0:
        print(f"[AVERT] {n_null} features sans classe ignorées.", file=sys.stderr)

    by_class: dict[str, Any] = {}
    for cls in sorted(gdf[class_col].dropna().unique(), key=str):
        sub = gdf[gdf[class_col] == cls]
        polys: list[Polygon] = []
        for geom in sub.geometry:
            polys.extend(_flat_polygons(geom))
        by_class[str(cls)] = compute_class_stats(polys)

    return {
        "total_features": len(gdf),
        "classes": by_class,
        "holes": compute_hole_stats(gdf),
    }


# --------------------------------------------------------------------------- #
# Chargement des données                                                       #
# --------------------------------------------------------------------------- #

def _load_gpkg_oom(path: str, layer: str | None, name_map: dict[str, str] | None = None) -> gpd.GeoDataFrame:
    """Charge un GPKG export OOM via ogr (contourne l'encodage latin-1 de pyogrio).
    Applique _OOM_VEGE_NAMES pour créer une colonne 'class' (406/408/410).
    Ignore les features dont le nom n'est pas dans le mapping."""
    from shapely.wkt import loads as _wkt

    ds = ogr.Open(path)
    if ds is None:
        raise FileNotFoundError(f"ogr ne peut pas ouvrir : {path}")

    # Auto-détection couche *_areas si layer non fourni
    layer_name = layer
    if layer_name is None:
        for i in range(ds.GetLayerCount()):
            n = ds.GetLayer(i).GetName()
            if n.endswith("_areas"):
                layer_name = n
                break
        if layer_name is None:
            names = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]
            raise ValueError(f"Aucune couche '*_areas' trouvée. Couches : {names}. "
                             "Utiliser --layer pour spécifier.")

    lyr = ds.GetLayerByName(layer_name)
    srs = lyr.GetSpatialRef()
    if srs and srs.GetAuthorityCode(None):
        crs = f"EPSG:{srs.GetAuthorityCode(None)}"
    else:
        crs = "EPSG:2154"
        print("[INFO] CRS absent dans le GPKG — EPSG:2154 (Lambert-93) supposé.", file=sys.stderr)
    mapping = name_map if name_map is not None else _OOM_VEGE_NAMES

    rows = []
    skipped = 0
    for feat in lyr:
        raw_name = feat.GetField("Name") or ""
        name = _decode_surrogate(raw_name).strip()
        cls = mapping.get(name)
        if cls is None:
            skipped += 1
            continue
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        rows.append({"class": cls, "geometry": _wkt(geom_ref.ExportToWkt())})

    print(f"[INFO] {layer_name} : {len(rows)} polygones végétation ({skipped} ignorés).")
    if not rows:
        return gpd.GeoDataFrame(columns=["class", "geometry"])
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def load_ffco(path: str, class_col: str, layer: str | None = None,
              name_map: dict[str, str] | None = None) -> gpd.GeoDataFrame:
    """Charge un fichier vecteur FFCO (GeoJSON/Shapefile/GPKG) en EPSG:2154."""
    if path.lower().endswith(".gpkg"):
        gdf = _load_gpkg_oom(path, layer, name_map=name_map)
        class_col = "class"
    else:
        gdf = gpd.read_file(path)
    if gdf.crs is None:
        print("[AVERT] CRS absent — mesures en unités brutes.", file=sys.stderr)
    elif not gdf.crs.is_projected:
        gdf = gdf.to_crs("EPSG:2154")
        print("[INFO] Reprojection → EPSG:2154 (Lambert-93).")
    print(f"[INFO] {len(gdf)} features chargées depuis {path}")
    if class_col not in gdf.columns:
        print(f"[INFO] Colonnes disponibles : {list(gdf.columns)}")
    return gdf


def polygonize_raster(tif_path: str) -> gpd.GeoDataFrame:
    """GDAL Polygonize d'un raster classifié 8-bit → GeoDataFrame avec colonne 'class'."""
    ds = gdal.Open(tif_path)
    if ds is None:
        raise FileNotFoundError(f"Impossible d'ouvrir : {tif_path}")

    band = ds.GetRasterBand(1)
    crs_wkt = ds.GetProjection()

    srs = osr.SpatialReference()
    if crs_wkt:
        srs.ImportFromWkt(crs_wkt)

    epsg = srs.GetAuthorityCode(None) if crs_wkt else None
    if epsg:
        crs_out: str | None = f"EPSG:{epsg}"
    elif crs_wkt:
        crs_out = crs_wkt  # fallback WKT complet
    else:
        crs_out = None
        print("[AVERT] CRS raster absent — mesures en unités brutes.", file=sys.stderr)

    drv = ogr.GetDriverByName("MEM")
    mem_ds = drv.CreateDataSource("")
    lyr = mem_ds.CreateLayer("polys", srs=srs)
    lyr.CreateField(ogr.FieldDefn("DN", ogr.OFTInteger))

    print("[INFO] Polygonisation du raster HAG...", end=" ", flush=True)
    gdal.Polygonize(band, None, lyr, 0, [], callback=None)
    n_raw = lyr.GetFeatureCount()
    print(f"{n_raw} features brutes.")

    rows = []
    for feat in lyr:
        dn = feat.GetField("DN")
        if dn == 0:
            continue
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        geom = _wkt_loads(geom_ref.ExportToWkt())
        rows.append({"class": _HAG_CLASS_MAP.get(dn, dn), "geometry": geom})

    mem_ds = None  # libère le layer OGR
    ds = None      # ferme le dataset raster GDAL

    if not rows:
        print("[AVERT] Aucun polygone non-nul dans le raster.", file=sys.stderr)
        return gpd.GeoDataFrame(columns=["class", "geometry"])

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs_out)
    print(f"[INFO] {len(gdf)} polygones non-nuls conservés.")
    return gdf


# --------------------------------------------------------------------------- #
# Rapport et histogrammes                                                      #
# --------------------------------------------------------------------------- #

def save_json(report: dict[str, Any], out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[RAPPORT] -> {path}")


def _hist(values: np.ndarray, title: str, xlabel: str, out_path: Path) -> None:
    if not _MATPLOTLIB:
        return
    cap = np.percentile(values, 99) if len(values) > 1 else values.max()
    data = values[values <= cap]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(data, bins=50, edgecolor="black", alpha=0.75)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Fréquence")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def save_histograms(gdf: gpd.GeoDataFrame, class_col: str, out_dir: Path, prefix: str) -> None:
    if not _MATPLOTLIB:
        print("[INFO] matplotlib absent — histogrammes ignorés (pip install matplotlib).")
        return
    hdir = out_dir / "histogrammes"
    hdir.mkdir(exist_ok=True)

    for cls in sorted(gdf[class_col].unique(), key=str):
        sub = gdf[gdf[class_col] == cls]
        polys = [p for geom in sub.geometry for p in _flat_polygons(geom)]
        if not polys:
            continue
        slug = f"{prefix}_cls{cls}"
        areas = np.array([p.area for p in polys])
        widths = np.array([_min_width(p) for p in polys])
        verts = np.array([_vertex_count(p) for p in polys], dtype=float)

        _hist(areas, f"Classe {cls} — Aires (m²) [n={len(polys)}]",
              "Aire m²", hdir / f"{slug}_area.png")
        _hist(widths, f"Classe {cls} — Largeur min MRR (m) [n={len(polys)}]",
              "Largeur m", hdir / f"{slug}_width.png")
        _hist(verts, f"Classe {cls} — Nb sommets [n={len(polys)}]",
              "Sommets", hdir / f"{slug}_vertices.png")

    print(f"[HISTO] -> {hdir}/")


def print_summary(report: dict[str, Any], label: str) -> None:
    """Affiche un tableau lisible des métriques clés."""
    print(f"\n{'='*60}")
    print(f" {label.upper()} — {report.get('file', '')}")
    print(f"{'='*60}")
    print(f" Total features : {report.get('total_features', '?')}")
    print()

    for cls, stats in report.get("classes", {}).items():
        count = stats.get("count", 0)
        if count == 0:
            continue
        area = stats.get("area_m2", {})
        elim = stats.get("elimination_at_area_m2", {})
        w = stats.get("min_width_m", {})
        nn = stats.get("nearest_neighbor_m", {})
        v = stats.get("vertex_count", {})
        fus = stats.get("fusion_candidates_at_dist_m", {})

        print(f" Classe {cls} ({count} polygones)")
        if area:
            print(f"   Aire    : p10={area['p10']:.1f} | méd={area['median']:.1f} | p90={area['p90']:.1f} | p95={area['p95']:.1f} m²")
        if elim:
            print(f"   Élim.   : <20m²={elim.get('20', 0):.0%} | <50m²={elim.get('50', 0):.0%} | <100m²={elim.get('100', 0):.0%}")
        if w:
            print(f"   Largeur : p10={w['p10']:.1f} | méd={w['median']:.1f} | p90={w['p90']:.1f} m")
        if nn:
            print(f"   Voisin  : p10={nn['p10']:.1f} | méd={nn['median']:.1f} | p90={nn['p90']:.1f} m")
        if fus:
            print(f"   Fusion  : <5m={fus.get('5', 0):.0%} | <8m={fus.get('8', 0):.0%} | <10m={fus.get('10', 0):.0%}")
        if v:
            print(f"   Sommets : méd={v['median']:.0f} | p90={v['p90']:.0f} | max={v['max']:.0f}")
        print()

    holes = report.get("holes", {})
    n_h = holes.get("count", 0)
    if n_h > 0:
        h_area = holes.get("area_m2", {})
        h_elim = holes.get("elimination_at_area_m2", {})
        print(f" Trous : {n_h} | méd={h_area.get('median', 0):.1f} m² | p95={h_area.get('p95', 0):.1f} m²")
        if h_elim:
            print(f"   Élim. trous : <20m²={h_elim.get('20', 0):.0%} | <50m²={h_elim.get('50', 0):.0%}")
    print()


# --------------------------------------------------------------------------- #
# Commandes CLI                                                                #
# --------------------------------------------------------------------------- #

def cmd_ffco(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    name_map = _load_name_map(getattr(args, "mapping", None))
    gdf = load_ffco(args.fichier, args.class_col, layer=getattr(args, "layer", None), name_map=name_map)
    col = "class" if args.fichier.lower().endswith(".gpkg") else args.class_col
    report: dict[str, Any] = {
        "source": "ffco",
        "file": str(args.fichier),
        **analyze_gdf(gdf, col),
    }
    save_json(report, out_dir, "ffco_stats")
    print_summary(report, "FFCO")
    gdf_renamed = gdf.rename(columns={col: "_class"})
    save_histograms(gdf_renamed, "_class", out_dir, "ffco")


def cmd_hag(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    gdf = polygonize_raster(args.raster)
    report: dict[str, Any] = {
        "source": "hag",
        "file": str(args.raster),
        **analyze_gdf(gdf, "class"),
    }
    save_json(report, out_dir, "hag_stats")
    print_summary(report, "HAG")
    save_histograms(gdf, "class", out_dir, "hag")


def cmd_compare(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)

    gdf_ffco = load_ffco(args.fichier, args.class_col)
    rep_ffco: dict[str, Any] = {
        "source": "ffco",
        "file": str(args.fichier),
        **analyze_gdf(gdf_ffco, args.class_col),
    }
    save_json(rep_ffco, out_dir, "ffco_stats")

    gdf_hag = polygonize_raster(args.raster)
    rep_hag: dict[str, Any] = {
        "source": "hag",
        "file": str(args.raster),
        **analyze_gdf(gdf_hag, "class"),
    }
    save_json(rep_hag, out_dir, "hag_stats")

    print_summary(rep_ffco, "FFCO (carte réelle)")
    print_summary(rep_hag, "HAG (sortie pipeline)")

    gdf_ffco_r = gdf_ffco.rename(columns={args.class_col: "_class"})
    save_histograms(gdf_ffco_r, "_class", out_dir, "ffco")
    save_histograms(gdf_hag, "class", out_dir, "hag")

    print(f"[COMPARE] Rapports -> {out_dir}/ffco_stats.json et hag_stats.json")


# --------------------------------------------------------------------------- #
# main                                                                         #
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5.5 — Mesure corpus CO Generalization Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ffco = sub.add_parser("ffco", help="Analyser une carte FFCO vectorielle")
    p_ffco.add_argument("fichier", help="GeoJSON / Shapefile / GPKG")
    p_ffco.add_argument("--class-col", default="symbol",
                        help="Colonne code ISOM pour GeoJSON/SHP (défaut: symbol). "
                             "Ignoré pour GPKG (mapping OOM automatique).")
    p_ffco.add_argument("--layer", default=None,
                        help="Couche GPKG à lire (défaut: auto-détection *_areas).")
    p_ffco.add_argument("--mapping", default=None,
                        help="Fichier YAML nom→classe ISOM (défaut: mapping OOM intégré).")
    p_ffco.add_argument("--out-dir", default="rapports")
    p_ffco.set_defaults(func=cmd_ffco)

    p_hag = sub.add_parser("hag", help="Analyser un raster HAG classifié (8-bit)")
    p_hag.add_argument("raster", help="GeoTIFF classifié (valeurs 85/170/255)")
    p_hag.add_argument("--out-dir", default="rapports")
    p_hag.set_defaults(func=cmd_hag)

    p_cmp = sub.add_parser("compare", help="Comparer FFCO réel vs sortie HAG")
    p_cmp.add_argument("fichier", help="Carte FFCO vectorielle")
    p_cmp.add_argument("raster", help="Raster HAG classifié")
    p_cmp.add_argument("--class-col", default="symbol")
    p_cmp.add_argument("--out-dir", default="rapports")
    p_cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[ERREUR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
