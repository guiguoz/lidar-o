"""Extraction des étiquettes OCAD.

Vérifications explicites :
  - alignement géométrique OCAD ↔ strates (même grille 500×500, 2 m/px)
  - centre pixel (0,0) conforme
  - pas de conversion couleur inconnue → 0 (découvert)
  - bati → LABEL_NODATA (exclu de l'apprentissage)
  - couleur non reconnue → LABEL_NODATA (exclu)
"""
from __future__ import annotations

import numpy as np
from PIL import Image
import rasterio

from config import (
    OCAD_PATH, STRATES_PATH,
    OCAD_PALETTE, CLASS_CODES, LABEL_NODATA,
    GRID_H, GRID_W, RES_M,
    LABELS_FILE,
)


def _check_alignment(ocad_arr: np.ndarray) -> None:
    """Vérifie que le PNG OCAD et le raster de strates sont sur la même grille."""
    h, w = ocad_arr.shape[:2]
    assert (h, w) == (GRID_H, GRID_W), \
        f"OCAD PNG {h}×{w} ≠ grille attendue {GRID_H}×{GRID_W}"

    with rasterio.open(STRATES_PATH) as src:
        t = src.transform
        # Centre du pixel (0,0) : (t.c + t.a/2, t.f + t.e/2)
        cx = t.c + t.a / 2.0
        cy = t.f + t.e / 2.0
        # Résolution (t.a = dx, |t.e| = dy)
        res_x, res_y = abs(t.a), abs(t.e)

    # Attendu d'après le PGW (confirmé session précédente)
    expected_cx, expected_cy = 425001.0, 6922999.0
    assert abs(cx - expected_cx) < 0.1, f"Centre px (0,0) X : {cx} ≠ {expected_cx}"
    assert abs(cy - expected_cy) < 0.1, f"Centre px (0,0) Y : {cy} ≠ {expected_cy}"
    assert abs(res_x - RES_M) < 0.01, f"Résolution X : {res_x} ≠ {RES_M} m/px"
    assert abs(res_y - RES_M) < 0.01, f"Résolution Y : {res_y} ≠ {RES_M} m/px"


def build_labels(ocad_arr: np.ndarray) -> np.ndarray:
    """
    RGB (H, W, 3) → labels (H, W) uint8.

    Codes :
      0 decouvert · 1 blanc · 2 veg_406 · 3 veg_408 · 4 veg_410
      LABEL_NODATA (255) = bati + couleur non reconnue
    Les cellules sans support LiDAR sont traitées en aval dans train.py
    (force LABEL_NODATA pour les pixels sans support).
    """
    h, w = ocad_arr.shape[:2]
    labels = np.full((h, w), LABEL_NODATA, dtype=np.uint8)

    for (r, g, b), name in OCAD_PALETTE.items():
        if name == "bati":
            continue  # → reste LABEL_NODATA
        if name not in CLASS_CODES:
            continue  # → reste LABEL_NODATA
        mask = (
            (ocad_arr[:, :, 0] == r) &
            (ocad_arr[:, :, 1] == g) &
            (ocad_arr[:, :, 2] == b)
        )
        labels[mask] = CLASS_CODES[name]

    return labels


def label_counts(labels: np.ndarray) -> dict[str, int]:
    """Dénombrement par classe + NODATA."""
    from config import CLASS_NAMES
    counts: dict[str, int] = {}
    for name in CLASS_NAMES:
        counts[name] = int((labels == CLASS_CODES[name]).sum())
    counts["nodata"] = int((labels == LABEL_NODATA).sum())
    return counts


def save_labels(*, verbose: bool = True) -> np.ndarray:
    """Charge l'OCAD, vérifie l'alignement, construit labels.npy."""
    img = Image.open(OCAD_PATH).convert("RGB")
    ocad_arr = np.array(img, dtype=np.uint8)

    _check_alignment(ocad_arr)
    labels = build_labels(ocad_arr)
    np.save(str(LABELS_FILE), labels)

    if verbose:
        counts = label_counts(labels)
        total = labels.size
        print(f"Labels sauvegardés : {LABELS_FILE}")
        for name, cnt in counts.items():
            print(f"  {name:>12} : {cnt:6d} px  ({100*cnt/total:.1f} %)")

    return labels


def load_labels() -> np.ndarray:
    return np.load(str(LABELS_FILE)).astype(np.uint8)


if __name__ == "__main__":
    save_labels()
