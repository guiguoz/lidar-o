"""Analyse comparative des rasters vegetation KP — experiences A / B / C / D.

Usage :
    python scripts/analyse_vege_abc.py [--out results_vege_abc.json]

Ce script utilise les fonctions de production de src/kp_raster.py pour garantir
que le decodage de la palette et le mapping shade->ISOM sont identiques a ceux
utilises par le pipeline. Aucune palette codee en dur.

Zones d'analyse :
    fenetre_NE : rectangle rows 0:340 cols 550:920 (12.58 ha)
                 repere commun pour toutes les comparaisons.
    bois_NE    : polygone fixe du bois cible (union+closing+fill+erosion),
                 independant des classifications. Sauvegarde dans
                 scripts/bois_NE_mask.npy. Les trouees internes sont les
                 pixels jaune/blanc a l'interieur de ce masque.

Traçabilite par experience :
    sha256 du PNG, hash de l'ini, palette observee avec effectifs,
    mapping ISOM utilise.

Verification de grille :
    Avant toute transition, les deux rasters doivent avoir meme taille,
    meme transform PGW et meme origine. Leve ValueError si incompatible.
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
from scripts.trous_analysis import (
    build_trapeze_mask,
    classify_open_zones,
    cc_correspondences,
    TRAPEZE_VERTICES,
)
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

# ── Zones d'analyse ───────────────────────────────────────────────────────────
FENETRE_NE = dict(row0=0, row1=340, col0=550, col1=920)
FENETRE_NE_BBOX = (425550, 6922660, 425920, 6923000)  # Lambert 93

BOIS_MASK_PATH    = pathlib.Path("scripts/bois_NE_mask.npy")
TRAPEZE_MASK_PATH = pathlib.Path("scripts/bois_trapeze_mask.npy")

# ── Experiences ───────────────────────────────────────────────────────────────
BASE = pathlib.Path("out_kp_bois_dupont")
LAZ  = "LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz"

EXPERIMENTS: dict[str, dict] = {
    "A_med9-16_t01": {
        "vege_png":   BASE / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "pullauta.ini",
        "label": "A med9/16 t=0.1",
    },
    "B_med1-1_t01": {
        "vege_png":   BASE / "test"  / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "test" / "pullauta.ini",
        "label": "B med1/1 t=0.1",
    },
    "C_med1-1_t02": {
        "vege_png":   BASE / "exp_c" / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "exp_c" / "pullauta.ini",
        "label": "C med1/1 t=0.2",
    },
    "D_med3-5_t01": {
        "vege_png":   BASE / "exp_d" / f"{LAZ}_vege.png",
        "pullauta_ini": BASE / "exp_d" / "pullauta.ini",
        "label": "D med3/5 t=0.1",
    },
}


# ── Chargement shade_to_isom ──────────────────────────────────────────────────

def load_shade_to_isom() -> dict[int, int]:
    import yaml
    cfg = yaml.safe_load(pathlib.Path("config.yaml").read_text(encoding="utf-8"))
    raw = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {}).get("shade_to_isom") or {}
    if not raw:
        raise ValueError("karttapullautin.vectorization.shade_to_isom absent de config.yaml")
    return {int(k): int(v) for k, v in raw.items()}


# ── Verification d'egalite de grille ─────────────────────────────────────────

def assert_same_grid(pgw_a: dict, pgw_b: dict, size_a: tuple, size_b: tuple,
                     name_a: str, name_b: str) -> None:
    """Leve ValueError si les deux rasters ont des grilles incompatibles.

    Compare la taille, la resolution et l'origine (centre du pixel haut-gauche).
    L'egalite est exigee a 1e-6 m pres pour la position et a 1e-9 m pour la resolution.
    """
    if size_a != size_b:
        raise ValueError(
            f"Grilles incompatibles : {name_a} {size_a} != {name_b} {size_b}"
        )
    for key in ("A", "E"):
        if abs(pgw_a[key] - pgw_b[key]) > 1e-9:
            raise ValueError(
                f"Resolution differente : {name_a} {key}={pgw_a[key]} "
                f"vs {name_b} {key}={pgw_b[key]}"
            )
    for key in ("C", "F"):
        if abs(pgw_a[key] - pgw_b[key]) > 1e-6:
            raise ValueError(
                f"Origine differente : {name_a} {key}={pgw_a[key]:.6f} "
                f"vs {name_b} {key}={pgw_b[key]:.6f}"
            )


# ── PGW ───────────────────────────────────────────────────────────────────────

def read_pgw(pgw_path: pathlib.Path) -> dict:
    if not pgw_path.exists():
        raise FileNotFoundError(f"PGW absent : {pgw_path}")
    vals = [float(l.strip()) for l in pgw_path.read_text().splitlines() if l.strip()]
    if len(vals) < 6:
        raise ValueError(f"PGW invalide ({len(vals)} lignes) : {pgw_path}")
    A, D, B, E, C, F = vals
    return {"A": A, "D": D, "B": B, "E": E, "C": C, "F": F,
            "pixel_m2": abs(A * E - B * D), "res_m": abs(A)}


# ── Decodage PNG ──────────────────────────────────────────────────────────────

def decode_png(png_path: pathlib.Path, ini_path: pathlib.Path) -> tuple[np.ndarray, dict]:
    """PNG *_vege.png -> labels KP + metadonnees de traçabilite.

    Traçabilite incluse : sha256 du PNG, hash sha256 de l'ini, palette
    observee avec effectifs, parametres de rendu (n_shades, lightgreentone).

    Toute couleur hors palette produit une ValueError (zero tolerance).
    Bilan complet verifie : blanc+jaune+verts+inconnus == total_px.
    """
    params = read_ini_vege_params(ini_path)
    lut = _rgb_lookup(params)
    expected_greens = kp_green_rgb(params["n_shades"], params["lightgreentone"])

    arr = np.array(Image.open(png_path).convert("RGB"))
    h, w = arr.shape[:2]
    rgb = arr.astype(np.int32)

    uniq, inv = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    table = np.full(len(uniq), _UNMATCHED, dtype=np.uint8)
    unknown: list[tuple[int, int, int]] = []
    palette_obs: dict[str, int] = {}

    for k, color in enumerate(uniq):
        key = (int(color[0]), int(color[1]), int(color[2]))
        palette_obs[str(key)] = int((inv == k).sum())
        if key in lut:
            table[k] = lut[key]
        else:
            unknown.append(key)

    labels = table[inv.reshape(h, w)]
    n_unknown = int(np.sum(labels == _UNMATCHED))

    # Bilan
    n_comptable = 0
    for shade in [KP_NO_DATA, KP_YELLOW] + list(range(KP_FIRST_GREEN,
                                                        KP_FIRST_GREEN + params["n_shades"])):
        n_comptable += int(np.sum(labels == shade))
    n_comptable += n_unknown
    if n_comptable != h * w:
        raise ValueError(f"{png_path.name}: bilan pixels incomplet ({n_comptable} != {h*w})")

    if n_unknown > 0:
        raise ValueError(
            f"{png_path.name}: {n_unknown} pixels hors palette "
            f"(n_shades={params['n_shades']}, tone={params['lightgreentone']}) "
            f"couleurs inconnues: {unknown[:5]}"
        )

    meta = {
        "path":          str(png_path.resolve()),
        "sha256_png":    hashlib.sha256(png_path.read_bytes()).hexdigest(),
        "sha256_ini":    hashlib.sha256(ini_path.read_bytes()).hexdigest(),
        "mode":          "RGB",
        "size_wh":       (w, h),
        "n_shades":      params["n_shades"],
        "lightgreentone": params["lightgreentone"],
        "expected_greens": [list(c) for c in expected_greens[:8]],
        "palette_observed": palette_obs,
        "n_unknown_px":  0,
        "palette_ok":    True,
    }
    return labels, meta


# ── Masque bois ───────────────────────────────────────────────────────────────

def load_or_build_bois_mask(
    labels_abc: list[np.ndarray],
    fenetre: dict,
) -> np.ndarray:
    """Charge scripts/bois_NE_mask.npy ou le reconstruit.

    Le masque est fixe : union des non-jaune de A/B/C + closing 15 m +
    fill_holes + erosion 5 m + composante principale.
    Independant des classifications individuelles.
    """
    if BOIS_MASK_PATH.exists():
        mask = np.load(BOIS_MASK_PATH)
        r0, r1, c0, c1 = fenetre["row0"], fenetre["row1"], fenetre["col0"], fenetre["col1"]
        expected_shape = (r1 - r0, c1 - c0)
        if mask.shape == expected_shape:
            return mask
        log.warning("Masque bois shape %s != attendu %s — reconstruction",
                    mask.shape, expected_shape)

    r0, r1, c0, c1 = fenetre["row0"], fenetre["row1"], fenetre["col0"], fenetre["col1"]
    union = np.zeros((r1-r0, c1-c0), dtype=bool)
    for labels in labels_abc:
        union |= (labels[r0:r1, c0:c1] != KP_YELLOW) & (labels[r0:r1, c0:c1] != _UNMATCHED)

    struct2 = ndimage.generate_binary_structure(2, 2)
    closed  = ndimage.binary_closing(union, structure=struct2, iterations=15)
    filled  = ndimage.binary_fill_holes(closed)
    eroded  = ndimage.binary_erosion(filled, structure=struct2, iterations=5)
    bois    = ndimage.binary_fill_holes(eroded)

    labeled, n = ndimage.label(bois)
    if n > 1:
        sizes = ndimage.sum(bois, labeled, range(1, n+1))
        bois = (labeled == (int(np.argmax(sizes)) + 1))

    BOIS_MASK_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(BOIS_MASK_PATH, bois)
    return bois


# ── Statistiques de surface ───────────────────────────────────────────────────

def surface_stats(
    labels: np.ndarray,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
    mask: np.ndarray | None = None,
) -> dict:
    """Surfaces et pourcentages par classe ISOM.

    Bilan : blanc + jaune + vert0 + 406 + 408 + 410 + inconnu = total_px.
    Pourcentages :
        pct_406/408/410 : sur le total du masque
        pct_vert        : (406+408+410)/total * 100
        pct_vert_sur_nonjaune : (406+408+410)/(total-jaune) * 100
    """
    work = labels[mask] if mask is not None else labels
    total_px = work.size
    ha = pixel_m2 / 10_000.0

    by_isom: dict = {"blanc": 0, "jaune": 0, "vert0": 0, 406: 0, 408: 0, 410: 0, "inconnu": 0}
    by_isom["blanc"] = int(np.sum(work == KP_NO_DATA))
    by_isom["jaune"] = int(np.sum(work == KP_YELLOW))

    for shade in range(KP_FIRST_GREEN, KP_FIRST_GREEN + 12):
        n = int(np.sum(work == shade))
        if n == 0:
            continue
        isom = shade_to_isom.get(shade)
        if isom is None:
            by_isom["inconnu"] += n
        elif isom == 0:
            by_isom["vert0"] += n
        elif isom in (406, 408, 410):
            by_isom[isom] += n
        else:
            by_isom["inconnu"] += n

    bilan = sum(by_isom.values())
    if bilan != total_px:
        raise ValueError(f"Bilan incomplet : {bilan} != {total_px}")

    def pct(n): return round(100.0 * n / total_px, 4)
    def h(n):   return round(n * ha, 4)

    nv = by_isom[406] + by_isom[408] + by_isom[410]
    nj = by_isom["jaune"]
    nonjaune = total_px - nj
    return {
        "total_px": total_px,    "total_ha":  round(total_px * ha, 4),
        "pixel_m2": pixel_m2,
        "px_blanc":  by_isom["blanc"],  "ha_blanc":  h(by_isom["blanc"]),  "pct_blanc":  pct(by_isom["blanc"]),
        "px_jaune":  nj,                "ha_jaune":  h(nj),                "pct_jaune":  pct(nj),
        "px_vert0":  by_isom["vert0"],  "ha_vert0":  h(by_isom["vert0"]), "pct_vert0":  pct(by_isom["vert0"]),
        "px_406":    by_isom[406],      "ha_406":    h(by_isom[406]),     "pct_406":    pct(by_isom[406]),
        "px_408":    by_isom[408],      "ha_408":    h(by_isom[408]),     "pct_408":    pct(by_isom[408]),
        "px_410":    by_isom[410],      "ha_410":    h(by_isom[410]),     "pct_410":    pct(by_isom[410]),
        "px_vert":   nv,                "ha_vert":   h(nv),               "pct_vert":   pct(nv),
        "pct_vert_sur_nonjaune": round(100.0 * nv / nonjaune, 4) if nonjaune > 0 else 0.0,
        "px_inconnu": by_isom["inconnu"],
    }


# ── Composantes connexes ──────────────────────────────────────────────────────

def cc_stats(
    labels: np.ndarray,
    isom_code: int,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
    connectivity: int,
    mask: np.ndarray | None = None,
) -> dict:
    """CCs pour une classe ISOM dans un masque donne.

    connectivity: 4 ou 8.
    n_cc_border : composantes touchant le bord du masque (tronquees).
    Medianes et moyennes en m² (flottants).
    """
    if mask is not None:
        work = np.zeros(labels.shape, dtype=bool)
        work_flat = np.zeros(labels.shape, dtype=bool)
        work_flat[mask if mask.ndim == 2 else np.unravel_index(
            np.where(mask)[0], labels.shape)] = True
    else:
        work_flat = np.ones(labels.shape, dtype=bool)

    class_mask = np.zeros(labels.shape, dtype=bool)
    for shade, isom in shade_to_isom.items():
        if isom == isom_code:
            class_mask |= (labels == shade)
    if mask is not None:
        class_mask &= work_flat

    struct = (np.ones((3, 3), dtype=int) if connectivity == 8
              else ndimage.generate_binary_structure(2, 1))
    labeled_arr, n_total = ndimage.label(class_mask, structure=struct)

    if n_total == 0:
        return {"connectivity": connectivity, "isom": isom_code,
                "n_cc": 0, "n_cc_border": 0, "n_cc_interior": 0,
                "median_m2": 0.0, "mean_m2": 0.0, "max_m2": 0.0}

    sizes = np.array(ndimage.sum(class_mask, labeled_arr, range(1, n_total + 1)))

    # Composantes de bord
    border_set: set[int] = set()
    for border in [labeled_arr[0, :], labeled_arr[-1, :],
                   labeled_arr[:, 0], labeled_arr[:, -1]]:
        border_set.update(int(v) for v in border if v != 0)
    if mask is not None:
        border_inner = work_flat & ~ndimage.binary_erosion(work_flat, structure=struct)
        border_set.update(int(v) for v in labeled_arr[border_inner] if v != 0)

    interior_sizes = [float(sizes[i-1]) for i in range(1, n_total+1) if i not in border_set]

    return {
        "connectivity":  connectivity,
        "isom":          isom_code,
        "n_cc":          n_total,
        "n_cc_border":   len(border_set),
        "n_cc_interior": len(interior_sizes),
        "median_m2":     round(float(np.median(interior_sizes)) * pixel_m2, 2) if interior_sizes else 0.0,
        "mean_m2":       round(float(np.mean(interior_sizes)) * pixel_m2, 2) if interior_sizes else 0.0,
        "max_m2":        round(float(max(interior_sizes)) * pixel_m2, 2) if interior_sizes else 0.0,
    }


# ── Matrices de transition ────────────────────────────────────────────────────

ISOM_CLASSES = [0, 1, 2, 406, 408, 410]  # blanc, jaune, vert0, 406, 408, 410

def to_isom_arr(labels: np.ndarray, shade_to_isom: dict[int, int]) -> np.ndarray:
    out = np.full(labels.shape, -1, dtype=np.int32)
    out[labels == KP_NO_DATA] = 0
    out[labels == KP_YELLOW]  = 1
    for shade, isom in shade_to_isom.items():
        m = labels == shade
        out[m] = 2 if isom == 0 else isom
    return out

def transition_matrix(
    labels_from: np.ndarray,
    labels_to: np.ndarray,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
    mask: np.ndarray | None,
    pgw_from: dict,
    pgw_to: dict,
    name_from: str,
    name_to: str,
) -> dict:
    """Matrice de transition entre deux experiences.

    Verifie l'egalite des grilles avant tout calcul.
    """
    assert_same_grid(pgw_from, pgw_to, labels_from.shape, labels_to.shape,
                     name_from, name_to)

    if mask is not None:
        f = to_isom_arr(labels_from, shade_to_isom)[mask if mask.ndim == 2
            else np.unravel_index(np.where(mask)[0], labels_from.shape)]
        t = to_isom_arr(labels_to,   shade_to_isom)[mask if mask.ndim == 2
            else np.unravel_index(np.where(mask)[0], labels_to.shape)]
    else:
        f = to_isom_arr(labels_from, shade_to_isom).ravel()
        t = to_isom_arr(labels_to,   shade_to_isom).ravel()

    ha = pixel_m2 / 10_000.0
    n = len(ISOM_CLASSES)
    mat = np.zeros((n, n), dtype=np.float64)
    for i, ci in enumerate(ISOM_CLASSES):
        for j, cj in enumerate(ISOM_CLASSES):
            mat[i, j] = float(np.sum((f == ci) & (t == cj))) * ha

    return {
        "from": name_from, "to": name_to,
        "classes": ISOM_CLASSES,
        "class_labels": {str(c): n for c, n in zip(
            ISOM_CLASSES, ["blanc", "jaune", "vert0(ISOM0)", "ISOM 406", "ISOM 408", "ISOM 410"])},
        "matrix_ha": [[round(v, 4) for v in row] for row in mat],
        "scope": "bois_NE" if mask is not None else "full",
    }


# ── Analyse principale d'une experience ──────────────────────────────────────

def analyze_exp(
    exp_id: str,
    meta: dict,
    shade_to_isom: dict[int, int],
    bois_mask: np.ndarray,
    trapeze_mask: np.ndarray,
) -> tuple[dict, np.ndarray, dict]:
    """Retourne (result_dict, labels_full, pgw)."""
    png_path: pathlib.Path = meta["vege_png"]
    ini_path: pathlib.Path = meta["pullauta_ini"]

    pgw  = read_pgw(png_path.with_suffix(".pgw"))
    labels, dec_meta = decode_png(png_path, ini_path)
    h, w = labels.shape

    fne = FENETRE_NE
    fne_mask2d = np.zeros((h, w), dtype=bool)
    fne_mask2d[fne["row0"]:fne["row1"], fne["col0"]:fne["col1"]] = True

    bois_full = np.zeros((h, w), dtype=bool)
    bois_full[fne["row0"]:fne["row1"], fne["col0"]:fne["col1"]] = bois_mask

    trapeze_full = np.zeros((h, w), dtype=bool)
    trapeze_full[fne["row0"]:fne["row1"], fne["col0"]:fne["col1"]] = trapeze_mask

    # Labels en crop 340×370 pour les fonctions trous_analysis
    labels_crop = labels[fne["row0"]:fne["row1"], fne["col0"]:fne["col1"]]

    result: dict = {
        "exp":    exp_id,
        "label":  meta["label"],
        "decode": dec_meta,
        "pgw":    pgw,
        "shade_to_isom": {str(k): v for k, v in shade_to_isom.items()},
        "fenetre_NE_bbox": list(FENETRE_NE_BBOX),
        "bois_mask_path":    str(BOIS_MASK_PATH),
        "trapeze_mask_path": str(TRAPEZE_MASK_PATH),
        "trapeze_vertices":  TRAPEZE_VERTICES,
    }

    for scope, mask2d in [
        ("full", None),
        ("fenetre_NE", fne_mask2d),
        ("bois_NE", bois_full),
        ("bois_trapeze", trapeze_full),
    ]:
        surf = surface_stats(labels, shade_to_isom, pgw["pixel_m2"], mask2d)
        result[f"surface_{scope}"] = surf
        cc_all = []
        for code in [406, 408, 410]:
            for conn in [4, 8]:
                cc_all.append(cc_stats(
                    labels, code, shade_to_isom, pgw["pixel_m2"], conn, mask2d,
                ))
        result[f"cc_{scope}"] = cc_all

    # Zones ouvertes séparées sur le bois trapézoïdal
    oz = classify_open_zones(labels_crop, trapeze_mask, shade_to_isom, pixel_m2=pgw["pixel_m2"])
    result["open_zones_trapeze"] = oz.as_dict()

    return result, labels, pgw


# ── Affichage ─────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    for zone in ["full", "fenetre_NE", "bois_NE", "bois_trapeze"]:
        ha_label = {"full": "100 ha", "fenetre_NE": "12.58 ha",
                    "bois_NE": "~7.2 ha", "bois_trapeze": "~4.6 ha"}[zone]
        print(f"\n=== SURFACES — {zone} ({ha_label}) ===")
        print(f"  {'Exp':22s}  {'blanc':>6}  {'jaune':>6}  {'vert0':>6}  {'406':>6}  {'408':>6}  {'410':>6}  {'%vert':>6}")
        for r in results:
            s = r[f"surface_{zone}"]
            print(f"  {r['label']:22s}  {s['ha_blanc']:6.2f}  {s['ha_jaune']:6.2f}  "
                  f"{s['ha_vert0']:6.2f}  {s['ha_406']:6.2f}  {s['ha_408']:6.2f}  "
                  f"{s['ha_410']:6.2f}  {s['pct_vert']:6.1f}%")

    for zone in ["fenetre_NE", "bois_NE", "bois_trapeze"]:
        for conn in [4, 8]:
            print(f"\n=== CC {zone} connexite {conn} ===")
            print(f"  {'Exp':22s}  {'ISOM':>4}  {'#CC':>5}  {'#bord':>5}  {'med m2':>8}  {'max m2':>9}")
            for r in results:
                for cc in r[f"cc_{zone}"]:
                    if cc["connectivity"] == conn:
                        print(f"  {r['label']:22s}  {cc['isom']:>4}  {cc['n_cc']:>5}  "
                              f"{cc['n_cc_border']:>5}  {cc['median_m2']:>8.0f}  {cc['max_m2']:>9.0f}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="results_vege_abc.json")
    parser.add_argument("--exps", nargs="*", help="Filtrer par ID d'experience")
    args = parser.parse_args()

    shade_to_isom = load_shade_to_isom()
    log.info("shade_to_isom : %s", shade_to_isom)

    # Charger tous les labels pour construire le masque bois
    all_labels: dict[str, np.ndarray] = {}
    all_pgw:    dict[str, dict] = {}

    exps_to_run = {k: v for k, v in EXPERIMENTS.items()
                   if (not args.exps or k in args.exps) and v["vege_png"].exists()}
    if not exps_to_run:
        log.error("Aucune experience disponible")
        return

    log.info("Experiences : %s", list(exps_to_run))

    # Premier passage : decode pour avoir les labels
    for exp_id, meta in exps_to_run.items():
        labels, _ = decode_png(meta["vege_png"], meta["pullauta_ini"])
        all_labels[exp_id] = labels
        all_pgw[exp_id] = read_pgw(meta["vege_png"].with_suffix(".pgw"))

    # Construire le masque bois (sur A/B/C si disponibles, sinon tous)
    base_exps = [v for k, v in all_labels.items() if k in (
        "A_med9-16_t01", "B_med1-1_t01", "C_med1-1_t02")]
    if not base_exps:
        base_exps = list(all_labels.values())
    bois_mask = load_or_build_bois_mask(base_exps, FENETRE_NE)
    log.info("Masque bois (elargi) : %d px = %.2f ha", bois_mask.sum(), bois_mask.sum()/10000)

    trapeze_mask = build_trapeze_mask(
        (FENETRE_NE["row1"] - FENETRE_NE["row0"],
         FENETRE_NE["col1"] - FENETRE_NE["col0"]),
        TRAPEZE_VERTICES,
        cache=TRAPEZE_MASK_PATH,
    )
    log.info("Masque trapeze : %d px = %.2f ha", trapeze_mask.sum(), trapeze_mask.sum()/10000)

    # Analyse complete
    results: list[dict] = []
    for exp_id, meta in exps_to_run.items():
        log.info("Analyse : %s", exp_id)
        result, labels, pgw = analyze_exp(
            exp_id, meta, shade_to_isom, bois_mask, trapeze_mask,
        )
        all_labels[exp_id] = labels
        all_pgw[exp_id]    = pgw
        results.append(result)

    print_summary(results)

    # Matrices de transition
    transitions: list[dict] = []
    pairs = [("B_med1-1_t01", "A_med9-16_t01"),
             ("A_med9-16_t01", "B_med1-1_t01"),
             ("B_med1-1_t01", "C_med1-1_t02"),
             ("B_med1-1_t01", "D_med3-5_t01")]
    bois_full = np.zeros((1000, 1000), dtype=bool)
    bois_full[FENETRE_NE["row0"]:FENETRE_NE["row1"],
              FENETRE_NE["col0"]:FENETRE_NE["col1"]] = bois_mask

    for id_from, id_to in pairs:
        if id_from in all_labels and id_to in all_labels:
            try:
                t = transition_matrix(
                    all_labels[id_from], all_labels[id_to],
                    shade_to_isom, all_pgw[id_from]["pixel_m2"],
                    bois_full,
                    all_pgw[id_from], all_pgw[id_to],
                    id_from, id_to,
                )
                transitions.append(t)
            except ValueError as e:
                log.error("Transition %s->%s : %s", id_from, id_to, e)

    # Correspondances de composantes B→D sur le bois trapézoïdal
    correspondances: dict = {}
    if "B_med1-1_t01" in all_labels and "D_med3-5_t01" in all_labels:
        fne = FENETRE_NE
        labels_b_crop = all_labels["B_med1-1_t01"][
            fne["row0"]:fne["row1"], fne["col0"]:fne["col1"]]
        labels_d_crop = all_labels["D_med3-5_t01"][
            fne["row0"]:fne["row1"], fne["col0"]:fne["col1"]]
        pixel_m2_b = all_pgw["B_med1-1_t01"]["pixel_m2"]
        for isom_code in [406, 408, 410]:
            events, summary = cc_correspondences(
                labels_b_crop, labels_d_crop, trapeze_mask,
                isom_code, shade_to_isom, pixel_m2=pixel_m2_b, connectivity=4,
            )
            correspondances[str(isom_code)] = {
                "summary": summary,
                "events": [e.as_dict() for e in events],
            }
        log.info("Correspondances B->D calculees sur bois_trapeze")

    # Ecriture JSON
    out_json = pathlib.Path(args.out)
    output = {
        "results": results,
        "transitions": transitions,
        "correspondances_BD_trapeze": correspondances,
        "bois_mask_ha":    round(float(bois_mask.sum()) / 10000, 4),
        "trapeze_mask_ha": round(float(trapeze_mask.sum()) / 10000, 4),
    }
    out_json.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("JSON -> %s", out_json)

    # CSV plat
    out_csv = out_json.with_suffix(".csv")
    rows: list[dict] = []
    for r in results:
        for scope in ["full", "fenetre_NE", "bois_NE", "bois_trapeze"]:
            row = {"exp": r["exp"], "label": r["label"], "scope": scope,
                   "sha256_png": r["decode"]["sha256_png"][:16],
                   "sha256_ini": r["decode"]["sha256_ini"][:16]}
            row.update(r[f"surface_{scope}"])
            for cc in r[f"cc_{scope}"]:
                if cc["connectivity"] == 4:
                    pfx = f"cc4_{cc['isom']}"
                    row.update({f"{pfx}_n": cc["n_cc"], f"{pfx}_med": cc["median_m2"],
                                 f"{pfx}_max": cc["max_m2"]})
                elif cc["connectivity"] == 8:
                    pfx = f"cc8_{cc['isom']}"
                    row.update({f"{pfx}_n": cc["n_cc"], f"{pfx}_med": cc["median_m2"],
                                 f"{pfx}_max": cc["max_m2"]})
            rows.append(row)
    if rows:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
    log.info("CSV -> %s", out_csv)


if __name__ == "__main__":
    main()
