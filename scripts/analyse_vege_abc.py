"""Analyse comparative des rasters végétation KP — expériences A / B / C.

Usage :
    python scripts/analyse_vege_abc.py [--out results_vege_abc.json]

Produit un JSON et un CSV avec :
  - surfaces en ha par classe ISOM (0, 406, 408, 410, jaune)
  - statistiques de composantes connexes (#CC, médiane, max) par classe
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
from collections import Counter

import numpy as np
from PIL import Image
from scipy import ndimage

# ── Palette KP (lightgreentone=160, greenshades=8) ───────────────────────────

JAUNE = (255, 219, 166)   # fond terrain (ISOM 401)
BLANC = (255, 255, 255)   # bit2 → ISOM 0 (blanc forêt courable)

# Bits 3–9, du plus clair au plus sombre (G décroissant)
GREENS_BIT = [
    (160, 254, 160),  # bit3 → 406
    (144, 246, 144),  # bit4 → 406
    (128, 239, 128),  # bit5 → 408
    (112, 231, 112),  # bit6 → 408
    ( 96, 224,  96),  # bit7 → 410
    ( 80, 217,  80),  # bit8 → 410
    ( 64, 209,  64),  # bit9 → 410
]

# shade_to_isom : bit → code ISOM
SHADE_TO_ISOM: dict[tuple[int, int, int], int] = {
    GREENS_BIT[0]: 406, GREENS_BIT[1]: 406,
    GREENS_BIT[2]: 408, GREENS_BIT[3]: 408,
    GREENS_BIT[4]: 410, GREENS_BIT[5]: 410, GREENS_BIT[6]: 410,
}

ISOM_CODES = [0, 406, 408, 410]


# ── Expériences ───────────────────────────────────────────────────────────────

BASE = pathlib.Path("out_kp_bois_dupont")
LAZ  = "LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz"

EXPERIMENTS = {
    "A_med9-16_t01": {
        "vege_png":   BASE / f"{LAZ}_vege.png",
        "vege_pgw":   BASE / f"{LAZ}_vege.pgw",
        "pullauta_ini": BASE / "pullauta.ini",
        "label": "med9/16 thresold=0.1",
    },
    "B_med1-1_t01": {
        "vege_png":   BASE / "test" / f"{LAZ}_vege.png",
        "vege_pgw":   BASE / "test" / f"{LAZ}_vege.pgw",
        "pullauta_ini": BASE / "test" / "pullauta.ini",
        "label": "med1/1 thresold=0.1",
    },
    "C_med1-1_t02": {
        "vege_png":   BASE / "exp_c" / f"{LAZ}_vege.png",
        "vege_pgw":   BASE / "exp_c" / f"{LAZ}_vege.pgw",
        "pullauta_ini": BASE / "exp_c" / "pullauta.ini",
        "label": "med1/1 thresold=0.2",
    },
}


# ── Fonctions d'analyse ───────────────────────────────────────────────────────

def surface_stats(arr: np.ndarray) -> dict[str, float]:
    h, w = arr.shape[:2]
    total = h * w
    counts: Counter = Counter(map(tuple, arr.reshape(-1, 3)))

    ha: dict[str, float] = {"jaune": 0.0, "blanc_0": 0.0, "406": 0.0, "408": 0.0, "410": 0.0}
    for col, cnt in counts.items():
        if col == JAUNE:
            ha["jaune"] += cnt / 10000
        elif col == BLANC:
            ha["blanc_0"] += cnt / 10000
        elif col in SHADE_TO_ISOM:
            ha[str(SHADE_TO_ISOM[col])] += cnt / 10000
    ha["total_vert"] = ha["406"] + ha["408"] + ha["410"]
    ha["pct_couvert"] = ha["total_vert"] / total * 100
    return ha


def cc_stats(arr: np.ndarray, isom_code: int) -> dict[str, int | float]:
    mask = np.zeros(arr.shape[:2], dtype=bool)
    for col, code in SHADE_TO_ISOM.items():
        if code == isom_code:
            col_arr = np.array(col, dtype=np.uint8)
            mask |= np.all(arr == col_arr, axis=2)

    labeled, num = ndimage.label(mask)
    if num == 0:
        return {"n_cc": 0, "median_m2": 0, "mean_m2": 0, "max_m2": 0}
    sizes = ndimage.sum(mask, labeled, range(1, num + 1))
    return {
        "n_cc":      int(num),
        "median_m2": int(np.median(sizes)),
        "mean_m2":   int(np.mean(sizes)),
        "max_m2":    int(sizes.max()),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="results_vege_abc.json")
    args = parser.parse_args()

    results: list[dict] = []

    for exp_id, meta in EXPERIMENTS.items():
        png_path: pathlib.Path = meta["vege_png"]
        if not png_path.exists():
            print(f"[WARN] absent : {png_path}")
            continue

        arr = np.array(Image.open(png_path).convert("RGB"))
        h, w = arr.shape[:2]

        record: dict = {
            "exp":    exp_id,
            "label":  meta["label"],
            "png":    str(png_path),
            "pgw":    str(meta["vege_pgw"]),
            "ini":    str(meta["pullauta_ini"]),
            "px_total": int(h * w),
            **{f"ha_{k}": round(v, 4) for k, v in surface_stats(arr).items()},
        }

        for code in [406, 408, 410]:
            stats = cc_stats(arr, code)
            for metric, val in stats.items():
                record[f"cc{code}_{metric}"] = val

        results.append(record)
        print(f"  {exp_id:25s}  406={record['ha_406']:.2f}ha  "
              f"408={record['ha_408']:.2f}ha  410={record['ha_410']:.2f}ha  "
              f"#CC410={record['cc410_n_cc']}")

    # JSON
    out_json = pathlib.Path(args.out)
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON -> {out_json}")

    # CSV
    out_csv = out_json.with_suffix(".csv")
    if results:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=results[0].keys())
            w.writeheader()
            w.writerows(results)
    print(f"CSV  -> {out_csv}")


if __name__ == "__main__":
    main()
