#!/usr/bin/env bash
# Validation Docker lidar-o — à lancer depuis la racine du projet.
# Pré-requis : Docker Desktop démarré, cwd = e:/Vikazim/Ovector
set -euo pipefail

IMAGE=lidar-o
TERRAIN=test_docker
GEOREF="assets/georef_${TERRAIN}.xml"

echo "=== §1 Build ==="
docker build -t "${IMAGE}" .

echo ""
echo "=== §2 ENTRYPOINT + versions ==="
docker run --rm "${IMAGE}" --help
docker run --rm --entrypoint bash "${IMAGE}" -c "
  echo 'GDAL :' && gdal-config --version
  echo 'PDAL :' && pdal --version 2>&1 | head -1
  echo 'pullauta :' && pullauta --version 2>&1 | head -1 || echo '(pas de --version)'
  echo 'Python :' && python --version
"

echo ""
echo "=== §3 init réel avec volume ==="
# PowerShell : -v \${PWD}:/app  /  bash : -v "$(pwd):/app"
docker run --rm -v "$(pwd):/app" "${IMAGE}" init "${TERRAIN}" --center 49.043 -0.421 --crs EPSG:2154

echo ""
echo "=== §4 Vérification fichiers survivent à l'arrêt ==="
if grep -q "${TERRAIN}" config.yaml; then
  echo "OK : ${TERRAIN} présent dans config.yaml"
else
  echo "ÉCHEC : ${TERRAIN} absent de config.yaml — volume non monté ?"
  exit 1
fi

if [ -f "${GEOREF}" ]; then
  echo "OK : ${GEOREF} créé"
  echo "     declination = $(grep -o 'declination="[^"]*"' "${GEOREF}")"
else
  echo "ÉCHEC : ${GEOREF} absent — vérifier assets/ monté en écriture"
  exit 1
fi

echo ""
echo "=== §5 tiles depuis le conteneur ==="
docker run --rm -v "$(pwd):/app" "${IMAGE}" tiles "${TERRAIN}"

echo ""
echo "=== §6 Nettoyage ==="
# Retirer l'entrée test_docker de config.yaml (ligne et ses sous-clés)
python - <<'PY'
import pathlib, re
p = pathlib.Path("config.yaml")
text = p.read_text(encoding="utf-8")
lines = text.split("\n")
result, skip = [], False
key = "  test_docker:"
for line in lines:
    s = line.rstrip()
    if s == key or (s.startswith(key) and len(s) > len(key) and s[len(key)] in " #"):
        skip = True
        continue
    if skip and s.startswith("    "):
        continue
    skip = False
    result.append(line)
p.write_text("\n".join(result), encoding="utf-8")
print("config.yaml nettoyé")
PY

rm -f "${GEOREF}"
echo "OK : ${GEOREF} supprimé"

echo ""
echo "=== Tous les contrôles passés ==="
