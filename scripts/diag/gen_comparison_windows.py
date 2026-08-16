"""Génère deux images de comparaison pipeline vs FFCO (500m×500m, 1:10000).

Fenêtres :
  - dense  : coeur de forêt (406 dense)
  - lisiere: transition forêt/ouvert

Usage :
    python scripts/diag/gen_comparison_windows.py
Sortie :
    output/comparaison_dense.png
    output/comparaison_lisiere.png
"""
import pathlib
import json
import warnings

import matplotlib
matplotlib.use("Agg")  # backend non-interactif, évite le segfault sur Windows+conda
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import PatchCollection
import shapely.geometry as sg
from shapely.ops import unary_union
from osgeo import ogr

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).parent.parent.parent
OUTPUT = ROOT / "output"

# ── couleurs ISOM ──────────────────────────────────────────────────────────────
COLORS = {406: "#C8E682", 408: "#73C97E", 410: "#009B56"}
LABELS = {406: "406 course lente", 408: "408 marche", 410: "410 progr. difficile"}

FFCO_MAP = {
    "course lente": 406,
    "course lente, bonne": 406,
    "marche, bonne": 408,
    "marche dans": 408,
    "progression": 410,
}


def _ffco_class(name: str) -> int | None:
    if name is None:
        return None
    low = name.lower()
    for kw, cls in FFCO_MAP.items():
        if kw in low:
            return cls
    if "marche" in low:
        return 408
    return None


def load_ffco(gpkg_path: pathlib.Path) -> dict[int, list]:
    """Charge les polygones FFCO via OGR → dict classe → liste de géométries."""
    ds = ogr.Open(str(gpkg_path))
    lyr = ds.GetLayerByName("grimbosq_areas")
    lyr.ResetReading()
    geoms: dict[int, list] = {406: [], 408: [], 410: []}
    for feat in lyr:
        name = feat.GetField("Name")
        cls = _ffco_class(name)
        if cls is None:
            continue
        ogr_geom = feat.GetGeometryRef()
        if ogr_geom is None:
            continue
        try:
            shp = sg.shape(json.loads(ogr_geom.ExportToJson()))
            if shp.is_valid and not shp.is_empty:
                geoms[cls].append(shp)
        except Exception:
            pass
    return geoms


def load_pipeline(gpkg_path: pathlib.Path) -> dict[int, list]:
    """Charge les polygones pipeline depuis vegetation_masked.gpkg."""
    geoms: dict[int, list] = {406: [], 408: [], 410: []}
    for cls, layer in [(406, "veg_406"), (408, "veg_408"), (410, "veg_410")]:
        gdf = gpd.read_file(str(gpkg_path), layer=layer)
        geoms[cls] = list(gdf.geometry)
    return geoms


def pick_windows(ffco: dict[int, list]) -> list[tuple[str, sg.box]]:
    """Fenêtres 500m×500m, calibrées sur le hull FFCO (toutes deux entièrement à l'intérieur).

    Sélectionnées par analyse de la grille FFCO :
    - dense   : [448191, 6887556, 448691, 6888056] — 57% surface 406, entièrement dans hull
    - lisiere : [449291, 6887656, 449791, 6888156] — 63% vide, transition est, dans hull
    """
    return [
        ("dense",   sg.box(448191, 6887556, 448691, 6888056)),
        ("lisiere", sg.box(449291, 6887656, 449791, 6888156)),
    ]


def _draw_geoms(ax, geoms: list, color: str, alpha: float = 0.75, zorder: int = 2) -> None:
    for g in geoms:
        if g is None or g.is_empty:
            continue
        parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        for part in parts:
            xs, ys = part.exterior.xy
            ax.fill(xs, ys, color=color, alpha=alpha, zorder=zorder, linewidth=0)
            for hole in part.interiors:
                hx, hy = hole.xy
                ax.fill(hx, hy, color="white", zorder=zorder + 1, linewidth=0)


def _clip_geoms(geoms: list, window: sg.box) -> list:
    out = []
    for g in geoms:
        try:
            c = g.intersection(window)
            if not c.is_empty:
                out.append(c)
        except Exception:
            pass
    return out


def plot_window(
    win_name: str,
    window: sg.box,
    ffco: dict[int, list],
    pipeline: dict[int, list],
    out_path: pathlib.Path,
) -> None:
    minx, miny, maxx, maxy = window.bounds
    pad = 20

    fig, axes = plt.subplots(1, 2, figsize=(14, 7), facecolor="white")
    fig.suptitle(
        f"Comparaison pipeline / FFCO — fenêtre {win_name} ({int(maxx-minx)}m × {int(maxy-miny)}m)",
        fontsize=12, fontweight="bold"
    )

    titles = ["Carte FFCO (référence)", "Pipeline (généré)"]
    datasets = [ffco, pipeline]

    for ax, title, data in zip(axes, titles, datasets):
        ax.set_facecolor("#F5F0E8")  # fond papier clair
        ax.set_xlim(minx - pad, maxx + pad)
        ax.set_ylim(miny - pad, maxy + pad)
        ax.set_aspect("equal")
        ax.set_title(title, fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])

        for cls in [410, 408, 406]:
            clipped = _clip_geoms(data[cls], window)
            _draw_geoms(ax, clipped, COLORS[cls])

        # cadre
        rect = plt.Polygon(
            [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)],
            fill=False, edgecolor="black", linewidth=1.2, zorder=10
        )
        ax.add_patch(rect)

        # échelle 100m
        bar_x = minx + 20
        bar_y = miny + 20
        ax.plot([bar_x, bar_x + 100], [bar_y, bar_y], color="black", linewidth=2, zorder=10)
        ax.text(bar_x + 50, bar_y + 8, "100 m", ha="center", va="bottom", fontsize=8, zorder=10)

    # légende partagée
    patches = [mpatches.Patch(color=COLORS[c], label=LABELS[c]) for c in [406, 408, 410]]
    fig.legend(handles=patches, loc="lower center", ncol=3, fontsize=9, frameon=False,
               bbox_to_anchor=(0.5, 0.01))

    plt.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Sauvegardé : {out_path}")


def main() -> None:
    print("Chargement FFCO...")
    ffco = load_ffco(ROOT / "grimbosq.gpkg")
    print(f"  406: {len(ffco[406])}  408: {len(ffco[408])}  410: {len(ffco[410])}")

    print("Chargement pipeline...")
    pipeline = load_pipeline(OUTPUT / "vegetation_masked.gpkg")
    print(f"  406: {len(pipeline[406])}  408: {len(pipeline[408])}  410: {len(pipeline[410])}")

    print("Sélection des fenêtres...")
    windows = pick_windows(ffco)
    for name, win in windows:
        print(f"  {name}: {[int(v) for v in win.bounds]}")

    OUTPUT.mkdir(exist_ok=True)
    for win_name, window in windows:
        out = OUTPUT / f"comparaison_{win_name}.png"
        print(f"Génération {win_name}...")
        plot_window(win_name, window, ffco, pipeline, out)

    print("Terminé.")


if __name__ == "__main__":
    main()
