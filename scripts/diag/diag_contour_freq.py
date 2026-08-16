"""Caractérisation de la fréquence spatiale des contours + sweep Chaikin.

Mesure sur les polygones pipeline (cpt < 0.3, hors isthmes) ET les polygones FFCO 406 :
  - Espacement médian entre sommets consécutifs
  - Angle de déviation médian à chaque sommet (0 = droit, pi = demi-tour)

Puis sweep chaikin_passes = 1, 2, 3, 5 avec compacité et %<0.3 en contrôle.

Usage :
    python scripts/diag_contour_freq.py
"""
from __future__ import annotations

import copy
import json
import math
import pathlib
import sys

import numpy as np
import yaml
from osgeo import ogr
from shapely.geometry import MultiPolygon, Polygon, shape

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def compactness(g: Polygon | MultiPolygon) -> float:
    a, p = g.area, g.length
    return 4 * math.pi * a / (p * p) if p > 0 else 0.0


def ext_sqrt_a(g: Polygon | MultiPolygon) -> float:
    a = g.area
    if a <= 0:
        return 0.0
    ext_p = sum(p.exterior.length for p in g.geoms) if isinstance(g, MultiPolygon) else g.exterior.length
    return ext_p / math.sqrt(a)


def _ring_vertex_stats(coords: list) -> tuple[list[float], list[float]]:
    """Espacements inter-sommets et angles de déviation sur un anneau."""
    pts = [c[:2] for c in coords[:-1]]  # sans doublon de fermeture
    n = len(pts)
    if n < 3:
        return [], []

    spacings: list[float] = []
    angles: list[float] = []

    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        c = pts[(i + 2) % n]

        dx_ab = b[0] - a[0]
        dy_ab = b[1] - a[1]
        seg_len = math.hypot(dx_ab, dy_ab)
        spacings.append(seg_len)

        dx_bc = c[0] - b[0]
        dy_bc = c[1] - b[1]
        cross = dx_ab * dy_bc - dy_ab * dx_bc
        dot = dx_ab * dx_bc + dy_ab * dy_bc
        angle = abs(math.atan2(cross, dot))  # 0 = droit, pi = demi-tour
        angles.append(angle)

    return spacings, angles


def polygon_vertex_stats(geom: Polygon | MultiPolygon) -> tuple[list[float], list[float]]:
    all_sp: list[float] = []
    all_ang: list[float] = []
    if isinstance(geom, Polygon):
        s, a = _ring_vertex_stats(list(geom.exterior.coords))
        all_sp.extend(s)
        all_ang.extend(a)
    elif isinstance(geom, MultiPolygon):
        for p in geom.geoms:
            s, a = _ring_vertex_stats(list(p.exterior.coords))
            all_sp.extend(s)
            all_ang.extend(a)
    return all_sp, all_ang


def characterize_polygons(geoms: list, label: str) -> None:
    all_sp: list[float] = []
    all_ang: list[float] = []
    for g in geoms:
        s, a = polygon_vertex_stats(g)
        all_sp.extend(s)
        all_ang.extend(a)

    if not all_sp:
        print(f"  {label} : aucune donnée")
        return

    print(f"  {label} ({len(geoms)} polygones, {len(all_sp)} segments) :")
    print(f"    espacement (m) : med={np.median(all_sp):.2f}  p25={np.percentile(all_sp,25):.2f}"
          f"  p75={np.percentile(all_sp,75):.2f}  p90={np.percentile(all_sp,90):.2f}")
    ang_deg = [math.degrees(a) for a in all_ang]
    print(f"    deviation (°)  : med={np.median(ang_deg):.1f}  p75={np.percentile(ang_deg,75):.1f}"
          f"  p90={np.percentile(ang_deg,90):.1f}  p95={np.percentile(ang_deg,95):.1f}")
    print(f"    segments > 5m : {sum(1 for s in all_sp if s > 5)/len(all_sp)*100:.1f}%  "
          f"  segments > 10m : {sum(1 for s in all_sp if s > 10)/len(all_sp)*100:.1f}%")


def load_ffco_406() -> list:
    ds = ogr.Open(str(FFCO_GPKG))
    if ds is None:
        return []
    lyr = ds.GetLayer("grimbosq_areas")
    geoms = []
    lyr.ResetReading()
    for feat in lyr:
        raw = feat.GetField("Name") or ""
        try:
            raw = raw.encode("utf-16", "surrogatepass").decode("utf-16")
        except Exception:
            pass
        if "course lente" not in raw:
            continue
        if "bonne" in raw:  # exclure 407
            continue
        g = feat.GetGeometryRef()
        if g is None:
            continue
        try:
            s = shape(json.loads(g.ExportToJson()))
            if not s.is_valid:
                s = s.buffer(0)
            geoms.append(s)
        except Exception:
            pass
    return geoms


def chaikin_sweep(cfg_base: dict) -> None:
    print()
    print("=== Sweep chaikin_passes ===")
    hdr = f"  {'passes':>6} | {'n_406':>6} | {'cpt_med':>8} | {'%<0.3':>7} | {'cpt_sw':>7}"
    print(hdr)
    print("  " + "-" * 45)

    for passes in [1, 2, 3, 5]:
        cfg = copy.deepcopy(cfg_base)
        prof = cfg["generalization"]["profiles"][cfg["generalization"]["active_profile"]]
        prof["chaikin_passes"] = passes
        gdf, _ = run_pipeline(str(CLASSIFIED), cfg)
        sub = gdf[gdf["class"] == 406]
        cpt = sub.geometry.apply(compactness)
        areas = sub.geometry.area
        sw = (cpt * areas).sum() / areas.sum()
        print(f"  {passes:>6} | {len(sub):>6} | {float(np.median(cpt)):>8.3f} | "
              f"{float((cpt < 0.3).mean() * 100):>7.1f} | {float(sw):>7.3f}")


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")

    cfg_base = load_config()

    # Run baseline (passes=1, sans chirurgie)
    print("Running pipeline baseline (chaikin×1)...", flush=True)
    gdf, _ = run_pipeline(str(CLASSIFIED), cfg_base)

    gdf406 = gdf[gdf["class"] == 406].copy().reset_index(drop=True)
    cpt_all = gdf406.geometry.apply(compactness)
    esa_all = gdf406.geometry.apply(ext_sqrt_a)

    # Polygones mauvais hors isthmes (le vrai problème de contour)
    bad_non_isthme = gdf406[(cpt_all < 0.3) & (esa_all <= 15)].geometry.tolist()
    good = gdf406[cpt_all >= 0.5].geometry.tolist()
    all406 = gdf406.geometry.tolist()

    print(f"\n  Total 406 : {len(all406)} | bad non-isthme (cpt<0.3, esa<=15) : {len(bad_non_isthme)}")
    print()

    print("=== Fréquence spatiale des contours ===")
    characterize_polygons(bad_non_isthme, "pipeline 406 (cpt<0.3, non-isthme)")
    characterize_polygons(good[:200], "pipeline 406 (cpt>=0.5, 200 premiers)")

    print()
    ffco406 = load_ffco_406()
    print(f"  FFCO 406 chargé : {len(ffco406)} polygones")
    characterize_polygons(ffco406, "FFCO 406 reference")

    # Sweep Chaikin
    chaikin_sweep(cfg_base)


if __name__ == "__main__":
    main()
