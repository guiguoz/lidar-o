"""Diagnostic d'intersection : polygones pipeline vs légende FFCO/ISOM.

Pour chaque classe pipeline (406, 408, 410), calcule la fraction de surface
qui tombe sur chaque groupe de la légende FFCO. Test clé pour distinguer
sur-détection en terrain ouvert vs classification correcte sous couvert.

Usage :
    python scripts/diag_ffco_intersection.py --terrain kilemaed \\
        --pipeline output_kilemaed/vegetation.gpkg \\
        --ffco "autres cartes/Kilemäed.gpkg" \\
        --mapping scripts/mappings/isom_en.yaml

    python scripts/diag_ffco_intersection.py --terrain airelles \\
        --pipeline output_airelles/vegetation_final.geojson \\
        --ffco airelles.gpkg \\
        --mapping scripts/mappings/ffco_fr.yaml
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import pathlib
import sys

import yaml
import geopandas as gpd
import pandas as pd
from osgeo import ogr
from shapely.ops import unary_union
from shapely.validation import make_valid
from shapely.wkt import loads as wkt_loads

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _decode(raw: str) -> str:
    return "".join(chr(ord(c) - 0xDC00) if 0xDC80 <= ord(c) <= 0xDCFF else c for c in raw)


def _load_mapping(yaml_path: str) -> tuple[dict[str, str], dict[str, str]]:
    with open(yaml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    name_to_group: dict[str, str] = {}
    group_label: dict[str, str] = {}
    for group, meta in cfg["groups"].items():
        for name in meta.get("names", []):
            name_to_group[name] = group
        if "label" in meta:
            group_label[group] = meta["label"]
    return name_to_group, group_label


def _resolve_path(path: str) -> str:
    """Résout un chemin avec des caractères spéciaux via glob si nécessaire."""
    p = pathlib.Path(path)
    if p.exists():
        return str(p)
    # Fallback : glob dans le dossier parent, cherche un fichier du même type
    # dont les 5 premiers caractères ASCII correspondent (avant tout char spécial).
    stem = p.stem
    safe_prefix = "".join(c for c in stem if ord(c) < 128)[:5]
    if safe_prefix:
        pattern = str(p.parent / (safe_prefix + "*" + p.suffix))
        matches = _glob.glob(pattern)
        if len(matches) == 1:
            return matches[0]
    return path


def _load_ffco_as_gdf(gpkg_path: str, name_to_group: dict[str, str]) -> gpd.GeoDataFrame:
    """Charge le GPKG FFCO, décode les noms, assigne les groupes."""
    gpkg_path = _resolve_path(gpkg_path)
    ds = ogr.Open(gpkg_path)
    if ds is None:
        raise FileNotFoundError(f"Impossible d'ouvrir : {gpkg_path}")
    lyr = None
    for i in range(ds.GetLayerCount()):
        if "area" in ds.GetLayer(i).GetName().lower():
            lyr = ds.GetLayer(i)
            break
    if lyr is None:
        raise ValueError("Couche *_areas introuvable")

    rows = []
    for feat in lyr:
        raw = feat.GetField("Name") or ""
        name = _decode(raw).strip()
        group = name_to_group.get(name)
        if group is None:
            # Essai par préfixe (noms tronqués)
            for n, g in name_to_group.items():
                if name.startswith(n[:28]):
                    group = g
                    break
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        geom = make_valid(wkt_loads(geom_ref.ExportToWkt()))
        rows.append({"name": name, "group": group, "geometry": geom})
    ds = None
    if not rows:
        raise ValueError("Aucune entité chargée depuis le GPKG")

    gdf = gpd.GeoDataFrame(rows, crs=None)
    # Récupérer le CRS depuis le fichier.
    # OCAD/OOM exporte parfois le datum géographique (ex EPSG:4171, 4180) même
    # quand les coordonnées sont métriques (Lambert 93, L-EST97). On détecte ce
    # cas par la magnitude des coordonnées (|x|>1000 → métrique, pas géographique).
    ds2 = ogr.Open(gpkg_path)
    for i in range(ds2.GetLayerCount()):
        if "area" in ds2.GetLayer(i).GetName().lower():
            srs = ds2.GetLayer(i).GetSpatialRef()
            if srs:
                epsg = srs.GetAttrValue("AUTHORITY", 1)
                is_geographic = srs.IsGeographic()
                if epsg and not is_geographic:
                    gdf = gdf.set_crs(f"EPSG:{epsg}", allow_override=True)
                elif epsg and is_geographic and rows:
                    # Datum géographique mais coordonnées métriques : CRS incorrect
                    # Laisser CRS=None, la reprojection sera évitée dans _intersection_by_group
                    pass
            break
    ds2 = None
    return gdf


def _load_pipeline(gpkg_or_geojson: str, cls: int) -> gpd.GeoDataFrame:
    """Charge les polygones d'une classe depuis le GeoPackage ou GeoJSON pipeline."""
    path = pathlib.Path(gpkg_or_geojson)
    if path.suffix == ".gpkg":
        layer = f"veg_{cls}"
        try:
            gdf = gpd.read_file(gpkg_or_geojson, layer=layer)
        except Exception:
            gdf = gpd.read_file(gpkg_or_geojson)
            if "class" in gdf.columns:
                gdf = gdf[gdf["class"] == cls]
    else:
        gdf = gpd.read_file(gpkg_or_geojson)
        if "class" in gdf.columns:
            gdf = gdf[gdf["class"] == cls]
    return gdf


def _intersection_by_group(
    pipeline_gdf: gpd.GeoDataFrame,
    ffco_gdf: gpd.GeoDataFrame,
    group_label: dict[str, str],
) -> pd.DataFrame:
    """Calcule la surface pipeline qui tombe dans chaque groupe FFCO."""
    if len(pipeline_gdf) == 0:
        return pd.DataFrame(columns=["group", "label", "area_m2", "pct"])

    # Harmoniser CRS.
    # OCAD/OOM peut exporter avec un datum géographique (EPSG:4171, 4180) alors
    # que les coordonnées sont métriques. On détecte ce cas par chevauchement des
    # bounding boxes : si les extents se recouvrent sans reprojection, les deux
    # sont déjà dans le même référentiel métrique.
    pb = pipeline_gdf.total_bounds   # [xmin, ymin, xmax, ymax]
    fb = ffco_gdf.total_bounds
    bbox_overlap = (fb[0] < pb[2]) and (fb[2] > pb[0]) and (fb[1] < pb[3]) and (fb[3] > pb[1])

    if bbox_overlap or ffco_gdf.crs is None:
        # Même espace de coordonnées — forcer le CRS sans reprojection
        if pipeline_gdf.crs is not None:
            ffco_gdf = ffco_gdf.set_crs(pipeline_gdf.crs, allow_override=True)
    elif pipeline_gdf.crs is not None and ffco_gdf.crs is not None and pipeline_gdf.crs != ffco_gdf.crs:
        ffco_gdf = ffco_gdf.to_crs(pipeline_gdf.crs)

    total_area = float(pipeline_gdf.geometry.area.sum())
    results = []

    active_groups = ffco_gdf["group"].dropna().unique()
    for group in sorted(active_groups):
        if group == "skip":
            continue
        sel = ffco_gdf[ffco_gdf["group"] == group]
        union = sel.geometry.union_all() if hasattr(sel.geometry, "union_all") else unary_union(sel.geometry)
        inter_area = float(pipeline_gdf.geometry.intersection(union).area.sum())
        results.append({
            "group": group,
            "label": group_label.get(group, group),
            "area_m2": inter_area,
            "pct": 100.0 * inter_area / total_area if total_area > 0 else 0.0,
        })

    # Surface hors zones FFCO
    all_ffco = ffco_gdf[ffco_gdf["group"] != "skip"].geometry
    all_union = all_ffco.union_all() if hasattr(all_ffco, "union_all") else unary_union(all_ffco)
    outside = float(pipeline_gdf.geometry.difference(all_union).area.sum())
    results.append({
        "group": "_outside_ffco",
        "label": "Hors emprise FFCO",
        "area_m2": outside,
        "pct": 100.0 * outside / total_area if total_area > 0 else 0.0,
    })

    return pd.DataFrame(results).sort_values("area_m2", ascending=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Intersection polygones pipeline vs groupes FFCO/ISOM"
    )
    parser.add_argument("--terrain", required=True)
    parser.add_argument("--pipeline", required=True,
                        help="GeoPackage ou GeoJSON de sortie pipeline")
    parser.add_argument("--ffco", required=True, help="GPKG FFCO/ISOM de référence")
    parser.add_argument("--mapping", required=True, help="YAML de mapping zones")
    parser.add_argument("--out-dir", help="Dossier de sortie JSON (défaut: rapports/{terrain})")
    parser.add_argument("--classes", nargs="+", type=int, default=[406, 408, 410])
    args = parser.parse_args()

    name_to_group, group_label = _load_mapping(args.mapping)
    ffco_gdf = _load_ffco_as_gdf(args.ffco, name_to_group)
    print(f"[INFO] FFCO : {len(ffco_gdf)} polygones  ({ffco_gdf['group'].value_counts().to_dict()})")

    out_dir = pathlib.Path(args.out_dir or f"rapports/{args.terrain}")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {"terrain": args.terrain, "pipeline": args.pipeline,
              "ffco": args.ffco, "mapping": args.mapping, "classes": {}}

    print(f"\n{'Groupe':<35} {'Aire (ha)':>10}  {'%':>6}")
    print("-" * 56)

    for cls in args.classes:
        pipe_gdf = _load_pipeline(args.pipeline, cls)
        total_ha = pipe_gdf.geometry.area.sum() / 1e4
        print(f"\n=== Classe {cls} — {len(pipe_gdf)} polygones, {total_ha:.1f} ha ===")

        if len(pipe_gdf) == 0:
            report["classes"][str(cls)] = {"n_polygons": 0, "total_ha": 0.0, "by_group": []}
            continue

        df = _intersection_by_group(pipe_gdf, ffco_gdf, group_label)
        for _, row in df.iterrows():
            print(f"  {row['label']:<33} {row['area_m2']/1e4:>10.2f} ha  {row['pct']:>6.1f}%")

        report["classes"][str(cls)] = {
            "n_polygons": len(pipe_gdf),
            "total_ha": round(total_ha, 2),
            "by_group": df.to_dict("records"),
        }

    json_path = out_dir / f"ffco_intersection_{args.terrain}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[JSON] -> {json_path}")


if __name__ == "__main__":
    main()
