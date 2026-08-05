"""D2 — Vérification densité points LiDAR par cellule (PLAN_vegetation_406.md §D2).

À lancer en TOUT PREMIER, avant les expériences A/B/C/D, sur les rasters
déjà produits par PDAL. Prend < 1 min.

Mesure le nombre de retours par cellule de 1 m dans :
  - la bande HAG [0.3–3 m]      (density_hag.tif)
  - tous les retours             (total_count.tif)

Sortie : statistiques en console + histogramme optionnel.

Usage :
    py -3.14 scripts/diag_point_density.py --hag output_grimbosq/density_hag.tif
    py -3.14 scripts/diag_point_density.py \\
        --hag output_grimbosq/density_hag.tif \\
        --total output_grimbosq/total_count.tif \\
        --hist rapports/diag_density.png
"""
from __future__ import annotations

import argparse
import pathlib
import sys

# Force UTF-8 sur Windows (terminal cp1252 ne peut pas afficher les caractères étendus)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import rasterio
from rasterio.enums import Resampling


def _load_valid(path: pathlib.Path) -> np.ndarray:
    """Charge un raster et retourne les valeurs non-nodata (1-D)."""
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        res = abs(ds.transform.a)
    if nodata is not None:
        arr[arr == nodata] = np.nan
    valid = arr[~np.isnan(arr)]
    print(f"  Résolution native : {res} m")
    print(f"  Cellules totales  : {arr.size:,}  |  valides : {valid.size:,} ({valid.size/arr.size:.1%})")
    return valid


def _stats(label: str, values: np.ndarray) -> None:
    """Affiche les percentiles clés."""
    if values.size == 0:
        print(f"  {label} : (aucune valeur)")
        return
    pcts = [0, 5, 25, 50, 75, 90, 95, 99, 100]
    vals = np.percentile(values, pcts)
    print(f"\n  {label}")
    print(f"  {'pct':>4}  {'retours/cellule':>15}")
    print(f"  {'-'*22}")
    for p, v in zip(pcts, vals):
        marker = "  <- mediane" if p == 50 else ("  <- p95" if p == 95 else "")
        print(f"  {p:>4}  {v:>15.1f}{marker}")

    # Proportion de cellules avec très peu de points
    for thresh in [0, 1, 4, 8, 16]:
        frac = np.mean(values <= thresh)
        tag = "  <- n_min NRD" if thresh == 8 else ""
        print(f"  <={thresh:>2} retours : {frac:.1%}{tag}")


def _hist(hag: np.ndarray, total: np.ndarray | None, out_path: pathlib.Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[INFO] matplotlib absent — histogramme ignoré (pip install matplotlib).")
        return

    fig, axes = plt.subplots(1, 2 if total is not None else 1, figsize=(12, 4))
    if total is None:
        axes = [axes]

    cap_hag = float(np.percentile(hag, 99))
    axes[0].hist(hag[hag <= cap_hag], bins=60, edgecolor="k", alpha=0.7, color="steelblue")
    axes[0].set_title(f"HAG [0.3–3 m] — retours/cellule\n(n={len(hag):,}, médiane={np.median(hag):.1f})")
    axes[0].set_xlabel("Retours / cellule")
    axes[0].axvline(np.median(hag), color="red", lw=1.5, label="médiane")
    axes[0].axvline(8, color="orange", lw=1.5, ls="--", label="n_min=8 (NRD)")
    axes[0].legend(fontsize=8)

    if total is not None:
        cap_tot = float(np.percentile(total, 99))
        axes[1].hist(total[total <= cap_tot], bins=60, edgecolor="k", alpha=0.7, color="seagreen")
        axes[1].set_title(f"Total retours — retours/cellule\n(n={len(total):,}, médiane={np.median(total):.1f})")
        axes[1].set_xlabel("Retours / cellule")
        axes[1].axvline(np.median(total), color="red", lw=1.5, label="médiane")
        axes[1].legend(fontsize=8)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"\n[HISTO] -> {out_path}")


def _aggregate_raster(path: pathlib.Path, factor: int) -> np.ndarray:
    """Ré-agrège par somme de blocs factor×factor (comptage physiquement correct).

    Utilise numpy reshape — plus rapide que rasterio warp pour des tests rapides.
    """
    if factor == 1:
        return _load_valid(path)

    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        nodata = src.nodata

    if nodata is not None:
        data[data == nodata] = 0.0  # nodata → 0 pour la somme (hors couverture)

    # Tronquer aux dimensions multiples de factor
    h = (data.shape[0] // factor) * factor
    w = (data.shape[1] // factor) * factor
    data = data[:h, :w]

    # Somme par blocs factor×factor via reshape
    aggregated = (
        data.reshape(h // factor, factor, w // factor, factor)
        .sum(axis=(1, 3))
    )
    return aggregated.astype(np.float32)


def _stats_at_res(hag_path: pathlib.Path, res_m: int, n_min: int = 8) -> None:
    """Affiche les stats HAG a la resolution cible (aggregation par somme)."""
    with rasterio.open(hag_path) as src:
        src_res = abs(src.transform.a)
    factor = round(res_m / src_res)
    if factor <= 0:
        return

    arr = _aggregate_raster(hag_path, factor)
    valid = arr[~np.isnan(arr) & (arr >= 0)]

    median_v = float(np.median(valid)) if valid.size > 0 else 0.0
    frac_below = float(np.mean(valid <= n_min)) if valid.size > 0 else 1.0
    p95_v = float(np.percentile(valid, 95)) if valid.size > 0 else 0.0

    print(f"  {res_m}m  mediane={median_v:6.1f}  p95={p95_v:6.1f}  "
          f"<= n_min({n_min})={frac_below:.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="D2 — Diagnostic densité LiDAR par cellule"
    )
    parser.add_argument("--hag", required=True,
                        help="Raster HAG [0.3-3 m] (density_hag.tif)")
    parser.add_argument("--total", default=None,
                        help="Raster total retours (total_count.tif) -- optionnel")
    parser.add_argument("--hist", default=None,
                        help="Chemin PNG pour histogramme (ex: rapports/diag_density.png)")
    parser.add_argument("--resolutions", nargs="+", type=int, default=[1, 2, 3, 4],
                        help="Resolutions a tester par agregation (defaut: 1 2 3 4)")
    parser.add_argument("--n-min", type=int, default=8,
                        help="Seuil n_min NRD (defaut: 8)")
    args = parser.parse_args()

    hag_path = pathlib.Path(args.hag)
    if not hag_path.exists():
        print(f"[ERREUR] Fichier introuvable : {hag_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f" D2 -- Densite LiDAR par cellule")
    print(f"{'='*55}")
    print(f"\n[HAG] {hag_path}")
    hag = _load_valid(hag_path)
    _stats("HAG [0.3-3 m]  retours/cellule 1 m", hag)

    total: np.ndarray | None = None
    if args.total:
        total_path = pathlib.Path(args.total)
        if total_path.exists():
            print(f"\n[TOTAL] {total_path}")
            total = _load_valid(total_path)
            _stats("Total retours  retours/cellule 1 m", total)

            # Cellules total=0 (hors empreinte LiDAR ou surface d eau)
            with rasterio.open(total_path) as dst:
                at_raw = dst.read(1).astype(np.float32)
                nd_t = dst.nodata
            zero_total = np.sum((at_raw == 0) & ((nd_t is None) or (at_raw != nd_t)))
            frac_zero = zero_total / at_raw.size
            print(f"\n  Cellules total=0 (hors couverture / surface d'eau) : "
                  f"{zero_total:,} ({frac_zero:.1%})")
            if frac_zero > 0.05:
                print(f"  --> Verifier si l'emprise contient un plan d'eau ou des bords de dalle.")
                print(f"  Ces cellules sont masquees en mode ratio/nrd (correction appliquee).")

            # Ratio HAG/total (cellules avec total > 0 uniquement)
            with rasterio.open(hag_path) as dsh:
                ah = dsh.read(1).astype(np.float32)
                nd_h = dsh.nodata
            r = min(ah.shape[0], at_raw.shape[0])
            c = min(ah.shape[1], at_raw.shape[1])
            ah, at = ah[:r, :c], at_raw[:r, :c]
            valid_mask = (at > 0)
            if nd_h is not None:
                valid_mask &= (ah != nd_h)
            if nd_t is not None:
                valid_mask &= (at != nd_t)
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio = np.where(valid_mask, ah / at, np.nan)
            ratio_valid = ratio[~np.isnan(ratio)]
            print(f"\n  Ratio HAG/total sur cellules valides (n={ratio_valid.size:,}) :")
            print(f"  mediane={np.median(ratio_valid):.4f}  "
                  f"p95={np.percentile(ratio_valid, 95):.4f}  "
                  f"max={ratio_valid.max():.4f}")
        else:
            print(f"[AVERT] {total_path} introuvable -- stats total ignorees.", file=sys.stderr)

    # Agregation multi-resolution (mesure directe, pas d'extrapolation lineaire)
    n_min_values = sorted(set([args.n_min, 4, 8, 16]))  # sweep automatique
    print(f"\n{'-'*55}")
    print(f" Agregation HAG par somme de blocs -- taux < n_min (mesure directe) :")
    header = f"  {'res':>4}  {'mediane':>8}  {'p95':>8}" + "".join(
        f"  <n={n:>2}" for n in n_min_values
    )
    print(header)
    print(f"  {'-'*4}  {'-'*8}  {'-'*8}" + "  ------" * len(n_min_values))

    for res in sorted(set(args.resolutions)):
        with rasterio.open(hag_path) as src:
            src_res = abs(src.transform.a)
        factor = round(res / src_res)
        if factor <= 0:
            continue
        arr = _aggregate_raster(hag_path, factor)
        valid = arr[~np.isnan(arr) & (arr >= 0)]
        if valid.size == 0:
            continue
        med = float(np.median(valid))
        p95_v = float(np.percentile(valid, 95))
        fracs = "".join(f"  {np.mean(valid <= n):>5.1%}" for n in n_min_values)
        print(f"  {res:>4}m  {med:>8.1f}  {p95_v:>8.1f}{fracs}")

    # Interpretation NRD
    median_hag = float(np.median(hag[hag >= 0])) if hag.size > 0 else 0.0
    frac_below_nmin = float(np.mean(hag[hag >= 0] <= args.n_min)) if hag.size > 0 else 1.0
    print(f"\n{'-'*55}")
    print(f" Interpretation NRD a 1 m :")
    print(f"  NOTE : n_min s'applique aux impulsions PENETRANTES (bande + sol),")
    print(f"         pas au total retours. Avec mediane HAG={median_hag:.1f}, n_min=8")
    print(f"         est ELEVE relativement au signal disponible.")
    if frac_below_nmin > 0.5:
        print(f"  {frac_below_nmin:.1%} des cellules < n_min={args.n_min} a 1 m.")
        print(f"  Le fill (rayon ~5m) domine le signal : NRD@1m mesure du lissage,")
        print(f"  pas directement la formule NRD. delta_1 dans le plan factoriel")
        print(f"  reflete 'fill NRD vs fill ratio', pas 'formule NRD vs formule ratio'.")
        print(f"  --> Etape A prioritaire. Voir agregation ci-dessus pour choisir RES_nrd.")
    elif frac_below_nmin > 0.3:
        print(f"  {frac_below_nmin:.1%} des cellules < n_min={args.n_min} a 1 m.")
        print(f"  NRD partiellement domine par le fill -- voir agregation.")
    else:
        print(f"  {frac_below_nmin:.1%} des cellules < n_min={args.n_min} a 1 m.")
        print(f"  Signal NRD majoritairement direct (fill minoritaire).")

    # Critere de qualite corpus (pertinent si total disponible)
    if args.total and pathlib.Path(args.total).exists():
        with rasterio.open(pathlib.Path(args.total)) as dst:
            at_raw = dst.read(1).astype(np.float32)
            nd_t = dst.nodata
        if nd_t is not None:
            at_raw[at_raw == nd_t] = 0.0
        frac_zero_total = float(np.mean(at_raw <= 0))
        print(f"\n  Couverture LiDAR : {(1-frac_zero_total):.1%} de l'emprise.")
        if frac_zero_total > 0.10:
            print(f"  ATTENTION : {frac_zero_total:.1%} hors couverture (total=0).")
            print(f"  Critere de decision terrain : si l'emprise exploitable apres masquage")
            print(f"  est trop petite ou fragmentee, exclure ce terrain du corpus pour")
            print(f"  cette serie de tests -- des IoU sur emprise residuelle biaisee sont")
            print(f"  moins fiables qu'un corpus a n=1 (Grimbosq seul) bien maitrise.")
            print(f"  Isoler geographiquement les zones sans couverture avant de conclure.")
    print(f"{'-'*55}\n")

    if args.hist:
        _hist(hag, total, pathlib.Path(args.hist))


if __name__ == "__main__":
    main()
