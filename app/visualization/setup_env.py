"""Configuration pour les notebooks sous app/visualization/."""

from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_project_path() -> ModuleType:
    if "project_path" in sys.modules:
        return sys.modules["project_path"]

    for candidate in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        module_file = candidate / "app" / "interfaces" / "project_path.py"
        if module_file.is_file():
            spec = importlib.util.spec_from_file_location("project_path", module_file) # prépare son chargement comme module Python
            mod = importlib.util.module_from_spec(spec) # Crée un objet module vide à partir de la spec
            assert spec.loader is not None
            spec.loader.exec_module(mod)
            sys.modules["project_path"] = mod
            return mod

    raise FileNotFoundError(
        "Impossible de trouver app/interfaces/project_path.py ; "
    )


def ensure_project_root() -> Path:
    """Ajoute la racine du depot a sys.path"""
    return _load_project_path().ensure_project_imports()
