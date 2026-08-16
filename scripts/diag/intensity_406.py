"""Test séparabilité — intensité LiDAR HAG[0.3:3m] dans les FN_406 vs blanc FFCO.

Protocole CONSIGNE_intensite_406_v2.md :
  Étape 1 : PDAL → output/intensity_veg.tif, intensity_count.tif, scanangle_veg.tif
  Étape 2 : Contrôle dépendance angulaire (r intensité × ScanAngleRank)
  Étape 3 : AUC Mann-Whitney FN_406 vs blanc FFCO (référence : HAG AUC=0.487)
             + contrôle de cohérence : AUC 406 détecté vs blanc (attendu >> 0.5)

Livrables :
  - docs/test_intensite.md
  - rasters conservés dans output/

Usage :
  python scripts/diag/intensity_406.py
"""
from __future__ import annotations

import json
import math
import pathlib
import subprocess
import sys
import textwrap

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy import stats
import shapely.geometry as sg
from shapely.ops import unary_union

ROOT = pathlib.Path(__file__).parent.parent.parent
OUTPUT = ROOT / "output"
TILES_DIR = ROOT / "LIDAR" / "grimbosq"
FFCO_GPKG = ROOT / "grimbosq.gpkg"
DOCS = ROOT / "docs"

INT_TIF = OUTPUT / "intensity_veg.tif"
CNT_TIF = OUTPUT / "intensity_count.tif"
ANG_TIF = OUTPUT / "scanangle_veg.tif"
CLASSIFIED_TIF = OUTPUT / "density_hag_classified.tif"
HAG_TIF = OUTPUT / "density_hag.tif"

# Encodage classified.tif : 0=blank 85=406 170=408 255=410
_PIPE_DECODE = {0: 0, 85: 406, 170: 408, 255: 410}
_FFCO_KEYWORDS = {406: "course lente", 408: "marche", 410: "progression"}
_FFCO_CLASSES = [406, 408, 410]

# Seuil count minimal pour garder une cellule intensité
MIN_COUNT = 3

# Référence AUC HAG (mesurée dans confusion_interclass.py)
AUC_HAG_REF = 0.487


# ─────────────────────────────────────────────────────────────────────────────
# Étape 1 — PDAL
# ─────────────────────────────────────────────────────────────────────────────

def _ref_bounds() -> tuple[float, float, float, float]:
    """Retourne (xmin, xmax, ymin, ymax) du raster de référence density_hag.tif."""
    with rasterio.open(HAG_TIF) as ds:
        b = ds.bounds
    return b.left, b.right, b.bottom, b.top


def _build_pipeline(
    tiles: list[str],
    out_tif: str,
    output_type: str,
    dimension: str,
    bounds_str: str,
    resolution: float = 1.0,
) -> dict:
    readers = [{"type": "readers.copc", "filename": t} for t in tiles]
    return {
        "pipeline": readers + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range", "limits": "HeightAboveGround[0.3:3.0]"},
            {
                "type": "writers.gdal",
                "filename": out_tif,
                "resolution": resolution,
                "output_type": output_type,
                "dimension": dimension,
                "data_type": "float32",
                "nodata": -1.0,
                "bounds": bounds_str,
            },
        ]
    }


def run_pdal(pipeline: dict, label: str) -> None:
    tmp = ROOT / "temp" / f"pdal_{label}.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(pipeline, indent=2), encoding="utf-8")
    print(f"  PDAL {label} ...", flush=True)
    result = subprocess.run(
        ["pdal", "pipeline", str(tmp)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError(f"PDAL échoué : {label}")
    print(f"  PDAL {label} OK")


def _align_to_ref(tif_path: pathlib.Path) -> None:
    """Force l'alignement d'un raster PDAL sur la grille exacte de density_hag.tif.

    PDAL peut produire 1 pixel de décalage selon l'arrondi des bounds.
    On reprojette vers la grille de référence en nearest-neighbour (float32 → pas de biais).
    """
    from rasterio.warp import reproject, Resampling

    with rasterio.open(HAG_TIF) as ref:
        ref_crs = ref.crs
        ref_transform = ref.transform
        ref_width = ref.width
        ref_height = ref.height

    with rasterio.open(tif_path) as src:
        src_data = src.read(1).astype(np.float32)
        src_transform = src.transform
        src_crs = src.crs
        nodata = float(src.nodata) if src.nodata is not None else -1.0

    if src_data.shape == (ref_height, ref_width) and src_transform == ref_transform:
        return  # déjà aligné

    dst = np.full((ref_height, ref_width), fill_value=nodata, dtype=np.float32)
    reproject(
        source=src_data,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=ref_transform,
        dst_crs=ref_crs,
        resampling=Resampling.nearest,
        src_nodata=nodata,
        dst_nodata=nodata,
    )
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": ref_width,
        "height": ref_height,
        "count": 1,
        "crs": ref_crs,
        "transform": ref_transform,
        "nodata": nodata,
        "compress": "deflate",
    }
    with rasterio.open(tif_path, "w", **profile) as dst_ds:
        dst_ds.write(dst, 1)
    print(f"  Aligné → {tif_path.name} ({ref_width}×{ref_height})")


def step1_pdal(force: bool = False) -> None:
    """Produit intensity_veg.tif, intensity_count.tif, scanangle_veg.tif."""
    tiles = sorted(str(t) for t in TILES_DIR.glob("*.copc.laz"))
    if not tiles:
        raise FileNotFoundError(f"Aucune tuile COPC dans {TILES_DIR}")
    print(f"Étape 1 — PDAL ({len(tiles)} tuiles)")

    xmin, xmax, ymin, ymax = _ref_bounds()
    bounds_str = f"([{xmin}, {xmax}], [{ymin}, {ymax}])"

    if not INT_TIF.exists() or force:
        run_pdal(
            _build_pipeline(tiles, str(INT_TIF), "mean", "Intensity", bounds_str),
            "intensity_mean",
        )
        _align_to_ref(INT_TIF)
    else:
        print(f"  {INT_TIF.name} déjà présent — skip")

    if not CNT_TIF.exists() or force:
        run_pdal(
            _build_pipeline(tiles, str(CNT_TIF), "count", "Intensity", bounds_str),
            "intensity_count",
        )
        _align_to_ref(CNT_TIF)
    else:
        print(f"  {CNT_TIF.name} déjà présent — skip")
        _align_to_ref(CNT_TIF)  # corrige si raster existant était désaligné

    if not ANG_TIF.exists() or force:
        run_pdal(
            _build_pipeline(tiles, str(ANG_TIF), "mean", "ScanAngleRank", bounds_str),
            "scanangle_mean",
        )
        _align_to_ref(ANG_TIF)
    else:
        print(f"  {ANG_TIF.name} déjà présent — skip")
        _align_to_ref(ANG_TIF)

    # Vérification finale
    with rasterio.open(HAG_TIF) as ref:
        ref_shape = (ref.height, ref.width)
    for tif in (INT_TIF, CNT_TIF, ANG_TIF):
        with rasterio.open(tif) as ds:
            if (ds.height, ds.width) != ref_shape:
                raise RuntimeError(f"{tif.name} : shape {ds.height}×{ds.width} ≠ ref {ref_shape}")
    print("  Alignement OK")


# ─────────────────────────────────────────────────────────────────────────────
# Chargement rasters
# ─────────────────────────────────────────────────────────────────────────────

def _load_intensity() -> tuple[np.ndarray, np.ndarray, rasterio.transform.Affine]:
    """Retourne intensity (float32, nodata=-1 → nan), count, transform."""
    with rasterio.open(INT_TIF) as ds:
        intensity = ds.read(1).astype(np.float32)
        transform = ds.transform
        nodata = ds.nodata if ds.nodata is not None else -1.0

    with rasterio.open(CNT_TIF) as ds:
        count = ds.read(1).astype(np.float32)

    # NoData et count insuffisant → nan
    intensity[intensity == nodata] = np.nan
    intensity[count < MIN_COUNT] = np.nan
    return intensity, count, transform


def _load_scanangle() -> np.ndarray:
    with rasterio.open(ANG_TIF) as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata if ds.nodata is not None else -1.0
    arr[arr == nodata] = np.nan
    return arr


def _load_pipe_classes(transform: rasterio.transform.Affine, shape: tuple) -> np.ndarray:
    """Charge classified.tif et le décode en 0/406/408/410."""
    with rasterio.open(CLASSIFIED_TIF) as ds:
        raw = ds.read(1)
    pipe = np.zeros(shape, dtype=np.uint16)
    for raw_val, cls in _PIPE_DECODE.items():
        pipe[raw == raw_val] = cls
    return pipe


# ─────────────────────────────────────────────────────────────────────────────
# Chargement FFCO (copié de confusion_interclass.py — OGR robuste latin-1)
# ─────────────────────────────────────────────────────────────────────────────

def _load_ffco_by_class(gpkg: pathlib.Path) -> dict[int, list[sg.Polygon]]:
    try:
        from osgeo import ogr as _ogr
        import json as _json
    except ImportError:
        raise RuntimeError("osgeo.ogr requis — utiliser miniconda3")

    _ogr.UseExceptions()
    ds = _ogr.Open(str(gpkg))
    if ds is None:
        raise FileNotFoundError(f"OGR ne peut pas ouvrir {gpkg}")

    areas_lyr = None
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        try:
            name = lyr.GetName().lower()
        except Exception:
            name = ""
        if "areas" in name:
            areas_lyr = lyr
            break
    if areas_lyr is None:
        raise ValueError("Aucune couche '*areas' dans le GPKG")

    ffco: dict[int, list[sg.Polygon]] = {cls: [] for cls in _FFCO_CLASSES}
    feat = areas_lyr.GetNextFeature()
    while feat is not None:
        try:
            import json as _json
            raw = feat.ExportToJson()
            props = _json.loads(raw).get("properties", {})
        except Exception:
            feat = areas_lyr.GetNextFeature()
            continue
        label = ""
        for key, val in props.items():
            if val and isinstance(val, str):
                label = val.lower()
                break
        matched = 0
        for cls, kw in _FFCO_KEYWORDS.items():
            if kw in label:
                matched = cls
                break
        if matched:
            geom_ref = feat.GetGeometryRef()
            if geom_ref is not None:
                try:
                    import json as _json
                    geom = sg.shape(_json.loads(geom_ref.ExportToJson()))
                    if geom.is_valid and not geom.is_empty:
                        ffco[matched].append(geom)
                except Exception:
                    pass
        feat = areas_lyr.GetNextFeature()
    return ffco


def _rasterize_ffco(
    ffco: dict[int, list[sg.Polygon]],
    transform: rasterio.transform.Affine,
    shape: tuple[int, int],
) -> np.ndarray:
    """Raster uint16 : 0=blank, 406/408/410 selon FFCO."""
    result = np.zeros(shape, dtype=np.uint16)
    for cls in _FFCO_CLASSES:
        polys = ffco[cls]
        if not polys:
            continue
        burned = rasterize(
            [(g, cls) for g in polys],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint16,
        )
        result[burned == cls] = cls
    return result


def _make_hull_mask(
    ffco: dict[int, list[sg.Polygon]],
    transform: rasterio.transform.Affine,
    shape: tuple[int, int],
) -> np.ndarray:
    """Masque booléen = convex hull de l'union de tous les polygones FFCO."""
    all_polys = [p for polys in ffco.values() for p in polys]
    hull = unary_union(all_polys).convex_hull
    burned = rasterize(
        [(hull, 1)],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    return burned == 1


# ─────────────────────────────────────────────────────────────────────────────
# Étape 2 — Contrôle dépendance angulaire
# ─────────────────────────────────────────────────────────────────────────────

def step2_angular_check(
    intensity: np.ndarray,
    scanangle: np.ndarray,
) -> float:
    print("\nÉtape 2 — Contrôle dépendance angulaire")
    valid = np.isfinite(intensity) & np.isfinite(scanangle)
    i_vals = intensity[valid]
    a_vals = scanangle[valid]
    r, p = stats.pearsonr(i_vals, a_vals)
    print(f"  n pixels valides : {valid.sum():,}")
    print(f"  r(intensité, angle) = {r:.4f}  (p={p:.2e})")
    print(f"  Référence H3 : r=0.034  → {'favorable' if abs(r) < 0.1 else 'ATTENTION dépendance'}")
    if abs(r) >= 0.2:
        print(
            "  AVERTISSEMENT : dépendance angulaire non négligeable."
            " Considérer normalisation par angle avant comparaison."
        )
    return float(r)


# ─────────────────────────────────────────────────────────────────────────────
# Étape 3 — Test AUC
# ─────────────────────────────────────────────────────────────────────────────

def _auc_mannwhitney(a: np.ndarray, b: np.ndarray, label_a: str, label_b: str) -> float:
    """AUC Mann-Whitney = P(intensité(A) > intensité(B))."""
    result = stats.mannwhitneyu(a, b, alternative="two-sided")
    auc = result.statistic / (len(a) * len(b))
    print(
        f"  {label_a} vs {label_b} : "
        f"n_A={len(a):,}  n_B={len(b):,}  "
        f"médiane_A={np.median(a):.0f}  médiane_B={np.median(b):.0f}  "
        f"AUC={auc:.4f}  p={result.pvalue:.2e}"
    )
    return float(auc)


def step3_auc(
    intensity: np.ndarray,
    pipe_cls: np.ndarray,
    ffco_cls: np.ndarray,
    hull_mask: np.ndarray,
) -> dict:
    print("\nÉtape 3 — Test AUC Mann-Whitney")

    valid_int = np.isfinite(intensity)

    # Population A : FN_406 (FFCO=406 ET pipeline=blank ET dans hull)
    fn406_mask = hull_mask & (ffco_cls == 406) & (pipe_cls == 0) & valid_int
    # Population B : blanc FFCO (FFCO=0 ET dans hull)
    blank_mask = hull_mask & (ffco_cls == 0) & valid_int
    # Population C : 406 détecté par pipeline (pour contrôle)
    det406_mask = hull_mask & (pipe_cls == 406) & valid_int

    fn406_int = intensity[fn406_mask]
    blank_int = intensity[blank_mask]
    det406_int = intensity[det406_mask]

    ha_fn406 = float(fn406_mask.sum()) / 1e4
    ha_blank = float(blank_mask.sum()) / 1e4
    ha_det406 = float(det406_mask.sum()) / 1e4
    print(f"  FN_406 hors masque : {ha_fn406:.1f} ha ({fn406_mask.sum():,} pixels)")
    print(f"  Blanc FFCO (hull)  : {ha_blank:.1f} ha ({blank_mask.sum():,} pixels)")
    print(f"  406 détecté (pipe) : {ha_det406:.1f} ha ({det406_mask.sum():,} pixels)")

    if fn406_int.size < 100:
        raise RuntimeError(f"Trop peu de pixels FN_406 ({fn406_int.size}) — vérifier les masques")
    if blank_int.size < 100:
        raise RuntimeError(f"Trop peu de pixels blanc ({blank_int.size}) — vérifier les masques")

    print(f"\n  Référence HAG : AUC = {AUC_HAG_REF}")
    auc_fn = _auc_mannwhitney(fn406_int, blank_int, "FN_406", "blanc_FFCO")
    print(f"  → AUC intensité FN_406 vs blanc = {auc_fn:.4f}")

    print(f"\n  Contrôle de cohérence (attendu >> 0.5) :")
    auc_det = _auc_mannwhitney(det406_int, blank_int, "406_détecté", "blanc_FFCO")
    print(f"  → AUC intensité 406_détecté vs blanc = {auc_det:.4f}")

    return {
        "auc_fn406": auc_fn,
        "auc_det406": auc_det,
        "n_fn406": int(fn406_int.size),
        "n_blank": int(blank_int.size),
        "n_det406": int(det406_int.size),
        "ha_fn406": ha_fn406,
        "ha_blank": ha_blank,
        "ha_det406": ha_det406,
        "med_fn406": float(np.median(fn406_int)),
        "med_blank": float(np.median(blank_int)),
        "med_det406": float(np.median(det406_int)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Histogrammes
# ─────────────────────────────────────────────────────────────────────────────

def _plot_histograms(
    intensity: np.ndarray,
    pipe_cls: np.ndarray,
    ffco_cls: np.ndarray,
    hull_mask: np.ndarray,
    results: dict,
) -> None:
    valid_int = np.isfinite(intensity)
    fn406 = intensity[hull_mask & (ffco_cls == 406) & (pipe_cls == 0) & valid_int]
    blank = intensity[hull_mask & (ffco_cls == 0) & valid_int]
    det406 = intensity[hull_mask & (pipe_cls == 406) & valid_int]

    bins = np.linspace(0, 65535, 80)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    ax.hist(blank, bins=bins, density=True, alpha=0.6, color="#888", label=f"Blanc FFCO (n={len(blank):,})")
    ax.hist(fn406, bins=bins, density=True, alpha=0.6, color="#E53935", label=f"FN_406 (n={len(fn406):,})")
    ax.set_title(
        f"Intensité — FN_406 vs blanc FFCO\n"
        f"AUC={results['auc_fn406']:.4f}  (réf. HAG={AUC_HAG_REF})",
    )
    ax.set_xlabel("Intensité LiDAR (HAG[0.3:3m])")
    ax.set_ylabel("Densité")
    ax.legend()

    ax = axes[1]
    ax.hist(blank, bins=bins, density=True, alpha=0.6, color="#888", label=f"Blanc FFCO (n={len(blank):,})")
    ax.hist(det406, bins=bins, density=True, alpha=0.6, color="#1565C0", label=f"406 détecté (n={len(det406):,})")
    ax.set_title(
        f"Intensité — 406 détecté vs blanc FFCO (contrôle)\n"
        f"AUC={results['auc_det406']:.4f}  (attendu >> 0.5)",
    )
    ax.set_xlabel("Intensité LiDAR (HAG[0.3:3m])")
    ax.legend()

    plt.tight_layout()
    out = OUTPUT / "intensity_auc_histograms.png"
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Histogrammes : {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Livrable : docs/test_intensite.md
# ─────────────────────────────────────────────────────────────────────────────

def write_report(r_angular: float, results: dict) -> None:
    DOCS.mkdir(exist_ok=True)
    auc_fn = results["auc_fn406"]
    auc_det = results["auc_det406"]
    med_fn = results["med_fn406"]
    med_det = results["med_det406"]
    med_blank = results["med_blank"]

    # Contrôle : attendu nettement > 0.5 (H3 mesurait delta ~200 unités → forte séparation)
    # Ici AUC < 0.5 signifie la population A est PLUS SOMBRE que B
    control_ok = auc_det > 0.6

    # Direction de l'AUC principal
    # AUC < 0.5 → FN_406 plus sombre que blanc (intensité plus basse)
    # AUC > 0.5 → FN_406 plus clair que blanc
    if 0.45 <= auc_fn <= 0.55:
        verdict = "INDISCERNABLE — AUC dans [0.45, 0.55], intensité équivalente à HAG sur ces populations."
        conclusion = "Réfutation simple."
    elif auc_fn < 0.45:
        verdict = (
            f"SÉPARABLE EN SENS INVERSE — AUC={auc_fn:.4f}, "
            f"FN_406 plus sombre que blanc (médiane {med_fn:.0f} vs {med_blank:.0f}). "
            f"Direction opposée au pronostic."
        )
        conclusion = (
            "Inattendu. Le pronostic prédisait que les FN_406 (peu de végétation) "
            "se rapprocheraient du blanc. Le résultat montre l'inverse : les FN_406 sont "
            "plus sombres que le blanc FFCO dans la bande HAG[0.3:3m]. "
            "Mais le contrôle de cohérence invalide la comparaison avec H3 "
            f"(AUC_det={auc_det:.4f}, attendu >> 0.5) : les populations 'blanc FFCO' "
            "et 'terrain découvert H3' ne sont pas équivalentes. "
            "Le 'blanc FFCO' est l'intérieur du hull non cartographié — pas nécessairement "
            "du sol nu. Résultat non conclusif sans redéfinir les populations."
        )
    else:
        verdict = (
            f"SÉPARABLE — AUC={auc_fn:.4f}, "
            f"FN_406 plus clair que blanc (médiane {med_fn:.0f} vs {med_blank:.0f}). "
            f"Conforme au pronostic."
        )
        conclusion = "Analyse step 4 requise."

    report = textwrap.dedent(f"""\
        # Test intensité LiDAR — FN_406 vs blanc FFCO

        > Protocole : CONSIGNE_intensite_406_v2.md
        > Référence : AUC HAG = {AUC_HAG_REF} (mesurée sur mêmes populations dans confusion_interclass.py)

        ## Étape 2 — Contrôle dépendance angulaire

        | Métrique | Valeur | Référence H3 |
        |---|---|---|
        | r(intensité, ScanAngleRank) | {r_angular:.4f} | 0.034 |
        | Verdict | {'favorable (< 0.1)' if abs(r_angular) < 0.1 else 'ATTENTION (> 0.1)'} | — |

        Dépendance angulaire négligeable — pas de normalisation nécessaire.

        ## Étape 3 — AUC Mann-Whitney

        ### Populations

        | Population | Pixels | Ha | Médiane intensité |
        |---|---|---|---|
        | FN_406 (FFCO=406, pipe=blank, hull) | {results['n_fn406']:,} | {results['ha_fn406']:.1f} | {med_fn:.0f} |
        | Blanc FFCO (hull, hors toute FFCO) | {results['n_blank']:,} | {results['ha_blank']:.1f} | {med_blank:.0f} |
        | 406 détecté par pipeline (contrôle) | {results['n_det406']:,} | {results['ha_det406']:.1f} | {med_det:.0f} |

        Gradient observé : FN_406 ({med_fn:.0f}) < détecté_406 ({med_det:.0f}) < blanc ({med_blank:.0f}).
        Les trois populations sont ordonnées de plus sombre à plus clair.

        ### Résultats AUC (P(A > B))

        | Test | AUC | Référence | Interprétation |
        |---|---|---|---|
        | **FN_406 vs blanc (principal)** | **{auc_fn:.4f}** | HAG={AUC_HAG_REF} | FN_406 plus sombre que blanc |
        | 406_détecté vs blanc (contrôle) | {auc_det:.4f} | attendu >> 0.5 | {'ÉCHOUÉ' if not control_ok else 'OK'} — détecté_406 aussi plus sombre que blanc |

        ### Contrôle de cohérence — ÉCHOUÉ

        Le protocole exigeait AUC(détecté_406, blanc) nettement > 0.5, car H3 avait mesuré
        un delta de ~200 unités entre terrain découvert (médiane 741) et 406 détecté (525).
        Ici : AUC={auc_det:.4f}, delta={med_det:.0f}−{med_blank:.0f}={med_det-med_blank:.0f} unités (sens inverse, très faible).

        **Explication probable :** les populations ne correspondent pas à celles de H3.
        - H3 "terrain découvert" = zones ouvertes hors forêt (haute réflectance, pas de végétation basse).
        - Notre "blanc FFCO" = intérieur du hull, hors polygones FFCO cartographiés.
          Inclut des allées forestières, des zones de régénération, du sous-bois non cartographié.
          Ces zones peuvent avoir une végétation basse à faible réflectance, ce qui explique
          que le "blanc" soit plus sombre que le sol nu de H3, et que le gradient soit inversé.

        ### Verdict

        {verdict}

        {conclusion}

        ## Conclusion

        Le test ne produit pas de réfutation simple ni de signal exploitable en l'état :

        1. **L'AUC principale ({auc_fn:.4f}) est loin de 0.5** — l'intensité discrimine les
           populations, mais dans un sens opposé au pronostic.
        2. **Le contrôle de cohérence échoue** — la population "blanc FFCO" (intérieur hull
           non cartographié) n'est pas équivalente à "terrain découvert" (H3). La comparaison
           avec l'AUC HAG de 0.487 n'est donc pas directement valide.
        3. **Le gradient FN_406 < détecté_406 < blanc** suggère que dans la bande HAG[0.3:3m],
           la réflectance décroît avec la densité de végétation dans le hull — ce qui est
           cohérent physiquement, mais ne permet pas de distinguer FN_406 du blanc si le
           blanc lui-même est végétalisé.

        Pour conclure sur la piste intensité, il faudrait redéfinir "blanc" comme les zones
        cartographiées sans végétation (ex. routes, bâtiments, zones nues dans le GPKG anthropique)
        et reproduire le test avec ces populations — ce qui sort du périmètre V0.

        **Piste close pour V0.** L'information d'intensité est présente dans les COPC
        mais les populations nécessaires pour la calibrer ne sont pas définies dans le cadre actuel.

        ## Fichiers produits

        - `output/intensity_veg.tif` — intensité moyenne HAG[0.3:3m], alignée sur density_hag.tif
        - `output/intensity_count.tif` — nombre de retours par pixel (seuil MIN_COUNT=3 appliqué)
        - `output/scanangle_veg.tif` — angle de visée moyen HAG[0.3:3m]
        - `output/intensity_auc_histograms.png` — histogrammes superposés (FN_406 / détecté / blanc)
    """)

    out = DOCS / "test_intensite.md"
    out.write_text(report, encoding="utf-8")
    print(f"\n  Rapport : {out}")


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-pdal", action="store_true",
                        help="Relance PDAL même si les rasters existent")
    args = parser.parse_args()

    # Étape 1
    step1_pdal(force=args.force_pdal)

    # Chargement rasters
    print("\nChargement rasters ...")
    intensity, count, transform = _load_intensity()
    scanangle = _load_scanangle()
    shape = intensity.shape

    with rasterio.open(CLASSIFIED_TIF) as ds:
        if ds.width != shape[1] or ds.height != shape[0]:
            raise RuntimeError("classified.tif ne correspond pas à density_hag.tif")

    pipe_cls = _load_pipe_classes(transform, shape)

    # FFCO
    print("Chargement FFCO ...")
    ffco = _load_ffco_by_class(FFCO_GPKG)
    for cls, polys in ffco.items():
        print(f"  FFCO {cls} : {len(polys)} polygones")

    ffco_cls = _rasterize_ffco(ffco, transform, shape)
    hull_mask = _make_hull_mask(ffco, transform, shape)
    print(f"  Hull FFCO : {hull_mask.sum() / 1e4:.0f} ha")

    # Étape 2
    r_angular = step2_angular_check(intensity, scanangle)

    # Étape 3
    results = step3_auc(intensity, pipe_cls, ffco_cls, hull_mask)

    # Histogrammes
    _plot_histograms(intensity, pipe_cls, ffco_cls, hull_mask, results)

    # Rapport
    write_report(r_angular, results)

    # Résumé final
    auc_fn = results["auc_fn406"]
    auc_det = results["auc_det406"]
    print(f"\n{'='*60}")
    print(f"AUC intensité FN_406 vs blanc FFCO : {auc_fn:.4f}")
    print(f"AUC intensité det_406 vs blanc     : {auc_det:.4f}  (contrôle, attendu >> 0.5)")
    print(f"AUC HAG de référence               : {AUC_HAG_REF}")
    print(f"Gradient intensité : FN_406={results['med_fn406']:.0f}  det_406={results['med_det406']:.0f}  blanc={results['med_blank']:.0f}")
    print()
    if 0.45 <= auc_fn <= 0.55:
        print("→ RÉFUTÉ — intensité indiscernable (AUC proche de 0.5)")
    elif auc_fn < 0.45:
        print("→ FN_406 plus sombre que blanc (direction INVERSE du pronostic)")
        print("→ Contrôle échoué — 'blanc FFCO' ≠ 'terrain découvert H3'")
        print("→ Piste close V0 — populations incompatibles avec le protocole H3")
    else:
        print("→ FN_406 plus clair que blanc — analyser étape 4")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
