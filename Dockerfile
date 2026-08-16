# Base : micromamba (conda-forge) — installe GDAL + PDAL + Python stack
# sans dépendre de PPAs ou binaires tiers instables.
FROM mambaorg/micromamba:2.0-ubuntu24.04

USER root

# ── Système ─────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Stack géospatiale (conda-forge) ─────────────────────────────────────────
# gdal   — Python bindings + CLI (gdal_translate, ogrinfo…)
# pdal   — CLI + Python bindings (traitement LiDAR)
# Les autres dépendances Python sont installées depuis pyproject.toml via pip.
RUN micromamba install -y -n base -c conda-forge \
    python=3.11 \
    gdal \
    pdal \
    geopandas \
    shapely \
    pyogrio \
    numpy \
    scipy \
    rasterio \
    requests \
    pyyaml \
    ezdxf \
    pip \
    "pytest>=8.0" \
  && micromamba clean -afy

ENV PATH="/opt/conda/bin:${PATH}"

# Vérification GEOS ≥ 3.12 — fail fast si insuffisant pour coverage_simplify
RUN python -c "from shapely.geos import geos_version; assert geos_version >= (3, 12, 0), f'GEOS {geos_version} < 3.12'"

# ── Karttapullautin (GPL-3.0) — téléchargé depuis les releases officielles ──
# Version épinglée : si KP_VERSION change, vérifier que les noms de calques DXF
# correspondent toujours au mapping scripts/mappings/kp_relief.yaml.
ARG KP_VERSION=2.12.1
# URL vérifiée sur https://github.com/karttapullautin/karttapullautin/releases/tag/v2.12.1
RUN mkdir /tmp/kp \
 && curl -fL "https://github.com/karttapullautin/karttapullautin/releases/download/v${KP_VERSION}/karttapullautin-x86_64-linux.tar.gz" \
    | tar xz -C /tmp/kp \
 && find /tmp/kp -name pullauta -type f -exec install -m 755 {} /usr/local/bin/pullauta \; \
 && rm -rf /tmp/kp
ENV KP_BINARY=/usr/local/bin/pullauta

# ── Code source ──────────────────────────────────────────────────────────────
# Le WORKDIR /app rend src.* importable directement — pas besoin d'install editable.
WORKDIR /app
COPY . .

# ── Vérification des imports ──────────────────────────────────────────────────
RUN python -c "import src.vegetation, src.omap_writer, src.qa, src.guards, src.metrics; print('imports OK')"

ENTRYPOINT ["python", "main.py"]
