"""Configuration pour les notebooks Jupyter du dépôt Pacing."""

from __future__ import annotations

from pathlib import Path

from pacing.config.paths import PROJECT_DIR, ensure_project_imports


def ensure_project_root() -> Path:
    """Ajoute la racine du dépôt à ``sys.path`` pour les imports ``pacing.*``."""
    return ensure_project_imports()
