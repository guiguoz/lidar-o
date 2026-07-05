"""Lissage + seuillage du raster HAG pour classification vegetation."""
import argparse
import pathlib
import numpy as np
import rasterio
import yaml
from scipy.ndimage import gaussian_filter, median_filter

parser = argparse.ArgumentParser()
parser.add_argument("--src", default="output/density_hag.tif")
parser.add_argument("--dst", default=None, help="Par defaut: meme dossier que --src")
args = parser.parse_args()

src = pathlib.Path(args.src)
out_dir = pathlib.Path(args.dst) if args.dst else src.parent
dst = out_dir / "density_hag_classified.tif"
dst_smoothed = out_dir / "density_hag_smoothed.tif"

PERCENTILE_MAX = 95

cfg = yaml.safe_load(pathlib.Path("config.yaml").read_text(encoding="utf-8"))
veg = cfg["vegetation"]
preset_name = veg.get("active_preset", "grimbosq_v0")
thresholds = veg["presets"][preset_name]["thresholds"]
T_406, T_408, T_410 = thresholds
ph = veg.get("process_hag", {})
SIGMA = float(ph.get("gaussian_sigma", 3.0))
MEDIAN_SIZE = int(ph.get("median_size", 9))
MODE = veg.get("density_metric", {}).get("mode", "count")
print(f"Preset: {preset_name} -- seuils {T_406}/{T_408}/{T_410} -- sigma={SIGMA} median={MEDIAN_SIZE} mode={MODE}")

with rasterio.open(src) as ds:
    arr = ds.read(1).astype(np.float32)
    nodata = ds.nodata
    profile = ds.profile.copy()

mask = (arr == nodata) if nodata is not None else np.zeros_like(arr, dtype=bool)
arr[mask] = 0.0

if MODE == "ratio":
    total_path = src.parent / "total_count.tif"
    if not total_path.exists():
        raise FileNotFoundError(f"Mode ratio nécessite {total_path} — lancer pdal_airelles_total.json d'abord")
    with rasterio.open(total_path) as ds_t:
        total = ds_t.read(1).astype(np.float32)
        total_nodata = ds_t.nodata
    if total_nodata is not None:
        total[total == total_nodata] = 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        arr = np.where((total > 0) & ~mask, arr / total, 0.0)
    arr = np.clip(arr, 0, 1)
    arr[mask] = 0.0
    print(f"  ratio p50={np.percentile(arr[~mask], 50):.4f}  p95={np.percentile(arr[~mask], 95):.4f}  max={arr[~mask].max():.4f}")

smoothed = gaussian_filter(arr, sigma=SIGMA)
smoothed = median_filter(smoothed, size=MEDIAN_SIZE)

vmax = float(np.percentile(smoothed[~mask], PERCENTILE_MAX))
smoothed = np.clip(smoothed / vmax, 0, 1)
smoothed[mask] = 0.0

classified = np.zeros_like(smoothed, dtype=np.uint8)
classified[smoothed > T_406] = 85   # 406
classified[smoothed > T_408] = 170  # 408
classified[smoothed > T_410] = 255  # 410
classified[mask] = 0

# Sauvegarde intermédiaire lissé
prof_f32 = profile.copy()
prof_f32.update(dtype="float32", nodata=-1.0, count=1)
smoothed_save = smoothed.copy()
smoothed_save[mask] = -1.0
with rasterio.open(dst_smoothed, "w", **prof_f32) as ds_out:
    ds_out.write(smoothed_save, 1)
print(f"Lisse    -> {dst_smoothed}")

# Sauvegarde classifié
prof_u8 = profile.copy()
prof_u8.update(dtype="uint8", nodata=0, count=1)
with rasterio.open(dst, "w", **prof_u8) as ds_out:
    ds_out.write(classified, 1)

print(f"Classifie -> {dst}")
print(f"  vmax (p{PERCENTILE_MAX}) = {vmax:.4f}")
print(f"  pixels 406 : {np.sum(classified == 85):,}")
print(f"  pixels 408 : {np.sum(classified == 170):,}")
print(f"  pixels 410 : {np.sum(classified == 255):,}")
