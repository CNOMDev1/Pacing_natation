"""Chemins canoniques du dépôt Pacing.

Centralise ``PROJECT_DIR`` et les dossiers ``data/`` pour éviter les
``Path(__file__).parents[N]`` dispersés dans les loaders et scripts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# services/paths.py → parents[1] = racine du dépôt
PROJECT_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORTS_DIR = DATA_DIR / "exports"

EXTRANAT_RAW_DIR = RAW_DIR / "extranat"
EXTRANAT_PROCESSED_DIR = PROCESSED_DIR / "extranat" / "competitions_per_type"

OMEGA_RAW_DIR = RAW_DIR / "omega"

USASWIMMING_RAW_DIR = RAW_DIR / "usaswimming"
USASWIMMING_PROCESSED_DIR = PROCESSED_DIR / "usaswimming"
USASWIMMING_PARQUET_DIR = USASWIMMING_PROCESSED_DIR / "_parquet_cache"

FRMNATATION_RAW_DIR = RAW_DIR / "frmnatation"
FRMNATATION_PROCESSED_DIR = PROCESSED_DIR / "frmnatation" / "html_results"

SECRETS_DIR = PROJECT_DIR / "services"
BEARER_TOKEN_PATH = SECRETS_DIR / "bearer_token.txt"
USASWIMMING_STATE_PATH = SECRETS_DIR / "state.json"

PREFETCHED_GRAPHS_PATH = EXPORTS_DIR / "prefetched_graphs.json"
PREFETCHED_EVENT_SWIMMERS_PATH = EXPORTS_DIR / "prefetched_event_swimmers.json"


def ensure_project_imports() -> Path:
    """
    Ajoute la racine du projet à ``sys.path`` si nécessaire.

    Returns:
        Path: Chemin absolu vers ``PROJECT_DIR``.
    """
    root = str(PROJECT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_DIR
