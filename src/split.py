"""Découpage calibration / validation pour l'expérience V0.

Charge experiments/v0/split.yaml et expose les limites effectives des zones
calibration et validation. Les bornes sont toujours dérivées de
split_y ± buffer_half_width_m — jamais hardcodées.

Convention buffer :
  buffer_half_width_m = demi-largeur ; chaque zone commence à split_y ± cette valeur.
  Buffer total = 2 × buffer_half_width_m.

Si buffer.status == "provisional", tout rapport de métrique finale doit inclure
l'avertissement retourné par provisional_flag().
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

_DEFAULT_YAML = pathlib.Path(__file__).parent.parent / "experiments" / "v0" / "split.yaml"

_FLAG_MSG = (
    "[ATTENTION] Buffer split PROVISOIRE (demi-largeur {hw} m, total {tw} m) "
    "— métriques à revalider après gel du découpage."
)


@dataclass(frozen=True)
class SplitConfig:
    split_y: float
    validation_side: str
    calibration_side: str
    buffer_half_width_m: float
    buffer_status: str

    @property
    def validation_y_min(self) -> float:
        """Borne sud de la zone validation (split_y + buffer_half_width_m)."""
        return self.split_y + self.buffer_half_width_m

    @property
    def calibration_y_max(self) -> float:
        """Borne nord de la zone calibration (split_y - buffer_half_width_m)."""
        return self.split_y - self.buffer_half_width_m

    @property
    def buffer_total_m(self) -> float:
        return self.buffer_half_width_m * 2

    @property
    def is_provisional(self) -> bool:
        return self.buffer_status == "provisional"

    def provisional_flag(self) -> str | None:
        """Retourne le message d'avertissement si le buffer est provisoire, sinon None."""
        if self.is_provisional:
            return _FLAG_MSG.format(
                hw=self.buffer_half_width_m, tw=self.buffer_total_m
            )
        return None

    def as_snapshot_dict(self) -> dict[str, Any]:
        """Fragment prêt à être injecté dans config_snapshot."""
        return {
            "split_y": self.split_y,
            "validation_side": self.validation_side,
            "calibration_side": self.calibration_side,
            "buffer_half_width_m": self.buffer_half_width_m,
            "buffer_total_m": self.buffer_total_m,
            "buffer_status": self.buffer_status,
            "validation_y_min": self.validation_y_min,
            "calibration_y_max": self.calibration_y_max,
        }


def load_split(yaml_path: str | pathlib.Path | None = None) -> SplitConfig:
    """Charge le fichier split.yaml et retourne un SplitConfig."""
    path = pathlib.Path(yaml_path) if yaml_path is not None else _DEFAULT_YAML
    with open(path, encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh)

    buf = raw.get("buffer", {})
    return SplitConfig(
        split_y=float(raw["split_y"]),
        validation_side=str(raw["validation_side"]),
        calibration_side=str(raw["calibration_side"]),
        buffer_half_width_m=float(buf["buffer_half_width_m"]),
        buffer_status=str(buf["status"]),
    )
