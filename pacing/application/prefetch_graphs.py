"""Use case : prefetch de figures graphes (sans dépendance Flet).

Expose une API testable pour matérialiser une figure à partir d'un DataFrame
et d'options de scope, via ``ServiceGraphe``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from pacing.application.graph_service import ServiceGraphe


class PrefetchGraphs:
    """
    Prefetch / construction de figures pour cache UI ou batch.

    Attributes:
        service (ServiceGraphe): Orchestrateur graphes.
    """

    def __init__(self, service: Optional[ServiceGraphe] = None) -> None:
        """
        Initialise le use case.

        Args:
            service (Optional[ServiceGraphe]): Service graphes ; créé si absent.
        """
        self.service = service or ServiceGraphe()

    def build_figure(self, df: pd.DataFrame, options: Dict[str, Any]):
        """
        Construit une figure selon les options UI / catalogue.

        Args:
            df (pd.DataFrame): Données scopées.
            options (Dict[str, Any]): Options (nom du graphe, filtres, etc.).

        Returns:
            matplotlib.figure.Figure: Figure générée.
        """
        return self.service.desktop_build_figure(df, options)

    def build_figure_by_name(
        self,
        df: pd.DataFrame,
        graph_name: str,
        **kwargs: Any,
    ):
        """
        Construit une figure par nom de catalogue.

        Args:
            df (pd.DataFrame): Données source.
            graph_name (str): Libellé du graphe dans le catalogue.
            **kwargs (Any): Options complémentaires.

        Returns:
            matplotlib.figure.Figure: Figure générée.
        """
        options = {"graph_name": graph_name, **kwargs}
        return self.build_figure(df, options)
