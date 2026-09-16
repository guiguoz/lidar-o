"""Tests du mécanisme config_snapshot.

Principe : tester que snapshot A != snapshot B quand la config varie,
et que check_config_snapshot() identifie nommément le paramètre divergent.
Un test "même config → même snapshot" serait vrai par construction — il ne
teste rien d'utile.
"""
import json
import pathlib

import pytest

from src.guards import check_config_snapshot
from src.qa import write_config_snapshot


def _base_cfg(**overrides) -> dict:
    cfg: dict = {
        "generalization": {
            "active_profile": "test_profile",
            "profiles": {
                "test_profile": {
                    "min_area_m2": {406: 100, 408: 100, 410: 75},
                    "fusion_distance_m": {406: 5, 408: 5, 410: 5},
                    "qa_targets": {},
                },
            },
        },
        "vegetation": {
            "active_preset": "test_preset",
            "presets": {"test_preset": {"thresholds": [0.20, 0.45, 0.85]}},
            "process_hag": {"gaussian_sigma": 1.0},
            "density_metric": {"mode": "ratio"},
            "grid_resolution_m": 1.0,
            "normalization": {"mode": "p95_local"},
        },
        "karttapullautin": {
            "version": "2.12.1",
            "rendering": {
                "lightgreentone": 160,
                "medianboxsize2": 16,
                "template_opacity_pct": 50,
            },
        },
    }
    for path, value in overrides.items():
        keys = path.split(".")
        node = cfg
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return cfg


def _read_snapshot(output_dir: pathlib.Path) -> dict:
    return json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))[
        "config_snapshot"
    ]


# ── B.4 : variation produit un snapshot différent ────────────────────────────

def test_snapshot_captures_kp_medianboxsize2(tmp_path: pathlib.Path) -> None:
    """Un changement de medianboxsize2 produit deux snapshots distincts."""
    cfg_a = _base_cfg(**{"karttapullautin.rendering.medianboxsize2": 1})
    cfg_b = _base_cfg(**{"karttapullautin.rendering.medianboxsize2": 16})

    dir_a = tmp_path / "run_a"
    dir_b = tmp_path / "run_b"
    dir_a.mkdir(); dir_b.mkdir()

    write_config_snapshot(cfg_a, dir_a)
    write_config_snapshot(cfg_b, dir_b)

    snap_a = _read_snapshot(dir_a)
    snap_b = _read_snapshot(dir_b)

    assert snap_a["kp_medianboxsize2"] == 1
    assert snap_b["kp_medianboxsize2"] == 16
    assert snap_a["kp_medianboxsize2"] != snap_b["kp_medianboxsize2"]


def test_snapshot_captures_kp_lightgreentone(tmp_path: pathlib.Path) -> None:
    """Un changement de lightgreentone se reflète dans le snapshot."""
    cfg_a = _base_cfg(**{"karttapullautin.rendering.lightgreentone": 160})
    cfg_b = _base_cfg(**{"karttapullautin.rendering.lightgreentone": 200})

    dir_a = tmp_path / "a"; dir_b = tmp_path / "b"
    dir_a.mkdir(); dir_b.mkdir()

    write_config_snapshot(cfg_a, dir_a)
    write_config_snapshot(cfg_b, dir_b)

    assert _read_snapshot(dir_a)["kp_lightgreentone"] == 160
    assert _read_snapshot(dir_b)["kp_lightgreentone"] == 200


def test_check_names_diverging_kp_param(tmp_path: pathlib.Path) -> None:
    """check_config_snapshot nomme le paramètre KP divergent."""
    cfg_reference = _base_cfg(**{"karttapullautin.rendering.medianboxsize2": 16})
    write_config_snapshot(cfg_reference, tmp_path)

    cfg_different = _base_cfg(**{"karttapullautin.rendering.medianboxsize2": 1})
    meta_path = tmp_path / "run_metadata.json"
    diffs = check_config_snapshot(cfg_different, meta_path)

    assert any("kp_medianboxsize2" in d for d in diffs), (
        f"kp_medianboxsize2 absent des diffs : {diffs}"
    )
    assert any("snapshot=16" in d for d in diffs), diffs
    assert any("config=1" in d for d in diffs), diffs


def test_check_names_diverging_hag_param(tmp_path: pathlib.Path) -> None:
    """check_config_snapshot nomme aussi les paramètres HAG divergents."""
    cfg_reference = _base_cfg(**{"vegetation.process_hag.gaussian_sigma": 1.0})
    write_config_snapshot(cfg_reference, tmp_path)

    cfg_different = _base_cfg(**{"vegetation.process_hag.gaussian_sigma": 3.0})
    meta_path = tmp_path / "run_metadata.json"
    diffs = check_config_snapshot(cfg_different, meta_path)

    assert any("gaussian_sigma" in d for d in diffs), diffs


def test_check_no_diff_on_same_config(tmp_path: pathlib.Path) -> None:
    """Même config → aucune divergence signalée."""
    cfg = _base_cfg()
    write_config_snapshot(cfg, tmp_path)
    diffs = check_config_snapshot(cfg, tmp_path / "run_metadata.json")
    assert diffs == []


def test_snapshot_contains_git_hash(tmp_path: pathlib.Path) -> None:
    """Le snapshot inclut git_hash (peut être None hors dépôt git)."""
    cfg = _base_cfg()
    write_config_snapshot(cfg, tmp_path)
    snap = _read_snapshot(tmp_path)
    assert "git_hash" in snap
