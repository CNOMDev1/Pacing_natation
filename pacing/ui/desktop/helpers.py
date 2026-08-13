"""Utilitaires partagés par l'interface desktop Flet (données, filtres, graphiques).

Ce module centralise le chargement du DataFrame Extranat, la résolution des
filtres par type de graphique (stroke / distance / bassin) et la conversion
matplotlib → PNG base64 pour l'affichage dans Flet.

Le flux côté UI :
1. **Chargement** — ``load_data()`` lit les JSON traités via
   ``ExtranatCompetitionsDataLoader`` (cache LRU).
2. **Navigation** — ``_event_combinations()`` et ``_resolve_scope_filters()``
   construisent les combinaisons valides selon ``SCOPE_*`` de ``graph_service``.
3. **Scope** — ``_materialize_df_scope()`` produit le DataFrame filtré pour
   un graphique donné.
4. **Rendu** — ``_figure_to_base64()`` sérialise les figures pour le cache
   ``prefetched_graphs.json``.
"""
import base64
import io
from functools import lru_cache
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd

from pacing.config.paths import EXTRANAT_PROCESSED_DIR
from pacing.data.extranat_loader import ExtranatCompetitionsDataLoader
from pacing.domain.normalize import (
    normalize_text as _normalize_text,
    primary_swimmer_name as _primary_swimmer_name,
    primary_swimmer_name_and_yob as _primary_swimmer_name_and_yob,
    slugify as _slugify,
)
from pacing.application.scope import (
    event_combinations as _event_combinations,
    materialize_df_scope as _materialize_df_scope,
    resolve_scope_filters as _resolve_scope_filters,
)

# --- Chemins et constantes d'affichage ---

EXTRANAT_OUTPUT_BASE_DIR = EXTRANAT_PROCESSED_DIR
CHART_PNG_DPI = 96
CORRIDOR_CHART_PNG_DPI = 72

CORRIDOR_PREFERRED_STROKES: Tuple[str, ...] = ("FR", "BK", "BR", "FL", "IM", "MD")
CORRIDOR_PREFERRED_DISTANCES: Tuple[int, ...] = (100, 200, 50, 400, 1500, 25)


def _pick_preferred_corridor_stroke(stroke_vals: List[str]) -> Optional[str]:
    """Choisit une nage par défaut lisible pour les couloirs de performance.

    Args:
        stroke_vals (List[str]): Codes nage disponibles pour l'épreuve filtrée.

    Returns:
        Optional[str]: Code nage préféré ou premier disponible.
    """
    if not stroke_vals:
        return None
    stroke_set = {str(s) for s in stroke_vals}
    for code in CORRIDOR_PREFERRED_STROKES:
        if code in stroke_set:
            return code
    return str(stroke_vals[0])


def _pick_preferred_corridor_distance(dist_vals: List[int]) -> Optional[int]:
    """Choisit une distance par défaut adaptée aux couloirs (évite le 25 m isolé).

    Args:
        dist_vals (List[int]): Distances disponibles pour la nage et le bassin.

    Returns:
        Optional[int]: Distance préférée ou première disponible.
    """
    if not dist_vals:
        return None
    dist_set = {int(d) for d in dist_vals}
    for distance in CORRIDOR_PREFERRED_DISTANCES:
        if distance in dist_set:
            return distance
    return int(sorted(dist_set)[0])


# --- Extraction nageur / normalisation : voir ``pacing.domain.normalize`` ---


@lru_cache(maxsize=1)
def load_data() -> pd.DataFrame:
    """Charge le DataFrame Extranat traité (mis en cache après le premier appel).

    Returns:
        pd.DataFrame: Performances aplaties depuis ``competitions_per_type``.
    """
    return ExtranatCompetitionsDataLoader(EXTRANAT_OUTPUT_BASE_DIR).load()


def _figure_to_base64(fig: plt.Figure, *, dpi: Optional[int] = None) -> str:
    """Convertit une figure matplotlib en data-URI PNG base64.

    Args:
        fig (plt.Figure): Figure à exporter.
        dpi (Optional[int]): Résolution ; défaut ``CHART_PNG_DPI``.

    Returns:
        str: URI ``data:image/png;base64,…``.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=int(dpi or CHART_PNG_DPI))
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"
