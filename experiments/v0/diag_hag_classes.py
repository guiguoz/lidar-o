"""Diagnostic HAG par classe LAS — Grimbosq (lecture seule, sans modification du pipeline).

Calcule la distribution des hauteurs au-dessus du sol [0, 3 m] pour chaque
classe LAS présente, en utilisant le DTM existant (trier_dtm.tif).

Usage :
    C:/Users/glemi/miniconda3/python.exe experiments/v0/diag_hag_classes.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pdal
import rasterio
import yaml
from rasterio.transform import rowcol

ROOT = pathlib.Path(__file__).parent.parent.parent
CFG_PATH = ROOT / "config.yaml"
LIDAR_DIR = ROOT / "LIDAR" / "grimbosq"
DTM_PATH = ROOT / "experiments" / "v0" / "output" / "level_a" / "trier_dtm.tif"
OUT_DIR = ROOT / "experiments" / "v0" / "output" / "level_a"

N_BINS = 20
H_MAX = 3.0
BIN_WIDTH = H_MAX / N_BINS   # 0.15 m exactement

LAS_NAMES = {
    0: "never_classified",
    1: "unclassified",
    2: "ground",
    3: "low_veg",
    4: "med_veg",
    5: "high_veg",
    6: "building",
    7: "low_noise",
    8: "model_key",
    9: "water",
}
CLASSES_REQUESTED = {2, 3, 4, 5, 6, 7, 9, 0, 1}


def main() -> None:
    cfg = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
    bbox = tuple(cfg["terrains"]["grimbosq"]["bbox"])
    crs = cfg["terrains"]["grimbosq"].get("crs", "EPSG:2154")
    xmin, ymin, xmax, ymax = bbox

    print(f"Emprise : ({xmin:.0f}, {ymin:.0f}) — ({xmax:.0f}, {ymax:.0f})  [{crs}]")
    print(f"DTM     : {DTM_PATH}")

    # ── Chargement DTM ─────────────────────────────────────────────────────────
    with rasterio.open(DTM_PATH) as src:
        dtm = src.read(1).astype(np.float32)
        dtm_t = src.transform
        dtm_rows, dtm_cols = src.height, src.width
    dtm[dtm == -9999.0] = np.nan
    print(f"DTM chargé : {dtm_rows}×{dtm_cols} px à {abs(dtm_t.a):.2f} m/px\n")

    bin_edges = np.linspace(0.0, H_MAX, N_BINS + 1)
    bin_labels = [f"[{bin_edges[i]:.2f},{bin_edges[i+1]:.2f})" for i in range(N_BINS)]

    copc_paths = sorted(LIDAR_DIR.glob("*.copc.laz"))
    print(f"Tuiles COPC : {len(copc_paths)}")
    for p in copc_paths:
        print(f"  {p.name}")
    print()

    # ── Accumulation tuile par tuile ──────────────────────────────────────────
    # class_code -> {"hist": ndarray(20), "neg", "lo", "hi_3", "above_0_2",
    #                "above_3", "total", "nan_hag"}
    class_stats: dict[int, dict] = {}
    grand_total = 0

    for tile_idx, path in enumerate(copc_paths, 1):
        print(f"Tuile {tile_idx}/{len(copc_paths)} : {path.name} ...")
        pipe = pdal.Pipeline(json.dumps({"pipeline": [
            {"type": "readers.copc", "filename": str(path)},
            {"type": "filters.crop",
             "bounds": f"([{xmin},{xmax}],[{ymin},{ymax}])"},
        ]}))
        n = pipe.execute()
        if n == 0:
            print(f"  -> 0 points dans l'emprise")
            continue
        pts = pipe.arrays[0]
        grand_total += len(pts)

        x = pts["X"].astype(np.float64)
        y = pts["Y"].astype(np.float64)
        z = pts["Z"].astype(np.float32)
        cls_arr = pts["Classification"].astype(np.int32)
        del pts

        # Calcul HAG par lookup cellule DTM (même méthode que trier_ref.py)
        ri, ci = rowcol(dtm_t, x, y)
        ri = np.asarray(ri, dtype=np.intp)
        ci = np.asarray(ci, dtype=np.intp)
        in_grid = (ri >= 0) & (ri < dtm_rows) & (ci >= 0) & (ci < dtm_cols)

        dtm_z = np.full(len(z), np.nan, dtype=np.float32)
        dtm_z[in_grid] = dtm[ri[in_grid], ci[in_grid]]
        hag = z - dtm_z

        for c in np.unique(cls_arr):
            c = int(c)
            mask = cls_arr == c
            h = hag[mask]

            if c not in class_stats:
                class_stats[c] = {
                    "hist": np.zeros(N_BINS, dtype=np.int64),
                    "neg": 0,
                    "lo": 0,    # [0, 0.2)
                    "hi_3": 0,  # [0.2, 3.0)
                    "above_0_2": 0,  # >= 0.2 (toutes hauteurs y compris > 3)
                    "above_3": 0,
                    "total": 0,
                    "nan_hag": 0,
                }
            s = class_stats[c]
            s["total"] += len(h)

            nan_m = np.isnan(h)
            s["nan_hag"] += int(nan_m.sum())
            hv = h[~nan_m]

            s["neg"] += int((hv < 0.0).sum())
            s["lo"] += int(((hv >= 0.0) & (hv < 0.2)).sum())
            s["hi_3"] += int(((hv >= 0.2) & (hv < H_MAX)).sum())
            s["above_0_2"] += int((hv >= 0.2).sum())
            s["above_3"] += int((hv >= H_MAX).sum())

            in_range = hv[(hv >= 0.0) & (hv < H_MAX)]
            hist, _ = np.histogram(in_range, bins=bin_edges)
            s["hist"] += hist

        del x, y, z, cls_arr, ri, ci, hag
        n_unique = len(np.unique(cls_arr if 'cls_arr' in dir() else np.array([])))
        print(f"  -> {n} pts, classes vues : {sorted(class_stats.keys())}")

    print(f"\nTotal points analysés : {grand_total:,}")
    print(f"Classes présentes     : {sorted(class_stats.keys())}\n")

    # ── Rapport classes absentes ───────────────────────────────────────────────
    absent = sorted(CLASSES_REQUESTED - set(class_stats.keys()))
    if absent:
        print(f"Classes demandées absentes des données : {absent}")

    # ── Output 1 : JSON ───────────────────────────────────────────────────────
    result = {
        "meta": {
            "bbox": list(bbox),
            "crs": crs,
            "n_tiles": len(copc_paths),
            "total_points": grand_total,
            "dtm_path": str(DTM_PATH),
            "hag_method": "Z - DTM[nearest_cell]  (même méthode que trier_ref.py)",
            "bin_width_m": BIN_WIDTH,
            "n_bins": N_BINS,
            "h_max": H_MAX,
        },
        "bin_labels": bin_labels,
        "classes": {},
    }
    for c, s in sorted(class_stats.items()):
        name = LAS_NAMES.get(c, f"class_{c}")
        result["classes"][str(c)] = {
            "name": name,
            "total": s["total"],
            "nan_hag": s["nan_hag"],
            "neg_hag": s["neg"],
            "hag_0_0p2": s["lo"],
            "hag_0p2_3m": s["hi_3"],
            "hag_ge_0p2": s["above_0_2"],
            "hag_ge_3m": s["above_3"],
            "frac_above_0p2": s["above_0_2"] / max(1, s["total"] - s["nan_hag"]),
            "histogram": s["hist"].tolist(),
        }

    json_path = OUT_DIR / "diag_hag_classes.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON écrit : {json_path}")

    # ── Output 2 : PNG histogramme ────────────────────────────────────────────
    classes_to_plot = sorted(class_stats.keys())
    n_cls = len(classes_to_plot)
    ncols = min(3, n_cls)
    nrows = (n_cls + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 5 * nrows), squeeze=False)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    palette = {2: "#8B4513", 3: "#90EE90", 4: "#32CD32", 5: "#006400",
               6: "#FF6347", 7: "#808080", 9: "#4169E1", 0: "#FFD700", 1: "#DAA520"}

    for idx, c in enumerate(classes_to_plot):
        ax = axes[idx // ncols][idx % ncols]
        s = class_stats[c]
        name = LAS_NAMES.get(c, f"class_{c}")
        color = palette.get(c, "steelblue")

        total_valid = s["total"] - s["nan_hag"]
        pct_hist = s["hist"] / max(1, total_valid) * 100

        ax.bar(bin_centers, pct_hist, width=BIN_WIDTH * 0.9,
               color=color, edgecolor="white", linewidth=0.5, alpha=0.85)
        ax.axvline(0.2, color="red", linewidth=1.5, linestyle="--", label="0.2 m (borne V)")

        frac = s["above_0_2"] / max(1, total_valid) * 100
        ax.set_title(
            f"Classe {c} — {name}\n"
            f"N={s['total']:,}  |  HAG≥0.2m : {frac:.1f}%",
            fontsize=9,
        )
        ax.set_xlabel("HAG (m)")
        ax.set_ylabel("% des points valides")
        ax.set_xlim(0, H_MAX)
        ax.legend(fontsize=7)

    # Masquer les axes vides
    for idx in range(n_cls, nrows * ncols):
        axes[idx // ncols][idx % ncols].set_visible(False)

    fig.suptitle(
        f"Distribution HAG [0–3 m] par classe LAS — Grimbosq\n"
        f"{len(copc_paths)} tuiles | {grand_total:,} pts | DTM 0.5m trier_ref",
        fontsize=12,
    )
    fig.tight_layout()
    png_path = OUT_DIR / "diag_hag_classes.png"
    fig.savefig(png_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"PNG écrit : {png_path}")

    # ── Output 3 : Markdown ────────────────────────────────────────────────────
    s2 = class_stats.get(2)
    if s2:
        valid2 = s2["total"] - s2["nan_hag"]
        frac2 = s2["above_0_2"] / max(1, valid2) * 100
    else:
        frac2 = float("nan")

    lines = [
        "# Diagnostic HAG par classe LAS — Grimbosq V0",
        "",
        f"**Classe LAS 2 : {frac2:.2f} % des points ont HAG ≥ 0,2 m**",
        "",
        "---",
        "",
        "## Métadonnées",
        "",
        f"- Tuiles analysées : {len(copc_paths)} ({', '.join(p.name for p in copc_paths)})",
        f"- Emprise (EPSG:2154) : ({xmin:.0f}, {ymin:.0f}) — ({xmax:.0f}, {ymax:.0f})",
        f"- Total points : {grand_total:,}",
        "- DTM utilisé : `trier_dtm.tif` (0.5 m, class 2, min/cell + NN fill)",
        "- Méthode HAG : `Z − DTM[cellule_la_plus_proche]`  (identique à trier_ref.py)",
        f"- Intervalles : {N_BINS} × {BIN_WIDTH:.2f} m de 0 à {H_MAX} m",
        "",
        "---",
        "",
        "## Résultats par classe",
        "",
    ]

    for c, s in sorted(class_stats.items()):
        name = LAS_NAMES.get(c, f"class_{c}")
        valid = s["total"] - s["nan_hag"]
        frac = s["above_0_2"] / max(1, valid) * 100
        present_flag = "(demandée)" if c in CLASSES_REQUESTED else "(non demandée)"
        lines += [
            f"### Classe {c} — {name} {present_flag}",
            "",
            f"| Métrique | Valeur |",
            f"|---|---|",
            f"| Total points | {s['total']:,} |",
            f"| HAG non calculable (hors grille DTM) | {s['nan_hag']:,} |",
            f"| HAG < 0 m | {s['neg']:,} |",
            f"| HAG ∈ [0, 0.2) m | {s['lo']:,} |",
            f"| HAG ∈ [0.2, 3.0) m | {s['hi_3']:,} |",
            f"| HAG ≥ 0.2 m (toutes haut.) | {s['above_0_2']:,} |",
            f"| HAG ≥ 3.0 m | {s['above_3']:,} |",
            f"| **Fraction HAG ≥ 0.2 m** | **{frac:.2f} %** |",
            "",
        ]

    lines += [
        "---",
        "",
        "## Classes absentes",
        "",
        f"Classes demandées non présentes : {absent if absent else 'aucune'}",
        "",
        "---",
        "",
        "## Tableau histogramme — 20 intervalles × classes",
        "",
    ]

    # En-tête tableau
    sorted_classes = sorted(class_stats.keys())
    hdr = "| Intervalle |" + "".join(f" cls{c} (%) |" for c in sorted_classes)
    sep = "|---|" + "---|" * len(sorted_classes)
    lines += [hdr, sep]

    for i, label in enumerate(bin_labels):
        row = f"| {label} |"
        for c in sorted_classes:
            s = class_stats[c]
            valid = s["total"] - s["nan_hag"]
            pct = s["hist"][i] / max(1, valid) * 100
            row += f" {pct:.2f} |"
        lines.append(row)

    lines += [
        "",
        "---",
        "",
        "## Question interprétative unique",
        "",
    ]
    if s2:
        valid2 = s2["total"] - s2["nan_hag"]
        frac2_exact = s2["above_0_2"] / max(1, valid2) * 100
        if frac2_exact > 1.0:
            lines.append(
                f"La classe LAS 2 contient {frac2_exact:.2f} % de points avec HAG ≥ 0,2 m "
                f"({s2['above_0_2']:,} points). Cette fraction est **susceptible d'expliquer "
                f"partiellement la faiblesse de V** si ces points contribuent à G sans contribuer à V."
            )
        else:
            lines.append(
                f"La classe LAS 2 ne contient que {frac2_exact:.2f} % de points avec HAG ≥ 0,2 m "
                f"({s2['above_0_2']:,} points). Cette fraction est **trop faible pour expliquer "
                f"seule la faiblesse de V**."
            )

    md_path = OUT_DIR / "diag_hag_classes.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown écrit : {md_path}")

    # ── Affichage console résultats principaux ─────────────────────────────────
    print()
    print("=" * 60)
    print("RÉSULTATS PRINCIPAUX")
    print("=" * 60)
    print(f"  Tuiles analysées  : {len(copc_paths)}")
    print(f"  Total points      : {grand_total:,}")
    print()
    print(f"  {'Cls':>4}  {'Nom':20s}  {'Total':>12}  {'HAG<0':>8}  {'[0,0.2)':>9}  {'>=0.2m':>9}  {'frac>=0.2':>9}")
    print("  " + "-" * 82)
    for c, s in sorted(class_stats.items()):
        name = LAS_NAMES.get(c, f"class_{c}")
        valid = s["total"] - s["nan_hag"]
        frac = s["above_0_2"] / max(1, valid) * 100
        flag = " <- POINT CENTRAL" if c == 2 else ""
        print(f"  {c:>4}  {name:20s}  {s['total']:>12,}  {s['neg']:>8,}  "
              f"{s['lo']:>9,}  {s['above_0_2']:>9,}  {frac:>8.2f}%{flag}")
    print()
    print(f"  Classes absentes parmi {sorted(CLASSES_REQUESTED)} : {absent}")
    print("=" * 60)


if __name__ == "__main__":
    main()
