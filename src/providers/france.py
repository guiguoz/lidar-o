"""IGN LiDAR HD tile connector — France (EPSG:2154 only)."""
from __future__ import annotations

import math

TILE_SOURCE = "https://geoservices.ign.fr/lidarhd"
_TILE_SUFFIX = "PTS_LAMB93_IGN69.copc.laz"


def list_tiles(
    bbox: tuple[float, float, float, float],
    crs: str,
) -> list[str]:
    """Return LiDAR HD filenames needed to cover bbox.

    Convention IGN : tuile LHD_FXX_XXXX_YYYY couvre
      x ∈ [XXXX×1000, (XXXX+1)×1000)   (XXXX = colonne ouest)
      y ∈ [(YYYY-1)×1000, YYYY×1000)   (YYYY = bord NORD de la tuile)

    Formules dérivées et vérifiées sur Grimbosq et Port-en-Bessin :
      x_tiles = range(floor(xmin/1000), floor(xmax/1000))
      y_tiles = range(floor(ymin/1000)+1, floor(ymax/1000)+1)
    """
    if "2154" not in str(crs):
        return []

    xmin, ymin, xmax, ymax = bbox

    x_start = math.floor(xmin / 1000)
    x_end   = math.floor(xmax / 1000)          # exclusive

    y_start = math.floor(ymin / 1000) + 1      # YYYY min (bord nord le plus bas)
    y_end   = math.floor(ymax / 1000) + 1      # exclusive

    tiles: list[str] = []
    for xx in range(x_start, x_end):
        for yy in range(y_start, y_end):
            tiles.append(f"LHD_FXX_{xx:04d}_{yy:04d}_{_TILE_SUFFIX}")

    return sorted(tiles)
