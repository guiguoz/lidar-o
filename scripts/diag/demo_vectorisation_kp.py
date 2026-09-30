"""Démo bout-en-bout du protocole de vectorisation du raster Karttapullautin.

Objet : montrer, sans dalles LiDAR ni binaire KP sous la main, ce que produit la
chaîne décrite dans docs/protocole_vectorisation_kp.md — et surtout l'écart entre
une vectorisation naïve et le protocole retenu.

    raster KP synthétique (2×2 tuiles *_vege_bit.png, palette et .pgw de KP)
        ↓ src/kp_raster.build_class_raster()        ← vrai code de production
    raster classifié DN 85/170/255
        ↓ polygonize                                ← GDAL Polygonize (via rasterio)
    polygones bruts (confetti, escaliers de pixels)
        ↓ src/vegetation._STAGES (10 étapes)        ← vrai moteur, vraie config.yaml
    vert généralisé + partition plane
        ↓ src/omap_writer.write_omap()              ← vrai writer
    work/demo/kp_vege_demo.omap  (végétation modifiable)

Seule la polygonisation est exécutée via `rasterio.features.shapes` au lieu de
`gdal.Polygonize` : c'est la même fonction GDAL, rasterio embarquant GDAL. Tout
le reste est le code de production, non modifié.

    python scripts/diag/demo_vectorisation_kp.py
"""
from __future__ import annotations

import logging
import pathlib
import sys

import numpy as np
import rasterio
import yaml
from rasterio.features import shapes
from scipy.ndimage import gaussian_filter, median_filter
from shapely.geometry import shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import geopandas as gpd  # noqa: E402

from src.kp_raster import KP_FIRST_GREEN, KP_YELLOW  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("demo")

# Grimbosq (asset georef présent dans le dépôt) — la démo doit tomber dedans.
WEST, NORTH = 448_500.0, 6888_500.0
TILE_M = 500                       # 4 tuiles de 500 m → 1 km²
N_TILES = 2
N_SHADES = 11                      # greenshades par défaut KP (dont 4 inactives)
TONE = 160                         # lightgreentone du dépôt
SCALE = 10_000                     # 1 mm carte = 10 m terrain → 1 mm² = 100 m²

WORK = ROOT / "work" / "demo"
FIGURE = ROOT / "docs" / "images" / "demo_vectorisation_kp.png"


# ── 1. Raster KP synthétique ──────────────────────────────────────────────────

def _density_field(size: int, seed: int) -> np.ndarray:
    """Champ de « verdeur » plausible : quelques échelles superposées.

    Reproduit les trois traits visibles d'une sortie KP :
      • des masses (forêt dense) à grande échelle,
      • du bruit de sous-bois à petite échelle,
      • des cellules de 3 m (greendetectsize) → contours en escalier.
    """
    rng = np.random.default_rng(seed)
    coarse = gaussian_filter(rng.normal(size=(size, size)), sigma=size / 12)
    mid = gaussian_filter(rng.normal(size=(size, size)), sigma=size / 40)
    fine = gaussian_filter(rng.normal(size=(size, size)), sigma=2.0)
    field = 0.55 * coarse + 0.30 * mid + 0.15 * fine
    field = (field - field.min()) / (np.ptp(field) + 1e-9)

    # Quantification par cellules de 3 m, comme le fait KP (greendetectsize=3).
    block = 3
    n = (size // block) * block
    cells = field[:n, :n].reshape(n // block, block, n // block, block).mean(axis=(1, 3))
    field = np.repeat(np.repeat(cells, block, axis=0), block, axis=1)

    # Massifs compacts : fourrés/taillis (vert foncé) et taches de sous-bois
    # (vert moyen). Sans eux, le filtre médian 17×17 de KP efface tout le vert
    # dense — comme sur un vrai terrain, le 410 vit en masses, pas en poussière.
    n_px = field.shape[0]
    yy, xx = np.indices((n_px, n_px))
    rng2 = np.random.default_rng(seed + 991)
    for _ in range(6):
        cx, cy = rng2.uniform(0.1, 0.9, 2) * n_px
        r = rng2.uniform(18, 45)
        field += 0.42 * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (r / 2.2) ** 2)))
    for _ in range(10):
        cx, cy = rng2.uniform(0.05, 0.95, 2) * n_px
        r = rng2.uniform(25, 70)
        field += 0.22 * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (r / 2.2) ** 2)))
    return np.clip(field, 0.0, None)


def make_synthetic_tiles(out_dir: pathlib.Path, seed: int = 7) -> list[pathlib.Path]:
    """Écrit 4 tuiles `*_vege_bit.png` + `.pgw` + un `pullauta.ini` façon KP batch."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = N_TILES * TILE_M
    full = _density_field(total, seed)
    cuts = np.quantile(full, [0.45, 0.60, 0.72, 0.80, 0.86, 0.91])
    tiles: list[pathlib.Path] = []
    for row in range(N_TILES):
        for col in range(N_TILES):
            west = WEST + col * TILE_M
            north = NORTH - row * TILE_M
            r0, c0 = row * TILE_M, col * TILE_M
            field = full[r0:r0 + TILE_M, c0:c0 + TILE_M]

            labels = np.zeros(field.shape, dtype=np.uint8)      # 0 = blanc (405)
            # Coupures placées sur les quantiles du champ, comme le fait un
            # cartographe qui règle greenshades sur un terrain donné (guide
            # greenmapping de J. Ryyppö) : la couverture visée est celle d'une
            # carte humaine — ~19 % de 406, 7 % de 408, 8 % de 410 (cibles
            # qa_targets mesurées sur la carte FFCO de Grimbosq). Ces coupures
            # donnent ici 18,4 / 6,5 / 6,0 ha pour 100 ha : c'est le réglage de
            # greenshades que ferait un cartographe sur CE terrain.
            for i, cut in enumerate(cuts):
                labels[field > cut] = KP_FIRST_GREEN + i

            # Terrain découvert (jaune KP) : une parcelle ouverte + lisières.
            yy, xx = np.indices(field.shape)
            open_land = ((xx - 90) ** 2 + (yy - 380) ** 2) < 70 ** 2
            open_land |= (field < 0.20) & (xx > TILE_M * 0.6)
            labels[open_land] = KP_YELLOW

            labels = _kp_median_passes(labels)

            name = f"LHD_FXX_044{col}_688{N_TILES - row}_vege_bit.png"
            path = out_dir / name
            with rasterio.open(path, "w", driver="PNG", height=labels.shape[0],
                               width=labels.shape[1], count=1, dtype="uint8") as ds:
                ds.write(labels, 1)
            # .pgw à la convention KP : centre du pixel haut-gauche, 1 px = 1 m.
            path.with_suffix(".pgw").write_text(
                f"1.0\n0.0\n0.0\n-1.0\n{west + 0.5}\n{north - 0.5}\n", encoding="utf-8")
            tiles.append(path)

    (out_dir / "pullauta.ini").write_text(
        "batch=1\n"
        "greenshades=0.2|0.35|0.5|0.7|1.3|2.6|4|99|99|99|99\n"
        f"lightgreentone={TONE}\n"
        "medianboxsize=9\nmedianboxsize2=16\nvege_bitmode=1\n",
        encoding="utf-8",
    )
    log.info("Tuiles KP synthétiques : %d × (%d×%d m) dans %s", len(tiles), TILE_M, TILE_M, out_dir)
    return tiles


def _kp_median_passes(labels: np.ndarray) -> np.ndarray:
    """Émule les deux filtres médians de KP (medianboxsize=9, medianboxsize2=16).

    KP filtre les verts et les jaunes **séparément** sur les indices de palette
    (src/vegetation.rs : `imggr1.median_filter(med/2, med/2)`), puis superpose le
    jaune. C'est cette passe qui donne aux masses vertes leur aspect « dessiné à
    la main » : sans elle, la sortie KP serait un confetti de cellules de 3 m — et
    c'est exactement ce que produit une vectorisation qui l'oublierait.
    """
    greens = np.where(labels >= KP_FIRST_GREEN, labels, 0).astype(np.uint8)
    greens = median_filter(greens, size=9, mode="nearest")
    greens = median_filter(greens, size=17, mode="nearest")

    yellow = (labels == KP_YELLOW).astype(np.uint8)
    yellow = median_filter(yellow, size=9, mode="nearest")
    yellow = median_filter(yellow, size=17, mode="nearest")

    return np.where(yellow == 1, KP_YELLOW, greens).astype(np.uint8)


# ── 2. Polygonisation (même algorithme GDAL que src/vegetation.stage_polygonize) ─

def polygonize(tif: pathlib.Path) -> gpd.GeoDataFrame:
    from src.vegetation import _HAG_CLASS_MAP

    with rasterio.open(tif) as ds:
        arr = ds.read(1)
        transform = ds.transform
        crs = ds.crs
    rows = [
        {"class": _HAG_CLASS_MAP.get(int(value), int(value)), "geometry": shape(geom)}
        for geom, value in shapes(arr, transform=transform)
        if int(value) != 0
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


# ── 3. Métriques « signature d'une carte humaine » ────────────────────────────

def metrics(gdf: gpd.GeoDataFrame, label: str) -> dict:
    from src.vegetation import _total_overlap

    mm2 = 100.0 if SCALE == 10_000 else 225.0      # 1 mm² carte en m² terrain
    out: dict = {"label": label}
    if gdf.empty:
        return {**out, "n": 0}
    for cls in (406, 408, 410):
        sub = gdf[gdf["class"] == cls]
        areas = sub.geometry.area / mm2 if not sub.empty else np.array([0.0])
        out[cls] = {
            "n": int(len(sub)),
            "ha": round(float(sub.geometry.area.sum()) / 10_000, 2),
            "med_mm2": round(float(np.median(areas)), 2),
            "pct_small": round(float((areas < 1.0).mean() * 100), 1),
        }
    out["n_total"] = int(len(gdf))
    out["sommets"] = int(sum(len(g.exterior.coords) for g in gdf.geometry
                             if hasattr(g, "exterior")))
    out["chevauchement_ha"] = round(_total_overlap(gdf) / 10_000, 3)
    return out


def print_metrics(rows: list[dict]) -> None:
    print("\n" + "=" * 78)
    print(f"{'':<26}{'objets':>8}{'sommets':>9}{'406 ha':>9}{'408 ha':>8}{'410 ha':>8}"
          f"{'méd. mm²':>10}{'% <1mm²':>9}{'chev. ha':>9}")
    print("-" * 78)
    for row in rows:
        if row.get("n", row.get("n_total", 0)) == 0 and 406 not in row:
            continue
        m406, m408, m410 = row.get(406, {}), row.get(408, {}), row.get(410, {})
        print(f"{row['label']:<26}{row.get('n_total', 0):>8}{row.get('sommets', 0):>9}"
              f"{m406.get('ha', 0):>9}{m408.get('ha', 0):>8}{m410.get('ha', 0):>8}"
              f"{m410.get('med_mm2', 0):>10}{m410.get('pct_small', 0):>9}"
              f"{row.get('chevauchement_ha', 0):>9}")
    print("=" * 78)
    print("Cibles mesurées sur carte FFCO humaine (config.yaml → qa_targets, hull 323,8 ha) :")
    print("   406 : méd. 5,17 mm² · 3,7 % < 1 mm² · compacité 0,663 · 1,1 % avec trous")
    print("   408 : méd. 2,31 mm² · 13,4 % < 1 mm²      410 : méd. 1,39 mm² · 32,0 % < 1 mm²")


# ── 4. Rendu comparatif ───────────────────────────────────────────────────────

ISOM_RGB = {406: "#a8e06a", 408: "#5ec24a", 410: "#1a9c28"}      # green 30/60/100 %


def render_figure(panels: list[tuple[str, np.ndarray | gpd.GeoDataFrame, str]],
                  path: pathlib.Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.kp_raster import kp_green_rgb

    fig, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 5.6))
    greens = kp_green_rgb(N_SHADES, TONE)
    extent = (WEST, WEST + N_TILES * TILE_M, NORTH - N_TILES * TILE_M, NORTH)

    for ax, (title, data, kind) in zip(axes, panels):
        if kind == "raster":
            rgb = np.zeros((*data.shape, 3), dtype=np.uint8)
            rgb[:] = (255, 255, 255)
            for i, g in enumerate(greens):
                rgb[data == KP_FIRST_GREEN + i] = g
            rgb[data == KP_YELLOW] = (255, 219, 166)
            ax.imshow(rgb, extent=extent, origin="upper", interpolation="nearest")
        else:
            ax.set_facecolor("white")
            for cls in (406, 408, 410):
                sub = data[data["class"] == cls]
                if sub.empty:
                    continue
                ax.add_collection(
                    matplotlib.collections.PatchCollection(
                        [matplotlib.patches.Polygon(g.exterior.coords, closed=True)
                         for g in sub.geometry if hasattr(g, "exterior")],
                        facecolor=ISOM_RGB[cls], edgecolor="none", zorder=2 + list(ISOM_RGB).index(cls)))
            ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
        ax.set_title(title, fontsize=10.5)
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#888")

    fig.suptitle("Vectorisation du raster Karttapullautin — 1 km² synthétique, échelle 1:10 000",
                 fontsize=12.5)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=145)
    log.info("Figure → %s", path)


# ── 4bis. Contrôle du .omap produit ───────────────────────────────────────────

def _verify_omap(path: pathlib.Path, expected_objects: int) -> None:
    """Relit le .omap écrit : symboles résolus, coordonnées aller-retour exactes.

    Un .omap dont les objets ne retrouvent pas leurs coordonnées terrain est
    inutilisable — c'est le contrôle minimal avant de l'ouvrir dans OOM.
    """
    import xml.etree.ElementTree as ET

    from src.omap_writer import _from_omap, _NSB, load_georef

    georef = load_georef(ROOT / "assets" / "georef_grimbosq.xml")
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    # Ne pas confondre les objets de la carte avec les <object> qui décrivent la
    # géométrie interne des symboles (206 dans le gabarit ISOM, sous <element>).
    block = root.find(f".//{_NSB}objects")
    assert block is not None, "bloc <objects> absent"
    objects = list(block)
    surfaces = [o for o in objects if o.get("type") == "1"]
    symbols = {int(o.get("symbol")) for o in surfaces}
    known = {int(sym.get("id")) for sym in root.iter(f"{_NSB}symbol") if sym.get("id")}
    assert surfaces, "aucun objet surface écrit"
    assert len(surfaces) == expected_objects, f"{len(surfaces)} objets ≠ {expected_objects}"
    assert symbols <= known, f"symboles inconnus du gabarit : {symbols - known}"
    assert int(block.get("count")) == len(objects), "attribut count incohérent"

    # Aller-retour coordonnées : le premier sommet doit retomber dans l'emprise.
    first = surfaces[0].find(f"{_NSB}coords")
    ox, oy = (int(v) for v in first.text.split(";")[0].split()[:2])
    x, y = _from_omap(ox, oy, georef)
    assert WEST - 5 <= x <= WEST + N_TILES * TILE_M + 5, f"X hors emprise : {x}"
    assert NORTH - N_TILES * TILE_M - 5 <= y <= NORTH + 5, f"Y hors emprise : {y}"
    print(f"Contrôle .omap : {len(surfaces)} objets surface, {len(symbols)} symbole(s) ISOM "
          f"résolu(s) dans le gabarit, premier sommet à X={x:.1f} Y={y:.1f} (Lambert-93).")


# ── 5. Enchaînement ───────────────────────────────────────────────────────────

def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    tiles = make_synthetic_tiles(WORK / "out_kp_demo")
    classified = WORK / "kp_vege_classified.tif"

    from src.kp_raster import build_class_raster
    report = build_class_raster(WORK / "out_kp_demo", cfg, "EPSG:2154", classified,
                                bbox=(WEST, NORTH - N_TILES * TILE_M,
                                      WEST + N_TILES * TILE_M, NORTH))
    print(f"\nRaster classifié : mode {report['input_mode']} · {report['res_m']} m/px · "
          f"{report['ha']} ha · jaune ignoré {report['yellow_ha_ignored']} ha")

    raw = polygonize(classified)
    rows = [metrics(raw, "1. polygonisé brut")]

    from src.vegetation import _STAGES

    def run_stages(config: dict, up_to: str | None = None) -> gpd.GeoDataFrame:
        out = raw.copy()
        for step_num, name, stage_fn in _STAGES:
            if up_to and name == up_to:
                break
            out, _ = stage_fn(out, config)
        return out

    # Témoin : le moteur SANS la partition plane (comportement antérieur).
    cfg_off = yaml.safe_load(yaml.safe_dump(cfg))
    profile = cfg_off["generalization"]["profiles"][cfg_off["generalization"]["active_profile"]]
    profile["planar_partition"] = False
    gdf_off = run_stages(cfg_off)
    rows.append(metrics(run_stages(cfg, up_to="coverage_partition"), "2. avant partition plane"))
    rows.append(metrics(gdf_off, "2bis. moteur sans partition"))

    gdf = run_stages(cfg)
    rows.append(metrics(gdf, "3. protocole complet"))
    print_metrics(rows)

    # .omap réel, végétation en objets modifiables.
    from src.omap_writer import Layer, load_georef, load_template, write_omap
    omap_out = WORK / "kp_vege_demo.omap"
    template = load_template(ROOT / "assets" / "ISOM 2017-2_10000.omap")
    georef = load_georef(ROOT / "assets" / "georef_grimbosq.xml")
    layers = []
    for cls in (406, 408, 410):
        sub = gdf[gdf["class"] == cls]
        if not sub.empty:
            layers.append(Layer(f"veg_{cls}", cls, list(sub.geometry)))
    write_omap(omap_out, template, layers, georef)
    total = sum(len(layer.geometries) for layer in layers)
    _verify_omap(omap_out, total)
    print(f"\n.omap écrit : {omap_out.relative_to(ROOT)}  ·  {total} objets verts "
          f"répartis sur {len(layers)} calques (406/408/410), symboles ISOM du gabarit, "
          f"géoréférencé Lambert-93 — modifiables dans OpenOrienteering Mapper.")

    # Recharge les tuiles pour afficher le rendu KP (panneau A).
    from src.kp_raster import load_tiles, mosaic, read_ini_vege_params
    params = read_ini_vege_params(WORK / "out_kp_demo" / "pullauta.ini")
    kp_labels, *_ = mosaic(load_tiles(WORK / "out_kp_demo", params))

    overlap_before = rows[-2]["chevauchement_ha"] if len(rows) > 2 else rows[-1]["chevauchement_ha"]
    render_figure([
        (f"A. Raster KP (mode {report['input_mode']})\nce que KP dessine — "
         f"{report['ha'].get('406', 0)}+{report['ha'].get('408', 0)}+{report['ha'].get('410', 0)} ha",
         kp_labels, "raster"),
        (f"B. Vectorisation naïve\n{rows[0]['n_total']} objets · "
         f"{rows[0]['sommets']:,} sommets · {rows[0][410]['pct_small']} % < 1 mm²",
         raw, "vector"),
        (f"C. Protocole retenu\n{rows[-1]['n_total']} objets · "
         f"{overlap_before} ha de chevauchements résorbés · partition plane",
         gdf, "vector"),
    ], FIGURE)


if __name__ == "__main__":
    main()
