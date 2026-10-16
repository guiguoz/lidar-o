"""Résolution du mode de pipeline végétation par terrain.

Contrat des modes (KP par défaut — décision porteur) :

- ``"kp"`` ou clé ABSENTE (KP par défaut) : branche HAG désactivée
  (pdal, process_hag, vegetation, mask) ; chemin KP actif. ``out_kp_<terrain>/``
  doit exister, sinon ``step_vegetation_kp`` lève une erreur explicite.
- ``"hag"`` : mode HAG EXPLICITEMENT demandé. La chaîne HAG est exécutée.
  Message INFO. ``"hag"`` ne signifie PAS « HAG uniquement » et ne signifie PAS
  que HAG alimente l'OMAP : ``vegetation_kp.gpkg`` reste la seule source de
  végétation de l'OMAP (``step_assemble``) ; la branche HAG garde son rôle
  analytique et sa QA (repli QA si ``vegetation_kp.gpkg`` est absent).
- valeur inconnue : erreur explicite (pas de repli silencieux).

La source se lit uniquement dans ``terrains.<terrain>.vegetation_source``.
Il n'existe plus de clé globale ``vegetation.source`` (supprimée en P1b).
"""
from __future__ import annotations

import logging
from typing import Literal

log = logging.getLogger(__name__)

VegMode = Literal["kp", "hag"]

_KP_DEFAUT_INFO = (
    "vegetation_source absente pour %r — KP par défaut. "
    "Pour la chaîne HAG, déclarer vegetation_source: \"hag\" explicitement."
)

_HAG_INFO = (
    "vegetation_source: hag pour %r — mode HAG explicite. "
    "vegetation_kp.gpkg reste la végétation de l'OMAP ; la branche HAG alimente l'analyse et la QA."
)


def resolve_veg_source(terrain: str, cfg: dict) -> VegMode:
    """Retourne le mode pipeline pour le terrain : 'kp' ou 'hag'.

    Clé absente = 'kp' (défaut). Valeur inconnue = ValueError.
    Voir le contrat des modes en tête de module.
    """
    source = cfg.get("terrains", {}).get(terrain, {}).get("vegetation_source")
    if source is None:
        log.info(_KP_DEFAUT_INFO, terrain)
        return "kp"
    if source == "kp":
        return "kp"
    if source == "hag":
        log.info(_HAG_INFO, terrain)
        return "hag"
    raise ValueError(
        f"vegetation_source={source!r} pour {terrain!r} : valeur inconnue "
        "(attendu : 'kp' ou 'hag', ou clé absente pour KP par défaut)"
    )
