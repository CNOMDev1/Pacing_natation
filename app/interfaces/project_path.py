"""Point de référence unique pour savoir où se trouve la racine du dépôt Pacing et pour que Python puisse importer le code du projet."""

from __future__ import annotations
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


def ensure_project_imports() -> Path:
    root = str(PROJECT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_DIR
