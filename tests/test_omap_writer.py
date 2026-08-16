"""Tests unitaires pour src/omap_writer.py.

Aucun fichier externe requis : le gabarit est construit en mémoire.
Le golden test végétation réelle (necessitant ISOM_2017-2_10000.omap) est
marqué skip si le fichier est absent — il devient actif quand l'utilisateur
dépose le gabarit dans assets/.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import shapely.geometry as sg

from src.omap_writer import (
    GeoRef,
    Layer,
    LineLayer,
    PointLayer,
    Template,
    _from_omap,
    _to_omap,
    load_template,
    write_omap,
)

# ── GeoRefs de référence ──────────────────────────────────────────────────────

_GEOREF_XML = """\
<georeferencing scale="10000" auxiliary_scale_factor="0.999966" declination="-2.48">
  <projected_crs id="EPSG">
    <spec language="PROJ.4">+init=epsg:2154</spec>
    <parameter>2154</parameter>
    <ref_point x="450000" y="6888000"/>
  </projected_crs>
  <geographic_crs id="Geographic coordinates">
    <spec language="PROJ.4">+proj=latlong +datum=WGS84</spec>
    <ref_point_deg lat="49.04313972" lon="-0.42052612"/>
  </geographic_crs>
</georeferencing>"""

GEOREF = GeoRef(scale=10_000, ref_x=450_000.0, ref_y=6_888_000.0, xml_block=_GEOREF_XML)
GEOREF_15K = GeoRef(scale=15_000, ref_x=450_000.0, ref_y=6_888_000.0, xml_block=_GEOREF_XML)

# ── Gabarit minimal ───────────────────────────────────────────────────────────

_NS = "http://openorienteering.org/apps/mapper/xml/v2"


def _minimal_omap_xml() -> str:
    """Gabarit XML minimal avec les 3 symboles végétation (406/408/410)."""
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="{_NS}" version="9">
  <notes></notes>
  <georeferencing scale="10000">
    <projected_crs id="EPSG">
      <spec language="PROJ.4">+init=epsg:2154</spec>
      <parameter>2154</parameter>
      <ref_point x="0" y="0"/>
    </projected_crs>
  </georeferencing>
  <colors count="0"/>
  <symbols count="3" id="ISOM 2017-2">
    <symbol id="86" code="406" name="Vegetation: slow running"/>
    <symbol id="89" code="408" name="Vegetation: walk"/>
    <symbol id="93" code="410" name="Vegetation: fight"/>
  </symbols>
  <parts count="1" current="0">
    <part name="default"><objects count="0">
    </objects></part>
  </parts>
</map>"""


@pytest.fixture()
def minimal_template(tmp_path: Path) -> Template:
    p = tmp_path / "template.omap"
    p.write_text(_minimal_omap_xml(), encoding="utf-8")
    return load_template(p)


# ── Tests de conversion de coordonnées ───────────────────────────────────────

class TestConversion:
    def test_cas_verifie_consigne(self) -> None:
        """Cas validé dans la CONSIGNE : L93 (448906.9, 6888775.1) → (-109310, -77510)."""
        ox, oy = _to_omap(448_906.9, 6_888_775.1, GEOREF)
        assert ox == -109_310
        assert oy == -77_510

    def test_aller_retour_inferieur_1cm(self) -> None:
        """L93 → omap → L93 avec erreur < 1 cm à 1:10000."""
        x0, y0 = 449_123.456, 6_887_654.321
        ox, oy = _to_omap(x0, y0, GEOREF)
        x1, y1 = _from_omap(ox, oy, GEOREF)
        assert abs(x1 - x0) < 0.01
        assert abs(y1 - y0) < 0.01

    def test_echelle_15000(self) -> None:
        """À 1:15000, 15 m de déplacement → 1000 unités omap."""
        ox, oy = _to_omap(450_015.0, 6_888_000.0, GEOREF_15K)
        assert ox == 1_000
        assert oy == 0

    def test_point_ref_donne_zero(self) -> None:
        """Le point de référence lui-même est à (0, 0) en omap."""
        ox, oy = _to_omap(GEOREF.ref_x, GEOREF.ref_y, GEOREF)
        assert ox == 0
        assert oy == 0

    def test_y_est_inverse(self) -> None:
        """Y L93 croissant vers le nord → Y omap décroissant (Y inversé)."""
        # Point au nord du ref_point (Y_L93 > ref_y) → y_omap négatif
        _, oy = _to_omap(GEOREF.ref_x, GEOREF.ref_y + 100, GEOREF)
        assert oy < 0


# ── Tests de chargement du gabarit ───────────────────────────────────────────

class TestLoadTemplate:
    def test_mapping_code_vers_id(self, tmp_path: Path) -> None:
        """load_template extrait correctement le mapping code ISOM → id interne."""
        p = tmp_path / "t.omap"
        p.write_text(_minimal_omap_xml(), encoding="utf-8")
        t = load_template(p)
        assert t.code_to_id[406] == 86
        assert t.code_to_id[408] == 89
        assert t.code_to_id[410] == 93

    def test_source_xml_preservee(self, tmp_path: Path) -> None:
        """Le XML source est conservé intact dans Template.source_xml."""
        p = tmp_path / "t.omap"
        content = _minimal_omap_xml()
        p.write_text(content, encoding="utf-8")
        t = load_template(p)
        assert t.source_xml == content


# ── Test golden minimal : carré 100 m en 406 ─────────────────────────────────

class TestGoldenMinimal:
    def test_carre_100m_structure(self, tmp_path: Path, minimal_template: Template) -> None:
        """Carré 100 m en 406 → 1 objet, symbol=86, 5 coords, dernier flag 2."""
        sq = sg.box(450_000.0, 6_888_000.0, 450_100.0, 6_888_100.0)
        layers = [Layer("test_406", 406, [sq])]
        out = tmp_path / "output.omap"

        write_omap(out, minimal_template, layers, GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        objects = root.findall(f".//{{{_NS}}}object")
        assert len(objects) == 1, f"Attendu 1 objet, obtenu {len(objects)}"

        obj = objects[0]
        assert obj.get("symbol") == "86"
        coords = obj.find(f"{{{_NS}}}coords")
        assert coords is not None
        assert int(coords.get("count")) == 5

        pts = [p.strip() for p in coords.text.split(";") if p.strip()]
        assert len(pts) == 5
        assert pts[-1].split()[-1] == "2"   # flag fermeture anneau extérieur

    def test_pattern_present(self, tmp_path: Path, minimal_template: Template) -> None:
        """L'élément <pattern> est présent sur l'objet surfacique."""
        sq = sg.box(450_000.0, 6_888_000.0, 450_100.0, 6_888_100.0)
        out = tmp_path / "p.omap"
        write_omap(out, minimal_template, [Layer("l", 406, [sq])], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        pattern = root.find(f".//{{{_NS}}}pattern")
        assert pattern is not None
        assert pattern.get("rotation") == "0"


# ── Test polygone avec trou ───────────────────────────────────────────────────

class TestTrou:
    def test_anneau_interieur_flag_18(self, tmp_path: Path, minimal_template: Template) -> None:
        """Polygone avec anneau intérieur → dernier point du trou a flag 18."""
        exterior = [
            (450_000.0, 6_888_000.0), (450_200.0, 6_888_000.0),
            (450_200.0, 6_888_200.0), (450_000.0, 6_888_200.0),
        ]
        hole = [
            (450_050.0, 6_888_050.0), (450_150.0, 6_888_050.0),
            (450_150.0, 6_888_150.0), (450_050.0, 6_888_150.0),
        ]
        poly = sg.Polygon(exterior, [hole])
        out = tmp_path / "trou.omap"
        write_omap(out, minimal_template, [Layer("trou", 406, [poly])], GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        coords = root.find(f".//{{{_NS}}}coords")
        assert coords is not None
        pts = [p.strip() for p in coords.text.split(";") if p.strip()]

        # Extérieur : 4 coins + fermeture = 5 points, pts[4] flag 2
        assert pts[4].split()[-1] == "2"
        # Intérieur : 5 points supplémentaires, dernier flag 18
        assert pts[-1].split()[-1] == "18"

    def test_count_inclut_trou(self, tmp_path: Path, minimal_template: Template) -> None:
        """count de <coords> inclut tous les points : anneau ext + anneau(x) intérieur(s)."""
        exterior = [(450_000.0, 6_888_000.0), (450_200.0, 6_888_000.0),
                    (450_200.0, 6_888_200.0), (450_000.0, 6_888_200.0)]
        hole = [(450_050.0, 6_888_050.0), (450_150.0, 6_888_050.0),
                (450_150.0, 6_888_150.0), (450_050.0, 6_888_150.0)]
        poly = sg.Polygon(exterior, [hole])
        out = tmp_path / "count.omap"
        write_omap(out, minimal_template, [Layer("c", 406, [poly])], GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        coords = root.find(f".//{{{_NS}}}coords")
        # 5 (ext) + 5 (hole) = 10 points
        assert int(coords.get("count")) == 10


# ── Test gate : mapping manquant ─────────────────────────────────────────────

class TestMapping:
    def test_code_absent_keyerror(self, tmp_path: Path, minimal_template: Template) -> None:
        """Code ISOM absent du gabarit → KeyError avant toute écriture."""
        sq = sg.box(450_000.0, 6_888_000.0, 450_100.0, 6_888_100.0)
        out = tmp_path / "x.omap"
        with pytest.raises(KeyError, match="999"):
            write_omap(out, minimal_template, [Layer("inconnu", 999, [sq])], GEOREF)
        assert not out.exists()   # aucune écriture partielle

    def test_couches_vides_acceptees(self, tmp_path: Path, minimal_template: Template) -> None:
        """Couche avec liste de géométries vide → aucun objet, fichier valide."""
        out = tmp_path / "vide.omap"
        write_omap(out, minimal_template, [Layer("rien", 406, [])], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        objects = root.findall(f".//{{{_NS}}}object")
        assert len(objects) == 0


# ── Tests robustesse injection XML ───────────────────────────────────────────

class TestInjectionXML:
    def test_objects_autofermant(self, tmp_path: Path) -> None:
        """<objects count="0"/> auto-fermant → injection réussie, pas de silence."""
        xml = _minimal_omap_xml().replace(
            '<objects count="0">\n    </objects>',
            '<objects count="0"/>',
        )
        p = tmp_path / "self_close.omap"
        p.write_text(xml, encoding="utf-8")
        t = load_template(p)
        sq = sg.box(450_000.0, 6_888_000.0, 450_100.0, 6_888_100.0)
        out = tmp_path / "out.omap"
        write_omap(out, t, [Layer("l", 406, [sq])], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        objects = root.findall(f".//{{{_NS}}}object")
        assert len(objects) == 1

    def test_plusieurs_parts_echoue(self, tmp_path: Path) -> None:
        """Gabarit avec 2 blocs <objects> → ValueError explicite avant écriture."""
        extra = '<part name="other"><objects count="0"></objects></part>'
        xml = _minimal_omap_xml().replace(
            '</objects></part>\n  </parts>',
            f'</objects></part>\n  {extra}\n  </parts>',
        )
        p = tmp_path / "multi.omap"
        p.write_text(xml, encoding="utf-8")
        t = load_template(p)
        sq = sg.box(450_000.0, 6_888_000.0, 450_100.0, 6_888_100.0)
        out = tmp_path / "out.omap"
        with pytest.raises(ValueError, match="objects"):
            write_omap(out, t, [Layer("l", 406, [sq])], GEOREF)
        assert not out.exists()

    def test_georef_absent_echoue(self, tmp_path: Path) -> None:
        """Gabarit sans bloc <georeferencing> → ValueError avant écriture."""
        import re as _re
        xml = _re.sub(r"<georeferencing\b.*?</georeferencing>", "", _minimal_omap_xml(), flags=_re.DOTALL)
        p = tmp_path / "no_georef.omap"
        p.write_text(xml, encoding="utf-8")
        t = load_template(p)
        out = tmp_path / "out.omap"
        with pytest.raises(ValueError, match="georeferencing"):
            write_omap(out, t, [], GEOREF)
        assert not out.exists()


# ── Test load_georef sur fichier XML autonome ─────────────────────────────────

class TestLoadGeoref:
    def test_load_depuis_xml_autonome(self) -> None:
        """load_georef lit assets/georef_grimbosq.xml (bloc seul, sans racine .omap)."""
        from src.omap_writer import load_georef
        georef = load_georef(ASSETS / "georef_grimbosq.xml")
        assert georef.scale == 10_000
        assert georef.ref_x == 450_000.0
        assert georef.ref_y == 6_888_000.0

    def test_load_coherent_avec_cas_verifie(self) -> None:
        """Le GeoRef chargé depuis georef_grimbosq.xml reproduit le cas de conversion validé."""
        from src.omap_writer import load_georef
        georef = load_georef(ASSETS / "georef_grimbosq.xml")
        ox, oy = _to_omap(448_906.9, 6_888_775.1, georef)
        assert ox == -109_310
        assert oy == -77_510


# ── Test relecture XML ────────────────────────────────────────────────────────

class TestXMLValide:
    def test_xml_bien_forme(self, tmp_path: Path, minimal_template: Template) -> None:
        """Le fichier produit est du XML bien formé reparseable par ElementTree."""
        polys = [
            sg.box(450_000.0, 6_888_000.0 + i * 200.0,
                   450_100.0, 6_888_100.0 + i * 200.0)
            for i in range(3)
        ]
        layers = [
            Layer("406", 406, polys[:1]),
            Layer("408", 408, polys[1:2]),
            Layer("410", 410, polys[2:]),
        ]
        out = tmp_path / "multi.omap"
        write_omap(out, minimal_template, layers, GEOREF)
        ET.fromstring(out.read_text(encoding="utf-8"))   # lève si malformé

    def test_count_objects_correct(self, tmp_path: Path, minimal_template: Template) -> None:
        """L'attribut count de <objects> correspond au nombre d'objets réels."""
        polys = [sg.box(450_000.0 + i * 200, 6_888_000.0, 450_100.0 + i * 200, 6_888_100.0)
                 for i in range(5)]
        out = tmp_path / "count.omap"
        write_omap(out, minimal_template, [Layer("l", 406, polys)], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        parts = root.find(f".//{{{_NS}}}objects")
        assert parts is not None
        assert int(parts.get("count")) == 5
        assert len(root.findall(f".//{{{_NS}}}object")) == 5

    def test_georef_injecte(self, tmp_path: Path, minimal_template: Template) -> None:
        """Le bloc <georeferencing> du fichier produit correspond au GeoRef fourni."""
        out = tmp_path / "georef.omap"
        write_omap(out, minimal_template, [], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        geo = root.find(f".//{{{_NS}}}georeferencing")
        assert geo is not None
        assert int(geo.get("scale")) == 10_000


# ── Gabarit minimal relief ────────────────────────────────────────────────────

def _minimal_relief_omap_xml() -> str:
    """Gabarit XML minimal avec symboles relief (101/102/103/106/109/111/202).

    Les ids sont identiques aux codes pour simplifier les assertions.
    """
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="{_NS}" version="9">
  <notes></notes>
  <georeferencing scale="10000">
    <projected_crs id="EPSG">
      <spec language="PROJ.4">+init=epsg:2154</spec>
      <parameter>2154</parameter>
      <ref_point x="0" y="0"/>
    </projected_crs>
  </georeferencing>
  <colors count="0"/>
  <symbols count="7" id="ISOM 2017-2">
    <symbol id="101" code="101" name="Contour"/>
    <symbol id="102" code="102" name="Index Contour"/>
    <symbol id="103" code="103" name="Form Line"/>
    <symbol id="106" code="106" name="Depression"/>
    <symbol id="109" code="109" name="Small Knoll"/>
    <symbol id="111" code="111" name="Small Depression"/>
    <symbol id="202" code="202" name="Cliff"/>
  </symbols>
  <parts count="1" current="0">
    <part name="default"><objects count="0">
    </objects></part>
  </parts>
</map>"""


@pytest.fixture()
def relief_template(tmp_path: Path) -> Template:
    p = tmp_path / "relief_template.omap"
    p.write_text(_minimal_relief_omap_xml(), encoding="utf-8")
    return load_template(p)


# ── Tests lignes (LineLayer) ──────────────────────────────────────────────────

class TestGoldenLigneOuverte:
    def test_trois_points_pas_de_flag2(self, tmp_path: Path, relief_template: Template) -> None:
        """Polyligne ouverte de 3 points → type=1, count=3, aucun flag 2."""
        verts = [(449_000.0, 6_888_500.0), (449_100.0, 6_888_500.0), (449_200.0, 6_888_600.0)]
        layers = [LineLayer("test_101", 101, [(verts, False)])]
        out = tmp_path / "ligne_ouverte.omap"
        write_omap(out, relief_template, layers, GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        ns = _NS
        objects_elem = root.find(f".//{{{ns}}}objects")
        assert objects_elem is not None
        objs = objects_elem.findall(f"{{{ns}}}object")
        assert len(objs) == 1

        obj = objs[0]
        assert obj.get("type") == "1"
        assert obj.get("symbol") == "101"
        coords = obj.find(f"{{{ns}}}coords")
        assert int(coords.get("count")) == 3

        pts = [p.strip() for p in coords.text.split(";") if p.strip()]
        assert len(pts) == 3
        # Aucun flag 2 sur aucun point
        for pt in pts:
            tokens = pt.split()
            assert len(tokens) == 2, f"Point inattendu avec flag : {pt!r}"

    def test_pas_de_pattern(self, tmp_path: Path, relief_template: Template) -> None:
        """Ligne ouverte → pas d'élément <pattern> (réservé aux surfaces)."""
        verts = [(449_000.0, 6_888_500.0), (449_100.0, 6_888_600.0)]
        out = tmp_path / "no_pattern.omap"
        write_omap(out, relief_template, [LineLayer("l", 101, [(verts, False)])], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        objects_elem = root.find(f".//{{{_NS}}}objects")
        obj = objects_elem.find(f"{{{_NS}}}object")
        pattern = obj.find(f"{{{_NS}}}pattern")
        assert pattern is None


class TestGoldenLigneFermee:
    def test_anneau_dernier_point_flag2(self, tmp_path: Path, relief_template: Template) -> None:
        """Polyligne fermée → dernier point porte flag 2."""
        verts = [
            (449_000.0, 6_888_500.0),
            (449_100.0, 6_888_500.0),
            (449_100.0, 6_888_600.0),
            (449_000.0, 6_888_600.0),
        ]
        layers = [LineLayer("dep_106", 106, [(verts, True)])]
        out = tmp_path / "ligne_fermee.omap"
        write_omap(out, relief_template, layers, GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        ns = _NS
        objects_elem = root.find(f".//{{{ns}}}objects")
        obj = objects_elem.find(f"{{{ns}}}object")
        coords = obj.find(f"{{{ns}}}coords")
        pts = [p.strip() for p in coords.text.split(";") if p.strip()]
        assert len(pts) == 4
        assert pts[-1].split()[-1] == "2", f"Flag 2 attendu sur dernier point, obtenu : {pts[-1]!r}"

    def test_points_precedents_sans_flag(self, tmp_path: Path, relief_template: Template) -> None:
        """Ligne fermée → seul le dernier point a flag 2, pas les précédents."""
        verts = [
            (449_000.0, 6_888_500.0),
            (449_100.0, 6_888_500.0),
            (449_100.0, 6_888_600.0),
            (449_000.0, 6_888_600.0),
        ]
        out = tmp_path / "flags.omap"
        write_omap(out, relief_template, [LineLayer("l", 106, [(verts, True)])], GEOREF)
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        ns = _NS
        objects_elem = root.find(f".//{{{ns}}}objects")
        obj = objects_elem.find(f"{{{ns}}}object")
        coords = obj.find(f"{{{ns}}}coords")
        pts = [p.strip() for p in coords.text.split(";") if p.strip()]
        for pt in pts[:-1]:
            assert len(pt.split()) == 2, f"Flag inattendu sur point intermediaire : {pt!r}"


class TestGoldenPoint:
    def test_type0_count1(self, tmp_path: Path, relief_template: Template) -> None:
        """Symbole ponctuel → type=0, count=1, une seule coordonnée."""
        layers = [PointLayer("butte", 109, [(449_500.0, 6_888_500.0)])]
        out = tmp_path / "point.omap"
        write_omap(out, relief_template, layers, GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        ns = _NS
        objects_elem = root.find(f".//{{{ns}}}objects")
        objs = objects_elem.findall(f"{{{ns}}}object")
        assert len(objs) == 1

        obj = objs[0]
        assert obj.get("type") == "0"
        assert obj.get("symbol") == "109"
        coords = obj.find(f"{{{ns}}}coords")
        assert int(coords.get("count")) == 1
        pts = [p.strip() for p in coords.text.split(";") if p.strip()]
        assert len(pts) == 1

    def test_coordonnees_converties(self, tmp_path: Path, relief_template: Template) -> None:
        """La coordonnée du point est convertie en unités omap (L93 → 1/1000mm)."""
        x, y = 449_500.0, 6_888_500.0
        layers = [PointLayer("test", 109, [(x, y)])]
        out = tmp_path / "pt_coords.omap"
        write_omap(out, relief_template, layers, GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        ns = _NS
        objects_elem = root.find(f".//{{{ns}}}objects")
        obj = objects_elem.find(f"{{{ns}}}object")
        coords = obj.find(f"{{{ns}}}coords")
        ox_str, oy_str = coords.text.strip().rstrip(";").split()
        # Vérifier la valeur attendue
        expected_ox, expected_oy = _to_omap(x, y, GEOREF)
        assert int(ox_str) == expected_ox
        assert int(oy_str) == expected_oy


class TestMixteRelief:
    def test_write_omap_trois_familles(self, tmp_path: Path, minimal_template: Template,
                                       relief_template: Template) -> None:
        """write_omap accepte Layer + LineLayer + PointLayer dans le même appel."""
        sq = sg.box(450_000.0, 6_888_000.0, 450_100.0, 6_888_100.0)
        verts = [(449_000.0, 6_888_500.0), (449_100.0, 6_888_600.0)]
        layers = [
            Layer("veg", 406, [sq]),
            LineLayer("contour", 101, [(verts, False)]),
            PointLayer("butte", 109, [(449_500.0, 6_888_500.0)]),
        ]
        # Le gabarit doit contenir tous les codes : on construit un gabarit combiné
        xml_combined = _minimal_omap_xml().replace(
            '<symbols count="3" id="ISOM 2017-2">',
            '<symbols count="5" id="ISOM 2017-2">',
        ).replace(
            '    <symbol id="93" code="410" name="Vegetation: fight"/>\n  </symbols>',
            '    <symbol id="93" code="410" name="Vegetation: fight"/>\n'
            '    <symbol id="101" code="101" name="Contour"/>\n'
            '    <symbol id="109" code="109" name="Small Knoll"/>\n  </symbols>',
        )
        p = tmp_path / "combined.omap"
        p.write_text(xml_combined, encoding="utf-8")
        combined_template = load_template(p)

        out = tmp_path / "mixed.omap"
        write_omap(out, combined_template, layers, GEOREF)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        ns = _NS
        objects_elem = root.find(f".//{{{ns}}}objects")
        assert int(objects_elem.get("count")) == 3
        objs = objects_elem.findall(f"{{{ns}}}object")
        assert len(objs) == 3
        types = {obj.get("type") for obj in objs}
        assert "0" in types   # point
        assert "1" in types   # ligne + surface

    def test_keyerror_sur_linelayer(self, tmp_path: Path, minimal_template: Template) -> None:
        """LineLayer avec code ISOM absent → KeyError avant toute écriture."""
        verts = [(449_000.0, 6_888_500.0), (449_100.0, 6_888_600.0)]
        out = tmp_path / "err.omap"
        with pytest.raises(KeyError, match="101"):
            write_omap(out, minimal_template, [LineLayer("contour", 101, [(verts, False)])], GEOREF)
        assert not out.exists()

    def test_keyerror_sur_pointlayer(self, tmp_path: Path, minimal_template: Template) -> None:
        """PointLayer avec code ISOM absent → KeyError avant toute écriture."""
        out = tmp_path / "err2.omap"
        with pytest.raises(KeyError, match="109"):
            write_omap(out, minimal_template, [PointLayer("b", 109, [(449_000.0, 6_888_000.0)])], GEOREF)
        assert not out.exists()


# ── Test golden réel (skip si gabarit absent) ─────────────────────────────────

ASSETS = Path(__file__).parent.parent / "assets"
_TEMPLATE_PATH = ASSETS / "ISOM 2017-2_10000.omap"
_GEOREF_PATH = ASSETS / "georef_grimbosq.xml"


@pytest.mark.skipif(
    not _TEMPLATE_PATH.exists(),
    reason="ISOM 2017-2_10000.omap absent de assets/ — déposer le fichier pour activer ce test",
)
def test_ids_corrects_sur_gabarit_reel() -> None:
    """Non-régression : le gabarit réel doit donner les ids 86/89/93, pas des variantes."""
    t = load_template(_TEMPLATE_PATH)
    assert t.code_to_id.get(406) == 86, f"406 → {t.code_to_id.get(406)} (attendu 86)"
    assert t.code_to_id.get(408) == 89, f"408 → {t.code_to_id.get(408)} (attendu 89)"
    assert t.code_to_id.get(410) == 93, f"410 → {t.code_to_id.get(410)} (attendu 93)"


@pytest.mark.skipif(
    not _TEMPLATE_PATH.exists(),
    reason="ISOM 2017-2_10000.omap absent de assets/ — déposer le fichier pour activer ce test",
)
def test_golden_reel_ouvre(tmp_path: Path) -> None:
    """Golden test végétation réelle : génère un .omap avec les 3 classes Grimbosq."""
    from src.omap_writer import load_georef
    import geopandas as gpd

    veg_gpkg = Path("output/controle_visuel/vegetation_grimbosq.gpkg")
    if not veg_gpkg.exists():
        pytest.skip("vegetation_grimbosq.gpkg absent — lancer process_hag.py d'abord")

    template = load_template(_TEMPLATE_PATH)

    georef_path = _GEOREF_PATH if _GEOREF_PATH.exists() else None
    if georef_path is None:
        pytest.skip("sainte_anne.omap absent de assets/ — requis pour le georef")
    georef = load_georef(georef_path)

    layers: list[Layer] = []
    for code, layer_name in [(406, "406_Slow_Running"), (408, "408_Walk"), (410, "410_Fight")]:
        try:
            gdf = gpd.read_file(veg_gpkg, layer=layer_name)
        except Exception:
            continue
        layers.append(Layer(layer_name, code, list(gdf.geometry)))

    out = tmp_path / "grimbosq_veg.omap"
    write_omap(out, template, layers, georef)

    # Vérifications minimales — chercher uniquement dans le bloc <objects> (enfants directs),
    # pas de manière récursive : les définitions de symboles contiennent elles aussi des
    # éléments <object> sans attribut symbol qui remonteraient avec un findall récursif.
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    ns = _NS
    objects_elem = root.find(f".//{{{ns}}}objects")
    assert objects_elem is not None
    objects = objects_elem.findall(f"{{{ns}}}object")
    assert len(objects) > 0

    # Non-régression symboles : les ids doivent être exactement 86/89/93
    symbol_ids = {obj.get("symbol") for obj in objects}
    assert symbol_ids <= {"86", "89", "93"}, (
        f"Ids inattendus dans le .omap : {symbol_ids - {'86', '89', '93'}}"
    )
    print(f"\n[golden] {len(objects)} objets, ids={sorted(symbol_ids)}, écrit dans {out}")
