"""Shim de compatibilité — lancer ``python -m pacing.ui.desktop.app``.

Ajoute la racine du dépôt à ``sys.path`` pour permettre
``python3 app/interfaces/desktop_flet.py`` sans ``pip install -e .``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pacing.ui.desktop.app import *  # noqa: F401,F403
from pacing.ui.desktop.app import main, run

__all__ = ["main", "run"]

if __name__ == "__main__":
    run()
