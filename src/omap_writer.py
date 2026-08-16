"""Phase 7 — Génère des fichiers .omap (XML OpenOrienteering Mapper).

Stratégie gabarit + injection : les blocs <colors> et <symbols> sont recopiés
verbatim depuis assets/ISOM_2017-2_10000.omap ; seuls <georeferencing> et le
contenu de <objects> sont remplacés.

Trois familles d'objets supportées :
    Layer      — surfaces (polygones Shapely) ; ex. végétation 406/408/410
    LineLayer  — lignes (polylignes DXF) ; ex. courbes de niveau 101/102/103
    PointLayer — points ; ex. buttes 109, petites dépressions 111

Usage :
    from src.omap_writer import load_template, load_georef, write_omap
    from src.omap_writer import Layer, LineLayer, PointLayer
    template = load_template("assets/ISOM_2017-2_10000.omap")
    georef   = load_georef("assets/georef_grimbosq.xml")
    # Végétation (surfaces)
    layers   = [Layer("veg_406", 406, list(gdf_406.geometry))]
    # Courbes de niveau (lignes)
    lines    = [LineLayer("contours", 101, [(vertices_list, False)])]
    # Buttes (points)
    pts      = [PointLayer("buttes", 109, [(x, y)])]
    write_omap("output/grimbosq.omap", template, layers + lines + pts, georef)
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, NamedTuple, Sequence

import shapely.geometry as sg
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

log = logging.getLogger(__name__)

_NS = "http://openorienteering.org/apps/mapper/xml/v2"
_NSB = f"{{{_NS}}}"


# ── Types publics ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GeoRef:
    """Géoréférencement Lambert 93 pour conversion de coordonnées et injection XML."""
    scale: int
    ref_x: float
    ref_y: float
    xml_block: str   # bloc <georeferencing>...</georeferencing> brut à injecter


@dataclass(frozen=True)
class Template:
    """Gabarit .omap parsé — symboles ISOM chargés, XML source conservé."""
    code_to_id: dict[int, int]   # code ISOM (int) → id interne du symbole
    source_xml: str              # XML brut du gabarit (pour injection)


class Layer(NamedTuple):
    """Couche vectorielle à injecter dans le .omap. Géométries en EPSG:2154."""
    name: str
    isom_code: int
    geometries: Sequence[BaseGeometry]


class LineLayer(NamedTuple):
    """Couche de lignes (polylignes) à injecter dans le .omap. Coordonnées en EPSG:2154."""
    name: str
    isom_code: int
    # Liste de (sommets, is_closed) — sommets = [(x, y), …], is_closed = True si
    # la ligne se ferme (dépression, butte en courbe) ; flag 2 sur le dernier point.
    segments: Sequence[tuple[Sequence[tuple[float, float]], bool]]


class PointLayer(NamedTuple):
    """Couche de symboles ponctuels à injecter dans le .omap. Coordonnées en EPSG:2154."""
    name: str
    isom_code: int
    points: Sequence[tuple[float, float]]


# ── Chargement ────────────────────────────────────────────────────────────────

def load_template(path: str | Path) -> Template:
    """Parse le gabarit ISOM et extrait le mapping code ISOM → id interne.

    Échoue explicitement si le fichier n'est pas du XML valide ou si le bloc
    <symbols> est absent.
    """
    source_xml = Path(path).read_text(encoding="utf-8")
    root = ET.fromstring(source_xml)

    code_to_id: dict[int, int] = {}
    for sym in root.iter(f"{_NSB}symbol"):
        raw_code = sym.get("code")
        raw_id = sym.get("id")
        # Exclure les variantes décimales (ex. "406.1", "406.2") — seuls les codes
        # entiers ("406") correspondent aux symboles de base ISOM attendus.
        # int(float(...)) réduirait toutes les variantes au même entier et garderait
        # la dernière écrite, ce qui produirait un id de variante au lieu du symbole de base.
        if raw_code is not None and raw_id is not None and "." not in raw_code:
            try:
                code_to_id[int(raw_code)] = int(raw_id)
            except ValueError:
                pass

    return Template(code_to_id=code_to_id, source_xml=source_xml)


def load_georef(path: str | Path) -> GeoRef:
    """Extrait le bloc <georeferencing> d'un fichier .omap ou d'un .xml autonome.

    Supporte deux formes :
    - fichier .omap complet : extrait le bloc <georeferencing> par regex
    - fichier .xml ne contenant que le bloc (ex. assets/georef_grimbosq.xml)

    Dans les deux cas, analyse le bloc extrait directement (sans namespace
    parent) pour récupérer scale et ref_point.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"(<georeferencing\b.*?</georeferencing>)", text, re.DOTALL)
    if not m:
        raise ValueError(f"Bloc <georeferencing> absent dans {path}")
    xml_block = m.group(1)

    # Parse le bloc extrait directement — le xmlns est sur la racine parente
    # dans un .omap, donc le bloc extrait n'a pas de préfixe de namespace.
    geo = ET.fromstring(xml_block)
    scale = int(geo.get("scale", 10000))
    ref = geo.find(".//ref_point")
    if ref is None:
        raise ValueError(f"<ref_point> absent dans <georeferencing> de {path}")
    ref_x = float(ref.get("x", 0))
    ref_y = float(ref.get("y", 0))
    return GeoRef(scale=scale, ref_x=ref_x, ref_y=ref_y, xml_block=xml_block)


# ── Conversion de coordonnées ─────────────────────────────────────────────────

def _to_omap(x: float, y: float, georef: GeoRef) -> tuple[int, int]:
    """Convertit L93 (m) → unités omap (1/1000 mm carte, Y inversé).

    x_omap = round((X_L93 - ref_x) * 1_000_000 / scale)
    y_omap = round(-(Y_L93 - ref_y) * 1_000_000 / scale)
    """
    upm = 1_000_000 / georef.scale
    return round((x - georef.ref_x) * upm), round(-(y - georef.ref_y) * upm)


def _from_omap(ox: int, oy: int, georef: GeoRef) -> tuple[float, float]:
    """Inverse de _to_omap — utilisé dans les tests aller-retour."""
    upm = 1_000_000 / georef.scale
    return georef.ref_x + ox / upm, georef.ref_y - oy / upm


# ── Sérialisation des géométries ──────────────────────────────────────────────

def _ring_to_parts(
    coords: list[tuple[float, float]], close_flag: int, georef: GeoRef
) -> list[str]:
    """Sérialise un anneau Shapely (fermé) en liste de chaînes 'x y [flag]'.

    close_flag : 2 pour anneau extérieur, 18 pour anneau intérieur (trou).
    Shapely répète le premier point en fin d'anneau ; on compte les points
    distincts avant de valider le minimum de 3.
    """
    # coords[:-1] = points sans le doublon de fermeture (Shapely peut inclure Z)
    xy_only = [(c[0], c[1]) for c in coords]
    distinct = list(dict.fromkeys(xy_only[:-1]))
    if len(distinct) < 3:
        raise ValueError(
            f"Anneau avec {len(distinct)} point(s) distinct(s) — minimum 3 requis"
        )
    parts: list[str] = []
    for i, (x, y) in enumerate(xy_only):
        ox, oy = _to_omap(x, y, georef)
        if i == len(xy_only) - 1:
            parts.append(f"{ox} {oy} {close_flag}")
        else:
            parts.append(f"{ox} {oy}")
    return parts


def _polygon_to_xml(poly: sg.Polygon, symbol_id: int, georef: GeoRef) -> str:
    """Sérialise un polygone Shapely en élément XML <object> de type surface."""
    if not poly.is_valid:
        fixed = make_valid(poly)
        if not isinstance(fixed, sg.Polygon):
            raise ValueError(
                f"make_valid a produit un {type(fixed).__name__} au lieu d'un Polygon"
            )
        log.warning("Géométrie invalide corrigée via make_valid")
        poly = fixed

    parts: list[str] = []
    parts.extend(_ring_to_parts(list(poly.exterior.coords), 2, georef))
    for hole in poly.interiors:
        parts.extend(_ring_to_parts(list(hole.coords), 18, georef))

    count = len(parts)
    coords_str = ";".join(parts) + ";"
    return (
        f'<object type="1" symbol="{symbol_id}">'
        f'<coords count="{count}">{coords_str}</coords>'
        f'<pattern rotation="0"><coord x="0" y="0"/></pattern>'
        f'</object>'
    )


def _iter_polygons(geom: BaseGeometry) -> Iterator[sg.Polygon]:
    """Itère les Polygon individuels d'une géométrie quelconque."""
    if isinstance(geom, sg.Polygon):
        yield geom
    elif isinstance(geom, (sg.MultiPolygon, sg.GeometryCollection)):
        for g in geom.geoms:
            if isinstance(g, sg.Polygon):
                yield g


def _line_to_xml(
    vertices: Sequence[tuple[float, float]],
    is_closed: bool,
    symbol_id: int,
    georef: GeoRef,
) -> str:
    """Sérialise une polyligne en élément XML <object type="1"> (ligne).

    Lignes ouvertes  : aucun flag sur le dernier point.
    Lignes fermées   : flag 2 sur le dernier point (même convention que l'anneau
                       extérieur d'un polygone).

    Minimum 2 sommets requis.
    """
    if len(vertices) < 2:
        raise ValueError(
            f"Polyligne avec {len(vertices)} sommet(s) — minimum 2 requis"
        )
    parts: list[str] = []
    for x, y in vertices:
        ox, oy = _to_omap(x, y, georef)
        parts.append(f"{ox} {oy}")
    if is_closed:
        parts[-1] += " 2"
    count = len(parts)
    coords_str = ";".join(parts) + ";"
    return (
        f'<object type="1" symbol="{symbol_id}">'
        f'<coords count="{count}">{coords_str}</coords>'
        f'</object>'
    )


def _point_to_xml(x: float, y: float, symbol_id: int, georef: GeoRef) -> str:
    """Sérialise un point en élément XML <object type="0">."""
    ox, oy = _to_omap(x, y, georef)
    return (
        f'<object type="0" symbol="{symbol_id}">'
        f'<coords count="1">{ox} {oy};</coords>'
        f'</object>'
    )


# ── Injection XML ─────────────────────────────────────────────────────────────

def _replace_block(xml: str, tag: str, replacement: str) -> str:
    """Remplace le premier bloc <tag …>…</tag> (ou autofermant) par replacement.

    Lève ValueError si le bloc est absent — pas d'injection silencieuse.
    """
    pattern = rf"<{tag}\b[^>]*>.*?</{tag}>|<{tag}\b[^>]*/>"
    result, n = re.subn(pattern, replacement, xml, count=1, flags=re.DOTALL)
    if n == 0:
        raise ValueError(f"Bloc <{tag}> introuvable dans le gabarit")
    return result


def _replace_objects(xml: str, inner: str, count: int) -> str:
    """Remplace <objects …>…</objects> (ou autofermant) et met à jour count.

    Lève ValueError si le bloc est absent ou s'il en existe plusieurs
    (plusieurs <parts> non supportés : cible ambiguë).
    """
    n_blocks = len(re.findall(r"<objects\b", xml))
    if n_blocks == 0:
        raise ValueError("Bloc <objects> introuvable dans le gabarit")
    if n_blocks > 1:
        raise ValueError(
            f"Le gabarit contient {n_blocks} blocs <objects> — "
            "plusieurs <parts> non supportés, attendu exactement 1"
        )
    new_block = f'<objects count="{count}">{inner}</objects>'
    result, n = re.subn(
        r"<objects[^>]*>.*?</objects>|<objects[^>]*/\s*>",
        new_block, xml, count=1, flags=re.DOTALL,
    )
    if n == 0:
        raise ValueError("Bloc <objects> présent mais non remplacé — format inattendu")
    return result


# ── API publique ──────────────────────────────────────────────────────────────

def write_omap(
    out_path: str | Path,
    template: Template,
    layers: list[Layer | LineLayer | PointLayer],
    georef: GeoRef,
) -> None:
    """Génère un fichier .omap en injectant les couches dans le gabarit ISOM.

    Accepte les trois familles :
    - Layer      → surfaces (polygones Shapely)
    - LineLayer  → lignes (polylignes, ouvertes ou fermées)
    - PointLayer → symboles ponctuels

    Gates bloquants (lèvent une exception avant toute écriture) :
    - code ISOM absent du gabarit → KeyError
    - géométrie invalide irrécupérable → ValueError
    - anneau/polyligne avec < 2 (lignes) ou < 3 (anneaux) points → ValueError

    Les coordonnées doivent être en EPSG:2154 (vérification à la charge de l'appelant).
    """
    xml = template.source_xml

    # 1. Géoréférencement
    xml = _replace_block(xml, "georeferencing", georef.xml_block)

    # 2. Construction des objets (valide tout avant d'écrire)
    obj_parts: list[str] = []
    for layer in layers:
        if layer.isom_code not in template.code_to_id:
            raise KeyError(
                f"Code ISOM {layer.isom_code} (couche '{layer.name}') absent du gabarit"
            )
        sym_id = template.code_to_id[layer.isom_code]

        if isinstance(layer, LineLayer):
            for vertices, is_closed in layer.segments:
                obj_parts.append(_line_to_xml(vertices, is_closed, sym_id, georef))
        elif isinstance(layer, PointLayer):
            for x, y in layer.points:
                obj_parts.append(_point_to_xml(x, y, sym_id, georef))
        else:
            for geom in layer.geometries:
                for poly in _iter_polygons(geom):
                    obj_parts.append(_polygon_to_xml(poly, sym_id, georef))

    # 3. Injection dans le gabarit
    xml = _replace_objects(xml, "\n".join(obj_parts), len(obj_parts))

    Path(out_path).write_text(xml, encoding="utf-8")
