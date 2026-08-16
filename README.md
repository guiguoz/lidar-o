# Lidar'O

Generate an ISOM base map from IGN HD LiDAR (France), output as a `.omap` file ready to open in OpenOrienteering Mapper or OCAD.

<!-- Representative map extract at scale — copy a screenshot into docs/images/ -->
<!-- ![Grimbosq extract](docs/images/extrait_grimbosq.png) -->

---

## Getting started

### Requirements

- **Geospatial Python** — recommended via [miniconda](https://docs.conda.io/en/latest/miniconda.html):

  ```bash
  conda install -c conda-forge geopandas shapely scipy numpy python-pdal pdal
  pip install pyyaml requests ezdxf
  ```

  Or from the repository:

  ```bash
  pip install -e .
  # Note: gdal, python-pdal and pyogrio require conda or a prebuilt wheel
  ```

- **OpenOrienteering Mapper** — [openorienteering.org](https://www.openorienteering.org/) — to open the produced `.omap`

- **Karttapullautin** (optional, for contours) — [github.com/karttapullautin](https://github.com/karttapullautin/karttapullautin) — run manually on LiDAR tiles, output goes into `out_kp/`

### Input data (France)

| Data | Source | Location |
|------|--------|----------|
| LiDAR HD tiles (COPC, ~500 MB/tile) | [IGN Géoplateforme](https://geoservices.ign.fr/lidarhd) | `LIDAR/` or `--tiles-dir DIR` |
| BD TOPO (department GPKG) | [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo) | `data/bdtopo/` |

**France-specific:** LiDAR comes from the IGN Géoplateforme HD (COPC format), anthropic data from BD TOPO v3. For use outside France, see [docs/portabilite.md](docs/portabilite.md).

Download 1–3 LiDAR tiles covering your area. Expect 10–30 min processing time (PDAL + rasterisation + vectorisation). A single tile (1×1 km) is enough for a first test.

### Run the pipeline

```bash
# Declare the terrain in config.yaml (EPSG:2154 bbox, CRS, department code)
python main.py grimbosq --tiles-dir LIDAR/ --skip-pdal
```

Options:

| Option | Description |
|--------|-------------|
| `--skip-pdal` | Skip PDAL if `density_hag_classified.tif` already exists |
| `--tiles-dir DIR` | Directory containing `.copc.laz` tiles |
| `--from-step STEP` | Resume from: `fetch`, `pdal`, `process_hag`, `vegetation`, `mask`, `assemble`, `qa` |
| `--force` | Ignore freshness checks and rerun all steps |

Output: `output/{terrain}.omap`

---

## What the tool detects

> Measured on **one terrain only** (Grimbosq forest, Calvados, France), against an FFCO reference
> map, over the common extent (convex hull, 324 ha). These figures are not guaranteed elsewhere.

| Class | Detected | Correct class |
|-------|---------|---------------|
| 406 slow run | 35 % | 28 % |
| 408 walk | 61 % | 26 % |
| 410 fight | 82 % | 48 % |

*"Detected"* = fraction of the FFCO reference area covered by any pipeline class — what the mapper does not need to draw.  
*"Correct class"* = fraction covered by the exact right class — what needs no retouching at all.  
Fixing the symbol takes two clicks in OCAD/OOM; drawing a missing polygon from scratch takes much longer.

*These metrics were measured against a non-redistributable reference map — the figures cannot be reproduced from this repository.*

---

## Validity domain

The pipeline has been tested on 5 terrains. The HAG[0.3–3 m] signal separates dense vegetation well; it is insufficient for light, runnable undergrowth.

| Terrain | Type | Result on 406 | Cause |
|---------|------|--------------|-------|
| Grimbosq (Normandy) | Mature beech forest | Partial (35 %) | Light signal indistinguishable from open ground |
| Airelles (Pyrenees) | High-altitude heath | Out of domain | HAG signal identical across FFCO classes |
| Kilemäed (Estonia) | Heath/mixed forest | Out of domain | Semantic mismatch open/covered |
| Kuti (Estonia) | Spruce + Vaccinium | Out of domain | Uniformly dense signal |
| (5th terrain, test) | Temperate forest | 408/410 detected | Confirms dense domain |

**Class 406 is out of domain, including on Grimbosq.** Mann-Whitney AUC = 0.487: the HAG[0.3–3 m] density in missed 406 zones is statistically indistinguishable from runnable open terrain. Lowering the threshold creates as many false positives as it recovers true ones.

**408/410 are in domain** on forests with clear vertical structure (dense temperate forest, 61 %/82 % detection). Tested and out of domain: high-altitude heath, bog-heath, forests with uniform understory.

---

## QA and reference map

The pipeline runs without a reference map (QA metrics fall back to class distribution only). To enable quantitative comparison:

1. Provide your own map as GPKG or `.omap` with layers `veg_406`, `veg_408`, `veg_410`
2. Declare it in `config.yaml`:

   ```yaml
   terrains:
     grimbosq:
       qa_reference: data/my_reference_map.gpkg
   ```

3. Recall by class and hull coverage are printed at the end of the run and saved to `output/run_metadata.json`

---

## Using outside France

The pipeline has run on Estonian data (COPC LiDAR + OSM). Adaptations needed:

- **CRS**: change `crs` in `config.yaml` (e.g. `EPSG:3301` for Estonia)
- **Georeferencing**: create `assets/georef_{terrain}.xml` (see examples in `assets/`)
- **Mappings**: adapt `scripts/mappings/bdtopo_isom.yaml` if anthropic data does not come from BD TOPO
- **BD TOPO**: no direct equivalent outside France — use OSM via the `osm_landuse` option in `config.yaml`

See [docs/portabilite.md](docs/portabilite.md) for a detailed guide.

---

## What this project has established

Eleven improvement directions were tested and measured (intensity bands, NDVI-like HAG, spatially varying thresholds, supervised learning, object-based segmentation…). Most were refuted by measurement on a multi-terrain corpus.

Documented in [docs/bilan_v0.md](docs/bilan_v0.md) to save others from repeating the same experiments.

---

## Project status

Published as-is — a working proof of concept on French temperate forest.

The pipeline produces usable output within the documented limits. GitHub issues will be read but responses are not guaranteed. Pull requests documenting new tested terrains or improving portability are welcome.

---

## Architecture

```
main.py                      main orchestrator (7 steps)
config.yaml                  all parameters — thresholds, profiles, endpoints

src/
  vegetation.py              CO Generalization Engine (9 chained steps)
  omap_writer.py             .omap file generation (OOM XML)
  qa.py                      QA metrics + config snapshot
  guards.py                  config drift detection between runs
  metrics.py                 HAG density computation (ratio, NRD)

scripts/
  fetch.py                   BD TOPO extraction from department GPKG
  process_hag.py             HAG raster normalisation + classification
  mask_vegetation.py         anthropic mask on vegetation layers
  generate_bdtopo.py         BD TOPO → .omap layers
  generate_relief.py         Karttapullautin DXF → contour .omap
  run_terrain.py             standalone PDAL pipeline
  measure_corpus.py          pipeline vs FFCO reference comparison
  mappings/                  ISOM symbol mapping tables (BD TOPO, KP)

scripts/diag/                calibration scripts (experiment history)
assets/                      ISOM 2017-2 template, georef files, KP CRT
docs/                        portability guide, v0 findings, IOF rules
```

---

## License and credits

**GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).

Free to use and modify. Any derivative or network service must be published under AGPL v3 with source code.

Third-party assets:
- ISOM 2017-2 symbol template from [OpenOrienteering Mapper](https://www.openorienteering.org/) (GPL-3.0)
- CRT table from [Blaze / Trailblaze Software](https://github.com/Trailblaze-Software/Blaze) (Apache-2.0)
- [Karttapullautin](https://github.com/karttapullautin/karttapullautin) — not included, download separately
