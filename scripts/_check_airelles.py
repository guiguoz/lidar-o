"""Check rapide : bbox output_airelles + layers airelles.gpkg."""
import pathlib
from osgeo import gdal, ogr

p = pathlib.Path("output_airelles/density_hag.tif")
if p.exists():
    ds = gdal.Open(str(p))
    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize
    xmin, ymax = gt[0], gt[3]
    xmax = xmin + w * gt[1]
    ymin = ymax + h * gt[5]
    print(f"density_hag bbox : ({xmin:.0f}, {ymin:.0f}, {xmax:.0f}, {ymax:.0f})")
    print(f"  surface : {(xmax-xmin)*(ymax-ymin)/1e4:.1f} ha")
    ds = None
else:
    print("density_hag.tif pas encore disponible (PDAL en cours)")

ds2 = ogr.Open("airelles.gpkg")
if ds2:
    for i in range(ds2.GetLayerCount()):
        lyr = ds2.GetLayerByIndex(i)
        print(f"Layer [{i}] : {lyr.GetName()} — {lyr.GetFeatureCount()} features")
