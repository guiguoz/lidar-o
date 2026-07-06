# co-vector-fr

Automated pipeline for generating orienteering map vegetation layers from IGN LiDAR HD data (France).

Converts LAS/LAZ point clouds into ISOM 2017-2 compliant vegetation polygons, ready for import in OpenOrienteering Mapper (OOM) or OCAD.

---

## What it does

Standard LiDAR tools (Karttapullautin, OmapMaker) produce vegetation as a raster image. **co-vector-fr produces clean vector polygons** with geometric generalization calibrated for orienteering cartography at 1:10,000.

```
IGN LiDAR HD (COPC)
        │
        ▼
PDAL — HAG density ratio (0.3–3 m above ground / total returns)
        │
        ▼
classification raster  →  [406] slow run  [408] walk  [410] fight
        │
        ▼
CO Generalization Engine (7 stages)
  dissolve → remove holes → filter small → merge proximate
  → remove isolated → Douglas-Peucker → Chaikin smooth
        │
        ▼
veg_406.geojson  veg_408.geojson  veg_410.geojson
        │
        ▼
OOM import (ISOM 2017-2)
```

**Key design choices:**
- **Ratio metric** — normalizes HAG density by total return count, removing scan angle and flight line artifacts
- **Per-class independent polygons** — no topological nesting constraint (unlike isoline-based approaches); a 410 patch can touch open terrain directly
- **Fully parameterized** — all thresholds in `config.yaml`, nothing hardcoded

---

## Status

| Component | Status |
|-----------|--------|
| HAG density ratio (vegetation source) | Calibrated |
| CO Generalization Engine | `v1_vegetation_baseline` — frozen |
| Multi-terrain validation | In progress (4 terrains tested) |
| Full pipeline (fetch → export OOM) | Under development |

Calibration terrain: Grimbosq (Normandy, mature deciduous), Les Airelles (Font-Romeu, Pyrenees mountain conifers).

---

## Requirements

- Python 3.11+, conda environment
- PDAL (point cloud processing)
- GeoPandas, rasterio, Shapely ≥ 2.1
- Karttapullautin v2.12.1 (relief generation, included in `build/`)
- IGN LiDAR HD data — COPC format, France

```bash
conda install -c conda-forge geopandas rasterio shapely pdal
pip install pyyaml
```

---

## Usage

### Run on a new terrain

```bash
python scripts/run_terrain.py --name grimbosq --tiles LIDAR/*.copc.laz
```

Output in `output_<name>/`:

| File | Content |
|------|---------|
| `density_hag.tif` | Raw HAG density raster |
| `total_count.tif` | Total return count raster |
| `density_hag_classified.tif` | 3-class raster (406 / 408 / 410) |
| `veg_406.geojson` | Generalized slow-run polygons |
| `veg_408.geojson` | Generalized walk polygons |
| `veg_410.geojson` | Generalized fight polygons |
| `vegetation_final.gpkg` | All classes, GeoPackage |

### Import in OpenOrienteering Mapper

1. Open your `.omap` file
2. File → Import → `veg_406.geojson` → assign symbol 406
3. Repeat for 408 and 410

### Configuration

Edit `config.yaml`. Active preset: `grimbosq_v0`.

```yaml
vegetation:
  density_metric:
    mode: ratio           # HAG / total_count (recommended)
  active_preset: grimbosq_v0

generalization:
  active_profile: grimbosq_v0
```

Switch terrain profile without touching the engine:

```yaml
generalization:
  active_profile: dense_summer   # or sparse_winter
```

### Measure against a reference map

```bash
python scripts/measure_corpus.py compare \
  --hag output_grimbosq/density_hag_classified.tif \
  --ffco reference.gpkg
```

---

## Architecture

```
scripts/
  run_terrain.py        orchestrator — PDAL → classify → generalize → export
  process_hag.py        HAG raster normalization and classification
  measure_corpus.py     compare against FFCO reference maps (3 modes)
  phase0_recon.py       reconnaissance — WFS capabilities, KP outputs, endpoints

src/
  vegetation.py         CO Generalization Engine (7-stage pipeline)
  crt_mapping.py        DXF / BD TOPO → ISOM symbol mapping
  fetch.py              LiDAR HD + BD TOPO download (IGN Géoplateforme)
  run_engine.py         Karttapullautin + PDAL orchestration
  assemble.py           multi-tile merge
  export_oom.py         OOM packaging (GPKG + CRT)
  qa.py                 QA report + PNG diff

config.yaml             all parameters — thresholds, profiles, endpoints
symbols_isom.yaml       ISOM 2017-2 symbol table + BD TOPO mapping
```

---

## Data sources

- **LiDAR HD** — [IGN Géoplateforme](https://geoservices.ign.fr/lidarhd), COPC format, France only
- **BD TOPO v3** — [data.geopf.fr/wfs](https://data.geopf.fr/wfs), typenames confirmed 2026-06-23
- Point cloud processing: [PDAL](https://pdal.io/)
- Relief generation: [Karttapullautin](https://github.com/karttapullautin/karttapullautin) v2.12.1

Data is not included in this repository.

---

## Validation methodology

Parameters were derived experimentally over 10 calibration iterations (T1–T10) on two independent reference terrains, with simultaneous validation from T5 onward to prevent terrain-specific overfitting.

Each test measured polygon count, class area, and visual match against FFCO reference maps before freezing any parameter. The `measure_corpus.py` script reproduces all measurements.

Current known limits:
- Open deciduous forests may produce more polygons than their cartographic representation (documented, cause under investigation)
- Road-side vegetation (branches, hedgerows) not yet masked — BD TOPO road mask planned

---

## License

**GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).

This means:
- Free to use, study, modify, and distribute
- Any derivative work — including running this as a network service — must be released under AGPL v3 with source code available
- Commercial use is permitted **only** if source modifications are shared back under AGPL v3

---

## Citation

If you use this pipeline in research or map production:

```
co-vector-fr — Automated orienteering map vegetation pipeline from IGN LiDAR HD
Guillaume Lemiègre, 2026
https://github.com/guiguoz/Ovector
```

---

## Related

- [Karttapullautin](https://github.com/karttapullautin/karttapullautin) — relief generation from LiDAR
- [OpenOrienteering Mapper](https://www.openorienteering.org/) — OOM, open-source orienteering map editor
