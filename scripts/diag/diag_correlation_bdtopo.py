"""
Corrélation spatiale : polygones HAG vs éléments BD TOPO (haies, routes).

Pour chaque couche BD TOPO, calcule le % de polygones et de surface
qui intersectent un buffer de rayon donné.

Usage :
    python scripts/diag_correlation_bdtopo.py output_tourouvre/veg_406.geojson
    python scripts/diag_correlation_bdtopo.py output_tourouvre/veg_406.geojson --buffers 5 10 15
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.ops import unary_union


WFS_URL = "https://data.geopf.fr/wfs"
BDTOPO_LAYERS = {
    "haie": "BDTOPO_V3:haie",
    "route": "BDTOPO_V3:troncon_de_route",
}
CRS = "EPSG:2154"


def fetch_wfs(layer: str, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    xmin, ymin, xmax, ymax = bbox
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": layer,
        "SRSNAME": CRS,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},{CRS}",
        "OUTPUTFORMAT": "application/json",
        "COUNT": "5000",
    }
    r = requests.get(WFS_URL, params=params, timeout=60)
    r.raise_for_status()
    import io
    gdf = gpd.read_file(io.BytesIO(r.content))
    if gdf.crs is None:
        gdf = gdf.set_crs(CRS)
    elif gdf.crs.to_epsg() != 2154:
        gdf = gdf.to_crs(CRS)
    return gdf


def correlation_stats(
    polys: gpd.GeoDataFrame,
    ref: gpd.GeoDataFrame,
    buffer_m: float,
) -> dict:
    if ref.empty:
        return {"n_polys": 0, "pct_polys": 0.0, "pct_area": 0.0}

    buf = unary_union(ref.geometry.buffer(buffer_m))
    hits = polys[polys.intersects(buf)]
    pct_polys = len(hits) / len(polys) * 100 if len(polys) > 0 else 0.0
    pct_area = hits.area.sum() / polys.area.sum() * 100 if polys.area.sum() > 0 else 0.0
    return {
        "n_polys": len(hits),
        "pct_polys": round(pct_polys, 1),
        "pct_area": round(pct_area, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("veg", help="GeoJSON des polygones HAG (ex: output_tourouvre/veg_406.geojson)")
    parser.add_argument("--buffers", nargs="+", type=float, default=[5.0, 10.0],
                        help="Rayons de buffer en mètres (défaut: 5 10)")
    args = parser.parse_args()

    veg_path = Path(args.veg)
    if not veg_path.exists():
        print(f"[ERREUR] Fichier introuvable : {veg_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Chargement {veg_path} ...")
    polys = gpd.read_file(veg_path)
    if polys.crs is None:
        polys = polys.set_crs(CRS)
    elif polys.crs.to_epsg() != 2154:
        polys = polys.to_crs(CRS)

    bounds = polys.total_bounds  # (xmin, ymin, xmax, ymax)
    bbox = tuple(bounds)
    print(f"[INFO] Emprise : {bbox[0]:.0f},{bbox[1]:.0f} → {bbox[2]:.0f},{bbox[3]:.0f}")
    print(f"[INFO] {len(polys)} polygones chargés\n")

    ref_data: dict[str, gpd.GeoDataFrame] = {}
    for name, layer in BDTOPO_LAYERS.items():
        print(f"[INFO] Téléchargement WFS : {layer} ...")
        try:
            gdf = fetch_wfs(layer, bbox)
            print(f"[INFO]   → {len(gdf)} objets")
            ref_data[name] = gdf
        except Exception as e:
            print(f"[WARN] Échec WFS {layer} : {e}")
            ref_data[name] = gpd.GeoDataFrame(geometry=[], crs=CRS)

    print()
    rows = []
    for buf_m in args.buffers:
        for name, ref in ref_data.items():
            stats = correlation_stats(polys, ref, buf_m)
            rows.append({
                "source": name,
                "buffer_m": buf_m,
                "n_polys": stats["n_polys"],
                "pct_polys": stats["pct_polys"],
                "pct_area": stats["pct_area"],
            })

    df = pd.DataFrame(rows)

    print("=" * 60)
    print(f" Corrélation spatiale — {veg_path.name} ({len(polys)} polygones)")
    print("=" * 60)
    for buf_m in args.buffers:
        print(f"\n Buffer {buf_m:.0f} m :")
        sub = df[df["buffer_m"] == buf_m]
        print(f"   {'Source':<10} {'N polys':>8}  {'% polys':>8}  {'% area':>8}")
        for _, row in sub.iterrows():
            print(f"   {row['source']:<10} {row['n_polys']:>8}  {row['pct_polys']:>7.1f}%  {row['pct_area']:>7.1f}%")

    # Polygones hors haies ET hors routes (buffer 10m)
    if "haie" in ref_data and "route" in ref_data:
        buf10 = args.buffers[-1]
        union_all = unary_union(
            ref_data["haie"].geometry.buffer(buf10).tolist()
            + ref_data["route"].geometry.buffer(buf10).tolist()
        )
        outside = polys[~polys.intersects(union_all)]
        pct = len(outside) / len(polys) * 100
        pct_a = outside.area.sum() / polys.area.sum() * 100
        print(f"\n Hors haies ET routes ({buf10:.0f} m) :")
        print(f"   {len(outside)} polygones ({pct:.1f}%) — {pct_a:.1f}% de la surface")


if __name__ == "__main__":
    main()
