"""Consigne 1 — Caractérisation géographique des cellules total_count=0 sur Airelles.

Produit :
  rapports/airelles/mask_nodata.tif       — raster binaire (1=nodata, 0=valide)
  rapports/airelles/mask_nodata.geojson   — polygones pour inspection QGIS
  rapports/airelles/nodata_components.csv — tableau composantes (aire, compacite, cause)
  rapports/airelles/nodata_summary.txt    — synthese

Croisements :
  - surface_hydrographique BD TOPO (gpkg/shp dans --bdtopo si disponible)
  - bounding boxes dalles COPC (depuis --tiles)

Usage :
    py -3.14 scripts/diag_airelles_nodata.py \
        --total output_airelles/total_count.tif
    py -3.14 scripts/diag_airelles_nodata.py \
        --total output_airelles/total_count.tif \
        --tiles LIDAR/LHD_FXX_*.copc.laz \
        --bdtopo data/airelles/surface_hydrographique.gpkg
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import rasterio
from rasterio.features import shapes
import shapely
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union
from scipy.ndimage import label as nd_label


# ---------------------------------------------------------------------------
# Raster masque nodata
# ---------------------------------------------------------------------------

def build_nodata_raster(
    total_path: pathlib.Path, out_tif: pathlib.Path
) -> tuple[np.ndarray, dict]:
    """Produit un raster binaire : 1 = total_count <= 0, 0 = valide."""
    with rasterio.open(total_path) as src:
        data = src.read(1).astype(np.float32)
        profile = src.profile.copy()
        nodata_val = src.nodata

    if nodata_val is not None:
        source_nodata = data == nodata_val
    else:
        source_nodata = np.zeros_like(data, dtype=bool)

    zero_mask = (data <= 0) & ~source_nodata
    mask_arr = zero_mask.astype(np.uint8)

    total_cells = data.size
    zero_cells = int(zero_mask.sum())
    print(f"  Cellules totales    : {total_cells:,}")
    print(f"  total_count <= 0    : {zero_cells:,} ({zero_cells / total_cells:.1%})")
    print(f"  nodata source       : {int(source_nodata.sum()):,}")

    out_profile = profile.copy()
    out_profile.update(dtype="uint8", nodata=255, count=1)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_tif, "w", **out_profile) as dst:
        dst.write(mask_arr, 1)
    print(f"  Raster masque -> {out_tif}")

    return mask_arr, profile


# ---------------------------------------------------------------------------
# Polygonisation + composantes connexes
# ---------------------------------------------------------------------------

def polygonize_mask(
    mask_arr: np.ndarray, profile: dict
) -> list[dict]:
    """Polygonise les zones total_count=0.

    Retourne une liste de dicts {geometry, properties} avec CRS dans profile.
    """
    transform = profile["transform"]
    polys = []
    for geom_dict, val in shapes(mask_arr, transform=transform):
        if val == 1:
            polys.append(shape(geom_dict))

    if not polys:
        print("  Aucune zone nodata trouvee.")
        return []

    # Dissoudre + exploser = composantes connexes distinctes
    merged = unary_union(polys)
    if merged.geom_type == "Polygon":
        components = [merged]
    else:
        components = list(merged.geoms)

    print(f"  Composantes connexes : {len(components)}")
    return components


def characterize_components(components: list) -> list[dict]:
    """Calcule aire (ha), perimetre, compacite, bbox pour chaque composante."""
    rows = []
    for i, geom in enumerate(components):
        area_m2 = geom.area
        perim = geom.length
        compact = (4 * math.pi * area_m2 / (perim ** 2)) if perim > 0 else 0.0
        b = geom.bounds  # (minx, miny, maxx, maxy)
        w = b[2] - b[0]
        h = b[3] - b[1]
        rows.append({
            "id": i,
            "geometry": geom,
            "area_ha": area_m2 / 1e4,
            "perimeter_m": perim,
            "compactness": compact,
            "width_m": w,
            "height_m": h,
            "cause": _classify_cause(area_m2 / 1e4, compact, w, h),
        })
    rows.sort(key=lambda r: r["area_ha"], reverse=True)
    return rows


def _classify_cause(area_ha: float, compact: float, w: float, h: float) -> str:
    ratio = min(w, h) / max(w, h) if max(w, h) > 0 else 1.0
    if ratio < 0.15 and area_ha > 5:
        return "bord_dalle"
    if area_ha > 10 and compact > 0.2:
        return "eau_probable"
    if area_ha > 50:
        return "dalle_manquante_probable"
    return "indetermine"


# ---------------------------------------------------------------------------
# Croisement BD TOPO hydrographie (lecture via GDAL si disponible)
# ---------------------------------------------------------------------------

def cross_bdtopo_hydro(rows: list[dict], hydro_path: pathlib.Path, crs_str: str) -> list[dict]:
    """Marque 'eau_bdtopo' les composantes qui intersectent la surface hydrographique.

    Lit le fichier avec rasterio/GDAL via fiona si dispo, sinon tente json direct.
    """
    try:
        import fiona
        polys = []
        with fiona.open(hydro_path) as src:
            for feat in src:
                polys.append(shape(feat["geometry"]))
        hydro_union = unary_union(polys)
    except Exception as e:
        print(f"  [AVERT] Lecture BD TOPO hydro echouee : {e}", file=sys.stderr)
        print(f"          Croisement hydrographique ignore.", file=sys.stderr)
        return rows

    for row in rows:
        if row["geometry"].intersects(hydro_union):
            overlap = row["geometry"].intersection(hydro_union).area
            frac = overlap / row["geometry"].area if row["geometry"].area > 0 else 0.0
            if frac > 0.3:
                row = dict(row, cause="eau_bdtopo")
    return rows


# ---------------------------------------------------------------------------
# Croisement dalles COPC
# ---------------------------------------------------------------------------

def cross_tiles(rows: list[dict], tile_paths: list[str]) -> list[dict]:
    """Marque 'hors_dalle' les composantes hors couverture des tuiles COPC."""
    tile_boxes = []
    for tp in tile_paths:
        try:
            with rasterio.open(tp) as src:
                tile_boxes.append(box(*src.bounds))
        except Exception:
            # Fallback : bbox desde le nom IGN LHD_FXX_CCCC_RRRR_...
            name = pathlib.Path(tp).stem
            parts = name.split("_")
            try:
                col = int(parts[2])
                row_val = int(parts[3])
                x0, y0 = col * 1000, row_val * 1000
                tile_boxes.append(box(x0, y0, x0 + 1000, y0 + 1000))
            except (IndexError, ValueError):
                pass

    if not tile_boxes:
        print("  [AVERT] Aucune bbox dalle calculable.", file=sys.stderr)
        return rows

    coverage = unary_union(tile_boxes)
    updated = []
    for row in rows:
        if row["cause"] == "indetermine" and not row["geometry"].intersects(coverage):
            row = dict(row, cause="hors_dalle")
        updated.append(row)
    return updated


# ---------------------------------------------------------------------------
# Emprise exploitable (fragmentation de la zone valide)
# ---------------------------------------------------------------------------

def compute_usable_extent(mask_arr: np.ndarray, profile: dict) -> None:
    res = abs(profile["transform"].a)
    cell_m2 = res * res
    total = mask_arr.size
    nodata = int((mask_arr == 1).sum())
    usable = total - nodata

    print(f"\n  Emprise totale      : {total * cell_m2 / 1e4:.1f} ha")
    print(f"  Emprise exploitable : {usable * cell_m2 / 1e4:.1f} ha ({usable / total:.1%})")

    valid_arr = (mask_arr == 0).astype(np.uint8)
    labeled, n_comp = nd_label(valid_arr)
    sizes = sorted(
        [int((labeled == i).sum()) * cell_m2 / 1e4 for i in range(1, n_comp + 1)],
        reverse=True,
    )
    print(f"  Composantes valides : {n_comp}")
    if sizes:
        print(f"  Plus grande         : {sizes[0]:.1f} ha")
        if len(sizes) > 1:
            print(f"  2e plus grande      : {sizes[1]:.1f} ha")
        small = sum(s < 1.0 for s in sizes)
        if small > 0:
            print(f"  < 1 ha              : {small} composantes")


# ---------------------------------------------------------------------------
# Sauvegarde GeoJSON
# ---------------------------------------------------------------------------

def save_geojson(rows: list[dict], out_path: pathlib.Path, crs_str: str) -> None:
    features = []
    for row in rows:
        props = {k: v for k, v in row.items() if k != "geometry"}
        props["area_ha"] = round(props["area_ha"], 4)
        props["perimeter_m"] = round(props["perimeter_m"], 2)
        props["compactness"] = round(props["compactness"], 4)
        props["width_m"] = round(props["width_m"], 1)
        props["height_m"] = round(props["height_m"], 1)
        features.append({
            "type": "Feature",
            "geometry": mapping(row["geometry"]),
            "properties": props,
        })
    fc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs_str}},
        "features": features,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  GeoJSON -> {out_path}")


def save_csv(rows: list[dict], out_path: pathlib.Path) -> None:
    cols = ["id", "area_ha", "perimeter_m", "compactness", "width_m", "height_m", "cause"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in cols})
    print(f"  CSV     -> {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostic cellules total_count=0 sur Airelles"
    )
    parser.add_argument("--total", required=True,
                        help="Raster total_count.tif (output_airelles/)")
    parser.add_argument("--tiles", nargs="*", default=[],
                        help="Chemins COPC .laz pour croisement bbox dalles")
    parser.add_argument("--bdtopo", default=None,
                        help="Couche surface_hydrographique (gpkg/shp)")
    parser.add_argument("--out-dir", default="rapports/airelles",
                        help="Dossier de sortie (defaut: rapports/airelles)")
    args = parser.parse_args()

    total_path = pathlib.Path(args.total)
    out_dir = pathlib.Path(args.out_dir)

    if not total_path.exists():
        print(f"[ERREUR] {total_path} introuvable", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f" Diagnostic nodata Airelles — {total_path}")
    print(f"{'='*60}")

    print(f"\n[1] Construction raster masque ...")
    mask_arr, profile = build_nodata_raster(total_path, out_dir / "mask_nodata.tif")
    crs_str = str(profile.get("crs", "EPSG:2154"))

    print(f"\n[2] Polygonisation ...")
    components = polygonize_mask(mask_arr, profile)

    if not components:
        print("Aucune zone nodata — arret.")
        return

    print(f"\n[3] Caracterisation morphologique ...")
    rows = characterize_components(components)

    if args.bdtopo and pathlib.Path(args.bdtopo).exists():
        print(f"\n[4] Croisement BD TOPO hydrographie ...")
        rows = cross_bdtopo_hydro(rows, pathlib.Path(args.bdtopo), crs_str)
    else:
        print(f"\n  [INFO] --bdtopo non fourni ou absent. Relancer avec BD TOPO pour affiner.")

    if args.tiles:
        print(f"\n[5] Croisement dalles COPC ...")
        rows = cross_tiles(rows, args.tiles)
    else:
        print(f"\n  [INFO] --tiles non fourni. Relancer avec chemins COPC pour affiner.")

    # Resume causes
    from collections import Counter
    cause_counter: Counter = Counter()
    cause_area: dict[str, float] = {}
    for row in rows:
        c = row["cause"]
        cause_counter[c] += 1
        cause_area[c] = cause_area.get(c, 0.0) + row["area_ha"]

    print(f"\n[6] Tableau causes :")
    print(f"  {'Cause':<30} {'N':>5}  {'Aire (ha)':>10}")
    print(f"  {'-'*30}  {'-'*5}  {'-'*10}")
    for cause, n in cause_counter.most_common():
        print(f"  {cause:<30} {n:>5}  {cause_area[cause]:>10.1f}")

    print(f"\n  Top 10 composantes :")
    print(f"  {'ID':>4}  {'aire ha':>8}  {'compact':>7}  {'cause'}")
    print(f"  {'-'*4}  {'-'*8}  {'-'*7}  {'-'*20}")
    for row in rows[:10]:
        print(f"  {row['id']:>4}  {row['area_ha']:>8.2f}  {row['compactness']:>7.3f}  {row['cause']}")

    print(f"\n[7] Emprise exploitable ...")
    compute_usable_extent(mask_arr, profile)

    print(f"\n[8] Sauvegarde ...")
    save_geojson(rows, out_dir / "mask_nodata.geojson", crs_str)
    save_csv(rows, out_dir / "nodata_components.csv")

    total_nodata_ha = sum(r["area_ha"] for r in rows)
    summary_lines = [
        f"Diagnostic nodata Airelles -- {total_path}",
        f"Composantes connexes : {len(rows)}",
        f"Aire nodata totale   : {total_nodata_ha:.1f} ha",
        "",
        "Causes :",
    ]
    for cause, n in cause_counter.most_common():
        summary_lines.append(
            f"  {cause:<30} {n:>5} composantes  {cause_area[cause]:.1f} ha"
        )
    summary_path = out_dir / "nodata_summary.txt"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"  Resume  -> {summary_path}")

    print(f"\n{'='*60}")
    print(f" QGIS : ouvrir {out_dir / 'mask_nodata.geojson'}")
    print(f"        + fond output_airelles/total_count.tif")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
