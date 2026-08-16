"""Sweep T_410 joint : recall_exact 408 et 410 simultanément.

Répond à deux questions :
  1. De combien baisse le recall_exact 408 quand T_410 descend ?
  2. Le gain net 410 - perte 408 est-il stable (plateau) ou étroit (surajustement) ?

Usage : python scripts/diag/sweep_t410_joint.py
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
import shapely.geometry as sg
from shapely.ops import unary_union
import json as _json

ROOT = pathlib.Path(__file__).parent.parent.parent
OUTPUT = ROOT / "output"
FFCO_GPKG = ROOT / "grimbosq.gpkg"

_FFCO_KEYWORDS = {406: "course lente", 408: "marche", 410: "progression"}
_CLASSES = [406, 408, 410]

T_406 = 0.20
T_408_CURRENT = 0.45


def _load_ffco(gpkg: pathlib.Path) -> dict[int, list[sg.Polygon]]:
    from osgeo import ogr as _ogr
    _ogr.UseExceptions()
    ds = _ogr.Open(str(gpkg))
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
    ffco: dict[int, list] = {cls: [] for cls in _CLASSES}
    feat = areas_lyr.GetNextFeature()
    while feat is not None:
        try:
            raw = feat.ExportToJson()
            props = _json.loads(raw).get("properties", {})
        except Exception:
            feat = areas_lyr.GetNextFeature()
            continue
        label = ""
        for val in props.values():
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
                    geom = sg.shape(_json.loads(geom_ref.ExportToJson()))
                    if geom.is_valid and not geom.is_empty:
                        ffco[matched].append(geom)
                except Exception:
                    pass
        feat = areas_lyr.GetNextFeature()
    return ffco


def main() -> None:
    # ── Chargement ────────────────────────────────────────────────────────────
    print("Chargement rasters...")
    with rasterio.open(OUTPUT / "density_hag_smoothed.tif") as ds:
        smoothed = ds.read(1).astype(np.float32)
        transform = ds.transform
        shape = (ds.height, ds.width)
        nodata = ds.nodata

    nodata_mask = (smoothed == nodata) if nodata is not None else np.zeros(shape, dtype=bool)
    smoothed[nodata_mask] = 0.0

    print("Chargement FFCO...")
    ffco = _load_ffco(FFCO_GPKG)

    print("Rasterisation FFCO...")
    ffco_cls = np.zeros(shape, dtype=np.uint16)
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
        ffco_cls[burned == cls] = cls

    all_polys = [g for polys in ffco.values() for g in polys]
    hull = unary_union(all_polys).convex_hull
    hull_mask = rasterize(
        [(hull, 1)],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    ).astype(bool) & ~nodata_mask

    # ── Sweep T_410 ───────────────────────────────────────────────────────────
    t_values = np.round(np.arange(0.45, 1.01, 0.01), 2)

    ffco_408 = hull_mask & (ffco_cls == 408)
    ffco_410 = hull_mask & (ffco_cls == 410)
    n_408 = float(np.sum(ffco_408))
    n_410 = float(np.sum(ffco_410))

    recall_408: list[float] = []
    recall_410: list[float] = []
    recall_408_any: list[float] = []

    for t410 in t_values:
        pipe = np.zeros(shape, dtype=np.uint16)
        pipe[smoothed > T_406] = 406
        pipe[smoothed > T_408_CURRENT] = 408
        pipe[smoothed > t410] = 410

        recall_408.append(float(np.sum(ffco_408 & (pipe == 408))) / n_408)
        recall_410.append(float(np.sum(ffco_410 & (pipe == 410))) / n_410)
        recall_408_any.append(float(np.sum(ffco_408 & (pipe > 0))) / n_408)

    recall_408 = np.array(recall_408)
    recall_410 = np.array(recall_410)

    # Surface FFCO en ha (pour pondérer les recalls par les superficies réelles)
    px_area_m2 = abs(transform.a * transform.e)
    ha_408 = n_408 * px_area_m2 / 1e4
    ha_410 = n_410 * px_area_m2 / 1e4
    total_correct_ha = recall_408 * ha_408 + recall_410 * ha_410

    # Référence = T_410 actuel (0.85), pas la borne inférieure du sweep
    ref_idx = int(np.argmin(np.abs(t_values - 0.85)))
    ref_408 = recall_408[ref_idx]
    ref_410 = recall_410[ref_idx]
    ref_ha = total_correct_ha[ref_idx]

    # Gain net pondéré en ha (différence vs point de référence T_410=0.85)
    gain_net_ha = total_correct_ha - ref_ha

    # ── Table de résultats ────────────────────────────────────────────────────
    print(f"\n  Référence T_410=0.85 : r408={ref_408:.1%} ({ref_408*ha_408:.2f}ha)  "
          f"r410={ref_410:.1%} ({ref_410*ha_410:.2f}ha)  "
          f"total correct={ref_ha:.2f}ha")
    print(f"  FFCO 408={ha_408:.1f}ha  FFCO 410={ha_410:.1f}ha")
    print(f"  Rapport de surfaces 408/410={ha_408/ha_410:.2f} "
          f"-> 1pp 408 = {ha_408/ha_410:.2f}x 1pp 410 en ha\n")

    print(f"{'T_410':>6}  {'r_408':>7}  {'r_410':>7}  "
          f"{'D408(pp)':>9}  {'D410(pp)':>9}  {'total_ha':>9}  {'net_ha':>8}")
    print("-" * 72)
    for i, t in enumerate(t_values):
        d408 = (recall_408[i] - ref_408) * 100
        d410 = (recall_410[i] - ref_410) * 100
        marker = " <--" if abs(t - 0.60) < 0.005 else (" REF" if abs(t - 0.85) < 0.005 else "    ")
        print(f"{t:6.2f}  {recall_408[i]:7.1%}  {recall_410[i]:7.1%}  "
              f"{d408:+9.1f}  {d410:+9.1f}  "
              f"{total_correct_ha[i]:9.2f}  {gain_net_ha[i]:+8.2f}{marker}")

    best_ha_idx = int(np.argmax(total_correct_ha))
    print(f"\nT optimal (max total_ha) : {t_values[best_ha_idx]:.2f}  "
          f"total={total_correct_ha[best_ha_idx]:.2f}ha  "
          f"gain vs 0.85 : {gain_net_ha[best_ha_idx]:+.2f}ha")

    # Plateau ha : zone où total_correct_ha > max - 0.1 ha
    plateau_ha_mask = total_correct_ha > float(np.max(total_correct_ha)) - 0.1
    if plateau_ha_mask.any():
        t_lo = float(t_values[plateau_ha_mask][0])
        t_hi = float(t_values[plateau_ha_mask][-1])
        print(f"Zone plateau ha (within 0.1ha du max) : T_410 in [{t_lo:.2f}, {t_hi:.2f}]")

    # ── Graphique ─────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(10, 10), sharex=True)

    ax1 = axes[0]
    ax1.plot(t_values, recall_410, "g-", lw=2, label="Recall exact 410 (gain)")
    ax1.plot(t_values, recall_408, "b-", lw=2, label="Recall exact 408 (perte)")
    ax1.axvline(0.85, color="gray", ls="--", lw=1, label="T actuel=0.85")
    ax1.axvline(0.60, color="orange", ls=":", lw=2, label="T propose=0.60")
    ax1.set_ylabel("Recall classe exacte")
    ax1.set_title("Sweep T_410 : recall_exact 408 et 410 simultanes\n(T_406=0.20, T_408=0.45 fixes)")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax1.set_ylim(0, 1.05)

    ax2 = axes[1]
    ax2.plot(t_values, gain_net_ha, "purple", lw=2,
             label="Gain net pondere (ha bien classes 408+410 vs T=0.85)")
    ax2.axhline(0, color="gray", ls="--", lw=0.8)
    ax2.axvline(0.85, color="gray", ls="--", lw=1, label="T actuel=0.85 (ref)")
    ax2.axvline(0.60, color="orange", ls=":", lw=2, label="T propose=0.60")
    ax2.axvline(t_values[best_ha_idx], color="green", ls=":", lw=2,
                label=f"T optimal ha={t_values[best_ha_idx]:.2f} (+{gain_net_ha[best_ha_idx]:.2f}ha)")
    ax2.set_xlabel("T_410")
    ax2.set_ylabel("Gain net en ha (vs T_410=0.85)")
    ax2.set_title(f"Gain net pondere par surfaces FFCO (408={ha_408:.1f}ha, 410={ha_410:.1f}ha)")
    ax2.legend()
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    out_path = OUTPUT / "sweep_t410_joint.png"
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"\nGraphique -> {out_path}")


if __name__ == "__main__":
    main()
