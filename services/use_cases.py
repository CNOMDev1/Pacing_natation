"""Use cases applicatifs testables (sans dépendance Flet).

Encapsulent ``ServiceGraphe`` pour la construction de figures couloirs / graphes.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from services.corridor_data import (
    build_corridor_chart_plot_kwargs,
    prepare_corridor_long_df,
)
from services.graph_service import ServiceGraphe


class BuildCorridorChart:
    """
    Construit une figure matplotlib de couloir pour une épreuve donnée.

    Attributes:
        service (ServiceGraphe): Orchestrateur graphes (calcul + rendu).
    """

    def __init__(self, service: Optional[ServiceGraphe] = None) -> None:
        """
        Initialise le use case.

        Args:
            service (Optional[ServiceGraphe]): Service graphes ; créé si absent.
        """
        self.service = service or ServiceGraphe()

    def prepare_long_df(
        self,
        df: pd.DataFrame,
        event_name: str,
        *,
        solo_only: bool = True,
        require_name: bool = False,
    ) -> pd.DataFrame:
        """
        Prépare le DataFrame long pour un couloir.

        Args:
            df (pd.DataFrame): Performances source.
            event_name (str): Libellé d'épreuve.
            solo_only (bool): Ne garder que les nages solo.
            require_name (bool): Exiger nom + année de naissance.

        Returns:
            pd.DataFrame: Données longues âge × temps.
        """
        return prepare_corridor_long_df(
            df,
            event_name,
            solo_only=solo_only,
            require_name=require_name,
        )

    def build_plot_kwargs(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Prépare les kwargs de tracé couloir.

        Args:
            **kwargs (Any): Paramètres transmis à ``build_corridor_chart_plot_kwargs``.

        Returns:
            Dict[str, Any]: Kwargs prêts pour le rendu.
        """
        return build_corridor_chart_plot_kwargs(**kwargs)

    def build_figure(self, df: pd.DataFrame, options: Dict[str, Any]):
        """
        Produit la figure couloir via ``ServiceGraphe``.

        Args:
            df (pd.DataFrame): DataFrame filtré / long.
            options (Dict[str, Any]): Options de rendu.

        Returns:
            matplotlib.figure.Figure: Figure prête à l'export.
        """
        return self.service.desktop_build_figure(df, options)


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
