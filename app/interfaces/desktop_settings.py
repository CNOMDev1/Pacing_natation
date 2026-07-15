"""Constantes et settings de l'UI desktop (prefetch, chemins d'export).

Extrait de ``desktop_flet`` pour séparer la configuration de l'orchestration UI.
"""
from __future__ import annotations

from typing import Tuple

from project_path import PROJECT_DIR, ensure_project_imports

ensure_project_imports()

from services.paths import (
    PREFETCHED_EVENT_SWIMMERS_PATH,
    PREFETCHED_GRAPHS_PATH,
)
from services.settings import PREFETCH

GRAPH_EXPORT_PATH = PREFETCHED_GRAPHS_PATH
EVENT_SWIMMERS_EXPORT_PATH = PREFETCHED_EVENT_SWIMMERS_PATH
EXPORT_IMAGE_BASE64_TO_JSON = True

ENABLE_PERSISTENT_GRAPH_CACHE = PREFETCH.enable_persistent_graph_cache
ENABLE_NOTEBOOK_PREFETCH_ON_START = PREFETCH.enable_notebook_prefetch
ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START = PREFETCH.enable_event_swimmers_cache
ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START = PREFETCH.enable_scope_performances
SCOPE_PERFORMANCES_PREFETCH_LIMIT = PREFETCH.scope_performances_limit

ENABLE_CORRIDOR_CHART_PREFETCH_ON_START = PREFETCH.enable_corridor_chart
CORRIDOR_CHART_PREFETCH_LIMIT = PREFETCH.corridor_chart_limit
ENABLE_HEATMAP_CHART_PREFETCH_ON_START = PREFETCH.enable_heatmap_chart
HEATMAP_CHART_PREFETCH_SWIMMER_LIMIT = PREFETCH.heatmap_swimmer_limit
ENABLE_MEDIAN_VS_BEST_CHART_PREFETCH_ON_START = PREFETCH.enable_median_vs_best
MEDIAN_VS_BEST_CHART_PREFETCH_LIMIT = PREFETCH.median_vs_best_limit
ENABLE_RELAY_CHART_PREFETCH_ON_START = PREFETCH.enable_relay_chart
RELAY_CHART_PREFETCH_LIMIT = PREFETCH.relay_chart_limit
HEATMAP_DROPDOWN_SWIMMER_LIMIT = PREFETCH.heatmap_dropdown_swimmer_limit

COUNTRY_FRANCE = "France"
COUNTRY_MOROCCO = "Maroc"
COUNTRY_USA = "États-Unis"

CORRIDOR_GRAPH_NAME = "Couloir de performance (âge) - nageur cible"
CORRIDOR_GLOBAL_GRAPH_NAME = "Couloir de performance global (âge)"
CORRIDOR_GLOBAL_DECILES_GRAPH_NAME = "Couloir de performance global (déciles 10-90)"
CORRIDOR_CATEGORY = "Couloirs de performance"
CORRIDOR_SWIMMER_UI_GRAPHS: Tuple[str, ...] = (
    CORRIDOR_GRAPH_NAME,
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
)
CORRIDOR_FR_TARGET_SWIMMER_GRAPHS: Tuple[str, ...] = (CORRIDOR_GRAPH_NAME,)
SCOPE_PERFORMANCES_PREFETCH_GRAPHS: Tuple[str, ...] = (
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_GRAPH_NAME,
)
CORRIDOR_CHART_PREFETCH_GRAPH_NAMES: Tuple[str, ...] = (
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_GRAPH_NAME,
)

USA_CORRIDOR_GRAPH_NAME = "Couloir de performance (AgeGroup) - USA Swimming"
USA_CORRIDOR_COLS = ("Event", "SwimTimeSeconds", "AgeGroup", "Gender", "Name")
USA_CORRIDOR_MIN_POINTS = 100

# Conservé pour compat éventuelle (chemins legacy)
_PROJECT_DIR_LEGACY = PROJECT_DIR
