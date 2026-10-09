"""Résolution du mode de pipeline végétation par terrain.

Contrat des modes (PLAN 4, option A — routage inchangé, messages distincts) :

- ``"kp"`` : branche HAG désactivée (pdal, process_hag, vegetation, mask) ;
  chemin KP conservé. ``--from-step`` HAG refusé.
- ``"hag"`` : mode EXPLICITEMENT demandé. Routage identique à ``None`` ;
  message INFO, pas d'avertissement de migration. ``"hag"`` ne signifie PAS
  « HAG uniquement » et ne signifie PAS que HAG alimente l'OMAP :
  ``vegetation_kp.gpkg`` reste la seule source de végétation de l'OMAP
  (``step_assemble``) ; la branche HAG garde son rôle analytique et sa QA
  (repli QA si ``vegetation_kp.gpkg`` est absent).
- ``None`` (legacy) : aucune clé ``vegetation_source`` ; comportement historique
  conservé (chaîne HAG + KP) avec avertissement de migration en attente.
  Un terrain sans clé n'est JAMAIS classé implicitement en HAG ou en KP.

La source se lit uniquement dans ``terrains.<terrain>.vegetation_source``.
Il n'existe plus de clé globale ``vegetation.source`` (supprimée en P1b).
"""
from __future__ import annotations

import logging
from typing import Literal

log = logging.getLogger(__name__)

VegMode = Literal["kp", "hag"] | None

_HAG_INFO = (
    "vegetation_source: hag pour %r — mode HAG explicite (routage identique au legacy). "
    "vegetation_kp.gpkg reste la végétation de l'OMAP ; la branche HAG alimente l'analyse et la QA."
)

_LEGACY_WARNING = (
    "⚠ aucune clé vegetation_source pour %s — comportement hérité (HAG + KP), migration en attente.\n"
    "   Pour un run de production sans PDAL : ajouter vegetation_source: \"kp\"."
)


def resolve_veg_source(terrain: str, cfg: dict) -> VegMode:
    """Retourne le mode pipeline pour le terrain : 'kp', 'hag', ou None (legacy).

    Voir le contrat des modes en tête de module.
    """
    source = cfg.get("terrains", {}).get(terrain, {}).get("vegetation_source")
    if source == "kp":
        return "kp"
    if source == "hag":
        log.info(_HAG_INFO, terrain)
        return "hag"
    if source is not None:
        log.warning(
            "vegetation_source=%r pour %r non reconnu — mode legacy", source, terrain
        )
    log.warning(_LEGACY_WARNING, terrain)
    return None
