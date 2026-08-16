"""Matrice de confusion pixel-niveau pipeline vs FFCO — diagnostic inter-classes.

Objectif : quantifier le biais d'erreur entre classes 406/408/410 et trouver
les seuils T_408/T_410 optimaux pour le recall classe-exacte, à any-class constant.

Sorties :
  - Matrice de confusion (console) : 4x4 en ha (blank/406/408/410)
  - output/confusion_interclass.png : histogrammes HAG par cellule inter-classe
  - output/threshold_sweep_408.png : class-specific recall 408 vs T_408
  - output/threshold_sweep_410.png : class-specific recall 410 vs T_410

Usage :
  python scripts/diag/confusion_interclass.py
"""
from __future__ import annotations

import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import rowcol
import shapely.geometry as sg
from shapely.ops import unary_union

ROOT = pathlib.Path(__file__).parent.parent.parent
OUTPUT = ROOT / "output"
FFCO_GPKG = ROOT / "grimbosq.gpkg"

# Encodage classified.tif : 0=blank 85=406 170=408 255=410
_PIPE_CODE = {0: 0, 85: 406, 170: 408, 255: 410}
_FFCO_KEYWORDS = {406: "course lente", 408: "marche", 410: "progression"}
_CLASSES = [406, 408, 410]
# Couleurs pour histogrammes
_COLORS = {406: "#2196F3", 408: "#4CAF50", 410: "#FF9800"}


# ─────────────────────────────────────────────────────────────────────────────
# Chargement FFCO
# ─────────────────────────────────────────────────────────────────────────────

def _load_ffco_by_class(
    gpkg: pathlib.Path,
) -> dict[int, list[sg.Polygon]]:
    """Charge les polygones FFCO par classe via OGR (robuste latin-1)."""
    try:
        from osgeo import ogr as _ogr
        import json as _json
    except ImportError:
        raise RuntimeError("osgeo.ogr requis — utiliser miniconda3")

    _ogr.UseExceptions()
    ds = _ogr.Open(str(gpkg))
    if ds is None:
        raise FileNotFoundError(f"OGR ne peut pas ouvrir {gpkg}")

    areas_lyr = None
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        try:
            name = lyr.GetName().lower()
        except Exception:
            name = ""
        if "areas" in name:
            areas_lyr = lyr
            break
    if areas_lyr is None:
        raise ValueError("Aucune couche '*areas' dans le GPKG")

    ffco: dict[int, list[sg.Polygon]] = {cls: [] for cls in _CLASSES}
    feat = areas_lyr.GetNextFeature()
    while feat is not None:
        try:
            raw = feat.ExportToJson()
            props = _json.loads(raw).get("properties", {})
        except Exception:
            feat = areas_lyr.GetNextFeature()
            continue
        label = ""
        for key, val in props.items():
            if val and isinstance(val, str):
                label = val.lower()
                break
        matched = 0
        for cls, kw in _FFCO_KEYWORDS.items():
            if kw in label:
                matched = cls
                break
        if matched:
            geom_ref = feat.GetGeometryRef()
            if geom_ref is not None:
                try:
                    geom = sg.shape(
                        _json.loads(geom_ref.ExportToJson())
                    )
                    if geom.is_valid and not geom.is_empty:
                        ffco[matched].append(geom)
                except Exception:
                    pass
        feat = areas_lyr.GetNextFeature()
    return ffco


# ─────────────────────────────────────────────────────────────────────────────
# Rasterisation FFCO sur la grille du classified.tif
# ─────────────────────────────────────────────────────────────────────────────

def _rasterize_ffco(
    ffco: dict[int, list[sg.Polygon]],
    transform: rasterio.transform.Affine,
    shape: tuple[int, int],
) -> np.ndarray:
    """Produit un raster uint16 encodé en ISOM (0/406/408/410)."""
    result = np.zeros(shape, dtype=np.uint16)
    for cls in _CLASSES:
        polys = ffco[cls]
        if not polys:
            continue
        burned = rasterize(
            [(g, cls) for g in polys],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint16,
        )
        result[burned == cls] = cls
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Matrice de confusion
# ─────────────────────────────────────────────────────────────────────────────

def _build_confusion(
    pipe_cls: np.ndarray,
    ffco_cls: np.ndarray,
    hull_mask: np.ndarray,
    px_area_m2: float,
) -> dict[tuple[int, int], float]:
    """Retourne confusion[ffco_cls][pipe_cls] = ha."""
    rows_cols = [(f, p) for f in [0, 406, 408, 410] for p in [0, 406, 408, 410]]
    confusion: dict[tuple[int, int], float] = {}
    for fc, pc in rows_cols:
        mask = hull_mask & (ffco_cls == fc) & (pipe_cls == pc)
        confusion[(fc, pc)] = float(np.sum(mask) * px_area_m2 / 1e4)
    return confusion


def _print_confusion(
    confusion: dict[tuple[int, int], float],
) -> None:
    labels = [0, 406, 408, 410]
    label_str = {0: "blank", 406: "406", 408: "408", 410: "410"}

    print("\n=== Matrice de confusion (ha) — lignes=FFCO, colonnes=pipeline ===")
    header = f"{'FFCO \\ pipe':>12}" + "".join(f"{label_str[p]:>8}" for p in labels) + f"{'TOTAL':>8}"
    print(header)
    for fc in labels:
        row_total = sum(confusion.get((fc, pc), 0.0) for pc in labels)
        row = f"{label_str[fc]:>12}" + "".join(
            f"{confusion.get((fc, pc), 0.0):>8.1f}" for pc in labels
        ) + f"{row_total:>8.1f}"
        print(row)
    col_totals = [sum(confusion.get((fc, pc), 0.0) for fc in labels) for pc in labels]
    total = sum(col_totals)
    print(f"{'TOTAL':>12}" + "".join(f"{v:>8.1f}" for v in col_totals) + f"{total:>8.1f}")

    print("\n=== Erreurs inter-classes (FFCO detectee mais mauvaise classe) ===")
    for fc in _CLASSES:
        total_fc = sum(confusion.get((fc, pc), 0.0) for pc in labels)
        correct = confusion.get((fc, fc), 0.0)
        wrong = {pc: confusion.get((fc, pc), 0.0) for pc in _CLASSES if pc != fc}
        missing = confusion.get((fc, 0), 0.0)
        print(f"  FFCO {fc}: total={total_fc:.1f}ha  correct={correct:.1f}ha "
              f" wrong=" + " ".join(f"{pc}:{v:.1f}ha" for pc, v in wrong.items())
              + f"  missing={missing:.1f}ha")


# ─────────────────────────────────────────────────────────────────────────────
# HAG distributions par cellule inter-classe
# ─────────────────────────────────────────────────────────────────────────────

def _plot_interclass_hag(
    smoothed: np.ndarray,
    pipe_cls: np.ndarray,
    ffco_cls: np.ndarray,
    hull_mask: np.ndarray,
    out_path: pathlib.Path,
) -> None:
    """Histogrammes HAG pour les erreurs de classification inter-classes."""
    pairs = [
        (408, 406, "FFCO 408 classe par pipe en 406"),
        (410, 408, "FFCO 410 classe par pipe en 408"),
        (406, 408, "FFCO 406 classe par pipe en 408"),
        (408, 410, "FFCO 408 classe par pipe en 410"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("HAG distributions — erreurs de classification inter-classes", fontsize=13)

    for ax, (fc, pc, title) in zip(axes.flat, pairs):
        mask = hull_mask & (ffco_cls == fc) & (pipe_cls == pc)
        n = int(np.sum(mask))
        vals = smoothed[mask]
        correct_mask = hull_mask & (ffco_cls == fc) & (pipe_cls == fc)
        vals_correct = smoothed[correct_mask]

        if n == 0:
            ax.set_title(f"{title}\n(aucun pixel)")
            ax.text(0.5, 0.5, "n=0", ha="center", va="center", transform=ax.transAxes)
            continue

        bins = np.linspace(0, 1, 51)
        ax.hist(vals, bins=bins, color=_COLORS[pc], alpha=0.6,
                label=f"Erreur (FFCO {fc}, pipe {pc}): n={n:,}", density=True)
        if len(vals_correct) > 0:
            ax.hist(vals_correct, bins=bins, color=_COLORS[fc], alpha=0.5,
                    label=f"Correct (FFCO {fc}, pipe {fc}): n={len(vals_correct):,}",
                    density=True)

        # Seuil actuel inter-classes
        if (fc == 408 and pc == 406) or (fc == 406 and pc == 408):
            ax.axvline(0.45, color="red", lw=1.5, ls="--", label="T_408=0.45")
        elif (fc == 410 and pc == 408) or (fc == 408 and pc == 410):
            ax.axvline(0.85, color="red", lw=1.5, ls="--", label="T_410=0.85")

        ax.set_title(title)
        ax.set_xlabel("HAG density (lissé, normalisé)")
        ax.set_ylabel("Densité")
        ax.legend(fontsize=7)
        p50 = float(np.median(vals)) if len(vals) > 0 else 0
        ax.set_title(f"{title}\n(n={n:,}, mediane={p50:.3f})", fontsize=9)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"HAG interclasse -> {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Sweep de seuils T_408/T_410
# ─────────────────────────────────────────────────────────────────────────────

def _sweep_threshold(
    smoothed: np.ndarray,
    ffco_cls: np.ndarray,
    hull_mask: np.ndarray,
    px_area_m2: float,
    fixed_t406: float = 0.20,
    fixed_t410: float = 0.85,
    sweep_param: str = "T_408",
) -> None:
    """Balaye T_408 (ou T_410) et trace recall any-class + class-specific."""
    if sweep_param == "T_408":
        sweep_values = np.linspace(0.20, 0.70, 51)
        fixed_other = fixed_t410
        target_cls = 408
        title = f"Sweep T_408 (T_406=0.20 fixe, T_410={fixed_t410} fixe)"
        out_path = OUTPUT / "threshold_sweep_408.png"
    else:  # T_410
        sweep_values = np.linspace(0.45, 0.99, 55)
        fixed_other = 0.45  # T_408 courant
        target_cls = 410
        title = f"Sweep T_410 (T_406=0.20 fixe, T_408=0.45 fixe)"
        out_path = OUTPUT / "threshold_sweep_410.png"

    recall_any: list[float] = []
    recall_exact: list[float] = []
    recall_406_any: list[float] = []

    ffco_target = hull_mask & (ffco_cls == target_cls)
    total_target = float(np.sum(ffco_target))
    if total_target == 0:
        print(f"Aucun pixel FFCO {target_cls} dans le hull")
        return

    ffco_406 = hull_mask & (ffco_cls == 406)
    total_406 = float(np.sum(ffco_406))

    for t in sweep_values:
        # Reclassification avec le seuil balayé
        if sweep_param == "T_408":
            t408, t410 = t, fixed_t410
        else:
            t408, t410 = fixed_other, t

        pipe = np.zeros_like(smoothed, dtype=np.uint16)
        pipe[smoothed > fixed_t406] = 406
        pipe[smoothed > t408] = 408
        pipe[smoothed > t410] = 410

        # Recall any-class sur la classe cible (fraction couverte par n'importe quelle classe)
        detected_target = ffco_target & (pipe > 0)
        recall_any.append(float(np.sum(detected_target)) / total_target)

        # Recall classe exacte (pipe == target_cls sur pixels FFCO target_cls)
        correct_target = ffco_target & (pipe == target_cls)
        recall_exact.append(float(np.sum(correct_target)) / total_target)

        # Recall any-class 406 (doit rester stable si le seuil ne touche pas T_406)
        if total_406 > 0:
            det_406 = ffco_406 & (pipe > 0)
            recall_406_any.append(float(np.sum(det_406)) / total_406)
        else:
            recall_406_any.append(0.0)

    # Indice actuel
    if sweep_param == "T_408":
        current_t = 0.45
    else:
        current_t = 0.85
    current_idx = int(np.argmin(np.abs(sweep_values - current_t)))
    best_exact_idx = int(np.argmax(recall_exact))
    best_t = float(sweep_values[best_exact_idx])

    print(f"\n=== Sweep {sweep_param} ===")
    print(f"  T actuel = {current_t:.2f} : recall_any={recall_any[current_idx]:.1%} "
          f"recall_exact={recall_exact[current_idx]:.1%}")
    print(f"  T optimal = {best_t:.2f} : recall_any={recall_any[best_exact_idx]:.1%} "
          f"recall_exact={recall_exact[best_exact_idx]:.1%}")
    print(f"  Any-class 406 au T optimal = {recall_406_any[best_exact_idx]:.1%} "
          f"(vs actuel {recall_406_any[current_idx]:.1%}) — doit rester stable")

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(sweep_values, recall_any, "b-", lw=2, label=f"Recall any-class {target_cls}")
    ax.plot(sweep_values, recall_exact, "g-", lw=2, label=f"Recall classe exacte {target_cls}")
    ax.plot(sweep_values, recall_406_any, "r--", lw=1.5, label="Recall any-class 406 (doit etre stable)")
    ax.axvline(current_t, color="gray", ls="--", lw=1, label=f"T actuel = {current_t:.2f}")
    ax.axvline(best_t, color="green", ls=":", lw=2,
               label=f"T optimal = {best_t:.2f} (recall_exact max)")
    ax.set_xlabel(sweep_param)
    ax.set_ylabel("Recall (fraction pixels FFCO)")
    ax.set_title(title)
    ax.legend()
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Sweep -> {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Chargement rasters ────────────────────────────────────────────────────
    smoothed_path = OUTPUT / "density_hag_smoothed.tif"
    classified_path = OUTPUT / "density_hag_classified.tif"

    if not smoothed_path.exists():
        raise FileNotFoundError(f"Absent : {smoothed_path}")
    if not classified_path.exists():
        raise FileNotFoundError(f"Absent : {classified_path}")

    print("Chargement rasters...")
    with rasterio.open(smoothed_path) as ds:
        smoothed = ds.read(1).astype(np.float32)
        transform = ds.transform
        profile = ds.profile.copy()
        nodata = ds.nodata
        shape = (ds.height, ds.width)

    with rasterio.open(classified_path) as ds:
        classified_raw = ds.read(1)

    # Masque nodata
    nodata_mask = (smoothed == nodata) if nodata is not None else np.zeros(shape, dtype=bool)
    smoothed[nodata_mask] = 0.0

    # Décode classified 0/85/170/255 → 0/406/408/410
    pipe_cls = np.zeros(shape, dtype=np.uint16)
    pipe_cls[classified_raw == 85] = 406
    pipe_cls[classified_raw == 170] = 408
    pipe_cls[classified_raw == 255] = 410

    px_area_m2 = abs(transform.a * transform.e)
    print(f"  Résolution : {abs(transform.a):.1f}m  "
          f"Shape : {shape[0]}x{shape[1]}  "
          f"Pixels : {shape[0]*shape[1]:,}")

    # ── Chargement FFCO ───────────────────────────────────────────────────────
    print(f"Chargement FFCO : {FFCO_GPKG.name} ...")
    ffco = _load_ffco_by_class(FFCO_GPKG)
    for cls in _CLASSES:
        print(f"  {cls} : {len(ffco[cls])} polygones")

    # ── Rasterisation FFCO ────────────────────────────────────────────────────
    print("Rasterisation FFCO ...")
    ffco_cls = _rasterize_ffco(ffco, transform, shape)

    # ── Hull FFCO (union de tous les polygones) ───────────────────────────────
    all_polys = [g for polys in ffco.values() for g in polys]
    if not all_polys:
        raise ValueError("Aucun polygone FFCO chargé")
    hull = unary_union(all_polys).convex_hull
    hull_raster = rasterize(
        [(hull, 1)],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    hull_mask = (hull_raster == 1) & ~nodata_mask
    print(f"  Hull FFCO : {float(np.sum(hull_mask)) * px_area_m2 / 1e4:.0f} ha")

    # ── Matrice de confusion ──────────────────────────────────────────────────
    confusion = _build_confusion(pipe_cls, ffco_cls, hull_mask, px_area_m2)
    _print_confusion(confusion)

    # ── HAG distributions inter-classes ──────────────────────────────────────
    _plot_interclass_hag(
        smoothed, pipe_cls, ffco_cls, hull_mask,
        OUTPUT / "confusion_interclass.png",
    )

    # ── Sweep seuils ─────────────────────────────────────────────────────────
    _sweep_threshold(smoothed, ffco_cls, hull_mask, px_area_m2, sweep_param="T_408")
    _sweep_threshold(smoothed, ffco_cls, hull_mask, px_area_m2, sweep_param="T_410")


if __name__ == "__main__":
    main()
