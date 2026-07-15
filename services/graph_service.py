"""Orchestration des graphiques Pacing (catalogue UI + ServiceGraphe).

La logique métier pure vit dans ``services.graph_compute`` ; le rendu matplotlib
non-couloir dans ``services.rendering.chart_plots`` ; les couloirs dans
``services.corridor_data`` et ``services.rendering.corridor_plots``.
Les méthodes ``plot_*`` sont dans ``services.graph_plots.GraphPlotsMixin`` ;
le menu desktop est dans ``services.graph_desktop``.
"""
from __future__ import annotations

from collections import OrderedDict
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import pandas as pd

from services.corridor_data import extract_event_split_speed_rows
from services.graph_compute import (
    _extract_relay_split_speed_rows,
    _prepare_speed_heatmap_long_df,
)
from services.graph_plots import GraphPlotsMixin

# Catalogue UI : ``services.graph_catalog`` (réexporté ci-dessous pour compat).
from services.graph_catalog import (  # noqa: E402
    DESKTOP_GRAPH_MENU,
    DesktopGraphCategory,
    EVENT_COUNTS_SORT_OPTIONS,
    EVENT_COUNTS_SORT_STROKE_DISTANCE,
    EVENT_COUNTS_SORT_TOTAL_DESC,
    GRAPH_CATEGORIES,
    GRAPH_CHRONOS_PAR_NAGE,
    GRAPH_NOMBRE_PERF_EPREUVE,
    GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM,
    GRAPH_RELAY_SPLIT_DISTANCE,
    GRAPH_VITESSE_DISTANCE_NAGE,
    GRAPH_VITESSE_MAX_SPLIT_NAGE,
    GRAPHES_NOTEBOOK,
    GRAPHES_PAR_KEY,
    GraphSpec,
    HEATMAP_CATEGORY_NAME,
    HEATMAP_GRAPH_NAME,
    MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
    MEDIAN_SPEED_BY_GENDER_GRAPH_NAME,
    MEDIAN_VS_BEST_CHART_STYLE_VERSION,
    MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME,
    MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
    MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME,
    RELAY_CATEGORY_NAME,
    RELAY_SPLIT_CHART_STYLE_VERSION,
    SCOPE_EVENT_COUNTS_GRAPHS,
    SCOPE_GENDER_FILTER_GRAPHS,
    SCOPE_NO_FILTER_GRAPHS,
    SCOPE_NO_STROKE_GRAPHS,
    SCOPE_POOL_ONLY_GRAPHS,
    SCOPE_POOL_STROKE_GRAPHS,
    SCOPE_STROKE_ONLY_GRAPHS,
    SPLIT_COMPARISON_CATEGORY_NAME,
)
from services import graph_desktop


class ServiceGraphe(GraphPlotsMixin):
    """Service central pour construire les graphes.

    Attributes:
        _split_speed_event_cache (OrderedDict[tuple, pd.DataFrame]): Cache LRU
            des lignes de split par épreuve.
        _split_speed_event_cache_max (int): Taille maximale du cache LRU.
    """

    def __init__(self) -> None:
        """Initialise les caches internes du service.

        Args:
            None: Cette méthode n'accepte aucun paramètre explicite.

        Returns:
            None: Initialise les attributs d'instance en place.
        """
        self._split_speed_event_cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
        self._split_speed_event_cache_max: int = 16
        self._speed_heatmap_long_cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
        self._speed_heatmap_long_cache_max: int = 4
        self._relay_split_event_cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
        self._relay_split_event_cache_max: int = 16

    def _relay_split_cache_key(self, df: pd.DataFrame, nom_event: str) -> tuple:
        """Construit une clé de cache pour les splits relais d'une épreuve.

        Args:
            df (pd.DataFrame): Jeu de performances source.
            nom_event (str): Libellé d'épreuve.

        Returns:
            tuple: Clé compacte (épreuve, taille, bornes d'index).
        """
        if df.empty:
            return (str(nom_event).strip(), 0, None, None)
        return (
            str(nom_event).strip(),
            int(len(df)),
            df.index.min(),
            df.index.max(),
        )

    def _get_cached_relay_split_rows(
        self, df: pd.DataFrame, nom_event: str
    ) -> pd.DataFrame:
        """Retourne le tableau long relais avec cache LRU par épreuve.

        Args:
            df (pd.DataFrame): Performances source.
            nom_event (str): Libellé exact de l'épreuve.

        Returns:
            pd.DataFrame: Lignes de splits relais exploitables.
        """
        cache_key = self._relay_split_cache_key(df, nom_event)
        cached = self._relay_split_event_cache.get(cache_key)
        if cached is not None:
            self._relay_split_event_cache.move_to_end(cache_key)
            return cached.copy()
        rows = _extract_relay_split_speed_rows(df, nom_event)
        self._relay_split_event_cache[cache_key] = rows.copy()
        self._relay_split_event_cache.move_to_end(cache_key)
        if len(self._relay_split_event_cache) > self._relay_split_event_cache_max:
            self._relay_split_event_cache.popitem(last=False)
        return rows

    def _speed_heatmap_long_cache_key(self, df: pd.DataFrame) -> tuple:
        """Construit une clé compacte pour le cache heatmap vitesse.

        Args:
            df (pd.DataFrame): Jeu de performances source.

        Returns:
            tuple: Empreinte stable du DataFrame.
        """
        if df.empty:
            return (0, None, None)
        return (int(len(df)), df.index.min(), df.index.max())

    def _get_cached_speed_heatmap_long_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Retourne le tableau long heatmap avec cache LRU.

        Args:
            df (pd.DataFrame): Performances source.

        Returns:
            pd.DataFrame: Lignes exploitables pour les heatmaps vitesse.
        """
        cache_key = self._speed_heatmap_long_cache_key(df)
        cached = self._speed_heatmap_long_cache.get(cache_key)
        if cached is not None:
            self._speed_heatmap_long_cache.move_to_end(cache_key)
            return cached.copy()
        rows = _prepare_speed_heatmap_long_df(df)
        self._speed_heatmap_long_cache[cache_key] = rows.copy()
        self._speed_heatmap_long_cache.move_to_end(cache_key)
        if len(self._speed_heatmap_long_cache) > self._speed_heatmap_long_cache_max:
            self._speed_heatmap_long_cache.popitem(last=False)
        return rows

    def _split_speed_cache_key(self, df: pd.DataFrame, nom_event: str) -> tuple:
        """Construit une clé compacte pour le cache split-speed par épreuve.

        Args:
            df (pd.DataFrame): Sous-ensemble courant utilisé pour le tracé.
            nom_event (str): Libellé de l'épreuve.

        Returns:
            tuple: Clé stable basée sur l'épreuve et l'empreinte du DataFrame.
        """
        if df.empty:
            return (str(nom_event).strip(), 0, None, None)
        idx_min = df.index.min()
        idx_max = df.index.max()
        return (str(nom_event).strip(), int(len(df)), idx_min, idx_max)

    def _get_cached_split_speed_rows(self, df: pd.DataFrame, nom_event: str) -> pd.DataFrame:
        """Retourne les lignes de split pour une épreuve avec cache LRU.

        Args:
            df (pd.DataFrame): Données filtrées du périmètre courant.
            nom_event (str): Libellé exact de l'épreuve.

        Returns:
            pd.DataFrame: Lignes de split exploitables (copie défensive).
        """
        cache_key = self._split_speed_cache_key(df, nom_event)
        cached = self._split_speed_event_cache.get(cache_key)
        if cached is not None:
            self._split_speed_event_cache.move_to_end(cache_key)
            return cached.copy()
        rows = extract_event_split_speed_rows(df, nom_event)
        self._split_speed_event_cache[cache_key] = rows.copy()
        self._split_speed_event_cache.move_to_end(cache_key)
        if len(self._split_speed_event_cache) > self._split_speed_event_cache_max:
            self._split_speed_event_cache.popitem(last=False)
        return rows

    def filter_performances_with_valid_splits_for_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[int], pd.DataFrame]:
        """Filtre les perfs solo d'une épreuve avec splits complets.
        
        Args:
            df (pd.DataFrame): Données source.
            nom_event (str): Libellé de l'épreuve.
        
        Returns:
            tuple[Optional[int], pd.DataFrame]: Distance d'épreuve et DataFrame filtré.
        """
        def parse_event_distance(event_name: object) -> Optional[int]:
            """Extrait la distance numérique depuis le libellé d'épreuve.
            
            Args:
                event_name (object): Nom d'épreuve (ex. « 100 NL LCM »).
            
            Returns:
                Optional[int]: Distance en mètres ou None.
            """
            match = re.search(r"(\d+)", str(event_name))
            return int(match.group(1)) if match else None

        def parse_split_distance(value: object) -> Optional[int]:
            """Convertit une distance de split en entier (mètres).
            
            Args:
                value (object): Distance brute (ex. « 50 m »).
            
            Returns:
                Optional[int]: Distance en mètres ou None.
            """
            try:
                return int(float(str(value).lower().replace("m", "").strip()))
            except (TypeError, ValueError):
                return None

        def get_last_split_distance(splits: object) -> Optional[int]:
            """Retourne la distance du dernier split valide d'une liste.
            
            Args:
                splits (object): Liste de dicts de splits.
            
            Returns:
                Optional[int]: Distance du dernier split ou None.
            """
            if not isinstance(splits, list) or len(splits) == 0:
                return None
            for split in reversed(splits):
                if not isinstance(split, dict):
                    continue
                distance = parse_split_distance(split.get("split_distance"))
                if distance is not None:
                    return distance
            return None

        def has_valid_splits(splits: object) -> bool:
            """Indique si au moins un split possède un chrono en secondes.
            
            Args:
                splits (object): Liste de dicts de splits.
            
            Returns:
                bool: True si un split_seconds exploitable est présent.
            """
            if not isinstance(splits, list) or len(splits) == 0:
                return False
            return any(isinstance(split, dict) and split.get("split_seconds") is not None for split in splits)

        event_distance = parse_event_distance(nom_event)
        df_splits_event = df[
            (df["Event"].astype(str).str.strip() == nom_event)
            & (df["splits"].apply(has_valid_splits))
            & (df["splits"].apply(lambda splits: get_last_split_distance(splits) == event_distance))
        ].copy()
        return event_distance, df_splits_event

    @staticmethod
    def _nb_first_event_label(df_nav: pd.DataFrame) -> Optional[str]:
        """Premier libellé d'épreuve « Distance Nage Bassin » depuis df_nav.
        
        Args:
            df_nav (pd.DataFrame): Données de navigation notebook/desktop.
        
        Returns:
            Optional[str]: Libellé d'épreuve ou None.
        """
        need = ("Stroke", "Distance", "PoolLabel")
        if df_nav.empty or not all(c in df_nav.columns for c in need):
            return None
        sub = df_nav.dropna(subset=list(need))
        if sub.empty:
            return None
        r = sub.iloc[0]
        try:
            d = int(float(r["Distance"]))
        except (TypeError, ValueError):
            return None
        st = str(r["Stroke"]).strip()
        pl = str(r["PoolLabel"]).strip()
        if not st or not pl:
            return None
        return f"{d} {st} {pl}"

    @staticmethod
    def _nb_first_pool_label(df_nav: pd.DataFrame) -> Optional[str]:
        """Premier libellé de bassin non nul depuis un DataFrame de navigation.
        
        Args:
            df_nav (pd.DataFrame): Données de navigation.
        
        Returns:
            Optional[str]: LCM/SCM ou None.
        """
        if "PoolLabel" not in df_nav.columns or df_nav.empty:
            return None
        pools = df_nav["PoolLabel"].dropna().astype(str).str.strip()
        if pools.empty:
            return None
        return str(pools.iloc[0])

    @staticmethod
    def _nb_first_swimmer_name(df_nav: pd.DataFrame) -> Optional[str]:
        """Premier nom de nageur trouvé dans la colonne swimmer.
        
        Args:
            df_nav (pd.DataFrame): Données de navigation.
        
        Returns:
            Optional[str]: Nom du nageur ou None.
        """
        if "swimmer" not in df_nav.columns:
            return None
        for swimmers in df_nav["swimmer"].tolist():
            if isinstance(swimmers, list) and swimmers and isinstance(swimmers[0], dict):
                n = swimmers[0].get("Name")
                if n:
                    return str(n).strip()
        return None

    @staticmethod
    def _nb_year_bounds(df_nav: pd.DataFrame) -> Tuple[int, int]:
        """Bornes min/max des années de nage dans un DataFrame de navigation.
        
        Args:
            df_nav (pd.DataFrame): Données avec colonne SwimDate.
        
        Returns:
            Tuple[int, int]: Année début et année fin (défaut 2000–2024).
        """
        if "SwimDate" not in df_nav.columns or df_nav.empty:
            return 2000, 2024
        years = pd.to_datetime(df_nav["SwimDate"], errors="coerce").dt.year.dropna()
        if years.empty:
            return 2000, 2024
        ymin, ymax = int(years.min()), int(years.max())
        if ymin > ymax:
            return 2000, 2024
        return ymin, ymax

    @staticmethod
    def _nb_first_solo_name_yob_for_event(
        df_nav: pd.DataFrame, nom_event: str
    ) -> Tuple[Optional[str], Optional[int]]:
        """Premier nageur solo (nom + année) pour une épreuve dans df_nav.
        
        Args:
            df_nav (pd.DataFrame): Données de navigation.
            nom_event (str): Libellé de l'épreuve.
        
        Returns:
            Tuple[Optional[str], Optional[int]]: Nom et année de naissance.
        """
        if df_nav.empty or "Event" not in df_nav.columns:
            return None, None
        df_e = df_nav[df_nav["Event"].astype(str).str.strip() == str(nom_event).strip()]
        for _, row in df_e.iterrows():
            sw = row.get("swimmer")
            if not isinstance(sw, list) or len(sw) != 1 or not isinstance(sw[0], dict):
                continue
            d0 = sw[0]
            name = d0.get("Name")
            yob = d0.get("Year_of_birth")
            if not name:
                continue
            try:
                if yob is not None and yob == yob:
                    yob_i = int(yob)
                else:
                    yob_i = None
            except (TypeError, ValueError):
                yob_i = None
            if yob_i is None:
                continue
            return str(name).strip(), yob_i
        return None, None

    @staticmethod
    def _prefetch_kwargs_for_notebook_spec(
        spec: GraphSpec, df: pd.DataFrame, df_nav: pd.DataFrame
    ) -> Optional[Dict[str, Any]]:
        """Déduit les kwargs par défaut d'un GraphSpec depuis les données de navigation.
        
        Args:
            spec (GraphSpec): Spécification du graphe notebook.
            df (pd.DataFrame): DataFrame principal.
            df_nav (pd.DataFrame): DataFrame de navigation.
        
        Returns:
            Optional[Dict[str, Any]]: Kwargs pour la méthode plot, ou None.
        """
        nom = ServiceGraphe._nb_first_event_label(df_nav)
        swimmer = ServiceGraphe._nb_first_swimmer_name(df_nav)
        y0, y1 = ServiceGraphe._nb_year_bounds(df_nav)
        pool = ServiceGraphe._nb_first_pool_label(df_nav)

        m = spec.method_name
        if m in (
            "plot_histogramme_simple",
            "plot_histogramme_cumulatif",
            "plot_camembert_sexe_global",
            "plot_boxplot_temps_par_nage",
            "plot_top10_clubs",
            "plot_heatmap_vitesse_moyenne",
            "plot_nombre_performances_par_epreuve_lcm_scm",
            "plot_nombre_performances_par_sexe",
            "plot_vitesse_max_par_split_et_nage",
            "plot_vitesse_moyenne_mediane_par_split_et_nage",
        ):
            return {}
        if m == "plot_nombre_performances_par_epreuve":
            if not pool:
                return None
            return {"course_type": pool}
        if m in (
            "plot_temps_median_top10_clubs_par_event",
            "plot_top10_nageurs_meilleur_temps_par_event",
        ):
            if not nom:
                return None
            return {"nom_event": nom}
        if m == "plot_evolution_temps_nage":
            return {"start_year": 2000, "sample_size": min(5000, max(1, len(df)))}
        if m == "plot_camembert_sexe_par_event":
            if not nom:
                return None
            return {"nom_event": nom}
        if m == "plot_split_speed_analysis_by_gender_with_targets":
            if not nom:
                return None
            targets: List[str] = []
            if swimmer:
                targets = [swimmer]
            return {
                "nom_event": nom,
                "swimmer_targets": targets,
                "target_colors": {},
            }
        if m == "plot_vitesse_par_split_pour_nageur_event":
            if not nom or not swimmer:
                return None
            return {"nom_nageur": swimmer, "nom_event": nom}
        if m == "plot_vitesse_par_split_meilleur_nageur_event_periode":
            if not nom:
                return None
            return {"nom_event": nom, "annee_debut": y0, "annee_fin": y1}
        if m == "plot_vitesse_par_split_top_nageurs_hf_event_periode":
            if not nom:
                return None
            return {"nom_event": nom, "annee_debut": y0, "annee_fin": y1, "top_n": 1}
        if m == "plot_vitesse_par_split_top_nageurs_uniques_event_periode":
            if not nom:
                return None
            return {"nom_event": nom, "annee_debut": y0, "annee_fin": y1, "top_n": 10}
        if m == "plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres":
            if not swimmer:
                return None
            return {"nageur_cible": swimmer}
        if m in (
            "plot_temps_median_vs_meilleur_nageur_par_split_event",
            "plot_temps_median_vs_top10_nageurs_par_split_event",
            "plot_vitesse_mediane_par_split_selon_genre_top_n_event",
            "plot_relais_split_speed_par_distance",
        ):
            if not nom:
                return None
            if m == "plot_vitesse_mediane_par_split_selon_genre_top_n_event":
                return {"nom_event": nom, "top_n": 10}
            return {"nom_event": nom}
        if m == "plot_performance_corridor_plot_time":
            if not nom:
                return None
            name, yob = ServiceGraphe._nb_first_solo_name_yob_for_event(df_nav, nom)
            if not name or yob is None:
                return None
            return {"nom_event": nom, "nom_nageur": name, "year_of_birth": int(yob)}
        if m == "plot_performance_corridor_global_plot_time":
            if not nom:
                return None
            return {"nom_event": nom}
        return {}

    def build_figure_prefetch(
        self, spec: GraphSpec, df: pd.DataFrame, df_nav: pd.DataFrame
    ) -> Any:
        """Kwargs par défaut depuis ``df_nav`` puis ``build_figure`` ; ``None`` si prefetch impossible."""
        kwargs = self._prefetch_kwargs_for_notebook_spec(spec, df, df_nav)
        if kwargs is None:
            return None
        return self.build_figure(spec, df, **kwargs)

    def build_figure(self, spec: GraphSpec, df: pd.DataFrame, **kwargs: Any) -> Any:
        """Dispatch vers la méthode ``plot_*`` indiquée par ``spec.method_name``.
        
        Args:
            spec (GraphSpec): Spécification du graphe à construire.
            df (pd.DataFrame): Données source.
            **kwargs: Arguments transmis à la méthode de tracé.
        
        Returns:
            Any: Résultat de la méthode (souvent plt.Figure ou tuple).
        """
        method: Callable[..., Any] = getattr(self, spec.method_name)
        return method(df, **kwargs)

    def desktop_build_figure(
        self,
        selected_graph: str,
        *,
        df: pd.DataFrame,
        df_scope: pd.DataFrame,
        df_filtered: pd.DataFrame,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        selected_distance: Any,
        selected_chronos_sample_size: int,
        selected_pacing_swimmers: List[str],
        selected_heatmap_swimmer: Optional[str],
        selected_corridor_swimmer_name: Optional[str],
        selected_corridor_swimmer_yob: Optional[int],
        moroccan_corridor_swimmer_name: Optional[str] = None,
        moroccan_corridor_swimmer_yob: Optional[int] = None,
        moroccan_corridor_df: Optional[pd.DataFrame] = None,
        corridor_plot_kwargs: Optional[Dict[str, Any]] = None,
        corridor_gender_filter: Optional[str] = None,
        corridor_reference_df: Optional[pd.DataFrame] = None,
        event_counts_sort: str = EVENT_COUNTS_SORT_STROKE_DISTANCE,
    ) -> Tuple[Optional[plt.Figure], str]:
        """
        Construit la figure pour le menu desktop Flet (noms tels que dans ``GRAPH_CATEGORIES``).

        Args:
            selected_graph (str): Nom du graphe tel qu'affiché dans le menu desktop.
            df (pd.DataFrame): Jeu de données complet (hors scope éventuel).
            df_scope (pd.DataFrame): Données après résolution du scope épreuve.
            df_filtered (pd.DataFrame): Données filtrées pour les graphes globaux.
            stroke (Optional[str]): Code de nage sélectionné.
            distance (Optional[int]): Distance sélectionnée (mètres).
            pool (Optional[str]): Bassin sélectionné (LCM/SCM).
            selected_distance (Any): Distance UI (peut être non numérique).
            selected_chronos_sample_size (int): Taille d'échantillon pour les chronos.
            selected_pacing_swimmers (List[str]): Nageurs cibles pour le pacing.
            selected_heatmap_swimmer (Optional[str]): Nageur cible heatmap.
            selected_corridor_swimmer_name (Optional[str]): Nom du nageur FR couloir.
            selected_corridor_swimmer_yob (Optional[int]): Année de naissance FR.
            moroccan_corridor_swimmer_name (Optional[str]): Nom du nageur MA couloir.
            moroccan_corridor_swimmer_yob (Optional[int]): Année de naissance MA.
            moroccan_corridor_df (Optional[pd.DataFrame]): Données MA pour overlay.
            corridor_plot_kwargs (Optional[Dict[str, Any]]): Kwargs précalculés couloir.
            corridor_gender_filter (Optional[str]): Filtre genre couloir (F/M).
            corridor_reference_df (Optional[pd.DataFrame]): Référence couloir alternative.
            event_counts_sort (str): Mode de tri des graphes de comptage d'épreuves.

        Returns:
            Tuple[Optional[plt.Figure], str]: Figure matplotlib (ou None) et titre affiché.
        """
        return graph_desktop.desktop_build_figure(
            self,
            selected_graph,
            df=df,
            df_scope=df_scope,
            df_filtered=df_filtered,
            stroke=stroke,
            distance=distance,
            pool=pool,
            selected_distance=selected_distance,
            selected_chronos_sample_size=selected_chronos_sample_size,
            selected_pacing_swimmers=selected_pacing_swimmers,
            selected_heatmap_swimmer=selected_heatmap_swimmer,
            selected_corridor_swimmer_name=selected_corridor_swimmer_name,
            selected_corridor_swimmer_yob=selected_corridor_swimmer_yob,
            moroccan_corridor_swimmer_name=moroccan_corridor_swimmer_name,
            moroccan_corridor_swimmer_yob=moroccan_corridor_swimmer_yob,
            moroccan_corridor_df=moroccan_corridor_df,
            corridor_plot_kwargs=corridor_plot_kwargs,
            corridor_gender_filter=corridor_gender_filter,
            corridor_reference_df=corridor_reference_df,
            event_counts_sort=event_counts_sort,
        )

# les graphiques a précharger dans le prefetch

def unwrap_matplotlib_figure(result: Any) -> Optional[plt.Figure]:
    """Extrait une figure matplotlib depuis un résultat de méthode plot hétérogène.

    Args:
        result (Any): Figure directe, tuple (figure, ...) ou None.

    Returns:
        Optional[plt.Figure]: Figure extraite ou None si non trouvée.
    """
    if result is None:
        return None
    if isinstance(result, plt.Figure):
        return result
    if isinstance(result, tuple) and result and isinstance(result[0], plt.Figure):
        return result[0]
    return None
