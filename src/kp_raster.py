"""Pont Karttapullautin → raster classifié (végétation vectorisable).

KP ne produit **aucun** vecteur de végétation : il écrit des PNG. Deux familles
sortent du mode batch (`batch=1`, celui qu'utilise `src/run_engine.py`) :

    {dalle}_vege.png       rendu RGB — la palette est étendue en RGB à l'écriture
                           (src/process.rs : `RgbImage` + `to_rgb8()`), les couleurs
                           restent exactes mais ne sont plus des indices
    {dalle}_vege_bit.png   raster de **classes** en niveaux de gris, produit si
                           `vege_bitmode=1` (src/vegetation.rs)

Sémantique du raster bit (KP v2.12.1, lue dans le source — pas déduite) :

    0     fond / blanc              → forêt courable ISOM 405 (rien à dessiner)
    1     jaune                     → terrain découvert ISOM 401
    2 + i teinte verte d'indice i   → i = 0 est le vert le plus clair

Sémantique du PNG indexé écrit dans `temp/` (src/palette.rs, `to_color()`) :

    0 transparent · 1 blanc · 2 noir · 3 jaune · 4 bleu · 5 undergrowth · 16+i vert i

Ce module ne fait **qu'une chose** : transformer ces tuiles en exactement le même
artefact que `scripts/process_hag.py`, à savoir un GeoTIFF uint8 dont les DN sont
ceux attendus par `src/vegetation.py` (85/170/255 → ISOM 406/408/410), géoréférencé
dans le CRS du terrain. Tout l'aval — généralisation, masque, assemblage `.omap`,
QA — est réutilisé tel quel : aucune chaîne de vectorisation parallèle.

Usage :
    from src.kp_raster import build_class_raster, report_shades
    build_class_raster("out_kp_grimbosq", cfg, "EPSG:2154",
                       "output/kp_vege_classified.tif", bbox=(448000, 6886000, 450001, 6889001))

    # Calibration du mapping teinte → ISOM (histogramme des teintes en ha) :
    python -m src.kp_raster report out_kp_grimbosq
"""
from __future__ import annotations

import argparse
import logging
import pathlib
from typing import Any, Iterable, NamedTuple

import numpy as np
import rasterio
import yaml
from rasterio.transform import from_origin

log = logging.getLogger(__name__)

# DN du raster classifié → code ISOM. Doit rester identique à
# src/vegetation._HAG_CLASS_MAP : c'est le contrat qui permet de réutiliser
# le CO Generalization Engine sans le modifier.
ISOM_TO_DN: dict[int, int] = {406: 85, 408: 170, 410: 255}

# Valeur du raster bit KP signifiant "aucune végétation" (blanc ISOM 405).
KP_NO_DATA = 0
KP_YELLOW = 1
KP_FIRST_GREEN = 2

# Sentinel interne : pixel présent dans le PNG mais absent de la palette attendue.
_UNMATCHED = 255

# Indices fixes de la palette KP (src/palette.rs → PaletteColorEnum::to_color).
KP_INDEX_YELLOW = 3
KP_INDEX_FIRST_GREEN = 16


class Tile(NamedTuple):
    """Une tuile KP localisée : raster + position au sol."""
    path: pathlib.Path
    labels: np.ndarray      # valeurs "bit" : 0 blanc, 1 jaune, 2+i vert i
    res_m: float
    west: float             # X du coin haut-gauche (bord du pixel, pas centre)
    north: float            # Y du coin haut-gauche


# ── Palette KP (recalculée depuis le source, jamais devinée) ──────────────────

def kp_green_rgb(n_shades: int, lightgreentone: int) -> list[tuple[int, int, int]]:
    """RGB des teintes vertes KP, du plus clair au plus foncé.

    Reproduit src/palette.rs :
        R = B = tone − tone/(N−1)·i        G = 254 − 74/(N−1)·i
    avec N = len(greenshades) **y compris les entrées `99` désactivées** — le
    diviseur est calculé sur la longueur du paramètre, pas sur le nombre de
    teintes réellement atteignables. Une palette recalculée avec le mauvais N
    ne correspond à aucun pixel du PNG.
    """
    if n_shades < 2:
        return [(lightgreentone, 254, lightgreentone)]
    out = []
    for i in range(n_shades):
        rb = int(lightgreentone - lightgreentone / (n_shades - 1) * i)
        g = int(254.0 - (74.0 / (n_shades - 1)) * i)
        out.append((rb, g, rb))
    return out


def read_ini_vege_params(ini_path: pathlib.Path | None) -> dict[str, Any]:
    """Lit `greenshades`, `lightgreentone` et `vege_bitmode` dans un pullauta.ini.

    `src/run_engine.generate_ini()` écrit ce fichier dans `out_kp_{terrain}/` :
    le relire garantit que la palette utilisée correspond au run réel, y compris
    si un `pullauta.ini` maison a servi de base. Retourne les défauts KP
    (greenshades à 11 entrées, tone 200) si le fichier est absent.
    """
    defaults = {"n_shades": 11, "lightgreentone": 200, "vege_bitmode": False, "ini": None}
    if ini_path is None or not pathlib.Path(ini_path).exists():
        return defaults

    params: dict[str, str] = {}
    for line in pathlib.Path(ini_path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        params[key.strip()] = val.strip()

    n_shades = defaults["n_shades"]
    if "greenshades" in params:
        n_shades = len([v for v in params["greenshades"].split("|") if v != ""])
    tone = int(float(params.get("lightgreentone", defaults["lightgreentone"])))
    bitmode = params.get("vege_bitmode", "0") == "1"
    return {
        "n_shades": n_shades,
        "lightgreentone": tone,
        "vege_bitmode": bitmode,
        "ini": str(ini_path),
    }


def _read_pgw(pgw_path: pathlib.Path) -> tuple[float, float, float]:
    """World file KP → (résolution m, X centre du pixel haut-gauche, Y idem).

    KP écrit `minx + 0.5` / `maxy − 0.5` (src/process.rs) : ce sont des
    **centres de pixel**, pas des coins. Le décalage d'un demi-pixel (0,5 m)
    est corrigé par `tile_origin()`.
    """
    lines = pgw_path.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) < 6:
        raise ValueError(f"PGW invalide (attendu 6 lignes) : {pgw_path}")
    return abs(float(lines[0])), float(lines[4]), float(lines[5])


def tile_origin(res_m: float, center_x: float, center_y: float) -> tuple[float, float]:
    """Centre du pixel haut-gauche → coin haut-gauche (convention GeoTIFF)."""
    return center_x - res_m / 2.0, center_y + res_m / 2.0


# ── Lecture d'une tuile ───────────────────────────────────────────────────────

def _rgb_lookup(params: dict[str, Any]) -> dict[tuple[int, int, int], int]:
    """Table RGB exact → valeur "bit" (0 blanc, 1 jaune, 2+i vert i)."""
    lut: dict[tuple[int, int, int], int] = {
        (255, 255, 255): KP_NO_DATA,         # PaletteColorEnum::BackgroundWhite
        (255, 219, 166): KP_YELLOW,          # PaletteColorEnum::Yellow2, src/palette.rs
    }
    for i, rgb in enumerate(kp_green_rgb(params["n_shades"], params["lightgreentone"])):
        lut[rgb] = KP_FIRST_GREEN + i
    return lut


def _labels_from_gray(arr: np.ndarray, params: dict[str, Any], path: pathlib.Path) -> np.ndarray:
    """Raster bit KP (`*_vege_bit.png`) : les valeurs SONT déjà les classes."""
    max_expected = KP_FIRST_GREEN + params["n_shades"] - 1
    if int(arr.max()) > max_expected:
        raise ValueError(
            f"{path.name} : valeurs jusqu'à {int(arr.max())} alors que le raster bit KP "
            f"culmine à {max_expected} (1 + len(greenshades)). Ce n'est pas un "
            f"*_vege_bit.png — vérifier `greenshades` dans le pullauta.ini du run."
        )
    return arr.astype(np.uint8)


def _labels_from_index(arr: np.ndarray, params: dict[str, Any]) -> tuple[np.ndarray, int]:
    """PNG indexé (`temp/vegetation.png`) : les indices de palette sont les classes.

    Indices figés dans src/palette.rs (`PaletteColorEnum::to_color`) :
    1 = blanc, 3 = jaune, 16+i = vert i. Tout autre indice (2 noir bâti, 4 bleu
    eau, 5 undergrowth) est ramené au blanc : ce n'est pas de la végétation KP.
    """
    idx = arr.astype(np.int32)
    labels = np.full(idx.shape, KP_NO_DATA, dtype=np.uint8)
    labels[idx == KP_INDEX_YELLOW] = KP_YELLOW
    green_idx = np.array([KP_INDEX_FIRST_GREEN + i for i in range(params["n_shades"])])
    for i, gi in enumerate(green_idx):
        labels[idx == gi] = KP_FIRST_GREEN + i
    known = np.concatenate(([0, 1, KP_INDEX_YELLOW], green_idx))
    unmatched = int(np.sum(~np.isin(idx, known)))
    return labels, unmatched


def _labels_from_rgb(arr: np.ndarray, params: dict[str, Any], path: pathlib.Path) -> tuple[np.ndarray, int]:
    """PNG RGB/RGBA (sortie batch `*_vege.png`) : appariement exact sur la palette.

    Aucune tolérance chromatique volontairement : les couleurs du rendu batch sont
    les couleurs de la palette (KP fait `to_rgb8()` puis overlay opaque sur blanc),
    donc un pixel non apparié signifie une palette mal recalculée, pas un dégradé.
    """
    rgb = arr[:, :, :3].astype(np.int32)
    lut = _rgb_lookup(params)
    uniq, inv = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    table = np.full(len(uniq), _UNMATCHED, dtype=np.uint8)
    unknown: list[tuple[int, int, int]] = []
    for k, color in enumerate(uniq):
        key = (int(color[0]), int(color[1]), int(color[2]))
        if key in lut:
            table[k] = lut[key]
        else:
            unknown.append(key)
    labels = table[inv.reshape(rgb.shape[:2])]
    unmatched = int(np.sum(labels == _UNMATCHED))
    if unmatched:
        log.warning(
            "%s : %d pixels (%.2f %%) hors palette KP attendue "
            "(greenshades=%d teintes, lightgreentone=%d) — couleurs inconnues : %s",
            path.name, unmatched, 100.0 * unmatched / labels.size,
            params["n_shades"], params["lightgreentone"], sorted(unknown)[:5],
        )
    return labels, unmatched


def _to_labels(arr: np.ndarray, colormap: dict | None, params: dict[str, Any],
               path: pathlib.Path) -> tuple[np.ndarray, int]:
    """Raster brut KP → valeurs "bit" (0 blanc, 1 jaune, 2+i vert i).

    `arr` est soit (H, W) — une seule bande — soit (H, W, 3) — RGB(A) aplati.
    La présentation est détectée depuis le fichier lui-même, pas depuis son nom :
    PNG indexé (colormap présente) · niveaux de gris (raster bit) · RGB.
    """
    if arr.ndim == 3:
        if colormap is not None:
            raise ValueError(f"{path.name} : bande multiple ET palette — cas non prévu")
        return _labels_from_rgb(arr, params, path)
    if colormap is not None:
        return _labels_from_index(arr, params)
    return _labels_from_gray(arr, params, path), 0


def load_tiles(
    out_kp: pathlib.Path,
    params: dict[str, Any] | None = None,
    prefer: str = "auto",
) -> list[Tile]:
    """Charge toutes les tuiles de végétation KP d'un répertoire.

    prefer : "bit" (force `*_vege_bit.png`), "rgb" (force `*_vege.png`),
             "auto" (bit si présent, sinon rgb).
    """
    out_kp = pathlib.Path(out_kp)
    params = params or read_ini_vege_params(out_kp / "pullauta.ini")

    if prefer == "auto":
        prefer = "bit" if list(out_kp.glob("*_vege_bit.png")) else "rgb"
    pattern = "*_vege_bit.png" if prefer == "bit" else "*_vege.png"
    pngs = sorted(p for p in out_kp.glob(pattern) if not p.name.startswith("merged"))

    if prefer == "rgb" and not pngs:
        # Repli sur les tuiles non-batch (KP hors mode batch écrit *_vege.png aussi,
        # mais un run manuel peut n'avoir laissé que vegetation.png).
        single = out_kp / "vegetation.png"
        if single.exists():
            pngs = [single]

    tiles: list[Tile] = []
    unmatched_total = 0
    for png in pngs:
        pgw = png.with_suffix(".pgw")
        if not pgw.exists():
            log.warning("Tuile ignorée (PGW absent) : %s", png.name)
            continue
        res_m, cx, cy = _read_pgw(pgw)
        west, north = tile_origin(res_m, cx, cy)
        with rasterio.open(png) as ds:
            raw = ds.read()
            try:
                cmap: dict | None = ds.colormap(1) if ds.count == 1 else None
            except ValueError:
                cmap = None            # niveaux de gris (raster bit) — pas de palette
            # Une bande → (H, W). Plusieurs bandes → (H, W, 3) : la détection se
            # fait sur le nombre de bandes, jamais sur la forme du tableau.
            arr = raw[0] if ds.count == 1 else np.moveaxis(raw[:3], 0, -1)
        labels, unmatched = _to_labels(arr, cmap, params, png)
        unmatched_total += unmatched
        tiles.append(Tile(png, labels, res_m, west, north))

    if not tiles:
        raise FileNotFoundError(
            f"Aucune tuile de végétation KP dans {out_kp}/ "
            f"(cherché {pattern}). Lancer l'étape relief d'abord, ou vérifier "
            f"`vege_bitmode=1` dans pullauta.ini pour obtenir *_vege_bit.png."
        )
    log.info("KP : %d tuile(s) végétation lue(s) en mode %s (%d pixels hors palette)",
             len(tiles), prefer, unmatched_total)
    return tiles


# ── Mosaïque + classification ─────────────────────────────────────────────────

def mosaic(tiles: Iterable[Tile], bbox: tuple[float, float, float, float] | None = None,
           ) -> tuple[np.ndarray, float, float, float]:
    """Assemble les tuiles en un seul raster de classes.

    Contrairement à `main._merge_vege_tiles()`, la mosaïque se fait sur les
    **valeurs de classe**, jamais sur des couleurs : aucun remapping de ton ne
    peut créer de teinte hors palette. Les tuiles se recouvrant sont écrasées
    par la suivante (elles proviennent du même run KP → mêmes valeurs).

    Retourne (labels, res_m, west, north).
    """
    tiles = list(tiles)
    res_m = min(t.res_m for t in tiles)
    if any(abs(t.res_m - res_m) > 1e-6 for t in tiles):
        log.warning("Résolutions hétérogènes (%s) — la plus fine est retenue",
                    sorted({t.res_m for t in tiles}))

    west = min(t.west for t in tiles)
    north = max(t.north for t in tiles)
    east = max(t.west + t.labels.shape[1] * t.res_m for t in tiles)
    south = min(t.north - t.labels.shape[0] * t.res_m for t in tiles)

    if bbox is not None:
        bxmin, bymin, bxmax, bymax = bbox
        west, east = max(west, bxmin), min(east, bxmax)
        south, north = max(south, bymin), min(north, bymax)
        if west >= east or south >= north:
            raise ValueError(
                f"Emprise KP [{west}, {south}, {east}, {north}] disjointe de la bbox "
                f"config {bbox} — mauvais terrain ou tuiles décalées (cf. `check`)."
            )

    # Alignement sur la grille de la tuile la plus fine.
    width = int(np.ceil((east - west) / res_m))
    height = int(np.ceil((north - south) / res_m))
    canvas = np.zeros((height, width), dtype=np.uint8)

    for t in tiles:
        col = int(round((max(t.west, west) - west) / res_m))
        row = int(round((north - min(t.north, north)) / res_m))
        scale = int(round(t.res_m / res_m))
        lab = t.labels
        if scale > 1:
            lab = np.repeat(np.repeat(lab, scale, axis=0), scale, axis=1)
        h, w = lab.shape
        h = min(h, height - row)
        w = min(w, width - col)
        if h <= 0 or w <= 0:
            continue
        canvas[row:row + h, col:col + w] = lab[:h, :w]

    return canvas, res_m, west, north


def shade_to_dn(labels: np.ndarray, mapping: dict[int, int]) -> tuple[np.ndarray, dict[int, int]]:
    """Applique la table teinte KP → code ISOM, puis code ISOM → DN raster.

    `mapping` est indexé par la valeur du raster bit KP (2 = vert le plus clair).
    Toute valeur absente de la table est ignorée (reste blanc) — c'est le cas des
    teintes que KP n'atteint jamais (entrées `99` de `greenshades`).
    """
    out = np.zeros(labels.shape, dtype=np.uint8)
    counts: dict[int, int] = {}
    for value, code in sorted(mapping.items()):
        if int(value) < KP_FIRST_GREEN:
            continue                      # 0/1 gérés à part (blanc / jaune)
        if int(code) == 0:
            continue                      # teinte volontairement abandonnée
        if int(code) not in ISOM_TO_DN:
            raise ValueError(
                f"shade_to_isom[{value}] = {code} : le moteur de généralisation ne "
                f"connaît que {sorted(ISOM_TO_DN)} (jaune/401 vient de BD TOPO/OSM)."
            )
        mask = labels == int(value)
        n = int(mask.sum())
        if n:
            out[mask] = ISOM_TO_DN[int(code)]
            counts[int(code)] = counts.get(int(code), 0) + n
    unmatched = int(np.sum(labels == _UNMATCHED))
    if unmatched:
        raise ValueError(
            f"{unmatched} pixels ({100.0 * unmatched / labels.size:.2f} %) ne "
            f"correspondent à aucune couleur de la palette KP attendue. "
            f"Vérifier greenshades/lightgreentone dans le pullauta.ini du run."
        )
    return out, counts


def build_class_raster(
    out_kp: str | pathlib.Path,
    cfg: dict,
    crs: str,
    out_tif: str | pathlib.Path,
    bbox: tuple[float, float, float, float] | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """Tuiles KP → GeoTIFF classifié au format attendu par `src/vegetation.py`.

    Produit exactement le même contrat que `scripts/process_hag.py` :
    uint8, DN 85/170/255, 0 = pas de végétation, CRS du terrain.
    """
    out_kp = pathlib.Path(out_kp)
    out_tif = pathlib.Path(out_tif)
    vege_cfg = (cfg.get("karttapullautin", {}).get("vectorization", {}) or {})
    mapping_raw = vege_cfg.get("shade_to_isom", {}) or {}
    mapping = {int(k): int(v) for k, v in mapping_raw.items()}
    if not mapping:
        raise ValueError(
            "karttapullautin.vectorization.shade_to_isom absent de config.yaml — "
            "aucune teinte KP ne peut être traduite en code ISOM."
        )

    params = read_ini_vege_params(out_kp / "pullauta.ini")
    tiles = load_tiles(out_kp, params, prefer=prefer or vege_cfg.get("input", "auto"))
    labels, res_m, west, north = mosaic(tiles, bbox=bbox)

    classified, counts = shade_to_dn(labels, mapping)

    yellow_px = int(np.sum(labels == KP_YELLOW))
    if yellow_px and int(vege_cfg.get("yellow_to", 0)) != 0:
        raise ValueError(
            "karttapullautin.vectorization.yellow_to != 0 : le jaune KP (401) n'est "
            "pas pris en charge par le moteur de généralisation (profil calibré pour "
            "406/408/410) et fait double emploi avec les couches BD TOPO/OSM."
        )

    transform = from_origin(west, north, res_m, res_m)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff", "height": classified.shape[0], "width": classified.shape[1],
        "count": 1, "dtype": "uint8", "crs": crs, "transform": transform,
        "nodata": 0, "compress": "deflate",
    }
    with rasterio.open(out_tif, "w", **profile) as ds:
        ds.write(classified, 1)

    ha = res_m * res_m / 10_000.0
    report = {
        "source_tiles": [t.path.name for t in tiles],
        "input_mode": "bit" if tiles[0].path.name.endswith("_vege_bit.png") else "rgb",
        "kp_params": params,
        "res_m": res_m,
        "extent": (west, north - classified.shape[0] * res_m,
                   west + classified.shape[1] * res_m, north),
        "pixels": {str(code): n for code, n in sorted(counts.items())},
        "ha": {str(code): round(n * ha, 2) for code, n in sorted(counts.items())},
        "yellow_ha_ignored": round(yellow_px * ha, 2),
        "out_tif": str(out_tif),
    }
    log.info(
        "Raster classifié KP → %s (%d×%d px, %.1f m/px) : %s",
        out_tif.name, classified.shape[1], classified.shape[0], res_m,
        ", ".join(f"{c}={report['ha'][str(c)]} ha" for c in sorted(counts)),
    )
    return report


# ── Calibration : que contient réellement le raster KP ? ──────────────────────

def report_shades(out_kp: str | pathlib.Path, cfg: dict | None = None) -> dict[str, Any]:
    """Histogramme des teintes KP en hectares — sert à caler `shade_to_isom`.

    La calibration ne se fait pas à l'œil sur une couleur : on compare la
    couverture de chaque teinte à celle d'une carte de référence (les cibles
    `generalization.profiles.*.qa_targets` mesurées sur carte FFCO), et on place
    les coupures là où les cumuls se rejoignent.
    """
    out_kp = pathlib.Path(out_kp)
    params = read_ini_vege_params(out_kp / "pullauta.ini")
    tiles = load_tiles(out_kp, params)
    labels, res_m, _, _ = mosaic(tiles)
    ha = res_m * res_m / 10_000.0

    values, counts = np.unique(labels, return_counts=True)
    table = []
    for v, n in zip(values, counts):
        v = int(v)
        if v == _UNMATCHED:
            name = "HORS PALETTE ⚠"
        elif v == KP_NO_DATA:
            name = "blanc (405 forêt courable)"
        elif v == KP_YELLOW:
            name = "jaune (401 terrain découvert)"
        else:
            name = f"vert {v - KP_FIRST_GREEN + 1} (teinte KP {v - KP_FIRST_GREEN}, " \
                   f"{'le plus clair' if v == KP_FIRST_GREEN else 'de plus en plus foncé'})"
        table.append({"value": v, "ha": round(float(n) * ha, 2), "pct": round(100.0 * n / labels.size, 2),
                      "label": name})

    total_green = sum(row["ha"] for row in table if row["value"] >= KP_FIRST_GREEN)
    print(f"Tuiles lues : {len(tiles)}  ·  {res_m} m/px  ·  palette {params['n_shades']} teintes, "
          f"tone {params['lightgreentone']}  ·  ini {params['ini']}")
    print(f"{'val':>4}  {'ha':>10}  {'%':>6}  {'% du vert':>9}   signification")
    for row in table:
        share = f"{100.0 * row['ha'] / total_green:8.1f}%" if (total_green and row["value"] >= KP_FIRST_GREEN) else "        —"
        print(f"{row['value']:>4}  {row['ha']:>10.2f}  {row['pct']:>6.2f}  {share}   {row['label']}")
    print(f"\nVert total : {total_green:.2f} ha   ·   jaune ignoré : "
          f"{sum(r['ha'] for r in table if r['value'] == KP_YELLOW):.2f} ha")
    if cfg:
        targets = (((cfg.get("generalization", {}).get("profiles", {}) or {})
                    .get(cfg.get("generalization", {}).get("active_profile", ""), {}) or {})
                   .get("qa_targets", {}) or {})
        if targets:
            print("Cibles carte de référence (qa_targets) : "
                  + ", ".join(f"{c}: {v.get('cov_pct')} %" for c, v in targets.items()
                              if isinstance(v, dict) and v.get("cov_pct") is not None))
    return {"params": params, "res_m": res_m, "table": table, "total_green_ha": total_green}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["report"], help="report = histogramme des teintes KP")
    parser.add_argument("out_kp", help="répertoire out_kp_{terrain}/ contenant les tuiles")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    cfg = yaml.safe_load(pathlib.Path(args.config).read_text(encoding="utf-8")) \
        if pathlib.Path(args.config).exists() else None
    if args.command == "report":
        report_shades(args.out_kp, cfg)


if __name__ == "__main__":
    main()
