"""Vérifie la fidélité raster → .omap → raster pour bois_dupont_supervised_e.

Pipeline :
  1. Parse les polygones du .omap (OOM units → L93)
  2. Rasterise sur la grille exacte du raster supervised_e (500×500 px, 2 m/px)
  3. Compare avec la prédiction source
  4. Produit statistiques + planche PNG

Aucun nouveau calcul LiDAR ou modèle.
"""
from __future__ import annotations

import re
import pathlib

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
from shapely.geometry import Polygon
from shapely.validation import make_valid
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

# ── Chemins et constantes ─────────────────────────────────────────────────────
ROOT     = pathlib.Path(__file__).resolve().parent
OMAP     = ROOT / "output" / "bois_dupont_supervised_e_fidele.omap"
PRED_TIF = ROOT / "output" / "supervised_e_test_bd" / "supervised_e_prediction.tif"
OUT_PNG  = ROOT / "output" / "verification_raster_omap_bd_fidele.png"
COV_TIF  = ROOT / "output" / "bois_dupont_supervised_e_coverage.tif"

BBOX        = (425000., 6922000., 426000., 6923000.)
H, W        = 500, 500
REF_X       = 426000.
REF_Y       = 6923000.
SCALE       = 10000
UPM         = 1_000_000 / SCALE   # 100 → 1 OOM unit = 0.01 m en L93
NODATA_PRED = 255

# symbol_id ISOM → classe supervised_e
# classe 1 (blanc) n'a pas de polygone dans le .omap → fond par défaut du raster
SYM_TO_CLASS: dict[int, int] = {79: 0, 86: 2, 89: 3, 93: 4}
CLASS_NAMES  = {0: "decouvert", 1: "blanc", 2: "veg_406", 3: "veg_408", 4: "veg_410"}


# ── Conversion coords ─────────────────────────────────────────────────────────

def _omap_to_l93(ox: int, oy: int) -> tuple[float, float]:
    return REF_X + ox / UPM, REF_Y - oy / UPM


# ── Parsing polygones OOM ─────────────────────────────────────────────────────

def _parse_rings(coords_str: str) -> list[tuple[int, list[tuple[float, float]]]]:
    """Retourne liste de (flag, [(x,y), ...]) par anneau.

    flag 2  = anneau extérieur
    flag 18 = trou
    """
    rings: list[tuple[int, list[tuple[float, float]]]] = []
    current: list[tuple[float, float]] = []
    for tok in coords_str.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        parts = tok.split()
        ox, oy = int(parts[0]), int(parts[1])
        flag   = int(parts[2]) if len(parts) > 2 else 0
        x, y   = _omap_to_l93(ox, oy)
        current.append((x, y))
        if flag in (2, 18):
            if len(current) >= 3:
                rings.append((flag, current))
            current = []
    return rings


def _build_polygons(coords_str: str) -> list[Polygon]:
    """coords OOM → liste de Shapely Polygons valides."""
    rings   = _parse_rings(coords_str)
    polys: list[Polygon] = []
    ext_pts: list[tuple[float, float]] | None = None
    holes:   list[list[tuple[float, float]]]  = []

    def _flush() -> None:
        if ext_pts is None:
            return
        p = make_valid(Polygon(ext_pts, holes))
        if p.geom_type == "Polygon" and p.is_valid and not p.is_empty:
            polys.append(p)
        elif p.geom_type == "MultiPolygon":
            polys.extend(g for g in p.geoms if g.is_valid and not g.is_empty)

    for flag, pts in rings:
        if flag == 2:          # nouvel anneau extérieur
            _flush()
            ext_pts = pts
            holes   = []
        elif flag == 18:
            holes.append(pts)

    _flush()
    return polys


# ── 1. Parser le .omap ────────────────────────────────────────────────────────

print("Parsing .omap...")
xml = OMAP.read_text(encoding="utf-8")

# <object type="1" symbol="N">...<coords count="K">...</coords>...</object>
pattern = re.compile(
    r'<object type="1" symbol="(\d+)">'
    r'.*?<coords[^>]*>(.*?)</coords>',
    re.DOTALL,
)

shapes_for_raster: list[tuple[Polygon, int]] = []
n_by_class: dict[int, int] = {c: 0 for c in SYM_TO_CLASS.values()}
n_errors = 0

for m in pattern.finditer(xml):
    sym_id = int(m.group(1))
    if sym_id not in SYM_TO_CLASS:
        continue
    cls = SYM_TO_CLASS[sym_id]
    try:
        polys = _build_polygons(m.group(2))
    except Exception as exc:
        n_errors += 1
        continue
    for p in polys:
        shapes_for_raster.append((p, cls))
        n_by_class[cls] += 1

print(f"  Polygones parsés : {sum(n_by_class.values())}"
      f"  (401:{n_by_class[0]} 406:{n_by_class[2]} 408:{n_by_class[3]} 410:{n_by_class[4]})"
      f"  erreurs:{n_errors}")

if not shapes_for_raster:
    raise RuntimeError("Aucun polygone parsé — vérifier le .omap.")


# ── 2. Rasteriser ─────────────────────────────────────────────────────────────

print("Rasterisation sur grille 500×500 px (2 m/px, EPSG:2154)...")
transform = from_bounds(*BBOX, W, H)

# fill=1 (blanc) = fond par défaut, classe 1 = aucun polygone en .omap
omap_raster = rasterize(
    shapes_for_raster,
    out_shape=(H, W),
    transform=transform,
    fill=1,
    dtype="uint8",
)
unique_omap = np.unique(omap_raster).tolist()
print(f"  Classes dans le raster OOM : {unique_omap}")


# ── 3. Charger la prédiction source ───────────────────────────────────────────

print("Chargement raster supervised_e...")
with rasterio.open(str(PRED_TIF)) as ds:
    pred    = ds.read(1)               # classes 0–4 ou 255
    support = ds.read(2).astype(bool)

n_support = int(support.sum())
n_nodata  = int((~support).sum())
print(f"  Pixels support : {n_support}  hors-support : {n_nodata}")


# ── 4. Statistiques ───────────────────────────────────────────────────────────

pred_s = pred[support]
omap_s = omap_raster[support]

n_changed = int((pred_s != omap_s).sum())
pct_ok    = 100.0 * (n_support - n_changed) / n_support
pct_chg   = 100.0 * n_changed / n_support

print()
print("=== RÉSULTATS ===")
print(f"Pixels support    : {n_support:,}")
print(f"Pixels identiques : {n_support - n_changed:,}  ({pct_ok:.2f}%)")
print(f"Pixels modifiés   : {n_changed:,}  ({pct_chg:.2f}%)")

classes  = [0, 1, 2, 3, 4]
n_cls    = len(classes)
cm       = np.zeros((n_cls, n_cls), dtype=np.int64)
for i, ci in enumerate(classes):
    for j, cj in enumerate(classes):
        cm[i, j] = int(((pred_s == ci) & (omap_s == cj)).sum())

print()
print("Matrice de confusion (lignes=prédiction source, colonnes=OOM rasterisé) :")
hdr = "              " + "  ".join(f"{CLASS_NAMES[c]:>10}" for c in classes)
print(hdr)
for i, ci in enumerate(classes):
    row = f"{CLASS_NAMES[ci]:>14}" + "  ".join(f"{cm[i,j]:>10,}" for j in range(n_cls))
    print(row)

print()
print("Écarts par classe (pixels support uniquement) :")
for i, ci in enumerate(classes):
    n_pred = int((pred_s == ci).sum())
    if n_pred == 0:
        continue
    n_ok  = int(cm[i, i])
    n_err = n_pred - n_ok
    pct   = 100.0 * n_err / n_pred
    dests = []
    for j, cj in enumerate(classes):
        if cj != ci and cm[i, j] > 0:
            dests.append(f"{CLASS_NAMES[cj]}:{cm[i,j]:,}")
    top = "  ".join(dests) or "-"
    print(f"  {CLASS_NAMES[ci]:>10} : {n_ok:>6,}/{n_pred:>6,} fideles ({pct:.2f}% perdu)  -> {top}")

# Pixels inconnus — verification separee
print()
print("=== PIXELS INCONNUS (hors support) ===")
n_pred_nodata = int((pred == NODATA_PRED).sum())
print(f"  Hors support (support=0)      : {n_nodata:,}/{H*W:,} ({100.*n_nodata/(H*W):.4f}%)")
print(f"  pred=NODATA(255) coincide     : {n_pred_nodata:,}  (attendu = {n_nodata:,})")
print(f"  Coherent                      : {n_pred_nodata == n_nodata}")
omap_on_unknown = omap_raster[~support]
vals_uk, cnts_uk = np.unique(omap_on_unknown, return_counts=True)
print(f"  Valeur OOM sur inconnus       : {dict(zip(vals_uk.tolist(), cnts_uk.tolist()))}")
all_blanc = bool((omap_on_unknown == 1).all())
print(f"  Tous a 1=blanc (fond)         : {all_blanc}")
print(f"  LIMITE : ces {n_nodata:,} px sont absents du .omap (hors couverture LiDAR).")
print(f"  Ils apparaissent comme fond blanc mais ne sont pas courables.")
print(f"  Masque de couverture          : {COV_TIF}")
unknown_rows, unknown_cols = np.where(~support)
if len(unknown_rows) <= 20:
    coords_uk = list(zip(unknown_rows.tolist(), unknown_cols.tolist()))
    print(f"  Localisation (row,col)        : {coords_uk}")
else:
    r_min, r_max = int(unknown_rows.min()), int(unknown_rows.max())
    c_min, c_max = int(unknown_cols.min()), int(unknown_cols.max())
    print(f"  Plage rows [{r_min},{r_max}]  cols [{c_min},{c_max}]")


# ── 5. Planche de visualisation ───────────────────────────────────────────────

print()
print("Génération planche...")

PALETTE = {0: "#FFC90F", 1: "#FFFFFF", 2: "#CCFFB3", 3: "#99FF66", 4: "#33FF00"}
NODATA_COLOR = "#3C3C3C"

cmap5  = mcolors.ListedColormap([PALETTE[c] for c in [0,1,2,3,4]] + [NODATA_COLOR])
bnds5  = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
norm5  = mcolors.BoundaryNorm(bnds5, cmap5.N)

DIFF_NOCHANGE = 5    # identique → gris clair
DIFF_NODATA   = 6    # hors support → gris foncé

cmap_diff = mcolors.ListedColormap(
    [PALETTE[c] for c in [0,1,2,3,4]] + ["#CCCCCC", NODATA_COLOR]
)
bnds_diff = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
norm_diff = mcolors.BoundaryNorm(bnds_diff, cmap_diff.N)

def _make_disp(arr: np.ndarray, nodata_val: int) -> np.ndarray:
    out = arr.astype(float)
    out[~support] = nodata_val
    return out

pred_disp = _make_disp(pred, 5)
omap_disp = _make_disp(omap_raster, 5)

# Différences : DIFF_NOCHANGE si identiques, classe prédiction si différents
diff_disp = np.full((H, W), DIFF_NOCHANGE, dtype=float)
changed2d = (pred != omap_raster) & support
diff_disp[changed2d] = pred[changed2d].astype(float)   # classe d'origine perdue
diff_disp[~support]  = DIFF_NODATA

fig, axes = plt.subplots(2, 2, figsize=(14, 12))
fig.suptitle(
    "Verification raster -> .omap_fidele -> raster   (Bois Dupont, supervised_e)\n"
    f"Modifies : {pct_chg:.2f}% des {n_support:,} pixels support | inconnus : {n_nodata}",
    fontsize=11,
)

ax0 = axes[0, 0]
ax0.imshow(pred_disp, cmap=cmap5, norm=norm5, interpolation="nearest")
ax0.set_title("Prédiction supervised_e (source)", fontsize=9)
ax0.axis("off")

ax1 = axes[0, 1]
ax1.imshow(omap_disp, cmap=cmap5, norm=norm5, interpolation="nearest")
ax1.set_title("OOM rasterisé (depuis .omap)", fontsize=9)
ax1.axis("off")

ax2 = axes[1, 0]
ax2.imshow(diff_disp, cmap=cmap_diff, norm=norm_diff, interpolation="nearest")
ax2.set_title(f"Différences ({n_changed:,} px modifiés = {pct_chg:.2f}%)", fontsize=9)
ax2.axis("off")

# Légende différences
import matplotlib.patches as mpatches
legend_handles = [
    mpatches.Patch(color="#CCCCCC", label="identique"),
    mpatches.Patch(color=NODATA_COLOR, label="hors support"),
] + [
    mpatches.Patch(color=PALETTE[c], label=f"{CLASS_NAMES[c]} perdu")
    for c in [0, 2, 3, 4] if int(cm[c, [j for j,cj in enumerate(classes) if cj!=c]].sum()) > 0
]
ax2.legend(handles=legend_handles, loc="lower right", fontsize=7, framealpha=0.8)

# Matrice de confusion (heatmap log-normalisée)
ax3 = axes[1, 1]
cm_norm = cm.astype(float) / (cm.sum(axis=1, keepdims=True) + 1e-9)
im3 = ax3.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)
ax3.set_xticks(range(n_cls))
ax3.set_yticks(range(n_cls))
ax3.set_xticklabels([CLASS_NAMES[c] for c in classes], rotation=30, ha="right", fontsize=7)
ax3.set_yticklabels([CLASS_NAMES[c] for c in classes], fontsize=7)
ax3.set_xlabel("OOM rasterisé", fontsize=8)
ax3.set_ylabel("Prédiction source", fontsize=8)
ax3.set_title("Matrice de confusion (normalisée par ligne)", fontsize=9)
for i in range(n_cls):
    for j in range(n_cls):
        v = cm[i, j]
        if v > 0:
            ax3.text(j, i, f"{v:,}", ha="center", va="center", fontsize=6,
                     color="white" if cm_norm[i, j] > 0.5 else "black")
fig.colorbar(im3, ax=ax3, fraction=0.046, pad=0.04)

plt.tight_layout()
plt.savefig(str(OUT_PNG), dpi=120, bbox_inches="tight")
plt.close()
print(f"Planche : {OUT_PNG}")
print("Terminé.")
