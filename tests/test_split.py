"""Tests du module src/split.py et garde-fous d'import pour src/omapmaker_ref.py."""
import importlib.util
import pathlib

import pytest
import yaml

from src.split import SplitConfig, load_split


def _minimal_yaml(tmp_path: pathlib.Path) -> pathlib.Path:
    data = {
        "split_y": 6887771.0,
        "validation_side": "north",
        "calibration_side": "south",
        "buffer": {
            "buffer_half_width_m": 30.0,
            "status": "provisional",
        },
    }
    p = tmp_path / "split.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# ── Garde-fous d'import ───────────────────────────────────────────────────────

def test_import_guard_split() -> None:
    """Garde-fou : src.split importable — module bien versionné."""
    from src.split import load_split as _fn
    assert _fn is not None


def test_import_guard_omapmaker_ref() -> None:
    """Garde-fou : src.omapmaker_ref trouvable via find_spec — module bien versionné.

    find_spec ne charge pas le module (pas d'import pdal) — vérifie uniquement
    que le fichier est présent sur sys.path, ce qui échoue si le module
    n'est pas suivi dans git.
    """
    spec = importlib.util.find_spec("src.omapmaker_ref")
    assert spec is not None, (
        "src/omapmaker_ref.py non trouvé — module non versionné ou absent du clone"
    )


# ── Chargement et propriétés ─────────────────────────────────────────────────

def test_load_split_with_yaml_path(tmp_path: pathlib.Path) -> None:
    """load_split(path) charge correctement un YAML minimal."""
    p = _minimal_yaml(tmp_path)
    sc = load_split(p)
    assert sc.split_y == 6887771.0
    assert sc.validation_side == "north"
    assert sc.calibration_side == "south"
    assert sc.buffer_half_width_m == 30.0
    assert sc.buffer_status == "provisional"


def test_split_derived_properties(tmp_path: pathlib.Path) -> None:
    """Propriétés dérivées cohérentes avec les formules documentées."""
    sc = load_split(_minimal_yaml(tmp_path))
    assert sc.validation_y_min == pytest.approx(6887771.0 + 30.0)
    assert sc.calibration_y_max == pytest.approx(6887771.0 - 30.0)
    assert sc.buffer_total_m == pytest.approx(60.0)
    assert sc.is_provisional is True
    flag = sc.provisional_flag()
    assert flag is not None
    assert "30" in flag


def test_split_frozen_is_provisional(tmp_path: pathlib.Path) -> None:
    """buffer.status=frozen → is_provisional False, provisional_flag None."""
    data = {
        "split_y": 6887771.0,
        "validation_side": "north",
        "calibration_side": "south",
        "buffer": {"buffer_half_width_m": 30.0, "status": "frozen"},
    }
    p = tmp_path / "split_frozen.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    sc = load_split(p)
    assert sc.is_provisional is False
    assert sc.provisional_flag() is None


def test_split_as_snapshot_dict(tmp_path: pathlib.Path) -> None:
    """as_snapshot_dict retourne les 8 clés attendues."""
    sc = load_split(_minimal_yaml(tmp_path))
    d = sc.as_snapshot_dict()
    for key in [
        "split_y", "validation_side", "calibration_side",
        "buffer_half_width_m", "buffer_total_m", "buffer_status",
        "validation_y_min", "calibration_y_max",
    ]:
        assert key in d, f"Clé '{key}' absente de as_snapshot_dict()"
    assert d["split_y"] == 6887771.0
    assert d["buffer_total_m"] == pytest.approx(60.0)
    assert d["validation_y_min"] == pytest.approx(6887771.0 + 30.0)
