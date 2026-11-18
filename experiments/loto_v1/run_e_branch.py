"""Lance la branche E en séquence : LOTO E → planches TE → table comparative.

Usage :
  cd e:/Vikazim/Ovector
  C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/run_e_branch.py
"""
from __future__ import annotations

import logging
import pathlib
import subprocess
import sys

_THIS = pathlib.Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

STEPS = [
    ("LOTO E (4 folds RF_leaf5)",   _THIS / "loto_pipeline_e.py"),
    ("Planches T vs E",             _THIS / "make_planches_te.py"),
    ("Tableau comparatif T vs E",   _THIS / "compare_te.py"),
]


def main() -> None:
    env = {**__import__("os").environ, "PYTHONUTF8": "1"}
    for label, script in STEPS:
        log.info("=== %s ===", label)
        subprocess.run([sys.executable, str(script)], check=True, env=env)
        log.info("=== %s : DONE ===", label)
    log.info("Pipeline E complet.")


if __name__ == "__main__":
    main()
