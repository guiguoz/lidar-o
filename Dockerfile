FROM ghcr.io/osgeo/gdal:ubuntu-full-3.9.0

# ── Système ─────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    pdal \
    lastools \
    curl \
    && rm -rf /var/lib/apt/lists/*

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

# ── Python : Shapely depuis wheel binaire (embarque GEOS 3.13) ──────────────
# On désinstalle d'abord le shapely système pour éviter d'hériter du GEOS système (potentiellement 3.11)
RUN pip3 uninstall -y shapely 2>/dev/null || true && \
    pip3 install --no-cache-dir --no-build-isolation "shapely>=2.1"

# Vérification GEOS ≥ 3.12 — fail fast si insuffisant pour coverage_simplify
RUN python3 -c "from shapely.geos import geos_version; assert geos_version >= (3, 12, 0), f'GEOS {geos_version} < 3.12 — coverage_simplify indisponible'"

# ── Dépendances projet ───────────────────────────────────────────────────────
WORKDIR /app
COPY pyproject.toml .
RUN pip3 install --no-cache-dir -e ".[dev]"

# ── Code source ──────────────────────────────────────────────────────────────
COPY . .

# ── Vérification des imports ──────────────────────────────────────────────────
RUN python3 -c "import src.vegetation, src.omap_writer, src.qa, src.guards, src.metrics; print('imports OK')"

ENTRYPOINT ["python3", "main.py"]
