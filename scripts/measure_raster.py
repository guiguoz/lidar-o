"""Mesure la surface raster par classe AVANT vectorisation."""
import sys
import pathlib
import rasterio
import numpy as np

raster = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("output/density_hag_classified.tif")

with rasterio.open(raster) as src:
    data = src.read(1)
    res = src.res

pixel_area_m2 = abs(res[0] * res[1])
classes = [406, 408, 410]
raster_map = {85: 406, 170: 408, 255: 410}
counts = {co_cls: int((data == raw).sum()) for raw, co_cls in raster_map.items()}
total = sum(counts.values())

print(f"Raster : {raster}")
print(f"Resolution : {res[0]:.2f} x {res[1]:.2f} m")
print(f"Total pixels classes : {total}")
print()

ha = {}
for cls in classes:
    n = counts[cls]
    surface_ha = n * pixel_area_m2 / 10000
    pct = 100 * n / total if total else 0
    ha[cls] = surface_ha
    print(f"  Classe {cls} : {n:8d} px   {surface_ha:8.2f} ha   {pct:.1f}%")

print()
r406 = ha[406] / ha[410] if ha[410] else 0
r408 = ha[408] / ha[410] if ha[410] else 0
print(f"Ratio raster  406:408:410 = {r406:.1f} : {r408:.1f} : 1.0")
print(f"Ratio FFCO ref             = 5.4 : 2.7 : 1.0")
print(f"Ratio polygones generes    = 0.8 : 1.2 : 1.0  (142:202:174)")
