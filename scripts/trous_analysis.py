"""Analyse des zones ouvertes et correspondances de composantes entre expériences.

Ce module fournit des fonctions pures (pas d'I/O ni de logging) utilisables
indépendamment par les scripts d'analyse et les tests synthétiques.

Conventions :
    shade     : np.ndarray uint8, valeurs KP (0=blanc, 1=jaune, 2..=vert)
    mask      : np.ndarray bool, même forme que shade
    pixel_m2  : surface d'un pixel en m², fourni explicitement (pas supposé 1).
"""
from __future__ import annotations

import hashlib
import pathlib
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

KP_BLANC = 0
KP_JAUNE = 1
KP_FIRST_GREEN = 2

# ---------------------------------------------------------------------------
# Masque trapézoïdal
# ---------------------------------------------------------------------------

# Sommets (row, col) dans le crop 340×370 de la fenêtre NE.
# Diagonale supérieure : (22,60)→(60,349) exclut le jardin est (coin droit rows 22-59).
# Bord inférieur à row=207 exclut les jardins sud (rows 208-340).
TRAPEZE_VERTICES: list[tuple[int, int]] = [
    (22, 60),    # coin supérieur gauche
    (60, 349),   # début du bord droit après la diagonale supérieure
    (207, 349),  # coin inférieur droit
    (207, 195),  # coude de la diagonale inférieure gauche
    (130, 30),   # point le plus à gauche
]


def _cache_key(shape: tuple, vertices: list[tuple[int, int]]) -> str:
    """Clé déterministe basée sur shape et sommets.

    Permet d'invalider automatiquement le cache si les sommets changent,
    sans nécessiter de suppression manuelle du fichier .npy.
    """
    payload = f"{shape}|{vertices}"
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def build_trapeze_mask(
    shape: tuple[int, int],
    vertices: list[tuple[int, int]] = TRAPEZE_VERTICES,
    cache: pathlib.Path | str | None = None,
) -> np.ndarray:
    """Masque booléen rempli par le polygone, purement géométrique.

    Tous les pixels à l'intérieur du polygone sont True, quelle que soit
    leur classe KP (blanc et jaune inclus).

    Le cache est invalide si shape ou vertices ont changé depuis le calcul
    précédent — aucune invalidation manuelle requise.

    Note sur MplPath : ``MplPath(verts, closed=True)`` affecte CLOSEPOLY au
    dernier sommet fourni dont les coordonnées sont ignorées. Ici on répète
    explicitement le premier sommet en fin de liste et on assigne CLOSEPOLY
    à ce doublon, garantissant que tous les sommets originaux reçoivent LINETO.
    """
    if cache is not None:
        cache = pathlib.Path(cache)
        sidecar = cache.with_suffix(".key")
        expected = _cache_key(shape, vertices)
        if cache.exists() and sidecar.exists() and sidecar.read_text().strip() == expected:
            m = np.load(cache)
            if m.shape == shape:
                return m

    from matplotlib.path import Path as MplPath

    verts_xy = [(float(c), float(r)) for r, c in vertices]
    verts_closed = verts_xy + [verts_xy[0]]          # répétition du 1er sommet
    n = len(verts_closed)
    codes = np.empty(n, dtype=np.uint8)
    codes[0]    = MplPath.MOVETO
    codes[1:-1] = MplPath.LINETO                     # tous les sommets originaux
    codes[-1]   = MplPath.CLOSEPOLY                  # doublon : coords ignorées

    path = MplPath(verts_closed, codes)
    rs, cs = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    pts = np.stack([cs.ravel(), rs.ravel()], axis=1)
    mask = path.contains_points(pts).reshape(shape)

    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, mask)
        sidecar.write_text(expected)
    return mask


# ---------------------------------------------------------------------------
# Frontière irrégulière du masque
# ---------------------------------------------------------------------------

def mask_boundary(mask: np.ndarray) -> np.ndarray:
    """Pixels du masque adjacents à l'extérieur (4-connexe).

    Utilise l'érosion avec border_value=0 : les pixels au bord du raster
    (edge de l'array) sont traités comme adjacents à l'extérieur du masque.
    Résultat = pixels du masque qu'une érosion pleine ne conserverait pas.
    """
    struct4 = ndimage.generate_binary_structure(2, 1)
    eroded = ndimage.binary_erosion(mask, structure=struct4, border_value=0)
    return mask & ~eroded


# ---------------------------------------------------------------------------
# Composantes connexes de zones non-vertes intérieures
# ---------------------------------------------------------------------------

def _interior_cc(binary: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Composantes connexes (4-connexe) de ``binary & mask`` intérieures au masque."""
    struct4 = ndimage.generate_binary_structure(2, 1)
    labeled, n = ndimage.label(binary & mask, structure=struct4)
    if n == 0:
        return labeled, []
    boundary = mask_boundary(mask)
    border_cc = set(np.unique(labeled[boundary])) - {0}
    return labeled, [i + 1 for i in range(n) if (i + 1) not in border_cc]


def get_interior_trous(
    shade: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, list[int]]:
    """CC non-vertes (blanc OU jaune) intérieures au masque irrégulier.

    Utilise la frontière d'érosion du masque, pas les seuls bords du rectangle.
    Retourne (labeled_array, interior_ids).
    """
    nonvert = (shade == KP_BLANC) | (shade == KP_JAUNE)
    return _interior_cc(nonvert, mask)


# ---------------------------------------------------------------------------
# Mesure séparée des zones ouvertes et classes de production
# ---------------------------------------------------------------------------

@dataclass
class OpenZoneStats:
    blanc_enclave_n: int = 0
    blanc_enclave_ha: float = 0.0
    jaune_enclave_n: int = 0
    jaune_enclave_ha: float = 0.0
    vert0_ha: float = 0.0
    ha_406: float = 0.0
    ha_408: float = 0.0
    ha_410: float = 0.0
    pixel_m2: float = 1.0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def classify_open_zones(
    shade: np.ndarray,
    mask: np.ndarray,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
) -> OpenZoneStats:
    """Mesure séparée des zones ouvertes enclavées et des classes de production.

    pixel_m2 : surface réelle d'un pixel, fournie explicitement.

    blanc_enclave / jaune_enclave : CC intérieures au masque (potentielles
        clairières — NON validées sans contrôle terrain).
    vert0  : pixels ISOM 0 (forêt courable). Classe de production légère,
        à ne pas confondre avec une zone ouverte.
    406/408/410 : classes de production.
    """
    if pixel_m2 <= 0:
        raise ValueError(f"pixel_m2 doit être positif, reçu {pixel_m2}")

    ha = pixel_m2 / 10_000.0

    labeled_b, b_ids = _interior_cc(shade == KP_BLANC, mask)
    labeled_j, j_ids = _interior_cc(shade == KP_JAUNE, mask)

    def _ha_ids(labeled: np.ndarray, ids: list[int]) -> float:
        return sum(int((labeled == i).sum()) for i in ids) * ha

    def _class_ha(isom_target: int) -> float:
        total = sum(
            int(((shade == s) & mask).sum())
            for s, v in shade_to_isom.items()
            if v == isom_target
        )
        return round(total * ha, 4)

    return OpenZoneStats(
        blanc_enclave_n=len(b_ids),
        blanc_enclave_ha=round(_ha_ids(labeled_b, b_ids), 4),
        jaune_enclave_n=len(j_ids),
        jaune_enclave_ha=round(_ha_ids(labeled_j, j_ids), 4),
        vert0_ha=_class_ha(0),
        ha_406=_class_ha(406),
        ha_408=_class_ha(408),
        ha_410=_class_ha(410),
        pixel_m2=pixel_m2,
    )


# ---------------------------------------------------------------------------
# Étiquetage ISOM d'un shade array
# ---------------------------------------------------------------------------

def isom_labeled(
    shade: np.ndarray,
    mask: np.ndarray,
    isom_code: int,
    shade_to_isom: dict[int, int],
    connectivity: int = 4,
) -> tuple[np.ndarray, int]:
    """Composantes connexes pour un code ISOM dans le masque."""
    cls = np.zeros(shade.shape, dtype=bool)
    for s, v in shade_to_isom.items():
        if v == isom_code:
            cls |= (shade == s)
    cls &= mask
    struct = (np.ones((3, 3), dtype=int) if connectivity == 8
              else ndimage.generate_binary_structure(2, 1))
    return ndimage.label(cls, structure=struct)


# ---------------------------------------------------------------------------
# Correspondances de composantes B → D
# ---------------------------------------------------------------------------

@dataclass
class ComponentEvent:
    event_type: str      # persist | disappear | appear | merge | split | complex
    from_ids: list[int]  # IDs dans lab_from (vides si appear)
    to_ids: list[int]    # IDs dans lab_to   (vides si disappear)
    from_ha: float
    to_ha: float
    pct_overlap: float   # fraction de from_ha recouverte par to (0-100)

    def as_dict(self) -> dict:
        return {
            "type":        self.event_type,
            "from_ids":    self.from_ids,
            "to_ids":      self.to_ids,
            "from_ha":     self.from_ha,
            "to_ha":       self.to_ha,
            "pct_overlap": self.pct_overlap,
        }


def cc_correspondences(
    shade_from: np.ndarray,
    shade_to: np.ndarray,
    mask: np.ndarray,
    isom_code: int,
    shade_to_isom: dict[int, int],
    pixel_m2: float,
    connectivity: int = 4,
) -> tuple[list[ComponentEvent], dict]:
    """Correspondances entre composantes d'une même classe ISOM de from vers to.

    pixel_m2 : surface réelle d'un pixel, fournie explicitement.

    Types d'événements :
        persist    : 1 CC_from ↔ 1 CC_to
        disappear  : CC_from de isom_code sans CC_to de isom_code en recouvrement.
                     Le pixel a pu changer de classe ISOM ou devenir blanc/jaune.
        appear     : CC_to de isom_code sans CC_from de isom_code en recouvrement.
                     Peut résulter d'un changement depuis une autre ISOM ou depuis
                     blanc/jaune.
        merge      : N CC_from → 1 CC_to  (N > 1)
        split      : 1 CC_from → M CC_to  (M > 1)
        complex    : N CC_from → M CC_to  (N > 1 et M > 1)

    Summary par type : n (groupes), n_from_cc (CC sources), n_to_cc (CC destinations).
    """
    if pixel_m2 <= 0:
        raise ValueError(f"pixel_m2 doit être positif, reçu {pixel_m2}")

    ha = pixel_m2 / 10_000.0

    lab_f, n_f = isom_labeled(shade_from, mask, isom_code, shade_to_isom, connectivity)
    lab_t, n_t = isom_labeled(shade_to,   mask, isom_code, shade_to_isom, connectivity)

    # Liens via overlap (vectorisé sur pixels du masque)
    mf = lab_f[mask]
    mt = lab_t[mask]
    f_to_ts: dict[int, set[int]] = defaultdict(set)
    t_to_fs: dict[int, set[int]] = defaultdict(set)
    for fi, ti in zip(mf.tolist(), mt.tolist()):
        if fi > 0 and ti > 0:
            f_to_ts[fi].add(ti)
            t_to_fs[ti].add(fi)

    sizes_f = {i: int((lab_f == i).sum()) for i in range(1, n_f + 1)}
    sizes_t = {j: int((lab_t == j).sum()) for j in range(1, n_t + 1)}

    def _overlap_px(fi: int, ti: int) -> int:
        return int(np.sum((lab_f == fi) & (lab_t == ti)))

    # Union-Find bipartite : regroupe les CC_from et CC_to connectées
    parent: dict = {}

    def find(x: object) -> object:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
            x = parent.get(x, x)
        return x

    def union(a: object, b: object) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    for fi in range(1, n_f + 1):
        for ti in f_to_ts.get(fi, set()):
            union(("f", fi), ("t", ti))

    groups: dict[object, dict] = defaultdict(lambda: {"from": [], "to": []})
    for fi in range(1, n_f + 1):
        groups[find(("f", fi))]["from"].append(fi)
    for ti in range(1, n_t + 1):
        if t_to_fs.get(ti):
            groups[find(("t", ti))]["to"].append(ti)

    covered_t: set[int] = {ti for g in groups.values() for ti in g["to"]}

    events: list[ComponentEvent] = []

    for g in groups.values():
        fids = g["from"]
        tids = g["to"]
        f_ha = round(sum(sizes_f[fi] for fi in fids) * ha, 5)
        t_ha = round(sum(sizes_t[ti] for ti in tids) * ha, 5)

        if not tids:
            events.append(ComponentEvent("disappear", fids, [], f_ha, 0.0, 0.0))
            continue

        total_ov = sum(_overlap_px(fi, ti) for fi in fids for ti in tids)
        total_from_px = sum(sizes_f[fi] for fi in fids)
        pct = round(100.0 * total_ov / total_from_px, 1) if total_from_px else 0.0

        nf, nt = len(fids), len(tids)
        if   nf == 1 and nt == 1: etype = "persist"
        elif nf >  1 and nt == 1: etype = "merge"
        elif nf == 1 and nt >  1: etype = "split"
        else:                     etype = "complex"

        events.append(ComponentEvent(etype, fids, tids, f_ha, t_ha, pct))

    for ti in range(1, n_t + 1):
        if ti not in covered_t:
            events.append(ComponentEvent(
                "appear", [], [ti], 0.0, round(sizes_t[ti] * ha, 5), 0.0,
            ))

    # Résumé : n (groupes), n_from_cc, n_to_cc, surfaces
    summary: dict = {}
    for etype in ("persist", "disappear", "appear", "merge", "split", "complex"):
        evts = [e for e in events if e.event_type == etype]
        summary[etype] = {
            "n":         len(evts),
            "n_from_cc": sum(len(e.from_ids) for e in evts),
            "n_to_cc":   sum(len(e.to_ids) for e in evts),
            "ha_from":   round(sum(e.from_ha for e in evts), 4),
            "ha_to":     round(sum(e.to_ha for e in evts), 4),
        }

    return events, summary


# ---------------------------------------------------------------------------
# Description proportionnelle (remplace les étiquettes binaires)
# ---------------------------------------------------------------------------

def overlap_label(pct: float) -> str:
    """Description de la proportion de surface conservée.

    Remplace les étiquettes binaires 'conservée/perdue' par la fraction réelle.
    """
    if pct >= 90:
        return f"persistante ({pct:.0f}%)"
    if pct >= 50:
        return f"partiellement conservee ({pct:.0f}%)"
    if pct >= 10:
        return f"partiellement disparue ({pct:.0f}%)"
    return f"quasi-disparue ({pct:.0f}%)"
