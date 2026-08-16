"""Sweep min_hole_area_m2 sur vegetation_masked.gpkg — métriques de forme.

Applique remove_holes à différents seuils (en m²) sur le fichier final et mesure :
  - compacité médiane (4πA/P²)
  - % polygones troués
  - nombre de trous restants, aire médiane en mm²
  - surface totale par classe (vérifier que le remplissage ne gonfle pas trop)

Usage : python scripts/diag/sweep_remove_holes.py
"""
from __future__ import annotations

import math
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import geopandas as gpd
import shapely.geometry as sg
from shapely.geometry import Polygon, MultiPolygon

ROOT = pathlib.Path(__file__).parent.parent.parent
OUTPUT = ROOT / "output"
MASKED_GPKG = OUTPUT / "vegetation_masked.gpkg"

SCALE = 10_000
MM2 = 1e6 / SCALE**2  # facteur m² → mm² à l'échelle cible

# Seuils à tester (m² au sol)
THRESHOLDS_M2 = [0, 30, 100, 200, 300, 500, 1000]
# 0 = état brut (aucun remove_holes supplémentaire)

LAYERS = {"veg_406": 406, "veg_408": 408, "veg_410": 410}

# Cibles FFCO 406 (reference Grimbosq)
FFCO_406 = {"compact": 0.663, "pct_holed": 1.1, "psa": 4.33}


def _drop_holes(geom: Polygon | MultiPolygon, min_area: float) -> Polygon | MultiPolygon:
    if isinstance(geom, Polygon):
        kept = [h for h in geom.interiors if Polygon(h).area >= min_area]
        return Polygon(geom.exterior, kept)
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([_drop_holes(p, min_area) for p in geom.geoms])
    return geom


def _iter_polys(geom: sg.base.BaseGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    if hasattr(geom, "geoms"):
        result: list[Polygon] = []
        for g in geom.geoms:
            result.extend(_iter_polys(g))
        return result
    return []


def _metrics(gdf: gpd.GeoDataFrame, threshold_m2: float) -> dict:
    """Applique remove_holes avec threshold_m2 et calcule les métriques de forme."""
    if threshold_m2 > 0:
        geoms = gdf.geometry.apply(lambda g: _drop_holes(g, threshold_m2))
    else:
        geoms = gdf.geometry

    compacities: list[float] = []
    psa_list: list[float] = []
    holed_count = 0
    hole_areas_mm2: list[float] = []
    total_area_m2 = 0.0

    for geom in geoms:
        polys = _iter_polys(geom)
        has_holes = False
        for poly in polys:
            total_area_m2 += poly.area
            if poly.area <= 0 or poly.length <= 0:
                continue
            compacities.append(4 * math.pi * poly.area / poly.length ** 2)
            psa_list.append(poly.length / math.sqrt(poly.area))
            for interior in poly.interiors:
                hole_areas_mm2.append(Polygon(interior).area * MM2)
                has_holes = True
        if has_holes:
            holed_count += 1

    return {
        "compact_med": float(np.median(compacities)) if compacities else 0.0,
        "pct_holed": float(holed_count / max(len(gdf), 1) * 100),
        "n_holes": len(hole_areas_mm2),
        "hole_med_mm2": float(np.median(hole_areas_mm2)) if hole_areas_mm2 else 0.0,
        "psa_med": float(np.median(psa_list)) if psa_list else 0.0,
        "total_ha": total_area_m2 / 1e4,
    }


def main() -> None:
    if not MASKED_GPKG.exists():
        raise FileNotFoundError(f"Absent : {MASKED_GPKG}")

    print(f"Source : {MASKED_GPKG.name}\n")

    for layer_name, cls in LAYERS.items():
        gdf = gpd.read_file(str(MASKED_GPKG), layer=layer_name)
        gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
        n = len(gdf)

        print(f"=== Classe {cls} ({layer_name}) — {n} polygones ===")
        hdr = (f"  {'seuil_m2':>9}  {'seuil_mm2':>9}  "
               f"{'compact':>8}  {'%troues':>8}  "
               f"{'n_trous':>8}  {'trou_med':>9}  "
               f"{'P/sqrtA':>8}  {'surf_ha':>8}")
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))

        baseline_ha = None
        for thr in THRESHOLDS_M2:
            m = _metrics(gdf, thr)
            if baseline_ha is None:
                baseline_ha = m["total_ha"]

            seuil_mm2 = thr * MM2
            surf_delta = m["total_ha"] - baseline_ha
            surf_str = f"{m['total_ha']:.2f}"
            if surf_delta > 0.01:
                surf_str += f" (+{surf_delta:.2f})"

            label = f"  {thr:>9d}  {seuil_mm2:>9.2f}  "
            row = (f"{m['compact_med']:>8.3f}  {m['pct_holed']:>7.1f}%  "
                   f"{m['n_holes']:>8d}  {m['hole_med_mm2']:>9.2f}  "
                   f"{m['psa_med']:>8.2f}  {surf_str:>8}")
            marker = ""
            if cls == 406:
                # Marquer la ligne la plus proche de la cible compacité
                if abs(m["compact_med"] - FFCO_406["compact"]) < 0.05:
                    marker = " <-- proche cible"
            print(label + row + marker)

        if cls == 406:
            print(f"\n  Cible FFCO 406 : compact={FFCO_406['compact']:.3f}  "
                  f"%troues={FFCO_406['pct_holed']:.1f}%  P/sqrtA={FFCO_406['psa']:.2f}")

        print()


if __name__ == "__main__":
    main()
