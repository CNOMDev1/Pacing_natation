"""Point de référence unique pour la racine du dépôt Pacing.

Ce module expose ``PROJECT_DIR`` (chemin absolu vers la racine du repo) et
``ensure_project_imports()`` qui ajoute cette racine à ``sys.path`` pour
permettre les imports ``from services.…`` depuis ``app/interfaces/``.

Utilisé par l'UI desktop (Flet) et tout script lancé
depuis ``app/interfaces/`` sans installation en mode paquet.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Racine du dépôt (Pacing/) : parents[2] depuis app/interfaces/
PROJECT_DIR = Path(__file__).resolve().parents[2]


def ensure_project_imports() -> Path:
    """Ajoute la racine du projet à ``sys.path`` si nécessaire.

    Returns:
        Path: Chemin absolu vers ``PROJECT_DIR``.
    """
    root = str(PROJECT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_DIR
