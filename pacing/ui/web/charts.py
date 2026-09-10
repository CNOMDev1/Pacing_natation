"""Tracé client des payloads couloir / comparaison.

Partagé par NiceGUI (``pacing.ui.web.app``) et DearPyGUI
(``pacing.ui.dearpygui.app``). Ces deux interfaces ne définissent plus aucune
couleur ni aucune géométrie : elles construisent la recette du graphique via
``pacing.grammar.corridor`` et la font rendre par le moteur Matplotlib commun.

Chaque interface reste libre de la seule chose qui la concerne : la façon de
porter la ``Figure`` à l'écran — data-URI base64 pour le navigateur, texture
GPU pour DearPyGUI.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from matplotlib.figure import Figure

from pacing.grammar.corridor import (
    compare_spec_from_payload,
    corridor_spec_from_payload,
)
from pacing.grammar.render_matplotlib import render_figure


def build_corridor_figure(
    payload: Dict[str, Any],
    *,
    title: Optional[str] = None,
) -> Figure:
    """
    Construit une figure couloir à partir d'un payload ``/couloir``.

    Args:
        payload (Dict[str, Any]): Réponse API couloir.
        title (Optional[str]): Titre override.

    Returns:
        Figure: Figure Matplotlib prête à afficher.
    """
    return render_figure(corridor_spec_from_payload(payload, title=title))


def build_compare_figure(
    payload: Dict[str, Any],
    *,
    title: Optional[str] = None,
) -> Figure:
    """
    Construit une figure de comparaison à partir de ``/comparaison``.

    Args:
        payload (Dict[str, Any]): Réponse API comparaison.
        title (Optional[str]): Titre override.

    Returns:
        Figure: Figure Matplotlib.
    """
    return render_figure(compare_spec_from_payload(payload, title=title))
