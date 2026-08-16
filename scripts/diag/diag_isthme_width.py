"""Diagnostic : largeur des goulots + correspondance FFCO.

Pour les N polygones 406 avec ext/sqrt(A) > 15 :
  1. Largeur du goulot : binary search sur erosion negative
  2. Correspondance FFCO : combien de patches FFCO 406 sont contenus dans chaque polygone ?

Usage :
    python scripts/diag_isthme_width.py
"""
from __future__ import annotations

import copy
import math
import pathlib
import sys

import numpy as np
import yaml
from osgeo import ogr
from shapely.geometry import shape, MultiPolygon, Polygon
from shapely.strtree import STRtree

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
from src.vegetation import run_pipeline

ROOT = pathlib.Path(".")
CLASSIFIED = ROOT / "output" / "density_hag_classified.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"
FFCO_406_NAME = "V\udce9g\udce9tation, course lente"

EXT_SQRT_A_THRESHOLD = 15


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8", errors="replace") as f:
        return yaml.safe_load(f)


def _ext_perimeter(geom) -> float:
    if isinstance(geom, Polygon):
        return geom.exterior.length
    elif isinstance(geom, MultiPolygon):
        return sum(p.exterior.length for p in geom.geoms)
    return geom.length


def _ext_sqrt_a(geom) -> float:
    a = geom.area
    if a <= 0:
        return 0.0
    return _ext_perimeter(geom) / math.sqrt(a)


def find_bottleneck_width(geom, w_min: float = 0.5, w_max: float = 30.0, n_iter: int = 18) -> float:
    """
    Binary search pour la largeur minimale de corridor.
    Erose par d, observe si le polygone se fragmente.
    Retourne ~2*d_critique = largeur du goulot.
    """
    lo, hi = w_min / 2, w_max / 2
    for _ in range(n_iter):
        mid = (lo + hi) / 2
        eroded = geom.buffer(-mid)
        if eroded.is_empty:
            hi = mid
            continue
        n_parts = len(eroded.geoms) if hasattr(eroded, "geoms") else 1
        if n_parts > 1:
            hi = mid
        else:
            lo = mid
    return hi * 2  # largeur du goulot ≈ 2 * distance critique


def load_ffco_406() -> list:
    """Charge les geometries FFCO 406+407 depuis grimbosq.gpkg via OGR.

    Inclut 406 (course lente) et 407 (course lente bonne visibilite) — les deux
    contiennent la chaine 'course lente' dans le champ Name.
    """
    import json as _json
    ds = ogr.Open(str(FFCO_GPKG))
    if ds is None:
        raise FileNotFoundError(f"FFCO absent : {FFCO_GPKG}")
    lyr = ds.GetLayer("grimbosq_areas")
    geoms = []
    lyr.ResetReading()
    for feat in lyr:
        raw = feat.GetField("Name") or ""
        try:
            raw = raw.encode("utf-16", "surrogatepass").decode("utf-16")
        except Exception:
            pass
        if "course lente" in raw:
            g = feat.GetGeometryRef()
            if g is None:
                continue
            try:
                s = shape(_json.loads(g.ExportToJson()))
                if not s.is_valid:
                    s = s.buffer(0)
                geoms.append(s)
            except Exception:
                pass
    return geoms


def main() -> None:
    if not CLASSIFIED.exists():
        sys.exit(f"ABSENT : {CLASSIFIED}")
    if not FFCO_GPKG.exists():
        sys.exit(f"ABSENT : {FFCO_GPKG}")

    cfg = load_config()
    gdf_all, _ = run_pipeline(str(CLASSIFIED), cfg)
    gdf406 = gdf_all[gdf_all["class"] == 406].copy().reset_index(drop=True)

    esa = gdf406.geometry.apply(_ext_sqrt_a)
    mask_isthme = esa > EXT_SQRT_A_THRESHOLD
    isthme_geoms = gdf406[mask_isthme].geometry
    n_isthme = mask_isthme.sum()
    total_ha = gdf406.geometry.area.sum() / 1e4
    isthme_ha = isthme_geoms.area.sum() / 1e4

    print(f"Polygones 406 total : {len(gdf406)} | {total_ha:.2f} ha")
    print(f"Polygones ext/sqrtA > {EXT_SQRT_A_THRESHOLD} : {n_isthme} | {isthme_ha:.2f} ha ({isthme_ha/total_ha*100:.1f}%)")
    print()

    # ── Mesure 1 : largeur des goulots ──────────────────────────────────────────
    print("=== Largeur des goulots (binary search sur erosion) ===")
    print(f"  {'rank':>4} | {'ha':>6} | {'ext/sqA':>7} | {'goulot_m':>9}")
    print("  " + "-" * 38)

    widths = []
    ranks = gdf406[mask_isthme].index.tolist()
    sorted_idx = isthme_geoms.area.sort_values(ascending=False).index

    for rank, idx in enumerate(sorted_idx, 1):
        geom = gdf406.loc[idx, "geometry"]
        ha = geom.area / 1e4
        esa_val = _ext_sqrt_a(geom)
        w = find_bottleneck_width(geom)
        widths.append(w)
        print(f"  {rank:>4} | {ha:>6.2f} | {esa_val:>7.1f} | {w:>9.2f}")

    if widths:
        print()
        print(f"  Distribution largeurs (m) :")
        print(f"    min={min(widths):.1f}  p25={np.percentile(widths,25):.1f}  "
              f"med={np.median(widths):.1f}  p75={np.percentile(widths,75):.1f}  max={max(widths):.1f}")
        print(f"    sous 2m : {sum(w < 2 for w in widths)} / {len(widths)}")
        print(f"    sous 3m : {sum(w < 3 for w in widths)} / {len(widths)}")
        print(f"    sous 5m : {sum(w < 5 for w in widths)} / {len(widths)}")

    # ── Mesure 2 : correspondance FFCO ──────────────────────────────────────────
    print()
    print("=== Correspondance FFCO 406 ===")
    print("  (nb patches FFCO 'course lente' contenus dans chaque polygone pipeline)")
    print()

    ffco_geoms = load_ffco_406()
    print(f"  FFCO 406 charge : {len(ffco_geoms)} polygones")

    tree = STRtree(ffco_geoms)

    print(f"  {'rank':>4} | {'ha':>6} | {'goulot_m':>9} | {'n_ffco':>7} | {'ffco_ha':>8} | verdict")
    print("  " + "-" * 65)

    for rank, (idx, w) in enumerate(zip(sorted_idx, widths), 1):
        geom = gdf406.loc[idx, "geometry"]
        ha = geom.area / 1e4
        candidates = tree.query(geom, predicate="intersects")
        n_ffco = 0
        ffco_ha = 0.0
        for ci in candidates:
            inter = geom.intersection(ffco_geoms[ci])
            if inter.area > 10:  # > 10 m2 = intersection significative
                n_ffco += 1
                ffco_ha += ffco_geoms[ci].area / 1e4

        if n_ffco == 0:
            verdict = "hors FFCO 406 (autre classe?)"
        elif n_ffco == 1:
            verdict = "1 masse FFCO -> ne pas couper"
        else:
            verdict = f"{n_ffco} patches FFCO -> couper correct"

        print(f"  {rank:>4} | {ha:>6.2f} | {w:>9.2f} | {n_ffco:>7} | {ffco_ha:>8.2f} | {verdict}")


if __name__ == "__main__":
    main()
