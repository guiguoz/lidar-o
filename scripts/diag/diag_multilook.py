"""Diagnostic multi-looks par ligne de vol — protocole L2.

Question (docs/pistes_raster_multipasses.md §3) : le contraste de bande mesure
dans docs/bilan_v0.md §7 (bande de recouvrement a 3 lignes de vol : densite
84,6 pts/m2 contre 41,2 hors bande, contraste residuel du ratio +0,024) vient-il
de la *ponderation* des looks (H-A, geometrie) ou d'un ecart reel du ratio entre
looks (H-B, covariation spatiale / effet angulaire) ?

Principe :
    1. Une seule lecture PDAL >= 2.7 : filters.merge -> filters.hag_nn ->
       filters.assign (drapeau bande HAG) -> filters.sort/filters.groupby sur
       PointSourceId -> writers.gdal avec '#' (un GeoTIFF par ligne de vol).
       Chaque fichier porte deux bandes : mean(flag) = fraction de retours dans
       la bande, count = nombre de points de la cellule pour ce look.
    2. Fusion numpy : par cellule, mediane des fractions de look (looks avec
       count >= n_min) -> champ « fusionne » ; comparaison au champ « poole »
       (moyenne ponderee par les counts = comportement actuel du pipeline).
    3. Contraste bande / hors bande avant-apres, ecart de surface par classe
       apres la chaine de classification de process_hag, verdict H-A / H-B.

Lecture :
    - ratio par look stable, ecart produit par la ponderation -> H-A :
      la fusion doit effondrer le contraste (cible <= 0,005) -> levier utile.
    - ratio par look divergent -> H-B : la fusion ne corrige rien, il faudra une
      correction dependante de l'angle (Beer-Lambert), pas une fusion.
    - contraste poole faible (< 0,005) -> la bande n'est pas un artefact de
      ratio : dossier banding a fermer.

Usage :
    python scripts/diag/diag_multilook.py --dry-run        # ecrit les pipelines JSON
    python scripts/diag/diag_multilook.py                  # PDAL + fusion + rapport
    python scripts/diag/diag_multilook.py --n-min 6 --looks-dir temp/looks
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT_TILES_DIR = ROOT / "LIDAR"
DEFAULT_LOOKS_DIR = ROOT / "temp" / "looks"
HAG_TIF = ROOT / "output" / "density_hag.tif"
TOTAL_TIF = ROOT / "output" / "total_count.tif"
PDAL_MIN_VERSION = (2, 7)


# ── Construction des pipelines PDAL ──────────────────────────────────────────

def build_multilook_pipeline(
    tiles: list[str],
    out_pattern: str,
    resolution: float,
    min_h: float,
    max_h: float,
    bounds: str | None = None,
    reader: str = "readers.copc",
    binmode: bool = False,
) -> dict:
    """Pipeline PDAL : un raster par ligne de vol (PointSourceId).

    out_pattern doit contenir un '#' (remplace par un index croissant) :
    writers.gdal ecrit un fichier par PointView recue de filters.groupby.

    Chaque fichier de sortie porte 2 bandes (output_type ["mean", "count"]) :
        bande 1 : moyenne du drapeau BandFlag = fraction de retours HAG dans
                  [min_h, max_h] pour ce look ;
        bande 2 : nombre de points du look contribuant a la cellule (toutes hauteurs).

    binmode reste a False par defaut : on reproduit ainsi *exactement* les
    reglages du writer de production (rayon par defaut ~0,71 m a 1 m de
    resolution), ce qui rend le « poole » reconstruit comparable a
    output/density_hag.tif. Passer binmode=True change la population par
    cellule et n'est plus comparable au run de reference.

    Bornes : filtres.range utilise [min_h:max_h] *ferme des deux cotes*, donc
    le drapeau doit utiliser <= (et non <) pour une equivalence stricte.

    Requiert PDAL >= 2.7 (filters.assign cree la dimension BandFlag).
    """
    if "#" not in out_pattern:
        raise ValueError("out_pattern doit contenir un '#' (placeholder multi-vues)")

    writer: dict = {
        "type": "writers.gdal",
        "filename": out_pattern,
        "resolution": resolution,
        "dimension": "BandFlag",
        "output_type": ["mean", "count"],
        "binmode": binmode,
        "data_type": "float32",
        "nodata": -1,
    }
    if bounds:
        writer["bounds"] = bounds

    return {
        "pipeline": [{"type": reader, "filename": t} for t in tiles] + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.assign", "value": ["BandFlag = 0"]},
            {"type": "filters.assign",
             "value": [f"BandFlag = 1 WHERE HeightAboveGround >= {min_h} "
                       f"&& HeightAboveGround <= {max_h}"]},
            {"type": "filters.sort", "dimension": "PointSourceId"},
            {"type": "filters.groupby", "dimension": "PointSourceId"},
            writer,
        ]
    }


# ── Fusion ───────────────────────────────────────────────────────────────────

def fuse_looks(
    fractions: np.ndarray,
    counts: np.ndarray,
    nodata: float = -1.0,
    n_min: int = 4,
) -> dict[str, np.ndarray]:
    """Fusionne les looks d'une cellule.

    Args:
        fractions: (n_looks, H, W) fraction de retours dans la bande par look.
        counts:    (n_looks, H, W) nombre de points du look dans la cellule.
        nodata:    valeur nodata des rasters PDAL.
        n_min:     nombre minimal de points d'un look pour qu'il compte.

    Returns:
        fused      : mediane des fractions des looks retenus (NaN si aucun)
        pooled     : somme des bandes / somme des points (comportement actuel)
        n_looks    : nombre de looks presents (count > 0)
        n_used     : nombre de looks retenus (count >= n_min)
    """
    frac = np.asarray(fractions, dtype=np.float64)
    cnt = np.asarray(counts, dtype=np.float64)
    if frac.shape != cnt.shape:
        raise ValueError(f"shapes incompatibles : {frac.shape} != {cnt.shape}")

    valid = (cnt != nodata) & (cnt > 0) & (frac != nodata)
    used = valid & (cnt >= n_min)

    frac_band = np.where(valid, frac * np.maximum(cnt, 0.0), 0.0)
    tot = np.where(valid, cnt, 0.0)
    sum_band = frac_band.sum(axis=0)
    sum_cnt = tot.sum(axis=0)

    with np.errstate(invalid="ignore", divide="ignore"):
        pooled = np.where(sum_cnt > 0, sum_band / np.where(sum_cnt > 0, sum_cnt, 1.0), np.nan)

    import warnings

    masked = np.where(used, frac, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # colonnes tout-NaN
        fused = np.nanmedian(masked, axis=0)
    fused[np.all(np.isnan(masked), axis=0)] = np.nan

    return {
        "fused": fused,
        "pooled": pooled,
        "n_looks": valid.sum(axis=0).astype(np.int32),
        "n_used": used.sum(axis=0).astype(np.int32),
    }


def band_contrast(
    field: np.ndarray,
    n_looks: np.ndarray,
    looks_threshold: int = 3,
) -> dict[str, float]:
    """Contraste median(bande) - median(hors bande) d'un champ de ratio.

    Retourne aussi la mediane de chaque population, pour lecture directe.
    """
    band = (n_looks >= looks_threshold) & np.isfinite(field)
    outside = (n_looks >= 1) & (n_looks < looks_threshold) & np.isfinite(field)
    if band.sum() == 0 or outside.sum() == 0:
        return {"band_med": float("nan"), "out_med": float("nan"),
                "contrast": float("nan"), "n_band": int(band.sum()),
                "n_out": int(outside.sum())}
    b = float(np.median(field[band]))
    o = float(np.median(field[outside]))
    return {"band_med": b, "out_med": o, "contrast": b - o,
            "n_band": int(band.sum()), "n_out": int(outside.sum())}


def classify_like_process_hag(
    field: np.ndarray,
    cfg: dict,
    resolution_m: float,
    invalid: np.ndarray | None = None,
) -> np.ndarray:
    """Rejoue la chaine de production (gauss -> median -> p95 -> seuils) sur un champ.

    Le champ d'entree est un ratio (ou une fraction) ; les parametres sont lus
    dans config.yaml, exactement comme scripts/process_hag.py.
    """
    from scipy.ndimage import gaussian_filter, median_filter

    veg = cfg["vegetation"]
    preset = veg["presets"][veg["active_preset"]]
    t406, t408, t410 = (float(t) for t in preset["thresholds"])
    ph = veg.get("process_hag", {})
    sigma_px = max(float(ph.get("gaussian_sigma", 1.0)) / resolution_m, 0.5)
    median_px = int(round(float(ph.get("median_size", 9)) / resolution_m))
    if median_px % 2 == 0:
        median_px += 1
    median_px = max(median_px, 3)

    mask = ~np.isfinite(field)
    if invalid is not None:
        mask = mask | invalid
    filled = np.where(mask, 0.0, field)
    smooth = median_filter(gaussian_filter(filled, sigma=sigma_px), size=median_px)
    valid_px = smooth[~mask]
    vmax = float(np.percentile(valid_px, 95)) if valid_px.size else 1.0
    normed = np.clip(smooth / vmax, 0.0, 1.0) if vmax > 1e-9 else np.clip(smooth, 0.0, 1.0)
    normed[mask] = 0.0

    cls = np.zeros(normed.shape, dtype=np.uint8)
    cls[normed > t406] = 85
    cls[normed > t408] = 170
    cls[normed > t410] = 255
    return cls


def class_surfaces(cls: np.ndarray) -> dict[int, float]:
    """Surface relative (%) de chaque classe sur les pixels classifies."""
    total = int((cls != 0).sum())
    return {
        406: 100.0 * int((cls == 85).sum()) / total if total else 0.0,
        408: 100.0 * int((cls == 170).sum()) / total if total else 0.0,
        410: 100.0 * int((cls == 255).sum()) / total if total else 0.0,
    }


# ── Lecture des rasters de look ──────────────────────────────────────────────

def read_look_rasters(looks_dir: pathlib.Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """Lit look_*.tif et empile mean(flag) et count.

    L'ordre des bandes suit output_type ['mean', 'count'] ; si GDAL expose des
    descriptions de bandes, elles sont utilisees pour lever toute ambiguite.
    """
    import rasterio

    files = sorted(looks_dir.glob("look_*.tif"))
    if not files:
        raise FileNotFoundError(f"Aucun look_*.tif dans {looks_dir}")
    fracs, counts, meta = [], [], {}
    ref = None
    for f in files:
        with rasterio.open(f) as ds:
            desc = [d.lower() if d else "" for d in (ds.descriptions or [])]
            if "mean" in desc and "count" in desc:
                i_mean, i_count = desc.index("mean"), desc.index("count")
            else:
                i_mean, i_count = 0, 1   # ordre de output_type
            frac = ds.read(i_mean + 1).astype(np.float64)
            cnt = ds.read(i_count + 1).astype(np.float64)
            nodata = ds.nodata if ds.nodata is not None else -1.0
            frac[frac == nodata] = np.nan
            cnt[cnt == nodata] = np.nan
            fracs.append(np.where(np.isnan(frac), nodata, frac))
            counts.append(np.where(np.isnan(cnt), nodata, cnt))
            if ref is None:
                ref = ds.profile.copy()
                meta["transform"] = ds.transform
                meta["res_m"] = abs(ds.transform.a)
            elif (ds.height, ds.width) != (ref["height"], ref["width"]):
                raise RuntimeError(
                    f"{f.name} : {ds.height}x{ds.width} != {ref['height']}x{ref['width']} "
                    "— bounds PDAL non homogenes entre looks"
                )
            meta[f.name] = int(np.nansum(np.where(np.isnan(cnt), 0, cnt)))
    meta["profile"] = ref
    return np.stack(fracs), np.stack(counts), meta


def _pdal_version() -> tuple[int, int] | None:
    exe = shutil.which("pdal")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    for token in out.stdout.split():
        parts = token.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
    return None


def run_pdal(pipeline: dict, tmp_path: pathlib.Path) -> None:
    exe = shutil.which("pdal")
    if not exe:
        sys.exit("pdal introuvable dans le PATH (ou utiliser --dry-run)")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(json.dumps(pipeline, indent=2), encoding="utf-8")
    print(f"  pipeline → {tmp_path}")
    res = subprocess.run([exe, "pipeline", str(tmp_path)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"PDAL a echoue :\n{res.stdout}\n{res.stderr}")


# ── Programme principal ──────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tiles-dir", type=pathlib.Path, default=DEFAULT_TILES_DIR)
    ap.add_argument("--looks-dir", type=pathlib.Path, default=DEFAULT_LOOKS_DIR)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--min-h", type=float, default=0.3)
    ap.add_argument("--max-h", type=float, default=3.0)
    ap.add_argument("--n-min", type=int, default=4,
                    help="points minimaux d'un look pour compter dans la mediane")
    ap.add_argument("--binmode", action="store_true",
                    help="compte les points strictement dans la cellule (defaut : reglages "
                         "du writer de production, rayon par defaut ~0,71 m)")
    ap.add_argument("--looks-threshold", type=int, default=3,
                    help="nombre de looks definissant la 'bande' (defaut 3, cf. bilan §7)")
    ap.add_argument("--dry-run", action="store_true",
                    help="ecrit les pipelines sans executer PDAL ni lire les looks")
    ap.add_argument("--skip-pdal", action="store_true",
                    help="reutilise les look_*.tif deja presents (pas de dalle requise)")
    ap.add_argument("--png", type=pathlib.Path, default=None,
                    help="ecrit un PNG comparatif pooled / fused / diff")
    args = ap.parse_args()

    tiles: list[str] = []
    if not args.skip_pdal or args.dry_run:
        tiles = sorted(str(t) for t in args.tiles_dir.glob("*.copc.laz"))
        if not tiles:
            sys.exit(f"Aucune dalle .copc.laz dans {args.tiles_dir} "
                     "(cf. README : LIDAR/ ou --tiles-dir)")

    # Alignement sur la grille du run de production si disponible
    bounds_str = None
    if HAG_TIF.exists():
        import rasterio
        with rasterio.open(HAG_TIF) as ds:
            b = ds.bounds
            bounds_str = f"([{b.left}, {b.right}], [{b.bottom}, {b.top}])"
        print(f"Bounds de reference (density_hag.tif) : {bounds_str}")

    args.looks_dir.mkdir(parents=True, exist_ok=True)
    pipeline = build_multilook_pipeline(
        tiles=tiles,
        out_pattern=str(args.looks_dir / "look_#.tif"),
        resolution=args.resolution,
        min_h=args.min_h,
        max_h=args.max_h,
        bounds=bounds_str,
        binmode=args.binmode,
    )

    scope = f"{len(tiles)} dalle(s)" if tiles else f"look_*.tif de {args.looks_dir}"
    print(f"Multi-looks : {scope}, bande HAG [{args.min_h}, {args.max_h}] m, "
          f"n_min={args.n_min}, bande = {args.looks_threshold}+ looks")
    version = _pdal_version()
    if version is None:
        print("  pdal absent du PATH — --dry-run ou --skip-pdal uniquement")
    else:
        print(f"  pdal {version[0]}.{version[1]}"
              + ("" if version >= PDAL_MIN_VERSION
                 else f"  ATTENTION : < {PDAL_MIN_VERSION[0]}.{PDAL_MIN_VERSION[1]} requis "
                      "(filters.assign ne cree pas de dimension)"))

    if args.dry_run:
        out = ROOT / "temp" / "pdal_multilook.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(pipeline, indent=2), encoding="utf-8")
        print(f"\nPipeline ecrit : {out}")
        print(json.dumps(pipeline, indent=2))
        return

    if not args.skip_pdal:
        run_pdal(pipeline, ROOT / "temp" / "pdal_multilook.json")

    fractions, counts, meta = read_look_rasters(args.looks_dir)
    n_looks_files = fractions.shape[0]
    print(f"\n{n_looks_files} look(s) lu(s), resolution {meta['res_m']} m")
    for name, total_pts in [(k, v) for k, v in meta.items() if k.startswith("look_")]:
        print(f"  {name:<18} {total_pts:>12,d} points".replace(",", " "))

    fusion = fuse_looks(fractions, counts, n_min=args.n_min)
    pooled, fused, n_looks = fusion["pooled"], fusion["fused"], fusion["n_looks"]

    # Contrôle de bon sens : le pool reconstruit doit coller au ratio de production
    if HAG_TIF.exists() and TOTAL_TIF.exists():
        import rasterio
        with rasterio.open(HAG_TIF) as a, rasterio.open(TOTAL_TIF) as b:
            hag = a.read(1).astype(np.float64)
            tot = b.read(1).astype(np.float64)
            nd_a, nd_b = a.nodata, b.nodata
        if nd_a is not None:
            hag[hag == nd_a] = 0.0
        if nd_b is not None:
            tot[tot == nd_b] = 0.0
        if hag.shape == pooled.shape:
            ref = np.where(tot > 0, hag / np.where(tot > 0, tot, 1.0), np.nan)
            ok = np.isfinite(ref) & np.isfinite(pooled)
            if ok.any():
                print(f"\nControle : ecart median |poole reconstruit - ratio prod| = "
                      f"{np.median(np.abs(ref[ok] - pooled[ok])):.4f}")
        else:
            print(f"\nControle impossible : shapes {hag.shape} != {pooled.shape}")

    c_pooled = band_contrast(pooled, n_looks, args.looks_threshold)
    c_fused = band_contrast(fused, n_looks, args.looks_threshold)
    print(f"\nContraste bande ({args.looks_threshold}+ looks) vs hors bande :")
    print(f"  poole  : {c_pooled['contrast']:+.4f}  "
          f"(bande {c_pooled['band_med']:.4f} / hors {c_pooled['out_med']:.4f}, "
          f"n={c_pooled['n_band']}/{c_pooled['n_out']})")
    print(f"  fusion : {c_fused['contrast']:+.4f}  "
          f"(bande {c_fused['band_med']:.4f} / hors {c_fused['out_med']:.4f}, "
          f"n={c_fused['n_band']}/{c_fused['n_out']})")

    both = np.isfinite(pooled) & np.isfinite(fused)
    if both.any():
        diff = np.abs(fused - pooled)[both]
        print(f"\nEcart fusion - poole : median |d|={np.median(diff):.4f}  "
              f"cellules |d|>0.05 = {100.0 * (diff > 0.05).mean():.1f}%")

    # Effet sur la carte classifiee
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    for label, field in (("poole", pooled), ("fusion", fused)):
        cls = classify_like_process_hag(field, cfg, meta["res_m"])
        s = class_surfaces(cls)
        print(f"Surfaces classees ({label:>6}) : "
              f"406={s[406]:5.1f}%  408={s[408]:5.1f}%  410={s[410]:5.1f}%")

    # Verdict
    print("\nVerdict :")
    if not np.isfinite(c_pooled["contrast"]):
        print("  non concluant — pas assez de cellules hors bande ou de looks.")
    elif abs(c_pooled["contrast"]) < 0.005:
        print("  H-A/H-B muettes : le contraste poole est deja < 0,005.")
        print("  -> la bande n'est pas un artefact de ratio : dossier banding a fermer.")
    elif abs(c_fused["contrast"]) <= 0.005 < abs(c_pooled["contrast"]):
        print("  H-A confirmee : la ponderation des looks creait l'essentiel du contraste,")
        print("  la fusion robuste le supprime -> levier L2 a promouvoir (lire aussi les surfaces).")
    elif abs(c_fused["contrast"]) < 0.8 * abs(c_pooled["contrast"]):
        print("  H-A partielle : la fusion reduit le contraste de > 20 % mais ne l'annule pas.")
    else:
        print("  H-B probable : le contraste persiste a look constant.")
        print("  -> l'effet est reel (angle / terrain), pas un probleme de ponderation ;")
        print("     envisager une correction dependante de l'angle, pas une fusion.")

    if args.png:
        _write_png(args.png, pooled, fused, n_looks)


def _write_png(path: pathlib.Path, pooled, fused, n_looks) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib absent — PNG non ecrit")
        return
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, (title, arr) in zip(axes, (
        ("poole (production)", pooled),
        ("fusion (mediane de looks)", fused),
        ("diff fusion-poole", fused - pooled),
    )):
        im = ax.imshow(arr, cmap="viridis", vmin=0, vmax=1 if "diff" not in title else None)
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    print(f"PNG → {path}")


if __name__ == "__main__":
    main()
