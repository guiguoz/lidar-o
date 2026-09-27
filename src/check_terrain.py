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


REQUIRED_BDTOPO_LAYERS = [
    "troncon_de_route",
    "zone_d_habitation",
    "batiment",
    "plan_d_eau",
    "cours_d_eau",
    "surface_de_transport",
    "zone_de_vegetation",
]


def cmd_check(
    terrain: str,
    cfg: dict,
    root: pathlib.Path,
    *,
    skip_check: bool = False,
    lidar_dir: pathlib.Path | None = None,
    verbose: bool = True,
    force_kp_version: bool = False,
) -> bool:
    """Contrôle pré-run complet du terrain. Retourne True si projet prêt.

    Affiche le rapport structuré sur stdout si verbose=True.
    """
    if skip_check:
        return True

    if not check_deps():
        return False

    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})
    bbox = terrain_cfg.get("bbox")
    crs_declared = terrain_cfg.get("crs", "")
    all_ok = True

    def _out(msg: str = "") -> None:
        if verbose:
            print(msg)

    _out(f"Lidar'O — contrôle du projet")
    _out("=" * 44)

    # ── Emprise ───────────────────────────────────────────────────────────────

    _out()
    _out("Emprise")

    lidar_dir_resolved: pathlib.Path
    lidar_dir_cfg = terrain_cfg.get("lidar_dir")
    if lidar_dir is not None:
        lidar_dir_resolved = lidar_dir
    elif lidar_dir_cfg:
        lidar_dir_resolved = pathlib.Path(lidar_dir_cfg)
    else:
        lidar_dir_resolved = root / "LIDAR" / terrain

    if bbox:
        bx1, by1, bx2, by2 = bbox
        w_km = (bx2 - bx1) / 1000
        h_km = (by2 - by1) / 1000
        crs_short = crs_declared.split(":")[-1] if ":" in crs_declared else crs_declared
        emprise_str = (
            f"{int(bx1)} – {int(bx2)} × {int(by1)} – {int(by2)}"
            f" · {w_km:.0f} × {h_km:.0f} km"
            f" · {_crs_label(crs_declared)}"
        )
        _out(f"  ✓ {emprise_str}")
    else:
        _out("  ⚠ bbox non déclarée dans config.yaml")

    # ── LiDAR HD ──────────────────────────────────────────────────────────────

    _out()
    _out("LiDAR HD")

    seen: set[str] = set()
    unique_tiles: list[pathlib.Path] = []
    if lidar_dir_resolved.exists():
        for f in sorted(lidar_dir_resolved.glob("*.copc.laz")) + sorted(lidar_dir_resolved.glob("*.laz")):
            if f.name not in seen:
                seen.add(f.name)
                unique_tiles.append(f)

    if not unique_tiles:
        _out(f"  ✗ aucune dalle LiDAR dans {lidar_dir_resolved}")
        _out(f"    Action : python main.py setup {terrain}")
        log.error("check : aucune dalle LiDAR dans %s", lidar_dir_resolved)
        all_ok = False
    else:
        tile_metadatas: dict[pathlib.Path, dict | None] = {
            f: _laz_metadata(f) for f in unique_tiles
        }
        tile_extents: dict[pathlib.Path, tuple[float, float, float, float] | None] = {
            f: (_bbox_from_metadata(m) if m else None) or _ign_tile_extent(f.name)
            for f, m in tile_metadatas.items()
        }
        extents = [e for e in tile_extents.values() if e is not None]

        if bbox is not None and extents:
            tiles_ext = _tiles_union(extents)
            cov = _coverage_pct(tuple(bbox), tiles_ext)

            try:
                from src.providers import find_tiles
                expected_tiles, _ = find_tiles(tuple(bbox), crs_declared)
                n_expected = len(expected_tiles)
            except Exception:
                n_expected = 0

            n_present = len(unique_tiles)
            if n_expected > 0:
                tile_summary = f"{n_present}/{n_expected} dalles"
            else:
                tile_summary = f"{n_present} dalle(s)"

            agencement = _check_agencement(extents)

            if cov >= 90.0:
                _out(f"  ✓ {tile_summary} · {agencement}")
            else:
                missing_n = max(0, n_expected - n_present) if n_expected > 0 else 0
                _out(f"  ✗ {tile_summary} · couverture {cov:.0f} % (< 90 %)")
                if missing_n > 0:
                    _out(f"    {missing_n} dalle(s) manquante(s)")
                _out(f"    Action : python main.py tiles {terrain}")
                log.error("check : couverture bbox %.0f %% (< 90 %%)", cov)
                all_ok = False
        else:
            _out(f"  ✓ {len(unique_tiles)} dalle(s) (emprise non vérifiée)")

        _out(f"  {lidar_dir_resolved}")

        # CRS consistency
        if crs_declared:
            declared_epsg = int(crs_declared.split(":")[-1]) if ":" in crs_declared else None
            if declared_epsg:
                for f, m in tile_metadatas.items():
                    if m:
                        tile_epsg = _epsg_from_metadata(m)
                        if tile_epsg and tile_epsg != declared_epsg:
                            log.warning(
                                "check : CRS dalle %s → EPSG:%d ≠ config EPSG:%d",
                                f.name, tile_epsg, declared_epsg,
                            )

    # ── BD TOPO ───────────────────────────────────────────────────────────────

    _out()
    _out("BD TOPO")

    bdtopo_path_cfg = terrain_cfg.get("bdtopo_path")
    dept = terrain_cfg.get("departement")

    if bdtopo_path_cfg:
        bdtopo_p = pathlib.Path(bdtopo_path_cfg)
        if not bdtopo_p.exists():
            _out(f"  ✗ bdtopo_path déclaré mais absent : {bdtopo_p}")
            _out(f"    Action : python main.py setup {terrain}")
            log.error("check : bdtopo_path absent : %s", bdtopo_p)
            all_ok = False
        else:
            missing_layers = _check_bdtopo_layers(bdtopo_p)
            covers = True
            if bbox:
                try:
                    import fiona
                    with fiona.open(str(bdtopo_p), layer="troncon_de_route") as src:
                        b = src.bounds
                    bx1, by1, bx2, by2 = bbox
                    covers = b[0] <= bx1 and b[1] <= by1 and b[2] >= bx2 and b[3] >= by2
                except Exception:
                    pass

            if missing_layers:
                _out(f"  ⚠ couches manquantes : {', '.join(missing_layers)}")
            elif not covers:
                _out(f"  ⚠ couverture spatiale insuffisante")
            else:
                _out(f"  ✓ {bdtopo_p.name}")
    elif dept:
        _out(f"  ⚠ département configuré ({dept}) mais bdtopo_path absent")
        _out(f"    Action : python main.py setup {terrain}")
        log.warning("check : bdtopo_path absent (ancienne config département %s)", dept)
    else:
        _out("  — BD TOPO non configurée (masquage anthropique désactivé)")

    # ── Karttapullautin ───────────────────────────────────────────────────────

    _out()
    _out("Karttapullautin")

    from src.kp_install import (
        KP_PINNED_VERSION,
        locate_binary as _kp_locate,
        read_binary_version,
    )

    binary = _kp_locate(cfg, terrain)
    kp_version_expected = terrain_cfg.get("kp_version") or KP_PINNED_VERSION

    if binary is None:
        _out(f"  ✗ absent")
        _out(f"    Action : python main.py setup {terrain}")
        log.error("check : KP (pullauta) introuvable")
        all_ok = False
    else:
        actual_version = read_binary_version(binary)
        if actual_version is None:
            _out(f"  ⚠ version illisible ({binary})")
        elif actual_version == kp_version_expected:
            _out(f"  ✓ v{actual_version}")
        else:
            if force_kp_version:
                _out(f"  ⚠ v{actual_version} (attendu : v{kp_version_expected}) — ignoré (--force-kp)")
                log.warning(
                    "check : KP version %s ≠ attendu %s — ignoré par --force-kp",
                    actual_version, kp_version_expected,
                )
            else:
                _out(f"  ✗ v{actual_version} ≠ attendu v{kp_version_expected}")
                _out(f"    Action : python main.py setup {terrain}")
                log.error(
                    "check : KP version %s ≠ attendu %s",
                    actual_version, kp_version_expected,
                )
                all_ok = False

    # ── Résumé ────────────────────────────────────────────────────────────────

    _out()
    _out("─" * 40)
    if all_ok:
        _out("PROJET PRÊT")
    else:
        _out("PROJET INCOMPLET")
    _out("─" * 40)

    return all_ok


def _crs_label(crs: str) -> str:
    """Retourne un nom court pour l'affichage."""
    labels = {
        "EPSG:2154": "Lambert-93",
        "EPSG:25832": "UTM 32N",
        "EPSG:25833": "UTM 33N",
        "EPSG:3067": "TM35FIN",
        "EPSG:27700": "BNG",
        "EPSG:2056": "CH1903+",
        "EPSG:3301": "L-EST97",
    }
    return labels.get(crs, crs)


def _check_agencement(
    extents: list[tuple[float, float, float, float]],
) -> str:
    """Vérifie la jointivité approximative des tuiles."""
    if len(extents) <= 1:
        return "dalle unique"

    xs = sorted({e[0] for e in extents} | {e[2] for e in extents})
    ys = sorted({e[1] for e in extents} | {e[3] for e in extents})

    if len(xs) < 2 or len(ys) < 2:
        return "dalles jointives"

    cell_w = xs[1] - xs[0]
    cell_h = ys[1] - ys[0]

    expected_xs = {xs[0] + i * cell_w for i in range(len(xs) - 1)}
    expected_ys = {ys[0] + i * cell_h for i in range(len(ys) - 1)}

    actual_xs = {e[0] for e in extents}
    actual_ys = {e[1] for e in extents}

    if actual_xs == expected_xs and actual_ys == expected_ys:
        return "dalles jointives"
    return "trous ou groupes disjoints détectés"


def _check_bdtopo_layers(gpkg_path: pathlib.Path) -> list[str]:
    """Retourne les couches REQUIRED manquantes dans le GPKG."""
    try:
        import fiona
        available = fiona.listlayers(str(gpkg_path))
        return [l for l in REQUIRED_BDTOPO_LAYERS if l not in available]
    except ImportError:
        return []
    except Exception:
        return []
