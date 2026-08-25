# Contributing

## Adding a country provider

To make `init` and `tiles` work for a new country, create a module in `src/providers/`:

```
src/providers/estonia.py
```

The module must expose two things:

```python
TILE_SOURCE = "https://geoportaal.maaamet.ee/est/Ruumiandmed/..."  # download URL shown to the user

def list_tiles(
    bbox: tuple[float, float, float, float],   # (xmin, ymin, xmax, ymax) in the native CRS
    crs: str,                                  # e.g. "EPSG:3301"
) -> list[str]:
    """Return filenames covering bbox, or [] if this provider does not handle this CRS."""
    if "3301" not in crs:
        return []
    # ... compute tile filenames from bbox ...
    return sorted(tiles)
```

That is all. The registry in `src/providers/__init__.py` discovers the module automatically — no other file needs to be changed.

See `src/providers/france.py` for a complete example.

## What makes a good provider

- **Return filenames, not URLs.** The caller constructs the download instructions.
- **Return `[]` for unrecognised CRS.** The dispatcher tries all providers and uses the first non-empty result.
- **Test with a real bbox.** Tile-naming conventions (north edge, west edge, 1 km grid…) vary by country — verify against a known area before submitting.

## Other contributions

Pull requests are welcome for:
- New country providers (see above)
- Tested terrains outside France (document the LiDAR source, CRS, and QA results if available)
- Portability fixes for the pipeline outside France

Issues are read but responses are not guaranteed.
