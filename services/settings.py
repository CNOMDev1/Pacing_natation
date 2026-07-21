"""Settings runtime Pacing (variables d'environnement ``PACING_*``).

Regroupe les flags de prefetch desktop et les limites associées.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = True) -> bool:
    """
    Lit une variable d'environnement comme booléen.

    Args:
        name (str): Nom de la variable.
        default (bool): Valeur si absente.

    Returns:
        bool: Valeur booléenne.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """
    Lit une variable d'environnement comme entier.

    Args:
        name (str): Nom de la variable.
        default (int): Valeur si absente ou invalide.

    Returns:
        int: Entier parsé ou ``default``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PrefetchSettings:
    """
    Flags et limites du prefetch au démarrage de l'UI desktop.

    Attributes:
        enable_persistent_graph_cache (bool): Persiste les PNG préchargés.
        enable_notebook_prefetch (bool): Prefetch des graphes notebooks.
        enable_event_swimmers_cache (bool): Cache nageurs par épreuve.
        enable_scope_performances (bool): Prefetch scopes performances.
        scope_performances_limit (int): Limite de scopes performances.
        enable_corridor_chart (bool): Prefetch couloirs.
        corridor_chart_limit (int): Limite de couloirs.
        enable_heatmap_chart (bool): Prefetch heatmaps.
        heatmap_swimmer_limit (int): Limite nageurs heatmap prefetch.
        heatmap_dropdown_swimmer_limit (int): Limite dropdown heatmap.
        enable_median_vs_best (bool): Prefetch médiane vs meilleur.
        median_vs_best_limit (int): Limite médiane vs meilleur.
        enable_relay_chart (bool): Prefetch relais.
        relay_chart_limit (int): Limite graphes relais.
    """

    enable_persistent_graph_cache: bool = True
    enable_notebook_prefetch: bool = True
    enable_event_swimmers_cache: bool = True
    enable_scope_performances: bool = True
    scope_performances_limit: int = 48
    enable_corridor_chart: bool = True
    corridor_chart_limit: int = 96
    enable_heatmap_chart: bool = True
    heatmap_swimmer_limit: int = 32
    heatmap_dropdown_swimmer_limit: int = 400
    enable_median_vs_best: bool = True
    median_vs_best_limit: int = 96
    enable_relay_chart: bool = True
    relay_chart_limit: int = 48


def load_prefetch_settings() -> PrefetchSettings:
    """
    Charge les settings de prefetch depuis l'environnement.

    Returns:
        PrefetchSettings: Configuration figée pour le démarrage desktop.
    """
    return PrefetchSettings(
        enable_persistent_graph_cache=_env_bool(
            "PACING_ENABLE_PERSISTENT_GRAPH_CACHE", True
        ),
        enable_notebook_prefetch=_env_bool(
            "PACING_ENABLE_NOTEBOOK_PREFETCH", True
        ),
        enable_event_swimmers_cache=_env_bool(
            "PACING_ENABLE_EVENT_SWIMMERS_CACHE", True
        ),
        enable_scope_performances=_env_bool(
            "PACING_ENABLE_SCOPE_PERFORMANCES_PREFETCH", True
        ),
        scope_performances_limit=_env_int(
            "PACING_SCOPE_PERFORMANCES_PREFETCH_LIMIT", 48
        ),
        enable_corridor_chart=_env_bool(
            "PACING_ENABLE_CORRIDOR_CHART_PREFETCH", True
        ),
        corridor_chart_limit=_env_int("PACING_CORRIDOR_CHART_PREFETCH_LIMIT", 96),
        enable_heatmap_chart=_env_bool(
            "PACING_ENABLE_HEATMAP_CHART_PREFETCH", True
        ),
        heatmap_swimmer_limit=_env_int(
            "PACING_HEATMAP_PREFETCH_SWIMMER_LIMIT", 32
        ),
        heatmap_dropdown_swimmer_limit=_env_int(
            "PACING_HEATMAP_DROPDOWN_SWIMMER_LIMIT", 400
        ),
        enable_median_vs_best=_env_bool(
            "PACING_ENABLE_MEDIAN_VS_BEST_PREFETCH", True
        ),
        median_vs_best_limit=_env_int(
            "PACING_MEDIAN_VS_BEST_PREFETCH_LIMIT", 96
        ),
        enable_relay_chart=_env_bool("PACING_ENABLE_RELAY_CHART_PREFETCH", True),
        relay_chart_limit=_env_int("PACING_RELAY_CHART_PREFETCH_LIMIT", 48),
    )


PREFETCH = load_prefetch_settings()
