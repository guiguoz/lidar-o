"""Trois mesures sur Grimbosq — sans avis extérieur.

1. TP/FP/FN surface : ce que le pipeline trouve correctement, ajoute en trop, manque
2. Carte d'erreur spatialement résolue : grille 100m, delta couverture par cellule
3. Test parcellaire : fraction des contours FFCO rectilignes (>50m) et alignés sur routes BD TOPO

Usage :
    python scripts/diag/measure_parcellaire.py
"""
import pathlib, json, math, warnings
import matplotlib
matplotlib.use("Agg")
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import shapely.geometry as sg
from shapely.ops import unary_union
from osgeo import ogr

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).parent.parent.parent
OUTPUT = ROOT / "output"

FFCO_VEG = {"course lente": 406, "marche": 408, "progression": 410}


# ── chargement ─────────────────────────────────────────────────────────────────

def load_ffco_geoms() -> tuple[list, dict[int, list]]:
    ds = ogr.Open(str(ROOT / "grimbosq.gpkg"))
    lyr = ds.GetLayerByName("grimbosq_areas")
    lyr.ResetReading()
    by_class: dict[int, list] = {406: [], 408: [], 410: []}
    for feat in lyr:
        name = feat.GetField("Name") or ""
        low = name.lower()
        cls = next((c for kw, c in FFCO_VEG.items() if kw in low), None)
        if cls is None:
            continue
        g = feat.GetGeometryRef()
        if g is None:
            continue
        try:
            shp = sg.shape(json.loads(g.ExportToJson()))
            if shp.is_valid and not shp.is_empty:
                by_class[cls].append(shp)
        except Exception:
            pass
    all_geoms = [g for gs in by_class.values() for g in gs]
    return all_geoms, by_class


def load_pipeline_geoms() -> tuple[list, dict[int, list]]:
    by_class: dict[int, list] = {}
    for cls, layer in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        gdf = gpd.read_file(str(OUTPUT / "vegetation_masked.gpkg"), layer=layer)
        by_class[cls] = list(gdf.geometry)
    all_geoms = [g for gs in by_class.values() for g in gs]
    return all_geoms, by_class


# ── mesure 1 : TP / FP / FN ───────────────────────────────────────────────────

def measure_tp_fp_fn(
    ffco_all: list, pipeline_all: list
) -> None:
    print("\n=== MESURE 1 — TP / FP / FN (surface) ===")
    ffco_u = unary_union(ffco_all)
    pipe_u = unary_union(pipeline_all)
    hull = ffco_u.convex_hull  # référence = emprise FFCO

    ffco_clip = ffco_u.intersection(hull)
    pipe_clip = pipe_u.intersection(hull)

    tp = ffco_clip.intersection(pipe_clip).area
    fp = pipe_clip.difference(ffco_clip).area
    fn = ffco_clip.difference(pipe_clip).area
    hull_area = hull.area
    ffco_area = ffco_clip.area

    print(f"Emprise FFCO (hull) : {hull_area/10000:.1f} ha")
    print(f"Surface FFCO        : {ffco_area/10000:.1f} ha  ({ffco_area/hull_area:.0%} du hull)")
    print()
    print(f"TP (pipeline correct) : {tp/10000:.1f} ha  = {tp/ffco_area:.0%} de la FFCO")
    print(f"FP (à effacer)        : {fp/10000:.1f} ha  = {fp/ffco_area:.0%} de la FFCO")
    print(f"FN (à dessiner)       : {fn/10000:.1f} ha  = {fn/ffco_area:.0%} de la FFCO")
    print()
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    print(f"Recall    (TP/FFCO)    : {recall:.0%}  — fraction FFCO couverte")
    print(f"Precision (TP/pipeline): {precision:.0%}  — fraction pipeline correcte")
    print()
    print(f"Gain cartographe : sur {ffco_area/10000:.1f} ha à cartographier,")
    print(f"  {tp/10000:.1f} ha déjà placés (rien à faire),")
    print(f"  {fp/10000:.1f} ha à effacer (rapide),")
    print(f"  {fn/10000:.1f} ha à tracer depuis zéro (lent).")

    return ffco_u, pipe_u, hull


# ── mesure 2 : carte d'erreur 100m ────────────────────────────────────────────

def measure_error_map(ffco_u, pipe_u, hull: sg.Polygon) -> None:
    print("\n=== MESURE 2 — Carte d'erreur spatialement résolue (grille 100m) ===")
    minx, miny, maxx, maxy = hull.bounds
    CELL = 100.0

    xs = np.arange(minx, maxx, CELL)
    ys = np.arange(miny, maxy, CELL)
    W, H = len(xs), len(ys)
    grid = np.full((H, W), np.nan)

    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            cell = sg.box(x, y, x + CELL, y + CELL)
            cell_in = cell.intersection(hull)
            if cell_in.is_empty or cell_in.area < 100:
                continue
            cov_ffco = ffco_u.intersection(cell_in).area / cell_in.area
            cov_pipe = pipe_u.intersection(cell_in).area / cell_in.area
            grid[iy, ix] = cov_pipe - cov_ffco

    valid = grid[~np.isnan(grid)]
    n_cells = len(valid)
    n_over = (valid > 0.1).sum()
    n_under = (valid < -0.1).sum()
    n_ok = ((valid >= -0.1) & (valid <= 0.1)).sum()
    print(f"Cellules valides : {n_cells}")
    print(f"Sur-détection  (delta > +10%) : {n_over}  ({n_over/n_cells:.0%})")
    print(f"Sous-détection (delta < -10%) : {n_under}  ({n_under/n_cells:.0%})")
    print(f"Accord         (delta ± 10%)  : {n_ok}  ({n_ok/n_cells:.0%})")
    print(f"Delta moyen : {valid.mean():+.3f}  |  écart-type : {valid.std():.3f}")

    fig, ax = plt.subplots(figsize=(8, 8), facecolor="white")
    vmax = 0.6
    extent = [minx, maxx, miny, maxy]
    im = ax.imshow(
        grid, origin="lower", extent=extent,
        cmap="RdBu_r", vmin=-vmax, vmax=vmax,
        interpolation="nearest"
    )
    plt.colorbar(im, ax=ax, label="Delta couverture (pipeline − FFCO)", shrink=0.7)
    ax.set_title("Carte d'erreur — grille 100m\nbleu=sous-détection pipeline  rouge=sur-détection", fontsize=10)
    ax.set_aspect("equal")
    ax.set_xlabel("X (EPSG:2154)")
    ax.set_ylabel("Y (EPSG:2154)")

    out = OUTPUT / "error_map_100m.png"
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Carte sauvegardée : {out}")


# ── mesure 3 : test parcellaire ───────────────────────────────────────────────

def _rectilinear_fraction(geom: sg.Polygon | sg.MultiPolygon, min_len_m: float = 50.0) -> tuple[float, float, float]:
    """Fraction du périmètre extérieur composée de segments unitaires ≥ min_len_m.

    Dans OOM, les arêtes droites sont encodées comme un seul long segment entre deux sommets ;
    les courbes comme une succession de courts segments (~4-6m). Un segment unique > 50m est
    donc un indicateur direct d'arête rectiligne intentionnelle.

    Retourne (frac_rectiligne, perimetre_total, longueur_rectiligne).
    """
    rings = []
    if geom.geom_type == "Polygon":
        rings = [geom.exterior]
    elif geom.geom_type == "MultiPolygon":
        rings = [p.exterior for p in geom.geoms]

    total_len = 0.0
    rectilinear_len = 0.0

    for ring in rings:
        coords = list(ring.coords)
        n = len(coords) - 1
        for i in range(n):
            dx = coords[i+1][0] - coords[i][0]
            dy = coords[i+1][1] - coords[i][1]
            seg = math.hypot(dx, dy)
            total_len += seg
            if seg >= min_len_m:
                rectilinear_len += seg

    frac = rectilinear_len / total_len if total_len > 0 else 0.0
    return frac, total_len, rectilinear_len


def measure_parcellaire(ffco_by_class: dict[int, list]) -> None:
    print("\n=== MESURE 3 — Test parcellaire ===")

    # 3a : segments rectilignes > 50m
    all_ffco = [g for gs in ffco_by_class.values() for g in gs]
    results = [_rectilinear_fraction(g) for g in all_ffco]
    frac_arr = np.array([r[0] for r in results])
    len_total = sum(r[1] for r in results)
    len_rect  = sum(r[2] for r in results)
    frac_weighted = len_rect / len_total if len_total > 0 else 0.0

    # Distribution des segments
    all_segs = []
    for g in all_ffco:
        rings = [g.exterior] if g.geom_type == "Polygon" else [p.exterior for p in g.geoms]
        for ring in rings:
            coords = list(ring.coords)
            for i in range(len(coords)-1):
                dx = coords[i+1][0] - coords[i][0]
                dy = coords[i+1][1] - coords[i][1]
                all_segs.append(math.hypot(dx, dy))
    all_segs = np.array(all_segs)
    print(f"Distribution segments FFCO : median={np.median(all_segs):.1f}m  mean={np.mean(all_segs):.1f}m  max={np.max(all_segs):.0f}m")
    print(f"  >50m : {(all_segs>50).sum()} segments / {len(all_segs)} total  ({(all_segs>50).mean():.1%})")
    print(f"  >100m: {(all_segs>100).sum()} segments")
    print()
    print(f"Segments rectilignes > 50m (mediane par polygone) : {np.median(frac_arr):.0%}")
    print(f"Segments rectilignes > 50m (pondere perimetre)    : {frac_weighted:.0%} du perimetre total FFCO")

    # 3b : proximite routes BD TOPO
    routes = gpd.read_file(str(ROOT / "data" / "grimbosq_bdtopo.gpkg"), layer="troncon_de_route")
    import shapely
    routes_2d = routes.copy()
    routes_2d["geometry"] = routes_2d.geometry.apply(
        lambda g: shapely.force_2d(g) if g is not None else g
    )
    road_union = unary_union(list(routes_2d.geometry.dropna()))
    road_buf = road_union.buffer(8.0)  # 8m = largeur layon + tolérance GPS

    # densifier les contours FFCO et tester la proximite
    from shapely.ops import substring
    from shapely import line_interpolate_point

    boundary_union = unary_union(
        [g.exterior for g in all_ffco if g.geom_type == "Polygon"] +
        [p.exterior for g in all_ffco if g.geom_type == "MultiPolygon" for p in g.geoms]
    )
    # Discrétiser à 5m
    total_b = boundary_union.length
    n_pts = int(total_b / 5) + 1
    pts = [line_interpolate_point(boundary_union, d / n_pts, normalized=True)
           for d in range(n_pts)]
    pts_in_buf = sum(1 for p in pts if road_buf.contains(p))
    pct_road = pts_in_buf / len(pts)
    print(f"Contour FFCO a moins de 8m d'une route BD TOPO : {pct_road:.0%}")
    print(f"(sur {len(pts)} points a 5m)")
    print()
    if frac_weighted > 0.4 and pct_road > 0.3:
        print("Hypothese parcellaire : CONFIRMEE —")
        print(f"  {frac_weighted:.0%} du contour est rectiligne ET {pct_road:.0%} suit les routes.")
    elif frac_weighted > 0.4:
        print(f"Hypothese partielle : contours rectilignes ({frac_weighted:.0%}) mais peu alignes sur routes ({pct_road:.0%}).")
        print("  Le tracé suit peut-etre un autre type de limite (parcellaire cadastral, bande pare-feu).")
    else:
        print(f"Hypothese parcellaire faible : rectiligne={frac_weighted:.0%}, routes={pct_road:.0%}.")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Chargement FFCO...")
    ffco_all, ffco_by_class = load_ffco_geoms()
    print(f"  406:{len(ffco_by_class[406])}  408:{len(ffco_by_class[408])}  410:{len(ffco_by_class[410])}")

    print("Chargement pipeline...")
    pipeline_all, _ = load_pipeline_geoms()

    ffco_u, pipe_u, hull = measure_tp_fp_fn(ffco_all, pipeline_all)

    print("\nCarte d'erreur (peut prendre 1-2 min)...")
    measure_error_map(ffco_u, pipe_u, hull)

    print("\nTest parcellaire...")
    measure_parcellaire(ffco_by_class)


if __name__ == "__main__":
    main()
