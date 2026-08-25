"""Provider registry — auto-discovers country modules in this package.

Each module must expose:
  TILE_SOURCE: str           human-readable URL of the data source
  list_tiles(bbox, crs) -> list[str]
      Return filenames covering bbox (xmin, ymin, xmax, ymax) for the given CRS string.
      Return [] if this provider does not handle that CRS.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path


def find_tiles(
    bbox: tuple[float, float, float, float],
    crs: str,
) -> tuple[list[str], str]:
    """Try every provider module; return (tile_names, source_url) from the first match.

    Returns ([], "") if no provider handles this CRS.
    """
    pkg_dir = Path(__file__).parent
    for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
        if mod_info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"src.providers.{mod_info.name}")
        tiles = mod.list_tiles(bbox, crs)
        if tiles:
            return tiles, getattr(mod, "TILE_SOURCE", "")
    return [], ""
