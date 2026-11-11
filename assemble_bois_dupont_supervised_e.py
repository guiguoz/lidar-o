"""Produit output/bois_dupont_supervised_e_fidele.omap depuis le raster supervised_e.

Deux modes :
  fidele     (défaut) : aucun filtrage de composante, aucune simplification.
                        Objectif : zéro différence de catégorie sur pixels supportés.
  generalise          : filtre MIN_AREA_M2=16 m² (archive — comportement v1).

Sources :
  Végétation  ← output/supervised_e_test_bd/supervised_e_prediction.tif
               (prédiction RF 63 features, classes 0–4 + support, 2 m/px)
  Relief      ← out_kp_bois_dupont/*.dxf  (courbes, buttes, dépressions)
  Anthropique ← data/bois_dupont_bdtopo.gpkg  (chemins, bâtiments)
  Remplissage ← data/bois_dupont_bdtopo.gpkg + OSM cache (si présent)

Pas de réentraînement.  Pas de vegetation_kp.gpkg.  Pas d'image OCAD.
Aucune dépendance vers des chemins de référence cartographiques.

Classes supervisées → codes ISOM :
  0 (découvert) → 401  1 (blanc) → fond blanc (pas de polygone, classe par défaut)
  2 (veg_406)  → 406  3 (veg_408) → 408   4 (veg_410) → 410

Pixels inconnus (support=0, 56 px = 0.02%) :
  Aucun objet OOM n'est créé sur ces pixels. Ils apparaissent comme fond blanc
  mais ne sont pas courables — le masque de couverture est exporté dans
  output/bois_dupont_supervised_e_coverage.tif (bande 1 : uint8, 1=couvert, 0=inconnu).

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe assemble_bois_dupont_supervised_e.py [--mode fidele|generalise]
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import numpy as np
import rasterio
import shapely.geometry as sg
from rasterio.features import shapes
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import make_valid

ROOT    = pathlib.Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
ASSETS  = ROOT / "assets"
DATA    = ROOT / "data"
OUTPUT  = ROOT / "output"

sys.path.insert(0, str(ROOT))

from scripts.generate_bdtopo import build_bdtopo_layers, load_mapping as load_bd_mapping
from scripts.generate_relief import build_relief_layers, load_relief_mapping
from scripts.mask_vegetation import build_fill_layers
from src.omap_writer import Layer, load_georef, load_template, write_omap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

TERRAIN  = "bois_dupont"
BBOX     = (425000.0, 6922000.0, 426000.0, 6923000.0)

PRED_TIF    = ROOT / "output" / "supervised_e_test_bd" / "supervised_e_prediction.tif"
OUT_KP      = ROOT / f"out_kp_{TERRAIN}"
BDTOPO      = DATA / f"{TERRAIN}_bdtopo.gpkg"
GEOREF      = ASSETS / f"georef_{TERRAIN}.xml"
TEMPLATE    = ASSETS / "ISOM 2017-2_10000.omap"
COV_TIF     = OUTPUT / f"{TERRAIN}_supervised_e_coverage.tif"

# classe 1 (blanc/405) = fond blanc, aucun polygone
_CLASS_TO_ISOM: dict[int, int] = {
    0: 401,
    2: 406,
    3: 408,
    4: 410,
}

# Seuil de filtrage selon le mode :
#   fidele     → 0.0  (aucun filtrage — fidélité pixel à pixel)
#   generalise → 16.0 (archive v1 — supprime composantes < 2×2 pixels)
_MIN_AREA_FIDELE     = 0.0
_MIN_AREA_GENERALISE = 16.0


def _vectorize_class(
    pred: np.ndarray,
    support: np.ndarray,
    class_id: int,
    transform,
    min_area_m2: float = 0.0,
) -> list[Polygon]:
    """Rasterio shapes → liste de Polygons valides de classe class_id.

    min_area_m2=0.0 (mode fidele) : aucun filtrage de composante.
    min_area_m2>0   (mode generalise) : suppression des petites composantes.
    Aucune simplification ni lissage dans les deux cas.
    """
    mask = ((pred == class_id) & support).astype("uint8")
    if mask.sum() == 0:
        return []
    polys: list[Polygon] = []
    for geom_dict, val in shapes(mask, mask=mask, transform=transform):
        if val != 1:
            continue
        geom = make_valid(shape(geom_dict))
        if isinstance(geom, Polygon):
            if geom.is_valid and not geom.is_empty and geom.area > min_area_m2:
                polys.append(geom)
        elif isinstance(geom, MultiPolygon):
            for p in geom.geoms:
                if isinstance(p, Polygon) and p.is_valid and not p.is_empty and p.area > min_area_m2:
                    polys.append(p)
    return polys


def _export_coverage(support: np.ndarray, pred_ds: rasterio.DatasetReader) -> None:
    """Exporte le masque de couverture LiDAR dans un GeoTIFF séparé.

    bande 1 uint8 : 1 = pixel évaluable, 0 = hors couverture LiDAR.
    Ces pixels ne reçoivent aucun objet dans le .omap et ne sont pas
    courables — ils doivent être traités comme zone d'incertitude.
    """
    import rasterio as _rio
    with _rio.open(
        str(COV_TIF), "w",
        driver="GTiff", height=pred_ds.height, width=pred_ds.width,
        count=1, dtype="uint8",
        crs=pred_ds.crs, transform=pred_ds.transform,
        compress="lzw",
    ) as dst:
        dst.write(support.astype("uint8"), 1)
        dst.update_tags(
            description="Masque couverture LiDAR supervised_e",
            value_1="pixel evalue (couvert)",
            value_0="pixel hors couverture — ni predit ni courable",
        )
    n_unknown = int((~support).sum())
    log.info("Coverage mask : %s  (%d pixels inconnus = %.2f%%)",
             COV_TIF.name, n_unknown, 100. * n_unknown / support.size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble .omap supervised_e Bois Dupont")
    parser.add_argument(
        "--mode", choices=["fidele", "generalise"], default="fidele",
        help="fidele (defaut) : aucun filtrage de composante. "
             "generalise : filtre MIN_AREA=16 m2 (archive v1).",
    )
    args = parser.parse_args()

    if args.mode == "fidele":
        min_area  = _MIN_AREA_FIDELE
        out_omap  = OUTPUT / f"{TERRAIN}_supervised_e_fidele.omap"
        mode_note = "mode FIDELE — aucun filtrage, aucune simplification"
    else:
        min_area  = _MIN_AREA_GENERALISE
        out_omap  = OUTPUT / f"{TERRAIN}_supervised_e.omap"
        mode_note = f"mode GENERALISE — filtre MIN_AREA={_MIN_AREA_GENERALISE} m2 (archive v1)"

    log.info("=== Assemblage supervised_e — %s ===", mode_note)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    if not PRED_TIF.exists():
        sys.exit(
            f"ERREUR : raster supervised_e absent : {PRED_TIF}\n"
            "Exécuter src/supervised_e.run_supervised_e() d'abord."
        )

    # ── 1. Végétation supervised_e ────────────────────────────────────────────
    log.info("Chargement raster supervised_e : %s", PRED_TIF.name)
    with rasterio.open(str(PRED_TIF)) as ds:
        pred      = ds.read(1)              # classes 0–4 ou 255
        support   = ds.read(2).astype(bool) # bande support (1 = évaluable)
        transform = ds.transform
        log.info("  grille %d×%d px  support=%d/%d  inconnus=%d",
                 ds.height, ds.width,
                 int(support.sum()), ds.height * ds.width,
                 int((~support).sum()))
        _export_coverage(support, ds)

    template = load_template(TEMPLATE)
    all_layers: list = []

    for class_id, isom_code in _CLASS_TO_ISOM.items():
        if isom_code not in template.code_to_id:
            log.warning("ISOM %d absent du gabarit — classe %d ignorée", isom_code, class_id)
            continue
        polys = _vectorize_class(pred, support, class_id, transform, min_area_m2=min_area)
        if polys:
            all_layers.append(Layer(f"veg_{isom_code}", isom_code, polys))
            total_ha = sum(p.area for p in polys) / 10_000
            log.info("  classe %d -> ISOM %d : %d polygones  (%.2f ha)",
                     class_id, isom_code, len(polys), total_ha)
        else:
            log.info("  classe %d -> ISOM %d : aucun polygone", class_id, isom_code)

    n_veg = len(all_layers)
    log.info("Végétation supervised_e : %d couches", n_veg)

    # ── 2. Remplissage (zone_d_habitation + OSM) ─────────────────────────────
    bbox_geom    = sg.box(*BBOX)
    bdtopo_gpkg  = BDTOPO if BDTOPO.exists() else None
    osm_cache    = DATA / f"osm_landuse_{TERRAIN}.json"
    osm_cache    = osm_cache if osm_cache.exists() else None

    if bdtopo_gpkg is None:
        log.warning("BD TOPO absent — remplissage et couches anthropiques ignorées")

    fill = build_fill_layers(bdtopo_gpkg, osm_cache, bbox_geom, terrain_crs="EPSG:2154")
    all_layers += fill
    log.info("Remplissage (520/401/403) : %d couches", len(fill))

    # ── 3. Couches anthropiques BD TOPO (chemins, bâtiments) ─────────────────
    if bdtopo_gpkg is not None:
        bd_mapping  = load_bd_mapping(SCRIPTS / "mappings" / "bdtopo_isom.yaml")
        bd_layers   = build_bdtopo_layers(bdtopo_gpkg, bd_mapping)
        all_layers += bd_layers
        log.info("BD TOPO anthropique : %d couches", len(bd_layers))

    # ── 4. Relief KP (DXF) ───────────────────────────────────────────────────
    if OUT_KP.exists():
        rel_mapping, rel_skip = load_relief_mapping(SCRIPTS / "mappings" / "kp_relief.yaml")
        relief_layers = build_relief_layers(OUT_KP, rel_mapping, rel_skip, bbox=BBOX)
        all_layers   += relief_layers
        n_relief = sum(len(lyr.segments) if hasattr(lyr, "segments") else len(lyr.points)
                       for lyr in relief_layers)
        log.info("Relief KP : %d couches  (%d éléments)", len(relief_layers), n_relief)
    else:
        log.warning("out_kp_%s/ absent — relief non inclus", TERRAIN)

    # ── 5. Écriture .omap ────────────────────────────────────────────────────
    georef = load_georef(GEOREF)
    write_omap(out_omap, template, all_layers, georef, image_templates=None)
    n_total_obj = sum(
        (len(lyr.geometries) if hasattr(lyr, "geometries") else
         len(lyr.segments)   if hasattr(lyr, "segments")   else
         len(lyr.points))
        for lyr in all_layers
    )
    log.info("==> %s  (%d objets total)", out_omap, n_total_obj)
    log.info("    %s", mode_note)
    log.info("    Coverage mask : %s", COV_TIF)
    log.info("    Pixels inconnus (support=0) : absents du .omap, non courables")


if __name__ == "__main__":
    main()
