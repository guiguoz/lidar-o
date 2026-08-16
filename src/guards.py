"""Guards d'exécution — fraîcheur des artefacts et cohérence de config.

Deux mécanismes complémentaires :

1. Fraîcheur mtime — pour les chaînes de fichiers de données :
       density_hag.tif → density_hag_classified.tif
   Le mtime de la source est une information fiable (re-run PDAL → nouveau tif).
   Fonctions : check_freshness, assert_fresh, warn_if_stale

2. Comparaison de snapshot — pour les changements de config :
       config.yaml → GPKG dérivé
   Le mtime de config.yaml n'est pas fiable (toucher un paramètre BD TOPO
   invaliderait les artefacts végétation ; un commit simultané peut inverser
   l'ordre des mtimes). La bonne source de vérité est le snapshot enregistré
   dans run_metadata.json après chaque run réussi.
   Fonction : check_config_snapshot
"""
from __future__ import annotations

import json
import logging
import pathlib

log = logging.getLogger(__name__)

_FMT = "%Y-%m-%dT%H:%M:%S"


# ── Fraîcheur mtime (chaînes de fichiers de données) ─────────────────────────

def check_freshness(artifact: pathlib.Path, source: pathlib.Path) -> bool:
    """Retourne True si artifact est frais (mtime >= source), False si périmé.

    Si l'un des deux fichiers est absent, retourne True (pas de blocage
    sans information). Ne lève pas d'exception.
    """
    if not artifact.exists() or not source.exists():
        return True
    return artifact.stat().st_mtime >= source.stat().st_mtime


def assert_fresh(
    artifact: pathlib.Path,
    source: pathlib.Path,
    regen_hint: str = "",
) -> None:
    """Lève SystemExit si artifact est périmé par rapport à source.

    À utiliser dans les scripts de production où un artefact périmé
    produit des résultats plausibles mais faux.
    """
    if check_freshness(artifact, source):
        return
    import datetime as _dt
    art_t = _dt.datetime.fromtimestamp(artifact.stat().st_mtime).strftime(_FMT)
    src_t = _dt.datetime.fromtimestamp(source.stat().st_mtime).strftime(_FMT)
    hint = f"\n  {regen_hint}" if regen_hint else ""
    raise SystemExit(
        f"ARRET -- GARDE-FOU FRAICHEUR :\n"
        f"  {artifact.name} ({art_t}) est anterieur a {source.name} ({src_t}).\n"
        f"  Regenerer l'artefact avant de continuer.{hint}"
    )


def warn_if_stale(artifact: pathlib.Path, source: pathlib.Path) -> bool:
    """Affiche un avertissement si artifact est périmé, retourne True si périmé.

    À utiliser dans les scripts de rapport où continuer est permis mais
    l'anomalie doit être signalée.
    """
    if check_freshness(artifact, source):
        return False
    import datetime as _dt
    art_t = _dt.datetime.fromtimestamp(artifact.stat().st_mtime).strftime(_FMT)
    src_t = _dt.datetime.fromtimestamp(source.stat().st_mtime).strftime(_FMT)
    print(
        f"ATTENTION -- ARTEFACT PERIME :\n"
        f"  {artifact.name} ({art_t}) < {source.name} ({src_t})\n"
        f"  Ce rapport peut etre base sur des donnees anterieures."
    )
    return True


# ── Cohérence de config (comparaison de snapshot) ────────────────────────────

def check_config_snapshot(cfg: dict, metadata_path: pathlib.Path) -> list[str]:
    """Compare la config actuelle au snapshot enregistré dans run_metadata.json.

    Retourne la liste des écarts (chaînes lisibles), vide si tout est cohérent
    ou si le snapshot est absent (premier run, pas de référence).

    Les clés comparées sont celles enregistrées par write_config_snapshot() :
    gaussian_sigma, thresholds, min_area_m2 et fusion_distance_m par classe.
    """
    if not metadata_path.exists():
        return []
    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    snap: dict = meta.get("config_snapshot", {})
    if not snap:
        return []

    diffs: list[str] = []

    gen = cfg.get("generalization", {})
    profile_name = gen.get("active_profile", "")
    profile = gen.get("profiles", {}).get(profile_name, {})
    veg = cfg.get("vegetation", {})
    preset_name = veg.get("active_preset", "")
    preset = veg.get("presets", {}).get(preset_name, {})

    # Profil
    if snap.get("generalization_profile") != profile_name:
        diffs.append(
            f"generalization_profile: snapshot={snap.get('generalization_profile')!r}"
            f" config={profile_name!r}"
        )

    # Sigma
    sigma_now = veg.get("process_hag", {}).get("gaussian_sigma")
    if snap.get("gaussian_sigma") != sigma_now:
        diffs.append(
            f"gaussian_sigma: snapshot={snap.get('gaussian_sigma')} config={sigma_now}"
        )

    # density_mode
    dm = veg.get("density_metric", {})
    mode_now = dm.get("mode")
    if snap.get("density_mode") is not None and snap.get("density_mode") != mode_now:
        diffs.append(f"density_mode: snapshot={snap.get('density_mode')!r} config={mode_now!r}")

    # grid_resolution_m
    res_now = veg.get("grid_resolution_m")
    if snap.get("grid_resolution_m") is not None and snap.get("grid_resolution_m") != res_now:
        diffs.append(f"grid_resolution_m: snapshot={snap.get('grid_resolution_m')} config={res_now}")

    # normalization_mode
    norm_now = veg.get("normalization", {}).get("mode")
    if snap.get("normalization_mode") is not None and snap.get("normalization_mode") != norm_now:
        diffs.append(
            f"normalization_mode: snapshot={snap.get('normalization_mode')!r} config={norm_now!r}"
        )

    # Seuils
    thresh_now = preset.get("thresholds")
    if snap.get("thresholds") != thresh_now:
        diffs.append(
            f"thresholds: snapshot={snap.get('thresholds')} config={thresh_now}"
        )

    # min_area_m2 par classe
    snap_ma: dict = snap.get("min_area_m2", {})
    cfg_ma: dict = profile.get("min_area_m2", {})
    for cls in [406, 408, 410]:
        sv = snap_ma.get(cls) or snap_ma.get(str(cls))
        cv = cfg_ma.get(cls) or cfg_ma.get(str(cls))
        if sv != cv:
            diffs.append(f"min_area_m2[{cls}]: snapshot={sv} config={cv}")

    # fusion_distance_m par classe
    snap_fd: dict = snap.get("fusion_distance_m", {})
    cfg_fd: dict = profile.get("fusion_distance_m", {})
    for cls in [406, 408, 410]:
        sv = snap_fd.get(cls) or snap_fd.get(str(cls))
        cv = cfg_fd.get(cls) or cfg_fd.get(str(cls))
        if sv != cv:
            diffs.append(f"fusion_distance_m[{cls}]: snapshot={sv} config={cv}")

    return diffs
