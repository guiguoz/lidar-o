"""Analyse comparative des rasters vegetation KP — experiences A / B / C.

Usage :
    python scripts/analyse_vege_abc.py [--out results_vege_abc.json]

Ce script utilise directement les fonctions de production de src/kp_raster.py
pour garantir que le decodage de la palette et le mapping shade->ISOM sont
identiques a ceux utilises par le pipeline. Aucune palette codee en dur.

Parcelle cible NE (bois trapezoidale nord-est de la dalle) :
    bbox Lambert 93 : [425550, 6922660, 425920, 6923000]
    pixels (dans le *_vege.png 1000x1000) : rows 0:340, cols 550:920
    surface : 12.58 ha

Corrections par rapport a la version precedente :
- shade 2 (teinte la plus claire) mappe a ISOM 0 (foret courable), pas 406
- pourcentage correct : pixels_verts / total_px * 100
- connexite 4 ET 8 mesurees separement
- pixels inconnus signales explicitement (pas silencieusement ignores)
- verification que blanc+jaune+vertsISOM+vert0+inconnus = total
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.kp_raster import (
    KP_FIRST_GREEN,
    KP_NO_DATA,
    KP_YELLOW,
    _UNMATCHED,
    _rgb_lookup,
    kp_green_rgb,
    read_ini_vege_params,
)

log = logging.getLogger(__name__)

# ── Parcelle cible NE ─────────────────────────────────────────────────────────
# Bois trapezoidale nord-est de la dalle bois_dupont.
# Delimite par densite verte sur grille 50m × 50m (voir scripts/analyse_vege_abc.py).
# Incertitude : frontiere a ±50 m sur les bords sud et ouest.
PARCEL_ROW0, PARCEL_ROW1 = 0, 340    # ligne 0 = Y=6923000
PARCEL_COL0, PARCEL_COL1 = 550, 920  # col 550 = X=425550
PARCEL_BBOX = (425550, 6922660, 425920, 6923000)  # Lambert 93

# ── Experiences ───────────────────────────────────────────────────────────────
BASE = pathlib.Path("out_kp_bois_dupont")
LAZ  = "LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz"

EXPERIMENTS: dict[str, dict] = {
    "A_med9-16_t01": {
        "vege_png":   BASE / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "pullauta.ini",
        "label": "A — med9/16 thresold=0.1",
    },
    "B_med1-1_t01": {
        "vege_png":   BASE / "test"  / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "test" / "pullauta.ini",
        "label": "B — med1/1 thresold=0.1",
    },
    "C_med1-1_t02": {
        "vege_png":   BASE / "exp_c" / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "exp_c" / "pullauta.ini",
        "label": "C — med1/1 thresold=0.2",
    },
}


# ── shade_to_isom depuis config.yaml ─────────────────────────────────────────

def load_shade_to_isom() -> dict[int, int]:
    """Charge shade_to_isom depuis config.yaml.

    C'est la meme table que le pipeline de production.
    Leve ValueError si absente.
    """
    import yaml
    cfg_path = pathlib.Path("config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError("config.yaml introuvable")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {}).get("shade_to_isom") or {}
    if not raw:
        raise ValueError("karttapullautin.vectorization.shade_to_isom absent de config.yaml")
    return {int(k): int(v) for k, v in raw.items()}


# ── Decode PNG en labels KP ───────────────────────────────────────────────────

def decode_png(png_path: pathlib.Path, ini_path: pathlib.Path) -> tuple[np.ndarray, dict]:
    """PNG *_vege.png -> tableau de labels KP (0=blanc, 1=jaune, 2+i=vert i).

    Utilise la palette recalculee par kp_green_rgb (src/kp_raster.py).
    Toute couleur hors palette est enregistree dans le rapport et levee en
    erreur si elle represente plus de 0 pixel (pas de tolerance silencieuse).
    """
    params = read_ini_vege_params(ini_path)
    lut = _rgb_lookup(params)

    arr = np.array(Image.open(png_path).convert("RGB"))
    h, w = arr.shape[:2]
    rgb = arr.astype(np.int32)

    uniq, inv = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    table = np.full(len(uniq), _UNMATCHED, dtype=np.uint8)
    unknown: list[tuple[int, int, int]] = []
    for k, color in enumerate(uniq):
        key = (int(color[0]), int(color[1]), int(color[2]))
        if key in lut:
            table[k] = lut[key]
        else:
            unknown.append(key)

    labels = table[inv.reshape(h, w)]
    n_unknown = int(np.sum(labels == _UNMATCHED))

    # Verification bilan complet
    n_blanc  = int(np.sum(labels == KP_NO_DATA))
    n_jaune  = int(np.sum(labels == KP_YELLOW))
    n_verifiable = n_blanc + n_jaune + n_unknown
    for shade in range(KP_FIRST_GREEN, KP_FIRST_GREEN + params["n_shades"]):
        n_verifiable += int(np.sum(labels == shade))
    if n_verifiable != h * w:
        raise ValueError(
            f"{png_path.name}: bilan pixels incomplet "
            f"({n_verifiable} != {h*w}) — labels corrompus"
        )

    meta = {
        "path":        str(png_path.resolve()),
        "sha256":      hashlib.sha256(png_path.read_bytes()).hexdigest(),
        "mode":        "RGB",
        "size":        (w, h),
        "n_shades":    params["n_shades"],
        "lightgreentone": params["lightgreentone"],
        "ini_path":    str(ini_path.resolve()),
        "n_unknown":   n_unknown,
        "unknown_colors": [list(c) for c in unknown[:10]],
        "palette_ok":  n_unknown == 0,
    }

    if n_unknown > 0:
        raise ValueError(
            f"{png_path.name}: {n_unknown} pixels ({100*n_unknown/(h*w):.3f}%) "
            f"hors palette KP (n_shades={params['n_shades']}, tone={params['lightgreentone']}) "
            f"— couleurs inconnues: {unknown[:5]}"
        )

    return labels, meta


# ── PGW ───────────────────────────────────────────────────────────────────────

def read_pgw(pgw_path: pathlib.Path) -> dict:
    """Lit un worldfile et calcule la surface du pixel en m²."""
    if not pgw_path.exists():
        raise FileNotFoundError(f"PGW absent : {pgw_path}")
    vals = [float(l.strip()) for l in pgw_path.read_text().splitlines() if l.strip()]
    if len(vals) < 6:
        raise ValueError(f"PGW invalide ({len(vals)} lignes) : {pgw_path}")
    A, D, B, E, C, F = vals
    pixel_m2 = abs(A * E - B * D)
    return {"A": A, "D": D, "B": B, "E": E, "C": C, "F": F,
            "pixel_m2": pixel_m2, "res_m": abs(A)}


# ── Statistiques de surface ───────────────────────────────────────────────────

def surface_stats(
    labels: np.ndarray,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
    mask: np.ndarray | None = None,
) -> dict:
    """Surfaces en ha et pourcentages par classe pour un raster (ou une zone).

    Comptabilisation :
        blanc (shade 0) + jaune (shade 1) + vert_isom0 (shade 2, ISOM 0)
        + ISOM 406 + ISOM 408 + ISOM 410 + inconnus = total_px

    Pourcentage de couverture verte :
        pct_vert_total = (px_406 + px_408 + px_410) / px_total * 100
        pct_vert_sur_nonjaune = (px_406 + px_408 + px_410) / (px_total - px_jaune) * 100
    """
    if mask is not None:
        labels = labels[mask]

    total_px = labels.size
    ha = pixel_m2 / 10_000.0

    # Par shade
    by_shade: dict[int, int] = {}
    for shade in [KP_NO_DATA, KP_YELLOW] + list(range(KP_FIRST_GREEN, KP_FIRST_GREEN + 12)):
        n = int(np.sum(labels == shade))
        if n:
            by_shade[shade] = n

    # Par classe ISOM (shade -> ISOM via shade_to_isom)
    by_isom: dict[int | str, int] = {"0_vert": 0, 406: 0, 408: 0, 410: 0, "inconnu": 0}
    for shade in range(KP_FIRST_GREEN, KP_FIRST_GREEN + 12):
        n = by_shade.get(shade, 0)
        if n == 0:
            continue
        isom = shade_to_isom.get(shade)
        if isom is None:
            # shade existant non mappe : signale comme inconnu
            by_isom["inconnu"] += n
        elif isom == 0:
            by_isom["0_vert"] += n
        elif isom in (406, 408, 410):
            by_isom[isom] += n
        else:
            by_isom["inconnu"] += n

    n_blanc   = by_shade.get(KP_NO_DATA, 0)
    n_jaune   = by_shade.get(KP_YELLOW, 0)
    n_vert0   = by_isom["0_vert"]
    n_406     = by_isom[406]
    n_408     = by_isom[408]
    n_410     = by_isom[410]
    n_inconnu = by_isom["inconnu"]
    n_vert    = n_406 + n_408 + n_410

    # Verification bilan
    bilan = n_blanc + n_jaune + n_vert0 + n_vert + n_inconnu
    if bilan != total_px:
        raise ValueError(
            f"Bilan incomplet : {bilan} != {total_px} "
            f"(blanc={n_blanc} jaune={n_jaune} vert0={n_vert0} "
            f"406={n_406} 408={n_408} 410={n_410} inconnu={n_inconnu})"
        )

    def pct(n): return round(100.0 * n / total_px, 4)
    def h(n):   return round(n * ha, 4)

    return {
        "total_px":      total_px,
        "pixel_m2":      pixel_m2,
        "px_blanc":      n_blanc,  "ha_blanc":      h(n_blanc),  "pct_blanc":      pct(n_blanc),
        "px_jaune":      n_jaune,  "ha_jaune":      h(n_jaune),  "pct_jaune":      pct(n_jaune),
        "px_vert0":      n_vert0,  "ha_vert0":      h(n_vert0),  "pct_vert0":      pct(n_vert0),
        "px_406":        n_406,    "ha_406":         h(n_406),   "pct_406":        pct(n_406),
        "px_408":        n_408,    "ha_408":         h(n_408),   "pct_408":        pct(n_408),
        "px_410":        n_410,    "ha_410":         h(n_410),   "pct_410":        pct(n_410),
        "px_vert":       n_vert,   "ha_vert":        h(n_vert),  "pct_vert":       pct(n_vert),
        "pct_vert_sur_nonjaune": round(100.0 * n_vert / (total_px - n_jaune), 4)
                                  if (total_px - n_jaune) > 0 else 0.0,
        "px_inconnu":   n_inconnu, "ha_inconnu":    h(n_inconnu),
    }


# ── Composantes connexes ──────────────────────────────────────────────────────

def cc_stats(
    labels: np.ndarray,
    isom_code: int,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
    connectivity: int = 4,
    mask: np.ndarray | None = None,
) -> dict:
    """Statistiques de composantes connexes pour une classe ISOM.

    connectivity : 4 (structure en croix) ou 8 (structure carree).
    Les composantes tronquees par le bord du masque sont identifiees
    (composantes touchant la frontiere du masque ou du raster).

    Retourne n_cc, mediane_m2, moyenne_m2, max_m2 sur les composantes
    entieres. Signale le nombre de composantes tronquees separement.
    """
    if mask is not None:
        work = np.zeros_like(labels, dtype=bool)
        work[mask] = True
    else:
        work = np.ones_like(labels, dtype=bool)

    # Masque de la classe ISOM : shades ayant shade_to_isom[shade] == isom_code
    class_mask = np.zeros_like(labels, dtype=bool)
    for shade, isom in shade_to_isom.items():
        if isom == isom_code:
            class_mask |= (labels == shade)
    if mask is not None:
        class_mask &= work

    struct = np.ones((3, 3), dtype=int) if connectivity == 8 else ndimage.generate_binary_structure(2, 1)
    labeled, n_total = ndimage.label(class_mask, structure=struct)

    if n_total == 0:
        return {
            "connectivity": connectivity, "isom": isom_code,
            "n_cc": 0, "n_cc_border": 0, "n_cc_interior": 0,
            "median_m2": 0.0, "mean_m2": 0.0, "max_m2": 0.0,
        }

    sizes = ndimage.sum(class_mask, labeled, range(1, n_total + 1))

    # Composantes touchant le bord (tronquees)
    border_ids = set()
    # Bords du raster ou du masque
    border_labels = set()
    border_labels.update(labeled[0, :].ravel())
    border_labels.update(labeled[-1, :].ravel())
    border_labels.update(labeled[:, 0].ravel())
    border_labels.update(labeled[:, -1].ravel())
    if mask is not None:
        # Bords du masque : pixels dans mask mais adjacents a ~mask
        mask_interior = ndimage.binary_erosion(work, structure=struct)
        mask_border = work & ~mask_interior
        border_labels.update(labeled[mask_border].ravel())
    border_ids = border_labels - {0}
    n_border = len(border_ids)

    interior_sizes = [float(sizes[i-1]) for i in range(1, n_total+1) if i not in border_ids]

    ha = pixel_m2 / 10_000.0
    return {
        "connectivity":  connectivity,
        "isom":          isom_code,
        "n_cc":          n_total,
        "n_cc_border":   n_border,
        "n_cc_interior": len(interior_sizes),
        "median_m2":     round(float(np.median(interior_sizes)) * pixel_m2, 2) if interior_sizes else 0.0,
        "mean_m2":       round(float(np.mean(interior_sizes)) * pixel_m2, 2) if interior_sizes else 0.0,
        "max_m2":        round(float(max(interior_sizes)) * pixel_m2, 2) if interior_sizes else 0.0,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def analyze_exp(
    exp_id: str,
    meta: dict,
    shade_to_isom: dict[int, int],
) -> dict:
    """Analyse complete d'une experience : palette, surfaces, CC."""
    png_path: pathlib.Path = meta["vege_png"]
    ini_path: pathlib.Path = meta["pullauta_ini"]

    pgw_path = png_path.with_suffix(".pgw")
    pgw = read_pgw(pgw_path)
    pixel_m2 = pgw["pixel_m2"]

    labels, decode_meta = decode_png(png_path, ini_path)
    h, w = labels.shape

    # Masque de la parcelle cible NE
    parcel_mask = np.zeros((h, w), dtype=bool)
    parcel_mask[PARCEL_ROW0:PARCEL_ROW1, PARCEL_COL0:PARCEL_COL1] = True

    result: dict = {
        "exp":     exp_id,
        "label":   meta["label"],
        "decode":  decode_meta,
        "pgw":     pgw,
        "parcel_bbox": list(PARCEL_BBOX),
    }

    for scope, mask in [("full", None), ("parcel_NE", parcel_mask)]:
        surf = surface_stats(labels, shade_to_isom, pixel_m2, mask)
        result[f"surface_{scope}"] = surf

        cc_all: list[dict] = []
        for code in [406, 408, 410]:
            for conn in [4, 8]:
                cc_all.append(cc_stats(labels, code, shade_to_isom, pixel_m2, conn, mask))
        result[f"cc_{scope}"] = cc_all

    return result


def print_summary(results: list[dict]) -> None:
    shade_to_isom = load_shade_to_isom()
    print("\n=== SURFACES — dalle complete (100 ha) ===")
    print(f"  {'Exp':30s}  {'blanc':>7}  {'jaune':>7}  {'vert0':>7}  {'406':>7}  {'408':>7}  {'410':>7}  {'%vert':>6}")
    for r in results:
        s = r["surface_full"]
        print(f"  {r['label']:30s}  {s['ha_blanc']:7.2f}  {s['ha_jaune']:7.2f}  "
              f"{s['ha_vert0']:7.2f}  {s['ha_406']:7.2f}  {s['ha_408']:7.2f}  "
              f"{s['ha_410']:7.2f}  {s['pct_vert']:6.2f}%")

    print("\n=== SURFACES — parcelle NE (12.58 ha) ===")
    print(f"  {'Exp':30s}  {'blanc':>7}  {'jaune':>7}  {'vert0':>7}  {'406':>7}  {'408':>7}  {'410':>7}  {'%vert':>6}")
    for r in results:
        s = r["surface_parcel_NE"]
        print(f"  {r['label']:30s}  {s['ha_blanc']:7.2f}  {s['ha_jaune']:7.2f}  "
              f"{s['ha_vert0']:7.2f}  {s['ha_406']:7.2f}  {s['ha_408']:7.2f}  "
              f"{s['ha_410']:7.2f}  {s['pct_vert']:6.2f}%")

    print("\n=== COMPOSANTES CONNEXES — parcelle NE, connexite 4 ===")
    hdr = f"  {'Exp':28s}  {'ISOM':>4}  {'#CC':>5}  {'#bord':>5}  {'#int':>5}  {'med m2':>7}  {'max m2':>8}"
    print(hdr)
    for r in results:
        for cc in r["cc_parcel_NE"]:
            if cc["connectivity"] == 4:
                print(f"  {r['label']:28s}  {cc['isom']:>4}  {cc['n_cc']:>5}  "
                      f"{cc['n_cc_border']:>5}  {cc['n_cc_interior']:>5}  "
                      f"{cc['median_m2']:>7.0f}  {cc['max_m2']:>8.0f}")

    print("\n=== COMPOSANTES CONNEXES — parcelle NE, connexite 8 ===")
    print(hdr)
    for r in results:
        for cc in r["cc_parcel_NE"]:
            if cc["connectivity"] == 8:
                print(f"  {r['label']:28s}  {cc['isom']:>4}  {cc['n_cc']:>5}  "
                      f"{cc['n_cc_border']:>5}  {cc['n_cc_interior']:>5}  "
                      f"{cc['median_m2']:>7.0f}  {cc['max_m2']:>8.0f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="results_vege_abc.json")
    args = parser.parse_args()

    shade_to_isom = load_shade_to_isom()
    print(f"shade_to_isom charge : {shade_to_isom}")

    results: list[dict] = []
    for exp_id, meta in EXPERIMENTS.items():
        png_path = meta["vege_png"]
        if not png_path.exists():
            log.warning("Absent : %s — experience ignoree", png_path)
            continue
        log.info("Analyse : %s", exp_id)
        try:
            results.append(analyze_exp(exp_id, meta, shade_to_isom))
        except Exception as exc:
            log.error("%s : %s", exp_id, exc)
            raise

    print_summary(results)

    out_json = pathlib.Path(args.out)
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON -> {out_json}")

    # CSV plat : une ligne par (exp, scope)
    out_csv = out_json.with_suffix(".csv")
    rows: list[dict] = []
    for r in results:
        for scope in ["full", "parcel_NE"]:
            row = {"exp": r["exp"], "label": r["label"], "scope": scope}
            row.update(r[f"surface_{scope}"])
            # Ajouter CC cles (4-connexe)
            for cc in r[f"cc_{scope}"]:
                if cc["connectivity"] == 4:
                    pfx = f"cc4_{cc['isom']}"
                    row[f"{pfx}_n"] = cc["n_cc"]
                    row[f"{pfx}_med"] = cc["median_m2"]
                    row[f"{pfx}_max"] = cc["max_m2"]
            for cc in r[f"cc_{scope}"]:
                if cc["connectivity"] == 8:
                    pfx = f"cc8_{cc['isom']}"
                    row[f"{pfx}_n"] = cc["n_cc"]
                    row[f"{pfx}_med"] = cc["median_m2"]
                    row[f"{pfx}_max"] = cc["max_m2"]
            rows.append(row)

    if rows:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
    print(f"CSV  -> {out_csv}")


if __name__ == "__main__":
    main()
