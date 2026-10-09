"""Résolution du mode de pipeline végétation par terrain."""
from __future__ import annotations

import logging
from typing import Literal

log = logging.getLogger(__name__)

VegMode = Literal["kp", "hag"] | None

_LEGACY_WARNING = (
    "⚠ aucune clé vegetation_source pour %s — comportement hérité (HAG + KP).\n"
    "   Pour un run de production sans PDAL : ajouter vegetation_source: \"kp\"."
)


def resolve_veg_source(terrain: str, cfg: dict) -> VegMode:
    """Retourne le mode pipeline pour le terrain : 'kp', 'hag', ou None (legacy).

    La clé globale vegetation.source est ignorée — elle sera supprimée en P1b.
    None = état de migration : comportement historique complet + warning.
    """
    source = cfg.get("terrains", {}).get(terrain, {}).get("vegetation_source")
    if source == "kp":
        return "kp"
    if source == "hag":
        return "hag"
    if source is not None:
        log.warning(
            "vegetation_source=%r pour %r non reconnu — mode legacy", source, terrain
        )
    log.warning(_LEGACY_WARNING, terrain)
    return None
