"""Passe PDAL — intensité de retour dans la bande végétation HAG[0.3:3m].

Produit deux rasters en une seule passe :
  intensity_veg.tif     — intensité moyenne des retours HAG[0.3:3m]
  angle_veg.tif         — angle de scan moyen HAG[0.3:3m]  (ScanAngleRank)

Le test de dépendance angle→intensité est obligatoire avant tout test de séparabilité :
si la variance inter-lignes de vol domine la variance inter-classes FFCO, il faut
normaliser avant de conclure. angle_veg.tif permet ce test sans passe PDAL supplémentaire.

Usage :
    python scripts/run_intensity_veg.py --tiles-dir LIDAR/airelles --out-dir output_airelles
    python scripts/run_intensity_veg.py --tiles-dir LIDAR/grimbosq --out-dir output
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


def build_pdal_intensity(
    tiles: list[str],
    out_intensity: str,
    out_angle: str,
    resolution: float,
    min_h: float = 0.3,
    max_h: float = 3.0,
) -> dict:
    readers = [{"type": "readers.copc", "filename": t} for t in tiles]
    base = {
        "type": "writers.gdal",
        "resolution": resolution,
        "output_type": "mean",
        "data_type": "float32",
        "nodata": -9999,
    }
    return {
        "pipeline": readers + [
            {"type": "filters.merge"},
            {"type": "filters.hag_nn", "count": 8},
            {"type": "filters.range",
             "limits": f"HeightAboveGround[{min_h}:{max_h}]"},
            {**base, "filename": out_intensity, "dimension": "Intensity"},
            {**base, "filename": out_angle,     "dimension": "ScanAngleRank"},
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Passe PDAL intensité + angle de scan (bande végétation)"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--tiles", nargs="+")
    grp.add_argument("--tiles-dir")
    parser.add_argument("--out-dir", required=True,
                        help="Dossier de sortie (ex: output_airelles)")
    parser.add_argument("--resolution", type=float, default=None)
    parser.add_argument("--min-h", type=float, default=0.3)
    parser.add_argument("--max-h", type=float, default=3.0)
    args = parser.parse_args()

    if args.tiles_dir:
        p = pathlib.Path(args.tiles_dir)
        tiles = sorted(str(f) for f in p.glob("*.copc.laz"))
        if not tiles:
            raise SystemExit(f"Aucun .copc.laz dans {args.tiles_dir}")
        log.info("--tiles-dir : %d tuile(s)", len(tiles))
    else:
        tiles = list(args.tiles)

    resolution = args.resolution
    if resolution is None:
        try:
            cfg = yaml.safe_load(pathlib.Path("config.yaml").read_text(encoding="utf-8"))
            resolution = float(cfg["vegetation"].get("grid_resolution_m", 1.0))
        except Exception:
            resolution = 1.0

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_intensity = str(out_dir / "intensity_veg.tif")
    out_angle     = str(out_dir / "angle_veg.tif")

    log.info("Résolution %.1f m | HAG [%.1f:%.1f m]", resolution, args.min_h, args.max_h)

    pipeline = build_pdal_intensity(tiles, out_intensity, out_angle,
                                    resolution, args.min_h, args.max_h)
    tmp = pathlib.Path("temp") / "pdal_intensity_veg.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(pipeline, indent=2), encoding="utf-8")

    log.info("PDAL en cours — %d tuile(s) ...", len(tiles))
    result = subprocess.run(["pdal", "pipeline", str(tmp)], capture_output=True, text=True)
    if result.returncode != 0:
        log.error("PDAL stderr:\n%s", result.stderr)
        raise SystemExit("PDAL échoué")

    log.info("OK → %s", out_intensity)
    log.info("OK → %s", out_angle)


if __name__ == "__main__":
    main()
