#!/usr/bin/env python3
"""audit_kp_regle.py — Plan §4-6 : Audit de Karttapullautin correctement paramétré.

Étape 2 (§5) : Reproduire KP avec le pullauta.ini du cartographe sur les dalles Grimbosq.
Étape 3B (§6) : Protocole identique à exp2_3 — métriques de fidélité géométrique.
Diagnostics immédiats (§5) : couverture, nuances, zone de triple recouvrement.
Critère A (§6) : comparaison visuelle côte à côte (Lidar'O vs KP réglé).

Usage:
  # Avec l'ini du cartographe (lance KP + évalue)
  python audit_kp_regle.py --ini /chemin/pullauta.ini

  # Évaluation seule (KP déjà lancé, résultats dans --kp-dir)
  python audit_kp_regle.py --skip-run --kp-dir e:/Vikazim/Ovector/out_kp_audit

  # Spécifier un suffixe raster précis
  python audit_kp_regle.py --skip-run --kp-dir ... --raster _vege
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path

# Forcer UTF-8 sur Windows (terminal CP1252 par défaut)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import scipy.ndimage as ndi
from scipy.spatial import cKDTree
from shapely.ops import unary_union
from osgeo import gdal

warnings.filterwarnings("ignore")

# ── Chemins ────────────────────────────────────────────────────────────────
ROOT            = Path("e:/Vikazim/Ovector")
GRIMBOSQ_GPKG   = ROOT / "grimbosq.gpkg"
VEG_MASKED_GPKG = ROOT / "output/vegetation_masked.gpkg"
LIDAR_DIR       = ROOT / "LIDAR/grimbosq"
DEFAULT_KP_DIR  = ROOT / "out_kp_audit"

# ── Constantes protocole (identiques à exp2_3) ─────────────────────────────
SAMPLING_STEP = 1.0  # m — rééchantillonnage vecteur

# Zone de triple recouvrement (exp2_1 / bande diagnostique)
BAND_YMIN, BAND_YMAX = 6887590.0, 6887720.0

# Fenêtres de comparaison visuelle (§6A)
VIZ_WINDOWS = [
    # (xmin, xmax, ymin, ymax)
    (448750.0, 449250.0, 6887500.0, 6888000.0),  # fenêtre 2.3 principale
    (448300.0, 448800.0, 6887700.0, 6888200.0),  # fenêtre nord-ouest
    (449100.0, 449600.0, 6887200.0, 6887700.0),  # fenêtre sud-est
]

# Suffixes raster produits par KP (dans l'ordre de préférence d'évaluation)
KP_PNG_SUFFIXES = ["_undergrowth", "_vege", ""]

# ── Baselines exp2_3 (Plan §6, tableau — repères, pas objectifs) ───────────
BASELINES = {
    "Lidar'O actuel":            {"dist_med": 27.0, "couv_10m":  9.9, "n_comp":   531},
    "density_hag 2 m":           {"dist_med":  6.5, "couv_10m": 34.1, "n_comp": 12310},
    "density_hag 5 m":           {"dist_med":  7.2, "couv_10m": 21.2, "n_comp":  2083},
    "KP _undergrowth non réglé": {"dist_med": 15.1, "couv_10m":  0.4, "n_comp":    21},
}


# ── Utilitaires protocole 2.3 ──────────────────────────────────────────────

def load_png_mosaic(
    kp_dir: Path, suffix: str,
    ref_xmin: float, ref_xmax: float,
    ref_ymin: float, ref_ymax: float,
) -> tuple[np.ndarray | None, tuple | None]:
    """Mosaïque des tuiles KP pour un suffixe donné.

    Retourne (canvas RGB uint8, geotransform GDAL) clippé sur l'emprise de
    référence. Retourne (None, None) si aucune tuile trouvée.
    """
    tiles = sorted(kp_dir.glob(f"*.copc.laz{suffix}.png"))
    if not tiles:
        return None, None

    # Calculer l'origine globale du canvas depuis toutes les tuiles
    canvas_xmin = float("inf")
    canvas_ymax = float("-inf")
    px = None
    for tile in tiles:
        ds = gdal.Open(str(tile))
        if ds is None:
            continue
        gt = ds.GetGeoTransform()
        if px is None:
            px = gt[1]
        canvas_xmin = min(canvas_xmin, gt[0])
        canvas_ymax = max(canvas_ymax, gt[3])
        ds = None

    if px is None:
        return None, None

    col0 = int(np.floor((ref_xmin - canvas_xmin) / px))
    row0 = int(np.floor((canvas_ymax - ref_ymax) / px))
    col1 = int(np.ceil((ref_xmax - canvas_xmin) / px))
    row1 = int(np.ceil((canvas_ymax - ref_ymin) / px))
    W = max(1, col1 - col0)
    H = max(1, row1 - row0)
    canvas = np.full((H, W, 3), 255, dtype=np.uint8)
    canvas_gt = (
        canvas_xmin + col0 * px, px, 0.0,
        canvas_ymax - row0 * px, 0.0, -px,
    )

    for tile in tiles:
        ds = gdal.Open(str(tile))
        if ds is None:
            continue
        gt = ds.GetGeoTransform()
        tw, th = ds.RasterXSize, ds.RasterYSize
        dc = int(round((gt[0] - canvas_gt[0]) / px))
        dr = int(round((canvas_gt[3] - gt[3]) / px))
        if ds.RasterCount >= 3:
            r = ds.GetRasterBand(1).ReadAsArray()
            g = ds.GetRasterBand(2).ReadAsArray()
            b = ds.GetRasterBand(3).ReadAsArray()
            img = np.stack([r, g, b], axis=2)
        else:
            ch = ds.GetRasterBand(1).ReadAsArray()
            img = np.stack([ch, ch, ch], axis=2)
        ds = None
        r0c, r1c = max(0, dr), min(H, dr + th)
        c0c, c1c = max(0, dc), min(W, dc + tw)
        r0t, c0t = max(0, -dr), max(0, -dc)
        if r1c > r0c and c1c > c0c:
            canvas[r0c:r1c, c0c:c1c] = img[
                r0t : r0t + (r1c - r0c), c0t : c0t + (c1c - c0c)
            ]

    return canvas, canvas_gt


def sample_lines(geom, step: float = SAMPLING_STEP) -> np.ndarray:
    """Rééchantillonne une géométrie linéaire à `step` mètres. Retourne Nx2."""
    if geom is None or geom.is_empty:
        return np.empty((0, 2))
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        parts = [g for g in geom.geoms if g.geom_type in ("LineString", "MultiLineString")]
    elif geom.geom_type == "LineString":
        parts = [geom]
    else:
        return np.empty((0, 2))
    pts: list[tuple[float, float]] = []
    for part in parts:
        segs = list(part.geoms) if part.geom_type == "MultiLineString" else [part]
        for seg in segs:
            if seg.is_empty or seg.length == 0:
                continue
            n = max(2, int(seg.length / step) + 1)
            for d in np.linspace(0, seg.length, n):
                p = seg.interpolate(d)
                pts.append((p.x, p.y))
    return np.array(pts) if pts else np.empty((0, 2))


def gt_px_to_coord(
    gt: tuple, rows: np.ndarray, cols: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    x = gt[0] + (cols + 0.5) * gt[1]
    y = gt[3] + (rows + 0.5) * gt[5]
    return x, y


def kp_boundary(
    rgb: np.ndarray, canvas_gt: tuple, ref_bbox: tuple
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extrait les frontières vég/non-vég du raster RGB KP.

    Non-blanc = végétation (seuil : au moins un canal < 220, identique à exp2_3).
    Retourne (x, y, boundary_mask, veg_mask).
    """
    veg = (rgb[:, :, 0] < 220) | (rgb[:, :, 1] < 220) | (rgb[:, :, 2] < 220)

    xmin, ymin, xmax, ymax = ref_bbox
    px = canvas_gt[1]
    c0 = max(0, int((xmin - canvas_gt[0]) / px))
    r0 = max(0, int((canvas_gt[3] - ymax) / px))
    c1 = min(veg.shape[1], int(np.ceil((xmax - canvas_gt[0]) / px)))
    r1 = min(veg.shape[0], int(np.ceil((canvas_gt[3] - ymin) / px)))
    clip = np.zeros_like(veg)
    clip[r0:r1, c0:c1] = veg[r0:r1, c0:c1]
    veg = clip

    eroded = ndi.binary_erosion(veg)
    dilated = ndi.binary_dilation(veg)
    bnd = dilated & (~eroded)
    rows, cols = np.where(bnd)
    x, y = gt_px_to_coord(canvas_gt, rows, cols)
    return x, y, bnd, veg


def compute_metrics(
    cand_pts: np.ndarray,
    ref_pts: np.ndarray,
    length_m: float,
    comp_lengths: list[float],
    cand_step: float = SAMPLING_STEP,
    ref_total_length_m: float | None = None,
) -> dict:
    """Métriques de fidélité protocole 2.3 — identiques à exp2_3.metrics().

    cand_step : pas d'échantillonnage du candidat en mètres (kp_px pour
    les rasters KP, res_m pour les rasters pipeline, SAMPLING_STEP pour
    les vecteurs vectorisés à 1 m).
    ref_total_length_m : longueur géométrique totale de la référence.
    Si renseignée et que plus_longue_composante_m la dépasse, is_blob=True
    est ajouté aux métriques (détection d'un aplat connexe, pas d'un réseau).
    """
    empty: dict = {
        "n_points_candidat": len(cand_pts),
        "n_points_ref": len(ref_pts),
        "distance_vers_ref": {"median": None, "p75": None, "p90": None, "max": None},
        "couverture_ref": {"pct_le_5m": None, "pct_le_10m": None, "pct_le_20m": None},
        "frontiere": {
            "longueur_totale_m": round(length_m, 1),
            "longueur_proche_10m_m": None,
            "ratio_utile": None,
            "n_composantes": len(comp_lengths),
            "longueur_mediane_composante_m": None,
            "plus_longue_composante_m": None,
        },
    }
    if len(cand_pts) == 0 or len(ref_pts) == 0:
        return empty

    d_c2r, _ = cKDTree(ref_pts).query(cand_pts)
    d_r2c, _ = cKDTree(cand_pts).query(ref_pts)
    n_useful = int(np.sum(d_c2r <= 10.0))
    useful_m = n_useful * cand_step

    plus_longue = round(float(np.max(comp_lengths)), 1) if comp_lengths else None

    result = {
        "n_points_candidat": len(cand_pts),
        "n_points_ref": len(ref_pts),
        "distance_vers_ref": {
            "median": round(float(np.median(d_c2r)), 2),
            "p75":    round(float(np.percentile(d_c2r, 75)), 2),
            "p90":    round(float(np.percentile(d_c2r, 90)), 2),
            "max":    round(float(np.max(d_c2r)), 2),
        },
        "couverture_ref": {
            "pct_le_5m":  round(float(np.mean(d_r2c <=  5.0)) * 100, 1),
            "pct_le_10m": round(float(np.mean(d_r2c <= 10.0)) * 100, 1),
            "pct_le_20m": round(float(np.mean(d_r2c <= 20.0)) * 100, 1),
        },
        "frontiere": {
            "longueur_totale_m":             round(length_m, 1),
            "longueur_proche_10m_m":         round(useful_m, 1),
            "ratio_utile":                   round(useful_m / length_m, 4)
                                             if length_m > 0 else None,
            "n_composantes":                 len(comp_lengths),
            "longueur_mediane_composante_m": round(float(np.median(comp_lengths)), 1)
                                             if comp_lengths else None,
            "plus_longue_composante_m":      plus_longue,
        },
    }

    if (ref_total_length_m is not None
            and plus_longue is not None
            and plus_longue > ref_total_length_m):
        result["frontiere"]["is_blob"] = True
        result["frontiere"]["blob_warning"] = (
            f"plus_longue ({plus_longue:.0f} m) > longueur_ref "
            f"({ref_total_length_m:.0f} m) — aplat connexe, pas un réseau de frontières"
        )

    return result


def diagnostics_immediats(
    rgb: np.ndarray, canvas_gt: tuple, ref_bbox: tuple
) -> dict:
    """Contrôles immédiats §5 : couverture, nuances, triple recouvrement."""
    px = abs(canvas_gt[1])
    xmin, ymin, xmax, ymax = ref_bbox

    # Emprise de référence en pixels
    c0 = max(0, int((xmin - canvas_gt[0]) / px))
    r0 = max(0, int((canvas_gt[3] - ymax) / px))
    c1 = min(rgb.shape[1], int(np.ceil((xmax - canvas_gt[0]) / px)))
    r1 = min(rgb.shape[0], int(np.ceil((canvas_gt[3] - ymin) / px)))

    rgb_ref = rgb[r0:r1, c0:c1]
    veg_ref = (rgb_ref[:, :, 0] < 220) | (rgb_ref[:, :, 1] < 220) | (rgb_ref[:, :, 2] < 220)
    couverture_pct = float(veg_ref.mean()) * 100

    # Zone de triple recouvrement
    rb0 = max(0, int((canvas_gt[3] - BAND_YMAX) / px))
    rb1 = min(rgb.shape[0], int(np.ceil((canvas_gt[3] - BAND_YMIN) / px)))
    veg_band = (rgb[rb0:rb1, c0:c1] < 220).any(axis=2)
    couverture_bande = float(veg_band.mean()) * 100 if veg_band.size > 0 else None

    # Nuances des pixels végétation
    veg_px = rgb_ref[veg_ref]
    diag: dict = {
        "resolution_m": round(px, 4),
        "couverture_emprise_ref_pct": round(couverture_pct, 2),
        "couverture_bande_triple_recouvrement_pct": (
            round(couverture_bande, 2) if couverture_bande is not None else None
        ),
        "n_pixels_vegetation": int(len(veg_px)),
    }

    if len(veg_px) > 0:
        r_v = veg_px[:, 0].astype(float)
        g_v = veg_px[:, 1].astype(float)
        b_v = veg_px[:, 2].astype(float)
        lum = (r_v + g_v + b_v) / 3.0
        diag["nuances_vegetation"] = {
            "r_mean": round(float(r_v.mean()), 1),
            "g_mean": round(float(g_v.mean()), 1),
            "b_mean": round(float(b_v.mean()), 1),
            "luminosite_p10": round(float(np.percentile(lum, 10)), 1),
            "luminosite_p50": round(float(np.percentile(lum, 50)), 1),
            "luminosite_p90": round(float(np.percentile(lum, 90)), 1),
        }

    return diag


# ── Chargement référence ───────────────────────────────────────────────────

def load_reference() -> tuple[np.ndarray, tuple, object]:
    """Charge contour_ref = union(406/408/410) depuis grimbosq.gpkg.

    Retourne (ref_pts Nx2, ref_bbox, ref_contour).
    """
    print("Chargement référence FFCO (grimbosq.gpkg, layer=grimbosq_areas)…")
    gdf = gpd.read_file(
        GRIMBOSQ_GPKG, layer="grimbosq_areas",
        encoding="latin-1", on_invalid="ignore",
    )
    veg = gdf[gdf["Name"].str.contains("tation", na=False)].copy()
    veg = veg[~veg.geometry.is_empty & veg.geometry.notna()].copy()
    n_inv = int((~veg.geometry.is_valid).sum())
    if n_inv > 0:
        veg["geometry"] = veg.geometry.buffer(0)
    ref_union = unary_union(veg.geometry)
    ref_contour = ref_union.boundary
    ref_pts = sample_lines(ref_contour, SAMPLING_STEP)
    print(
        f"  {len(veg)} polygones -> {len(ref_pts):,} points ref "
        f"(contour {ref_contour.length:.0f} m, {n_inv} invalides corrigees)"
    )
    return ref_pts, ref_union.bounds, ref_contour


# ── Lancement KP ───────────────────────────────────────────────────────────

def _locate_binary() -> Path:
    import os
    env = os.environ.get("KP_BINARY")
    if env:
        p = Path(env)
        if p.exists():
            return p
    which = shutil.which("pullauta")
    if which:
        return Path(which)
    raise FileNotFoundError(
        "Karttapullautin introuvable.\n"
        "  • Définir KP_BINARY=/chemin/vers/pullauta, ou\n"
        "  • Ajouter le répertoire contenant pullauta au PATH."
    )


def run_kp_with_ini(ini_path: Path, kp_dir: Path) -> None:
    """Lance KP sur les dalles Grimbosq avec le pullauta.ini du cartographe.

    Remplace uniquement batch / lazfolder / batchoutfolder pour préserver
    tous les paramètres de végétation originaux (§5 : ne modifier aucun paramètre).
    """
    kp_dir.mkdir(parents=True, exist_ok=True)
    binary = _locate_binary()

    laz_str = str(LIDAR_DIR.resolve()).replace("\\", "/")
    out_str = str(kp_dir.resolve()).replace("\\", "/")
    overrides = {"batch": "1", "lazfolder": laz_str, "batchoutfolder": out_str}

    lines = ini_path.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in overrides:
                result.append(f"{key}={overrides[key]}")
                seen.add(key)
                continue
        result.append(line)
    for k, v in overrides.items():
        if k not in seen:
            result.append(f"{k}={v}")

    dest_ini = kp_dir / "pullauta.ini"
    dest_ini.write_text("\n".join(result), encoding="utf-8")
    print(f"  pullauta.ini → {dest_ini}")
    print(f"  LiDAR source : {LIDAR_DIR} ({len(list(LIDAR_DIR.glob('*.laz')))} dalles)")

    print(f"Lancement KP (cwd={kp_dir})…")
    t0 = time.time()
    proc = subprocess.run([str(binary.resolve())], cwd=str(kp_dir))
    elapsed = time.time() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"KP a échoué (code retour {proc.returncode})")
    print(f"  KP terminé en {elapsed:.0f} s")


def discover_suffixes(kp_dir: Path) -> list[str]:
    """Retourne les suffixes de raster KP disponibles dans kp_dir."""
    found = []
    for suffix in KP_PNG_SUFFIXES:
        tiles = list(kp_dir.glob(f"*.copc.laz{suffix}.png"))
        if tiles:
            found.append(suffix)
            print(f"  {suffix or '(base)'!r:20s} : {len(tiles)} tuile(s)")
    return found


# ── Visualisation comparaison (critère A §6) ──────────────────────────────

def _clip_rgb_window(
    rgb: np.ndarray, canvas_gt: tuple,
    xmin: float, xmax: float, ymin: float, ymax: float,
) -> np.ndarray:
    px = abs(canvas_gt[1])
    c0 = max(0, int((xmin - canvas_gt[0]) / px))
    r0 = max(0, int((canvas_gt[3] - ymax) / px))
    c1 = min(rgb.shape[1], int(np.ceil((xmax - canvas_gt[0]) / px)))
    r1 = min(rgb.shape[0], int(np.ceil((canvas_gt[3] - ymin) / px)))
    return rgb[r0:r1, c0:c1]


def make_comparison_figure(
    kp_rgbs: dict[str, tuple[np.ndarray, tuple]],
    ref_pts: np.ndarray,
    ref_bbox: tuple,
    out_png: Path,
) -> None:
    """Figure de comparaison visuelle côte à côte — critère A (§6).

    Colonnes : Lidar'O actuel (vegetation_masked.gpkg)  |  KP [suffixe] …
    Lignes   : fenêtres VIZ_WINDOWS (représentatives + zone triple recouvrement).

    La ligne pointillée cyan délimite la zone de triple recouvrement (§2.1).
    Le contour_ref est superposé en rouge pour évaluer la cohérence spatiale.
    """
    gdf_vm = gpd.read_file(VEG_MASKED_GPKG)
    gdf_vm = gdf_vm[~gdf_vm.geometry.is_empty & gdf_vm.geometry.notna()].copy()

    n_win = len(VIZ_WINDOWS)
    n_kp = len(kp_rgbs)
    n_cols = 1 + n_kp  # Lidar'O + rendus KP

    fig, axes = plt.subplots(n_win, n_cols, figsize=(n_cols * 5, n_win * 4.5))
    if n_win == 1:
        axes = np.array([axes])
    if n_cols == 1:
        axes = axes[:, np.newaxis]

    fig.suptitle(
        "Audit KP — Comparaison visuelle (Plan §6A)\n"
        "Rouge : contour_ref FFCO  |  Cyan : zone triple recouvrement",
        fontsize=9,
    )

    for row, (xmin, xmax, ymin, ymax) in enumerate(VIZ_WINDOWS):
        extent = [xmin, xmax, ymin, ymax]

        # ── Colonne 0 : Lidar'O actuel (vegetation_masked.gpkg) ───────────
        ax0 = axes[row, 0]
        ax0.set_xlim(xmin, xmax); ax0.set_ylim(ymin, ymax)
        ax0.set_aspect("equal"); ax0.set_facecolor("#f0ede8")
        vm_clip = gdf_vm.cx[xmin:xmax, ymin:ymax]
        if not vm_clip.empty:
            vm_clip.plot(
                ax=ax0, color="#6aaf4e", edgecolor="#3a7a20",
                linewidth=0.3, alpha=0.85,
            )
        # Contour ref
        ref_in = ref_pts[
            (ref_pts[:, 0] >= xmin) & (ref_pts[:, 0] <= xmax) &
            (ref_pts[:, 1] >= ymin) & (ref_pts[:, 1] <= ymax)
        ]
        if len(ref_in) > 0:
            ax0.scatter(ref_in[:, 0], ref_in[:, 1],
                        s=0.15, c="red", alpha=0.5, rasterized=True)
        ax0.axhline(BAND_YMIN, color="cyan", lw=0.7, ls="--", alpha=0.8)
        ax0.axhline(BAND_YMAX, color="cyan", lw=0.7, ls="--", alpha=0.8)
        ax0.set_xticks([]); ax0.set_yticks([])
        if row == 0:
            ax0.set_title("Lidar'O actuel", fontsize=8, fontweight="bold")

        # ── Colonnes 1+ : rendus KP ────────────────────────────────────────
        for col_idx, (suffix, (rgb, cgt)) in enumerate(kp_rgbs.items()):
            ax = axes[row, col_idx + 1]
            clip = _clip_rgb_window(rgb, cgt, xmin, xmax, ymin, ymax)
            ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax)
            ax.set_aspect("equal")
            if clip.size > 0:
                ax.imshow(clip, extent=extent, aspect="equal",
                          origin="upper", interpolation="nearest")
            if len(ref_in) > 0:
                ax.scatter(ref_in[:, 0], ref_in[:, 1],
                           s=0.15, c="red", alpha=0.5, rasterized=True)
            ax.axhline(BAND_YMIN, color="cyan", lw=0.7, ls="--", alpha=0.8)
            ax.axhline(BAND_YMAX, color="cyan", lw=0.7, ls="--", alpha=0.8)
            ax.set_xticks([]); ax.set_yticks([])
            if row == 0:
                label = f"KP réglé ({suffix or 'base'})"
                ax.set_title(label, fontsize=8, fontweight="bold")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Comparaison visuelle → {out_png}")


# ── Programme principal ────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--ini", type=Path,
        help="Chemin vers le pullauta.ini du cartographe (requis sauf --skip-run)",
    )
    parser.add_argument(
        "--kp-dir", type=Path, default=DEFAULT_KP_DIR,
        help=f"Répertoire de sortie KP (défaut : {DEFAULT_KP_DIR})",
    )
    parser.add_argument(
        "--raster", default="auto",
        help=(
            "Suffixe raster à évaluer : _undergrowth | _vege | (vide=base) | "
            "auto (tous, défaut)"
        ),
    )
    parser.add_argument(
        "--skip-run", action="store_true",
        help="Ne pas relancer KP — évaluer l'existant dans --kp-dir",
    )
    args = parser.parse_args()

    if not args.skip_run and args.ini is None:
        print(
            "ATTENTION : --ini non fourni.\n"
            "  Fournir le pullauta.ini du cartographe (Étape 1 du plan).\n"
            "  Pour évaluer un résultat existant : --skip-run --kp-dir <chemin>"
        )
        sys.exit(1)

    print(f"\n{'='*60}")
    print("AUDIT KP — Plan PLAN_audit_kp_v2")
    print(f"{'='*60}")

    # ── Étape 2 §5 : lancement KP ─────────────────────────────────────────
    if not args.skip_run:
        print(f"\n=== Étape 2 (§5) : Reproduction KP ===")
        print(f"  ini  : {args.ini}")
        print(f"  vers : {args.kp_dir}")
        run_kp_with_ini(args.ini, args.kp_dir)

    # ── Découverte des sorties ─────────────────────────────────────────────
    print(f"\n=== Découverte des sorties KP dans {args.kp_dir} ===")
    if args.raster == "auto":
        suffixes = discover_suffixes(args.kp_dir)
    else:
        suffixes = [args.raster if args.raster != "(base)" else ""]

    if not suffixes:
        print(
            "AUCUN fichier PNG trouvé.\n"
            "  Vérifier que KP a bien tourné et que savetempfiles=1 est dans l'ini."
        )
        sys.exit(1)

    # ── Chargement référence ───────────────────────────────────────────────
    print()
    ref_pts, ref_bbox, ref_contour = load_reference()
    xmin_r, ymin_r, xmax_r, ymax_r = ref_bbox

    # ── Étape 3B §6 : protocole 2.3 ───────────────────────────────────────
    print("\n=== Étape 3B (§6) : Protocole 2.3 ===")
    resultats: list[dict] = []
    kp_rgbs: dict[str, tuple[np.ndarray, tuple]] = {}

    for suffix in suffixes:
        label = suffix or "base"
        print(f"\n--- Raster : {label!r} ---")

        rgb, cgt = load_png_mosaic(args.kp_dir, suffix, xmin_r, xmax_r, ymin_r, ymax_r)
        if rgb is None:
            print(f"  Impossible de charger la mosaïque (suffixe={label!r})")
            continue

        kp_px = abs(cgt[1])
        print(f"  Canvas {rgb.shape[0]}×{rgb.shape[1]} px, résolution {kp_px:.4f} m/pixel")

        # Diagnostics §5
        diag = diagnostics_immediats(rgb, cgt, ref_bbox)
        cov   = diag["couverture_emprise_ref_pct"]
        cov_b = diag.get("couverture_bande_triple_recouvrement_pct")
        cov_b_s = f"{cov_b:.1f} %" if cov_b is not None else "n/a"
        print(f"  Couverture emprise : {cov:.1f} %  |  triple recouvrement : {cov_b_s}")

        if cov < 0.5:
            print(
                "  AVERTISSEMENT : couverture < 0.5 % — raster quasi vide.\n"
                "  Vérifier que l'ini du cartographe active bien la végétation."
            )

        # Frontières
        x_kp, y_kp, bnd_mask, veg_mask = kp_boundary(rgb, cgt, ref_bbox)
        print(f"  {len(x_kp):,} pixels de frontière")

        # Composantes connexes
        labeled, n_comp = ndi.label(veg_mask)
        length_total = float(len(x_kp)) * kp_px
        comp_lengths: list[float] = []
        for i in range(1, n_comp + 1):
            bm2 = bnd_mask & (labeled == i)
            c = float(bm2.sum()) * kp_px
            if c > 0:
                comp_lengths.append(c)

        cand_pts = (
            np.column_stack([x_kp, y_kp]) if len(x_kp) > 0 else np.empty((0, 2))
        )
        m = compute_metrics(
            cand_pts, ref_pts, length_total, comp_lengths,
            cand_step=kp_px,
            ref_total_length_m=float(ref_contour.length),
        )

        dm  = m["distance_vers_ref"]["median"]
        c10 = m["couverture_ref"]["pct_le_10m"]
        nc  = m["frontiere"]["n_composantes"]
        dm_s  = f"{dm:.1f} m"  if dm  is not None else "n/a"
        c10_s = f"{c10:.1f} %" if c10 is not None else "n/a"
        print(f"  dist médiane → ref : {dm_s}  |  couv ≤10 m : {c10_s}  |  composantes : {nc}")

        kp_rgbs[label] = (rgb, cgt)
        resultats.append({
            "suffixe": label,
            "ini_source": str(args.ini) if args.ini else "skip-run",
            "diagnostics_immediats": diag,
            "metriques": m,
        })

    # ── Tableau de synthèse vs baselines ───────────────────────────────────
    print(f"\n{'='*60}")
    print("SYNTHÈSE — Comparaison aux baselines (Plan §6, tableau)")
    print(f"{'='*60}")
    print(f"  {'produit':38s}  {'dist_med':>8s}  {'couv≤10m':>9s}  {'n_comp':>7s}")
    print(f"  {'-'*38}  {'-'*8}  {'-'*9}  {'-'*7}")
    for name, bl in BASELINES.items():
        print(f"  {name:38s}  {bl['dist_med']:8.1f}  {bl['couv_10m']:9.1f}  {bl['n_comp']:7d}")
    print(f"  {'-'*38}  {'-'*8}  {'-'*9}  {'-'*7}")
    for r in resultats:
        m = r["metriques"]
        dm  = m["distance_vers_ref"]["median"]
        c10 = m["couverture_ref"]["pct_le_10m"]
        nc  = m["frontiere"]["n_composantes"]
        nom = f"KP réglé ({r['suffixe']})"
        dm_s  = f"{dm:8.1f}"  if dm  is not None else f"{'n/a':>8s}"
        c10_s = f"{c10:9.1f}" if c10 is not None else f"{'n/a':>9s}"
        nc_s  = f"{nc:7d}"    if nc  is not None else f"{'n/a':>7s}"
        print(f"  {nom:38s}  {dm_s}  {c10_s}  {nc_s}")

    # ── Verdict préliminaire (§8) ──────────────────────────────────────────
    cas = _verdict_preliminaire(resultats)
    print(f"\nVerdict préliminaire : {cas}")

    # ── JSON ───────────────────────────────────────────────────────────────
    out_json = ROOT / "audit_kp_regle.json"
    out_json.write_text(
        json.dumps(
            {
                "plan": "PLAN_audit_kp_v2 — §5 + §6B",
                "kp_dir": str(args.kp_dir),
                "ini_source": str(args.ini) if args.ini else "skip-run",
                "baselines_reference": BASELINES,
                "resultats": resultats,
                "verdict_preliminaire": cas,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nJSON → {out_json}")

    # ── Comparaison visuelle (critère A §6) ───────────────────────────────
    if kp_rgbs:
        out_png = ROOT / "audit_kp_comparaison.png"
        print("\n=== Critère A (§6) : Comparaison visuelle ===")
        make_comparison_figure(kp_rgbs, ref_pts, ref_bbox, out_png)
    else:
        print("\nAucun raster chargé — figure de comparaison non produite.")

    print("\nDone.")


def _verdict_preliminaire(resultats: list[dict]) -> str:
    """Orienteur de cas A/B/C (Plan §8) à compléter avec l'évaluation du cartographe."""
    if not resultats:
        return "Indéterminé — aucun raster évalué"

    # Prendre le meilleur résultat (distance médiane minimale)
    valid = [r for r in resultats if r["metriques"]["distance_vers_ref"]["median"] is not None]
    if not valid:
        return "Indéterminé — métriques vides (couverture nulle ?)"

    best = min(valid, key=lambda r: r["metriques"]["distance_vers_ref"]["median"])
    dm   = best["metriques"]["distance_vers_ref"]["median"]
    c10  = best["metriques"]["couverture_ref"]["pct_le_10m"] or 0
    cov  = best["diagnostics_immediats"]["couverture_emprise_ref_pct"]

    if cov < 1.0:
        return (
            f"Cas B potentiel — couverture {cov:.1f} %, raster quasi vide "
            f"(dist {dm:.1f} m, couv≤10m {c10:.1f} %). "
            "Vérifier l'ini (undergrowth / greenground)."
        )
    if dm < 10 and c10 > 20:
        return (
            f"Cas A potentiel — dist médiane {dm:.1f} m, couv≤10m {c10:.1f} %. "
            "KP réglé fournit un fond géométriquement proche. "
            "Compléter avec évaluation visuelle du cartographe (critère A)."
        )
    if cov > 5 and (dm is None or dm > 15):
        return (
            f"Cas C potentiel — couverture {cov:.1f} % (visuellement utilisable), "
            f"mais dist médiane {dm:.1f} m (frontières éloignées). "
            "Le fond peut assister le tracé humain sans être géométriquement précis."
        )
    return (
        f"Indéterminé — couv {cov:.1f} %, dist {dm:.1f} m, couv≤10m {c10:.1f} %. "
        "Évaluation visuelle nécessaire (critère A, §6)."
    )


if __name__ == "__main__":
    main()
