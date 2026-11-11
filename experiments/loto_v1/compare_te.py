"""Tableau comparatif T vs E — branche RF_leaf5.

Lit metrics.json (T) et metrics_e.json (E) et affiche
le delta par métrique, par terrain et en moyenne.

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/compare_te.py
"""
from __future__ import annotations

import json
import pathlib

import numpy as np

_THIS = pathlib.Path(__file__).resolve().parent
RESULTS_DIR   = _THIS / "results"
RESULTS_E_DIR = _THIS / "results_e"

FOLDS = ["bd", "caen", "montmirel", "sainte_anne"]
VEG_KEYS = ["veg_406", "veg_408", "veg_410"]


def _load(path: pathlib.Path, config: str | None = None) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if config is not None:
        raw = [r for r in raw if r.get("config") == config]
    return {r["fold"]: r for r in raw}


def _fmt(v: float, delta: bool = False) -> str:
    if np.isnan(v):
        return "  NaN "
    if delta:
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:+.3f}"
    return f"{v:.3f}"


def main() -> None:
    mt = _load(RESULTS_DIR   / "metrics.json",   config="RF_leaf5")
    me = _load(RESULTS_E_DIR / "metrics_e.json", config="E_RF_leaf5")

    sep = "─" * 90
    print(f"\n{'T vs E — RF_leaf5 — 4 terrains LOTO':^90}")
    print(sep)

    # ── Par terrain ──────────────────────────────────────────────────────────
    headers = [
        ("mIoU-veg",  lambda r: r["macro_veg"]),
        ("IoU-prés",  lambda r: r["iou_veg"]),
        ("Prec-veg",  lambda r: r["prec_veg"]),
        ("Rec-veg",   lambda r: r["rec_veg"]),
        ("IoU-406",   lambda r: r["iou"]["veg_406"]),
        ("IoU-408",   lambda r: r["iou"]["veg_408"]),
        ("IoU-410",   lambda r: r["iou"]["veg_410"]),
    ]

    print(f"\n{'Terrain':>12s} | " + " | ".join(f"{h:>9s}" for h, _ in headers))
    print("-" * 12 + "-+-" + "-+-".join("-" * 9 for _ in headers))

    for fold in FOLDS:
        rt, re = mt[fold], me[fold]
        row_t = [_fmt(fn(rt)) for _, fn in headers]
        row_e = [_fmt(fn(re)) for _, fn in headers]
        row_d = [_fmt(fn(re) - fn(rt), delta=True) for _, fn in headers]
        print(f"{'T  ' + fold:>12s} | " + " | ".join(f"{v:>9s}" for v in row_t))
        print(f"{'E  ' + fold:>12s} | " + " | ".join(f"{v:>9s}" for v in row_e))
        print(f"{'Δ  ' + fold:>12s} | " + " | ".join(f"{v:>9s}" for v in row_d))
        print()

    # ── Moyennes ─────────────────────────────────────────────────────────────
    print(sep)
    print(f"\n{'Moyenne 4 terrains':^90}")
    print(f"\n{'':>12s} | " + " | ".join(f"{h:>9s}" for h, _ in headers))
    print("-" * 12 + "-+-" + "-+-".join("-" * 9 for _ in headers))

    vals_t = [[fn(mt[f]) for f in FOLDS] for _, fn in headers]
    vals_e = [[fn(me[f]) for f in FOLDS] for _, fn in headers]
    mean_t = [float(np.mean(v)) for v in vals_t]
    mean_e = [float(np.mean(v)) for v in vals_e]
    mean_d = [e - t for t, e in zip(mean_t, mean_e)]

    print(f"{'T (RF_leaf5)':>12s} | " + " | ".join(f"{_fmt(v):>9s}" for v in mean_t))
    print(f"{'E (RF_leaf5)':>12s} | " + " | ".join(f"{_fmt(v):>9s}" for v in mean_e))
    print(f"{'Δ E-T':>12s} | " + " | ".join(f"{_fmt(v, delta=True):>9s}" for v in mean_d))

    print(f"\n{sep}")
    print("\nNote : config pré-spécifiée RF_leaf5 — aucune sélection sur validation interne.")
    print("Δ positif = gain E par rapport à T.\n")


if __name__ == "__main__":
    main()
