"""Tests de _bdtopo_status, déduplication LiDAR et _bbox_from_tiles (gui/app.py) — aucune fenêtre."""
from __future__ import annotations

import pathlib

import pytest

import gui.app as gui_app
from gui.app import _bdtopo_status, _COLOR_MISSING, _COLOR_PRESENT, _COLOR_UNVERIFIED
from src.check_terrain import BdtopoCoverageResult, BdtopoLayerResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _layer(status: str, missing: list[str] | None = None, reason: str = "") -> BdtopoLayerResult:
    return BdtopoLayerResult(status, missing or [], reason or f"layer-{status}")


def _cov(status: str, reason: str = "") -> BdtopoCoverageResult:
    return BdtopoCoverageResult(status, reason or f"cov-{status}")


# ── Tests _bdtopo_status ──────────────────────────────────────────────────────

class TestBdtopoStatus:
    """9 combinaisons ok/anomalie/non_verifie × ok/anomalie/non_verifie."""

    def test_ok_ok_produit_coche_vert(self):
        text, color = _bdtopo_status(_layer("ok"), _cov("ok"), "bd.gpkg")
        assert "✓" in text
        assert "bd.gpkg" in text
        assert color == _COLOR_PRESENT

    def test_anomalie_ok_rouge_pas_coche(self):
        text, color = _bdtopo_status(
            _layer("anomalie", ["troncon_de_route"], "couches manquantes"),
            _cov("ok"),
            "bd.gpkg",
        )
        assert "✓" not in text
        assert color == _COLOR_MISSING

    def test_ok_anomalie_rouge_pas_coche(self):
        text, color = _bdtopo_status(_layer("ok"), _cov("anomalie"), "bd.gpkg")
        assert "✓" not in text
        assert color == _COLOR_MISSING

    def test_anomalie_anomalie_rouge_pas_coche(self):
        text, color = _bdtopo_status(
            _layer("anomalie", ["batiment"]),
            _cov("anomalie"),
            "bd.gpkg",
        )
        assert "✓" not in text
        assert color == _COLOR_MISSING

    def test_non_verifie_ok_orange_pas_coche(self):
        text, color = _bdtopo_status(_layer("non_verifie"), _cov("ok"), "bd.gpkg")
        assert "✓" not in text
        assert color == _COLOR_UNVERIFIED

    def test_ok_non_verifie_orange_pas_coche(self):
        text, color = _bdtopo_status(_layer("ok"), _cov("non_verifie"), "bd.gpkg")
        assert "✓" not in text
        assert color == _COLOR_UNVERIFIED

    def test_non_verifie_non_verifie_orange_pas_coche(self):
        text, color = _bdtopo_status(
            _layer("non_verifie"),
            _cov("non_verifie"),
            "bd.gpkg",
        )
        assert "✓" not in text
        assert color == _COLOR_UNVERIFIED

    def test_anomalie_non_verifie_rouge_pas_coche(self):
        """Une anomalie prime sur non_verifie → rouge."""
        text, color = _bdtopo_status(
            _layer("anomalie", ["troncon_de_route"]),
            _cov("non_verifie"),
            "bd.gpkg",
        )
        assert "✓" not in text
        assert color == _COLOR_MISSING

    def test_non_verifie_anomalie_rouge_pas_coche(self):
        """Une anomalie côté couverture prime → rouge."""
        text, color = _bdtopo_status(
            _layer("non_verifie"),
            _cov("anomalie"),
            "bd.gpkg",
        )
        assert "✓" not in text
        assert color == _COLOR_MISSING

    def test_raisons_des_deux_controles_presentes_quand_non_ok(self):
        """Quand les deux contrôles sont non-ok, leurs raisons apparaissent toutes deux."""
        layer_reason = "non vérifié (couches) : pyogrio absent"
        cov_reason = "non vérifié (couverture) : bbox absente"
        text, _ = _bdtopo_status(
            _layer("non_verifie", reason=layer_reason),
            _cov("non_verifie", reason=cov_reason),
            "bd.gpkg",
        )
        assert layer_reason in text
        assert cov_reason in text

    def test_raisons_anomalie_et_non_verifie_toutes_deux_presentes(self):
        """anomalie couches + non_verifie couverture → les deux lignes dans le texte."""
        text, color = _bdtopo_status(
            _layer("anomalie", ["batiment"], "couches manquantes : batiment"),
            _cov("non_verifie", "non vérifié couverture"),
            "bd.gpkg",
        )
        assert "batiment" in text
        assert "non vérifié couverture" in text
        assert color == _COLOR_MISSING

    def test_aucun_coche_pour_les_8_combinaisons_non_ok_ok(self):
        """Garde-fou : aucun ✓ pour les 8 combinaisons autres que (ok, ok)."""
        statuses = ["ok", "anomalie", "non_verifie"]
        for ls in statuses:
            for cs in statuses:
                if ls == "ok" and cs == "ok":
                    continue
                text, _ = _bdtopo_status(
                    _layer(ls, ["x"] if ls == "anomalie" else []),
                    _cov(cs),
                    "bd.gpkg",
                )
                assert "✓" not in text, (
                    f"✓ ne doit pas apparaître pour ({ls}, {cs}), obtenu: {text!r}"
                )


# ── Déduplication dalles LiDAR ───────────────────────────────────────────────

class TestTileDeduplicate:
    """Vérifie que *.copc.laz n'est pas compté deux fois par *.laz."""

    @staticmethod
    def _deduplicate(paths: list[pathlib.Path]) -> list[pathlib.Path]:
        seen: set[pathlib.Path] = set()
        tiles: list[pathlib.Path] = []
        for p in paths:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                tiles.append(p)
        return tiles

    def test_copc_laz_ne_compte_pas_deux_fois(self, tmp_path):
        f = tmp_path / "tile.copc.laz"
        f.write_bytes(b"")
        both = list(tmp_path.glob("*.copc.laz")) + list(tmp_path.glob("*.laz"))
        assert len(both) == 2, "le bug original doit être reproductible"
        assert len(self._deduplicate(both)) == 1

    def test_sept_copc_laz_comptent_sept_pas_quatorze(self, tmp_path):
        for i in range(7):
            (tmp_path / f"tile_{i}.copc.laz").write_bytes(b"")
        both = list(tmp_path.glob("*.copc.laz")) + list(tmp_path.glob("*.laz"))
        assert len(both) == 14, "le bug doit être reproductible pour 7 dalles"
        assert len(self._deduplicate(both)) == 7

    def test_laz_non_copc_reste_distinct(self, tmp_path):
        (tmp_path / "a.copc.laz").write_bytes(b"")
        (tmp_path / "b.laz").write_bytes(b"")
        both = list(tmp_path.glob("*.copc.laz")) + list(tmp_path.glob("*.laz"))
        assert len(self._deduplicate(both)) == 2

    def test_mix_copc_et_laz_simples(self, tmp_path):
        (tmp_path / "a.copc.laz").write_bytes(b"")
        (tmp_path / "b.copc.laz").write_bytes(b"")
        (tmp_path / "c.laz").write_bytes(b"")
        both = list(tmp_path.glob("*.copc.laz")) + list(tmp_path.glob("*.laz"))
        # a et b comptés deux fois par glob → 5 entrées ; dédupliqué → 3
        assert len(self._deduplicate(both)) == 3


# ── _bbox_from_tiles ─────────────────────────────────────────────────────────

class TestBboxFromTiles:
    """Teste LidarOApp._bbox_from_tiles sans ouvrir de fenêtre tkinter."""

    @staticmethod
    def _make_app(tile_extents: dict) -> gui_app.LidarOApp:
        app = object.__new__(gui_app.LidarOApp)
        app._tile_extents = tile_extents
        return app

    def test_union_deux_dalles_adjacentes(self):
        app = self._make_app({
            pathlib.Path("a.laz"): (448000.0, 6885000.0, 449000.0, 6886000.0),
            pathlib.Path("b.laz"): (449000.0, 6885000.0, 450000.0, 6886000.0),
        })
        assert app._bbox_from_tiles() == (448000.0, 6885000.0, 450000.0, 6886000.0)

    def test_retourne_none_si_dict_vide(self):
        assert self._make_app({})._bbox_from_tiles() is None

    def test_ignore_extents_none(self):
        app = self._make_app({
            pathlib.Path("a.laz"): None,
            pathlib.Path("b.laz"): (448000.0, 6885000.0, 449000.0, 6886000.0),
        })
        assert app._bbox_from_tiles() == (448000.0, 6885000.0, 449000.0, 6886000.0)

    def test_retourne_none_si_tous_none(self):
        app = self._make_app({
            pathlib.Path("a.laz"): None,
            pathlib.Path("b.laz"): None,
        })
        assert app._bbox_from_tiles() is None

    def test_une_seule_dalle(self):
        app = self._make_app({
            pathlib.Path("tile.copc.laz"): (450000.0, 6887000.0, 451000.0, 6888000.0),
        })
        assert app._bbox_from_tiles() == (450000.0, 6887000.0, 451000.0, 6888000.0)


# ── Garde-fous source ─────────────────────────────────────────────────────────

class TestGuiAppSource:
    """Vérifie que gui/app.py ne contient plus fiona ni de "#ff9800" magique."""

    _app_path = pathlib.Path(__file__).parent.parent / "gui" / "app.py"

    def test_fiona_absent_du_source(self):
        assert "fiona" not in self._app_path.read_text(encoding="utf-8"), (
            "gui/app.py ne doit plus importer fiona"
        )

    def test_une_seule_occurrence_de_ff9800(self):
        """La valeur magique #ff9800 ne doit apparaître qu'une fois : la définition de _COLOR_UNVERIFIED."""
        count = self._app_path.read_text(encoding="utf-8").count('"#ff9800"')
        assert count == 1, (
            f"#ff9800 devrait apparaître exactement 1 fois (définition constante), trouvé {count}"
        )
