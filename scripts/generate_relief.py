"""Phase 7 — Génère grimbosq_relief.omap depuis les DXF Karttapullautin.

Lit les DXF dans out_kp/ (mode batch, 6 dalles Grimbosq),
applique le mapping scripts/mappings/kp_relief.yaml,
et produit output/grimbosq_relief.omap.

Usage :
    python scripts/generate_relief.py

Prérequis :
    - assets/ISOM 2017-2_10000.omap  (gabarit ISOM)
    - assets/georef_grimbosq.xml     (géoréférencement Lambert 93)
    - out_kp/*_contours.dxf, *_dotknolls.dxf, *_formlines.dxf, ...  (sortie batch KP)
    - pip install ezdxf pyyaml       (dépendances)
"""
from __future__ import annotations

import collections
import logging
import pathlib
import sys

import ezdxf
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.omap_writer import LineLayer, PointLayer, load_georef, load_template, write_omap

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = pathlib.Path(".")
OUT_KP = ROOT / "out_kp"
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
MAPPING_PATH = ROOT / "scripts" / "mappings" / "kp_relief.yaml"
TEMPLATE_PATH = ASSETS / "ISOM 2017-2_10000.omap"
GEOREF_PATH = ASSETS / "georef_grimbosq.xml"
OUTPUT_PATH = OUTPUT / "grimbosq_relief.omap"


def load_relief_mapping(path: pathlib.Path) -> tuple[dict[str, int], set[str]]:
    """Charge le mapping calque→code et la liste de skip depuis le YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mapping: dict[str, int] = {k: int(v) for k, v in raw["mapping"].items()}
    skip: set[str] = set(str(s) for s in raw.get("skip", []))
    return mapping, skip


def _normalize_vertices(
    vertices: list[tuple[float, float]],
    dxf_closed: bool,
) -> tuple[list[tuple[float, float]], bool]:
    """Normalise une liste de sommets DXF pour la conversion omap.

    KP exporte les polylignes fermées en répétant le premier sommet en fin de
    liste plutôt qu'en posant le flag DXF CLOSED. Cette fonction détecte les
    deux formes (flag DXF ou premier==dernier sommet) et retourne toujours
    (sommets_sans_doublon, is_closed).
    """
    if len(vertices) >= 3 and vertices[0] == vertices[-1]:
        return vertices[:-1], True
    return vertices, dxf_closed


def read_dxf(
    dxf_path: pathlib.Path,
    mapping: dict[str, int],
    skip: set[str],
) -> tuple[
    dict[int, list[tuple[list[tuple[float, float]], bool]]],
    dict[int, list[tuple[float, float]]],
]:
    """Lit un DXF et retourne (line_segs_by_isom, points_by_isom).

    Calques dans skip → ignorés silencieusement.
    Calques absents de mapping ET skip → ValueError explicite.
    """
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    line_segs: dict[int, list] = collections.defaultdict(list)
    pts: dict[int, list] = collections.defaultdict(list)
    unknown: set[str] = set()

    for entity in msp:
        layer = entity.dxf.layer
        if layer in skip:
            continue
        if layer not in mapping:
            unknown.add(layer)
            continue

        code = mapping[layer]
        etype = entity.dxftype()

        if etype == "POLYLINE":
            vertices = [
                (v.dxf.location.x, v.dxf.location.y)
                for v in entity.vertices
            ]
            vertices, is_closed = _normalize_vertices(vertices, entity.is_closed)
            if len(vertices) >= 2:
                line_segs[code].append((vertices, is_closed))
            else:
                log.warning(
                    "%s : calque %s — POLYLINE avec %d sommet(s) ignorée",
                    dxf_path.name, layer, len(vertices),
                )

        elif etype == "LWPOLYLINE":
            raw_pts = list(entity.get_points())
            vertices = [(p[0], p[1]) for p in raw_pts]
            vertices, is_closed = _normalize_vertices(vertices, entity.closed)
            if len(vertices) >= 2:
                line_segs[code].append((vertices, is_closed))
            else:
                log.warning(
                    "%s : calque %s — LWPOLYLINE avec %d sommet(s) ignorée",
                    dxf_path.name, layer, len(vertices),
                )

        elif etype == "POINT":
            x, y = entity.dxf.location.x, entity.dxf.location.y
            pts[code].append((x, y))

        else:
            log.debug("%s : type d'entité inattendu %s sur calque %s", dxf_path.name, etype, layer)

    if unknown:
        raise ValueError(
            f"{dxf_path.name} : calques inconnus (absents du mapping ET du skip) : "
            f"{sorted(unknown)}"
        )

    return dict(line_segs), dict(pts)


def collect_dxf_files(out_kp: pathlib.Path) -> list[pathlib.Path]:
    """Collecte tous les DXF du répertoire batch, triés pour un output stable."""
    dxf_files = sorted(out_kp.glob("*.dxf"))
    if not dxf_files:
        raise FileNotFoundError(f"Aucun DXF trouvé dans {out_kp}")
    return dxf_files


def _seg_overlaps_bbox(
    vertices: list[tuple[float, float]],
    bbox: tuple[float, float, float, float],
) -> bool:
    """True si le segment chevauche (même partiellement) la bbox (x1,y1,x2,y2)."""
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    x1, y1, x2, y2 = bbox
    return max(xs) >= x1 and min(xs) <= x2 and max(ys) >= y1 and min(ys) <= y2


def build_relief_layers(
    out_kp: pathlib.Path,
    mapping: dict[str, int],
    skip: set[str],
    bbox: tuple[float, float, float, float] | None = None,
) -> list[LineLayer | PointLayer]:
    """Lit les DXF KP → liste de LineLayer / PointLayer.

    Si bbox (x1,y1,x2,y2) est fournie, les géométries hors emprise sont rejetées.
    Un WARNING est émis si AUCUNE géométrie ne passe le filtre (terrain mismatch probable).
    """
    dxf_files = collect_dxf_files(out_kp)
    log.info("%d fichiers DXF trouvés dans %s", len(dxf_files), out_kp)

    all_lines: dict[int, list] = collections.defaultdict(list)
    all_points: dict[int, list] = collections.defaultdict(list)

    for dxf_path in dxf_files:
        log.info("Lecture %s …", dxf_path.name)
        segs, pts = read_dxf(dxf_path, mapping, skip)
        for code, entries in segs.items():
            all_lines[code].extend(entries)
            log.info("  %s : %d lignes ISOM %s", dxf_path.name, len(entries), code)
        for code, points in pts.items():
            all_points[code].extend(points)
            log.info("  %s : %d points ISOM %s", dxf_path.name, len(points), code)

    if bbox is not None:
        n_lines_in = sum(len(v) for v in all_lines.values())
        n_pts_in = sum(len(v) for v in all_points.values())

        all_lines = {
            code: [seg for seg in segs if _seg_overlaps_bbox(seg[0], bbox)]
            for code, segs in all_lines.items()
        }
        all_points = {
            code: [
                pt for pt in pts
                if bbox[0] <= pt[0] <= bbox[2] and bbox[1] <= pt[1] <= bbox[3]
            ]
            for code, pts in all_points.items()
        }

        n_lines_out = sum(len(v) for v in all_lines.values())
        n_pts_out = sum(len(v) for v in all_points.values())
        n_in = n_lines_in + n_pts_in
        n_out = n_lines_out + n_pts_out

        if n_in > 0 and n_out == 0:
            log.warning(
                "GARDE-FOU relief : 0/%d géométries dans l'emprise — "
                "DXF probablement issus d'un autre terrain. Relief ignoré.",
                n_in,
            )
        elif n_in > n_out:
            log.info(
                "Clip relief : %d/%d géométries dans l'emprise (%d rejetées hors bbox)",
                n_out, n_in, n_in - n_out,
            )

    layers: list[LineLayer | PointLayer] = []
    for code in sorted(all_lines):
        if all_lines[code]:
            layers.append(LineLayer(f"line_{code}", code, all_lines[code]))
    for code in sorted(all_points):
        if all_points[code]:
            layers.append(PointLayer(f"point_{code}", code, all_points[code]))
    return layers


def main() -> None:
    import argparse as _argparse
    parser = _argparse.ArgumentParser(description="DXF Karttapullautin -> .omap ISOM relief")
    parser.add_argument("terrain", nargs="?", default="grimbosq", help="Nom du terrain (ex: port_en_bessin)")
    args = parser.parse_args()

    import yaml as _yaml
    _cfg = _yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    _tcfg = _cfg.get("terrains", {}).get(args.terrain, {})
    _out_dir_name = _tcfg.get("output_dir") or (
        f"output_{args.terrain}" if args.terrain != "grimbosq" else "output"
    )
    output = ROOT / _out_dir_name

    kp_folder = ROOT / f"out_kp_{args.terrain}" if args.terrain != "grimbosq" else OUT_KP
    if not kp_folder.exists():
        kp_folder = OUT_KP
        log.warning("out_kp_%s/ absent — utilisation de out_kp/", args.terrain)

    georef_path = ASSETS / f"georef_{args.terrain}.xml"
    if not georef_path.exists():
        georef_path = GEOREF_PATH
        log.warning("georef_%s.xml absent — utilisation de georef_grimbosq.xml", args.terrain)

    for p in [MAPPING_PATH, TEMPLATE_PATH, georef_path]:
        if not p.exists():
            sys.exit(f"ABSENT : {p}")
    if not kp_folder.exists():
        sys.exit(f"ABSENT : {kp_folder} — lancer KP en mode batch d'abord")

    mapping, skip = load_relief_mapping(MAPPING_PATH)
    log.info("Mapping : %d calques, %d en skip", len(mapping), len(skip))

    template = load_template(TEMPLATE_PATH)
    georef = load_georef(georef_path)

    layers = build_relief_layers(kp_folder, mapping, skip)

    total_lines = sum(len(l.segments) for l in layers if isinstance(l, LineLayer))
    total_pts = sum(len(l.points) for l in layers if isinstance(l, PointLayer))
    log.info("Total : %d lignes + %d points = %d objets", total_lines, total_pts, total_lines + total_pts)

    output.mkdir(parents=True, exist_ok=True)
    out_path = output / f"{args.terrain}_relief.omap"
    write_omap(out_path, template, layers, georef)
    log.info("Ecrit : %s", out_path)


if __name__ == "__main__":
    main()
