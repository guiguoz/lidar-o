"""Lissage + seuillage du raster HAG pour classification végétation.

Modes supportés (density_metric.mode dans config.yaml) :
  count          Comptage brut HAG (baseline)
  ratio          HAG / total_count (T8 — défaut production)
  nrd            Normalized Relative Density façon Blaze (Étape B)

Normalisation (normalization.mode) :
  p95_local      Divise par le p95 de la scène (défaut — T8)
  fixed_percentile  Divise par normalization.fixed_value gelé (T11)
  none           Pas de normalisation (T12)

Résolution (grid_resolution_m) :
  Si différente de la résolution native du raster source, rééchantillonnage
  par somme (physiquement correct pour des rasters de comptage).

Séparation de bandes (density_metric.band_split, Étape D) :
  Requiert count_band_low.tif + count_band_mid.tif + count_below.tif.
  406 classé depuis nrd_low, 408/410 depuis nrd_mid.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
import yaml
from scipy.ndimage import gaussian_filter, label as _ndlabel, median_filter

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.metrics import compute_nrd, compute_nrd_bands, compute_ratio


def _hysteresis_threshold(arr: np.ndarray, t_low: float, t_high: float) -> np.ndarray:
    """Seuillage par hysteresis : garde les regions connectees contenant au moins
    un pixel au-dessus de t_high, etendues jusqu'a t_low.

    Equivalent a skimage.filters.apply_hysteresis_threshold sans dependance externe.
    Propriete anti-percolation : une region entierement sous t_high reste exclue,
    meme si elle touche une region graines -- les ponts faibles sont coupes.
    """
    candidates = arr > t_low
    seeds = arr > t_high
    labeled, _ = _ndlabel(candidates)
    # Masque des labels qui contiennent au moins une graine
    seed_labels = np.unique(labeled[seeds])
    seed_labels = seed_labels[seed_labels != 0]
    if seed_labels.size == 0:
        return np.zeros_like(arr, dtype=bool)
    return np.isin(labeled, seed_labels)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers raster
# ─────────────────────────────────────────────────────────────────────────────

def _load_raster(path: pathlib.Path) -> tuple[np.ndarray, dict, np.ndarray]:
    """Charge un raster → (array float32, profile, mask bool)."""
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        profile = ds.profile.copy()
    mask = (arr == nodata) if nodata is not None else np.zeros_like(arr, dtype=bool)
    arr[mask] = 0.0
    return arr, profile, mask


def _resample_to(
    arr: np.ndarray,
    profile: dict,
    target_res_m: float,
) -> tuple[np.ndarray, dict]:
    """Rééchantillonne par somme de blocs vers target_res_m.

    Physiquement correct pour des rasters de comptage : la somme des retours
    dans une cellule 2 m² = la somme des 4 cellules 1 m² correspondantes.
    Utilise numpy reshape — Resampling.sum ne fonctionne pas en lecture rasterio.
    """
    src_res = abs(profile["transform"].a)
    if abs(target_res_m - src_res) < 1e-6:
        return arr, profile

    factor = max(1, round(target_res_m / src_res))

    # Tronquer aux dimensions multiples de factor
    h = (arr.shape[0] // factor) * factor
    w = (arr.shape[1] // factor) * factor
    data = arr[:h, :w]

    # Somme par blocs factor×factor
    aggregated = (
        data.reshape(h // factor, factor, w // factor, factor)
        .sum(axis=(1, 3))
    )

    t = profile["transform"]
    new_transform = rasterio.transform.Affine(
        t.a * factor, t.b, t.c,
        t.d, t.e * factor, t.f,
    )
    new_profile = profile.copy()
    new_profile.update(height=h // factor, width=w // factor, transform=new_transform)
    return aggregated.astype(np.float32), new_profile


def _align(*arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    """Tronque toutes les arrays à la plus petite forme commune (lignes, colonnes)."""
    r = min(a.shape[0] for a in arrays)
    c = min(a.shape[1] for a in arrays)
    return tuple(a[:r, :c] for a in arrays)


def _to_odd_pixels(distance_m: float, res_m: float, minimum: int = 3) -> int:
    """Convertit une distance physique en nb de pixels impair (minimum 3)."""
    px = max(minimum, round(distance_m / res_m))
    return px if px % 2 == 1 else px + 1


def _save_raster(
    arr: np.ndarray, path: pathlib.Path, profile: dict, dtype: str, nodata: float
) -> None:
    p = profile.copy()
    p.update(dtype=dtype, nodata=nodata, count=1,
             height=arr.shape[0], width=arr.shape[1])
    with rasterio.open(path, "w", **p) as ds:
        ds.write(arr.astype(dtype), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalisation + classification raster HAG (Phase 1)"
    )
    parser.add_argument("--src", default="output/density_hag.tif",
                        help="Raster HAG source (density_hag.tif ou count_band.tif)")
    parser.add_argument("--dst", default=None,
                        help="Répertoire de sortie (défaut : même dossier que --src)")
    args = parser.parse_args()

    src = pathlib.Path(args.src)
    out_dir = pathlib.Path(args.dst) if args.dst else src.parent

    # ── Config ────────────────────────────────────────────────────────────────
    cfg = yaml.safe_load(pathlib.Path("config.yaml").read_text(encoding="utf-8"))
    veg = cfg["vegetation"]

    preset_name = veg.get("active_preset", "grimbosq_v0")
    preset = veg["presets"][preset_name]
    T_406, T_408, T_410 = preset["thresholds"]
    thresholds_low = preset.get("thresholds_low", None)  # None = seuillage simple

    ph = veg.get("process_hag", {})
    sigma_m = float(ph.get("gaussian_sigma", 3.0))
    median_m = float(ph.get("median_size", 9.0))

    dm = veg.get("density_metric", {})
    MODE = dm.get("mode", "count")
    N_MIN = int(dm.get("n_min", 8))
    FILL_RADIUS = int(dm.get("nrd_fill_radius", 2))
    BAND_SPLIT = bool(dm.get("band_split", False))

    norm_cfg = veg.get("normalization", {})
    NORM_MODE = norm_cfg.get("mode", "p95_local")
    NORM_FIXED = norm_cfg.get("fixed_value", None)

    TARGET_RES = float(veg.get("grid_resolution_m", 1.0))

    print(f"Preset    : {preset_name} — seuils {T_406}/{T_408}/{T_410}")
    print(f"Mode      : {MODE} | norm={NORM_MODE} | res_cible={TARGET_RES}m | band_split={BAND_SPLIT}")

    # ── Chargement raster principal ───────────────────────────────────────────
    arr, profile, mask = _load_raster(src)
    src_res = abs(profile["transform"].a)

    if abs(TARGET_RES - src_res) > 1e-4:
        print(f"Rééchantillonnage {src_res}m → {TARGET_RES}m ...")
        arr, profile = _resample_to(arr, profile, TARGET_RES)
        mask, _ = _resample_to(mask.astype(np.float32), {**profile, "height": mask.shape[0], "width": mask.shape[1]}, TARGET_RES)
        mask = mask > 0.5

    actual_res = abs(profile["transform"].a)
    print(f"Résolution effective : {actual_res}m")

    # ── Calcul de la métrique ─────────────────────────────────────────────────
    metric_low: np.ndarray | None = None
    metric_mid: np.ndarray | None = None
    confidence: np.ndarray | None = None

    if MODE == "ratio":
        total_path = src.parent / "total_count.tif"
        if not total_path.exists():
            raise FileNotFoundError(f"Mode ratio nécessite {total_path}")
        total, tp, tm = _load_raster(total_path)
        if abs(TARGET_RES - src_res) > 1e-4:
            total, _ = _resample_to(total, tp, TARGET_RES)
        arr, total, mask = _align(arr, total, mask)
        # Cellules hors empreinte LiDAR (total=0, non nodata) : étendre le masque
        # pour qu'elles ne polluent pas la normalisation p95 ni l'IoU
        mask = mask | (total <= 0)
        metric = compute_ratio(arr, total, mask)
        valid_px = metric[~mask]
        if valid_px.size > 0:
            print(f"  ratio p50={np.percentile(valid_px, 50):.4f}  "
                  f"p95={np.percentile(valid_px, 95):.4f}  max={valid_px.max():.4f}")

    elif MODE == "nrd":
        below_path = src.parent / "count_below.tif"
        if not below_path.exists():
            raise FileNotFoundError(
                f"Mode nrd nécessite {below_path}\n"
                "  → lancer run_terrain.py avec mode nrd pour générer ce raster via PDAL."
            )
        below, bp, bm = _load_raster(below_path)
        if abs(TARGET_RES - src_res) > 1e-4:
            below, _ = _resample_to(below, bp, TARGET_RES)

        if BAND_SPLIT:
            low_path = src.parent / "count_band_low.tif"
            mid_path = src.parent / "count_band_mid.tif"
            if not low_path.exists() or not mid_path.exists():
                raise FileNotFoundError(
                    f"Mode nrd+band_split nécessite {low_path} et {mid_path}"
                )
            low, lp, lm = _load_raster(low_path)
            mid, mp, mm = _load_raster(mid_path)
            if abs(TARGET_RES - src_res) > 1e-4:
                low, _ = _resample_to(low, lp, TARGET_RES)
                mid, _ = _resample_to(mid, mp, TARGET_RES)
            low, mid, below, mask = _align(low, mid, below, mask)
            # Hors empreinte : ni low, ni mid, ni below → masquer
            mask = mask | ((low + mid + below) <= 0)
            metric_low, metric_mid, confidence = compute_nrd_bands(
                low, mid, below, mask, N_MIN, FILL_RADIUS
            )
            metric = metric_low
        else:
            arr, below, mask = _align(arr, below, mask)
            # Hors empreinte : ni band, ni below → masquer pour bloquer le fill
            mask = mask | ((arr + below) <= 0)
            metric, confidence = compute_nrd(arr, below, mask, N_MIN, FILL_RADIUS)

        # Sauvegarder confidence.tif
        _save_raster(confidence, out_dir / "confidence.tif", profile, "uint16", 0)
        print(f"Confidence -> {out_dir / 'confidence.tif'}")

    else:  # count
        metric = arr.copy()

    # ── Lissage ───────────────────────────────────────────────────────────────
    sigma_px = sigma_m / actual_res
    median_px = _to_odd_pixels(median_m, actual_res)
    print(f"Lissage   : gauss={sigma_px:.2f}px ({sigma_m}m) | médian={median_px}px ({median_m}m)")

    def _smooth(arr2d: np.ndarray) -> np.ndarray:
        s = gaussian_filter(arr2d, sigma=sigma_px)
        return median_filter(s, size=median_px)

    smoothed = _smooth(metric)
    smoothed_mid: np.ndarray | None = None
    if metric_mid is not None:
        smoothed_mid = _smooth(metric_mid)

    # ── Normalisation ─────────────────────────────────────────────────────────
    cur_mask = mask[:smoothed.shape[0], :smoothed.shape[1]]

    def _normalize(s: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, float]:
        valid_px = s[~m]
        if NORM_MODE == "p95_local":
            vmax = float(np.percentile(valid_px, 95)) if valid_px.size > 0 else 1.0
            out = np.clip(s / vmax if vmax > 1e-9 else s, 0.0, 1.0)
        elif NORM_MODE == "fixed_percentile":
            if NORM_FIXED is None:
                raise ValueError(
                    "normalization.fixed_value requis pour mode=fixed_percentile\n"
                    "  → mesurer une fois sur le corpus de calibration, geler dans config.yaml"
                )
            vmax = float(NORM_FIXED)
            out = np.clip(s / vmax, 0.0, 1.0)
        else:  # none
            vmax = 1.0
            out = np.clip(s, 0.0, 1.0)
        out[m] = 0.0
        return out, vmax

    smoothed, vmax = _normalize(smoothed, cur_mask)
    print(f"Norm      : {NORM_MODE} | vmax={vmax:.4f}")
    if smoothed_mid is not None:
        smoothed_mid, vmax_mid = _normalize(smoothed_mid, cur_mask)
        print(f"Norm mid  : vmax_mid={vmax_mid:.4f}")

    # ── Classification ────────────────────────────────────────────────────────
    classified = np.zeros(smoothed.shape, dtype=np.uint8)
    if thresholds_low is not None:
        L_406, L_408, L_410 = thresholds_low
        print(f"Hysteresis: t_low={L_406}/{L_408}/{L_410} t_high={T_406}/{T_408}/{T_410}")
        src_mid = smoothed_mid if smoothed_mid is not None else smoothed
        classified[_hysteresis_threshold(smoothed,  L_406, T_406)] = 85
        classified[_hysteresis_threshold(src_mid,   L_408, T_408)] = 170
        classified[_hysteresis_threshold(src_mid,   L_410, T_410)] = 255
    elif smoothed_mid is not None:
        # Étape D : 406 ← nrd_low, 408/410 ← nrd_mid
        classified[smoothed > T_406] = 85
        classified[smoothed_mid > T_408] = 170
        classified[smoothed_mid > T_410] = 255
    else:
        classified[smoothed > T_406] = 85
        classified[smoothed > T_408] = 170
        classified[smoothed > T_410] = 255
    classified[cur_mask] = 0

    # ── Sauvegarde ────────────────────────────────────────────────────────────
    dst_smoothed = out_dir / "density_hag_smoothed.tif"
    smoothed_save = smoothed.copy()
    smoothed_save[cur_mask] = -1.0
    _save_raster(smoothed_save, dst_smoothed, profile, "float32", -1.0)
    print(f"Lissé    -> {dst_smoothed}")

    dst = out_dir / "density_hag_classified.tif"
    _save_raster(classified, dst, profile, "uint8", 0)
    print(f"Classifié -> {dst}")
    print(f"  pixels 406 : {np.sum(classified == 85):,}")
    print(f"  pixels 408 : {np.sum(classified == 170):,}")
    print(f"  pixels 410 : {np.sum(classified == 255):,}")


if __name__ == "__main__":
    main()
