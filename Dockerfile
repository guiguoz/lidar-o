FROM ghcr.io/osgeo/gdal:ubuntu-full-3.9.0

# ── Système ─────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    pdal \
    lastools \
    && rm -rf /var/lib/apt/lists/*

# ── Karttapullautin (binaire Rust, version épinglée) ────────────────────────
# Télécharger la release depuis https://github.com/karttapullautin/karttapullautin/releases
# et la placer dans build/karttapullautin AVANT de builder l'image.
# Version épinglée : mettre à jour KP_VERSION ET expected_dxf_layers dans config.yaml simultanément.
ARG KP_VERSION=2.12.1
COPY build/pullauta/pullauta /usr/local/bin/pullauta
RUN chmod +x /usr/local/bin/pullauta

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

CMD ["python3", "-m", "src.main"]
