"""Diagnostic de faisabilite HAG sur une tuile LiDAR a faible densite.

Quatre indicateurs dans l'ordre de criticite :

1. Proportion et densite de points sol (classe 2).
2. Relief reel de la tuile (Z stats des points sol uniquement).
3. Precision du modele sol -- validation croisee pair/impair :
   on construit le modele sol sur les points pairs, on mesure l'erreur
   d'interpolation sur les points impairs. Evite le biais circulaire de
   hag_nn (qui inclut chaque point dans son propre voisinage -> std bas).
4. Zone de bascule [0.30:0.50m] : fraction de tous les retours dont HAG tombe
   dans cette bande apres hag_nn, rapportee a la bande suivante [0.50:0.70m].
   Une accumulation anormale au-dessus du seuil est la signature d'un bruit de sol
   qui bascule des retours de part et d'autre du seuil 0,30 m.

Usage :
    python scripts/diag_hag_feasibility.py tuile.laz
    python scripts/diag_hag_feasibility.py tuile.laz --reader las
    python scripts/diag_hag_feasibility.py tuile.laz --hag-count 4
    python scripts/diag_hag_feasibility.py tuile.laz --out-dir rapports/kilemäed
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import pdal
from scipy.spatial import cKDTree


def _read_points(tile: str, reader: str, extra_filters: list | None = None) -> np.ndarray:
    stages: list[dict] = [{"type": reader, "filename": tile}]
    if extra_filters:
        stages.extend(extra_filters)
    pipeline = pdal.Pipeline(json.dumps({"pipeline": stages}))
    pipeline.execute()
    return pipeline.arrays[0]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Faisabilite hag_nn sur tuile LiDAR a faible densite"
    )
    parser.add_argument("tile", help="Fichier LiDAR (.laz)")
    parser.add_argument("--reader", choices=["las", "copc"], default=None,
                        help="Forcer reader (defaut : copc si .copc.laz, sinon las)")
    parser.add_argument("--hag-count", type=int, default=8,
                        help="Voisins sol pour hag_nn (defaut: 8)")
    parser.add_argument("--out-dir", help="Dossier de sortie pour le JSON")
    args = parser.parse_args()

    tile = str(pathlib.Path(args.tile).resolve())
    if not pathlib.Path(tile).exists():
        print(f"[ERREUR] Tuile introuvable : {tile}", file=sys.stderr)
        sys.exit(1)

    reader = args.reader or ("readers.copc" if tile.endswith(".copc.laz")
                             else "readers.las")
    if not reader.startswith("readers."):
        reader = f"readers.{reader}"

    k = args.hag_count
    print(f"[INFO] {pathlib.Path(tile).name}  reader={reader}  hag_count={k}")

    report: dict = {"tile": tile, "reader": reader, "hag_count": k}

    # ── Lecture complete ──────────────────────────────────────────────────────
    print("[INFO] Lecture de la tuile...")
    pts = _read_points(tile, reader)
    total = len(pts)
    X, Y, Z = pts["X"], pts["Y"], pts["Z"]
    C = pts["Classification"]

    dx = float(X.max() - X.min()); dy = float(Y.max() - Y.min())
    area_m2 = dx * dy

    # ── Etape 1 : proportion et densite sol ───────────────────────────────────
    print("\n[ETAPE 1] Proportion et densite sol")
    ground_mask = C == 2
    ground_count = int(ground_mask.sum())
    pct_ground = 100 * ground_count / total if total else 0
    density_total = total / area_m2 if area_m2 else 0
    density_ground = ground_count / area_m2 if area_m2 else 0

    print(f"  Emprise : {dx:.0f} x {dy:.0f} m = {area_m2/1e6:.3f} km²")
    print(f"  Points totaux    : {total:,}  ({density_total:.2f} pts/m²)")
    if density_ground > 0:
        print(f"  Points sol (cl2) : {ground_count:,}  ({pct_ground:.1f} %)"
              f"  ({density_ground:.3f} pts/m²)"
              f"  espacement moyen ~{1/density_ground**0.5:.1f} m")
    else:
        print(f"  Points sol (cl2) : {ground_count:,}  ({pct_ground:.1f} %)")

    report.update({"total_points": total, "ground_points": ground_count,
                   "ground_pct": round(pct_ground, 2),
                   "density_total_per_m2": round(density_total, 3),
                   "density_ground_per_m2": round(density_ground, 4)})

    if ground_count < 100:
        print("  [ALERTE] Moins de 100 points sol -- hag_nn impossible")
        sys.exit(1)
    if pct_ground < 1:
        print("  [ALERTE] < 1 % de sol -- hag_nn tres instable")
    elif pct_ground < 5:
        print("  [ATTENTION] Sol < 5 % -- verifier l'etape 3 avant de conclure")
    else:
        print("  [OK] Proportion sol suffisante")

    # ── Etape 2 : relief reel ─────────────────────────────────────────────────
    print("\n[ETAPE 2] Relief reel (Z des points sol uniquement)")
    Zg = Z[ground_mask]
    z_range = float(Zg.max() - Zg.min())
    z_std = float(Zg.std())

    print(f"  Z sol : min={Zg.min():.1f}  max={Zg.max():.1f}  "
          f"range={z_range:.1f} m  std={z_std:.2f} m")
    report.update({"z_range_ground_m": round(z_range, 1),
                   "z_std_ground_m": round(z_std, 2)})

    if z_range > 20:
        print(f"  [ATTENTION] Relief {z_range:.0f} m -- "
              "interpolation degradee a faible densite sol")
    elif z_range > 5:
        print(f"  [INFO] Relief modere {z_range:.0f} m -- "
              "surveiller l'erreur en etape 3")
    else:
        print(f"  [OK] Terrain plat ({z_range:.1f} m de denivele)")

    # ── Etape 3 : validation croisee pair/impair ──────────────────────────────
    print(f"\n[ETAPE 3] Validation croisee sol (pair->modele, impair->test, k={k})")
    Xg, Yg = X[ground_mask], Y[ground_mask]
    n_g = len(Xg)

    train = np.arange(n_g) % 2 == 0
    test = ~train
    n_test = int(test.sum())

    if n_test < 20:
        print("  [ATTENTION] Moins de 20 points sol en test -- resultat peu fiable")

    tree = cKDTree(np.column_stack([Xg[train], Yg[train]]))
    k_actual = min(k, int(train.sum()))
    dists, idxs = tree.query(np.column_stack([Xg[test], Yg[test]]), k=k_actual)

    Zt_train = Zg[train]
    if k_actual == 1:
        Z_interp = Zt_train[idxs.flatten()]
    else:
        w = 1.0 / np.maximum(dists, 1e-6)
        Z_interp = (w * Zt_train[idxs]).sum(axis=1) / w.sum(axis=1)

    cv_error = Zg[test] - Z_interp
    cv_std = float(np.std(cv_error))
    cv_p95 = float(np.percentile(np.abs(cv_error), 95))
    frac_above_30cm = float(np.mean(np.abs(cv_error) > 0.30))

    print(f"  n_test  : {n_test:,}")
    print(f"  std(erreur sol)         = {cv_std:.3f} m")
    print(f"  p95(|erreur sol|)       = {cv_p95:.3f} m")
    print(f"  fraction |erreur|>0.30m = {100*frac_above_30cm:.1f} %")

    report.update({"cv_std_m": round(cv_std, 4), "cv_p95_m": round(cv_p95, 4),
                   "cv_frac_error_above_30cm": round(frac_above_30cm, 4)})

    if frac_above_30cm > 0.05:
        verdict_cv = ("REDHIBITOIRE -- erreur sol depasse 0,30 m pour "
                      f"{100*frac_above_30cm:.0f} % des points test")
    elif cv_std > 0.10:
        verdict_cv = f"MARGINAL -- std={cv_std:.3f} m notable, tester a resolution augmentee"
    else:
        verdict_cv = f"OK -- erreur sol compatible avec seuil 0,30 m (std={cv_std:.3f} m)"
    print(f"  Verdict : {verdict_cv}")
    report["verdict_cv"] = verdict_cv

    # ── Etape 4 : zone de bascule [0.30:0.50m] ───────────────────────────────
    print(f"\n[ETAPE 4] Zone de bascule HAG [0.30:0.50m] apres hag_nn")
    print("  Calcul hag_nn sur l'ensemble de la tuile...")

    pts_hag = _read_points(tile, reader,
                           [{"type": "filters.hag_nn", "count": k}])
    if "HeightAboveGround" not in pts_hag.dtype.names:
        print("  [ERREUR] HeightAboveGround absent -- hag_nn a echoue")
        report["verdict_flip_zone"] = "ERREUR"
    else:
        hag = pts_hag["HeightAboveGround"]
        finite_mask = np.isfinite(hag)
        hag_v = hag[finite_mask]
        n_finite = len(hag_v)

        flip = float(np.mean((hag_v >= 0.30) & (hag_v < 0.50)))
        next_b = float(np.mean((hag_v >= 0.50) & (hag_v < 0.70)))
        veg_band = float(np.mean((hag_v >= 0.30) & (hag_v < 3.0)))
        ratio = flip / next_b if next_b > 0 else float("inf")
        contamination = flip / veg_band if veg_band > 0 else float("inf")

        print(f"  Points HAG valides    : {n_finite:,} / {total:,}")
        print(f"  HAG [0.00:0.30m]      : {100*np.mean(hag_v < 0.30):.1f} %  (sous le seuil)")
        print(f"  HAG [0.30:3.00m]      : {100*veg_band:.2f} %  (bande vegetation pipeline)")
        print(f"  HAG [0.30:0.50m]      : {100*flip:.2f} %  <- zone de bascule")
        print(f"  HAG [0.50:0.70m]      : {100*next_b:.2f} %  (bande suivante)")
        attn = "[ATTENTION accumulation]" if ratio > 2 else "[OK]"
        print(f"  Ratio bascule/suivante: {ratio:.2f}  {attn}")
        print(f"  Contamination flip/[0.30:3m] : {100*contamination:.1f} %")

        report.update({"hag_frac_below_30cm": round(float(np.mean(hag_v < 0.30)), 4),
                       "hag_frac_veg_band_30_3m": round(veg_band, 4),
                       "hag_frac_flip_zone": round(flip, 4),
                       "hag_frac_next_band": round(next_b, 4),
                       "hag_flip_ratio": round(ratio, 2),
                       "hag_contamination_flip_in_veg_band": round(contamination, 4)})

        if ratio > 2:
            verdict_fz = ("ATTENTION -- accumulation dans [0.30:0.50m] "
                          f"(ratio={ratio:.2f}) : bruit sol contamine la bande basse")
        else:
            verdict_fz = f"OK -- distribution HAG reguliere autour du seuil (ratio={ratio:.2f})"
        print(f"  Verdict : {verdict_fz}")
        report["verdict_flip_zone"] = verdict_fz

    # ── Rapport JSON ──────────────────────────────────────────────────────────
    print("\n[RESUME]")
    for k_r, v_r in report.items():
        if "verdict" in k_r:
            print(f"  {k_r}: {v_r}")

    if args.out_dir:
        out = pathlib.Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        name = pathlib.Path(tile).stem
        p = out / f"hag_feasibility_{name}.json"
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[JSON] -> {p}")


if __name__ == "__main__":
    main()
