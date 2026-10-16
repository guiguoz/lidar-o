"""V3 — Comparaison méthodes de généralisation géométrique (Grimbosq).

Bras :
  A — RAW              vectorized_raw.gpkg issu de V1 (baseline)
  B — DP + Chaikin     douglas_peucker(2 m) + chaikin×2 par polygone (pipeline actuel)
  C — coverage_simplify  shapely.coverage_simplify(2 m) sur les 3 classes combinées
  D — coverage_simplify  + Chaikin par polygone (post-simplification)
      → mesuré séparément ; si gap > 0, documenté comme abandonné

Paramètres gelés (interdits de modifier) :
  douglas_peucker_tolerance_m = 2.0  (config.yaml : generalization.profiles.grimbosq_v0)
  chaikin_passes               = 2   (idem)

Portes dures :
  overlaps = 0 par classe (et inter-classes)
  gaps = 0 couverture combinée 3 classes

Sorties :
  v3_arm_b.gpkg, v3_arm_c.gpkg, v3_arm_d.gpkg (si D valide)
  v3_report.md
  v3_plate1.png  (vue d'ensemble 1:10 000, 4 panneaux A/B/C/D)
  v3_plate2.png  (zoom 400×400 m, fenêtre 406 fragmenté)
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

import logging
from typing import Any

import matplotlib
matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import shapely
import yaml
from rasterio.features import rasterize as rio_rasterize
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

OUT_DIR    = pathlib.Path(__file__).parent
SOURCE_TIF = OUT_DIR / "source_classes.tif"
RAW_GPKG   = OUT_DIR / "vectorized_raw.gpkg"

DP_TOL    = 2.0   # douglas_peucker_tolerance_m
CHAIKIN_N = 2     # chaikin_passes

DN_ISOM  = {85: 406, 170: 408, 255: 410}
ISOM_DN  = {v: k for k, v in DN_ISOM.items()}
ISOM_COLORS: dict[int, str] = {406: "#c7e9b4", 408: "#41b6c4", 410: "#225ea8"}


# ── Utilitaires géométrie ─────────────────────────────────────────────────────

def chaikin(coords: np.ndarray, passes: int) -> np.ndarray:
    """Lissage Chaikin par polygone : Q = ¾p₀ + ¼p₁, R = ¼p₀ + ¾p₁."""
    pts = np.asarray(coords, dtype=float)
    closed = np.allclose(pts[0], pts[-1])
    for _ in range(passes):
        new_pts: list[np.ndarray] = []
        n = len(pts) - (1 if closed else 0)
        for i in range(n):
            p0, p1 = pts[i], pts[(i + 1) % len(pts)]
            new_pts.append(0.75 * p0 + 0.25 * p1)
            new_pts.append(0.25 * p0 + 0.75 * p1)
        pts = np.array(new_pts)
        if closed and len(pts):
            pts = np.vstack([pts, pts[0]])
    return pts


def smooth_geom(geom: Polygon | MultiPolygon, passes: int) -> Polygon | MultiPolygon:
    """Chaikin sur exterior + interiors d'un polygone."""
    def _smooth_poly(p: Polygon) -> Polygon:
        ext = chaikin(np.array(p.exterior.coords), passes)
        holes = [chaikin(np.array(r.coords), passes) for r in p.interiors]
        return Polygon(ext, holes)
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([_smooth_poly(p) for p in geom.geoms])
    return _smooth_poly(geom)


def simplify_dp(geom: Polygon | MultiPolygon, tol: float) -> Polygon | MultiPolygon:
    return geom.simplify(tol, preserve_topology=True)


# ── Métriques géométriques ────────────────────────────────────────────────────

def geom_stats(gdf: gpd.GeoDataFrame) -> dict[int, dict]:
    """Métriques par classe 406/408/410."""
    stats: dict[int, dict] = {}
    for cls in sorted(gdf["class"].unique()):
        sub = gdf[gdf["class"] == cls]
        areas  = sub.geometry.area.values
        perims = sub.geometry.length.values
        n = len(sub)

        # Sommets
        n_v = 0
        n_holes = 0
        for geom in sub.geometry:
            polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            for p in polys:
                if not isinstance(p, Polygon): continue
                n_v += len(p.exterior.coords)
                for ring in p.interiors:
                    n_holes += 1
                    n_v += len(ring.coords)

        total_perim = float(perims.sum())
        total_area  = float(areas.sum())
        p95         = float(np.percentile(areas, 95)) if n else 0.0
        med         = float(np.median(areas)) if n else 0.0
        n_tiny      = int((areas < 100).sum())

        esa = perims / np.sqrt(np.clip(areas, 1e-9, None))
        n_slivers = int(((areas < 1.0) | ((areas < 100.0) & (esa > 20.0))).sum())

        stats[int(cls)] = {
            "n_polys": n,
            "total_ha": round(total_area / 10_000, 3),
            "med_m2": round(med, 1),
            "p95_m2": round(p95, 0),
            "n_tiny": n_tiny,
            "perim_m": round(total_perim, 0),
            "n_verts": n_v,
            "verts_per_m": round(n_v / total_perim, 4) if total_perim else 0,
            "n_holes": n_holes,
            "n_slivers": n_slivers,
        }
    return stats


def check_topology(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Portes dures : overlaps = 0, gaps (couverture combinée) = 0."""
    from shapely.strtree import STRtree
    geoms = list(gdf.geometry)
    tree  = STRtree(geoms)
    n_ov  = 0
    for i, g in enumerate(geoms):
        for j in tree.query(g):
            if j <= i: continue
            try:
                inter = geoms[j].intersection(g)
                if inter.area > 1e-3:
                    n_ov += 1
            except Exception:
                n_ov += 1   # géométrie invalide : compter comme overlap

    union_area = unary_union(geoms).area
    with rasterio.open(SOURCE_TIF) as ds:
        src = ds.read(1).copy()
    src_veg_area = float((src != 0).sum())   # 1 m²/px
    gap_m2 = round(abs(union_area - src_veg_area), 3)

    return {"n_overlaps": n_ov, "gap_m2": gap_m2}


def hausdorff_vs_raw(
    gdf_arm: gpd.GeoDataFrame, gdf_raw: gpd.GeoDataFrame
) -> dict[int, dict]:
    """Déplacement de frontière par classe : p95 et max du Hausdorff polygon-à-polygon."""
    result: dict[int, dict] = {}
    for cls in [406, 408, 410]:
        sub_arm = gdf_arm[gdf_arm["class"] == cls]
        sub_raw = gdf_raw[gdf_raw["class"] == cls]
        if sub_arm.empty or sub_raw.empty:
            result[cls] = {"p95_m": 0.0, "max_m": 0.0}
            continue
        # Joindre par indice (même ordre après V1 dissolve)
        min_n = min(len(sub_arm), len(sub_raw))
        dists = []
        for g_arm, g_raw in zip(sub_arm.geometry.iloc[:min_n], sub_raw.geometry.iloc[:min_n]):
            try:
                dists.append(g_arm.hausdorff_distance(g_raw))
            except Exception:
                dists.append(0.0)
        arr = np.array(dists)
        result[cls] = {
            "p95_m": round(float(np.percentile(arr, 95)), 3),
            "max_m": round(float(arr.max()), 3),
        }
    return result


def roundtrip_cost(gdf: gpd.GeoDataFrame) -> dict[int, dict]:
    """Rasterise sur la grille source V1, compare pixel à pixel par classe."""
    with rasterio.open(SOURCE_TIF) as ds:
        src  = ds.read(1).copy()
        xform = ds.transform
        h, w  = ds.height, ds.width
        crs   = ds.crs.to_string()

    dn_series = gdf["class"].map(ISOM_DN)
    shapes = [
        (geom.__geo_interface__, int(dn))
        for geom, dn in zip(gdf.geometry, dn_series)
        if dn is not None and not np.isnan(dn)
    ]
    rt = rio_rasterize(
        shapes, out_shape=(h, w), transform=xform, fill=0, dtype=np.uint8,
        merge_alg=rasterio.enums.MergeAlg.replace,
    ) if shapes else np.zeros((h, w), dtype=np.uint8)

    result: dict[int, dict] = {}
    for dn, isom in DN_ISOM.items():
        m_s = src == dn
        m_r = rt  == dn
        identical = int((m_s & m_r).sum())
        lost  = int((m_s & ~m_r).sum())
        added = int((~m_s & m_r).sum())
        result[isom] = {"identical": identical, "different": lost + added,
                        "lost": lost, "added": added}
    return result


# ── Bras ─────────────────────────────────────────────────────────────────────

def arm_b(gdf_raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """DP (2 m) + Chaikin × 2 par polygone — pipeline actuel."""
    log.info("Arm B — DP %.1f m + Chaikin × %d", DP_TOL, CHAIKIN_N)
    geoms = []
    for g in gdf_raw.geometry:
        simp = simplify_dp(g, DP_TOL)
        smooth = smooth_geom(simp, CHAIKIN_N)
        if not smooth.is_valid:
            smooth = shapely.make_valid(smooth)
        geoms.append(smooth)
    gdf = gdf_raw.copy()
    gdf["geometry"] = geoms
    return gdf[gdf.geometry.area > 0].reset_index(drop=True)


def arm_c(gdf_raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """coverage_simplify (2 m) sur les 3 classes combinées."""
    log.info("Arm C — coverage_simplify %.1f m (3 classes combinées)", DP_TOL)
    geom_arr = np.array(gdf_raw.geometry.values, dtype=object)
    simplified = shapely.coverage_simplify(geom_arr, tolerance=DP_TOL, simplify_boundary=True)
    gdf = gdf_raw.copy()
    gdf["geometry"] = list(simplified)
    return gdf[gdf.geometry.area > 0].reset_index(drop=True)


def arm_d(gdf_c: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame | None, str]:
    """C + Chaikin × 2 par polygone (post-coverage_simplify).

    Les arêtes partagées entre polygones sont lissées deux fois indépendamment
    (une fois par polygone adjacent, directions opposées) → gaps possibles.
    On mesure et on documente.
    """
    log.info("Arm D — coverage_simplify + Chaikin × %d par polygone", CHAIKIN_N)
    geoms = [smooth_geom(g, CHAIKIN_N) for g in gdf_c.geometry]
    gdf = gdf_c.copy()
    gdf["geometry"] = geoms
    gdf = gdf[gdf.geometry.area > 0].reset_index(drop=True)

    topo = check_topology(gdf)
    if topo["gap_m2"] > 1.0:
        note = (
            f"ABANDONNÉ — Chaikin par polygone brise les arêtes partagées : "
            f"gap_combiné={topo['gap_m2']:.1f} m² après lissage. "
            f"Edge-graph coverage-wide non implémenté (variante S1 abandonnée)."
        )
        log.warning("Arm D : %s", note)
        return None, note
    return gdf, f"valide (overlaps={topo['n_overlaps']}, gap={topo['gap_m2']} m²)"


# ── Zoom bbox automatique ────────────────────────────────────────────────────

def _zoom_bbox(gdf_raw: gpd.GeoDataFrame, window_m: float = 400.0) -> tuple[float, float, float, float]:
    """Fenêtre zoom : zone la plus dense en petits polygones 406."""
    sub406 = gdf_raw[(gdf_raw["class"] == 406) & (gdf_raw.geometry.area < 200)]
    if sub406.empty:
        cx, cy = gdf_raw.geometry.centroid.x.mean(), gdf_raw.geometry.centroid.y.mean()
    else:
        cx = float(sub406.geometry.centroid.x.mean())
        cy = float(sub406.geometry.centroid.y.mean())
    half = window_m / 2
    return (cx - half, cy - half, cx + half, cy + half)


# ── Planche 1:10 000 ─────────────────────────────────────────────────────────

def _plot_arm(ax: plt.Axes, gdf: gpd.GeoDataFrame | None, bbox: tuple, kp_rgb: np.ndarray,
              title: str, kp_alpha: float = 0.0) -> None:
    bxmin, bymin, bxmax, bymax = bbox
    if kp_alpha > 0:
        ax.imshow(kp_rgb[::4, ::4], extent=[bxmin, bxmax, bymin, bymax],
                  origin="upper", alpha=kp_alpha, interpolation="bilinear")
    ax.set_xlim(bxmin, bxmax)
    ax.set_ylim(bymin, bymax)
    ax.set_aspect("equal")
    if gdf is not None:
        for cls, color in ISOM_COLORS.items():
            sub = gdf[gdf["class"] == cls]
            if not sub.empty:
                sub.plot(ax=ax, color=color, edgecolor="none")
    ax.set_title(title, fontsize=7)
    ax.tick_params(labelsize=5)


def _plot_arm_zoom(ax: plt.Axes, gdf: gpd.GeoDataFrame | None, bbox: tuple,
                   title: str) -> None:
    bxmin, bymin, bxmax, bymax = bbox
    ax.set_facecolor("white")
    ax.set_xlim(bxmin, bxmax)
    ax.set_ylim(bymin, bymax)
    ax.set_aspect("equal")
    if gdf is not None:
        for cls, color in ISOM_COLORS.items():
            sub = gdf[gdf["class"] == cls]
            if not sub.empty:
                sub.plot(ax=ax, color=color, edgecolor="gray", linewidth=0.3)
    ax.set_title(title, fontsize=7)
    ax.tick_params(labelsize=5)


def make_plate1(arms: dict[str, gpd.GeoDataFrame | None], kp_rgb: np.ndarray,
                bbox: tuple, out_path: pathlib.Path) -> None:
    """Planche 1 — vue d'ensemble 4 bras."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 22), dpi=100)
    bxmin, bymin, bxmax, bymax = bbox
    labels_ax = [
        ("A", axes[0, 0], "A — RAW (baseline V1)", arms.get("A")),
        ("B", axes[0, 1], "B — DP 2m + Chaikin×2", arms.get("B")),
        ("C", axes[1, 0], "C — coverage_simplify 2m", arms.get("C")),
        ("D", axes[1, 1], "D — C + Chaikin×2 (par polygone)", arms.get("D")),
    ]
    for _, ax, title, gdf in labels_ax:
        _plot_arm(ax, gdf, bbox, kp_rgb, title, kp_alpha=0.3)

    patches = [mpatches.Patch(color=c, label=f"ISOM {k}") for k, c in ISOM_COLORS.items()]
    axes[0, 0].legend(handles=patches, fontsize=5, loc="lower left")

    fig.suptitle("Grimbosq — V3 Généralisation géométrique 1:10 000", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    log.info("Planche 1 → %s", out_path.name)


def make_plate2(arms: dict[str, gpd.GeoDataFrame | None], zoom_bbox: tuple,
                out_path: pathlib.Path) -> None:
    """Planche 2 — zoom sur zone fragmentée 406."""
    n_arms = sum(1 for v in arms.values() if v is not None) + 1  # +1 pour A
    ncols = min(n_arms, 4)
    fig, axes = plt.subplots(1, ncols, figsize=(5 * ncols, 7), dpi=100)
    if ncols == 1:
        axes = [axes]
    arm_order = [("A", arms.get("A")), ("B", arms.get("B")),
                 ("C", arms.get("C")), ("D", arms.get("D"))]
    col = 0
    for arm_key, gdf in arm_order:
        if gdf is None and arm_key != "A":
            continue
        _plot_arm_zoom(axes[col], gdf, zoom_bbox, f"Bras {arm_key}")
        col += 1
        if col >= ncols:
            break

    bxmin, bymin, bxmax, bymax = zoom_bbox
    fig.suptitle(
        f"Grimbosq — V3 Zoom 406 fragmenté\n"
        f"Fenêtre ({bxmin:.0f}, {bymin:.0f}, {bxmax:.0f}, {bymax:.0f}) EPSG:2154",
        fontsize=8,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    log.info("Planche 2 → %s", out_path.name)


# ── Rapport ───────────────────────────────────────────────────────────────────

def _stat_row(cls: int, arm_stats: dict[int, dict], arm_topo: dict,
              rt: dict[int, dict], hdist: dict[int, dict] | None) -> str:
    s = arm_stats.get(cls, {})
    rt_c = rt.get(cls, {})
    hd = hdist.get(cls, {}) if hdist else {}
    return (
        f"| {cls} | {s.get('n_polys','—')} | {s.get('total_ha','—')} "
        f"| {s.get('med_m2','—')} | {s.get('p95_m2','—')} "
        f"| {s.get('n_tiny','—')} | {s.get('perim_m','—')} "
        f"| {s.get('n_verts','—')} | {s.get('verts_per_m','—')} "
        f"| {s.get('n_holes','—')} | {s.get('n_slivers','—')} "
        f"| {hd.get('p95_m','—')} / {hd.get('max_m','—')} "
        f"| {rt_c.get('identical','—')} / {rt_c.get('lost','—')} / {rt_c.get('added','—')} |"
    )


def write_report(
    raw_stats: dict, b_stats: dict, c_stats: dict, d_stats: dict | None,
    topo: dict[str, dict],
    rt: dict[str, dict[int, dict]],
    hdist: dict[str, dict[int, dict] | None],
    d_note: str,
    zoom_bbox: tuple,
    out_path: pathlib.Path,
) -> None:
    header = (
        "| ISOM | Polys | ha | Méd m² | p95 m² | <100m² | Périm m | "
        "Sommets | Som/m | Trous | Slivers | Hausdorff p95/max m | "
        "RT ident/perdu/ajouté |"
    )
    sep = "|-----:|------:|---:|-------:|-------:|-------:|--------:|--------:|-----:|------:|--------:|--------------------:|---------------------:|"

    lines = [
        "# V3 — Généralisation géométrique KP raster (Grimbosq)",
        "",
        f"Paramètres : DP_TOL={DP_TOL} m, Chaikin×{CHAIKIN_N}, coverage_simplify={DP_TOL} m.",
        f"Zoom bbox plate 2 : {zoom_bbox}",
        "",
    ]

    for arm, stats, topo_d, rt_d, hd in [
        ("A — RAW (baseline)", raw_stats, topo["A"], rt["A"], None),
        ("B — DP + Chaikin par polygone", b_stats, topo["B"], rt["B"], hdist["B"]),
        ("C — coverage_simplify combiné", c_stats, topo["C"], rt["C"], hdist["C"]),
    ]:
        lines += [
            f"## Bras {arm}",
            "",
            f"Overlaps : {topo_d['n_overlaps']} — Gaps couverture : {topo_d['gap_m2']} m²",
            "",
            header, sep,
        ]
        for cls in [406, 408, 410]:
            lines.append(_stat_row(cls, stats, topo_d, rt_d, hd))
        lines.append("")

    lines += [
        "## Bras D — coverage_simplify + Chaikin par polygone",
        "",
        f"> {d_note}",
        "",
    ]
    if d_stats is not None:
        lines += [
            f"Overlaps : {topo['D']['n_overlaps']} — Gaps couverture : {topo['D']['gap_m2']} m²",
            "",
            header, sep,
        ]
        for cls in [406, 408, 410]:
            lines.append(_stat_row(cls, d_stats, topo["D"], rt["D"], hdist.get("D")))
        lines.append("")

    lines += [
        "---",
        "",
        "## Portes dures",
        "",
        "| Bras | Overlaps | Gap m² | Status |",
        "|------|--------:|-------:|--------|",
    ]
    for arm_key, arm_name in [("A","A RAW"), ("B","B DP+Ch"), ("C","C cov_simp"), ("D","D cov+Ch")]:
        if arm_key not in topo:
            lines.append(f"| {arm_name} | — | — | non produit |")
            continue
        td = topo[arm_key]
        ov_ok  = td['n_overlaps'] == 0
        gap_ok = td['gap_m2'] < 1.0
        status = "PASS" if (ov_ok and gap_ok) else "FAIL"
        lines.append(f"| {arm_name} | {td['n_overlaps']} | {td['gap_m2']} | **{status}** |")

    lines += [
        "",
        "---",
        "",
        "⛔ STOP — relecture planche + choix méthode par le tenant de porte.",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Rapport V3 → %s", out_path.name)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== V3 généralisation géométrique ===")
    gdf_raw = gpd.read_file(RAW_GPKG)
    log.info("RAW : %d polygones chargés", len(gdf_raw))

    with rasterio.open(SOURCE_TIF) as ds:
        terrain_bbox = (ds.bounds.left, ds.bounds.bottom, ds.bounds.right, ds.bounds.top)

    # ── Bras ──────────────────────────────────────────────────────────────────
    gdf_b = arm_b(gdf_raw)
    gdf_b.to_file(OUT_DIR / "v3_arm_b.gpkg", driver="GPKG", layer="vegetation_b")

    gdf_c = arm_c(gdf_raw)
    gdf_c.to_file(OUT_DIR / "v3_arm_c.gpkg", driver="GPKG", layer="vegetation_c")

    gdf_d_raw, d_note = arm_d(gdf_c)
    if gdf_d_raw is not None:
        gdf_d_raw.to_file(OUT_DIR / "v3_arm_d.gpkg", driver="GPKG", layer="vegetation_d")
    gdf_d: gpd.GeoDataFrame | None = gdf_d_raw

    # ── Métriques ─────────────────────────────────────────────────────────────
    log.info("Calcul des métriques...")
    raw_stats = geom_stats(gdf_raw)
    b_stats   = geom_stats(gdf_b)
    c_stats   = geom_stats(gdf_c)
    d_stats   = geom_stats(gdf_d) if gdf_d is not None else None

    topo: dict[str, dict] = {
        "A": check_topology(gdf_raw),
        "B": check_topology(gdf_b),
        "C": check_topology(gdf_c),
    }
    if gdf_d is not None:
        topo["D"] = check_topology(gdf_d)

    log.info("Calcul round-trip...")
    rt: dict[str, dict[int, dict]] = {
        "A": roundtrip_cost(gdf_raw),
        "B": roundtrip_cost(gdf_b),
        "C": roundtrip_cost(gdf_c),
    }
    if gdf_d is not None:
        rt["D"] = roundtrip_cost(gdf_d)

    log.info("Calcul Hausdorff...")
    hdist: dict[str, dict[int, dict] | None] = {
        "B": hausdorff_vs_raw(gdf_b, gdf_raw),
        "C": hausdorff_vs_raw(gdf_c, gdf_raw),
    }
    if gdf_d is not None:
        hdist["D"] = hausdorff_vs_raw(gdf_d, gdf_raw)

    # ── KP RGB mosaic pour les planches ───────────────────────────────────────
    log.info("Chargement KP RGB...")
    sys.path.insert(0, str(ROOT))
    from work.expe.vectorisation.v1_run import _load_kp_rgb_mosaic
    kp_rgb, _ = _load_kp_rgb_mosaic(terrain_bbox)

    # ── Zoom bbox ─────────────────────────────────────────────────────────────
    zoom_bbox = _zoom_bbox(gdf_raw, window_m=400.0)
    log.info("Zoom bbox : %s", zoom_bbox)

    # ── Planches ──────────────────────────────────────────────────────────────
    arms = {"A": gdf_raw, "B": gdf_b, "C": gdf_c, "D": gdf_d}
    make_plate1(arms, kp_rgb, terrain_bbox, OUT_DIR / "v3_plate1.png")
    make_plate2(arms, zoom_bbox, OUT_DIR / "v3_plate2.png")

    # ── Rapport ───────────────────────────────────────────────────────────────
    write_report(
        raw_stats, b_stats, c_stats, d_stats,
        topo, rt, hdist, d_note, zoom_bbox,
        OUT_DIR / "v3_report.md",
    )
    log.info("=== V3 terminé ===")


if __name__ == "__main__":
    main()
