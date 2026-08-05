"""Passe PDAL dédiée — count_high.tif : retours HAG [min_high:200] m.

count_high.tif ne peut pas être dérivé par soustraction depuis density_hag.tif :
  total - density_hag mélange les retours sous 0.3 m (sol) et les retours au-dessus
  de 3 m (canopée), qui sont conceptuellement distincts.

Usage :
    python scripts/run_count_high.py --tiles-dir LIDAR/grimbosq --out output/count_high.tif
    python scripts/run_count_high.py --tiles-dir LIDAR/airelles --out output_airelles/count_high.tif
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def build_pdal_high(
    tiles: list[str],
    out_tif: str,
    resolution: float,
    min_high: float = 3.0,
    max_high: float = 200.0,
) -> dict:
    readers = [{"type": "readers.copc", "filename": t} for t in tiles]
    writer = {
        "type": "writers.gdal",
        "filename": out_tif,
        "resolution": resolution,
        "output_type": "count",
        "data_type": "float32",
        "nodata": -1,
    }
    return {
        "pipeline": readers + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range",
             "limits": f"HeightAboveGround[{min_high}:{max_high}]"},
            writer,
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Passe PDAL count_high.tif (retours HAG > min_high m)"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--tiles", nargs="+", help="Chemins .copc.laz explicites")
    grp.add_argument("--tiles-dir", help="Dossier contenant les *.copc.laz (auto-glob)")
    parser.add_argument("--out", required=True, help="Chemin de sortie count_high.tif")
    parser.add_argument("--min-high", type=float, default=3.0,
                        help="Hauteur minimum canopée (défaut : 3.0 m)")
    parser.add_argument("--resolution", type=float, default=None,
                        help="Résolution grille en mètres (défaut : config.yaml)")
    args = parser.parse_args()

    if args.tiles_dir:
        p = pathlib.Path(args.tiles_dir)
        tiles = sorted(str(f) for f in p.glob("*.copc.laz"))
        if not tiles:
            raise SystemExit(f"Aucun .copc.laz dans {args.tiles_dir}")
        log.info("--tiles-dir : %d tuile(s) dans %s", len(tiles), args.tiles_dir)
    else:
        tiles = list(args.tiles)

    resolution = args.resolution
    if resolution is None:
        try:
            cfg = yaml.safe_load(pathlib.Path("config.yaml").read_text(encoding="utf-8"))
            resolution = float(cfg["vegetation"].get("grid_resolution_m", 1.0))
        except Exception:
            resolution = 1.0
    log.info("Résolution : %.1f m | min_high : %.1f m", resolution, args.min_high)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pipeline = build_pdal_high(tiles, str(out_path), resolution, args.min_high)

    tmp = pathlib.Path("temp") / "pdal_count_high.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(pipeline, indent=2), encoding="utf-8")

    log.info("PDAL en cours [HAG %.1f→200 m] — %d tuile(s) ...", args.min_high, len(tiles))
    result = subprocess.run(["pdal", "pipeline", str(tmp)], capture_output=True, text=True)
    if result.returncode != 0:
        log.error("PDAL stderr:\n%s", result.stderr)
        raise SystemExit("PDAL échoué")
    log.info("OK → %s", out_path)


if __name__ == "__main__":
    main()
