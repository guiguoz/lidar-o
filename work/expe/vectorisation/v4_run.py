"""V4 — Validation OOM (structural controls).

Produit deux fichiers .omap depuis v3_arm_c.gpkg :
  v4_no_template.omap   keep_template=False
  v4_with_template.omap keep_template=True  (fond KP vegetation.png à 50 %)

Contrôles structurels sans OOM :
  1. Validité XML
  2. Comptes d'objets par symbole ISOM
  3. Bbox des coordonnées .omap vs emprise V1
  4. Géoréférencement : ref_point présent et cohérent
  5. Round-trip raster : rasteriser les objets veg sur la grille source V1
  6. Taille des fichiers
  7. Temps d'écriture

Contrôles OOM (ouverture manuelle — répertoriés dans le rapport, non automatisés ici) :
  ouverture sans erreur ; fond géoréférencé ; sélection par classe ;
  présence 406/408/410 ; anneaux intérieurs ; objets hors emprise ;
  éditabilité (déplacer un sommet, annuler) ;
  keep_template=False = vecteurs seuls.
"""
from __future__ import annotations

import pathlib
import sys
import time
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

import logging
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize as rio_rasterize

from src.omap_writer import (
    GeoRef,
    Layer,
    Template,
    TemplateImage,
    load_georef,
    load_template,
    write_omap,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

OUT_DIR      = pathlib.Path(__file__).parent
SOURCE_TIF   = OUT_DIR / "source_classes.tif"
ARM_C_GPKG   = OUT_DIR / "v3_arm_c.gpkg"
TEMPLATE_OOM = ROOT / "assets/ISOM 2017-2_10000.omap"
GEOREF_XML   = ROOT / "assets/georef_grimbosq.xml"
VEG_PNG      = ROOT / "output/vegetation.png"
VEG_PGW      = ROOT / "output/vegetation.pgw"

OUT_NO_TPL   = OUT_DIR / "v4_no_template.omap"
OUT_WITH_TPL = OUT_DIR / "v4_with_template.omap"

ISOM_DN = {406: 85, 408: 170, 410: 255}


# ── Chargement ────────────────────────────────────────────────────────────────

def _veg_layers(gdf: gpd.GeoDataFrame) -> list[Layer]:
    layers = []
    for cls in [406, 408, 410]:
        sub = gdf[gdf["class"] == cls]
        if not sub.empty:
            layers.append(Layer(f"veg_{cls}", cls, list(sub.geometry)))
            log.info("  veg_%d : %d polygones", cls, len(sub))
    return layers


def _vegetation_template(opacity: int = 50) -> TemplateImage:
    pgw_lines = VEG_PGW.read_text(encoding="utf-8").strip().splitlines()
    res_m  = abs(float(pgw_lines[0]))
    cx, cy = float(pgw_lines[4]), float(pgw_lines[5])   # centre pixel haut-gauche
    top_left_x = cx - res_m / 2.0
    top_left_y = cy + res_m / 2.0

    with rasterio.open(VEG_PNG) as ds:
        w_px, h_px = ds.width, ds.height

    return TemplateImage(
        file="vegetation.png",
        top_left_x=top_left_x,
        top_left_y=top_left_y,
        width_px=w_px,
        height_px=h_px,
        res_m=res_m,
        name="KP vegetation (fond)",
        opacity_pct=opacity,
        crs_spec="+init=epsg:2154",
    )


# ── Contrôles structurels ─────────────────────────────────────────────────────

_NS = "http://openorienteering.org/apps/mapper/xml/v2"

def _ctrl_xml_valid(path: pathlib.Path) -> tuple[bool, str]:
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        return True, f"racine <{root.tag.split('}')[-1]}>"
    except ET.ParseError as e:
        return False, str(e)


def _ctrl_object_counts(path: pathlib.Path, template: Template) -> dict[str, int]:
    tree = ET.parse(str(path))
    root = tree.getroot()
    id_to_code = {str(v): k for k, v in template.code_to_id.items()}
    counts: dict[str, int] = {}
    # Seul le bloc <objects> contient les objets de carte — les <object> enfants
    # de <element> dans les définitions de symboles ne sont PAS des objets de carte.
    objects_elem = root.find(f".//{{{_NS}}}objects")
    if objects_elem is None:
        return counts
    for obj in objects_elem:
        if obj.tag != f"{{{_NS}}}object":
            continue
        sym_id = obj.get("symbol", "?")
        code   = id_to_code.get(sym_id, f"sym_{sym_id}")
        counts[str(code)] = counts.get(str(code), 0) + 1
    return counts


def _parse_coords_text(text: str) -> list[tuple[int, int]]:
    """Parse OOM coords : 'ox oy;ox oy flag;...' → [(ox, oy), …].

    Chaque entrée = 'ox oy' ou 'ox oy flag' séparée par des ';'.
    Le flag (2=close ext, 18=close int) est ignoré pour le calcul de coordonnées.
    """
    pts: list[tuple[int, int]] = []
    for entry in text.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split()
        if len(parts) >= 2:
            try:
                pts.append((int(parts[0]), int(parts[1])))
            except ValueError:
                pass
    return pts


def _parse_coords_with_flags(text: str) -> list[tuple[int, int, int | None]]:
    """Parse OOM coords incluant les flags (pour reconstruction de polygones)."""
    pts: list[tuple[int, int, int | None]] = []
    for entry in text.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split()
        if len(parts) >= 2:
            try:
                flag = int(parts[2]) if len(parts) > 2 else None
                pts.append((int(parts[0]), int(parts[1]), flag))
            except ValueError:
                pass
    return pts


def _ctrl_bbox_omap(path: pathlib.Path, georef: GeoRef) -> tuple[float, float, float, float]:
    """Décode les coordonnées .omap → bbox L93 (objets végétation uniquement)."""
    tree = ET.parse(str(path))
    root = tree.getroot()
    upm = 1_000_000 / georef.scale
    xs2, ys2 = [], []
    # Seuls les <coords> directs des <object> (pas les <coord> dans <pattern>)
    for obj in root.iter(f"{{{_NS}}}object"):
        coords_elem = obj.find(f"{{{_NS}}}coords")
        if coords_elem is None or not coords_elem.text:
            continue
        for ox, oy in _parse_coords_text(coords_elem.text):
            xs2.append(georef.ref_x + ox / upm)
            ys2.append(georef.ref_y - oy / upm)
    if not xs2:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs2), min(ys2), max(xs2), max(ys2))


def _ctrl_roundtrip(path: pathlib.Path, georef: GeoRef, template: Template) -> dict[str, int]:
    """Rasterise les objets veg du .omap sur la grille source V1, compare."""
    id_to_code = {str(v): k for k, v in template.code_to_id.items()}

    tree = ET.parse(str(path))
    root = tree.getroot()
    upm = 1_000_000 / georef.scale

    with rasterio.open(SOURCE_TIF) as ds:
        src = ds.read(1).copy()
        xform = ds.transform
        h, w  = ds.height, ds.width

    # Reconstruire les polygones depuis les coords XML
    from shapely.geometry import Polygon
    shapes_all: list[tuple] = []

    for obj in root.iter(f"{{{_NS}}}object"):
        sym_id = obj.get("symbol", "?")
        code   = id_to_code.get(sym_id)
        if code not in ISOM_DN:
            continue
        dn = ISOM_DN[code]
        coords_elem = obj.find(f"{{{_NS}}}coords")
        if coords_elem is None or not coords_elem.text:
            continue
        parsed = _parse_coords_with_flags(coords_elem.text)
        # Reconstruit les anneaux : flag=2 ferme l'extérieur, flag=18 ferme un trou
        exterior: list[tuple[float, float]] = []
        interiors: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for ox, oy, flag in parsed:
            x = georef.ref_x + ox / upm
            y = georef.ref_y - oy / upm
            current.append((x, y))
            if flag == 2:
                exterior = current[:]
                current = []
            elif flag == 18:
                interiors.append(current[:])
                current = []
        if not exterior and current:
            exterior = current
        if len(exterior) >= 3:
            try:
                import shapely as _shp
                geom = Polygon(exterior, interiors)
                if not geom.is_valid:
                    geom = _shp.make_valid(geom)
                if geom.is_valid and geom.area > 0:
                    shapes_all.append((geom.__geo_interface__, dn))
            except Exception:
                pass

    if not shapes_all:
        return {"error": "no_shapes_decoded"}

    rt = rio_rasterize(
        shapes_all, out_shape=(h, w), transform=xform, fill=0, dtype=np.uint8,
        merge_alg=rasterio.enums.MergeAlg.replace,
    )

    result: dict[str, int] = {}
    for isom, dn in ISOM_DN.items():
        m_s = src == dn
        m_r = rt  == dn
        identical = int((m_s & m_r).sum())
        lost  = int((m_s & ~m_r).sum())
        added = int((~m_s & m_r).sum())
        result[str(isom)] = {"identical": identical, "lost": lost, "added": added}
    return result


def _run_controls(
    path: pathlib.Path, template: Template, georef: GeoRef,
    source_bbox: tuple[float, float, float, float],
) -> dict:
    log.info("Contrôles → %s", path.name)
    out: dict = {}

    # 1. XML
    ok, msg = _ctrl_xml_valid(path)
    out["xml_valid"] = {"ok": ok, "msg": msg}
    log.info("  1. XML valide : %s — %s", ok, msg)

    # 2. Comptes
    counts = _ctrl_object_counts(path, template)
    out["object_counts"] = counts
    log.info("  2. Objets : %s", counts)

    # 3. Bbox
    bbox = _ctrl_bbox_omap(path, georef)
    src_xmin, src_ymin, src_xmax, src_ymax = source_bbox
    ok_bbox = (bbox[0] >= src_xmin - 10 and bbox[2] <= src_xmax + 10
               and bbox[1] >= src_ymin - 10 and bbox[3] <= src_ymax + 10)
    out["bbox"] = {"omap": list(bbox), "source": list(source_bbox), "in_range": ok_bbox}
    log.info("  3. Bbox : %s → %s", bbox, "OK" if ok_bbox else "HORS EMPRISE")

    # 4. Taille fichier
    size_kb = os.path.getsize(path) / 1024
    out["file_size_kb"] = round(size_kb, 1)
    log.info("  4. Taille : %.1f KB", size_kb)

    # 5. Round-trip
    rt = _ctrl_roundtrip(path, georef, template)
    out["roundtrip"] = rt
    for cls, vals in rt.items():
        if isinstance(vals, dict):
            log.info("  5. RT %s : identiques=%d perdu=%d ajouté=%d",
                     cls, vals["identical"], vals["lost"], vals["added"])

    return out


# ── Rapport ───────────────────────────────────────────────────────────────────

def write_report(
    results: dict[str, dict],
    timings: dict[str, float],
    out_path: pathlib.Path,
) -> None:
    lines = [
        "# V4 — Contrôles structurels .omap (Grimbosq)",
        "",
        f"Input : v3_arm_c.gpkg — coverage_simplify 2 m, {ARM_C_GPKG.stat().st_size // 1024} KB",
        "",
    ]

    for variant, ctrl in results.items():
        omap_name = f"v4_{variant}.omap"
        counts = ctrl.get('object_counts', {})
        total_map_objects = sum(v for v in counts.values() if isinstance(v, int))
        lines += [
            f"## {variant} ({omap_name}, {ctrl.get('file_size_kb','?')} KB, "
            f"écriture {timings.get(variant, 0):.1f} s)",
            "",
            f"1. XML valide : **{ctrl['xml_valid']['ok']}** — {ctrl['xml_valid']['msg']}",
            f"2. Objets par ISOM : {counts}  (total objets de carte : {total_map_objects})",
            f"   *Note : le compteur ne lit que le bloc `<objects>` du .omap ; les `<object>`",
            f"   graphiques à l'intérieur des définitions de symboles (enfants `<element>`)",
            f"   ne sont pas des objets de carte et ne sont pas comptés ici.*",
            f"3. Bbox .omap : {ctrl.get('bbox', {}).get('omap')} → "
            f"{'dans emprise' if ctrl.get('bbox',{}).get('in_range') else 'HORS EMPRISE'}",
            f"4. Taille fichier : {ctrl.get('file_size_kb','?')} KB",
            "",
        ]
        rt = ctrl.get("roundtrip", {})
        if rt and "error" not in rt:
            lines += [
                "5. Round-trip raster (grille V1) :",
                "",
                "| ISOM | Identiques | Perdus | Ajoutés |",
                "|-----:|-----------:|-------:|--------:|",
            ]
            for cls in ["406", "408", "410"]:
                v = rt.get(cls, {})
                if isinstance(v, dict):
                    lines.append(f"| {cls} | {v['identical']} | {v['lost']} | {v['added']} |")
        lines.append("")

    # Tableau de validation unifié §V4.5
    def _r(cond: bool | None) -> str:
        if cond is None:
            return "N/A"
        return "**PASS**" if cond else "**FAIL**"

    rt_no  = results.get("no_template",   {}).get("roundtrip", {})
    rt_wit = results.get("with_template", {}).get("roundtrip", {})
    cnts_no  = results.get("no_template",   {}).get("object_counts", {})
    cnts_wit = results.get("with_template", {}).get("object_counts", {})

    def _rt_ok(rt: dict) -> bool:
        if "error" in rt:
            return False
        expected = {"406": (12081, 11152), "408": (3918, 3643), "410": (105, 110)}
        for cls, (exp_lost, exp_added) in expected.items():
            v = rt.get(cls, {})
            if not isinstance(v, dict):
                return False
            if v.get("lost") != exp_lost or v.get("added") != exp_added:
                return False
        return True

    _no_bbox = results.get("no_template",  {}).get("bbox", {})
    _wt_bbox = results.get("with_template",{}).get("bbox", {})

    lines += [
        "---",
        "",
        "## V4.5 — Tableau de validation unifié",
        "",
        "| Contrôle | sans template | avec template (50 %) |",
        "|----------|:-------------:|:--------------------:|",
        f"| XML valide | {_r(results.get('no_template',{}).get('xml_valid',{}).get('ok'))} "
        f"| {_r(results.get('with_template',{}).get('xml_valid',{}).get('ok'))} |",
        f"| ISOM 406 = 1340 | {_r(cnts_no.get('406') == 1340)} | {_r(cnts_wit.get('406') == 1340)} |",
        f"| ISOM 408 = 409  | {_r(cnts_no.get('408') == 409)}  | {_r(cnts_wit.get('408') == 409)}  |",
        f"| ISOM 410 = 18   | {_r(cnts_no.get('410') == 18)}   | {_r(cnts_wit.get('410') == 18)}   |",
        f"| Objets parasites (sym_?) | {_r(len(cnts_no) == 3)} | {_r(len(cnts_wit) == 3)} |",
        f"| Bbox dans emprise V1 | {_r(_no_bbox.get('in_range'))} | {_r(_wt_bbox.get('in_range'))} |",
        f"| Round-trip = coût bras C | {_r(_rt_ok(rt_no))} | {_r(_rt_ok(rt_wit))} |",
        "| OOM ouvre sans erreur | ? | ? |",
        "| Géoréférencement sur fond | N/A | ? |",
        "| Sélection objets par classe | ? | ? |",
        "| Anneaux intérieurs visibles | ? | ? |",
        "| Objets hors emprise : 0 | ? | ? |",
        "| Modification d'un sommet | ? | ? |",
        "| Sauvegarde + réouverture | ? | ? |",
        "| Vecteurs seuls exploitables (R1) | ? | N/A |",
        "| Rendu décalque correct (R2) | N/A | ? |",
        "",
        "> Remplir les `?` lors de l'ouverture OOM.",
        "",
        "---",
        "",
        "## V4.6 — Planche de vérification",
        "",
        "Planche 3 panneaux (1:10 000) : [v4_plate.png](v4_plate.png)",
        "",
        "A — KP vegetation.png · B — OMAP vecteurs seuls · C — OMAP vecteurs + fond 50 %",
        "",
        "---",
        "",
        "⛔ STOP — verdict V4 = commit après ouverture OOM.",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Rapport V4 → %s", out_path.name)


# ── Planche V4.6 ─────────────────────────────────────────────────────────────

ISOM_COLORS: dict[int, str] = {
    406: "#c7e9b4",   # vert clair
    408: "#41b6c4",   # cyan-vert
    410: "#225ea8",   # bleu foncé
}


def _downsample(arr: np.ndarray, factor: int) -> np.ndarray:
    if arr.ndim == 2:
        return arr[::factor, ::factor]
    return arr[::factor, ::factor, :]


def v4_6_plate(
    gdf: gpd.GeoDataFrame,
    out_dir: pathlib.Path,
) -> pathlib.Path:
    """Planche 3 panneaux V4.6 à 1:10 000.

    A — KP vegetation.png original
    B — Vecteurs arm C seuls (fond blanc)
    C — Vecteurs arm C + fond KP (opacité 50 %)
    """
    out_png = out_dir / "v4_plate.png"

    with rasterio.open(VEG_PNG) as ds:
        rgb_raw = ds.read()
        kp_rgb  = np.moveaxis(rgb_raw[:3], 0, -1).copy()
        b = ds.bounds
        bbox = (b.left, b.bottom, b.right, b.top)

    bxmin, bymin, bxmax, bymax = bbox
    extent_mpl = [bxmin, bxmax, bymin, bymax]

    FACTOR = 4
    kp_small = _downsample(kp_rgb, FACTOR)

    dpi = 100
    # 3 panneaux côte à côte — largeur ≈ 3 × 5 in + marges = ~17 in, hauteur ~10 in
    fig, (ax_a, ax_b, ax_c) = plt.subplots(1, 3, figsize=(17.0, 10.0), dpi=dpi)

    # — A : KP vegetation.png —
    ax_a.imshow(kp_small, extent=extent_mpl, origin="upper", interpolation="bilinear")
    ax_a.set_title("A — KP vegetation.png", fontsize=8)

    # — B : vecteurs seuls —
    ax_b.set_facecolor("white")
    ax_b.set_xlim(bxmin, bxmax)
    ax_b.set_ylim(bymin, bymax)
    for cls, color in ISOM_COLORS.items():
        sub = gdf[gdf["class"] == cls]
        if not sub.empty:
            sub.plot(ax=ax_b, color=color, edgecolor="none")
    patches_b = [mpatches.Patch(color=c, label=f"ISOM {k}") for k, c in ISOM_COLORS.items()]
    ax_b.legend(handles=patches_b, fontsize=6, loc="lower left")
    ax_b.set_title("B — OMAP vecteurs seuls", fontsize=8)

    # — C : vecteurs + KP 50 % —
    ax_c.imshow(kp_small, extent=extent_mpl, origin="upper", alpha=0.5, interpolation="bilinear")
    ax_c.set_xlim(bxmin, bxmax)
    ax_c.set_ylim(bymin, bymax)
    for cls, color in ISOM_COLORS.items():
        sub = gdf[gdf["class"] == cls]
        if not sub.empty:
            sub.plot(ax=ax_c, color=color, edgecolor="none", alpha=0.85)
    ax_c.set_title("C — OMAP vecteurs + fond KP (50 %)", fontsize=8)

    for ax in (ax_a, ax_b, ax_c):
        ax.set_aspect("equal")
        ax.tick_params(labelsize=5)
        ax.set_xlabel("X Lambert93 (m)", fontsize=5)
        ax.set_ylabel("Y Lambert93 (m)", fontsize=5)

    fig.suptitle(
        "Grimbosq — V4.6 Vérification OMAP vecteurs végétation (1:10 000, arm C coverage_simplify 2 m)",
        fontsize=8,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    log.info("V4.6 planche → %s", out_png)
    return out_png


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=== V4 validation OOM ===")

    gdf = gpd.read_file(ARM_C_GPKG)
    log.info("v3_arm_c.gpkg : %d polygones chargés", len(gdf))

    template = load_template(TEMPLATE_PATH := TEMPLATE_OOM)
    georef   = load_georef(GEOREF_XML)
    layers   = _veg_layers(gdf)

    with rasterio.open(SOURCE_TIF) as ds:
        b = ds.bounds
        source_bbox = (b.left, b.bottom, b.right, b.top)

    timings: dict[str, float] = {}
    results: dict[str, dict] = {}

    # — v4_no_template.omap —
    log.info("Écriture v4_no_template.omap")
    t0 = time.perf_counter()
    write_omap(OUT_NO_TPL, template, layers, georef, image_templates=None)
    timings["no_template"] = time.perf_counter() - t0
    log.info("  Écrit en %.2f s", timings["no_template"])
    results["no_template"] = _run_controls(OUT_NO_TPL, template, georef, source_bbox)

    # — v4_with_template.omap —
    log.info("Écriture v4_with_template.omap")
    img_tpl = _vegetation_template(opacity=50)
    t0 = time.perf_counter()
    write_omap(OUT_WITH_TPL, template, layers, georef,
               image_templates=[img_tpl])
    timings["with_template"] = time.perf_counter() - t0
    log.info("  Écrit en %.2f s", timings["with_template"])
    results["with_template"] = _run_controls(OUT_WITH_TPL, template, georef, source_bbox)

    write_report(results, timings, OUT_DIR / "v4_report.md")

    # V4.6 — planche de vérification
    log.info("V4.6 — génération planche")
    v4_6_plate(gdf, OUT_DIR)

    log.info("=== V4 terminé ===")


if __name__ == "__main__":
    main()
