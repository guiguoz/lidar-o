"""Sweep ordre / cascade du post-traitement raster — protocole L1.

Question (docs/pistes_raster_multipasses.md §4, levier L1) :
    l'ordre des operations non lineaires (gaussienne, mediane, normalisation p95,
    seuillage) a-t-il un effet mesurable, a operations et parametres constants ?

Ordre de production actuel (scripts/process_hag.py) :
    ratio -> gaussienne(sigma) -> mediane(size) -> normalisation p95_local -> seuils

Variantes comparees (meme sigma, meme noyau median de reference, memes seuils) :
    V0 gauss_med    : production (temoin)
    V1 med_gauss    : ordre inverse
    V2 med_med      : cascade de deux medianes demi-taille (KP fait exactement 2 tours)
    V3 gauss_med_med: une passe mediane supplementaire
    V4 norm_before  : normalisation p95 avant lissage, puis gauss_med sans renorm

Deux ordres de reference de la litterature, ajoutes en V5/V6 (cf.
docs/revue_plan_signaux_lidar.md) :

    V5 seuil_med    : seuiller le ratio brut, PUIS medianes 9 m et 16 m sur la
                      carte de classes — ordre de Karttapullautin
                      (medianboxsize/medianboxsize2 sur la teinte quantifiee)
    V6 seuil_morpho : seuiller, PUIS cascade morphologique progressive
                      closing/opening (7-3-9-5-11-7 px) — ordre de Trier 2015 §2.2

Metriques : metriques de forme (compacite, %trous, P/sqrtA) via src.qa, plus
quadruplet (n, mediane mm2, %<1mm2, part du plus grand composant 406).

Garde-fous : surface 406 non effondree, couverture non degradee de plus de 6 pp.

Usage :
    python scripts/diag/sweep_ordre_lissage.py
    python scripts/diag/sweep_ordre_lissage.py --save-dir temp/sweep_ordre
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

import numpy as np
import rasterio
from scipy.ndimage import gaussian_filter, median_filter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.qa import _shape_metrics  # noqa: E402  (pas de dependance osgeo a l'import)

HAG_TIF = ROOT / "output" / "density_hag.tif"
TOTAL_TIF = ROOT / "output" / "total_count.tif"
FFCO_GPKG = ROOT / "grimbosq.gpkg"   # optionnel : sans lui, pas de comparaison FFCO

SCALE = 10_000
MM2 = 1e6 / SCALE ** 2
CLASSES = [406, 408, 410]


# ── Entrees / sorties raster ─────────────────────────────────────────────────

def _load(path: pathlib.Path) -> tuple[np.ndarray, dict, np.ndarray]:
    """Retourne (tableau float32, profil, masque nodata)."""
    with rasterio.open(path) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        profile = ds.profile.copy()
    mask = (arr == nodata) if nodata is not None else np.zeros(arr.shape, dtype=bool)
    arr = np.where(mask, 0.0, arr)
    return arr, profile, mask


def _save(arr: np.ndarray, profile: dict, path: pathlib.Path, dtype: str, nodata) -> None:
    prof = profile.copy()
    prof.update(dtype=dtype, nodata=nodata, count=1)
    with rasterio.open(path, "w", **prof) as ds:
        ds.write(arr[np.newaxis, :, :].astype(dtype))


def _odd(px: float) -> int:
    n = int(round(px))
    if n % 2 == 0:
        n += 1
    return max(n, 3)


# ── Variantes d'ordre / cascade ──────────────────────────────────────────────

def build_variants(
    ratio: np.ndarray,
    mask: np.ndarray,
    res_m: float,
    sigma_m: float,
    median_m: float,
) -> dict[str, np.ndarray]:
    """Applique les 5 variantes d'ordre et retourne un champ normalise par variante.

    Toutes les variantes sortent un champ [0, 1] masque (0 hors emprise) pour
    pouvoir etre passees telles quelles au seuillage.

    L'ordre de production est gauss -> median -> norm (V0). V4 normalise AVANT
    le lissage et ne renormalise pas ensuite.
    """
    sigma_px = max(sigma_m / res_m, 0.5)
    med_px = _odd(median_m / res_m)
    med_half_px = _odd(max(median_m / res_m / 2.0, 1.5))

    field = np.where(mask, 0.0, ratio).astype(np.float64)

    def _gauss(a: np.ndarray) -> np.ndarray:
        return gaussian_filter(a, sigma=sigma_px)

    def _med(a: np.ndarray, k: int) -> np.ndarray:
        return median_filter(a, size=k)

    def _p95_norm(a: np.ndarray) -> np.ndarray:
        valid = a[~mask]
        vmax = float(np.percentile(valid, 95)) if valid.size else 1.0
        out = np.clip(a / vmax, 0.0, 1.0) if vmax > 1e-9 else np.clip(a, 0.0, 1.0)
        out[mask] = 0.0
        return out

    out: dict[str, np.ndarray] = {}
    out["V0_gauss_med"] = _p95_norm(_med(_gauss(field), med_px))
    out["V1_med_gauss"] = _p95_norm(_gauss(_med(field, med_px)))
    out["V2_med_med"] = _p95_norm(_med(_med(field, med_half_px), med_half_px))
    out["V3_gauss_med_med"] = _p95_norm(_med(_med(_gauss(field), med_px), med_px))
    normed_first = _p95_norm(field)
    out["V4_norm_before"] = _med(_gauss(normed_first), med_px)
    out["V4_norm_before"][mask] = 0.0
    return out


def classify(
    normed: np.ndarray,
    mask: np.ndarray,
    thresholds: tuple[float, float, float],
) -> np.ndarray:
    """Seuillage simple identique a process_hag : 85/170/255, 0 ailleurs."""
    t406, t408, t410 = thresholds
    cls = np.zeros(normed.shape, dtype=np.uint8)
    cls[normed > t406] = 85
    cls[normed > t408] = 170
    cls[normed > t410] = 255
    cls[mask] = 0
    return cls


# ── Deux ordres de reference : seuiller PUIS filtrer ─────────────────────────

def _disk(radius: int) -> "np.ndarray":
    """Disque binaire (structure morphologique), scipy n'en fournit pas."""
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    return (yy ** 2 + xx ** 2) <= radius ** 2


def classify_threshold_then_filter(
    ratio: np.ndarray,
    mask: np.ndarray,
    thresholds: tuple[float, float, float],
    res_m: float,
    medians_m: tuple[float, float] = (9.0, 16.0),
) -> np.ndarray:
    """Ordre KP : seuiller d'abord, filtrer median ensuite (carte de classes).

    Le ratio BRUT est normalise par son p95 (sur les pixels valides), seuille aux
    seuils de production, PUIS la carte de classes est passee dans deux medianes
    successifs de 9 m et 16 m — transposition de `medianboxsize=9` et
    `medianboxsize2=16` de KP, qui appliquent ces filtres a l'image de teintes
    deja quantifiee (src/vegetation.rs : median_filter apres le seuillage
    `greenshades`).

    Note : normaliser le ratio brut par son p95 n'est pas exactement ce que fait
    la production (qui normalise le champ lisse). C'est la seule normalisation
    definie dans cet ordre ; le comparateur teste donc « seuiller puis medianer »
    a normalisation honnete, pas une equivalence bit a bit.
    """
    valid = ratio[~mask]
    vmax = float(np.percentile(valid, 95)) if valid.size else 1.0
    normed = np.clip(ratio / vmax, 0.0, 1.0) if vmax > 1e-9 else np.clip(ratio, 0.0, 1.0)
    normed[mask] = 0.0
    cls = classify(normed, mask, thresholds)

    for med_m in medians_m:
        k = _odd(med_m / res_m)
        if k > 1:
            cls = median_filter(cls, size=k).astype(np.uint8)
    cls[mask] = 0
    return cls


# Cascade morphologique de Trier (2015 §2.2), en pixels a 1 m :
# closing 7 -> opening 3 -> closing 9 -> opening 5 -> closing 11 -> opening 7.
# Trier alterne fermetures et ouvertures de taille croissante : la fermeture
# connecte les taches proches, l'ouverture qui suit re-retire ce qui est plus
# fin que le noyau, donc le signal faible est exagere sans etre invente.
TRIER_CASCADE: tuple[tuple[str, int], ...] = (
    ("closing", 7), ("opening", 3),
    ("closing", 9), ("opening", 5),
    ("closing", 11), ("opening", 7),
)


def _apply_cascade(binary: np.ndarray, res_m: float,
                   cascade: tuple[tuple[str, int], ...] = TRIER_CASCADE) -> np.ndarray:
    """Applique une cascade (operation, noyau en metres) a un masque binaire."""
    from scipy.ndimage import binary_closing, binary_opening

    out = binary
    for op, kernel_m in cascade:
        # Taille de noyau impaire (7, 3, 9, 5, 11, 7 px) : rayon = taille // 2,
        # ce qui reproduit exactement les noyaux de Trier 2015 (§2.2).
        size_px = max(int(round(kernel_m / res_m)), 3)
        if size_px % 2 == 0:
            size_px += 1
        struct = _disk(size_px // 2)
        out = binary_closing(out, structure=struct) if op == "closing" \
            else binary_opening(out, structure=struct)
    return out


def classify_threshold_then_morphology(
    ratio: np.ndarray,
    mask: np.ndarray,
    thresholds: tuple[float, float, float],
    res_m: float,
    cascade: tuple[tuple[str, int], ...] = TRIER_CASCADE,
) -> np.ndarray:
    """Ordre Trier : seuiller d'abord, puis generaliser par morphologie progressive.

    Les trois classes sont traitees separement puis recomposees de la plus
    severe a la moins severe (410 > 408 > 406), ce qui garde l'imbrication
    naturelle des seuils. C'est la transposition de la methode 2.2 de
    Trier 2015 (closing/opening alternes de taille croissante).
    """
    valid = ratio[~mask]
    vmax = float(np.percentile(valid, 95)) if valid.size else 1.0
    normed = np.clip(ratio / vmax, 0.0, 1.0) if vmax > 1e-9 else np.clip(ratio, 0.0, 1.0)
    normed[mask] = 0.0
    raw = classify(normed, mask, thresholds)

    out = np.zeros_like(raw)
    assigned = np.zeros(raw.shape, dtype=bool)
    for value in (255, 170, 85):          # severe -> leger
        binary = (raw == value) & ~assigned
        if not binary.any():
            continue
        kept = _apply_cascade(binary, res_m, cascade)
        out[kept] = value
        assigned |= kept
    out[mask] = 0
    return out


# ── Metriques ────────────────────────────────────────────────────────────────

_RAW_VALUE = {406: 85, 408: 170, 410: 255}


def raster_metrics(cls: np.ndarray, cls_id: int, res_m: float) -> dict[str, float]:
    """Surface raster d'une classe (%, ha) + part du plus grand composant connexe.

    La part du plus grand composant est le garde-fou de percolation deja utilise
    dans le bilan (« max%406 ») : elle est ici mesuree AVANT vectorisation.
    """
    from scipy.ndimage import label as _ndlabel

    px_m2 = res_m ** 2
    binary = cls == _RAW_VALUE[cls_id]
    n_px = int(binary.sum())
    total_px = int((cls != 0).sum())
    if n_px == 0:
        return {"pct": 0.0, "ha": 0.0, "max_comp_pct": 0.0}
    labels, _ = _ndlabel(binary, structure=np.ones((3, 3), dtype=int))
    sizes = np.bincount(labels.ravel())
    biggest = int(sizes[1:].max()) if sizes.size > 1 else n_px
    return {
        "pct": 100.0 * n_px / total_px if total_px else 0.0,
        "ha": n_px * px_m2 / 10_000,
        "max_comp_pct": 100.0 * biggest / n_px,
    }


def vector_metrics(gdf, cls: int) -> dict[str, float]:
    """Quadruplet vecteur : n, mediane m2, %<1mm2, part du plus grand composant."""
    sub = gdf[gdf["class"] == cls]
    if sub.empty:
        return {"n": 0.0, "med_mm2": 0.0, "pct_lt1mm2": 0.0, "max_share_pct": 0.0}
    areas = np.asarray(sub.geometry.area, dtype=float)
    mm2 = areas * MM2
    return {
        "n": float(len(sub)),
        "med_mm2": float(np.median(mm2)),
        "pct_lt1mm2": float((mm2 < 1.0).mean() * 100.0),
        "max_share_pct": float(areas.max() / areas.sum() * 100.0) if areas.sum() else 0.0,
    }


# ── Programme principal ──────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hag", type=pathlib.Path, default=HAG_TIF)
    ap.add_argument("--total", type=pathlib.Path, default=TOTAL_TIF)
    ap.add_argument("--save-dir", type=pathlib.Path, default=None,
                    help="ecrit les rasters classifies de chaque variante")
    args = ap.parse_args()

    for p in (args.hag, args.total):
        if not p.exists():
            sys.exit(f"ABSENT : {p}\n  (sweep L1 requis apres un run complet, cf. README)")

    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    veg = cfg["vegetation"]
    preset = veg["presets"][veg["active_preset"]]
    thresholds = tuple(float(t) for t in preset["thresholds"])
    if preset.get("thresholds_low"):
        print("ATTENTION : hysteresis activee dans le preset — le sweep seuille en dur.")
    ph = veg.get("process_hag", {})
    sigma_m = float(ph.get("gaussian_sigma", 1.0))
    median_m = float(ph.get("median_size", 9))

    hag, profile, mask_hag = _load(args.hag)
    total, _, mask_total = _load(args.total)
    res_m = abs(profile["transform"].a)

    mask = mask_hag | mask_total | (total <= 0)
    ratio = np.where(mask, 0.0, np.divide(hag, total, out=np.zeros_like(hag), where=total > 0))

    print(f"Sweep ordre/cascade — sigma={sigma_m} m  mediane={median_m} m  "
          f"seuils={thresholds}  res={res_m:.2f} m")
    print(f"Champ : {mask.size - mask.sum()} px valides sur {mask.size}\n")

    variants = build_variants(ratio, mask, res_m, sigma_m, median_m)
    class_orders: dict[str, np.ndarray] = {
        "V5_seuil_med_med": classify_threshold_then_filter(ratio, mask, thresholds, res_m),
        "V6_seuil_morpho": classify_threshold_then_morphology(ratio, mask, thresholds, res_m),
    }

    # Changement effectif de chaque variante vs V0 (avant vectorisation)
    print("Ecarts raster vs V0 (avant vectorisation) :")
    for name, field in variants.items():
        if name == "V0_gauss_med":
            continue
        diff = np.abs(field - variants["V0_gauss_med"])[~mask]
        frac = float((diff > 0.05).mean() * 100.0) if diff.size else 0.0
        print(f"  {name:<18} |ecart| med={np.median(diff):.4f}  "
              f"p95={np.percentile(diff, 95):.4f}  cellules>0.05={frac:.1f}%")
    print()

    from src.vegetation import run_pipeline  # import tardif (osgeo/gdal requis)

    hdr = (f"{'variante':<18} {'classe':>6} {'cov%':>6} {'maxC%':>6} {'n':>6} {'med_mm2':>8} "
           f"{'%<1mm2':>7} {'compact':>8} {'%trous':>7} {'P/sqrtA':>8}")
    print(hdr)
    print("-" * len(hdr))

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="sweep_ordre_"))
    save_dir = args.save_dir
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    order_rows: list[tuple[str, np.ndarray]] = [
        (name, classify(field, mask, thresholds)) for name, field in variants.items()
    ]
    order_rows += list(class_orders.items())

    for name, cls in order_rows:
        tif = tmpdir / f"{name}.tif"
        _save(cls, profile, tif, "uint8", 0)
        if save_dir:
            _save(cls, profile, save_dir / f"{name}.tif", "uint8", 0)

        gdf, _ = run_pipeline(str(tif), cfg)
        for c in CLASSES:
            vm = vector_metrics(gdf, c)
            rm = raster_metrics(cls, c, res_m)
            sh = _shape_metrics(gdf, None, c)
            print(f"{name:<18} {c:>6} "
                  f"{rm['pct']:>6.1f} {rm['max_comp_pct']:>6.1f} {vm['n']:>6.0f} "
                  f"{vm['med_mm2']:>8.2f} {vm['pct_lt1mm2']:>7.1f} "
                  f"{sh['compacity_med']:>8.3f} {sh['pct_holed']:>7.1f} "
                  f"{sh['peri_over_sqrtarea_med']:>8.2f}")
        sys.stdout.flush()

    print()
    print("V5 = ordre KP (seuiller puis medianer) — V6 = ordre Trier (seuiller")
    print("puis cascade morphologique progressive). Voir review pour les sources.")
    print()
    print("Lecture : comparer chaque variante a V0 (production) ligne a ligne.")
    print("  Go    : compacite mediane en hausse, %<1mm2 stable, part max 406 stable.")
    print("  No-go : gain de compacite accompagne d'une perte de couverture > 6 pp,")
    print("          ou %<1mm2 en hausse (fragmentation accrue).")
    print(f"\nRasters temporaires : {tmpdir}")


if __name__ == "__main__":
    main()
