"""Tests pour tools/ctrl_omap.py.

(a) Régression ALWAYS-ON : les <object> graphiques dans les définitions de symboles
    (<symbol> → <element> → <object>) ne doivent PAS être comptés comme objets de carte.
    C'est la régression du bug sym_? découvert lors de V4.

(b) Golden-skip sur artefacts V4 réels : actif seulement si les .omap V4 sont présents
    (work/expe/vectorisation/v4_no_template.omap et v4_with_template.omap).
    Attendu : 406=1340, 408=409, 410=18, aucun sym_?.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

# Accès à tools/ depuis le répertoire racine du repo
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.ctrl_omap import OmapCounts, count_objects, load_code_to_id

_NS = "http://openorienteering.org/apps/mapper/xml/v2"

# ── Gabarits XML synthétiques ─────────────────────────────────────────────────

def _xml_with_symbol_subelements() -> str:
    """Fichier .omap minimal contenant un <object> DANS une définition de symbole.

    Structure :
      <symbols>
        <symbol id="100" code="406">   ← définition du symbole
          <point_symbol>
            <elements count="1">
              <element>
                <object type="1">     ← sous-élément graphique, PAS un objet de carte
                  <coords count="1">0 0;</coords>
                </object>
              </element>
            </elements>
          </point_symbol>
        </symbol>
      </symbols>
      <parts>
        <part>
          <objects count="2">
            <object type="1" symbol="100">  ← objet de carte #1
              <coords count="1">1000 2000;</coords>
            </object>
            <object type="1" symbol="100">  ← objet de carte #2
              <coords count="1">3000 4000;</coords>
            </object>
          </objects>
        </part>
      </parts>
    """
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="{_NS}" version="9">
  <symbols count="1" id="test">
    <symbol id="100" code="406" name="Test">
      <point_symbol>
        <elements count="1">
          <element>
            <object type="1">
              <coords count="1">0 0;</coords>
            </object>
          </element>
        </elements>
      </point_symbol>
    </symbol>
  </symbols>
  <parts count="1" current="0">
    <part name="default">
      <objects count="2">
        <object type="1" symbol="100">
          <coords count="1">1000 2000;</coords>
        </object>
        <object type="1" symbol="100">
          <coords count="1">3000 4000;</coords>
        </object>
      </objects>
    </part>
  </parts>
</map>"""


def _xml_empty_objects() -> str:
    """Fichier .omap sans objet de carte."""
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="{_NS}" version="9">
  <symbols count="0"/>
  <parts count="1">
    <part name="default">
      <objects count="0"></objects>
    </part>
  </parts>
</map>"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_temp(tmp_path: Path, content: str, name: str = "test.omap") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ── (a) Régression sym_? — ALWAYS-ON ─────────────────────────────────────────

class TestSymQuestionRegression:
    """Régression du bug : root.iter() comptait les <object> de définitions de symboles."""

    def test_ne_compte_pas_objets_dans_symboles(self, tmp_path: Path) -> None:
        """Les <object> dans <element>/<symbol> ne doivent PAS être comptés."""
        path = _write_temp(tmp_path, _xml_with_symbol_subelements())
        code_to_id = {406: 100}
        result = count_objects(path, code_to_id)
        # Seulement les 2 objets de carte dans <objects>, PAS le 3e dans <symbol>
        assert result.actual == 2
        assert result.counts == {"406": 2}

    def test_count_attr_coherent(self, tmp_path: Path) -> None:
        path = _write_temp(tmp_path, _xml_with_symbol_subelements())
        result = count_objects(path)
        assert result.declared == 2
        assert result.actual == 2
        assert result.count_match is True

    def test_pas_de_sym_inconnu(self, tmp_path: Path) -> None:
        """Avec le bon code_to_id, aucun objet ne doit être inconnu."""
        path = _write_temp(tmp_path, _xml_with_symbol_subelements())
        result = count_objects(path, {406: 100})
        assert result.unknown_sym == []

    def test_symbole_inconnu_signale(self, tmp_path: Path) -> None:
        """Un objet avec un symbole absent du mapping → dans unknown_sym."""
        path = _write_temp(tmp_path, _xml_with_symbol_subelements())
        # code_to_id vide → aucun symbole reconnu
        result = count_objects(path, {})
        assert "sym_100" in result.unknown_sym
        assert result.actual == 2

    def test_pas_dobjet_sans_objects_block(self, tmp_path: Path) -> None:
        """Sans bloc <objects>, aucun objet ne doit être compté."""
        xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="{_NS}" version="9">
  <symbols count="0"/>
  <parts count="1"/>
</map>"""
        path = _write_temp(tmp_path, xml)
        result = count_objects(path)
        assert result.actual == 0
        assert result.counts == {}

    def test_objects_vide(self, tmp_path: Path) -> None:
        path = _write_temp(tmp_path, _xml_empty_objects())
        result = count_objects(path)
        assert result.actual == 0
        assert result.count_match is True


# ── (b) Golden-skip sur artefacts V4 réels ───────────────────────────────────

_V4_NO_TPL  = ROOT / "work/expe/vectorisation/v4_no_template.omap"
_V4_WITH_TPL = ROOT / "work/expe/vectorisation/v4_with_template.omap"
_ISOM_PATH  = ROOT / "assets/ISOM 2017-2_10000.omap"

_EXPECTED_COUNTS = {"406": 1340, "408": 409, "410": 18}
_EXPECTED_TOTAL  = 1767

_skip_no_tpl  = pytest.mark.skipif(
    not _V4_NO_TPL.exists(),
    reason=f"artefact absent : {_V4_NO_TPL.name}",
)
_skip_with_tpl = pytest.mark.skipif(
    not _V4_WITH_TPL.exists(),
    reason=f"artefact absent : {_V4_WITH_TPL.name}",
)
_skip_isom = pytest.mark.skipif(
    not _ISOM_PATH.exists(),
    reason=f"gabarit absent : {_ISOM_PATH.name}",
)


@pytest.mark.integration
class TestV4GoldenSkip:
    """Contrôles golden sur les artefacts V4 réels.

    Ces tests sont actifs si les .omap V4 et le gabarit ISOM sont présents.
    Ils vérifient que les comptes sont 406=1340, 408=409, 410=18, aucun sym_?.
    """

    @_skip_no_tpl
    @_skip_isom
    def test_no_template_comptes(self) -> None:
        code_to_id = load_code_to_id(_ISOM_PATH)
        result = count_objects(_V4_NO_TPL, code_to_id)
        assert result.counts == _EXPECTED_COUNTS
        assert result.actual == _EXPECTED_TOTAL
        assert result.unknown_sym == []
        assert result.count_match is True

    @_skip_with_tpl
    @_skip_isom
    def test_with_template_comptes(self) -> None:
        code_to_id = load_code_to_id(_ISOM_PATH)
        result = count_objects(_V4_WITH_TPL, code_to_id)
        assert result.counts == _EXPECTED_COUNTS
        assert result.actual == _EXPECTED_TOTAL
        assert result.unknown_sym == []
        assert result.count_match is True

    @_skip_no_tpl
    @_skip_with_tpl
    @_skip_isom
    def test_deux_variantes_identiques(self) -> None:
        """no_template et with_template doivent avoir les mêmes objets de carte."""
        code_to_id = load_code_to_id(_ISOM_PATH)
        r1 = count_objects(_V4_NO_TPL, code_to_id)
        r2 = count_objects(_V4_WITH_TPL, code_to_id)
        assert r1.counts == r2.counts
        assert r1.actual == r2.actual
