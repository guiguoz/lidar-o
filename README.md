# Lidar'O

*[Version française](README.fr.md)*

**Lidar'O automatically generates an orienteering base map** from LiDAR data and geographic databases.
It produces a `.omap` file ready to open in OpenOrienteering Mapper, with contours, roads, hydrography, and a first vegetation estimate.

The mapper retains field verification, vegetation correction, and fine detail work.

> **Full documentation in French** — see [README.fr.md](README.fr.md) and [docs/guide_utilisateur.md](docs/guide_utilisateur.md)

---

## Download for Windows (v0.1.0)

**[→ Download LidarO-v0.1.0-Windows-x64.zip](https://github.com/guiguoz/lidar-o/releases/tag/v0.1.0)** (~738 MB)

No separate Python, Conda, GDAL, or PDAL installation required.

**Setup:**

1. Download and **fully extract** the ZIP → folder `LidarO-v0.1.0-Windows-x64/`
2. Double-click `setup.bat` — one-time initialisation (~2 min), **wait for it to complete**
3. Double-click `LidarO.bat` → GUI

> **Included guide:** open `docs/DEMARRER.html` in the extracted folder for step-by-step instructions (French).

> **Results folder:** choose a folder outside the application folder (e.g. `Documents\my-maps\`) to avoid losing computed results when updating.

> **Experimental version** — tested on Windows 11 — field verification required before publishing an official map — manual updates (download the new version into a new folder, re-run `setup.bat`).

---

![Lidar'O GUI](docs/images/capture_gui.png)
*Lidar'O GUI — LiDAR / BD TOPO selectors, vegetation engine and export mode*

![Lidar'O result in OpenOrienteering Mapper](docs/images/extrait_grimbosq.jpg)
*Lidar'O output opened in OpenOrienteering Mapper — Grimbosq terrain (Normandy, France)*

---

## What Lidar'O produces

```
vectorised and symbolised:
  contour lines       — from Karttapullautin
  tracks / roads      — BD TOPO
  buildings           — BD TOPO
  hydrography         — BD TOPO
  open land and agricultural areas
  out-of-bounds areas
  vegetation 406 / 408 / 410  — automatic estimate (see vegetation modes below)

assembled and georeferenced
→ .omap file, ready to open in OpenOrienteering Mapper
```

## What Lidar'O does not produce

- Cliffs or boulders (symbols 201/202 disabled)
- Point features or plantation rows
- A finished map — the automatic vegetation is a base to correct in the field

---

## Vegetation modes

| Mode | Principle | Status |
|---|---|---|
| `kp` (default) | Karttapullautin extracts a vegetation image from LiDAR; layers 406/408/410 are vectorised from that image. | Stable |
| `supervised_e` | Direct classification from the vertical structure of the point cloud — 4 levels (401/406/408/410). | Experimental |

Both modes run autonomously from LiDAR data, without any external cartographic reference at inference time.

**Which combination to use?**

- **`kp`** (default): always available, no additional model required.
- **`supervised_e` + `faithful`**: uses the pre-trained model included in the Windows package. The vegetation output is an indicative estimate based on the vertical structure of the point cloud — it does not claim equivalence with an OCAD survey and requires field verification.
- **`supervised_e` + `generalized`**: same estimate, with geometric simplification (MMU + smoothing).

**Export mode** (`vegetation_export_mode`, `supervised_e` only):

| Value | Effect |
|---|---|
| `faithful` (default) | Detected polygons exported as-is — no loss, noisy output |
| `generalized` | Geometric simplification (MMU + smoothing) — clean cartographic output |

---

## Input data

| Data | Source | Location |
|---|---|---|
| LiDAR HD tiles (`*.copc.laz`) | [IGN Géoplateforme](https://geoservices.ign.fr/lidarhd) | any folder |
| BD TOPO (department GPKG, France) | [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo) | any file |

---

## Quick start

1. Launch the GUI via `LidarO.bat`
2. **Project name** — type a name (e.g. `my_forest`)
3. **Choose LiDAR folder…** — select the folder containing your `.copc.laz` tiles
4. **Load BD TOPO…** — select the department `.gpkg` file
5. **Generate**

Output: `.omap` file in the results folder you chose — open in OpenOrienteering Mapper.

The project is created automatically from the IGN tile filenames. No command-line setup needed for standard IGN France data.

---

## Validity domain

| | |
|---|---|
| **Tested** | Normandy deciduous forest — IGN HD LiDAR — COPC — Lambert-93 — leaf-off acquisition |
| **Not tested** | Mountain forests, heathlands, dense conifers, leaf-on acquisitions |
| **Portable** | CRS auto-detected; meridian convergence computed; two countries tested (France, Estonia) |
| **Note** | Code portability does not guarantee vegetation quality outside the tested domain |

---

## Full guide

→ **[docs/DEMARRER.html](docs/DEMARRER.html)** (included in the Windows package) — setup, configuration, full example, troubleshooting (French)
→ **[docs/guide_utilisateur.md](docs/guide_utilisateur.md)** (French) — same content in Markdown
→ **[BD TOPO download guide](docs/guide_utilisateur.md#télécharger-et-préparer-la-bd-topo-france-uniquement)** — format, department selection, extraction

Technical documentation:
- [docs/supervised_e.md](docs/supervised_e.md) — supervised_e mode: architecture, model, results
- [docs/portabilite.md](docs/portabilite.md) — usage outside France
- [docs/bilan_v0.md](docs/bilan_v0.md) — evaluation results and experimental history

---

## Developers — source installation

> This section is for developers who want to modify the code or use Lidar'O outside the Windows package.

### Quick setup (Windows)

```bat
rem Clone
git clone https://github.com/guiguoz/lidar-o.git
cd lidar-o

rem Install geospatial Python (Miniconda Prompt)
conda install -c conda-forge python=3.11 geopandas shapely scipy numpy ^
    python-pdal pdal rasterio ezdxf requests pyyaml
```

Launch:

```bat
python main.py gui
```

### CLI (advanced / non-IGN data)

```bash
python main.py init my_forest --center 49.043 -0.421  # declare terrain
python main.py setup my_forest                         # interactive config
python main.py run my_forest --tiles-dir LIDAR/        # run pipeline
```

Use the CLI for non-IGN coordinates, custom bounding boxes, or scripted workflows.

---

## Architecture

```
main.py                   CLI + GUI (python main.py run / gui)
config.yaml               terrain and pipeline parameters

src/
  vegetation.py           CO Generalization Engine (kp/hag mode)
  supervised_e.py         vegetation detection from LiDAR (supervised_e mode)
  omap_writer.py          .omap generation
  pipeline_mode.py        vegetation mode resolution

gui/
  app.py                  tkinter interface
  worker.py               pipeline thread

scripts/                  fetch BD TOPO, process HAG, contours
assets/                   ISOM 2017-2 template, georef files
docs/                     user and technical guides
experiments/              supervised_e training and experiments
```

---

## Licence and credits

**GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).

Third-party assets:
- ISOM 2017-2 template from [OpenOrienteering Mapper](https://www.openorienteering.org/) (GPL-3.0)
- CRT table from [Blaze / Trailblaze Software](https://github.com/Trailblaze-Software/Blaze) (GPL-3.0)
- [Karttapullautin](https://github.com/karttapullautin/karttapullautin) v2.12.1 — bundled in the Windows package (GPL-3.0; source: [releases/tag/v2.12.1](https://github.com/karttapullautin/karttapullautin/releases/tag/v2.12.1)); in source installation, downloaded automatically by `setup`
