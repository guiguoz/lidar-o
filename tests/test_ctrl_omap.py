"""Tests du contrôle reproductible d'objets .omap (tools/ctrl_omap.py).

Régression du bug ``sym_?`` : un compteur parcourant tout le document
(``root.iter()``) comptait comme objets de carte les nœuds ``<object>``
imbriqués dans les définitions de symboles (``<element> → <object>``).
Le contrôle ne doit lire QUE le bloc de carte ``<objects>``.

Tests always-on : XML synthétique en mémoire, aucun artefact requis.
Tests golden-skip : artefacts V4 réels (work/expe/vectorisation/),
actifs seulement là où ils existent (machine exécuteur).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ctrl_omap import count_map_objects, load_id_to_code, main  # noqa: E402

_NS = "http://openorienteering.org/apps/mapper/xml/v2"


def _synth_omap(count_attr: str = "2", extra_obj: str = "") -> str:
    """.omap synthétique minimal, namespace réel inclus.

    Le piège : deux nœuds <object> vivent DANS les définitions de
    symboles (<symbol> → <element> → <object>) et ne doivent JAMAIS
    être comptés comme objets de carte.
    """
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="{_NS}" version="9">
  <symbols>
    <symbol id="1" code="406" type="1">
      <element><object type="1" symbol="1"/></element>
    </symbol>
    <symbol id="2" code="408" type="1">
      <element><object type="1" symbol="2"/></element>
    </symbol>
    <symbol id="3" code="406.1" type="1"/>
  </symbols>
  <objects count="{count_attr}">
    <object type="1" symbol="1"/>
    <object type="1" symbol="2"/>
    {extra_obj}
  </objects>
</map>"""


def _write(tmp_path: Path, xml: str, name: str = "t.omap") -> Path:
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return p


# ── always-on : régression du bug sym_? ───────────────────────────────────


def test_piege_definitions_symboles_non_compte(tmp_path):
    """Les <object> imbriqués dans <symbols> ne sont pas des objets de carte."""
    p = _write(tmp_path, _synth_omap())
    res = count_map_objects(p, {})
    assert res["n_map_objects"] == 2


def test_comptage_par_code_isom(tmp_path):
    p = _write(tmp_path, _synth_omap())
    res = count_map_objects(p, load_id_to_code(p))
    assert dict(res["by_code"]) == {406: 1, 408: 1}


def test_variante_decimale_exclue_du_mapping(tmp_path):
    """"406.1" n'est pas un symbole de base : id 3 sans code connu."""
    p = _write(tmp_path, _synth_omap())
    mapping = load_id_to_code(p)
    assert 3 not in mapping
    assert set(mapping) == {1, 2}


def test_attribut_count_verifie(tmp_path):
    ok = _write(tmp_path, _synth_omap(count_attr="2"), "ok.omap")
    ko = _write(tmp_path, _synth_omap(count_attr="3"), "ko.omap")
    assert count_map_objects(ok, {})["count_attr_ok"] is True
    assert count_map_objects(ko, {})["count_attr_ok"] is False


def test_mapping_none_vs_mapping_vide(tmp_path):
    """None = mapping non fourni ; {} = fourni mais vide (consigne V4.0)."""
    p = _write(tmp_path, _synth_omap())
    sans = count_map_objects(p, None)
    assert sans["by_code"] is None
    assert sans["unknown_symbol_ids"] is None
    vide = count_map_objects(p, {})
    assert vide["by_code"] == {}
    assert dict(vide["unknown_symbol_ids"]) == {"1": 1, "2": 1}


def test_objet_sans_attribut_symbol_signale(tmp_path):
    p = _write(tmp_path, _synth_omap(extra_obj='<object type="1"/>'))
    res = count_map_objects(p, {})
    assert res["n_map_objects"] == 3
    assert res["missing_symbol_attr"] == 1


def test_symbole_inconnu_signale(tmp_path):
    p = _write(tmp_path, _synth_omap(extra_obj='<object type="1" symbol="99"/>'))
    res = count_map_objects(p, load_id_to_code(p))
    assert dict(res["unknown_symbol_ids"]) == {"99": 1}


def test_cli_codes_retour(tmp_path, capsys):
    ok = _write(tmp_path, _synth_omap(), "ok.omap")
    ko = _write(tmp_path, _synth_omap(extra_obj='<object type="1" symbol="99"/>'), "ko.omap")
    assert main([str(ok)]) == 0
    capsys.readouterr()
    assert main([str(ko)]) == 1
    out = capsys.readouterr().out
    assert "PROBLÈMES" in out


# ── golden-skip : artefacts V4 réels (machine exécuteur) ──────────────────

_V4 = REPO_ROOT / "work" / "expe" / "vectorisation"
_NO_T = _V4 / "v4_no_template.omap"
_WITH_T = _V4 / "v4_with_template.omap"
_golden = pytest.mark.skipif(
    not (_NO_T.exists() and _WITH_T.exists()),
    reason="artefacts V4 absents (golden-skip)",
)

_EXPECTED = {406: 1340, 408: 409, 410: 18}


@_golden
def test_golden_no_template_comptes():
    res = count_map_objects(_NO_T, load_id_to_code(_NO_T))
    assert dict(res["by_code"]) == _EXPECTED


@_golden
def test_golden_with_template_comptes():
    res = count_map_objects(_WITH_T, load_id_to_code(_WITH_T))
    assert dict(res["by_code"]) == _EXPECTED


@_golden
def test_golden_aucun_objet_parasite():
    for f in (_NO_T, _WITH_T):
        res = count_map_objects(f, load_id_to_code(f))
        assert res["count_attr_ok"] is True
        assert res["missing_symbol_attr"] == 0
        assert not res["unknown_symbol_ids"]
        assert sum(res["by_code"].values()) == res["n_map_objects"]
