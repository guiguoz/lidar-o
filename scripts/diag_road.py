"""Diagnostic route : crop 400x400m autour d'un point OOM, panneau 4-couches."""
import pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import rasterio
from rasterio.windows import from_bounds

# Coordonnées du point OOM (EPSG:2154)
CX, CY = 623466, 6157042
HALF = 200  # demi-côté en mètres → zone 400×400m

BOUNDS = (CX - HALF, CY - HALF, CX + HALF, CY + HALF)

OUT_DIR = pathlib.Path("output_airelles")
RATIO_TIF  = OUT_DIR / "density_ratio.tif"
CLASS_TIF  = OUT_DIR / "density_hag_classified.tif"

def crop(path, bounds):
    with rasterio.open(path) as ds:
        win = from_bounds(*bounds, ds.transform)
        arr = ds.read(1, window=win).astype(np.float32)
        nodata = ds.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        return arr

ratio = crop(RATIO_TIF, BOUNDS)
cls   = crop(CLASS_TIF, BOUNDS)

# Panneau classifié en couleurs CO
cmap_cls = mcolors.ListedColormap(["#f5f5dc", "#90ee90", "#32cd32", "#006400"])
bounds_cls = [-0.5, 42.5, 127.5, 212.5, 255.5]
norm_cls = mcolors.BoundaryNorm(bounds_cls, cmap_cls.N)

fig, axes = plt.subplots(1, 2, figsize=(12, 6))

im0 = axes[0].imshow(ratio, cmap="YlOrRd", vmin=0, vmax=0.5, interpolation="nearest")
axes[0].set_title(f"density_ratio (HAG/total)\ncentre ({CX},{CY})", fontsize=9)
plt.colorbar(im0, ax=axes[0], fraction=0.046)

im1 = axes[1].imshow(cls, cmap=cmap_cls, norm=norm_cls, interpolation="nearest")
axes[1].set_title("classified (0=vide / 85=406 / 170=408 / 255=410)", fontsize=9)
plt.colorbar(im1, ax=axes[1], fraction=0.046, ticks=[0, 85, 170, 255])

for ax in axes:
    ax.axis("off")

out = OUT_DIR / "diag_road.png"
plt.tight_layout()
plt.savefig(out, dpi=150)
print(f"Enregistre -> {out}")
