"""
Phase 0 — Script de reconnaissance.

Usage :
    python scripts/phase0_recon.py wfs
    python scripts/phase0_recon.py lidar <xmin> <ymin> <xmax> <ymax>
    python scripts/phase0_recon.py kp <dossier_sortie_kp>
    python scripts/phase0_recon.py all <dossier_sortie_kp> <xmin> <ymin> <xmax> <ymax>

Sorties imprimées dans le terminal — à copier dans docs/etat_existant.md.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


WFS_URL = "https://data.geopf.fr/wfs"
LIDAR_WFS_URL = "https://data.geopf.fr/wfs"
LIDAR_LAYER = "IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle"  # nom courant nov 2025 — confirmer via GetCapabilities
OMAPMAKER_BINARY = "omapmaker"  # à ajuster si chemin complet nécessaire


def test_wfs_capabilities() -> None:
    """Imprime les typenames exacts des couches BD TOPO disponibles sur data.geopf.fr/wfs."""
    import requests

    print("\n=== WFS GetCapabilities ===")
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetCapabilities",
    }
    try:
        r = requests.get(WFS_URL, params=params, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[ERREUR] Impossible de joindre le WFS : {e}")
        return

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        print(f"[ERREUR] Réponse XML invalide : {e}")
        return

    ns = {
        "wfs": "http://www.opengis.net/wfs/2.0",
        "ows": "http://www.opengis.net/ows/1.1",
    }

    feature_types = root.findall(".//wfs:FeatureType", ns)
    if not feature_types:
        feature_types = root.findall(".//{http://www.opengis.net/wfs/2.0}FeatureType")

    if not feature_types:
        print("[INFO] Aucun FeatureType trouvé — inspecter le XML brut ci-dessous")
        print(r.text[:3000])
        return

    def _get_name(ft: ET.Element) -> str:
        for tag in ("{http://www.opengis.net/wfs/2.0}Name", "Name"):
            el = ft.find(tag)
            if el is not None and el.text:
                return el.text
        return ""

    all_names = [_get_name(ft) for ft in feature_types]
    all_names = [n for n in all_names if n]
    print(f"\nTotal couches WFS : {len(all_names)}")

    bd_topo_types = [n for n in all_names if any(
        kw in n.upper() for kw in ("BDTOPO", "ROUTE", "BATIMENT", "EAU", "LIGNE", "VOIE")
    )]
    print(f"\nCouches BD TOPO trouvées ({len(bd_topo_types)}) :")
    for t in sorted(bd_topo_types):
        print(f"  {t}")

    lidar_types = [n for n in all_names if any(
        kw in n.upper() for kw in ("LIDAR", "NUAGES-DE-POINTS", "NUAGES_DE_POINTS")
    )]
    print(f"\nCouches LiDAR HD trouvées ({len(lidar_types)}) :")
    for t in sorted(lidar_types):
        print(f"  {t}")
    if lidar_types:
        print("→ Comparer avec LIDAR_LAYER en tête de script ; mettre à jour si différent")

    if not bd_topo_types and not lidar_types:
        print("\n[DIAGNOSTIC] Aucune couche filtrée — premières couches brutes reçues :")
        for n in all_names[:20]:
            print(f"  {n}")

    print("\n→ BD TOPO : reporter dans config.yaml (section bd_topo.layers) et symbols_isom.yaml (bd_topo_mapping)")


def test_lidar_index(bbox: tuple[float, float, float, float]) -> None:
    """Teste l'index des dalles LIDAR HD sur une emprise EPSG:2154."""
    import requests

    xmin, ymin, xmax, ymax = bbox
    print(f"\n=== Index LIDAR HD — emprise {bbox} ===")
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": LIDAR_LAYER,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},EPSG:2154",
        "resultType": "hits",
    }
    try:
        r = requests.get(LIDAR_WFS_URL, params=params, timeout=30)
        r.raise_for_status()
        # Réponse XML (WFS 2.0 hits) — extraire numberMatched
        try:
            root = ET.fromstring(r.content)
            total = (
                root.get("numberMatched")
                or root.get("numberOfFeatures")
                or root.get("totalFeatures")
                or "?"
            )
        except ET.ParseError:
            total = "? (réponse non parseable)"
        print(f"Dalles trouvées sur l'emprise : {total}")
        if total in ("0", 0):
            print("[ATTENTION] Aucune dalle — emprise hors couverture ou typename incorrect")
        elif total == "?":
            print("[INFO] Réponse reçue mais attribut numberMatched absent — inspecter :")
            print(r.text[:500])
    except Exception as e:
        print(f"[ERREUR] {e}")
        print(f"  URL tentée : {r.url if 'r' in dir() else 'N/A'}")
        print("  → Vérifier le typename LIDAR dans LIDAR_LAYER en haut du script")


def inspect_kp_outputs(kp_outdir: Path) -> None:
    """
    Inspecte les sorties de Karttapullautin dans kp_outdir.

    Répond aux questions :
    1. Quels fichiers DXF sont produits ? Quels sont leurs noms de calques ?
    2. KP expose-t-il un raster de densité végétation continu (float) réutilisable ?
       Ou seulement le PNG vert rendu (non réutilisable) ?
    """
    print(f"\n=== Sorties Karttapullautin — {kp_outdir} ===")

    if not kp_outdir.exists():
        print(f"[ERREUR] Dossier inexistant : {kp_outdir}")
        return

    all_files = list(kp_outdir.rglob("*"))
    print(f"\nFichiers produits ({len(all_files)}) :")
    for f in sorted(all_files):
        if f.is_file():
            size_kb = f.stat().st_size // 1024
            print(f"  {f.relative_to(kp_outdir)}  ({size_kb} kB)")

    # Inspecter les DXF
    dxf_files = list(kp_outdir.rglob("*.dxf"))
    if dxf_files:
        print(f"\nFichiers DXF ({len(dxf_files)}) — noms de calques :")
        for dxf in dxf_files:
            layers = _extract_dxf_layers(dxf)
            print(f"  {dxf.name} :")
            for layer in sorted(layers):
                print(f"    → {layer!r}")
        print("\n→ À reporter dans config.yaml (karttapullautin.expected_dxf_layers)")
    else:
        print("[ATTENTION] Aucun fichier DXF trouvé")

    # Inspecter les rasters potentiellement réutilisables
    raster_exts = {".tif", ".tiff", ".img", ".asc", ".xyz"}
    rasters = [f for f in all_files if f.suffix.lower() in raster_exts and f.is_file()]
    png_files = [f for f in all_files if f.suffix.lower() == ".png" and f.is_file()]

    print(f"\nRasters trouvés (hors PNG) : {len(rasters)}")
    for r in rasters:
        _inspect_raster(r)

    print(f"\nPNG trouvés : {len(png_files)}")
    for p in png_files:
        print(f"  {p.name}")
        if p.name in ("undergrowth.png", "vegetation.png"):
            _audit_kp_png(p)

    print("\n→ DÉCISION CRITIQUE pour config.vegetation.source :")
    if rasters:
        print("  KP produit des rasters non-PNG → évaluer s'ils encodent une densité float continue")
        print("  Si oui  → source: 'kp'   (défaut)")
        print("  Si non  → source: 'pdal' (plan B)")
    else:
        print("  Aucun raster non-PNG trouvé → KP ne produit pas de densité réutilisable")
        print("  → source: 'pdal' (plan B activé)")


def _extract_dxf_layers(dxf_path: Path) -> set[str]:
    """Extrait les noms de calques d'un fichier DXF (parsing texte léger)."""
    layers: set[str] = set()
    try:
        content = dxf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return layers

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "8" and i + 1 < len(lines):
            layer_name = lines[i + 1].strip()
            if layer_name and not layer_name.startswith("0"):
                layers.add(layer_name)
            elif layer_name == "0":
                layers.add("0")
    return layers


def _inspect_raster(path: Path) -> None:
    """Imprime les métadonnées GDAL d'un raster (type, min, max, CRS)."""
    try:
        from osgeo import gdal
        ds = gdal.Open(str(path))
        if ds is None:
            print(f"  {path.name} — non lisible par GDAL")
            return
        band = ds.GetRasterBand(1)
        min_val, max_val = band.ComputeRasterStatistics(False)[0:2]
        dtype = gdal.GetDataTypeName(band.DataType)
        proj = ds.GetProjection()
        print(f"  {path.name} — type={dtype}, min={min_val:.3f}, max={max_val:.3f}, CRS={'défini' if proj else 'ABSENT'}")
    except ImportError:
        print(f"  {path.name} — GDAL non disponible pour l'inspection")
    except Exception as e:
        print(f"  {path.name} — erreur : {e}")


def _audit_kp_png(path: Path) -> None:
    """Audit PNG KP : bit-depth, palette indexée, valeurs distinctes (seuillabilité)."""
    try:
        from osgeo import gdal
        ds = gdal.Open(str(path))
        if ds is None:
            print(f"    [GDAL] non lisible")
            return
        band = ds.GetRasterBand(1)
        dtype = gdal.GetDataTypeName(band.DataType)
        ct = band.GetColorTable()
        stats = band.ComputeRasterStatistics(False)
        hist = band.GetHistogram(0, 256, 256, False, False)
        n_distinct = sum(1 for v in hist if v > 0)
        print(f"    bit-depth      : {dtype}")
        print(f"    palette indexée: {'oui' if ct else 'non'}")
        print(f"    min={stats[0]:.0f}  max={stats[1]:.0f}  valeurs distinctes={n_distinct}")
        if n_distinct <= 5:
            print(f"    ⚠️  Déjà quantifié ({n_distinct} teintes) — finesse de calibration perdue")
        else:
            print(f"    OK : gradient continu ou semi-continu ({n_distinct} valeurs)")
        print(f"    → Reporter dans docs/etat_existant.md § 'Audit PNG KP'")
    except Exception as e:
        print(f"    [erreur audit] {e}")


def check_omapmaker_version(binary: str = OMAPMAKER_BINARY) -> bool:
    """Vérifie la disponibilité d'OmapMaker et imprime sa version. Retourne True si trouvé."""
    import subprocess
    print("\n=== OmapMaker — version ===")
    for flags in (["--version"], ["--help"], []):
        try:
            result = subprocess.run(
                [binary] + flags,
                capture_output=True, text=True, timeout=10,
            )
            lines = (result.stdout or result.stderr).strip().splitlines()
            if lines:
                print(f"  {lines[0]}")
            print(f"  Binaire : {binary}")
            return True
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"  [ERREUR] {e}")
            return False
    print(f"  [ERREUR] Binaire '{binary}' introuvable")
    print("  -> Installer OmapMaker (GitHub : yvind/omapmaker, Rust)")
    return False


def _run_omapmaker(binary: str, input_tile: Path, out_dir: Path) -> bool:
    """Lance OmapMaker sur input_tile → out_dir. Retourne True si succès."""
    import subprocess
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n  Lancement : {binary} {input_tile} -> {out_dir}")
    try:
        result = subprocess.run(
            [binary, str(input_tile), "--output", str(out_dir)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"  [ERREUR code {result.returncode}]")
            if result.stderr:
                print(f"  {result.stderr[:500]}")
            return False
        print("  Terminé.")
        return True
    except FileNotFoundError:
        print(f"  [ERREUR] Binaire '{binary}' introuvable")
        return False
    except subprocess.TimeoutExpired:
        print("  [ERREUR] Timeout (> 5 min)")
        return False
    except Exception as e:
        print(f"  [ERREUR] {e}")
        return False


def _parse_omap(omap_path: Path) -> dict:
    """Parse un fichier .omap (XML OOM). Retourne CRS, déclinaison, symboles végétation, présence polygones."""
    result: dict = {
        "crs": None,
        "magnetic_declination": None,
        "symbols": [],
        "vege_symbols": [],
        "has_polygons": False,
        "parse_error": None,
    }
    try:
        tree = ET.parse(omap_path)
        root = tree.getroot()

        # Géoréférencement
        geo = root.find(".//georeferencing")
        if geo is not None:
            result["magnetic_declination"] = geo.get("declination") or geo.get("magnetic_declination")
            proj = geo.find("projected_crs")
            if proj is not None:
                result["crs"] = proj.get("id") or (proj.find("id") or ET.Element("x")).get("id")

        # Symboles
        for sym in root.findall(".//*[@code]"):
            code = sym.get("code", "")
            name = sym.get("name", "")
            result["symbols"].append({"code": code, "name": name, "tag": sym.tag})
            try:
                code_int = int(float(code))
                if 401 <= code_int <= 412:
                    result["vege_symbols"].append({"code": code, "name": name})
            except (ValueError, TypeError):
                pass

        # Présence de polygones (type="1" dans OOM = area)
        for obj in root.findall(".//object[@type='1']"):
            result["has_polygons"] = True
            break

    except ET.ParseError as e:
        result["parse_error"] = f"XML invalide : {e}"
    except Exception as e:
        result["parse_error"] = str(e)

    return result


def inspect_omapmaker_outputs(omap_dir: Path, binary: str = OMAPMAKER_BINARY,
                               input_tile: Path | None = None) -> None:
    """
    Phase 0 bis — Inspecte les sorties OmapMaker. Répond aux 4 questions de l'avenant A :
      Q1. Export .omap robuste et réutilisable ?
      Q2. Géoréférencement Lambert-93 / dalle IGN fonctionnel ?
      Q3. Structure des calques (symboles, organisation) ?
      Q4. Végétation exploitable (polygones ISOM) ou seuillage brut ?
    """
    print(f"\n=== OmapMaker — Phase 0 bis — {omap_dir} ===")

    if input_tile is not None:
        print(f"\n  Lancement OmapMaker sur : {input_tile}")
        _run_omapmaker(binary, input_tile, omap_dir)

    if not omap_dir.exists():
        print(f"[ERREUR] Dossier inexistant : {omap_dir}")
        return

    all_files = [f for f in omap_dir.rglob("*") if f.is_file()]
    print(f"\nFichiers produits ({len(all_files)}) :")
    for f in sorted(all_files):
        print(f"  {f.relative_to(omap_dir)}  ({f.stat().st_size // 1024} kB)")

    omap_files = list(omap_dir.rglob("*.omap"))
    if not omap_files:
        print("\n  Q1 [ECHEC] Aucun .omap produit — OmapMaker n'a pas généré de sortie OOM.")
        print("  -> Vérifier l'interface CLI (--output peut différer selon la version).")
        return

    for omap_path in omap_files:
        print(f"\n  Fichier : {omap_path.name}")
        info = _parse_omap(omap_path)

        if info["parse_error"]:
            print(f"  Q1 [ECHEC] Parse .omap : {info['parse_error']}")
            continue

        # Q1
        n_sym = len(info["symbols"])
        print(f"  Q1 — Export .omap : OK ({n_sym} symboles parsés) — fichier réutilisable.")

        # Q2
        crs = info["crs"]
        decl = info["magnetic_declination"]
        if crs:
            lambert = "2154" in str(crs) or "LAMB" in str(crs).upper() or "RGF93" in str(crs).upper()
            print(f"  Q2 — CRS : {crs} {'-> Lambert-93 CONFIRME' if lambert else '-> NON Lambert-93 (a verifier)'}")
        else:
            print("  Q2 — CRS : ABSENT dans le .omap — géoréférencement non trouvé.")
        if decl:
            print(f"       Déclinaison magnétique : {decl}°")

        # Q3
        print(f"  Q3 — Symboles totaux : {n_sym}")
        vege = info["vege_symbols"]
        if vege:
            print(f"       Symboles végétation 401-412 ({len(vege)}) :")
            for s in vege:
                print(f"         {s['code']:>6}  {s['name']}")
        else:
            print("       Aucun symbole végétation 401-412 détecté.")

        # Q4
        has_poly = info["has_polygons"]
        if vege and has_poly:
            print("  Q4 — Végétation : EXPLOITABLE — polygones avec symboles ISOM présents.")
        elif vege:
            print("  Q4 — Végétation : symboles ISOM présents mais aucun polygone détecté.")
        else:
            print("  Q4 — Végétation : aucun symbole ISOM — seuillage brut ou absent.")

    print("\n=== Synthèse OmapMaker ===")
    print("Reporter Q1-Q4 dans docs/etat_existant.md.")
    print("Comparer côte-à-côte dans OOM : PNG KP | PDAL maison | MNH | OmapMaker.")
    print("Décision : OmapMaker robuste → privilégier son .omap ; sinon → architecture KP+CRT.")


def check_kp_version(kp_binary: str = "pullauta") -> None:
    """Affiche la version de Karttapullautin installée."""
    import subprocess
    print("\n=== Version Karttapullautin ===")
    try:
        result = subprocess.run(
            [kp_binary],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout.strip() or result.stderr.strip()).splitlines()[0]
        print(f"  {output}")
        print("\n→ À reporter dans config.yaml (karttapullautin.version) et Dockerfile (KP_VERSION)")
    except FileNotFoundError:
        print(f"  [ERREUR] Binaire '{kp_binary}' introuvable")
        print("  → Installer KP ou passer le chemin complet")
    except Exception as e:
        print(f"  [ERREUR] {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 0 — Reconnaissance lidar-o")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("wfs", help="Lister les couches WFS BD TOPO")

    p_lidar = sub.add_parser("lidar", help="Tester l'index LIDAR HD sur une emprise")
    p_lidar.add_argument("bbox", nargs=4, type=float, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))

    p_kp = sub.add_parser("kp", help="Inspecter les sorties Karttapullautin")
    p_kp.add_argument("kp_outdir", type=Path)

    p_om = sub.add_parser("omapmaker", help="Phase 0 bis — Inspecter sorties OmapMaker (Q1-Q4)")
    p_om.add_argument("omap_dir", type=Path,
                      help="Dossier contenant les sorties OmapMaker (ou à créer si --input-tile)")
    p_om.add_argument("--binary", default=OMAPMAKER_BINARY,
                      help=f"Chemin binaire OmapMaker (défaut: {OMAPMAKER_BINARY})")
    p_om.add_argument("--input-tile", type=Path, default=None,
                      help="Si fourni, lance OmapMaker sur cette dalle avant inspection")

    p_all = sub.add_parser("all", help="Tout lancer (Phase 0 + Phase 0 bis optionnel)")
    p_all.add_argument("kp_outdir", type=Path)
    p_all.add_argument("bbox", nargs=4, type=float, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))
    p_all.add_argument("--omapmaker-dir", type=Path, default=None,
                       help="Si fourni, inspecte aussi les sorties OmapMaker (Phase 0 bis)")
    p_all.add_argument("--omapmaker-binary", default=OMAPMAKER_BINARY)
    p_all.add_argument("--omapmaker-input-tile", type=Path, default=None)

    args = parser.parse_args()

    if args.cmd == "wfs":
        test_wfs_capabilities()
    elif args.cmd == "lidar":
        test_lidar_index(tuple(args.bbox))
    elif args.cmd == "kp":
        check_kp_version()
        inspect_kp_outputs(args.kp_outdir)
    elif args.cmd == "omapmaker":
        check_omapmaker_version(args.binary)
        inspect_omapmaker_outputs(args.omap_dir, args.binary, args.input_tile)
    elif args.cmd == "all":
        test_wfs_capabilities()
        test_lidar_index(tuple(args.bbox))
        check_kp_version()
        inspect_kp_outputs(args.kp_outdir)
        if args.omapmaker_dir:
            check_omapmaker_version(args.omapmaker_binary)
            inspect_omapmaker_outputs(
                args.omapmaker_dir, args.omapmaker_binary, args.omapmaker_input_tile
            )
    else:
        parser.print_help()
        sys.exit(1)

    print("\n=== Résumé ===")
    print("Compléter docs/etat_existant.md avec les résultats ci-dessus.")
    print("Mettre à jour config.yaml (expected_dxf_layers, bd_topo.layers, vegetation.source).")


if __name__ == "__main__":
    main()
