"""init — creates terrain entry in config.yaml + georef XML from geographic coordinates."""
from __future__ import annotations

import pathlib
import sys

import yaml
from pyproj import CRS, Proj, Transformer


# Country → (lat_min, lat_max, lon_min, lon_max, epsg, crs_name)
# Ordered so that smaller/more specific regions take priority over larger ones.
_CRS_TABLE = [
    (45.8, 47.9,   5.9,  10.6, 2056,  "CH1903+ / LV95"),
    (57.5, 59.7,  21.7,  28.2, 3301,  "Estonian Coordinate System of 1997"),
    (49.8, 61.0,  -8.7,   2.0, 27700, "OSGB36 / British National Grid"),
    (59.5, 70.1,  19.0,  32.0, 3067,  "ETRS89 / TM35FIN(E,N)"),
    (41.0, 51.5,  -5.5,   9.8, 2154,  "RGF93 / Lambert-93"),
    (55.0, 72.0,   4.0,  18.0, 25832, "ETRS89 / UTM zone 32N"),
    (55.0, 72.0,  18.0,  32.0, 25833, "ETRS89 / UTM zone 33N"),
]

_DEFAULT_SIZE_M = 2000
_MAX_SIZE_M = 5000


def deduce_crs(lat: float, lon: float) -> tuple[int, str]:
    """Return (epsg, crs_name) for lat/lon. Falls back to UTM zone if outside table."""
    for lat_min, lat_max, lon_min, lon_max, epsg, name in _CRS_TABLE:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return epsg, name
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone, f"WGS 84 / UTM zone {zone}N"
    return 32700 + zone, f"WGS 84 / UTM zone {zone}S"



def compute_convergence(lat: float, lon: float, epsg: int) -> float:
    """Meridian convergence at (lat, lon) for the given CRS, in degrees.

    This is the 'declination' field in .omap georeferencing blocks.
    Uses pyproj.Proj.get_factors() — exact for any projection (Lambert, UTM…).
    NOT magnetic declination.
    """
    return Proj(f"EPSG:{epsg}").get_factors(lon, lat).meridian_convergence


def projected_to_wgs84(x: float, y: float, epsg: int) -> tuple[float, float]:
    """Return (lat, lon) in WGS84."""
    t = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(x, y)
    return lat, lon


def wgs84_to_projected(lat: float, lon: float, epsg: int) -> tuple[float, float]:
    """Return (x, y) in projected CRS."""
    t = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    x, y = t.transform(lon, lat)
    return x, y


def bbox_from_center(lat: float, lon: float, size_m: float, epsg: int) -> tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) in projected CRS from geographic center + side length."""
    cx, cy = wgs84_to_projected(lat, lon, epsg)
    half = size_m / 2.0
    return (round(cx - half), round(cy - half), round(cx + half), round(cy + half))


def _ref_point_from_bbox(bbox: tuple[float, float, float, float]) -> tuple[int, int]:
    """Center of bbox, rounded to nearest 1000 m."""
    cx = (bbox[0] + bbox[2]) / 2.0
    cy = (bbox[1] + bbox[3]) / 2.0
    return (round(cx / 1000) * 1000, round(cy / 1000) * 1000)


def _auxiliary_scale_factor(epsg: int) -> float:
    """0.999966 for Lambert-93 (approximation valid on flat terrain). 1.0 otherwise."""
    if epsg == 2154:
        return 0.999966
    return 1.0


def write_georef_xml(
    terrain: str,
    bbox: tuple[float, float, float, float],
    epsg: int,
    assets_dir: pathlib.Path,
) -> pathlib.Path:
    """Write assets/georef_{terrain}.xml and return its path."""
    rx, ry = _ref_point_from_bbox(bbox)
    lat, lon = projected_to_wgs84(rx, ry, epsg)
    conv = compute_convergence(lat, lon, epsg)
    asf = _auxiliary_scale_factor(epsg)

    xml = (
        f'<georeferencing scale="10000" auxiliary_scale_factor="{asf}" declination="{conv:.2f}">\n'
        f'  <projected_crs id="EPSG">\n'
        f'    <spec language="PROJ.4">+init=epsg:{epsg}</spec>\n'
        f'    <parameter>{epsg}</parameter>\n'
        f'    <ref_point x="{rx}" y="{ry}"/>\n'
        f'  </projected_crs>\n'
        f'  <geographic_crs id="Geographic coordinates">\n'
        f'    <spec language="PROJ.4">+proj=latlong +datum=WGS84</spec>\n'
        f'    <ref_point_deg lat="{lat:.8f}" lon="{lon:.8f}"/>\n'
        f'  </geographic_crs>\n'
        f'</georeferencing>\n'
        f'<!-- declination = convergence des méridiens (angle grille → géographique au point de référence),\n'
        f'     PAS la déclinaison magnétique.\n'
        f'     Calculée via pyproj.Proj.get_factors() — exacte pour tout CRS (Lambert, UTM…). -->\n'
    )

    path = assets_dir / f"georef_{terrain}.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _remove_terrain_block(terrain: str, text: str) -> str:
    """Remove an existing terrain YAML block from config text (line-based)."""
    lines = text.split("\n")
    result: list[str] = []
    in_block = False
    key_prefix = f"  {terrain}:"

    for line in lines:
        stripped = line.rstrip()
        is_header = stripped == key_prefix or (
            stripped.startswith(key_prefix)
            and len(stripped) > len(key_prefix)
            and stripped[len(key_prefix)] in " #"
        )
        if is_header:
            in_block = True
            continue
        if in_block:
            if stripped.startswith("    "):
                continue
            in_block = False
        result.append(line)

    return "\n".join(result)


def patch_terrain_yaml(
    terrain: str,
    fields: dict,
    config_path: pathlib.Path,
) -> None:
    """Met à jour les champs d'un terrain dans config.yaml sans écraser les autres.

    Lit le bloc existant, fusionne avec les nouveaux champs, réécrit le bloc entier.
    Les champs None sont omis. Les valeurs string path sont citées en YAML.
    """
    text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text) or {}
    terrains = cfg.get("terrains") or {}
    existing = dict(terrains.get(terrain, {}))

    existing.update({k: v for k, v in fields.items() if v is not None})

    _PATH_FIELDS = {"lidar_dir", "bdtopo_path", "kp_binary"}
    _KNOWN_ORDER = [
        "bbox", "crs", "departement",
        "lidar_dir", "bdtopo_path",
        "kp_binary", "kp_version",
    ]

    entry_lines = [f"\n  {terrain}:"]
    written: set[str] = set()
    for key in _KNOWN_ORDER:
        if key not in existing:
            continue
        val = existing[key]
        if val is None:
            continue
        if key in _PATH_FIELDS and isinstance(val, str):
            val_str = val.replace("\\", "/")
            entry_lines.append(f'    {key}: "{val_str}"')
        elif isinstance(val, str):
            entry_lines.append(f'    {key}: "{val}"')
        else:
            entry_lines.append(f"    {key}: {val}")
        written.add(key)

    for key, val in existing.items():
        if key in written or val is None:
            continue
        if isinstance(val, str):
            val_str = val.replace("\\", "/")
            entry_lines.append(f'    {key}: "{val_str}"')
        else:
            entry_lines.append(f"    {key}: {val}")

    if terrain in terrains:
        text = _remove_terrain_block(terrain, text)

    config_path.write_text(
        text.rstrip("\n") + "\n" + "\n".join(entry_lines) + "\n",
        encoding="utf-8",
    )


def update_config_yaml(
    terrain: str,
    bbox: tuple[float, float, float, float],
    epsg: int,
    config_path: pathlib.Path,
    *,
    force: bool = False,
) -> None:
    """Append terrain entry to config.yaml. Raises ValueError if terrain exists and not force."""
    text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text) or {}
    terrains = cfg.get("terrains") or {}

    if terrain in terrains and not force:
        raise ValueError(
            f"Le terrain '{terrain}' existe déjà dans config.yaml. "
            f"Utilisez --force pour écraser."
        )

    if terrain in terrains:
        text = _remove_terrain_block(terrain, text)

    bbox_list = [int(v) for v in bbox]
    entry = f"\n  {terrain}:\n    bbox: {bbox_list}\n    crs: EPSG:{epsg}\n"
    config_path.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")


def _country_label(lat: float, lon: float) -> str:
    labels = {
        2056: "Suisse / Liechtenstein",
        3301: "Estonie",
        27700: "Grande-Bretagne",
        3067: "Finlande",
        2154: "France métropolitaine",
        25832: "Norvège (zone UTM 32N)",
        25833: "Norvège (zone UTM 33N)",
    }
    epsg, _ = deduce_crs(lat, lon)
    return labels.get(epsg, f"zone UTM {epsg}")


def cmd_init(args) -> None:
    """python main.py init <terrain> --center lat lon [--size N] [--crs EPSG:XXXX]"""
    root = pathlib.Path(".")
    assets_dir = root / "assets"
    config_path = root / "config.yaml"

    terrain: str = args.terrain
    force: bool = getattr(args, "force", False)

    # ── Determine bbox and EPSG ────────────────────────────────────────────────

    if args.center is not None:
        lat, lon = args.center
        size_m = args.size if args.size else _DEFAULT_SIZE_M

        if args.crs:
            epsg = int(args.crs.split(":")[-1])
            crs_name = args.crs
        else:
            epsg, crs_name = deduce_crs(lat, lon)
            print(f"\nPoint {lat}°N, {lon}°E → {_country_label(lat, lon)}")
            print(f"CRS proposé : EPSG:{epsg} ({crs_name})")
            try:
                ans = input("Confirmer ? [O/n] ").strip().lower()
            except EOFError:
                ans = ""
            if ans and ans not in ("o", "y", "oui", "yes"):
                print("Annulé.")
                sys.exit(0)

        if size_m > _MAX_SIZE_M:
            print(f"\nAvertissement : taille {size_m} m > plafond {_MAX_SIZE_M} m.")
            print("Temps de traitement et volume de données importants (centaines de Mo).")
            try:
                ans = input("Continuer ? [o/N] ").strip().lower()
            except EOFError:
                ans = "n"
            if ans not in ("o", "y", "oui", "yes"):
                print("Annulé.")
                sys.exit(0)

        bbox = bbox_from_center(lat, lon, size_m, epsg)

    elif args.bbox is not None:
        if not args.crs:
            sys.exit("ERREUR : --crs requis avec --bbox (ex. --crs EPSG:2154)")
        epsg = int(args.crs.split(":")[-1])
        bbox = tuple(float(v) for v in args.bbox)
    else:
        sys.exit("ERREUR : --center lat lon OU --bbox xmin ymin xmax ymax requis")

    # ── Check terrain doesn't already exist ────────────────────────────────────

    if config_path.exists():
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if terrain in (cfg.get("terrains") or {}) and not force:
            sys.exit(
                f"ERREUR : le terrain '{terrain}' existe déjà dans config.yaml.\n"
                f"Utilisez --force pour écraser."
            )

    # ── Create directories ─────────────────────────────────────────────────────

    for d in ["data", "output"]:
        (root / d).mkdir(exist_ok=True)
    (root / "LIDAR" / terrain).mkdir(parents=True, exist_ok=True)

    # ── Write georef XML ───────────────────────────────────────────────────────

    georef_path = write_georef_xml(terrain, bbox, epsg, assets_dir)

    # ── Update config.yaml ─────────────────────────────────────────────────────

    update_config_yaml(terrain, bbox, epsg, config_path, force=force)

    # ── Summary ────────────────────────────────────────────────────────────────

    rx, ry = _ref_point_from_bbox(bbox)
    lat_ref, lon_ref = projected_to_wgs84(rx, ry, epsg)
    conv = compute_convergence(lat_ref, lon_ref, epsg)

    try:
        from src.providers import find_tiles
        tiles_list, tile_source = find_tiles(tuple(bbox), f"EPSG:{epsg}")
    except Exception:
        tiles_list, tile_source = [], ""

    tiles_dir = f"LIDAR/{terrain}"

    print(f"\nTerrain '{terrain}' initialisé.")
    print(f"  bbox   : {[int(v) for v in bbox]}")
    print(f"  CRS    : EPSG:{epsg}")
    print(f"  georef : assets/georef_{terrain}.xml")
    print()
    print("DONNÉES NÉCESSAIRES")
    print()

    if tiles_list:
        print(f"  LiDAR HD — {len(tiles_list)} dalle(s) :")
        for t in tiles_list:
            print(f"    {t}")
        print(f"  → Télécharger depuis la source officielle IGN LiDAR HD")
    else:
        print(f"  LiDAR HD :")
        print(f"  → Placer vos dalles (.laz ou .copc.laz) dans : {tiles_dir}/")

    print()

    if epsg == 2154:
        print(f"  BD TOPO (France) :")
        print(f"  → Télécharger depuis la source officielle IGN BD TOPO")
        print(f"    (format GPKG, département correspondant à votre secteur)")
        print()

    print(f"  Karttapullautin :")
    print(f"  → github.com/karttapullautin/karttapullautin/releases")
    print(f"    (sera installé automatiquement par setup)")
    print()
    print(f"Étape suivante :")
    print(f"  python main.py setup {terrain}")
    print()
