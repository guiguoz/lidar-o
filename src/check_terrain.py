"""check — pre-run validation of tiles, CRS, georef and optional data."""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

log = logging.getLogger(__name__)

# (module_name, install_hint)
_REQUIRED_MODULES: list[tuple[str, str]] = [
    ("pyproj",    "conda install -c conda-forge pyproj"),
    ("geopandas", "conda install -c conda-forge geopandas"),
    ("shapely",   "conda install -c conda-forge shapely"),
    ("pdal",      "conda install -c conda-forge python-pdal pdal"),
    ("rasterio",  "conda install -c conda-forge rasterio"),
    ("ezdxf",     "pip install ezdxf"),
    ("yaml",      "pip install pyyaml"),
    ("requests",  "pip install requests"),
]


def check_deps() -> bool:
    """Verify required Python modules are importable (no import — find_spec only).

    Returns True if all critical modules are present.
    """
    missing = [
        (mod, hint)
        for mod, hint in _REQUIRED_MODULES
        if importlib.util.find_spec(mod) is None
    ]

    if missing:
        log.error("ERREUR : modules Python manquants :")
        for mod, hint in missing:
            log.error("  %-12s  →  %s", mod, hint)
        log.error(
            "Note : geopandas, shapely, pdal, rasterio nécessitent conda — "
            "pas pip seul. Voir README § Requirements."
        )
        return False

    # KP binary — optional, info only
    kp = os.environ.get("KP_BINARY") or shutil.which("pullauta")
    if not kp:
        log.info("Info : binaire Karttapullautin (pullauta) absent — relief non disponible")

    return True

# IGN LiDAR HD filename pattern: LHD_FXX_XXXX_YYYY_PTS_LAMB93_IGN69.copc.laz
_IGN_RE = re.compile(r"LHD_FXX_(\d{4})_(\d{4})_PTS_LAMB93_IGN69\.(?:copc\.)?laz$")


def _ign_tile_extent(filename: str) -> tuple[float, float, float, float] | None:
    """Return (xmin, ymin, xmax, ymax) for an IGN tile filename, or None if not IGN."""
    m = _IGN_RE.search(pathlib.Path(filename).name)
    if not m:
        return None
    xx, yy = int(m.group(1)), int(m.group(2))
    # Tile covers x ∈ [xx*1000, (xx+1)*1000) and y ∈ [(yy-1)*1000, yy*1000)
    return (xx * 1000, (yy - 1) * 1000, (xx + 1) * 1000, yy * 1000)


def _laz_metadata(path: pathlib.Path) -> dict | None:
    """Read LAS/LAZ header via pdal info --metadata. Returns metadata dict or None."""
    try:
        r = subprocess.run(
            ["pdal", "info", "--metadata", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout).get("metadata", {})
    except Exception:
        return None


def _bbox_from_metadata(meta: dict) -> tuple[float, float, float, float] | None:
    try:
        return (float(meta["minx"]), float(meta["miny"]),
                float(meta["maxx"]), float(meta["maxy"]))
    except (KeyError, TypeError, ValueError):
        return None


def _epsg_from_metadata(meta: dict) -> int | None:
    """Extract EPSG code from LAS/LAZ SRS metadata, or None."""
    try:
        from pyproj import CRS
        srs = meta.get("srs", {})
        wkt = srs.get("compoundwkt") or srs.get("wkt", "")
        if not wkt:
            return None
        return CRS.from_wkt(wkt).to_epsg()
    except Exception:
        return None


def _tile_extent(path: pathlib.Path) -> tuple[float, float, float, float] | None:
    """Return (xmin, ymin, xmax, ymax) for a LiDAR tile.

    Reads LAZ/LAS header metadata via pdal info (universal — any naming convention).
    Falls back to IGN filename parsing only if metadata read fails.
    """
    meta = _laz_metadata(path)
    if meta:
        bbox = _bbox_from_metadata(meta)
        if bbox is not None:
            return bbox
    return _ign_tile_extent(path.name)


def _tiles_union(extents: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    xmin = min(e[0] for e in extents)
    ymin = min(e[1] for e in extents)
    xmax = max(e[2] for e in extents)
    ymax = max(e[3] for e in extents)
    return xmin, ymin, xmax, ymax


def _coverage_pct(
    bbox: tuple[float, float, float, float],
    tiles_extent: tuple[float, float, float, float],
) -> float:
    """Intersection area of tiles_extent with bbox, as % of bbox area."""
    bx1, by1, bx2, by2 = bbox
    tx1, ty1, tx2, ty2 = tiles_extent

    ix1 = max(bx1, tx1)
    iy1 = max(by1, ty1)
    ix2 = min(bx2, tx2)
    iy2 = min(by2, ty2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    bbox_area = (bx2 - bx1) * (by2 - by1)
    if bbox_area == 0:
        return 100.0

    return 100.0 * (ix2 - ix1) * (iy2 - iy1) / bbox_area


def _validate_georef_xml(path: pathlib.Path) -> bool:
    """Return True if file exists and contains a valid <georeferencing> block."""
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r"(<georeferencing\b.*?</georeferencing>)", text, re.DOTALL)
        if not m:
            return False
        geo = ET.fromstring(m.group(1))
        ref = geo.find(".//ref_point")
        return ref is not None and ref.get("x") is not None
    except Exception:
        return False


def cmd_check(
    terrain: str,
    cfg: dict,
    root: pathlib.Path,
    *,
    skip_check: bool = False,
    lidar_dir: pathlib.Path | None = None,
) -> bool:
    """Run all pre-flight checks for terrain. Returns True if all critical checks pass.

    Errors:  tiles absent, coverage < 90 %, georef XML missing/invalid
    Warnings: BD TOPO absent when departement declared, CRS mismatch
    Info:     KP output absent (relief optional)

    lidar_dir: override for the tiles directory (defaults to root/LIDAR).
               When supplied by --tiles-dir, tile presence check uses that path.
    """
    if skip_check:
        return True

    if not check_deps():
        return False

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
    bbox = terrain_cfg.get("bbox")
    crs_declared = terrain_cfg.get("crs", "")
    dept = terrain_cfg.get("departement")
    all_ok = True

    # ── 1. LiDAR tiles ────────────────────────────────────────────────────────

    lidar_dir = lidar_dir if lidar_dir is not None else root / "LIDAR"
    seen: set[str] = set()
    unique_tiles: list[pathlib.Path] = []
    for f in sorted(lidar_dir.glob("*.copc.laz")) + sorted(lidar_dir.glob("*.laz")):
        if f.name not in seen:
            seen.add(f.name)
            unique_tiles.append(f)

    if not unique_tiles:
        log.error("ERREUR : aucune dalle LiDAR dans %s", lidar_dir)
        log.error("  → python main.py tiles %s", terrain)
        return False

    log.info("check : %d dalle(s) LiDAR", len(unique_tiles))

    # ── 2. Tile coverage vs declared bbox ─────────────────────────────────────

    tile_metadatas: dict[pathlib.Path, dict | None] = {
        f: _laz_metadata(f) for f in unique_tiles
    }
    tile_extents: dict[pathlib.Path, tuple[float, float, float, float] | None] = {
        f: (_bbox_from_metadata(m) if m else None) or _ign_tile_extent(f.name)
        for f, m in tile_metadatas.items()
    }
    extents = [e for e in tile_extents.values() if e is not None]
    unresolved = [f for f, e in tile_extents.items() if e is None]

    if unresolved:
        log.warning(
            "check : %d dalle(s) sans emprise lisible (pdal info a échoué) : %s",
            len(unresolved), ", ".join(f.name for f in unresolved),
        )

    if bbox is not None:
        if extents:
            tiles_ext = _tiles_union(extents)
            cov = _coverage_pct(tuple(bbox), tiles_ext)

            if cov < 90.0:
                bx1, by1, bx2, by2 = bbox
                tx1, ty1, tx2, ty2 = tiles_ext
                log.error("ERREUR : les dalles ne couvrent pas la bbox déclarée.")
                log.error("  bbox config   : X %d–%d  Y %d–%d", bx1, bx2, by1, by2)
                log.error("  dalles LIDAR/ : X %d–%d  Y %d–%d", tx1, tx2, ty1, ty2)
                log.error("  recouvrement  : %.0f %%", cov)
                log.error("    Vérifiez avec : python main.py tiles %s", terrain)
                all_ok = False
            else:
                log.info("check : recouvrement bbox %.0f %% (OK)", cov)
        else:
            log.warning("check : recouvrement non vérifié — aucune emprise disponible")

    # ── 3. CRS consistency ────────────────────────────────────────────────────

    if crs_declared:
        declared_epsg = int(crs_declared.split(":")[-1]) if ":" in crs_declared else None
        if declared_epsg:
            mismatched = [
                (f.name, epsg)
                for f, m in tile_metadatas.items()
                if m and (epsg := _epsg_from_metadata(m)) and epsg != declared_epsg
            ]
            if mismatched:
                for fname, tile_epsg in mismatched:
                    log.warning(
                        "check : CRS dalle %s → EPSG:%d ≠ config EPSG:%d",
                        fname, tile_epsg, declared_epsg,
                    )

    ign_extents = [e for f, e in tile_extents.items()
                   if e is not None and _ign_tile_extent(f.name) is not None]
    if crs_declared and ign_extents:
        if "2154" not in crs_declared:
            log.warning(
                "check : CRS déclaré %s mais dalles IGN Lambert-93 — vérifier config.yaml",
                crs_declared,
            )

    # ── 4. Georef XML ─────────────────────────────────────────────────────────

    georef_path = root / "assets" / f"georef_{terrain}.xml"
    if _validate_georef_xml(georef_path):
        log.info("check : %s présent et valide (OK)", georef_path.name)
    else:
        log.error("ERREUR : %s absent ou invalide", georef_path)
        log.error("  → python main.py init %s --center lat lon", terrain)
        all_ok = False

    # ── 5. BD TOPO (avertissement) ────────────────────────────────────────────

    if dept:
        data_dir = root / "data"
        bdtopo_cache = data_dir / f"{terrain}_bdtopo.gpkg"
        bdtopo_raw = sorted((data_dir / "bdtopo").glob(f"*D0{dept}*.gpkg")) if (data_dir / "bdtopo").exists() else []
        if not bdtopo_cache.exists() and not bdtopo_raw:
            log.warning(
                "Avertissement : BD TOPO introuvable pour département %s "
                "(masquage anthropique désactivé — pipeline continue sans)",
                dept,
            )

    # ── 6. Karttapullautin (information) ─────────────────────────────────────

    out_kp = root / f"out_kp_{terrain}"
    if not out_kp.exists():
        out_kp = root / "out_kp"
    if not out_kp.exists() or not any(out_kp.glob("*.dxf")):
        log.info("Info : out_kp/ absent — relief non inclus (optionnel)")

    return all_ok
