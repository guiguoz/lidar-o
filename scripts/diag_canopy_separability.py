"""Diagnostic de séparabilité du masque canopée.

Hypothèse : canopy_fraction = count_high / total discrimine les zones ouvertes (403/404)
des zones boisées (406), ce qui permettrait de filtrer les faux positifs HAG.

Produit trois courbes par histogramme :
  - terrain découvert (403/404)
  - zone découverte avec arbres dispersés (404 ambigu)
  - végétation codée 406

Et un second plot pour `total` seul, afin de détecter si la séparation reflète la densité
d'acquisition plutôt que la présence d'arbres.

Usage :
    python scripts/diag_canopy_separability.py --terrain airelles
    python scripts/diag_canopy_separability.py --terrain grimbosq
    python scripts/diag_canopy_separability.py --terrain airelles \\
        --count-high output_airelles/count_high.tif \\
        --total output_airelles/total_count.tif \\
        --ffco airelles.gpkg
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
    zone_names : nom OOM → groupe (ex: "Terrain découvert" → "open_terrain")
    zone_ids   : groupe → entier pour rasterisation (skip et groupes sans label exclus)
    active_groups : groupes dans l'ordre du YAML, hors "skip"
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


# ─── Décodage surrogates OOM ─────────────────────────────────────────────────

def _decode(raw: str) -> str:
    result = []
    for ch in raw:
        code = ord(ch)
        result.append(chr(code - 0xDC00) if 0xDC80 <= code <= 0xDCFF else ch)
    return "".join(result)


# ─── Chargement FFCO (zones pertinentes seulement) ───────────────────────────

def _load_oom_zones(
    gpkg_path: str,
    zone_names: dict[str, str],
    zone_ids: dict[str, int],
    zone_labels: dict[str, str],
) -> dict[str, list]:
    """Retourne {zone_group: [shapely geom, ...]} depuis le GPKG OOM."""
    ds = ogr.Open(gpkg_path)
    if ds is None:
        raise FileNotFoundError(f"Impossible d'ouvrir : {gpkg_path}")

    layer_idx = None
    for i in range(ds.GetLayerCount()):
        n = ds.GetLayer(i).GetName()
        if "area" in n.lower():
            layer_idx = i
            break
    if layer_idx is None:
        raise ValueError("Couche *_areas introuvable")

    lyr = ds.GetLayer(layer_idx)
    layer_display = lyr.GetName()
    zones: dict[str, list] = {z: [] for z in zone_ids}
    skipped = 0

    for feat in lyr:
        raw_name = feat.GetField("Name") or ""
        name = _decode(raw_name).strip()
        group = zone_names.get(name)
        if group is None or group == "skip":
            skipped += 1
            continue
        if group not in zones:
            skipped += 1
            continue
        geom_ref = feat.GetGeometryRef()
        if geom_ref is None:
            continue
        zones[group].append(wkt_loads(geom_ref.ExportToWkt()))

    n_loaded = sum(len(v) for v in zones.values())
    print(f"[INFO] FFCO : {n_loaded} zones chargées ({skipped} ignorées)")
    for group, geoms in zones.items():
        label = zone_labels.get(group, group)
        print(f"  {label} : {len(geoms)} polygones")
    ds = None
    return zones


# ─── Rasterisation des zones ─────────────────────────────────────────────────

def _rasterize_zones(
    zones: dict[str, list],
    zone_ids: dict[str, int],
    gt: tuple,
    rows: int,
    cols: int,
    crs_wkt: str,
) -> np.ndarray:
    """Retourne un tableau uint8 avec zone_id par pixel (0 = non classifié)."""
    srs = osr.SpatialReference()
    srs.ImportFromWkt(crs_wkt)

    drv_r = gdal.GetDriverByName("MEM")
    ds_out = drv_r.Create("", cols, rows, 1, gdal.GDT_Byte)
    ds_out.SetGeoTransform(gt)
    ds_out.SetProjection(crs_wkt)
    band = ds_out.GetRasterBand(1)
    band.Fill(0)

    drv_v = ogr.GetDriverByName("Memory")

    for group, zone_id in zone_ids.items():
        geoms = zones.get(group, [])
        if not geoms:
            continue
        mem_src = drv_v.CreateDataSource("")
        lyr = mem_src.CreateLayer("", srs=srs, geom_type=ogr.wkbPolygon)
        for geom in geoms:
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetGeometry(ogr.CreateGeometryFromWkt(geom.wkt))
            lyr.CreateFeature(feat)
        gdal.RasterizeLayer(ds_out, [1], lyr, burn_values=[zone_id])
        mem_src = None

    arr = band.ReadAsArray()
    ds_out = None
    return arr


# ─── Lecture raster ──────────────────────────────────────────────────────────

def _load_raster(path: str) -> tuple[np.ndarray, tuple, str, np.ndarray]:
    """Retourne (arr, gt, crs_wkt, nodata_mask)."""
    ds = gdal.Open(path)
    if ds is None:
        raise FileNotFoundError(f"Impossible d'ouvrir : {path}")
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nd = ds.GetRasterBand(1).GetNoDataValue()
    gt = ds.GetGeoTransform()
    crs = ds.GetProjection()
    ds = None
    mask = (arr == nd) if nd is not None else np.zeros_like(arr, dtype=bool)
    arr[mask] = np.nan
    return arr, gt, crs, mask


# ─── Percentiles ─────────────────────────────────────────────────────────────

def _stats(arr: np.ndarray) -> dict:
    valid = arr[np.isfinite(arr)]
    if len(valid) == 0:
        return {"n": 0}
    return {
        "n":      int(len(valid)),
        "mean":   float(np.mean(valid)),
        "std":    float(np.std(valid)),
        "p05":    float(np.percentile(valid, 5)),
        "p25":    float(np.percentile(valid, 25)),
        "median": float(np.median(valid)),
        "p75":    float(np.percentile(valid, 75)),
        "p95":    float(np.percentile(valid, 95)),
    }


# ─── Histogramme superposé ───────────────────────────────────────────────────

def _plot_overlaid(
    data_by_zone: dict[str, np.ndarray],
    zone_labels: dict[str, str],
    zone_colors: dict[str, str],
    title: str,
    xlabel: str,
    out_path: pathlib.Path,
    x_max: float | None = None,
    n_bins: int = 60,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    x_cap = x_max

    for group, arr in data_by_zone.items():
        valid = arr[np.isfinite(arr)]
        if len(valid) == 0:
            continue
        if x_cap is None:
            x_cap = float(np.percentile(valid, 99))
        valid = valid[valid <= x_cap]
        label = f"{zone_labels.get(group, group)} (n={len(valid):,})"
        ax.hist(
            valid,
            bins=n_bins,
            range=(0, x_cap),
            density=True,
            alpha=0.55,
            color=zone_colors.get(group, "#888888"),
            edgecolor="none",
            label=label,
        )

    ax.set_title(title, fontsize=11)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Densité relative")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    print(f"[PNG] → {out_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostic séparabilité canopy_fraction par zone FFCO"
    )
    parser.add_argument("--terrain", required=True,
                        help="Nom du terrain (ex: airelles, grimbosq)")
    parser.add_argument("--count-high",
                        help="count_high.tif (défaut: output_{terrain}/count_high.tif)")
    parser.add_argument("--total",
                        help="total_count.tif (défaut: output_{terrain}/total_count.tif)")
    parser.add_argument("--ffco",
                        help="FFCO GPKG (défaut: {terrain}.gpkg)")
    parser.add_argument("--out-dir",
                        help="Dossier rapports (défaut: rapports/{terrain})")
    parser.add_argument("--mapping", default=str(_DEFAULT_MAPPING),
                        help="Fichier YAML de mapping zones (défaut: ffco_fr.yaml)")
    args = parser.parse_args()

    zone_names, zone_ids, zone_labels, zone_colors, active_groups = \
        _load_zone_mapping(args.mapping)

    name = args.terrain
    count_high_path = args.count_high or f"output_{name}/count_high.tif"
    total_path      = args.total      or f"output_{name}/total_count.tif"
    ffco_path       = args.ffco       or f"{name}.gpkg"
    out_dir         = pathlib.Path(args.out_dir or f"rapports/{name}")
    out_dir.mkdir(parents=True, exist_ok=True)

    for p, label in [(count_high_path, "count_high.tif"), (total_path, "total_count.tif"),
                     (ffco_path, "FFCO GPKG")]:
        if not pathlib.Path(p).exists():
            print(f"[ERREUR] {label} introuvable : {p}", file=sys.stderr)
            if "count_high" in p:
                print(
                    "  → Lancer d'abord :\n"
                    f"  python scripts/run_count_high.py "
                    f"--tiles-dir LIDAR/{name} --out {count_high_path}",
                    file=sys.stderr,
                )
            sys.exit(1)

    print(f"[INFO] Chargement rasters pour terrain={name}")
    high_arr, gt, crs_wkt, high_mask = _load_raster(count_high_path)
    total_arr, gt2, _, total_mask = _load_raster(total_path)

    # Aligner si tailles légèrement différentes
    r = min(high_arr.shape[0], total_arr.shape[0])
    c = min(high_arr.shape[1], total_arr.shape[1])
    high_arr  = high_arr[:r, :c]
    total_arr = total_arr[:r, :c]
    high_mask = high_mask[:r, :c]
    total_mask = total_mask[:r, :c]
    bad = high_mask | total_mask | (total_arr <= 0)
    high_arr[bad] = np.nan
    total_arr[bad] = np.nan

    # canopy_fraction : NaN là où total=0 ou nodata
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(bad, np.nan, high_arr / total_arr)

    print(f"[INFO] Raster : {r}×{c} px | pixels valides : {int(np.sum(~bad)):,}")

    # Chargement et rasterisation des zones FFCO
    zones = _load_oom_zones(ffco_path, zone_names, zone_ids, zone_labels)
    zone_mask = _rasterize_zones(zones, zone_ids, gt, r, c, crs_wkt)
    n_classified = int(np.sum(zone_mask > 0))
    print(f"[INFO] Pixels rasterisés dans une zone FFCO : {n_classified:,} "
          f"({100*n_classified/r/c:.1f}% de l'emprise)")

    # Extraction par zone
    frac_by_zone: dict[str, np.ndarray] = {}
    total_by_zone: dict[str, np.ndarray] = {}
    stats: dict[str, dict] = {}

    for group, zone_id in zone_ids.items():
        sel = (zone_mask == zone_id) & ~bad
        frac_vals = frac[sel]
        total_vals = total_arr[sel]
        frac_by_zone[group] = frac_vals
        total_by_zone[group] = total_vals
        s = _stats(frac_vals)
        s["total_stats"] = _stats(total_vals)
        stats[group] = s
        n = s.get("n", 0)
        label = zone_labels.get(group, group)
        if n > 0:
            print(f"  {label} : n={n:,} | "
                  f"frac médiane={s['median']:.3f} | p05={s['p05']:.3f} | p95={s['p95']:.3f}")
        else:
            print(f"  {label} : aucun pixel valide")

    # Histogrammes
    _plot_overlaid(
        frac_by_zone, zone_labels, zone_colors,
        title=f"{name} — canopy_fraction (count_high/total) par zone FFCO",
        xlabel="count_high / total",
        out_path=out_dir / "canopy_fraction_hist.png",
        x_max=1.0,
    )

    _plot_overlaid(
        total_by_zone, zone_labels, zone_colors,
        title=f"{name} — total retours/m² par zone FFCO (biais densité acquisition ?)",
        xlabel="total retours par pixel 1m²",
        out_path=out_dir / "total_by_zone_hist.png",
        x_max=None,
    )

    # JSON
    report = {
        "terrain": name,
        "count_high_tif": count_high_path,
        "total_tif": total_path,
        "ffco_gpkg": ffco_path,
        "raster_shape": [r, c],
        "n_valid_pixels": int(np.sum(~bad)),
        "n_zone_pixels": n_classified,
        "zones": stats,
    }
    json_path = out_dir / "canopy_separability.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[JSON] → {json_path}")


if __name__ == "__main__":
    main()
