"""Diagnostic bandes : comparatif density_hag brut vs lissé vs classifié."""
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import rasterio
import yaml
from scipy.ndimage import gaussian_filter, median_filter


def load_raster(path: pathlib.Path) -> tuple[np.ndarray, object]:
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr, ds.profile


def main():
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("output_airelles/density_hag.tif")
    out_dir = src.parent

    cfg = yaml.safe_load(pathlib.Path("config.yaml").read_text(encoding="utf-8"))
    veg = cfg["vegetation"]
    preset_name = veg.get("active_preset", "grimbosq_v0")
    thresholds = veg["presets"][preset_name]["thresholds"]
    T_406, T_408, T_410 = thresholds
    ph = veg.get("process_hag", {})
    sigma = float(ph.get("gaussian_sigma", 3.0))
    median_r = int(ph.get("median_size", 9))
    print(f"sigma={sigma}  median={median_r}  seuils={T_406}/{T_408}/{T_410}")

    raw, _ = load_raster(src)
    mask = np.isnan(raw)
    raw_filled = np.where(mask, 0.0, raw)

    gauss = gaussian_filter(raw_filled, sigma=sigma)
    after_median = median_filter(gauss, size=median_r)
    vmax = float(np.nanpercentile(after_median[~mask], 95))
    smoothed_norm = np.clip(after_median / vmax, 0, 1)
    smoothed_norm[mask] = np.nan

    classified = np.zeros_like(smoothed_norm, dtype=np.uint8)
    classified[smoothed_norm > T_406] = 85
    classified[smoothed_norm > T_408] = 170
    classified[smoothed_norm > T_410] = 255
    classified = classified.astype(float)
    classified[mask] = np.nan

    # --- save all intermediates ---
    with rasterio.open(src) as ds:
        prof = ds.profile.copy()
    prof.update(dtype="float32", nodata=-1.0, count=1)

    for name, arr_out in [
        ("density_hag_gauss.tif", gauss),
        ("density_hag_median.tif", after_median),
        ("density_hag_smoothed.tif", smoothed_norm),
    ]:
        save_arr = arr_out.copy()
        save_arr[mask] = -1.0
        with rasterio.open(out_dir / name, "w", **prof) as dst:
            dst.write(save_arr.astype(np.float32), 1)
        print(f"Sauvegardé : {out_dir}/{name}")

    # --- 4-panel viz ---
    fig, axes = plt.subplots(1, 4, figsize=(26, 8))

    p98 = float(np.nanpercentile(raw[~mask], 98))
    axes[0].imshow(raw, cmap="viridis", vmin=0, vmax=p98, interpolation="nearest")
    axes[0].set_title(f"1. Brut (density_hag)\np95={np.nanpercentile(raw[~mask],95):.1f} ret/m²")

    axes[1].imshow(gauss, cmap="plasma", vmin=0, vmax=float(np.nanpercentile(gauss[~mask], 98)), interpolation="nearest")
    axes[1].set_title(f"2. Après gaussien σ={sigma}")

    axes[2].imshow(smoothed_norm, cmap="plasma", vmin=0, vmax=1, interpolation="nearest")
    axes[2].set_title(f"3. Après médian {median_r}×{median_r} + normalisation\nvmax={vmax:.2f}")

    cmap_co = mcolors.ListedColormap(["#1a1a2e", "#90EE90", "#228B22", "#004d00"])
    bounds_co = [-1, 42, 127, 212, 256]
    norm_co = mcolors.BoundaryNorm(bounds_co, cmap_co.N)
    axes[3].imshow(classified, cmap=cmap_co, norm=norm_co, interpolation="nearest")
    n406 = int(np.nansum(classified == 85))
    n408 = int(np.nansum(classified == 170))
    n410 = int(np.nansum(classified == 255))
    axes[3].set_title(f"4. Classifié\n406:{n406/1e3:.0f}k  408:{n408/1e3:.0f}k  410:{n410/1e3:.0f}k px")

    for ax in axes:
        ax.axis("off")

    plt.suptitle(f"Diagnostic bandes — {src.parent.name}", fontsize=14)
    plt.tight_layout()
    out_path = out_dir / "diag_bandes.png"
    plt.savefig(out_path, dpi=90, bbox_inches="tight")
    print(f"Sauvegardé : {out_path}")


if __name__ == "__main__":
    main()
