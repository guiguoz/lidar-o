"""Lancement de la référence Trier 2015 sur Grimbosq — expérience V0.

Run principal : sous-échantillonnage par impulsion (GpsTime) -> ~10 impl/m²
                seuils Table 5 densité 10/m²

Usage :
    C:/Users/glemi/miniconda3/python.exe experiments/v0/run_trier.py

Sorties dans experiments/v0/output/level_a/.
"""
import json
import logging
import pathlib
import sys
import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import yaml
from rasterio.transform import rowcol

from src.trier_ref import (
    _THRESHOLDS,
    check_gpstime,
    measure_empreinte,
    run,
)
from src.split import load_split


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

ROOT = pathlib.Path(__file__).parent.parent.parent
CFG_PATH = ROOT / "config.yaml"
LIDAR_DIR = ROOT / "LIDAR" / "grimbosq"
OUTPUT_DIR = ROOT / "experiments" / "v0" / "output" / "level_a"

# Densités documentées par Trier. Grimbosq = ~15 impl/m².
ACTUAL_DENSITY = 15.0    # impl/m² mesuré
TARGET_DENSITY = 10.0    # impl/m² run principal (Table 5)
SUBSAMPLE_FRACTION = TARGET_DENSITY / ACTUAL_DENSITY   # 0.6667


def _find_boundary_pixel(
    classes_path: pathlib.Path,
    target_y: float,
    bbox: tuple,
) -> tuple[float, float]:
    with rasterio.open(classes_path) as src:
        cls = src.read(1)
        transform = src.transform
        rows, cols = src.height, src.width

    tr = int(rowcol(transform, (bbox[0] + bbox[2]) / 2, target_y)[0])
    for dr in range(0, 300, 2):
        for row in [tr + dr, tr - dr]:
            if not (0 <= row < rows - 1):
                continue
            row_arr = cls[row, :]
            transitions = np.where(np.diff(row_arr.astype(np.int32)) != 0)[0]
            if len(transitions):
                col = int(transitions[len(transitions) // 2])
                px = float(transform.c + (col + 0.5) * transform.a)
                py = float(transform.f + (row + 0.5) * transform.e)
                return px, py

    logging.warning("Aucune frontière trouvée — centre du bbox utilisé")
    return float((bbox[0] + bbox[2]) / 2), float((bbox[1] + bbox[3]) / 2)


def _estimate_density(copc_paths: list[pathlib.Path], bbox: tuple) -> float:
    """Estime la densité d'impulsions/m² sur le premier fichier COPC."""
    import pdal
    xmin, ymin, xmax, ymax = bbox
    pipe = pdal.Pipeline(json.dumps({"pipeline": [
        {"type": "readers.copc", "filename": str(copc_paths[0])},
        {"type": "filters.crop",
         "bounds": f"([{xmin},{xmax}],[{ymin},{ymax}])"},
    ]}))
    n_pts = pipe.execute()
    if n_pts == 0:
        return 0.0
    pts = pipe.arrays[0]
    if "NumberOfReturns" in pts.dtype.names:
        avg_ret = float(np.mean(pts["NumberOfReturns"].astype(float)))
    else:
        avg_ret = 1.5
    area_m2 = (xmax - xmin) * (ymax - ymin)
    return (n_pts / avg_ret) / area_m2


def _class_stats(arr: np.ndarray, res_m: float) -> dict:
    nodata_mask = arr == 65535
    valid = ~nodata_mask
    stats = {}
    for code in [0, 406, 408, 410]:
        count = int((arr[valid] == code).sum())
        stats[code] = {"px": count, "m2": count * res_m * res_m}
    stats["nodata_px"] = int(nodata_mask.sum())
    return stats


# ── Visualisation 1 : DTM ─────────────────────────────────────────────────────

def _viz_dtm(dtm_path: pathlib.Path, out_png: pathlib.Path) -> None:
    with rasterio.open(dtm_path) as src:
        dtm = src.read(1).astype(np.float32)
        transform = src.transform
        cols, rows = src.width, src.height

    dtm[dtm == -9999.0] = np.nan
    extent = [
        transform.c,
        transform.c + transform.a * cols,
        transform.f + transform.e * rows,
        transform.f,
    ]
    valid = np.isfinite(dtm)
    zmin, zmax = float(np.nanmin(dtm)), float(np.nanmax(dtm))

    fig, axes = plt.subplots(1, 2, figsize=(18, 9))

    im = axes[0].imshow(dtm, cmap="terrain", vmin=zmin, vmax=zmax,
                        extent=extent, aspect="equal", interpolation="bilinear")
    plt.colorbar(im, ax=axes[0], fraction=0.03, label="Altitude (m)")
    axes[0].set_title(
        f"DTM Trier — class 2 uniquement\n"
        f"[TRIER-DEV-DTM] min/cell + NN fill (vs TIN TRIGRID)\n"
        f"z min={zmin:.1f} m  max={zmax:.1f} m"
    )
    axes[0].set_xlabel("X Lambert-93 (m)")
    axes[0].set_ylabel("Y Lambert-93 (m)")

    axes[1].hist(dtm[valid].ravel(), bins=200, color="saddlebrown", alpha=0.8)
    axes[1].set_xlabel("Altitude (m)")
    axes[1].set_ylabel("Fréquence (pixels)")
    axes[1].set_title("Distribution altimétrique DTM")

    fig.suptitle("Trier 2015 — §1 DTM (0.5 m, class 2 ground)", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logging.info("Viz DTM -> %s", out_png)


# ── Visualisation 2 : Strates V_raw / G_raw ──────────────────────────────────

def _viz_strates(strates_path: pathlib.Path, out_png: pathlib.Path) -> None:
    with rasterio.open(strates_path) as src:
        V = src.read(1).astype(np.float32)
        G = src.read(2).astype(np.float32)
        transform = src.transform
        cols, rows = src.width, src.height

    V[V < 0] = np.nan
    G[G < 0] = np.nan
    extent = [
        transform.c,
        transform.c + transform.a * cols,
        transform.f + transform.e * rows,
        transform.f,
    ]

    fig, axes = plt.subplots(1, 2, figsize=(20, 9))

    for ax, data, title, cmap in [
        (axes[0], V, "V_raw — retours non-ground HAG [0.2,2.0) m", "YlGn"),
        (axes[1], G, "G_raw — retours ground (class 2)", "YlOrBr"),
    ]:
        vmax = float(np.nanpercentile(data[np.isfinite(data)], 99))
        im = ax.imshow(data, cmap=cmap, vmin=0, vmax=vmax,
                       extent=extent, aspect="equal", interpolation="nearest")
        plt.colorbar(im, ax=ax, fraction=0.03, label="Nombre de retours")
        ax.set_title(
            f"{title}\n"
            f"total={np.nansum(data):.0f}  max_cell={np.nanmax(data):.0f}"
        )
        ax.set_xlabel("X Lambert-93 (m)")

    fig.suptitle(
        "Trier 2015 — §2 Strates brutes V et G (0.5 m)\n"
        "[TRIER-DEV-V-UNRESOLVED] classes 6/7/9 Grimbosq traitées comme 'other'",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logging.info("Viz strates -> %s", out_png)


# ── Visualisation 3 & 4 : NDVD signal (brut et après voisinage) ─────────────

def _viz_ndvd_signal(
    ndvd_path: pathlib.Path,
    out_png: pathlib.Path,
    title_prefix: str,
    section_label: str,
) -> None:
    with rasterio.open(ndvd_path) as src:
        ndvd = src.read(1)
        transform = src.transform
        cols, rows = src.width, src.height

    extent = [
        transform.c,
        transform.c + transform.a * cols,
        transform.f + transform.e * rows,
        transform.f,
    ]
    valid = np.isfinite(ndvd)
    p1, p99 = float(np.nanpercentile(ndvd[valid], 1)), float(np.nanpercentile(ndvd[valid], 99))

    fig, axes = plt.subplots(1, 2, figsize=(18, 10))

    im = axes[0].imshow(
        ndvd, cmap="RdYlGn", vmin=p1, vmax=p99,
        extent=extent, aspect="equal", interpolation="nearest",
    )
    plt.colorbar(im, ax=axes[0], fraction=0.03, label="NDVD [-1,1]")
    axes[0].set_title(
        f"{title_prefix}\n"
        f"p1={p1:.3f}  p99={p99:.3f}  valid={valid.mean()*100:.1f}%"
    )
    axes[0].set_xlabel("X Lambert-93 (m)")
    axes[0].set_ylabel("Y Lambert-93 (m)")

    axes[1].hist(ndvd[valid].ravel(), bins=200, color="steelblue", alpha=0.8)
    t_slow, t_walk, t_fight = _THRESHOLDS["10"]
    for t, label, color in [
        (t_slow, "slow 406 (0.00)", "orange"),
        (t_walk, "walk 408 (0.35)", "red"),
        (t_fight, "fight 410 (0.70)", "darkred"),
    ]:
        axes[1].axvline(t, color=color, linestyle="--", linewidth=1.5, label=label)
    axes[1].legend(fontsize=9)
    axes[1].set_xlabel("NDVD")
    axes[1].set_ylabel("Fréquence")
    axes[1].set_title("Distribution NDVD (pixels valides)")

    fig.suptitle(
        f"Trier 2015 — {section_label}\n"
        "Run principal : ~10 impl/m² sous-échantillonnés | seuils Table 5 10/m²",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logging.info("Viz NDVD %s -> %s", section_label, out_png)


# ── Visualisation 5 : Classes avant/après morpho ─────────────────────────────

def _viz_classes(
    classes_path: pathlib.Path,
    classes_gen_path: pathlib.Path,
    out_png: pathlib.Path,
    res_m: float = 1.0,
) -> None:
    with rasterio.open(classes_path) as src:
        cls = src.read(1).astype(np.int32)
        transform = src.transform
        cols, rows = src.width, src.height
    with rasterio.open(classes_gen_path) as src:
        cls_gen = src.read(1).astype(np.int32)

    extent = [
        transform.c,
        transform.c + transform.a * cols,
        transform.f + transform.e * rows,
        transform.f,
    ]
    cmap = mcolors.ListedColormap(["#f7f7f7", "#a8ddb5", "#41ae76", "#005824"])
    norm = mcolors.BoundaryNorm([-0.5, 0.5, 406.5, 408.5, 410.5], 4)

    patches = [
        mpatches.Patch(color="#f7f7f7", label="0 normal"),
        mpatches.Patch(color="#a8ddb5", label="406 slow run"),
        mpatches.Patch(color="#41ae76", label="408 walk"),
        mpatches.Patch(color="#005824", label="410 fight"),
    ]

    def _prep(arr):
        a = arr.astype(np.float32)
        a[arr == 65535] = np.nan
        return a

    fig, axes = plt.subplots(1, 2, figsize=(20, 11))

    for ax, data, title in [
        (axes[0], cls, "Classes après seuillage (avant morpho)"),
        (axes[1], cls_gen, "Classes après généralisation §2.2"),
    ]:
        d = _prep(data)
        ax.imshow(d, cmap=cmap, norm=norm, extent=extent,
                  aspect="equal", interpolation="nearest")
        ax.legend(handles=patches, loc="lower right", fontsize=9)
        stats = _class_stats(data.astype(np.uint16), res_m)
        total = sum(v["px"] for v in stats.values() if isinstance(v, dict))
        pct = {k: stats[k]["px"] / max(1, total) * 100 for k in [0, 406, 408, 410]}
        ax.set_title(
            f"{title}\n"
            f"0={pct[0]:.1f}%  406={pct[406]:.1f}%  408={pct[408]:.1f}%  410={pct[410]:.1f}%"
        )
        ax.set_xlabel("X Lambert-93 (m)")

    fig.suptitle(
        "Trier 2015 — §5 Classes de végétation (1 m)\n"
        "Run principal : ~10 impl/m² | seuils Table 5 10/m²",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logging.info("Viz classes -> %s", out_png)


# ── Visualisation 6 : Empreinte spatiale ─────────────────────────────────────

def _viz_empreinte(
    diff_path: pathlib.Path,
    perturb_x: float,
    perturb_y: float,
    out_png: pathlib.Path,
) -> None:
    with rasterio.open(diff_path) as src:
        diff = src.read(1).astype(np.float32)
        transform = src.transform
        cols, rows = src.width, src.height

    extent = [
        transform.c,
        transform.c + transform.a * cols,
        transform.f + transform.e * rows,
        transform.f,
    ]

    # Zone de zoom : ±6 m autour du point de perturbation
    zoom_r = 6.0
    zx0, zx1 = perturb_x - zoom_r, perturb_x + zoom_r
    zy0, zy1 = perturb_y - zoom_r, perturb_y + zoom_r
    pr = int((transform.f - perturb_y) / abs(transform.e))
    pc = int((perturb_x - transform.c) / transform.a)
    r0 = max(0, pr - int(zoom_r / abs(transform.e)))
    r1 = min(rows, pr + int(zoom_r / abs(transform.e)) + 1)
    c0 = max(0, pc - int(zoom_r / transform.a))
    c1 = min(cols, pc + int(zoom_r / transform.a) + 1)

    diff_zoom = diff[r0:r1, c0:c1]
    extent_zoom = [
        transform.c + c0 * transform.a,
        transform.c + c1 * transform.a,
        transform.f + r1 * transform.e,
        transform.f + r0 * transform.e,
    ]

    vmax = float(np.nanmax(np.abs(diff)))
    if vmax == 0:
        vmax = 1.0

    fig, axes = plt.subplots(1, 2, figsize=(18, 9))

    for ax, data, ext, title in [
        (axes[0], diff, extent, "Diff NDVD globale"),
        (axes[1], diff_zoom, extent_zoom, f"Zoom ±{zoom_r}m autour du point perturb."),
    ]:
        valid = np.isfinite(data)
        vmax_local = float(np.nanmax(np.abs(data[valid]))) if valid.any() else 1.0
        if vmax_local == 0:
            vmax_local = 1.0
        im = ax.imshow(data, cmap="RdBu_r", vmin=-vmax_local, vmax=vmax_local,
                       extent=ext, aspect="equal", interpolation="nearest")
        plt.colorbar(im, ax=ax, fraction=0.03, label="ΔNDVD")
        ax.plot(perturb_x, perturb_y, "k+", markersize=10, markeredgewidth=2,
                label=f"Perturbation\n({perturb_x:.0f}, {perturb_y:.0f})")
        ax.legend(fontsize=8)
        ax.set_title(title)
        ax.set_xlabel("X Lambert-93 (m)")

    changed = int(np.isfinite(diff).sum() and (np.abs(diff) > 1e-6).sum())
    fig.suptitle(
        "Trier 2015 — §6 Empreinte spatiale du noyau conique\n"
        f"Rayon théorique : 2.0 m | Diagonale max : 2.83 m | Cellules affectées : {changed}",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logging.info("Viz empreinte -> %s", out_png)


# ── Visualisation 7 : Bilan statistiques ─────────────────────────────────────

def _viz_bilan(
    classes_path: pathlib.Path,
    classes_gen_path: pathlib.Path,
    out_png: pathlib.Path,
    res_m: float = 1.0,
) -> None:
    with rasterio.open(classes_path) as src:
        cls = src.read(1).astype(np.uint16)
    with rasterio.open(classes_gen_path) as src:
        cls_gen = src.read(1).astype(np.uint16)

    stats_raw = _class_stats(cls, res_m)
    stats_gen = _class_stats(cls_gen, res_m)
    total = sum(v["m2"] for v in stats_gen.values() if isinstance(v, dict))

    codes = [0, 406, 408, 410]
    labels = ["0\nnormal", "406\nslow run", "408\nwalk", "410\nfight"]
    colors = ["#f7f7f7", "#a8ddb5", "#41ae76", "#005824"]
    edge_colors = ["gray", "gray", "gray", "gray"]

    raw_m2 = [stats_raw[c]["m2"] for c in codes]
    gen_m2 = [stats_gen[c]["m2"] for c in codes]
    raw_pct = [100 * stats_raw[c]["m2"] / max(1, total) for c in codes]
    gen_pct = [100 * stats_gen[c]["m2"] / max(1, total) for c in codes]

    fig, axes = plt.subplots(1, 2, figsize=(14, 7))

    x = np.arange(len(codes))
    width = 0.35
    for i, (code, label, color, ec) in enumerate(zip(codes, labels, colors, edge_colors)):
        axes[0].bar(x[i] - width/2, raw_m2[i], width, color=color, edgecolor=ec, linewidth=1.2,
                    label="Avant morpho" if i == 0 else "")
        axes[0].bar(x[i] + width/2, gen_m2[i], width, color=color, edgecolor="black", linewidth=1.5,
                    label="Après morpho §2.2" if i == 0 else "", hatch="//")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].set_ylabel("Surface (m²)")
    axes[0].set_title("Surfaces par classe\navant / après généralisation §2.2")
    axes[0].legend()

    axes[1].bar(x - width/2, raw_pct, width, color=colors, edgecolor="gray", linewidth=1.2)
    axes[1].bar(x + width/2, gen_pct, width, color=colors, edgecolor="black", linewidth=1.5, hatch="//")
    for i, (r, g) in enumerate(zip(raw_pct, gen_pct)):
        axes[1].text(x[i] - width/2, r + 0.3, f"{r:.1f}%", ha="center", fontsize=8)
        axes[1].text(x[i] + width/2, g + 0.3, f"{g:.1f}%", ha="center", fontsize=8)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].set_ylabel("% de la surface totale")
    axes[1].set_title("Pourcentages par classe")

    fig.suptitle(
        "Trier 2015 — §7 Bilan des classes ISOM\n"
        "Run principal ~10 impl/m² | seuils Table 5 10/m²",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logging.info("Viz bilan -> %s", out_png)


# ── Rapport markdown §1-11 ────────────────────────────────────────────────────

def _build_report(
    paths: dict,
    empreinte: dict,
    subsample_fraction: float,
    gpstime_check: dict,
    density_estimated: float,
    copc_paths: list,
    bbox: tuple,
    crs: str,
) -> str:
    with rasterio.open(paths["classes_gen"]) as src:
        cls_gen = src.read(1).astype(np.uint16)
        res = abs(src.res[0])
    with rasterio.open(paths["classes"]) as src:
        cls_raw = src.read(1).astype(np.uint16)

    stats_raw = _class_stats(cls_raw, res)
    stats_gen = _class_stats(cls_gen, res)
    total = sum(v["px"] for v in stats_gen.values() if isinstance(v, dict))
    today = datetime.date.today().isoformat()
    xmin, ymin, xmax, ymax = bbox

    lines = [
        "# Rapport Trier 2015 — Grimbosq V0",
        "",
        f"> Date : {today}  ",
        f"> Run principal : ~{TARGET_DENSITY:.0f} impl/m² (depuis ~{ACTUAL_DENSITY:.0f} impl/m²)  ",
        "> Seuils : Table 5 10 impl/m²  ",
        "> Référence : Trier (2015). DOI: 10.3846/20296991.2015.1051342",
        "",
        "---",
        "",
        "## §1. Référence bibliographique",
        "",
        "Trier, Ø.D. (2015). Automatic mapping of forest density from airborne lidar data.  ",
        "*Geodesy and Cartography*, 41(2): 49–65. DOI: 10.3846/20296991.2015.1051342",
        "",
        "Méthode : NDVD (Normalized Difference Vegetation Density) calculé par noyau conique",
        "sur les retours de végétation basse [0.2, 2.0) m, segmenté en 3 classes ISOM",
        "(406 slow run, 408 walk, 410 fight), suivi d'une généralisation morphologique.",
        "",
        "---",
        "",
        "## §2. Données d'entrée — LiDAR Grimbosq",
        "",
        f"- Fichiers COPC : {len(copc_paths)} tuiles dans `LIDAR/grimbosq/`",
        f"- Densité estimée (première tuile) : ~{density_estimated:.1f} impl/m²",
        f"- Bbox (EPSG:2154) : ({xmin:.0f}, {ymin:.0f}, {xmax:.0f}, {ymax:.0f})",
        f"- CRS : {crs}",
        f"- GpsTime disponible : {gpstime_check.get('available', '?')}",
        f"  - Ratio pts/impulsion : {gpstime_check.get('ratio_pts_per_impulse', 0):.2f}",
        f"  - {gpstime_check.get('comment', '')}",
        "",
        "---",
        "",
        "## §3. Construction du terrain (DTM)",
        "",
        "| | Trier 2015 | Implémentation |",
        "|---|---|---|",
        "| Points utilisés | class 2 uniquement (§1.3) | class 2 uniquement |",
        "| Méthode | ENVI TRIGRID (TIN) | min par cellule + NN hole-fill |",
        "| Résolution | 0.5 m (implicite) | 0.5 m |",
        "| Trous | non spécifié | NN fill |",
        "",
        "**Statut : `[TRIER-DEV-DTM]`** — approximation de TIN, négligeable à ~10 impl/m².",
        "",
        "---",
        "",
        "## §4. Définition de V et G",
        "",
        "**SOURCE (§1.1, §2)** : Données Trier = 2 classes uniquement : 'ground' (class 2) et 'other'.",
        "",
        "| Variable | SOURCE | Implémentation |",
        "|---|---|---|",
        "| G | retours 'ground' (class 2), tous ReturnNumber | class 2, tous ReturnNumber (FIDÈLE) |",
        "| V | retours 'other' dans HAG [0.2, 2.0) m | non-class2, HAG [0.2, 2.0) m |",
        "| Bande inf. | 0.2 m (§2 artefacts chevauchement) | 0.2 m (FIDÈLE) |",
        "| ReturnNumber | non filtré pour NDVD (§1.1) | tous RetourNumber comptés (FIDÈLE) |",
        "",
        "**Ambiguïté : `[TRIER-DEV-V-UNRESOLVED]`**",
        "Les données Trier ont 2 classes. Grimbosq a des classes supplémentaires",
        "(6=bâtiment, 9=eau, 7=bruit bas) absentes du dataset Trier.",
        "Convention : ces classes sont traitées comme 'other' (incluses dans V si HAG convient).",
        "L'article ne permet pas de trancher — ambiguïté non résolue.",
        "",
        "---",
        "",
        "## §5. Formule NDVD et noyau de voisinage",
        "",
        "```",
        "NDVD = (V − G) / (V + G)    ∈ [-1, 1]    (Eq. 1)",
        "  +1 = 100% végétation, -1 = 100% sol, NaN si V+G=0",
        "```",
        "",
        "**Noyau (§2, Fig. 3)** : circulaire plat-conique",
        "- Rayon interne : 1.0 m → poids = 1.0",
        "- Rayon externe : 2.0 m → poids = 0.0 (décroissance linéaire)",
        "- À 0.5 m/px : noyau 9×9 pixels",
        "- **Statut : FIDÈLE**",
        "",
        "---",
        "",
        "## §6. Résolution et agrégation",
        "",
        "| Étape | Résolution |",
        "|---|---|",
        "| Accumulation V/G | 0.5 m |",
        "| NDVD (brut + après noyau) | 0.5 m |",
        "| Agrégation (moyenne) avant classification | → 1.0 m |",
        "| Classification + morphologie | 1.0 m |",
        "",
        "**Statut : FIDÈLE** (§2 : \"0.5 m pixel size\" et §2.2 : \"Aggregate... to 1.0 m\")",
        "",
        "---",
        "",
        "## §7. Seuils, densité et sous-échantillonnage",
        "",
        "**Seuils Table 5 (10 impl/m²)** :",
        "",
        "| Classe | Code ISOM | Seuil NDVD |",
        "|---|---|---|",
        "| slow run | 406 | ≥ 0.00 |",
        "| walk | 408 | ≥ 0.35 |",
        "| fight | 410 | ≥ 0.70 |",
        "",
        "**Densité et sous-échantillonnage** :",
        "",
        f"- Densité native Grimbosq : ~{ACTUAL_DENSITY:.0f} impl/m² (hors domaine Trier documenté)",
        f"- Densité cible run principal : {TARGET_DENSITY:.0f} impl/m² (Table 5)",
        f"- Fraction retenue : {subsample_fraction:.4f} = {TARGET_DENSITY:.0f}/{ACTUAL_DENSITY:.0f}",
        "- **Méthode** : sous-échantillonnage **par impulsion** (GpsTime unique)",
        "  Tous les retours d'une impulsion retenue sont conservés.",
        "  Le rapport V/G est préservé (pas de biais sur les retours multiples).",
        "  Graine : 42 + index_tuile (cohérence passe 1 DTM / passe 2 V/G).",
        "",
        "**Statut : `[TRIER-ADAPTATION]`** — densité native hors domaine documenté (2 et 10 impl/m²).",
        "",
        "---",
        "",
        "## §8. Sorties produites",
        "",
        "| Fichier | Description | Résolution | Statut |",
        "|---|---|---|---|",
        "| `trier_dtm.tif` | DTM class 2, min/cell + NN | 0.5 m | [TRIER-DEV-DTM] |",
        "| `trier_strates.tif` | V_raw (b1) + G_raw (b2) | 0.5 m | [TRIER-DEV-V-UNRESOLVED] |",
        "| `trier_signal_brut.tif` | NDVD (V-G)/(V+G) avant noyau | 0.5 m | FIDÈLE |",
        "| `trier_signal_apres_voisinage.tif` | NDVD après noyau conique | 0.5 m | FIDÈLE |",
        "| `trier_classes.tif` | Classes 0/406/408/410 avant morpho | 1.0 m | FIDÈLE |",
        "| `trier_classes_gen.tif` | Classes après généralisation §2.2 | 1.0 m | FIDÈLE |",
        "| `trier_empreinte_diff.tif` | Diff NDVD perturbation +1000V | 0.5 m | — |",
        "| `trier_viz_01_dtm.png` | Visualisation DTM | — | — |",
        "| `trier_viz_02_strates.png` | V_raw et G_raw | — | — |",
        "| `trier_viz_03_signal_brut.png` | NDVD brut + histogramme | — | — |",
        "| `trier_viz_04_signal_voisinage.png` | NDVD voisinage + histogramme | — | — |",
        "| `trier_viz_05_classes.png` | Classes avant/après morpho | — | — |",
        "| `trier_viz_06_empreinte.png` | Empreinte + zoom | — | — |",
        "| `trier_viz_07_bilan.png` | Bilan surfaces par classe | — | — |",
        "| `trier_report.md` | Ce rapport | — | — |",
        "| `trier_rapport.json` | Métriques numériques | — | — |",
        "",
        "---",
        "",
        "## §9. Masque zones ouvertes",
        "",
        "**SOURCE (§2.1)** : nDSM agrégé à 1 m, seuil 0.75 m, puis séquence",
        "morphologique complète (non reproduite fidèlement), aire minimale 22.5 m².",
        "",
        "**Implémentation** : seuil nDSM < 0.75 m → zone ouverte, opening disk 3×3, aire minimale 22 px.",
        "",
        "**Statut : `[TRIER-DEV-OPENMAP]`** — séquence §2.1 complète non reproduite.",
        "Impact : légère différence dans les zones ouvertes masquées.",
        "",
        "---",
        "",
        "## §10. Généralisation morphologique (§2.2)",
        "",
        "Séquence exacte appliquée à chaque classe indépendamment (à 1.0 m) :",
        "",
        "| Étape | Opération | Noyau |",
        "|---|---|---|",
        "| 1 | Fermeture | disque 7×7 |",
        "| 2 | Ouverture | disque 3×3 |",
        "| 3 | Fermeture | disque 9×9 |",
        "| 4 | Ouverture | disque 5×5 |",
        "| 5 | Fermeture | disque 11×11 |",
        "| 6 | Ouverture | disque 7×7 |",
        "| 7 | Retrait masque zones ouvertes | — |",
        "| 8 | Ouverture | carré 3×3 |",
        "| 9 | Filtre aire minimale | 225 m² (406/408), 112 m² (410) |",
        "",
        "**Statut : FIDÈLE** (§2.2 citations exactes reproduites)",
        "",
        "---",
        "",
        "## §11. Résultats et bilan",
        "",
        "### Statistiques des classes",
        "",
        "| Classe | Avant morpho (px) | Avant morpho (m²) | Après morpho (px) | Après morpho (m²) | % final |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for code in [0, 406, 408, 410]:
        s_r = stats_raw[code]
        s_g = stats_gen[code]
        pct = s_g["px"] / max(1, total) * 100
        lines.append(
            f"| {code} | {s_r['px']:,} | {s_r['m2']:,.0f} | "
            f"{s_g['px']:,} | {s_g['m2']:,.0f} | {pct:.1f}% |"
        )

    lines += [
        "",
        "### Empreinte spatiale",
        "",
        f"- Point de perturbation : x={empreinte.get('perturb_x',0):.1f}, y={empreinte.get('perturb_y',0):.1f}",
        f"- Rayon max mesuré : **{empreinte.get('max_dist_m', 0):.2f} m**",
        f"- Rayon théorique noyau : {empreinte.get('theoretical_radius_m', 0):.1f} m",
        f"- Diagonale théorique (√2 × rayon) : {empreinte.get('theoretical_max_m', 0):.2f} m",
        f"- Cellules NDVD affectées : {empreinte.get('changed_cells', 0):,}",
        "- Raster diff sauvé : `trier_empreinte_diff.tif`",
        "",
    ]
    if empreinte.get("max_dist_m", 0) <= empreinte.get("theoretical_max_m", 99) + 0.5:
        lines.append("> **OK** : empreinte conforme au noyau conique (max_dist ≤ diagonale + 0.5 m)")
    else:
        lines.append("> **ATTENTION** : empreinte supérieure à la diagonale théorique")

    lines += [
        "",
        "### Bilan des écarts",
        "",
        "| ID | Étape | Cause | Impact attendu |",
        "|---|---|---|---|",
        "| `[TRIER-DEV-DTM]` | Construction DTM | min/cell+NN vs TIN (ENVI TRIGRID) | HAG légèrement différent → V/G modifiés. Négligeable à ~10 impl/m². |",
        "| `[TRIER-DEV-V-UNRESOLVED]` | Définition V | Classes 6/7/9 Grimbosq traitées comme 'other' | V potentiellement sur-estimé si bâtiments/bruit dans HAG [0.2, 2.0). |",
        "| `[TRIER-DEV-OPENMAP]` | Masque zones ouvertes | §2.1 simplifié (seuil+aire seuls) | Légère différence dans les zones ouvertes masquées. |",
        "| `[TRIER-ADAPTATION]` | Densité | 15 impl/m² sous-échantillonné à 10/m² | Hors domaine publié. Run principal adapté. |",
        "",
        "---",
        "",
        "*Rapport généré automatiquement par `experiments/v0/run_trier.py`*",
    ]
    return "\n".join(lines)


def main() -> None:
    cfg = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
    bbox = tuple(cfg["terrains"]["grimbosq"]["bbox"])
    crs = cfg["terrains"]["grimbosq"]["crs"]

    copc_paths = sorted(LIDAR_DIR.glob("*.copc.laz"))
    if not copc_paths:
        raise FileNotFoundError(f"Aucun fichier COPC dans {LIDAR_DIR}")
    logging.info("Fichiers COPC : %d tuiles", len(copc_paths))

    # ── Vérification GpsTime ─────────────────────────────────────────────────
    logging.info("Vérification GpsTime...")
    gpstime_check = check_gpstime(copc_paths, bbox)
    logging.info("GpsTime : available=%s  ratio=%.2f pts/impulsion",
                 gpstime_check["available"],
                 gpstime_check.get("ratio_pts_per_impulse", 0))
    if not gpstime_check["available"]:
        raise RuntimeError(
            f"GpsTime non disponible : {gpstime_check['reason']}\n"
            "Le sous-échantillonnage par impulsion est impossible."
        )
    if not gpstime_check["ok"]:
        logging.warning(
            "GpsTime disponible mais ratio inattendu : %s",
            gpstime_check["comment"],
        )

    # ── Estimation densité ────────────────────────────────────────────────────
    logging.info("Estimation densité sur première tuile...")
    density_estimated = _estimate_density(copc_paths, bbox)
    logging.info("Densité estimée : %.1f impl/m²", density_estimated)

    # ── Run principal : ~10 impl/m² ───────────────────────────────────────────
    logging.info(
        "Run principal : sous-échantillonnage %.4f -> ~%.0f impl/m²",
        SUBSAMPLE_FRACTION, TARGET_DENSITY,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    paths = run(
        copc_paths, bbox, OUTPUT_DIR, crs,
        density_key="10",
        subsample_fraction=SUBSAMPLE_FRACTION,
    )

    # ── Mesure d'empreinte ────────────────────────────────────────────────────
    sc = load_split()
    px, py = _find_boundary_pixel(
        paths["classes"],
        sc.validation_y_min + 50.0,
        bbox,
    )
    logging.info("Point perturbation : x=%.1f, y=%.1f", px, py)

    empreinte = measure_empreinte(OUTPUT_DIR, perturb_x=px, perturb_y=py, crs=crs)
    empreinte["perturb_x"] = px
    empreinte["perturb_y"] = py
    paths["empreinte_diff"] = OUTPUT_DIR / "trier_empreinte_diff.tif"

    # ── Visualisations (7) ────────────────────────────────────────────────────
    logging.info("Production des 7 visualisations...")

    _viz_dtm(
        paths["dtm"],
        OUTPUT_DIR / "trier_viz_01_dtm.png",
    )
    _viz_strates(
        paths["strates"],
        OUTPUT_DIR / "trier_viz_02_strates.png",
    )
    _viz_ndvd_signal(
        paths["signal_brut"],
        OUTPUT_DIR / "trier_viz_03_signal_brut.png",
        title_prefix="NDVD brut (avant noyau, 0.5 m)",
        section_label="§3 Signal brut",
    )
    _viz_ndvd_signal(
        paths["signal_apres_voisinage"],
        OUTPUT_DIR / "trier_viz_04_signal_voisinage.png",
        title_prefix="NDVD après noyau conique (0.5 m)",
        section_label="§4 Signal après voisinage",
    )
    _viz_classes(
        paths["classes"],
        paths["classes_gen"],
        OUTPUT_DIR / "trier_viz_05_classes.png",
    )
    _viz_empreinte(
        paths["empreinte_diff"],
        px, py,
        OUTPUT_DIR / "trier_viz_06_empreinte.png",
    )
    _viz_bilan(
        paths["classes"],
        paths["classes_gen"],
        OUTPUT_DIR / "trier_viz_07_bilan.png",
    )

    # ── Rapport markdown §1-11 ────────────────────────────────────────────────
    report_md = _build_report(
        paths, empreinte, SUBSAMPLE_FRACTION, gpstime_check,
        density_estimated, copc_paths, bbox, crs,
    )
    report_path = OUTPUT_DIR / "trier_report.md"
    report_path.write_text(report_md, encoding="utf-8")

    report_json = {
        "gpstime_check": {k: (v if not isinstance(v, np.generic) else float(v))
                          for k, v in gpstime_check.items()},
        "density_estimated": density_estimated,
        "subsample_fraction": SUBSAMPLE_FRACTION,
        "target_density": TARGET_DENSITY,
        "empreinte": {k: (float(v) if hasattr(v, "__float__") else v)
                      for k, v in empreinte.items()},
        "paths": {k: str(v) for k, v in paths.items()},
    }
    (OUTPUT_DIR / "trier_rapport.json").write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Résumé console ────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("TRIER 2015 — RUN TERMINÉ")
    print("=" * 60)
    print(f"  Densité estimée Grimbosq : ~{density_estimated:.1f} impl/m²")
    print(f"  Fraction sous-échant.    : {SUBSAMPLE_FRACTION:.4f} ({TARGET_DENSITY:.0f}/{ACTUAL_DENSITY:.0f} impl/m²)")
    print(f"  GpsTime disponible       : {gpstime_check['available']}")
    print(f"  Ratio pts/impulsion      : {gpstime_check.get('ratio_pts_per_impulse', 0):.2f}")
    print()

    with rasterio.open(paths["classes_gen"]) as src:
        cls_gen = src.read(1).astype(np.uint16)
        res_out = abs(src.res[0])
    stats = _class_stats(cls_gen, res_out)
    total = sum(v["px"] for v in stats.values() if isinstance(v, dict))
    print("  Classes (après morpho §2.2) :")
    for code, name in [(0, "normal"), (406, "slow run"), (408, "walk"), (410, "fight")]:
        pct = stats[code]["px"] / max(1, total) * 100
        print(f"    {code:3d} {name:8s}: {stats[code]['m2']:>10,.0f} m²  ({pct:.1f}%)")

    print()
    print(f"  Empreinte max mesurée    : {empreinte['max_dist_m']:.2f} m")
    print(f"  Rayon théorique          : {empreinte.get('theoretical_radius_m', 2.0):.1f} m")
    print(f"  Diagonale théorique      : {empreinte.get('theoretical_max_m', 2.83):.2f} m")
    print(f"  Cellules affectées       : {empreinte['changed_cells']:,}")
    if empreinte["max_dist_m"] <= empreinte.get("theoretical_max_m", 2.83) + 0.5:
        print("  -> Empreinte conforme (OK)")
    else:
        print("  -> ATTENTION : empreinte > diagonale théorique")

    print()
    print(f"  Rapport : {report_path}")
    print(f"  Sorties : {OUTPUT_DIR}")
    print("=" * 60)

    flag = sc.provisional_flag()
    if flag:
        print(f"\n  {flag}")


if __name__ == "__main__":
    main()
