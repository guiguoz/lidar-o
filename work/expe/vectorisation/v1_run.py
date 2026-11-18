"""V1 — Round-trip KP raster → polygonize / dissolve → rasterize (Grimbosq).

Étapes :
  V1.1  Bilan zéro : distribution des teintes KP avec table shade_to_isom active.
  V1.2  build_class_raster → stage_polygonize + stage_dissolve (sans simplification).
  V1.3A Round-trip : rasteriser les polygones sur la grille source, comparer pixel à pixel.
        Deux registres : décisions de table (bit 2 → 0) vs pertes vectoriseur (doivent être 0).
  V1.3B Statistiques géométriques : polygones, surfaces, sommets, isthmes potentiels.
  V1.4  Planche 4 panneaux à 1:10 000.

Sorties :
  work/expe/vectorisation/source_classes.tif
  work/expe/vectorisation/vectorized_raw.gpkg
  work/expe/vectorisation/roundtrip.tif
  work/expe/vectorisation/v1_roundtrip_report.md
  work/expe/vectorisation/v1_plate.png
"""
from __future__ import annotations

import pathlib
import sys

# Accès à src/ depuis le sous-répertoire work/expe/vectorisation/
ROOT = pathlib.Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

import logging
from typing import Any

import matplotlib
matplotlib.use("Agg")  # backend non-interactif — évite segfault sur figures volumineuses
import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import yaml
from rasterio.features import rasterize as rio_rasterize
from rasterio.transform import from_origin

from src.kp_raster import (
    KP_FIRST_GREEN,
    KP_NO_DATA,
    KP_YELLOW,
    ISOM_TO_DN,
    build_class_raster,
    kp_green_rgb,
    load_tiles,
    mosaic,
    read_ini_vege_params,
)
from src.vegetation import stage_dissolve, stage_polygonize

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Constantes terrain ────────────────────────────────────────────────────────

TERRAIN = "grimbosq"
OUT_DIR = ROOT / "work/expe/vectorisation"
CONFIG_PATH = ROOT / "config.yaml"
OUT_KP = ROOT / f"out_kp_{TERRAIN}"

DN_TO_ISOM = {v: k for k, v in ISOM_TO_DN.items()}   # {85:406, 170:408, 255:410}

# Couleurs planche : vert clair / moyen / foncé inspirés ISOM
ISOM_COLORS: dict[int, str] = {
    406: "#c7e9b4",  # vert clair
    408: "#41b6c4",  # cyan-vert (distinguable du fond KP)
    410: "#225ea8",  # bleu-vert foncé
}


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _terrain_cfg(cfg: dict) -> dict:
    return cfg["terrains"][TERRAIN]


def _bbox(cfg: dict) -> tuple[float, float, float, float]:
    b = _terrain_cfg(cfg)["bbox"]
    return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))


def _shade_table(cfg: dict) -> dict[int, int]:
    raw = cfg["karttapullautin"]["vectorization"]["shade_to_isom"]
    return {int(k): int(v) for k, v in raw.items()}


# ── V1.1 — Bilan zéro ────────────────────────────────────────────────────────

def v1_1_bilan_zero(
    tiles,
    params: dict,
    table: dict[int, int],
    bbox: tuple[float, float, float, float],
    res_m: float = 1.0,
) -> dict[str, Any]:
    """Compte les pixels par teinte KP et corrèle avec la table active."""
    labels, _, _, _ = mosaic(tiles, bbox=bbox)

    ha = res_m * res_m / 10_000.0
    values, counts = np.unique(labels, return_counts=True)

    rows = []
    for v, n in zip(values.tolist(), counts.tolist()):
        isom = table.get(v, None)
        rows.append({
            "bit": v,
            "pixels": n,
            "ha": round(n * ha, 2),
            "pct": round(100.0 * n / labels.size, 2),
            "isom_effectif": isom,
        })

    # Vérification : teintes inatteignables (bit 9-12, greenshades=99)
    max_reachable = KP_FIRST_GREEN + params["n_shades"] - 1
    unreachable = [r for r in rows if r["bit"] > max_reachable and r["bit"] < 255]
    if unreachable:
        log.warning("Teintes inatteignables présentes dans le raster : %s", unreachable)

    total_green_px = sum(r["pixels"] for r in rows if r["bit"] >= KP_FIRST_GREEN)
    log.info("Bilan zéro : %d teintes, %d px verts (%.1f ha)",
             len([r for r in rows if r["bit"] >= KP_FIRST_GREEN]),
             total_green_px, total_green_px * ha)
    return {"rows": rows, "labels": labels, "total_px": int(labels.size)}


# ── V1.2 — Classification + vectorisation ────────────────────────────────────

def v1_2_classify_vectorize(
    cfg: dict,
    bbox: tuple[float, float, float, float],
    out_dir: pathlib.Path,
) -> tuple[pathlib.Path, gpd.GeoDataFrame]:
    """Produit source_classes.tif et vectorized_raw.gpkg."""
    crs = _terrain_cfg(cfg)["crs"]
    out_tif = out_dir / "source_classes.tif"
    out_gpkg = out_dir / "vectorized_raw.gpkg"

    log.info("V1.2 — build_class_raster → %s", out_tif.name)
    build_class_raster(OUT_KP, cfg, crs, out_tif, bbox=bbox)

    log.info("V1.2 — stage_polygonize")
    gdf_poly, stats_poly = stage_polygonize(out_tif, cfg)
    log.info("  polygonize : %d polygones, %d ha",
             stats_poly["output"]["count"],
             round(stats_poly["output"]["total_area_m2"] / 10_000, 1))

    log.info("V1.2 — stage_dissolve")
    gdf_diss, stats_diss = stage_dissolve(gdf_poly, cfg)
    log.info("  dissolve : %d → %d polygones",
             stats_diss["before"]["count"], stats_diss["after"]["count"])

    gdf_diss.to_file(out_gpkg, driver="GPKG", layer="vegetation_raw")
    log.info("V1.2 — vectorized_raw.gpkg écrit (%d polygones)", len(gdf_diss))
    return out_tif, gdf_diss


# ── V1.3A — Round-trip ────────────────────────────────────────────────────────

def v1_3a_roundtrip(
    source_tif: pathlib.Path,
    gdf: gpd.GeoDataFrame,
    labels: np.ndarray,
    table: dict[int, int],
    out_dir: pathlib.Path,
) -> dict[str, Any]:
    """Rasterise les polygones sur la grille source, compare pixel à pixel.

    Deux registres :
      A — Décisions de table : pixels présents dans labels (bit ≥ 2) mais
          délibérément laissés à 0 par la table (shade_to_isom[bit] = 0).
          Ces pixels ne peuvent pas apparaître dans le round-trip ; c'est un choix,
          pas une perte.
      B — Pertes vectoriseur : pixels non nuls dans source_classes.tif qui
          n'apparaissent pas dans roundtrip.tif. Sans simplification, doit être 0.
    """
    out_roundtrip = out_dir / "roundtrip.tif"

    with rasterio.open(source_tif) as ds:
        src_arr = ds.read(1)
        transform = ds.transform
        height, width = ds.height, ds.width
        crs_str = ds.crs.to_string() if ds.crs else None

    # Rasteriser les polygones avec les DN correspondants
    dn_series = gdf["class"].map(ISOM_TO_DN)
    shapes = [
        (geom.__geo_interface__, int(dn))
        for geom, dn in zip(gdf.geometry, dn_series)
        if dn is not None and not np.isnan(dn)
    ]

    if shapes:
        roundtrip_arr = rio_rasterize(
            shapes,
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype=np.uint8,
            merge_alg=rasterio.enums.MergeAlg.replace,
        )
    else:
        roundtrip_arr = np.zeros((height, width), dtype=np.uint8)

    # Écriture roundtrip.tif
    profile = {
        "driver": "GTiff", "height": height, "width": width,
        "count": 1, "dtype": "uint8",
        "crs": crs_str, "transform": transform,
        "nodata": 0, "compress": "deflate",
    }
    with rasterio.open(out_roundtrip, "w", **profile) as ds:
        ds.write(roundtrip_arr, 1)

    # — Registre A : décisions de table (bits délibérément → 0) —
    table_zero_bits = [bit for bit, isom in table.items() if isom == 0 and bit >= KP_FIRST_GREEN]
    mask_table_decision = np.zeros(labels.shape, dtype=bool)
    for bit in table_zero_bits:
        mask_table_decision |= (labels == bit)
    n_table_decision = int(mask_table_decision.sum())

    # — Registre B : pertes vectoriseur —
    mask_source_veg = src_arr != 0
    mask_roundtrip_zero = roundtrip_arr == 0
    mask_vectorizer_loss = mask_source_veg & mask_roundtrip_zero
    n_vectorizer_loss = int(mask_vectorizer_loss.sum())

    # — Diff global —
    diff = src_arr.astype(np.int16) - roundtrip_arr.astype(np.int16)
    n_diff = int(np.sum(diff != 0))

    ha = 1.0 / 10_000.0   # 1 m² par pixel à 1 m/px
    total_veg_px = int(mask_source_veg.sum())

    log.info("Round-trip : diff total=%d px (%.3f ha), table_décision=%d px (%.2f ha), "
             "pertes_vect=%d px",
             n_diff, n_diff * ha, n_table_decision, n_table_decision * ha, n_vectorizer_loss)

    return {
        "table_decision_bits": table_zero_bits,
        "n_table_decision_px": n_table_decision,
        "n_table_decision_ha": round(n_table_decision * ha, 3),
        "n_vectorizer_loss_px": n_vectorizer_loss,
        "n_diff_px": n_diff,
        "total_veg_px_source": total_veg_px,
        "roundtrip_tif": str(out_roundtrip),
    }


# ── V1.3B — Statistiques géométriques ────────────────────────────────────────

def v1_3b_geometry_stats(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Stats géométriques par classe : polygones, surfaces, sommets, isthmes."""
    from shapely.geometry import Polygon, MultiPolygon

    stats: dict[int, dict] = {}
    for cls in sorted(gdf["class"].unique()):
        sub = gdf[gdf["class"] == cls]
        areas = sub.geometry.area
        n_polys = len(sub)
        total_ha = float(areas.sum()) / 10_000.0
        med_m2 = float(areas.median())
        n_tiny = int((areas < 100).sum())   # < 100 m² (min_area pas encore appliqué)

        # Comptage des sommets (exterior + holes)
        n_vertices = 0
        n_holes = 0
        for geom in sub.geometry:
            polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            for p in polys:
                if not isinstance(p, Polygon):
                    continue
                n_vertices += len(p.exterior.coords)
                for ring in p.interiors:
                    n_holes += 1
                    n_vertices += len(ring.coords)

        # Détection isthmes potentiels : P/√A élevé (> 15 → forme linéaire)
        perimeters = sub.geometry.length
        esa = perimeters / np.sqrt(areas.clip(lower=1e-6))
        n_isthmes = int((esa > 15).sum())

        stats[int(cls)] = {
            "n_polys": n_polys,
            "total_ha": round(total_ha, 2),
            "med_area_m2": round(med_m2, 1),
            "n_tiny_lt100m2": n_tiny,
            "n_holes": n_holes,
            "n_vertices": n_vertices,
            "n_isthmes_potentiels": n_isthmes,
        }
        log.info("V1.3B ISOM %d : %d polys, %.1f ha, med=%.0f m², %d trous, %d isthmes pot.",
                 cls, n_polys, total_ha, med_m2, n_holes, n_isthmes)

    # Vérification overlaps (ne devrait pas arriver après dissolve sur données catégorielles)
    from shapely.strtree import STRtree
    n_overlaps = 0
    geoms = list(gdf.geometry)
    tree = STRtree(geoms)
    for i, g in enumerate(geoms):
        candidates = tree.query(g)
        for j in candidates:
            if j <= i:
                continue
            if geoms[j].intersects(g):
                inter = geoms[j].intersection(g)
                if inter.area > 1e-6:
                    n_overlaps += 1
    stats["n_overlaps"] = n_overlaps
    if n_overlaps:
        log.warning("V1.3B : %d chevauchements détectés (surface > 1 mm²)", n_overlaps)
    else:
        log.info("V1.3B : aucun chevauchement")
    return stats


# ── V1.4 — Planche 4 panneaux ────────────────────────────────────────────────

def _load_kp_rgb_mosaic(
    bbox: tuple[float, float, float, float],
) -> tuple[np.ndarray, rasterio.transform.Affine]:
    """Charge les tuiles *_vege.png en RGB et les assemble dans la bbox."""
    pngs = sorted(p for p in OUT_KP.glob("*_vege.png") if not p.name.startswith("merged"))
    params = read_ini_vege_params(OUT_KP / "pullauta.ini")

    # Découverte de l'emprise commune
    from src.kp_raster import _read_pgw, tile_origin
    tile_info = []
    for png in pngs:
        pgw = png.with_suffix(".pgw")
        if not pgw.exists():
            continue
        res_m, cx, cy = _read_pgw(pgw)
        west, north = tile_origin(res_m, cx, cy)
        with rasterio.open(png) as ds:
            h, w = ds.height, ds.width
            raw = ds.read()
            rgb = np.moveaxis(raw[:3], 0, -1) if ds.count >= 3 else np.stack([raw[0]] * 3, -1)
        east = west + w * res_m
        south = north - h * res_m
        tile_info.append((west, north, east, south, rgb, res_m))

    bxmin, bymin, bxmax, bymax = bbox
    # Fenêtre du canvas
    width = int(round((bxmax - bxmin)))
    height = int(round((bymax - bymin)))
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)

    for west, north, east, south, rgb, res_m in tile_info:
        col_src = max(0, int(round((bxmin - west) / res_m)))
        row_src = max(0, int(round((north - bymax) / res_m)))
        col_dst = max(0, int(round((west - bxmin) / res_m)))
        row_dst = max(0, int(round((bymax - north) / res_m)))
        patch = rgb[row_src:, col_src:]
        h = min(patch.shape[0], height - row_dst)
        w = min(patch.shape[1], width - col_dst)
        if h <= 0 or w <= 0:
            continue
        canvas[row_dst:row_dst + h, col_dst:col_dst + w] = patch[:h, :w]

    transform = from_origin(bxmin, bymax, 1.0, 1.0)
    return canvas, transform


def _downsample(arr: np.ndarray, factor: int) -> np.ndarray:
    """Sous-échantillonnage par sous-selection (pas de lissage — labels catégoriels)."""
    if arr.ndim == 2:
        return arr[::factor, ::factor]
    return arr[::factor, ::factor, :]


def v1_4_plate(
    source_tif: pathlib.Path,
    roundtrip_tif: pathlib.Path,
    gdf: gpd.GeoDataFrame,
    bbox: tuple[float, float, float, float],
    out_dir: pathlib.Path,
) -> pathlib.Path:
    """Planche 4 panneaux à 1:10 000.

    A : KP vegetation.png original (RGB)
    B : raster classifié 406/408/410 (source_classes.tif)
    C : vecteurs dissolve sur fond blanc
    D : vecteurs superposés au fond KP (opacité KP 50 %)
    """
    out_png = out_dir / "v1_plate.png"
    bxmin, bymin, bxmax, bymax = bbox

    log.info("V1.4 — chargement KP RGB mosaic")
    kp_rgb, _ = _load_kp_rgb_mosaic(bbox)

    log.info("V1.4 — chargement source_classes.tif")
    with rasterio.open(source_tif) as ds:
        src_arr = ds.read(1).copy()

    # Palette classifié → RGB
    classified_rgb = np.full((*src_arr.shape, 3), 255, dtype=np.uint8)
    for dn, hex_color in [(85, ISOM_COLORS[406]), (170, ISOM_COLORS[408]), (255, ISOM_COLORS[410])]:
        r, g, b = tuple(int(hex_color.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
        classified_rgb[src_arr == dn] = [r, g, b]

    # Sous-échantillonnage × 4 pour alléger le rendu
    FACTOR = 4
    kp_small = _downsample(kp_rgb, FACTOR)
    cls_small = _downsample(classified_rgb, FACTOR)

    # Dimensionnement fixe : ~20 cm par panneau à 100 dpi (4 panneaux, 2×2)
    dpi = 100
    fig_w_in, fig_h_in = 16.0, 22.0

    fig, axes = plt.subplots(2, 2, figsize=(fig_w_in, fig_h_in), dpi=dpi)
    (ax_a, ax_b), (ax_c, ax_d) = axes

    extent_mpl = [bxmin, bxmax, bymin, bymax]

    # — Panneau A : KP RGB original —
    ax_a.imshow(kp_small, extent=extent_mpl, origin="upper", interpolation="bilinear")
    ax_a.set_title("A — KP vegetation.png original", fontsize=8)

    # — Panneau B : raster classifié —
    ax_b.imshow(cls_small, extent=extent_mpl, origin="upper", interpolation="nearest")
    patches_b = [
        mpatches.Patch(color=ISOM_COLORS[406], label="ISOM 406"),
        mpatches.Patch(color=ISOM_COLORS[408], label="ISOM 408"),
        mpatches.Patch(color=ISOM_COLORS[410], label="ISOM 410"),
    ]
    ax_b.legend(handles=patches_b, fontsize=6, loc="lower left")
    ax_b.set_title("B — Raster classifié 406 / 408 / 410", fontsize=8)

    # — Panneau C : vecteurs seuls —
    ax_c.set_facecolor("white")
    ax_c.set_xlim(bxmin, bxmax)
    ax_c.set_ylim(bymin, bymax)
    ax_c.set_aspect("equal")
    for cls, color in ISOM_COLORS.items():
        sub = gdf[gdf["class"] == cls]
        if not sub.empty:
            sub.plot(ax=ax_c, color=color, edgecolor="none")
    patches_c = [mpatches.Patch(color=c, label=f"ISOM {k}") for k, c in ISOM_COLORS.items()]
    ax_c.legend(handles=patches_c, fontsize=6, loc="lower left")
    ax_c.set_title("C — Vecteurs dissolve (sans simplification)", fontsize=8)

    # — Panneau D : vecteurs + KP à 50 % —
    ax_d.imshow(kp_small, extent=extent_mpl, origin="upper", alpha=0.5, interpolation="bilinear")
    ax_d.set_xlim(bxmin, bxmax)
    ax_d.set_ylim(bymin, bymax)
    ax_d.set_aspect("equal")
    for cls, color in ISOM_COLORS.items():
        sub = gdf[gdf["class"] == cls]
        if not sub.empty:
            sub.plot(ax=ax_d, color=color, edgecolor="none", alpha=0.8)
    ax_d.set_title("D — Vecteurs + fond KP (α=50 %)", fontsize=8)

    # ── Mise en forme commune ─────────────────────────────────────────────────
    for ax in axes.flat:
        ax.set_aspect("equal")
        ax.tick_params(labelsize=5)
        ax.set_xlabel("X Lambert93 (m)", fontsize=5)
        ax.set_ylabel("Y Lambert93 (m)", fontsize=5)

    fig.suptitle("Grimbosq — V1 Round-trip KP raster → vecteurs (1:10 000)", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    log.info("V1.4 — planche sauvée : %s", out_png)
    return out_png


# ── Rapport Markdown ──────────────────────────────────────────────────────────

def write_report(
    v11: dict,
    v13a: dict,
    v13b: dict,
    out_dir: pathlib.Path,
) -> pathlib.Path:
    out_md = out_dir / "v1_roundtrip_report.md"

    ha_px = 1.0 / 10_000.0  # 1 m² par pixel
    rows_bilan = v11["rows"]
    total_px = v11["total_px"]

    lines: list[str] = [
        "# V1 — Round-trip KP raster → vecteurs (Grimbosq)",
        "",
        "## V1.1 Bilan zéro — distribution des teintes",
        "",
        "| Bit KP | ha | % emprise | ISOM effectif |",
        "|-------:|---:|----------:|---------------|",
    ]
    for r in rows_bilan:
        isom_str = str(r["isom_effectif"]) if r["isom_effectif"] else "—"
        lines.append(f"| {r['bit']} | {r['ha']:.2f} | {r['pct']:.2f} | {isom_str} |")

    lines += [
        "",
        "## V1.2 Classification et vectorisation",
        "",
        "Table shade_to_isom appliquée (gelée config.yaml) :",
        "",
        "```",
        "  2 → 0     (décision calibration, forêt courable greenshades[0]=0.2)",
        "  3 → 406   4 → 406",
        "  5 → 408   6 → 408",
        "  7 → 410   8 → 410",
        "```",
        "",
        f"source_classes.tif, vectorized_raw.gpkg produits.",
        "",
        "## V1.3A Round-trip",
        "",
        "### Registre A — Décisions de table",
        "",
        f"Bits délibérément laissés à 0 : {v13a['table_decision_bits']}",
        f"Pixels concernés : **{v13a['n_table_decision_px']:,} px ({v13a['n_table_decision_ha']:.1f} ha)**",
        "",
        "Ces pixels sont absents de source_classes.tif et ne peuvent pas apparaître",
        "dans le round-trip. C'est un choix de calibration, pas une perte vectoriseur.",
        "",
        "### Registre B — Pertes vectoriseur",
        "",
        f"Pixels non nuls dans source_classes.tif absents du round-trip : "
        f"**{v13a['n_vectorizer_loss_px']} px**",
        "",
    ]
    if v13a["n_vectorizer_loss_px"] == 0:
        lines.append("Round-trip parfait (0 pixel perdu) — attendu sans simplification.")
    else:
        n = v13a["n_vectorizer_loss_px"]
        lines.append(f"ATTENTION : {n} pixels perdus par la vectorisation. "
                     "Investiguer avant de passer à V1.5.")

    lines += [
        "",
        "## V1.3B Statistiques géométriques",
        "",
        "| ISOM | Polygones | Surface ha | Med. m² | < 100 m² | Trous | Sommets | Isthmes pot. |",
        "|-----:|----------:|-----------:|--------:|---------:|------:|--------:|-------------:|",
    ]
    for cls in [406, 408, 410]:
        if cls not in v13b:
            continue
        s = v13b[cls]
        lines.append(
            f"| {cls} | {s['n_polys']} | {s['total_ha']:.2f} | {s['med_area_m2']:.0f} "
            f"| {s['n_tiny_lt100m2']} | {s['n_holes']} | {s['n_vertices']:,} "
            f"| {s['n_isthmes_potentiels']} |"
        )

    n_ov = v13b.get("n_overlaps", 0)
    lines += [
        "",
        f"Chevauchements inter-classes : **{n_ov}** (doit être 0 — source catégorielle).",
        "",
        "## V1.4 Planche",
        "",
        "Voir `v1_plate.png` — 4 panneaux à 1:10 000 :",
        "- A : KP vegetation.png original (RGB)",
        "- B : raster classifié 406/408/410",
        "- C : vecteurs dissolve, fond blanc",
        "- D : vecteurs + fond KP 50 %",
        "",
        "---",
        "",
        "*Arrêt V1.4 — relecture humaine requise avant V1.5 (simplification).*",
    ]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    log.info("Rapport écrit : %s", out_md)
    return out_md


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=== V1 round-trip KP raster — terrain %s ===", TERRAIN)
    cfg = _load_cfg()
    bbox = _bbox(cfg)
    table = _shade_table(cfg)
    params = read_ini_vege_params(OUT_KP / "pullauta.ini")

    log.info("Bbox : %s, CRS : %s", bbox, _terrain_cfg(cfg)["crs"])
    log.info("Table shade_to_isom : %s", table)
    log.info("Params KP : %s", params)

    # V1.1
    log.info("── V1.1 bilan zéro ──")
    tiles = load_tiles(OUT_KP, params)
    v11 = v1_1_bilan_zero(tiles, params, table, bbox)

    # V1.2
    log.info("── V1.2 classification + vectorisation ──")
    source_tif, gdf = v1_2_classify_vectorize(cfg, bbox, OUT_DIR)

    # V1.3A
    log.info("── V1.3A round-trip ──")
    v13a = v1_3a_roundtrip(source_tif, gdf, v11["labels"], table, OUT_DIR)

    # V1.3B
    log.info("── V1.3B statistiques géométriques ──")
    v13b = v1_3b_geometry_stats(gdf)

    # V1.4
    log.info("── V1.4 planche ──")
    v1_4_plate(source_tif, OUT_DIR / "roundtrip.tif", gdf, bbox, OUT_DIR)

    # Rapport
    report_path = write_report(v11, v13a, v13b, OUT_DIR)
    log.info("=== V1 terminé === rapport : %s", report_path)


if __name__ == "__main__":
    main()
