"""Convertit les GeoJSON T8 en Shapefile et GeoPackage pour import OCAD."""
import pathlib
import geopandas as gpd

out = pathlib.Path("output")

classes = [406, 408, 410]

# GeoPackage unique (toutes classes, une couche par classe)
gpkg = out / "vegetation_t8.gpkg"
for cls in classes:
    src = out / f"veg_{cls}_t8.geojson"
    gdf = gpd.read_file(src)
    gdf.to_file(gpkg, layer=f"veg_{cls}", driver="GPKG")
    print(f"  GPKG couche veg_{cls} : {len(gdf)} polygones")

# Shapefiles individuels (si OCAD ancienne version)
shp_dir = out / "shp"
shp_dir.mkdir(exist_ok=True)
for cls in classes:
    src = out / f"veg_{cls}_t8.geojson"
    gdf = gpd.read_file(src)
    gdf.to_file(shp_dir / f"veg_{cls}_t8.shp")
    print(f"  SHP veg_{cls} : {len(gdf)} polygones -> shp/veg_{cls}_t8.shp")

print(f"\nGeoPackage : {gpkg}")
print(f"Shapefiles : {shp_dir}/")
