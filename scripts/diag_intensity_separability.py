"""Diagnostic H3 — séparabilité de l'intensité de retour par zone FFCO.

Protocole en deux étapes (plan v5, §H3) :

1. Test de dépendance angle→intensité (obligatoire avant conclusion)
   Compare la variance d'intensité entre tranches d'angle avec la variance entre zones FFCO.
   Si la variance angulaire domine → normaliser d'abord.
   Sortie : diag_intensity_angle.png + section JSON "angle_dependence"

2. Séparabilité par zone FFCO (open_terrain / scattered_trees / veg_406)
   Histogrammes superposés, statistiques par zone.
   Sortie : intensity_by_zone_hist.png + canopy_separability_intensity.json

Usage :
    python scripts/diag_intensity_separability.py --terrain airelles
    python scripts/diag_intensity_separability.py --terrain grimbosq \\
        --intensity output/intensity_veg.tif --angle output/angle_veg.tif \\
        --ffco grimbosq.gpkg
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml
from osgeo import gdal, ogr, osr
from shapely.wkt import loads as wkt_loads

gdal.UseExceptions()

_DEFAULT_MAPPING = pathlib.Path(__file__).parent / "mappings" / "ffco_fr.yaml"


def _load_zone_mapping(yaml_path: str | pathlib.Path) -> tuple[
    dict[str, str], dict[str, int], dict[str, str], dict[str, str], list[str]
]:
    """Charge un fichier YAML de mapping zone.

    Retourne (zone_names, zone_ids, zone_labels, zone_colors, active_groups).
    """
    with open(yaml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    zone_names: dict[str, str] = {}
    zone_labels: dict[str, str] = {}
    zone_colors: dict[str, str] = {}
    active_groups: list[str] = []

    for group, meta in cfg["groups"].items():
        for name in meta.get("names", []):
            zone_names[name] = group
        if group == "skip":
            continue
        if "label" in meta:
            zone_labels[group] = meta["label"]
            zone_colors[group] = meta.get("color", "#888888")
            active_groups.append(group)

    zone_ids = {g: i + 1 for i, g in enumerate(active_groups)}
    return zone_names, zone_ids, zone_labels, zone_colors, active_groups


def _decode(raw: str) -> str:
    r = []
    for ch in raw:
        code = ord(ch)
        r.append(chr(code - 0xDC00) if 0xDC80 <= code <= 0xDCFF else ch)
    return "".join(r)


def _load_oom_zones(
    gpkg_path: str,
    zone_names: dict[str, str],
    zone_ids: dict[str, int],
) -> dict[str, list]:
    ds = ogr.Open(gpkg_path)
    if ds is None:
        raise FileNotFoundError(f"Impossible d'ouvrir : {gpkg_path}")
    layer_idx = None
    for i in range(ds.GetLayerCount()):
        if "area" in ds.GetLayer(i).GetName().lower():
            layer_idx = i; break
    if layer_idx is None:
        raise ValueError("Couche *_areas introuvable")
    lyr = ds.GetLayer(layer_idx)
    zones: dict[str, list] = {z: [] for z in zone_ids}
    skipped = 0
    for feat in lyr:
        raw = feat.GetField("Name") or ""
        name = _decode(raw).strip()
        group = zone_names.get(name)
        if group is None or group == "skip" or group not in zones:
            skipped += 1; continue
        ref = feat.GetGeometryRef()
        if ref:
            zones[group].append(wkt_loads(ref.ExportToWkt()))
    n_loaded = sum(len(v) for v in zones.values())
    print(f"[INFO] {n_loaded} zones chargées ({skipped} ignorées)")
    ds = None
    return zones


def _rasterize_zones(zones, zone_ids, gt, rows, cols, crs_wkt):
    srs = osr.SpatialReference(); srs.ImportFromWkt(crs_wkt)
    drv_r = gdal.GetDriverByName("MEM")
    ds_out = drv_r.Create("", cols, rows, 1, gdal.GDT_Byte)
    ds_out.SetGeoTransform(gt); ds_out.SetProjection(crs_wkt)
    b = ds_out.GetRasterBand(1); b.Fill(0)
    drv_v = ogr.GetDriverByName("Memory")
    for group, zone_id in zone_ids.items():
        geoms = zones.get(group, [])
        if not geoms: continue
        mem = drv_v.CreateDataSource("")
        lyr = mem.CreateLayer("", srs=srs, geom_type=ogr.wkbPolygon)
        for geom in geoms:
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetGeometry(ogr.CreateGeometryFromWkt(geom.wkt))
            lyr.CreateFeature(feat)
        gdal.RasterizeLayer(ds_out, [1], lyr, burn_values=[zone_id])
        mem = None
    arr = b.ReadAsArray(); ds_out = None
    return arr


def _load_raster(path: str) -> tuple[np.ndarray, tuple, str, np.ndarray]:
    ds = gdal.Open(path)
    if ds is None:
        raise FileNotFoundError(f"Introuvable : {path}")
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nd = ds.GetRasterBand(1).GetNoDataValue()
    gt = ds.GetGeoTransform(); crs = ds.GetProjection(); ds = None
    mask = (arr == nd) if nd is not None else np.zeros_like(arr, bool)
    arr[mask] = np.nan
    return arr, gt, crs, mask


def _stats(arr: np.ndarray) -> dict:
    v = arr[np.isfinite(arr)]
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "mean": float(np.mean(v)), "std": float(np.std(v)),
            "p05": float(np.percentile(v, 5)), "p25": float(np.percentile(v, 25)),
            "median": float(np.median(v)), "p75": float(np.percentile(v, 75)),
            "p95": float(np.percentile(v, 95))}


def _plot_overlaid(data_by_zone, zone_labels, zone_colors, title, xlabel, out_path,
                   x_lim=None, n_bins=60):
    fig, ax = plt.subplots(figsize=(9, 5))
    cap = x_lim
    for group, arr in data_by_zone.items():
        valid = arr[np.isfinite(arr)]
        if len(valid) == 0: continue
        if cap is None:
            cap = float(np.percentile(valid, 99))
        valid = valid[valid <= cap]
        ax.hist(valid, bins=n_bins, range=(0, cap), density=True,
                alpha=0.55, color=zone_colors.get(group, "#888888"), edgecolor="none",
                label=f"{zone_labels.get(group, group)} (n={len(valid):,})")
    ax.set_title(title, fontsize=11)
    ax.set_xlabel(xlabel); ax.set_ylabel("Densité relative")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out_path, dpi=140); plt.close(fig)
    print(f"[PNG] → {out_path}")


def _test_angle_dependence(intensity: np.ndarray, angle: np.ndarray,
                           bad: np.ndarray, out_dir: pathlib.Path) -> dict:
    """Bin intensity by angle, check if angle explains variance."""
    valid = ~bad & np.isfinite(intensity) & np.isfinite(angle)
    i_vals = intensity[valid]; a_vals = angle[valid]
    if len(i_vals) < 100:
        return {"status": "insufficient_data"}

    # Corrélation Pearson angle→intensité
    corr = float(np.corrcoef(a_vals, i_vals)[0, 1])

    # Variance entre tranches d'angle (bins de 5°)
    a_min, a_max = np.percentile(a_vals, 2), np.percentile(a_vals, 98)
    bins = np.arange(a_min, a_max + 5, 5)
    bin_medians = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = (a_vals >= lo) & (a_vals < hi)
        if sel.sum() > 100:
            bin_medians.append(float(np.median(i_vals[sel])))
    variance_between_angles = float(np.std(bin_medians)) if bin_medians else 0.0
    variance_global = float(np.std(i_vals))

    # Plot angle vs intensité (scatter sample)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    sample_idx = np.random.choice(len(i_vals), min(50000, len(i_vals)), replace=False)
    axes[0].scatter(a_vals[sample_idx], i_vals[sample_idx], s=0.3, alpha=0.3, color="steelblue")
    axes[0].set_xlabel("ScanAngleRank (°)"); axes[0].set_ylabel("Intensité")
    axes[0].set_title(f"Corrélation angle/intensité (r={corr:.3f})")
    axes[1].plot(bins[:-1], bin_medians, "o-", color="navy")
    axes[1].set_xlabel("Tranche d'angle (°)"); axes[1].set_ylabel("Intensité médiane")
    axes[1].set_title(f"Intensité médiane par angle\nstd={variance_between_angles:.1f} / std_global={variance_global:.1f}")
    fig.tight_layout()
    out_png = out_dir / "diag_intensity_angle.png"
    fig.savefig(out_png, dpi=140); plt.close(fig)
    print(f"[PNG] → {out_png}")

    ratio_angle_to_global = variance_between_angles / variance_global if variance_global > 0 else 0
    verdict = ("NORMALISER — variance angulaire domine"
               if ratio_angle_to_global > 0.3
               else "OK — variance angulaire modérée, test séparabilité valide")
    print(f"[ANGLE] r={corr:.3f} | std_angle={variance_between_angles:.1f} "
          f"| std_global={variance_global:.1f} | ratio={ratio_angle_to_global:.2f} → {verdict}")

    return {"pearson_r": corr, "std_between_angles": variance_between_angles,
            "std_global": variance_global, "ratio_angle_to_global": ratio_angle_to_global,
            "verdict": verdict}


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostic H3 — séparabilité intensité")
    parser.add_argument("--terrain", required=True)
    parser.add_argument("--intensity")
    parser.add_argument("--angle")
    parser.add_argument("--ffco")
    parser.add_argument("--out-dir")
    parser.add_argument("--mapping", default=str(_DEFAULT_MAPPING),
                        help="Fichier YAML de mapping zones (défaut: ffco_fr.yaml)")
    args = parser.parse_args()

    zone_names, zone_ids, zone_labels, zone_colors, _ = _load_zone_mapping(args.mapping)

    name = args.terrain
    intensity_path = args.intensity or f"output_{name}/intensity_veg.tif"
    angle_path     = args.angle     or f"output_{name}/angle_veg.tif"
    ffco_path      = args.ffco      or f"{name}.gpkg"
    out_dir        = pathlib.Path(args.out_dir or f"rapports/{name}")
    out_dir.mkdir(parents=True, exist_ok=True)

    for p, label in [(intensity_path, "intensity_veg.tif"), (angle_path, "angle_veg.tif"),
                     (ffco_path, "FFCO GPKG")]:
        if not pathlib.Path(p).exists():
            print(f"[ERREUR] {label} introuvable : {p}", file=sys.stderr)
            if "intensity" in p:
                print(f"  → python scripts/run_intensity_veg.py "
                      f"--tiles-dir LIDAR/{name} --out-dir output_{name}", file=sys.stderr)
            sys.exit(1)

    print(f"[INFO] Chargement rasters terrain={name}")
    intensity, gt, crs, im = _load_raster(intensity_path)
    angle, _, _, am = _load_raster(angle_path)
    r = min(intensity.shape[0], angle.shape[0])
    c = min(intensity.shape[1], angle.shape[1])
    intensity, angle = intensity[:r,:c], angle[:r,:c]
    bad = im[:r,:c] | am[:r,:c]
    print(f"[INFO] Raster {r}×{c} | pixels valides : {int(np.sum(~bad)):,}")

    # ── Étape 1 : dépendance angulaire ───────────────────────────────────────
    print("\n[ÉTAPE 1] Dépendance angle → intensité")
    angle_dep = _test_angle_dependence(intensity, angle, bad, out_dir)

    # ── Étape 2 : séparabilité par zone FFCO ─────────────────────────────────
    print("\n[ÉTAPE 2] Séparabilité par zone FFCO")
    zones = _load_oom_zones(ffco_path, zone_names, zone_ids)
    zone_mask = _rasterize_zones(zones, zone_ids, gt, r, c, crs)

    intensity_by_zone: dict[str, np.ndarray] = {}
    stats_by_zone: dict[str, dict] = {}

    for group, zone_id in zone_ids.items():
        sel = (zone_mask == zone_id) & ~bad
        vals = intensity[sel]
        intensity_by_zone[group] = vals
        s = _stats(vals)
        stats_by_zone[group] = s
        n = s.get("n", 0)
        label = zone_labels.get(group, group)
        if n > 0:
            print(f"  {label} : n={n:,} | "
                  f"médiane={s['median']:.1f} | p25={s['p25']:.1f} | p75={s['p75']:.1f}")
        else:
            print(f"  {label} : aucun pixel")

    _plot_overlaid(
        intensity_by_zone, zone_labels, zone_colors,
        title=f"{name} — intensité retours HAG[0.3:3m] par zone FFCO",
        xlabel="Intensité (unités brutes)",
        out_path=out_dir / "intensity_by_zone_hist.png",
    )

    report = {
        "terrain": name, "intensity_tif": intensity_path, "angle_tif": angle_path,
        "ffco_gpkg": ffco_path, "raster_shape": [r, c],
        "angle_dependence": angle_dep,
        "zones": stats_by_zone,
    }
    json_path = out_dir / "canopy_separability_intensity.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[JSON] → {json_path}")


if __name__ == "__main__":
    main()
