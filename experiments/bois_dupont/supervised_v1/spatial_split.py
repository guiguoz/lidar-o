"""Découpage spatial en 3 blocs non-chevauchants avec marges.

Blocs (bandes horizontales) :
  train : lignes [  0, 185)  — 185 × 500 = 92 500 px
  val   : lignes [200, 335)  — 135 × 500 = 67 500 px
  test  : lignes [350, 500)  — 150 × 500 = 75 000 px
Marges : lignes [185, 200) et [335, 350) — excluses de tout ensemble
  Largeur marge = 15 px = 30 m >> portée max descripteurs (12 m)

Convention : axe 0 = lignes (Y décroissant), axe 1 = colonnes (X croissant).
"""
from __future__ import annotations

import json
import numpy as np

from config import (
    SPLIT_CFG, MARGIN_PX, GRID_H, GRID_W, SCALES, SPLIT_FILE,
)


# ── Masques boléens (H × W) ──────────────────────────────────────────────

def build_split_masks() -> dict[str, np.ndarray]:
    """Retourne {"train": mask, "val": mask, "test": mask}."""
    masks: dict[str, np.ndarray] = {}
    for split_name, blk in SPLIT_CFG.items():
        m = np.zeros((GRID_H, GRID_W), dtype=bool)
        m[blk["r0"]:blk["r1"], blk["c0"]:blk["c1"]] = True
        masks[split_name] = m
    return masks


def validate_split(masks: dict[str, np.ndarray]) -> None:
    """Vérifie :
    - aucun chevauchement entre ensembles
    - marge effective ≥ MARGIN_PX entre chaque paire
    - pas de coordonnée absolue dans les masques (invariant par construction)
    """
    names = list(masks.keys())

    # 1. Non-chevauchement
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = int((masks[a] & masks[b]).sum())
            assert overlap == 0, f"Chevauchement {a} ∩ {b} = {overlap} px"

    # 2. Marge effective (en lignes) entre chaque paire de blocs
    max_scale_px = max(sigma_m for _, sigma_m in SCALES) / 1.0  # sigma_px = sigma_m / RES_M (RES_M=2)
    # À RES_M=2.0 : max sigma_m=6.0 → sigma_px=3.0 → rayon effectif ~2*truncate*sigma_px = 12 px
    # On exige marge ≥ MARGIN_PX = 15 px > 12 px → vérification structurelle

    # Cherche la ligne max du bloc i et la ligne min du bloc j (i < j)
    blk_items = [(n, SPLIT_CFG[n]) for n in names if n in SPLIT_CFG]
    blk_items.sort(key=lambda x: x[1]["r0"])
    for idx in range(len(blk_items) - 1):
        _, a_blk = blk_items[idx]
        _, b_blk = blk_items[idx + 1]
        margin_actual = b_blk["r0"] - a_blk["r1"]
        assert margin_actual >= MARGIN_PX, \
            f"Marge {margin_actual} px < {MARGIN_PX} px requis"

    # 3. Couverture totale sanity
    total_in_blocs = sum(m.sum() for m in masks.values())
    assert total_in_blocs <= GRID_H * GRID_W, "Blocs dépassent la grille"

    # 4. Aucune variable interdite : les masques ne contiennent pas de coord X/Y
    # (par construction, ce sont des tableaux booléens indexés par position)


def class_distribution_per_split(
    labels: np.ndarray,
    masks: dict[str, np.ndarray],
) -> dict[str, dict[str, int]]:
    """Compte les pixels de chaque classe dans chaque ensemble."""
    from config import CLASS_NAMES, CLASS_CODES, LABEL_NODATA
    result: dict[str, dict[str, int]] = {}
    for split_name, mask in masks.items():
        lbl_in = labels[mask]
        counts: dict[str, int] = {}
        for name in CLASS_NAMES:
            counts[name] = int((lbl_in == CLASS_CODES[name]).sum())
        counts["nodata"] = int((lbl_in == LABEL_NODATA).sum())
        result[split_name] = counts
    return result


def save_split(labels: np.ndarray) -> dict[str, np.ndarray]:
    """Construit, valide et sauvegarde le découpage."""
    masks = build_split_masks()
    validate_split(masks)

    dist = class_distribution_per_split(labels, masks)
    record = {
        "split_cfg": SPLIT_CFG,
        "margin_px": MARGIN_PX,
        "grid": {"h": GRID_H, "w": GRID_W},
        "distributions": dist,
    }
    SPLIT_FILE.write_text(json.dumps(record, indent=2))

    print(f"Découpage spatial : {SPLIT_FILE}")
    print(f"  Marge : {MARGIN_PX} px = {MARGIN_PX * 2:.0f} m")
    for split_name, counts in dist.items():
        total = sum(counts.values())
        blk = SPLIT_CFG[split_name]
        rows = blk["r1"] - blk["r0"]
        print(f"\n  {split_name:5} ({rows} × {GRID_W} px = {rows*GRID_W:,} px) :")
        for cls, cnt in counts.items():
            pct = 100.0 * cnt / max(total, 1)
            flag = " ← ABSENT" if cnt == 0 and cls != "nodata" else ""
            print(f"    {cls:>12} : {cnt:6d}  ({pct:.1f}%){flag}")

    return masks


if __name__ == "__main__":
    from labels import load_labels
    labels = load_labels()
    save_split(labels)
