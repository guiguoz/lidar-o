"""Exporte les GeoJSON T10 en GeoPackage pour import OCAD."""
import pathlib
import geopandas as gpd

for out_dir, suffix in [("output", "grimbosq"), ("output_airelles", "airelles")]:
    out = pathlib.Path(out_dir)
    gpkg = out / "vegetation_t10.gpkg"
    for cls in [406, 408, 410]:
        src = out / f"veg_{cls}_t10.geojson"
        gdf = gpd.read_file(src)
        gdf.to_file(gpkg, layer=f"veg_{cls}", driver="GPKG")
        print(f"  {suffix} veg_{cls} : {len(gdf)} polygones -> {gpkg}")
