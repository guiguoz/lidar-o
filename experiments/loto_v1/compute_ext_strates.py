"""Calcul des strates étendues depuis les LAZ — branche E (enrichie).

Produit pour chaque terrain un fichier <terrain>_strates_ext.npz contenant :
  bins    (9, H, W) float32  — comptes bruts par tranche HAG
  n_first (H, W)   float32  — retours premiers (ReturnNumber == 1)
  n_last  (H, W)   float32  — retours derniers (ReturnNumber == NumberOfReturns)
  n_unique(H, W)   float32  — retours uniques (NumberOfReturns == 1)
  bbox              [xmin, ymin, xmax, ymax] EPSG:2154
  res_m             résolution pixel (m)
  laz_files         liste des LAZ utilisés

Tranches HAG (mètres, bornées inférieurement à 0, tous retours non-withheld) :
  b0 : [0.0, 0.2)   — quasi-sol (inclus dans T.ground, affiné ici)
  b1 : [0.2, 0.5)   — broussailles basses
  b2 : [0.5, 1.0)   — broussailles
  b3 : [1.0, 1.5)   — arbustes hauts    (limite T.low = 1.5)
  b4 : [1.5, 2.0)   — bas de canopée
  b5 : [2.0, 3.0)   — canopée basse     (limite T.med = 3.0)
  b6 : [3.0, 5.0)   — canopée interméd.
  b7 : [5.0, 10.0)  — canopée haute
  b8 : [10.0, +∞)   — très haute canopée

La définition du sol (DTM) réutilise exactement la méthode T :
  - Classes LAS 2 (Ground) + 9 (Water)
  - Minimum Z par cellule + hole-fill nearest-neighbor
(cf. DEVIATION-DTM dans omapmaker_ref.py)

Utiliser miniconda3/python.exe (python-pdal requis).
Commande :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/compute_ext_strates.py
"""
from __future__ import annotations

import logging
import pathlib
import sys

import numpy as np
import rasterio
from rasterio.transform import from_bounds, rowcol
from scipy.ndimage import distance_transform_edt

_THIS = pathlib.Path(__file__).resolve().parent
_ROOT = _THIS.parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

# _read_points réutilise le pipeline PDAL testé de omapmaker_ref
from omapmaker_ref import _read_points  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = _THIS / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Paramètres figés (identiques à la branche T) ─────────────────────────
RES_M: float = 2.0
CRS: str = "EPSG:2154"

# 9 tranches HAG (bornes en mètres, +∞ représenté par np.inf)
BIN_EDGES: list[float] = [0.0, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, np.inf]
N_BINS: int = len(BIN_EDGES) - 1  # 9

# Classes LAS pour le DTM (identiques à omapmaker_ref)
_GROUND_CLASSES: frozenset[int] = frozenset({2, 9})


# ── Configuration des terrains ────────────────────────────────────────────

def _strates_bbox(tif_path: pathlib.Path) -> tuple[list[float], int, int]:
    """Lit bbox, H, W depuis un TIF de strates existant."""
    with rasterio.open(str(tif_path)) as src:
        b = src.bounds
        h, w = src.height, src.width
    return [b.left, b.bottom, b.right, b.top], h, w


def _terrain_configs() -> list[dict]:
    bd_laz = pathlib.Path(
        r"E:\RunningRaid\Cartographie\ça te dit 2027\bois Dupont"
        r"\LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz"
    )
    # BD : bbox depuis config.py (source de vérité pour la grille 2 m/px)
    bd_bbox = [425000.0, 6922000.0, 426000.0, 6923000.0]

    return [
        {
            "name": "bd",
            "laz_files": [bd_laz],
            "bbox": bd_bbox,
            "h": 500, "w": 500,
        },
        {
            "name": "caen",
            "laz_files": sorted((
                _ROOT / "LIDAR" / "foret_caen"
            ).glob("*.laz")),
            # Eval zone = moitié sud du strates TIF (Y=[6888000,6889000]),
            # correspond à rows 0-499 du TIF OCAD (Y=[6887000,6889000])
            "bbox": [448000.0, 6888000.0, 450000.0, 6889000.0],
            "h": 500, "w": 1000,
        },
        {
            "name": "montmirel",
            "laz_files": sorted((
                _ROOT / "bois de montmirel"
            ).glob("*.laz")),
            "strates_tif": (
                _ROOT / "experiments" / "montmirel" / "output" / "omapmaker_strates.tif"
            ),
        },
        {
            "name": "sainte_anne",
            "laz_files": sorted((
                _ROOT / "la route de sainte anne"
            ).glob("*.laz")),
            "strates_tif": (
                _ROOT / "experiments" / "sainte_anne" / "output" / "omapmaker_strates.tif"
            ),
        },
    ]


# ── DTM ───────────────────────────────────────────────────────────────────

def _compute_dtm(
    pts_ground: np.ndarray,
    bbox: list[float],
    h: int,
    w: int,
) -> np.ndarray:
    """DTM par minimum Z des points sol + hole-fill nearest-neighbor.

    Identique à omapmaker_ref run_pass1, transposé pour la résolution 2 m.
    """
    dtm = np.full((h, w), np.nan, dtype=np.float64)
    if len(pts_ground) == 0:
        log.warning("DTM : aucun point sol — retour tableau NaN")
        return dtm

    xmin, ymin, xmax, ymax = bbox
    transform = from_bounds(xmin, ymin, xmax, ymax, w, h)

    xs = pts_ground["X"]
    ys = pts_ground["Y"]
    zs = pts_ground["Z"]

    rows, cols = rowcol(transform, xs, ys)
    valid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    rows, cols, zs = rows[valid], cols[valid], zs[valid]

    for r, c, z in zip(rows, cols, zs):
        if np.isnan(dtm[r, c]) or z < dtm[r, c]:
            dtm[r, c] = z

    # Hole-fill nearest-neighbor
    nodata = np.isnan(dtm)
    if nodata.any():
        indices = distance_transform_edt(nodata, return_distances=False, return_indices=True)
        dtm = dtm[tuple(indices)]  # indices.shape = (2, h, w) → (row_idx, col_idx)

    return dtm


# ── Calcul des strates étendues ───────────────────────────────────────────

def compute_ext_strates_for_terrain(cfg: dict) -> pathlib.Path:
    name = cfg["name"]
    out_path = DATA_DIR / f"{name}_strates_ext.npz"

    if out_path.exists():
        log.info("%s : strates ext déjà en cache (%s)", name, out_path.name)
        return out_path

    # Résoudre bbox + grille
    if "strates_tif" in cfg:
        bbox, h, w = _strates_bbox(cfg["strates_tif"])
        log.info("%s : bbox depuis strates TIF %dx%d px", name, h, w)
    else:
        bbox = cfg["bbox"]
        h, w  = cfg["h"], cfg["w"]
        log.info("%s : bbox depuis config — %dx%d px", name, h, w)

    laz_files = [pathlib.Path(f) for f in cfg["laz_files"]]
    missing = [f for f in laz_files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"{name} : LAZ manquants : {missing}")
    log.info("%s : %d fichier(s) LAZ", name, len(laz_files))

    transform = from_bounds(*bbox[:2], *bbox[2:], w, h)  # xmin ymin xmax ymax

    # ── Passe 1 : DTM ─────────────────────────────────────────────────────
    log.info("%s : lecture points sol (classes 2+9)...", name)
    ground_expr = "Classification == 2 || Classification == 9"
    pts_ground = _read_points(laz_files, bbox, expression=ground_expr)
    dtm = _compute_dtm(pts_ground, bbox, h, w)
    del pts_ground

    # ── Passe 2 : strates fines + ordres de retour ────────────────────────
    log.info("%s : lecture tous retours non-withheld...", name)
    pts = _read_points(laz_files, bbox)
    n_pts = len(pts)
    if n_pts == 0:
        log.warning("%s : aucun point — cache vide", name)
        bins_grid  = np.zeros((N_BINS, h, w), dtype=np.float32)
        n_first    = np.zeros((h, w), dtype=np.float32)
        n_last_arr = np.zeros((h, w), dtype=np.float32)
        n_unique   = np.zeros((h, w), dtype=np.float32)
    else:
        log.info("%s : %d points — calcul HAG...", name, n_pts)

        xs = pts["X"].astype(np.float64)
        ys = pts["Y"].astype(np.float64)
        zs = pts["Z"].astype(np.float64)

        # Indices grille
        rows, cols = rowcol(transform, xs, ys)
        in_grid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        rows = rows[in_grid].astype(np.int32)
        cols = cols[in_grid].astype(np.int32)
        zs   = zs[in_grid]

        # HAG = Z - DTM(r,c), clippé à [0, +∞)
        z_dtm = dtm[rows, cols]
        hag   = np.maximum(0.0, zs - z_dtm)

        # ── Strates fines (9 bins) ─────────────────────────────────────────
        bins_grid = np.zeros((N_BINS, h, w), dtype=np.float32)
        for k in range(N_BINS):
            lo, hi = BIN_EDGES[k], BIN_EDGES[k + 1]
            if np.isinf(hi):
                in_bin = hag >= lo
            else:
                in_bin = (hag >= lo) & (hag < hi)
            # np.add.at accumule sans boucle Python
            np.add.at(bins_grid[k], (rows[in_bin], cols[in_bin]), 1.0)

        del hag, in_grid, xs, ys, zs, z_dtm

        # ── Ordres de retour ──────────────────────────────────────────────
        n_first    = np.zeros((h, w), dtype=np.float32)
        n_last_arr = np.zeros((h, w), dtype=np.float32)
        n_unique   = np.zeros((h, w), dtype=np.float32)

        # Réindexer sur les mêmes points (en_grid appliqué plus haut)
        pts_in = pts[np.nonzero(
            (rowcol(transform, pts["X"], pts["Y"])[0] >= 0) &
            (rowcol(transform, pts["X"], pts["Y"])[0] < h) &
            (rowcol(transform, pts["X"], pts["Y"])[1] >= 0) &
            (rowcol(transform, pts["X"], pts["Y"])[1] < w)
        )[0]]

        rows2, cols2 = rowcol(transform, pts_in["X"], pts_in["Y"])
        rows2 = rows2.astype(np.int32)
        cols2 = cols2.astype(np.int32)

        rn  = pts_in["ReturnNumber"].astype(np.int32)
        nor = pts_in["NumberOfReturns"].astype(np.int32)

        is_first  = rn == 1
        is_last   = rn == nor
        is_unique = nor == 1

        np.add.at(n_first,    (rows2[is_first],  cols2[is_first]),  1.0)
        np.add.at(n_last_arr, (rows2[is_last],   cols2[is_last]),   1.0)
        np.add.at(n_unique,   (rows2[is_unique], cols2[is_unique]), 1.0)

        del pts, pts_in, rn, nor, rows2, cols2

    # Écriture atomique : temp → validation → remplacement
    tmp_path = out_path.with_suffix(".tmp.npz")
    if tmp_path.exists():
        tmp_path.unlink()
    log.info("%s : sauvegarde temporaire %s...", name, tmp_path.name)
    np.savez_compressed(
        str(tmp_path),
        bins=bins_grid,
        n_first=n_first,
        n_last=n_last_arr,
        n_unique=n_unique,
        bbox=np.array(bbox),
        res_m=np.float32(RES_M),
        laz_files=np.array([str(f) for f in laz_files]),
    )
    # Validation avant remplacement
    log.info("%s : validation du fichier temporaire...", name)
    with np.load(str(tmp_path)) as v:
        assert v["bins"].shape == (N_BINS, h, w), (
            f"bins.shape={v['bins'].shape} attendu ({N_BINS},{h},{w})"
        )
        for key in ("n_first", "n_last", "n_unique"):
            assert v[key].shape == (h, w), f"{key}.shape={v[key].shape} attendu ({h},{w})"
        assert not np.any(np.isnan(v["bins"])), "bins contient des NaN"
    tmp_path.replace(out_path)
    log.info("%s : OK — total retours = %.0f", name, bins_grid.sum())
    return out_path


def main() -> None:
    for cfg in _terrain_configs():
        compute_ext_strates_for_terrain(cfg)
    log.info("=== Strates étendues complètes ===")


if __name__ == "__main__":
    main()
