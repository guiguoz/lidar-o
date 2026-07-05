"""Diagnostic artefact bandes : comparatif total_count / density_hag / ratio."""
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio


def load(path: pathlib.Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr, ds.profile


def main():
    out_dir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("output_airelles")
    total, prof = load(out_dir / "total_count.tif")
    hag, _     = load(out_dir / "density_hag.tif")

    # ratio HAG / total — NaN où total == 0 ou hors emprise
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where((total > 0) & ~np.isnan(hag), hag / total, np.nan)

    # sauvegarde density_ratio.tif
    prof_out = prof.copy()
    prof_out.update(dtype="float32", nodata=-1.0)
    ratio_save = np.where(np.isnan(ratio), -1.0, ratio).astype(np.float32)
    with rasterio.open(out_dir / "density_ratio.tif", "w", **prof_out) as dst:
        dst.write(ratio_save, 1)
    print(f"Sauvegardé : {out_dir}/density_ratio.tif")

    # stats
    for name, arr in [("total_count", total), ("density_hag", hag), ("density_ratio", ratio)]:
        valid = arr[~np.isnan(arr)]
        print(f"  {name}: min={valid.min():.3f}  p50={np.median(valid):.3f}  p95={np.percentile(valid,95):.3f}  max={valid.max():.3f}")

    # viz 3 panneaux
    fig, axes = plt.subplots(1, 3, figsize=(21, 8))

    def p(arr, q): return float(np.nanpercentile(arr, q))

    axes[0].imshow(total, cmap="viridis", vmin=0, vmax=p(total, 98), interpolation="nearest")
    axes[0].set_title(f"total_count.tif\n(tous retours, sans filtre)\np95={p(total,95):.1f} ret/m²")

    axes[1].imshow(hag, cmap="viridis", vmin=0, vmax=p(hag, 98), interpolation="nearest")
    axes[1].set_title(f"density_hag.tif\n(retours HAG 0.3–3 m)\np95={p(hag,95):.1f} ret/m²")

    axes[2].imshow(ratio, cmap="RdYlGn", vmin=0, vmax=p(ratio, 98), interpolation="nearest")
    axes[2].set_title(f"density_ratio.tif\n(HAG / total)\np95={p(ratio,95):.3f}")

    for ax in axes:
        ax.axis("off")

    plt.suptitle("Diagnostic artefact bandes — Airelles", fontsize=14)
    plt.tight_layout()
    out = out_dir / "diag_ratio.png"
    plt.savefig(out, dpi=90, bbox_inches="tight")
    print(f"Sauvegardé : {out}")


if __name__ == "__main__":
    main()
