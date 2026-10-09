"""Setup interactif — configure LiDAR, BD TOPO et KP pour un terrain."""
from __future__ import annotations

import logging
import pathlib
import re
import subprocess
import sys

import yaml

from src.kp_install import (
    KP_PINNED_VERSION,
    install_kp,
    locate_binary,
    query_latest_version,
    read_binary_version,
)

log = logging.getLogger(__name__)

REQUIRED_BDTOPO_LAYERS = [
    "troncon_de_route",
    "batiment",
    "surface_hydrographique",
    "troncon_hydrographique",
]


# ── Utilitaires BD TOPO ───────────────────────────────────────────────────────

def _extract_dept_from_filename(filename: str) -> str | None:
    """Extrait le code département depuis un nom de fichier type IGN (D014, D14...)."""
    m = re.search(r"D0?(\d{2,3})", pathlib.Path(filename).stem, re.IGNORECASE)
    return m.group(1).lstrip("0") or m.group(1) if m else None


def _validate_bdtopo_layers(gpkg_path: pathlib.Path) -> list[str]:
    """Retourne la liste des couches REQUIRED manquantes dans le GPKG."""
    try:
        import warnings
        import pyogrio
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            available = {row[0] for row in pyogrio.list_layers(str(gpkg_path))}
        return [l for l in REQUIRED_BDTOPO_LAYERS if l not in available]
    except ImportError:
        log.warning("pyogrio non disponible — validation couches ignorée")
        return []
    except Exception as exc:
        log.warning("Validation couches BD TOPO échouée : %s", exc)
        return []


def _bdtopo_covers_bbox(
    gpkg_path: pathlib.Path,
    bbox: tuple[float, float, float, float],
) -> bool:
    """Vérifie que la couche 'troncon_de_route' du GPKG couvre la bbox terrain."""
    try:
        import warnings
        import pyogrio
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            info = pyogrio.read_info(str(gpkg_path), layer="troncon_de_route")
        b = info["total_bounds"]  # (minx, miny, maxx, maxy)
        bx1, by1, bx2, by2 = bbox
        return float(b[0]) <= bx1 and float(b[1]) <= by1 and float(b[2]) >= bx2 and float(b[3]) >= by2
    except Exception:
        return True  # bénéfice du doute


def _find_gpkg_in_dir(directory: pathlib.Path) -> pathlib.Path | None:
    """Cherche un fichier GPKG dans un répertoire (pattern *D*.gpkg)."""
    candidates = sorted(directory.glob("*D*.gpkg"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _extract_7z(archive_path: pathlib.Path, dest_dir: pathlib.Path) -> None:
    """Extrait une archive .7z dans dest_dir.

    Essaie py7zr, puis subprocess 7z, sinon lève RuntimeError.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        import py7zr
        with py7zr.SevenZipFile(str(archive_path), "r") as sz:
            sz.extractall(str(dest_dir))
        return
    except ImportError:
        pass

    result = subprocess.run(
        ["7z", "x", str(archive_path), f"-o{dest_dir}"],
        capture_output=True,
    )
    if result.returncode == 0:
        return

    raise RuntimeError(
        f"Impossible d'extraire {archive_path.name}.\n"
        "  Installer py7zr (pip install py7zr) ou 7-Zip (7z dans PATH)."
    )


# ── Affichage grille ASCII ────────────────────────────────────────────────────

def _ascii_grid(
    tiles: list[pathlib.Path],
    extents: dict[pathlib.Path, tuple[float, float, float, float] | None],
    expected_names: list[str] | None = None,
) -> str:
    """Génère une grille ASCII des dalles présentes/manquantes."""
    from src.check_terrain import _ign_tile_extent

    ign_tiles = {
        f: ext for f, ext in extents.items() if ext and _ign_tile_extent(f.name)
    }
    if not ign_tiles:
        present_extents = [e for e in extents.values() if e]
        if not present_extents:
            return ""
        xs = sorted({int(e[0] / 1000) for e in present_extents})
        ys = sorted({int(e[3] / 1000) for e in present_extents}, reverse=True)
        lines = ["  (dalles sans nommage IGN — grille numérique)"]
        for y in ys:
            row = f"  {y*1000:8d} │"
            for x in xs:
                match = any(
                    int(e[0] / 1000) == x and int(e[3] / 1000) == y
                    for e in present_extents
                )
                row += "  ✓   │" if match else "  ?   │"
            lines.append(row)
        return "\n".join(lines)

    from src.check_terrain import _IGN_RE

    present_keys: set[tuple[int, int]] = set()
    for f in tiles:
        m = _IGN_RE.search(f.name)
        if m:
            present_keys.add((int(m.group(1)), int(m.group(2))))

    expected_keys: set[tuple[int, int]] = set()
    if expected_names:
        for name in expected_names:
            m = _IGN_RE.search(name)
            if m:
                expected_keys.add((int(m.group(1)), int(m.group(2))))

    all_keys = present_keys | expected_keys
    if not all_keys:
        return ""

    xs = sorted({k[0] for k in all_keys})
    ys = sorted({k[1] for k in all_keys}, reverse=True)

    header = "      " + "".join(f"  {x:04d}  " for x in xs)
    sep = "    ┌" + "┬".join("────────" for _ in xs) + "┐"
    mid = "    ├" + "┼".join("────────" for _ in xs) + "┤"
    bot = "    └" + "┴".join("────────" for _ in xs) + "┘"

    lines = [header, sep]
    for i, y in enumerate(ys):
        row = f"{y:4d}│"
        for x in xs:
            if (x, y) in present_keys:
                row += "   ✓    │"
            elif (x, y) in expected_keys:
                row += "   ✗    │"
            else:
                row += "        │"
        lines.append(row)
        if i < len(ys) - 1:
            lines.append(mid)
    lines.append(bot)
    return "\n".join(lines)


# ── Étape 1 : état actuel ─────────────────────────────────────────────────────

def _show_current_state(terrain: str, terrain_cfg: dict) -> None:
    print(f"\nÉtat actuel du terrain '{terrain}' :")
    path_keys = [("lidar_dir", "Répertoire LiDAR"), ("bdtopo_path", "BD TOPO"), ("kp_binary", "Binaire KP")]
    for key, label in path_keys:
        val = terrain_cfg.get(key)
        if val:
            status = "✓" if pathlib.Path(val).exists() else "✗ (absent)"
            print(f"  {label} : {val}  [{status}]")
        else:
            print(f"  {label} : non configuré")
    kp_ver = terrain_cfg.get("kp_version")
    print(f"  Version KP attendue : {kp_ver}" if kp_ver else "  Version KP attendue : non configurée")


# ── Étape 2 : LiDAR ──────────────────────────────────────────────────────────

def _setup_lidar(
    terrain: str,
    terrain_cfg: dict,
    root: pathlib.Path,
    cfg: dict,
) -> pathlib.Path | None:
    """Configure le répertoire LiDAR. Retourne le chemin validé ou None."""
    from src.check_terrain import _tile_extent

    print("\n── LiDAR HD ──────────────────────────────────────────────────")

    existing = terrain_cfg.get("lidar_dir")
    if existing:
        p = pathlib.Path(existing)
        tiles = list(p.glob("*.copc.laz")) + list(p.glob("*.laz"))
        if p.exists() and tiles:
            print(f"  ✓ déjà configuré : {p}  ({len(tiles)} fichier(s))")
            _show_lidar_grid(terrain, p, tiles, cfg)
            return p
        print(f"  ✗ chemin invalide ou vide : {p}")

    while True:
        try:
            raw = input("\n  Chemin vers le répertoire LiDAR (laisser vide pour LIDAR/{terrain}) : ").strip()
        except EOFError:
            raw = ""
        lidar_path = pathlib.Path(raw) if raw else root / "LIDAR" / terrain

        tiles = list(lidar_path.glob("*.copc.laz")) + list(lidar_path.glob("*.laz"))
        if tiles:
            print(f"  ✓ {len(tiles)} fichier(s) LiDAR trouvé(s) dans {lidar_path}")
            _show_lidar_grid(terrain, lidar_path, tiles, cfg)
            return lidar_path
        print(f"  ✗ Aucun fichier .laz ou .copc.laz dans {lidar_path}")
        try:
            retry = input("  Réessayer ? [O/n] ").strip().lower()
        except EOFError:
            retry = "n"
        if retry in ("n", "non", "no"):
            return None


def _show_lidar_grid(
    terrain: str,
    lidar_path: pathlib.Path,
    tiles: list[pathlib.Path],
    cfg: dict,
) -> None:
    """Affiche la grille ASCII et le résumé des dalles."""
    from src.check_terrain import _tile_extent

    extents = {f: _tile_extent(f) for f in tiles}
    valid_extents = [e for e in extents.values() if e]

    terrain_cfg = cfg.get("terrains", {}).get(terrain, {})
    expected_names: list[str] | None = None
    bbox = terrain_cfg.get("bbox")
    if bbox:
        try:
            from src.providers import find_tiles
            crs = terrain_cfg.get("crs", "EPSG:2154")
            expected_names, _ = find_tiles(tuple(bbox), crs)
        except Exception:
            pass

    grid = _ascii_grid(tiles, extents, expected_names)
    if grid:
        print()
        print(grid)

    if valid_extents:
        xmin = min(e[0] for e in valid_extents)
        ymin = min(e[1] for e in valid_extents)
        xmax = max(e[2] for e in valid_extents)
        ymax = max(e[3] for e in valid_extents)
        w_km = (xmax - xmin) / 1000
        h_km = (ymax - ymin) / 1000
        cx = (xmin + xmax) / 2
        cy = (ymin + ymax) / 2
        try:
            from src.init_terrain import projected_to_wgs84
            crs = cfg.get("terrains", {}).get(terrain, {}).get("crs", "EPSG:2154")
            epsg = int(crs.split(":")[-1]) if ":" in crs else 2154
            lat, lon = projected_to_wgs84(cx, cy, epsg)
            center_str = f"centre : {lat:.3f}°N {abs(lon):.3f}°{'O' if lon < 0 else 'E'}"
        except Exception:
            center_str = f"centre : ({cx:.0f}, {cy:.0f})"
        print(f"\n  {len(tiles)} dalle(s) · {w_km:.0f} × {h_km:.0f} km · {center_str}")


# ── Étape 3 : BD TOPO ────────────────────────────────────────────────────────

def _setup_bdtopo(
    terrain: str,
    terrain_cfg: dict,
    root: pathlib.Path,
    cfg: dict,
) -> tuple[pathlib.Path | None, str | None]:
    """Configure le fichier BD TOPO. Retourne (gpkg_path, departement) ou (None, None)."""
    print("\n── BD TOPO ───────────────────────────────────────────────────")

    crs = terrain_cfg.get("crs", "")
    if "2154" not in crs:
        print("  (terrain non France — BD TOPO non requise)")
        return None, None

    existing = terrain_cfg.get("bdtopo_path")
    if existing:
        p = pathlib.Path(existing)
        if p.exists():
            print(f"  ✓ déjà configuré : {p}")
            missing_layers = _validate_bdtopo_layers(p)
            if missing_layers:
                print(f"  ⚠ Couches manquantes : {', '.join(missing_layers)}")
            else:
                print(f"  ✓ Couches BD TOPO validées")
            bbox = terrain_cfg.get("bbox")
            if bbox:
                covers = _bdtopo_covers_bbox(p, tuple(bbox))
                print(f"  ✓ Couverture spatiale OK" if covers else f"  ⚠ Couverture spatiale insuffisante")
            return p, _extract_dept_from_filename(p.name)
        print(f"  ✗ chemin invalide : {p}")

    while True:
        try:
            raw = input("\n  Chemin vers le fichier BD TOPO (.gpkg, .7z ou dossier) : ").strip()
        except EOFError:
            raw = ""
        if not raw:
            print("  (BD TOPO ignorée)")
            return None, None

        path = pathlib.Path(raw)

        if not path.exists():
            print(f"  ✗ Chemin introuvable : {path}")
            continue

        gpkg_path: pathlib.Path | None = None

        if path.is_dir():
            gpkg_path = _find_gpkg_in_dir(path)
            if not gpkg_path:
                print(f"  ✗ Aucun fichier *D*.gpkg dans {path}")
                continue

        elif path.suffix == ".7z":
            proposed_dir = path.parent / path.stem
            print(f"\n  Archive BD TOPO détectée.")
            print(f"  → Extraire dans : {proposed_dir} ? [O/n]")
            try:
                ans = input("  ").strip().lower()
            except EOFError:
                ans = ""
            if ans and ans not in ("o", "y", "oui", "yes"):
                continue
            try:
                _extract_7z(path, proposed_dir)
                gpkg_path = _find_gpkg_in_dir(proposed_dir)
                if not gpkg_path:
                    print(f"  ✗ Aucun GPKG trouvé après extraction dans {proposed_dir}")
                    continue
            except RuntimeError as exc:
                print(f"  ✗ {exc}")
                continue

        elif path.suffix == ".gpkg":
            gpkg_path = path

        else:
            print(f"  ✗ Format non reconnu (attendre .gpkg, .7z ou un dossier)")
            continue

        missing_layers = _validate_bdtopo_layers(gpkg_path)
        if missing_layers:
            print(f"  ⚠ Couches manquantes : {', '.join(missing_layers)}")
        else:
            print(f"  ✓ Couches BD TOPO validées")

        bbox = terrain_cfg.get("bbox")
        if bbox:
            covers = _bdtopo_covers_bbox(gpkg_path, tuple(bbox))
            if covers:
                print(f"  ✓ Couverture spatiale OK")
            else:
                print(f"  ⚠ Couverture spatiale insuffisante — vérifier le département")

        dept = _extract_dept_from_filename(gpkg_path.name)
        if dept:
            print(f"  Département déduit : {dept}")

        return gpkg_path, dept


# ── Étape 4 : KP ─────────────────────────────────────────────────────────────

def _setup_kp(
    terrain: str,
    terrain_cfg: dict,
    root: pathlib.Path,
    cfg: dict,
) -> tuple[pathlib.Path | None, str | None]:
    """Configure KP. Retourne (binary_path, version) ou (None, None)."""
    print("\n── Karttapullautin ───────────────────────────────────────────")

    try:
        raw = input("  Chemin vers un binaire existant (laisser vide pour auto) : ").strip()
    except EOFError:
        raw = ""

    binary: pathlib.Path | None = None

    if raw:
        candidate = pathlib.Path(raw)
        if candidate.exists():
            binary = candidate
        else:
            print(f"  ✗ Chemin introuvable : {candidate}")

    if binary is None:
        binary = locate_binary(cfg, terrain)

    if binary is not None:
        version = read_binary_version(binary)
        expected = terrain_cfg.get("kp_version") or KP_PINNED_VERSION

        if version == expected:
            print(f"  ✓ v{version}  ({binary})")
            return binary, version

        print(f"  ⚠ v{version} (attendu : v{expected})  ({binary})")
        print("  [1] Utiliser quand même")
        print(f"  [2] Installer v{KP_PINNED_VERSION}")
        try:
            choice = input("  Choix [1/2] : ").strip()
        except EOFError:
            choice = "1"

        if choice != "2":
            return binary, version

    install_dir = root / "bin"
    try:
        binary = install_kp(install_dir, confirm=True)
        version = read_binary_version(binary)
        return binary, version
    except RuntimeError as exc:
        print(f"  ✗ {exc}")
        return None, None


# ── Enregistrement ────────────────────────────────────────────────────────────

def _reload_cfg(root: pathlib.Path) -> dict:
    config_path = root / "config.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


# ── Point d'entrée principal ──────────────────────────────────────────────────

def cmd_setup(terrain: str, cfg: dict, root: pathlib.Path) -> bool:
    """Setup interactif — sélection, validation, stockage. Retourne True si projet prêt."""
    from src.check_terrain import cmd_check
    from src.init_terrain import patch_terrain_yaml

    config_path = root / "config.yaml"
    terrain_cfg = (cfg.get("terrains") or {}).get(terrain, {})

    if not terrain_cfg:
        print(
            f"\nTerrain '{terrain}' absent de config.yaml.\n"
            f"  Lancer d'abord : python main.py init {terrain} --center lat lon"
        )
        return False

    print(f"\nLidar'O — configuration du terrain '{terrain}'")
    print("=" * 52)

    _show_current_state(terrain, terrain_cfg)

    lidar_dir = _setup_lidar(terrain, terrain_cfg, root, cfg)
    gpkg_path, dept = _setup_bdtopo(terrain, terrain_cfg, root, cfg)
    binary, kp_version = _setup_kp(terrain, terrain_cfg, root, cfg)

    print("\n── Enregistrement ────────────────────────────────────────────")
    fields: dict[str, str | None] = {}
    if lidar_dir is not None:
        fields["lidar_dir"] = str(lidar_dir).replace("\\", "/")
    if gpkg_path is not None:
        fields["bdtopo_path"] = str(gpkg_path).replace("\\", "/")
    if dept is not None:
        fields["departement"] = dept
    if binary is not None:
        fields["kp_binary"] = str(binary).replace("\\", "/")
    if kp_version is not None:
        fields["kp_version"] = kp_version

    if fields:
        patch_terrain_yaml(terrain, fields, config_path)
        for k, v in fields.items():
            print(f"  {k} = {v}")
    else:
        print("  (aucun champ à enregistrer)")

    print("\n── Contrôle final ────────────────────────────────────────────")
    cfg_reloaded = _reload_cfg(root)
    from src.pipeline_mode import resolve_veg_source
    veg_mode = resolve_veg_source(terrain, cfg_reloaded)
    ok = cmd_check(terrain, cfg_reloaded, root, verbose=True, veg_mode=veg_mode)
    return ok
