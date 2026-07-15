"""Orchestration des graphiques Pacing (catalogue UI + ServiceGraphe).

La logique métier pure vit dans ``services.graph_compute`` ; le rendu matplotlib
non-couloir dans ``services.rendering.chart_plots`` ; les couloirs dans
``services.corridor_data`` et ``services.rendering.corridor_plots``.
Ce module conserve le menu desktop, le dispatch ``build_figure`` et les
méthodes ``plot_*`` qui enchaînent calcul → rendu.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import difflib
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple
import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import Normalize, TwoSlopeNorm, to_hex
from matplotlib.ticker import FuncFormatter, MaxNLocator, MultipleLocator

from services.stroke_labels import (
    format_event_label,
    localize_event_string,
    relabel_stroke_column,
    stroke_code_to_label,
    stroke_label_to_code,
)
from services.corridor_data import (
    CorridorSwimmerSpec,
    CORRIDOR_FR_SWIMMER_COLOR,
    CORRIDOR_MA_SWIMMER_COLOR,
    CORRIDOR_ANNOTATION_COLOR,
    CORRIDOR_CHART_STYLE_VERSION,
    CORRIDOR_GRID_ALPHA,
    CORRIDOR_REFERENCE_LINE_COLOR,
    STANDARD_CORRIDOR_PERCENTILES,
    DECILE_CORRIDOR_PERCENTILES,
    add_within_swim_speed_pct,
    build_corridor_chart_plot_kwargs,
    compute_corridor_percentiles_df,
    compute_group_percentiles_df,
    compute_corridor_deciles_df,
    corridor_age_limits,
    corridor_gender_display_label,
    corridor_norm_name,
    exclude_corridor_swimmer_specs_from_df,
    extract_event_split_speed_rows,
    filter_corridor_long_df_gender,
    merge_corridor_swimmer_specs_for_plot,
    parse_event_distance_m,
    prepare_corridor_long_df,
    prepare_corridor_long_df_combined,
    resolve_corridor_plot_gender,
    resolve_corridor_swimmer,
    resolve_corridor_swimmer_flexible,
)
from services.rendering.corridor_plots import (
    apply_corridor_chart_theme,
    draw_decile_corridor_bands,
    draw_percentile_corridor_bands,
    plot_corridor_swimmer_specs,
    plot_normalized_pacing_profiles_on_ax,
)

from services.graph_compute import (
    CORRIDOR_OVERLAY_SWIMMER_COLOR,
    CORRIDOR_OVERLAY_SWIMMER_LABEL,
    _STROKE_SORT_ORDER,
    _HEATMAP_STANDARD_DISTANCES,
    _CHRONOS_YEARLY_MIN_PERFORMANCES,
    _CHRONOS_ROLLING_WINDOW_YEARS,
    _SPEED_DISTANCE_MIN_AGE_YEARS,
    _SPEED_DISTANCE_MIN_GROUP_N,
    _SPEED_DISTANCE_MAX_MPS,
    _SPEED_DISTANCE_MIN_MPS,
    _SPLIT_SPEED_MIN_MPS,
    _SPLIT_SPEED_MAX_MPS,
    _GENDER_LABEL_FEMALE,
    _GENDER_LABEL_MALE,
    _adaptive_histogram_bin_count,
    _canonical_heatmap_stroke_columns,
    _compute_yearly_stroke_median_times,
    _corridor_swimmer_specs_from_kwargs,
    _drop_zero_count_events,
    _event_display_sort_key,
    _extract_all_split_speed_rows,
    _extract_relay_split_speed_rows,
    _filter_stroke_swim_time_outliers,
    _filter_yearly_stats_by_min_count,
    _gender_label_for_code,
    _is_relay_swimmers,
    _ordered_stroke_labels,
    _parse_split_distance_m,
    _parse_split_speed_mps,
    _prepare_max_split_speed_by_stroke,
    _prepare_speed_distance_stroke_stats,
    _prepare_speed_heatmap_long_df,
    _reindex_heatmap_grid,
    _resolve_fastest_solo_swim_for_event,
    _resolve_speed_distance_min_group_n,
    _smooth_centered_rolling,
    _solo_swim_key_from_row,
    _sort_event_counts_df,
    _speed_heatmap_pivot_tables,
    _split_segment_tick_labels,
    _stroke_label_sort_key,
    _swimmer_field_from_cell,
    _top_n_swim_keys_for_event,
    _top_n_swim_keys_for_event_by_gender,
)
from services.rendering.chart_plots import (
    NON_CORRIDOR_CMAP_DIVERGING,
    NON_CORRIDOR_CMAP_SEQUENTIAL,
    NON_CORRIDOR_COLOR_ACCENT,
    NON_CORRIDOR_COLOR_FEMALE,
    NON_CORRIDOR_COLOR_MALE,
    NON_CORRIDOR_COLOR_NEUTRAL,
    NON_CORRIDOR_COLOR_PRIMARY,
    NON_CORRIDOR_COLOR_SECONDARY,
    NON_CORRIDOR_COLOR_TARGET,
    MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
    MEDIAN_VS_BEST_CHART_STYLE_VERSION,
    MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
    RELAY_SPLIT_CHART_STYLE_VERSION,
    _GENDER_PIE_COLORS,
    _HISTOGRAM_STATS_BBOX,
    _MEDIAN_LABEL_BBOX,
    _STROKE_CATEGORY_COLORS,
    _STROKE_MARKERS,
    _all_split_distance_ticks,
    _apply_corridor_consistent_styling,
    _apply_heatmap_text_contrast,
    _apply_histogram_bin_xaxis,
    _apply_histogram_yaxis_label,
    _apply_standard_chart_theme,
    _boxplot_category_center_x,
    _draw_speed_heatmap_panel,
    _format_count_display,
    _format_performance_count_tick,
    _format_speed_tick,
    _format_swim_time_annotation,
    _format_swim_time_display,
    _format_swim_time_tick,
    _heatmap_annotations,
    _histogram_time_tick_label,
    _histogram_xaxis_label_band,
    _place_histogram_stats_footnote,
    _plot_gender_grouped_counts_by_event,
    _plot_gender_performance_counts,
    _plot_gender_pie_chart,
    _plot_max_split_speed_by_stroke,
    _plot_mean_speed_by_distance_and_stroke,
    _plot_ranked_horizontal_counts,
    _plot_ranked_horizontal_median_times,
    _plot_yearly_stroke_time_evolution,
    _ranked_sequential_bar_colors,
    _stroke_palette_for_labels,
    plot_corridor_swimmer_age_curve,
)



# Palette non-couloir (basée sur Munzner/Cleveland/Tufte)
# - Catégoriel: teintes distinctes et daltonisme-friendly (Okabe-Ito)
# - Ordonné: luminance (séquentiel) ou double extrémité + neutre (divergent)


HEATMAP_GRAPH_NAME = "Heatmap vitesse moyenne (distance x nage)"
HEATMAP_CATEGORY_NAME = "Synthèse des vitesses par distance et nage"
MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME = "Temps médian vs meilleur nageur"
MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME = "Temps médian vs Top 10 nageurs"
SPLIT_COMPARISON_CATEGORY_NAME = (
    "Comparaisons de pacing par splits (à partir de la médiane)"
)
MEDIAN_SPEED_BY_GENDER_GRAPH_NAME = "Vitesse médiane par split selon le genre"


@dataclass(frozen=True)
class GraphSpec:
    """dataclass pour la description des graphes """
    key: str
    name: str
    category: str
    method_name: str


@dataclass(frozen=True)
class DesktopGraphCategory:
    """Une rubrique du menu graphes (UI desktop Flet)."""
    title: str
    graph_names: Tuple[str, ...]


GRAPH_CHRONOS_PAR_NAGE = "Évolution des chronos par type de nage (échantillon 5000)"
GRAPH_VITESSE_DISTANCE_NAGE = "Vitesse par distance et type de nage"
GRAPH_VITESSE_MAX_SPLIT_NAGE = "Vitesse maximale par split et type de nage"
GRAPH_RELAY_SPLIT_DISTANCE = "Vitesse de split selon la distance (relais)"
RELAY_CATEGORY_NAME = "Pacing en relais"
DESKTOP_GRAPH_MENU: Tuple[DesktopGraphCategory, ...] = (
    DesktopGraphCategory(
        "Distributions de temps",
        (
            "Histogramme simple",
            "Histogramme cumulatif",
        ),
    ),
    DesktopGraphCategory(
        "Effectifs et répartition par sexe",
        (
            "Nombre de performances par épreuve",
            "Nombre de performances par épreuve (LCM + SCM)",
            "Comptage par sexe (global)",
            "Camembert par sexe (global)",
            "Camembert par sexe (épreuve)",
        ),
    ),
    DesktopGraphCategory(
        "Comparaison des temps par nage",
        ("Distribution des temps par type de nage (boxplot)",),
    ),
    DesktopGraphCategory(
        "Clubs",
        (
            "Top 10 clubs par participation (épreuve)",
            "Temps médian des 10 meilleurs clubs",
        ),
    ),
    DesktopGraphCategory(
        "Chronos dans le temps",
        (
            GRAPH_CHRONOS_PAR_NAGE,
        ),
    ),
    DesktopGraphCategory(
        "Vitesse globale",
        (
            GRAPH_VITESSE_DISTANCE_NAGE,
            GRAPH_VITESSE_MAX_SPLIT_NAGE,
        ),
    ),
    DesktopGraphCategory(
        "Pacing comparatif",
        ("Vitesse de split - F vs M + nageurs cibles",),
    ),
    DesktopGraphCategory(
        "Synthèse des vitesses par distance et nage",
        ("Heatmap vitesse moyenne (distance x nage)",),
    ),
    DesktopGraphCategory(
        "Comparaisons de pacing par splits (à partir de la médiane)",
        (
            "Temps médian vs meilleur nageur",
            "Temps médian vs Top 10 nageurs",
            "Vitesse médiane par split selon le genre",
        ),
    ),
    DesktopGraphCategory(
        "Pacing en relais",
        (GRAPH_RELAY_SPLIT_DISTANCE,),
    ),
    DesktopGraphCategory(
        "Couloirs de performance",
        (
            "Couloir de performance global (âge)",
            "Couloir de performance (âge) - nageur cible",
            "Couloir de performance global (déciles 10-90)",
            "Couloir de performance (AgeGroup) - USA Swimming",
        ),
    ),
)

GRAPH_CATEGORIES: Dict[str, List[str]] = {
    block.title: list[str](block.graph_names) for block in DESKTOP_GRAPH_MENU
}

EVENT_COUNTS_SORT_STROKE_DISTANCE = "stroke_distance"
EVENT_COUNTS_SORT_TOTAL_DESC = "total_desc"
EVENT_COUNTS_SORT_OPTIONS: Dict[str, str] = {
    EVENT_COUNTS_SORT_STROKE_DISTANCE: "Par distance (croissant)",
    EVENT_COUNTS_SORT_TOTAL_DESC: "Par effectif décroissant",
}
GRAPH_NOMBRE_PERF_EPREUVE = "Nombre de performances par épreuve"
GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM = "Nombre de performances par épreuve (LCM + SCM)"
SCOPE_EVENT_COUNTS_GRAPHS = frozenset(
    {
        GRAPH_NOMBRE_PERF_EPREUVE,
        GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM,
    }
)

SCOPE_NO_FILTER_GRAPHS = frozenset(
    {
        "Comptage par sexe (global)",
        "Camembert par sexe (global)",
        GRAPH_CHRONOS_PAR_NAGE,
        GRAPH_VITESSE_DISTANCE_NAGE,
        GRAPH_VITESSE_MAX_SPLIT_NAGE,
        "Heatmap vitesse moyenne (distance x nage)",
    }
)
SCOPE_GENDER_FILTER_GRAPHS: frozenset[str] = frozenset()
SCOPE_POOL_ONLY_GRAPHS: frozenset[str] = frozenset()
SCOPE_POOL_STROKE_GRAPHS = frozenset({GRAPH_NOMBRE_PERF_EPREUVE})
SCOPE_STROKE_ONLY_GRAPHS = frozenset({GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM})
SCOPE_NO_STROKE_GRAPHS = frozenset({"Distribution des temps par type de nage (boxplot)"})


class ServiceGraphe:
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

    def plot_histogramme_simple(self, df: pd.DataFrame, swim_col: str = "SwimTimeSeconds") -> plt.Figure:
        """Trace un histogramme robuste des temps de nage.

        Le tracé applique un nombre de classes (bins) adapté à la taille de
        l'échantillon afin d'améliorer la lisibilité (petits n) et la stabilité
        visuelle (grands n). Le graphique affiche aussi des repères descriptifs
        (moyenne, médiane, intervalle interquartile) et une tendance KDE.

        Args:
            df (pd.DataFrame): Données de performances.
            swim_col (str): Nom de la colonne contenant les temps en secondes.

        Returns:
            plt.Figure: Figure matplotlib de l'histogramme.

        Raises:
            ValueError: Si ``swim_col`` est introuvable dans ``df``.
        """
        if swim_col not in df.columns:
            raise ValueError(f"Colonne introuvable pour l'histogramme: {swim_col}")

        values = pd.to_numeric(df[swim_col], errors="coerce")
        values = values[np.isfinite(values)].astype(float)
        values = values[values > 0]

        fig, ax = plt.subplots(figsize=(12, 8))
        ax.set_facecolor("#f8fafc")

        if values.empty:
            ax.text(
                0.5,
                0.5,
                "Aucune performance disponible pour cet histogramme.",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=12,
                color="#334155",
            )
            ax.set_axis_off()
            fig.tight_layout()
            return fig

        q1, median, q3 = np.percentile(values, [25, 50, 75])
        mean_val = float(np.mean(values))
        std_val = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        data_min = float(np.min(values))
        data_max = float(np.max(values))
        iqr = float(q3 - q1)
        n_perf = int(len(values))
        nbins = _adaptive_histogram_bin_count(n_perf, data_min, data_max, iqr)

        hist_counts, bin_edges, _ = ax.hist(
            values,
            bins=nbins,
            color=NON_CORRIDOR_COLOR_PRIMARY,
            edgecolor="#ffffff",
            linewidth=0.9,
            alpha=0.78,
            rwidth=0.96,
        )
        bin_width = _apply_histogram_bin_xaxis(ax, bin_edges, nbins)

        ax.axvspan(
            q1,
            q3,
            color=NON_CORRIDOR_COLOR_SECONDARY,
            alpha=0.12,
            label="Intervalle interquartile (Q1-Q3)",
        )
        ax.axvline(
            mean_val,
            color=NON_CORRIDOR_COLOR_TARGET,
            linestyle="dashed",
            linewidth=2.4,
            label="Moyenne",
            zorder=7,
        )
        ax.axvline(
            float(median),
            color=NON_CORRIDOR_COLOR_SECONDARY,
            linestyle=(0, (3, 2)),
            linewidth=2.6,
            label="Médiane",
            zorder=8,
        )
        if len(values) >= 5 and np.unique(values).size > 1:
            ax_kde = ax.twinx()
            sns.kdeplot(
                values,
                ax=ax_kde,
                color=NON_CORRIDOR_COLOR_NEUTRAL,
                linewidth=2.0,
                alpha=0.9,
                clip=(data_min, data_max),
                bw_adjust=1.1,
                label="Tendance (KDE)",
            )
            ax_kde.set_yticks([])
            ax_kde.set_ylabel("")
            ax_kde.grid(False)

        stats_text = (
            f"n={n_perf}  |  classes={nbins}  Δ≈{bin_width:.2f}s  |  "
            f"min={data_min:.2f}s  max={data_max:.2f}s  "
            f"moy={mean_val:.2f}s  méd={median:.2f}s  σ={std_val:.2f}s"
        )

        hist_handles, hist_labels = ax.get_legend_handles_labels()
        if len(values) >= 5 and np.unique(values).size > 1:
            kde_handles, kde_labels = ax_kde.get_legend_handles_labels()
            ax.legend(hist_handles + kde_handles, hist_labels + kde_labels, loc="upper right")
        else:
            ax.legend(loc="upper right")
        ax.set_title("Histogramme simple des temps de nage")
        max_count = int(np.max(hist_counts)) if hist_counts.size > 0 else 0
        if max_count <= 12:
            ax.yaxis.set_major_locator(MultipleLocator(1))
        else:
            ax.yaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=5))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda tick, _: f"{int(tick)}" if tick >= 0 else ""))
        ax.grid(axis="y", alpha=0.22, linestyle="--", linewidth=0.7)
        _place_histogram_stats_footnote(fig, stats_text, ax=ax, nbins=nbins)
        return fig

    def plot_camembert_sexe_global(
        self,
        df: pd.DataFrame,
        gender_col: str = "Gender",
        *,
        title: str = "Répartition globale par sexe",
    ) -> plt.Figure:
        """Trace un diagramme en anneau de la répartition globale F/M.

        Args:
            df (pd.DataFrame): Performances avec colonne Gender ou swimmer imbriqué.
            gender_col (str): Nom de la colonne genre (défaut ``Gender``).
            title (str): Titre affiché sur la figure.

        Returns:
            plt.Figure: Figure matplotlib du camembert.
        """
        local_df = df.copy()
        if gender_col not in local_df.columns:
            local_df[gender_col] = local_df.get("swimmer", pd.Series(dtype=object)).apply(
                lambda x: x[0].get("Gender")
                if isinstance(x, list) and len(x) > 0 and isinstance(x[0], dict)
                else None
            )

        counts = (
            local_df.get(gender_col, pd.Series(dtype=str))
            .dropna()
            .value_counts()
            .to_dict()
        )
        return _plot_gender_pie_chart(counts, title=title)

    def plot_histogramme_cumulatif(self, df: pd.DataFrame, swim_col: str = "SwimTimeSeconds") -> plt.Figure:
        """Trace un histogramme cumulatif lisible des temps de nage.

        Le tracé adapte les bornes de l'axe des temps aux données observées
        (évite un axe 0–500 s trompeur), utilise un nombre de classes cohérent
        avec la taille d'échantillon et affiche des comptages cumulés entiers.
        Des repères (moyenne, médiane, intervalle interquartile) facilitent la
        lecture de la distribution cumulative, conformément aux principes de
        perception graphique (position sur axe commun, intégrité des échelles).

        Args:
            df (pd.DataFrame): Données de performances.
            swim_col (str): Colonne des temps en secondes.

        Returns:
            plt.Figure: Figure matplotlib de l'histogramme cumulatif.

        Raises:
            ValueError: Si ``swim_col`` est introuvable dans ``df``.
        """
        if swim_col not in df.columns:
            raise ValueError(f"Colonne introuvable pour l'histogramme cumulatif: {swim_col}")

        values = pd.to_numeric(df[swim_col], errors="coerce")
        values = values[np.isfinite(values)].astype(float)
        values = values[values > 0]

        fig, ax = plt.subplots(figsize=(12, 8))
        ax.set_facecolor("#f8fafc")

        if values.empty:
            ax.text(
                0.5,
                0.5,
                "Aucune performance disponible pour cet histogramme cumulatif.",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=12,
                color="#334155",
            )
            ax.set_axis_off()
            fig.tight_layout()
            return fig

        q1, median, q3 = np.percentile(values, [25, 50, 75])
        mean_val = float(np.mean(values))
        std_val = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        data_min = float(np.min(values))
        data_max = float(np.max(values))
        iqr = float(q3 - q1)
        n_perf = int(len(values))
        count_at_or_below_median = int(np.sum(values <= median))
        nbins = _adaptive_histogram_bin_count(n_perf, data_min, data_max, iqr)

        span = max(data_max - data_min, 1e-6)
        pad = max(0.25, span * 0.06)
        x_lo = max(0.0, data_min - pad)
        x_hi = data_max + pad
        bin_edges = np.linspace(x_lo, x_hi, nbins + 1)

        ax.hist(
            values,
            bins=bin_edges,
            cumulative=True,
            histtype="stepfilled",
            color=NON_CORRIDOR_COLOR_PRIMARY,
            alpha=0.28,
            edgecolor="none",
        )
        ax.hist(
            values,
            bins=bin_edges,
            cumulative=True,
            histtype="step",
            color=NON_CORRIDOR_COLOR_PRIMARY,
            linewidth=2.4,
        )
        bin_width = _apply_histogram_bin_xaxis(ax, bin_edges, nbins)

        ax.axvspan(
            q1,
            q3,
            color=NON_CORRIDOR_COLOR_SECONDARY,
            alpha=0.12,
            label="Intervalle interquartile (Q1-Q3)",
            zorder=1,
        )
        ax.axvline(
            mean_val,
            color=NON_CORRIDOR_COLOR_TARGET,
            linestyle="dashed",
            linewidth=2.4,
            label="Moyenne",
            zorder=7,
        )
        ax.axvline(
            float(median),
            color=NON_CORRIDOR_COLOR_SECONDARY,
            linestyle=(0, (3, 2)),
            linewidth=2.6,
            label="Médiane",
            zorder=8,
        )
        ax.axhline(
            count_at_or_below_median,
            color=NON_CORRIDOR_COLOR_NEUTRAL,
            linestyle=":",
            linewidth=1.4,
            alpha=0.75,
            label=f"Effectif ≤ médiane ({count_at_or_below_median})",
            zorder=4,
        )

        stats_text = (
            f"n={n_perf}  |  classes={nbins}  Δ≈{bin_width:.2f}s  |  "
            f"min={data_min:.2f}s  max={data_max:.2f}s  "
            f"moy={mean_val:.2f}s  méd={median:.2f}s  σ={std_val:.2f}s  |  "
            f"≤ médiane : {count_at_or_below_median}/{n_perf} "
            f"({100.0 * count_at_or_below_median / n_perf:.0f} %)"
        )

        ax.set_ylim(0, n_perf)
        if n_perf <= 12:
            ax.yaxis.set_major_locator(MultipleLocator(1))
        else:
            ax.yaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=5))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda tick, _: f"{int(tick)}" if tick >= 0 else ""))

        ax.set_title("Histogramme cumulatif des temps de nage")
        ax.legend(loc="lower right")
        ax.grid(axis="y", alpha=0.22, linestyle="--", linewidth=0.7)
        _place_histogram_stats_footnote(
            fig,
            stats_text,
            ax=ax,
            nbins=nbins,
            ylabel="Nombre cumulé de performances",
        )
        return fig

    def plot_boxplot_temps_par_nage(
        self,
        df: pd.DataFrame,
        stroke_col: str = "Stroke",
        swim_col: str = "SwimTimeSeconds",
        *,
        title: str = "Distribution des temps par type de nage (boxplot)",
    ) -> plt.Figure:
        """Boxplot des temps par type de nage avec thème Pacing unifié.

        Compare les distributions sur un axe commun (Cleveland & McGill) :
        palette catégorielle Okabe-Ito par nage, points individuels en
        superposition (jitter) et médiane annotée au-dessus de chaque boîte.

        Args:
            df (pd.DataFrame): Données de performances.
            stroke_col (str): Colonne du type de nage.
            swim_col (str): Colonne des temps en secondes.
            title (str): Titre affiché au-dessus du graphique.

        Returns:
            plt.Figure: Figure matplotlib du boxplot.

        Raises:
            ValueError: Si ``swim_col`` est absent du DataFrame.
        """
        if swim_col not in df.columns:
            raise ValueError(f"Colonne introuvable pour le boxplot: {swim_col}")

        local_df = df.copy()
        local_df[swim_col] = pd.to_numeric(local_df.get(swim_col), errors="coerce")
        local_df = local_df.dropna(subset=[stroke_col, swim_col])
        local_df = local_df.loc[local_df[swim_col] > 0].copy()
        local_df = relabel_stroke_column(local_df, stroke_col)

        fig, ax = plt.subplots(figsize=(12, 8))
        _apply_standard_chart_theme(fig, ax)

        if local_df.empty:
            ax.text(
                0.5,
                0.5,
                "Aucune performance disponible pour ce périmètre.",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=12,
                color="#334155",
            )
            ax.set_axis_off()
            ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
            fig.tight_layout()
            return fig

        stroke_order = _ordered_stroke_labels(local_df[stroke_col].tolist())
        palette = _stroke_palette_for_labels(stroke_order)

        sns.boxplot(
            data=local_df,
            x=stroke_col,
            y=swim_col,
            order=stroke_order,
            hue=stroke_col,
            palette=palette,
            dodge=False,
            width=0.52,
            linewidth=1.4,
            fliersize=0,
            boxprops={"facecolor": "white", "alpha": 0.88, "edgecolor": "#475569", "linewidth": 1.4},
            medianprops={"color": NON_CORRIDOR_COLOR_NEUTRAL, "linewidth": 2.4},
            whiskerprops={"color": "#64748b", "linewidth": 1.2, "linestyle": "-"},
            capprops={"color": "#64748b", "linewidth": 1.2},
            legend=False,
            ax=ax,
            zorder=3,
        )
        for stroke_label in stroke_order:
            stroke_subset = local_df.loc[local_df[stroke_col] == stroke_label]
            sns.stripplot(
                data=stroke_subset,
                x=stroke_col,
                y=swim_col,
                order=stroke_order,
                color=palette[stroke_label],
                size=4.0,
                alpha=0.35,
                jitter=0.24,
                linewidth=0.4,
                edgecolor="#ffffff",
                ax=ax,
                zorder=2,
            )

        box_center_x = _boxplot_category_center_x(ax, len(stroke_order))
        y_max = float(local_df[swim_col].max())
        y_min = float(local_df[swim_col].min())
        y_span = max(y_max - y_min, 0.01)
        label_offset = y_span * 0.03
        median_label_ymax = y_min

        for x_center, stroke_label in zip(box_center_x, stroke_order):
            stroke_values = local_df.loc[
                local_df[stroke_col] == stroke_label, swim_col
            ].astype(float)
            if stroke_values.empty:
                continue
            median_val = float(stroke_values.median())
            q1_val = float(stroke_values.quantile(0.25))
            q3_val = float(stroke_values.quantile(0.75))
            iqr = max(q3_val - q1_val, 0.01)
            whisker_top = min(float(stroke_values.max()), q3_val + 1.5 * iqr)
            label_y = whisker_top + label_offset
            median_label_ymax = max(median_label_ymax, label_y)
            ax.text(
                x_center,
                label_y,
                _format_swim_time_annotation(median_val),
                ha="center",
                va="bottom",
                fontsize=9.5,
                color="#0f172a",
                fontweight="semibold",
                bbox=_MEDIAN_LABEL_BBOX,
                zorder=6,
            )

        tick_labels = [
            f"{label}\n(n={int((local_df[stroke_col] == label).sum())})"
            for label in stroke_order
        ]
        ax.set_xticks(box_center_x)
        ax.set_xticklabels(tick_labels)

        ax.set_ylabel("Temps (secondes)")
        ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
        ax.yaxis.set_major_formatter(FuncFormatter(_format_swim_time_tick))
        y_top = max(y_max + y_span * 0.12, median_label_ymax + y_span * 0.04)
        ax.set_ylim(y_min - y_span * 0.06, y_top)
        ax.grid(
            axis="y",
            alpha=CORRIDOR_GRID_ALPHA,
            color="#94a3b8",
            linestyle="-",
            linewidth=0.6,
            zorder=0,
        )
        fig.tight_layout()
        ax.set_xlabel("Type de nage", fontsize=11, labelpad=18)
        ax.xaxis.set_label_coords(0.5, -0.11)
        return fig

    def plot_top10_clubs(
        self,
        df: pd.DataFrame,
        club_col: str = "Club",
        *,
        title: str = "Top 10 clubs par participation",
    ) -> plt.Figure:
        """Classement horizontal des clubs les plus représentés.

        Barres horizontales triées par effectif décroissant, palette séquentielle
        Pacing et libellés de clubs lisibles sans rotation (Cleveland & McGill).

        Args:
            df (pd.DataFrame): Données de performances.
            club_col (str): Colonne du nom de club.
            title (str): Titre affiché au-dessus du graphique.

        Returns:
            plt.Figure: Figure matplotlib du top 10 clubs.
        """
        club_series = df.get(club_col, pd.Series(dtype=str)).dropna().astype(str).str.strip()
        club_series = club_series.loc[club_series != ""]
        counts = club_series.value_counts().nlargest(10)
        return _plot_ranked_horizontal_counts(
            counts,
            title=title,
            y_label="Club",
            x_label="Nombre de participations",
            total_count=int(len(club_series)),
        )

    def plot_heatmap_vitesse_moyenne(
        self,
        df: pd.DataFrame,
        distance_col: str = "Distance",
        stroke_col: str = "Stroke",
        speed_col: str = "Speed",
    ) -> plt.Figure:
        """Heatmap de la vitesse médiane par distance et nage (peloton).

        Args:
            df (pd.DataFrame): Données de performances.
            distance_col (str): Colonne distance (conservée pour compatibilité API).
            stroke_col (str): Colonne type de nage (conservée pour compatibilité API).
            speed_col (str): Colonne vitesse (conservée pour compatibilité API).

        Returns:
            plt.Figure: Figure matplotlib de la heatmap.
        """
        _ = (distance_col, stroke_col, speed_col)
        long_df = self._get_cached_speed_heatmap_long_df(df)
        speed_pivot, count_pivot = _speed_heatmap_pivot_tables(
            long_df,
            mask=pd.Series(True, index=long_df.index),
        )
        vmin = float(speed_pivot.min().min(skipna=True)) if not speed_pivot.empty else 0.0
        vmax = float(speed_pivot.max().max(skipna=True)) if not speed_pivot.empty else 1.0
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            vmin, vmax = 0.8, 1.8

        fig, ax = plt.subplots(figsize=(12, 7))
        _draw_speed_heatmap_panel(
            ax,
            speed_pivot,
            count_pivot,
            title="Heatmap vitesse médiane (distance × nage)",
            vmin=vmin,
            vmax=vmax,
            cmap=NON_CORRIDOR_CMAP_SEQUENTIAL,
            cbar=True,
            cbar_label="Vitesse médiane (m/s)",
            show_counts=False,
        )
        fig.suptitle(
            "Synthèse peloton · vitesse médiane par distance et nage",
            fontsize=14,
            fontweight="bold",
            y=1.02,
        )
        fig.tight_layout()
        return fig

    def plot_swimming_speed_by_distance_and_stroke(
        self,
        df: pd.DataFrame,
        speed_col: str = "Speed",
        distance_col: str = "Distance",
        stroke_col: str = "Stroke",
        *,
        title: str = GRAPH_VITESSE_DISTANCE_NAGE,
        gender_filter: Optional[str] = None,
    ) -> Optional[plt.Figure]:
        """Vitesse médiane par distance et type de nage — courbes ordonnées.

        Agrège la vitesse médiane (m/s) pour chaque couple distance × nage après
        nettoyage méthodologique (âge, statut, cohérence épreuve, IQR).

        Args:
            df (pd.DataFrame): Données de performances.
            speed_col (str): Colonne vitesse en m/s (recalculée depuis le temps).
            distance_col (str): Colonne distance en mètres.
            stroke_col (str): Colonne du type de nage.
            title (str): Titre affiché au-dessus du graphique.
            gender_filter (Optional[str]): ``F``, ``M`` ou None pour tous les sexes.

        Returns:
            Optional[plt.Figure]: Figure matplotlib ou None si données insuffisantes.
        """
        if gender_filter not in (None, "F", "M"):
            gender_filter = None

        min_group_n = _resolve_speed_distance_min_group_n(len(df))
        speed_by_dist = _prepare_speed_distance_stroke_stats(
            df,
            distance_col=distance_col,
            stroke_col=stroke_col,
            gender_filter=gender_filter,
            min_group_n=min_group_n,
        )

        gender_note = "tous sexes · LCM + SCM"
        age_note = (
            f"âge ≥ {_SPEED_DISTANCE_MIN_AGE_YEARS} ans"
            if len(df) >= max(min_group_n * 2, 8)
            else "âge assoupli (petit échantillon)"
        )
        subtitle = (
            f"Médiane · {age_note} · ≥ {min_group_n} perf./point · {gender_note} · "
            "épreuve = distance · axe X linéaire"
        )
        chart_title = title or "Vitesse médiane par distance et type de nage"
        if speed_by_dist.empty:
            return _plot_mean_speed_by_distance_and_stroke(
                speed_by_dist,
                title=chart_title,
                subtitle=subtitle,
                empty_message=(
                    "Données insuffisantes pour tracer ce profil.\n"
                    "Vérifiez que le jeu de données contient assez de performances valides."
                ),
                distance_col=distance_col,
                speed_col="median_speed",
                stroke_col=stroke_col,
                count_col="n",
            )
        return _plot_mean_speed_by_distance_and_stroke(
            speed_by_dist,
            title=chart_title,
            subtitle=subtitle,
            distance_col=distance_col,
            speed_col="median_speed",
            stroke_col=stroke_col,
            count_col="n",
        )

    def plot_vitesse_max_par_split_et_nage(
        self,
        df: pd.DataFrame,
        *,
        title: str = GRAPH_VITESSE_MAX_SPLIT_NAGE,
    ) -> tuple[plt.Figure, pd.DataFrame]:
        """Records de vitesse de split par distance cumulée et type de nage.

        Pour chaque couple nage × distance de passage, affiche la vitesse
        maximale observée dans le périmètre après nettoyage des splits.

        Args:
            df (pd.DataFrame): Performances avec colonne ``splits``.
            title (str): Titre affiché au-dessus du graphique.

        Returns:
            tuple[plt.Figure, pd.DataFrame]: Figure matplotlib et tableau des
                records ; le DataFrame des pics peut être vide.
        """
        df_splits = _extract_all_split_speed_rows(df)
        peaks = _prepare_max_split_speed_by_stroke(df_splits)
        subtitle = (
            f"Record par distance de passage · vitesses "
            f"{_SPLIT_SPEED_MIN_MPS:.2f}–{_SPLIT_SPEED_MAX_MPS:.1f} m/s · "
            "statut OK · échelle X linéaire"
        )
        chart_title = title or GRAPH_VITESSE_MAX_SPLIT_NAGE
        if peaks.empty:
            fig = _plot_max_split_speed_by_stroke(
                peaks,
                title=chart_title,
                subtitle=subtitle,
                empty_message=(
                    "Aucun split exploitable dans ce périmètre.\n"
                    "Vérifiez que les performances incluent des chronos intermédiaires."
                ),
            )
            return fig, peaks
        fig = _plot_max_split_speed_by_stroke(
            peaks,
            title=chart_title,
            subtitle=subtitle,
        )
        return fig, peaks

    def plot_vitesse_moyenne_mediane_par_split_et_nage(
        self,
        df: pd.DataFrame,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        """Courbes de vitesse moyenne et médiane par split et nage.
        
        Args:
            df (pd.DataFrame): Performances avec splits.
        
        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame]: Figure et statistiques par split.
        """
        local_df = df.loc[
            df["Speed"].notna(),
            ["Stroke", "Distance", "Speed", "swimmer", "splits"],
        ].copy()

        split_rows: list[dict[str, object]] = []
        has_splits = local_df["splits"].apply(lambda x: isinstance(x, list) and len(x) > 0)
        for _, row in local_df.loc[has_splits].iterrows():
            stroke = row["Stroke"]
            for split in row["splits"]:
                if not isinstance(split, dict):
                    continue
                split_distance = split.get("split_distance")
                split_speed = split.get("split_speed")
                if split_distance is None or split_speed is None:
                    continue
                try:
                    distance = int(str(split_distance).replace(" m", "").strip())
                    speed = float(split_speed)
                except (TypeError, ValueError):
                    continue
                if 0 < speed < 5:
                    split_rows.append(
                        {
                            "Stroke": stroke,
                            "SplitDistance": distance,
                            "SplitSpeed": speed,
                        }
                    )

        df_splits = pd.DataFrame(split_rows)
        if df_splits.empty:
            return None, pd.DataFrame()

        df_stats = (
            df_splits.groupby(["Stroke", "SplitDistance"], as_index=False)
            .agg(
                MeanSpeed=("SplitSpeed", "mean"),
                MedianSpeed=("SplitSpeed", "median"),
                N=("SplitSpeed", "size"),
            )
        )
        df_stats = relabel_stroke_column(df_stats, "Stroke")

        df_plot = df_stats.melt(
            id_vars=["Stroke", "SplitDistance", "N"],
            value_vars=["MeanSpeed", "MedianSpeed"],
            var_name="Stat",
            value_name="SpeedValue",
        )
        df_plot["Stat"] = df_plot["Stat"].map(
            {
                "MeanSpeed": "Moyenne",
                "MedianSpeed": "Mediane",
            }
        )

        fig, ax = plt.subplots(figsize=(13, 7))
        sns.set_style("whitegrid")
        sns.scatterplot(
            data=df_plot,
            x="SplitDistance",
            y="SpeedValue",
            hue="Stroke",
            style="Stat",
            s=150,
            ax=ax,
        )

        max_split = int(df_plot["SplitDistance"].max())
        ax.set_xticks(np.arange(0, max_split + 50, 50))
        ax.set_title("Vitesse moyenne et médiane par split et nage", fontsize=16)
        ax.set_xlabel("Distance du split (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(title="Nage / Statistique", bbox_to_anchor=(1.05, 1), loc="upper left")
        fig.tight_layout()
        return fig, df_plot

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

    def plot_nombre_performances_par_epreuve(
        self,
        df: pd.DataFrame,
        course_type: str = "LCM",
        *,
        sort_by_total: bool = False,
    ) -> plt.Figure:
        """Barres horizontales groupées F/M du nombre de performances par épreuve.

        Args:
            df (pd.DataFrame): Données de performances.
            course_type (str): Filtre bassin (« LCM » ou « SCM »).
            sort_by_total (bool): Si True, tri par effectif total décroissant.

        Returns:
            plt.Figure: Figure matplotlib des effectifs par épreuve.
        """
        local_df = df.copy()
        local_df["Gender"] = local_df["swimmer"].apply(
            lambda x: x[0].get("Gender") if isinstance(x, list) and len(x) > 0 else None
        )
        local_df["swimmer_name"] = local_df["swimmer"].apply(
            lambda x: x[0].get("Name") if isinstance(x, list) and len(x) > 0 else None
        )
        local_df = local_df.dropna(subset=["Gender", "Event", "swimmer_name"])
        local_df = local_df[local_df["Event"].str.contains(course_type, na=False)]

        df_counts = (
            local_df
            .groupby(["Event", "Gender"])["swimmer_name"]
            .count()
            .unstack(fill_value=0)
        )
        return _plot_gender_grouped_counts_by_event(
            df_counts,
            title=f"Nombre de performances par épreuve ({course_type})",
            by_total=sort_by_total,
        )

    def plot_nombre_performances_par_epreuve_lcm_scm(
        self,
        df: pd.DataFrame,
        *,
        sort_by_total: bool = False,
    ) -> plt.Figure:
        """Barres horizontales groupées F/M par épreuve, LCM et SCM fusionnés.

        Args:
            df (pd.DataFrame): Données de performances.
            sort_by_total (bool): Si True, tri par effectif total décroissant.

        Returns:
            plt.Figure: Figure matplotlib des effectifs combinés.
        """
        local_df = df.copy()
        local_df["Gender"] = local_df["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )
        local_df["Event_clean"] = (
            local_df["Event"]
            .str.replace(" LCM", "", regex=False)
            .str.replace(" SCM", "", regex=False)
        )
        local_df = local_df.dropna(subset=["Gender", "Event_clean"])

        df_counts = local_df.groupby(["Event_clean", "Gender"]).size().unstack(fill_value=0)
        return _plot_gender_grouped_counts_by_event(
            df_counts,
            title="Nombre de performances par épreuve (LCM + SCM)",
            by_total=sort_by_total,
        )

    def plot_nombre_performances_par_sexe(
        self,
        df: pd.DataFrame,
        *,
        title: str = "Nombre de performances par sexe",
    ) -> plt.Figure:
        """Diagramme en barres du nombre de performances par sexe.

        Args:
            df (pd.DataFrame): Données de performances.
            title (str): Titre affiché sur la figure.

        Returns:
            plt.Figure: Figure matplotlib du décompte par sexe.
        """
        local_df = df.copy()
        local_df["Gender"] = local_df["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )
        counts = (
            local_df["Gender"]
            .dropna()
            .value_counts()
            .to_dict()
        )
        return _plot_gender_performance_counts(counts, title=title)

    def plot_camembert_sexe_par_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
        *,
        title: Optional[str] = None,
    ) -> Optional[plt.Figure]:
        """Camembert de la répartition F/M pour une épreuve donnée.

        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            title (Optional[str]): Titre personnalisé ; sinon libellé localisé.

        Returns:
            Optional[plt.Figure]: Figure ou None si aucune donnée de sexe.
        """
        df_event = df.loc[df["Event"] == nom_event].copy()
        df_event["Gender"] = df_event["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )

        gender_counts = df_event["Gender"].value_counts().to_dict()
        if not gender_counts:
            return None

        chart_title = title or (
            f"Proportion des performances par sexe — {localize_event_string(nom_event)}"
        )
        return _plot_gender_pie_chart(gender_counts, title=chart_title)

    def plot_temps_median_top10_clubs_par_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
        *,
        title: Optional[str] = None,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        """Classement horizontal des temps médians des meilleurs clubs sur une épreuve.

        Sélectionne les clubs au temps médian le plus bas (meilleure performance),
        puis trace des barres horizontales avec thème Pacing et temps en secondes.

        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            title (Optional[str]): Titre personnalisé ; sinon libellé localisé par défaut.

        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame]: Figure et stats médianes par club.
        """
        df_time = df[
            (df["Event"] == nom_event)
            & (df["SwimTimeSeconds"].notna())
            & (pd.to_numeric(df["SwimTimeSeconds"], errors="coerce") > 0)
        ].copy()
        if df_time.empty:
            return None, pd.DataFrame()

        df_time["Club"] = df_time.get("Club", pd.Series(dtype=str)).astype(str).str.strip()
        df_time = df_time.loc[df_time["Club"] != ""].copy()
        if df_time.empty:
            return None, pd.DataFrame()

        top10_clubs = (
            df_time.groupby("Club", as_index=False)
            .agg(
                median_seconds=("SwimTimeSeconds", "median"),
                n_performances=("SwimTimeSeconds", "size"),
            )
            .sort_values("median_seconds", ascending=True)
            .head(10)
            .reset_index(drop=True)
        )
        if top10_clubs.empty:
            return None, pd.DataFrame()

        chart_title = title or (
            f"Temps médian des 10 meilleurs clubs - {localize_event_string(nom_event)}"
        )
        fig = _plot_ranked_horizontal_median_times(
            top10_clubs,
            title=chart_title,
            club_col="Club",
            median_col="median_seconds",
            count_col="n_performances",
            y_label="Club",
            x_label="Temps médian (secondes)",
        )
        return fig, top10_clubs

    def plot_evolution_temps_nage(
        self,
        df: pd.DataFrame,
        start_year: int = 2000,
        sample_size: int = 5000,
        *,
        title: Optional[str] = None,
    ) -> Optional[plt.Figure]:
        """Évolution des temps médians annuels par type de nage.

        Agrège les performances par année et par nage (médiane), après filtrage
        IQR des temps extrêmes. Chaque nage est tracée dans un panneau dédié
        avec lissage par moyenne mobile, années peu représentées exclues,
        graduations d'années sur chaque panneau et thème Pacing.

        Args:
            df (pd.DataFrame): Données de performances.
            start_year (int): Année minimale incluse.
            sample_size (int): Taille d'échantillon aléatoire (0 = toutes les lignes).
            title (Optional[str]): Titre personnalisé ; sinon libellé par défaut.

        Returns:
            Optional[plt.Figure]: Figure ou None si données insuffisantes.
        """
        local_df = df.copy()
        local_df["SwimDate"] = pd.to_datetime(local_df["SwimDate"], errors="coerce")
        local_df["SwimTimeSeconds"] = pd.to_numeric(
            local_df.get("SwimTimeSeconds"), errors="coerce"
        )

        df_plot = local_df[
            local_df["SwimDate"].notna()
            & local_df["SwimTimeSeconds"].notna()
            & (local_df["SwimTimeSeconds"] > 0)
            & (local_df["SwimDate"].dt.year >= start_year)
        ].copy()

        if df_plot.empty:
            return None

        df_plot["year"] = df_plot["SwimDate"].dt.year.astype(int)
        if sample_size > 0:
            df_work = df_plot.sample(min(sample_size, len(df_plot)), random_state=42)
        else:
            df_work = df_plot

        df_work = relabel_stroke_column(df_work, "Stroke")
        yearly_stats = _compute_yearly_stroke_median_times(
            df_work,
            stroke_col="Stroke",
            swim_col="SwimTimeSeconds",
            year_col="year",
        )
        if yearly_stats.empty:
            return None

        chart_title = title or (
            f"Évolution des temps médians par nage (à partir de {start_year})"
        )
        return _plot_yearly_stroke_time_evolution(
            yearly_stats,
            title=chart_title,
            stroke_col="Stroke",
            year_col="year",
            median_col="median_seconds",
        )

    def plot_top10_nageurs_meilleur_temps_par_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        """Barres horizontales du top 10 des meilleurs temps sur une épreuve.
        
        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
        
        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame]: Figure et DataFrame du top 10.
        """
        subset = df[
            (df["Event"] == nom_event)
            & (df["SwimTimeSeconds"].notna())
            & (df["SwimTimeSeconds"] > 0)
        ].copy()

        if subset.empty:
            return None, pd.DataFrame()

        subset["SwimmerName"] = subset["swimmer"].apply(
            lambda x: x[0]["Name"] if isinstance(x, list) and len(x) > 0 else "Unknown"
        )

        best_times = subset.groupby("SwimmerName", as_index=False)["SwimTimeSeconds"].min()
        top10 = best_times.nsmallest(10, "SwimTimeSeconds")

        def format_time(sec: float) -> str:
            """Formate un temps en secondes en chaîne « M:SS.mm min ».
            
            Args:
                sec (float): Durée en secondes.
            
            Returns:
                str: Libellé formaté pour annotation graphique.
            """
            minutes = int(sec // 60)
            seconds = sec % 60
            return f"{minutes}:{seconds:05.2f} min"

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(
            x="SwimTimeSeconds",
            y="SwimmerName",
            data=top10,
            palette=NON_CORRIDOR_CMAP_DIVERGING,
            orient="h",
            errorbar=None,
            ax=ax,
        )

        ax.set_title(f"Top 10 nageurs (meilleur temps) - {localize_event_string(nom_event)}")
        ax.set_ylabel("Nageur")
        ax.set_xlabel("")
        ax.set_xticks([])
        ax.spines["bottom"].set_visible(False)

        for i, v in enumerate(top10["SwimTimeSeconds"]):
            ax.text(v + 0.5, i, format_time(v), va="center")

        fig.tight_layout()
        return fig, top10

    def plot_split_speed_analysis_by_gender_with_targets(
        self,
        df: pd.DataFrame,
        nom_event: str,
        swimmer_targets: list[str],
        target_colors: Optional[dict[str, str]] = None,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        """Analyse des vitesses de split F vs M avec surcouches de nageurs cibles.

        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            swimmer_targets (list[str]): Noms de nageurs à superposer.
            target_colors (Optional[dict[str, str]]): Couleurs par nageur cible.

        Returns:
            tuple: Figure, stats globales, stats cibles et métadonnées.
        """
        target_colors = target_colors or {}
        style_by_gender = {
            "F": {
                "fill": "#F6D5E8",
                "median": NON_CORRIDOR_COLOR_FEMALE,
                "mean": "#9D4B85",
            },
            "M": {
                "fill": "#D2E8F8",
                "median": NON_CORRIDOR_COLOR_MALE,
                "mean": "#1B4F8A",
            },
        }
        fill_alpha = 0.22
        line_width_med = 2.8
        line_width_mean = 3.2
        marker_size = 7

        event_distance = parse_event_distance_m(nom_event)
        long_df = self._get_cached_split_speed_rows(df, nom_event)
        performances_count = (
            int(long_df["swim_key"].nunique()) if not long_df.empty else 0
        )

        if long_df.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "event_distance": event_distance,
                "message": (
                    f"Aucune vitesse de split exploitable pour "
                    f"{localize_event_string(nom_event)}."
                ),
                "performances_count": performances_count,
                "split_values_count": 0,
            }

        target_set_norm = {corridor_norm_name(name) for name in swimmer_targets}
        long_df = long_df.copy()
        long_df["is_target"] = long_df["Name"].apply(
            lambda name: corridor_norm_name(name) in target_set_norm
        )

        df_splits = long_df[["Gender", "split_no", "split_distance", "split_speed"]].copy()
        target_rows = long_df.loc[
            long_df["is_target"],
            ["Name", "Gender", "split_no", "split_distance", "split_speed"],
        ]

        stats = (
            df_splits.groupby(["Gender", "split_no"])["split_speed"]
            .agg(
                mean="mean",
                median="median",
                q1=lambda x: x.quantile(0.25),
                q3=lambda x: x.quantile(0.75),
                n="count",
            )
            .reset_index()
            .sort_values(["Gender", "split_no"])
        )
        stats["split_distance_theorique"] = stats["split_no"].map(
            df_splits.groupby("split_no")["split_distance"].first().to_dict()
        )

        if not target_rows.empty:
            target_stats = (
                target_rows.groupby(["Name", "Gender", "split_no"])["split_speed"]
                .agg(target_mean="mean", target_n="count")
                .reset_index()
                .sort_values(["Name", "split_no"])
            )
            target_stats["split_distance_theorique"] = target_stats["split_no"].map(
                target_rows.groupby("split_no")["split_distance"].first().to_dict()
            )
        else:
            target_stats = pd.DataFrame()

        fig, ax = plt.subplots(figsize=(13, 7))
        for gender in ["F", "M"]:
            data_gender = stats[stats["Gender"] == gender].sort_values("split_no")
            if data_gender.empty:
                continue
            style = style_by_gender[gender]
            ax.fill_between(
                data_gender["split_no"],
                data_gender["q1"],
                data_gender["q3"],
                color=style["fill"],
                alpha=fill_alpha,
                linewidth=0,
                label=f"IQR (Q1-Q3) - {gender}",
            )
            ax.plot(
                data_gender["split_no"],
                data_gender["median"],
                color=style["median"],
                linewidth=line_width_med,
                linestyle="--",
                marker="s",
                markersize=marker_size,
                markeredgecolor="white",
                markeredgewidth=0.8,
                label=f"Mediane - {gender}",
                zorder=5,
            )
            ax.plot(
                data_gender["split_no"],
                data_gender["mean"],
                color=style["mean"],
                linewidth=line_width_mean,
                linestyle="-",
                marker="o",
                markersize=marker_size,
                markeredgecolor="white",
                markeredgewidth=0.8,
                label=f"Moyenne - {gender}",
                zorder=6,
            )

        if not target_stats.empty:
            for swimmer in swimmer_targets:
                swimmer_norm = corridor_norm_name(swimmer)
                data_sw = target_stats[
                    target_stats["Name"].apply(corridor_norm_name) == swimmer_norm
                ].sort_values("split_no")
                if data_sw.empty:
                    continue
                gender = data_sw.iloc[0]["Gender"]
                color_sw = target_colors.get(swimmer, NON_CORRIDOR_COLOR_NEUTRAL)
                ax.plot(
                    data_sw["split_no"],
                    data_sw["target_mean"],
                    color=color_sw,
                    linewidth=3.2,
                    linestyle="-",
                    marker="D",
                    markersize=8,
                    markeredgecolor="white",
                    markeredgewidth=0.9,
                    label=f"{swimmer} (moyenne, {gender})",
                    zorder=7,
                )

        ticks = sorted(df_splits["split_no"].dropna().astype(int).unique().tolist())
        distance_by_no = df_splits.groupby("split_no")["split_distance"].first().to_dict()
        labels = [f"{int(distance_by_no.get(tick, tick * 50))} m" for tick in ticks]
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        ax.set_title(
            f"{localize_event_string(nom_event)} - vitesse de split - F vs M + nageurs cibles",
            fontsize=14,
            fontweight="bold",
        )
        ax.set_xlabel("Rang du split", fontsize=12)
        ax.set_ylabel("Vitesse par split", fontsize=12)
        ax.grid(alpha=0.25)
        ax.legend(ncol=2, frameon=False, fontsize=9)
        fig.tight_layout()

        return fig, stats, target_stats, {
            "event_distance": event_distance,
            "message": "ok",
            "performances_count": performances_count,
            "split_values_count": len(df_splits),
        }

    def plot_vitesse_par_split_pour_nageur_event(
        self,
        df: pd.DataFrame,
        nom_nageur: str,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, Optional[str]]:
        """Courbe de vitesse par split pour un nageur sur une épreuve.
        
        Args:
            df (pd.DataFrame): Données de performances.
            nom_nageur (str): Nom du nageur cible.
            nom_event (str): Libellé de l'épreuve.
        
        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, Optional[str]]: Figure, splits et genre.
        """
        split_data: list[dict[str, object]] = []
        gender_nageur: Optional[str] = None

        for _, row in df.iterrows():
            swimmers = row.get("swimmer", [])
            if row.get("Event") != nom_event or not isinstance(swimmers, list) or len(swimmers) != 1:
                continue
            swimmer = swimmers[0]
            if not isinstance(swimmer, dict) or swimmer.get("Name") != nom_nageur:
                continue

            gender_nageur = swimmer.get("Gender")
            for split in row.get("splits", []):
                if not isinstance(split, dict) or split.get("split_speed") is None:
                    continue
                try:
                    distance = int(str(split.get("split_distance")).replace(" m", ""))
                    speed = float(split.get("split_speed"))
                except (TypeError, ValueError):
                    continue
                split_data.append({"split_distance": distance, "split_speed": speed})

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), gender_nageur

        df_splits = df_splits.sort_values("split_distance")
        if gender_nageur == "M":
            color_line = NON_CORRIDOR_COLOR_MALE
        elif gender_nageur == "F":
            color_line = NON_CORRIDOR_COLOR_FEMALE
        else:
            color_line = NON_CORRIDOR_COLOR_NEUTRAL

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            data=df_splits,
            marker="o",
            color=color_line,
            errorbar=None,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        plt.setp(ax.get_xticklabels(), rotation=45)
        ax.set_title(f"Vitesse par split pour {nom_nageur} - {localize_event_string(nom_event)}")
        ax.set_xlabel("Split (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True)
        fig.tight_layout()
        return fig, df_splits, gender_nageur

    def plot_vitesse_par_split_meilleur_nageur_event_periode(
        self,
        df: pd.DataFrame,
        nom_event: str,
        annee_debut: int,
        annee_fin: int,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
        """Vitesse par split du meilleur nageur sur une épreuve et période.
        
        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            annee_debut (int): Première année incluse.
            annee_fin (int): Dernière année incluse.
        
        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]: Figure, splits et métadonnées.
        """
        df_work = df.copy()
        df_work.columns = df_work.columns.map(lambda x: str(x).strip())

        event_col = next((c for c in df_work.columns if c.lower() == "event"), None)
        swimtime_col = next((c for c in df_work.columns if c.lower() == "swimtimeseconds"), None)
        swimmer_col = next((c for c in df_work.columns if c.lower() == "swimmer"), None)
        if event_col is None or swimtime_col is None or swimmer_col is None:
            return None, pd.DataFrame(), {
                "message": "Colonnes indispensables manquantes (Event/SwimTimeSeconds/swimmer).",
            }

        year_candidates = [c for c in df_work.columns if "year" in c.lower()]
        date_candidates = [c for c in df_work.columns if "date" in c.lower()]

        chosen_year_col = None
        for pref in ["swimyear", "year", "meetyear", "competitionyear"]:
            chosen_year_col = next((c for c in year_candidates if c.lower() == pref), None)
            if chosen_year_col is not None:
                break
        if chosen_year_col is None and len(year_candidates) > 0:
            chosen_year_col = year_candidates[0]

        if chosen_year_col is not None:
            df_work["year"] = pd.to_numeric(df_work[chosen_year_col], errors="coerce")
        else:
            chosen_date_col = None
            for pref in ["swimdate", "date", "mpp_date", "meetdate", "competitiondate"]:
                chosen_date_col = next((c for c in date_candidates if c.lower() == pref), None)
                if chosen_date_col is not None:
                    break
            if chosen_date_col is None and len(date_candidates) > 0:
                chosen_date_col = date_candidates[0]
            if chosen_date_col is None:
                return None, pd.DataFrame(), {"message": "Aucune colonne annee/date disponible."}
            df_work["year"] = pd.to_datetime(df_work[chosen_date_col], errors="coerce").dt.year

        df_event = df_work[
            (df_work[event_col] == nom_event)
            & (df_work[swimtime_col].notna())
            & (df_work[swimmer_col].apply(lambda x: isinstance(x, list) and len(x) == 1))
            & (df_work["year"].between(annee_debut, annee_fin))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), {
                "message": f"Aucune performance pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        df_event["swimmer_name"] = df_event[swimmer_col].apply(
            lambda x: x[0].get("Name") if isinstance(x, list) and len(x) == 1 and isinstance(x[0], dict) else None
        )
        df_event["swimmer_gender"] = df_event[swimmer_col].apply(
            lambda x: x[0].get("Gender") if isinstance(x, list) and len(x) == 1 and isinstance(x[0], dict) else None
        )

        best_row = df_event.nsmallest(1, swimtime_col).iloc[0]
        best_name = best_row["swimmer_name"]
        best_gender = best_row["swimmer_gender"]
        best_time = float(best_row[swimtime_col])
        best_year = best_row["year"]
        meet_col = next((c for c in df_event.columns if c.lower() == "meet"), None)
        best_meet = best_row[meet_col] if meet_col is not None else "Meet non disponible"

        split_data: list[dict[str, object]] = []
        best_splits = best_row.get("splits", [])
        if isinstance(best_splits, list):
            for split in best_splits:
                if not isinstance(split, dict):
                    continue
                if split.get("split_speed") is None or split.get("split_distance") is None:
                    continue
                try:
                    distance = int(str(split["split_distance"]).replace(" m", "").strip())
                    speed = float(split["split_speed"])
                except (TypeError, ValueError):
                    continue
                split_data.append({"split_distance": distance, "split_speed": speed})

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), {
                "message": (
                    f"Aucun split valide trouve pour le meilleur nageur de l'event {nom_event} "
                    f"({annee_debut}-{annee_fin})."
                ),
                "best_name": best_name,
                "best_gender": best_gender,
                "best_time": best_time,
                "best_year": best_year,
                "best_meet": best_meet,
            }

        df_splits = df_splits.sort_values("split_distance")
        color = NON_CORRIDOR_COLOR_MALE if best_gender == "M" else NON_CORRIDOR_COLOR_FEMALE
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            data=df_splits,
            marker="o",
            color=color,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(
            f"Vitesse par split pour {best_name} ({best_gender}) - {nom_event} ({annee_debut}-{annee_fin})",
            fontsize=16,
        )
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse (m/s)", fontsize=14)
        ax.grid(True)
        fig.tight_layout()
        return fig, df_splits, {
            "best_name": best_name,
            "best_gender": best_gender,
            "best_time": best_time,
            "best_year": best_year,
            "best_meet": best_meet,
            "message": "ok",
        }

    def plot_vitesse_par_split_top_nageurs_hf_event_periode(
        self,
        df: pd.DataFrame,
        nom_event: str,
        annee_debut: int,
        annee_fin: int,
        top_n: int = 1,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
        """Vitesses par split des meilleurs nageurs H et F sur une période.
        
        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            annee_debut (int): Première année incluse.
            annee_fin (int): Dernière année incluse.
            top_n (int): Nombre de nageurs par genre.
        
        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]: Figure, splits et métadonnées.
        """
        df_work = df.copy()
        df_work.columns = df_work.columns.map(lambda x: str(x).strip())

        if "SwimnjkYear" in df_work.columns:
            df_work["year"] = pd.to_numeric(df_work["SwimYear"], errors="coerce")
        elif "Year" in df_work.columns:
            df_work["year"] = pd.to_numeric(df_work["Year"], errors="coerce")
        elif "SwimDate" in df_work.columns:
            df_work["year"] = pd.to_datetime(df_work["SwimDate"], errors="coerce").dt.year
        elif "Date" in df_work.columns:
            df_work["year"] = pd.to_datetime(df_work["Date"], errors="coerce").dt.year
        elif "mpp_date" in df_work.columns:
            df_work["year"] = pd.to_datetime(df_work["mpp_date"], errors="coerce").dt.year
        else:
            return None, pd.DataFrame(), {"message": "Aucune colonne annee/date trouvee."}

        df_event = df_work[
            (df_work["Event"] == nom_event)
            & (df_work["SwimTimeSeconds"].notna())
            & (df_work["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1))
            & (df_work["year"].between(annee_debut, annee_fin))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), {
                "message": f"Aucune performance pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        df_event["swimmer_name"] = df_event["swimmer"].apply(lambda x: x[0]["Name"])
        df_event["swimmer_gender"] = df_event["swimmer"].apply(lambda x: x[0]["Gender"])

        df_top_men = df_event[df_event["swimmer_gender"] == "M"].nsmallest(top_n, "SwimTimeSeconds")
        df_top_women = df_event[df_event["swimmer_gender"] == "F"].nsmallest(top_n, "SwimTimeSeconds")
        df_top_all = pd.concat([df_top_men, df_top_women], ignore_index=True)

        split_data: list[dict[str, object]] = []
        for _, row in df_top_all.iterrows():
            swimmer_name = row["swimmer_name"]
            gender = row["swimmer_gender"]
            splits = row["splits"]
            if not isinstance(splits, list):
                continue
            for split in splits:
                if not isinstance(split, dict):
                    continue
                if split.get("split_speed") is None or split.get("split_distance") is None:
                    continue
                try:
                    distance = int(str(split["split_distance"]).replace(" m", "").strip())
                    speed = float(split["split_speed"])
                except (TypeError, ValueError):
                    continue
                split_data.append(
                    {
                        "swimmer": swimmer_name,
                        "gender": gender,
                        "split_distance": distance,
                        "split_speed": speed,
                    }
                )

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), {"message": "Aucun split valide trouve pour les top nageurs."}

        df_splits["swimmer_label"] = df_splits["swimmer"] + " (" + df_splits["gender"] + ")"
        palette_colors = {"M": NON_CORRIDOR_COLOR_MALE, "F": NON_CORRIDOR_COLOR_FEMALE}
        labels_gender = df_splits[["swimmer_label", "gender"]].drop_duplicates()
        palette_for_plot = {
            row["swimmer_label"]: palette_colors.get(row["gender"], NON_CORRIDOR_COLOR_NEUTRAL)
            for _, row in labels_gender.iterrows()
        }

        fig, ax = plt.subplots(figsize=(14, 8))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            hue="swimmer_label",
            style="swimmer_label",
            data=df_splits,
            markers=True,
            dashes=False,
            palette=palette_for_plot,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(
            f"Vitesse par split pour les meilleurs nageurs - {nom_event} ({annee_debut}-{annee_fin})",
            fontsize=16,
        )
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse (m/s)", fontsize=14)
        ax.grid(True)
        ax.legend(title="Nageur (Genre)", bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=12)

        if not df_top_men.empty:
            best_male = df_top_men.nsmallest(1, "SwimTimeSeconds")["swimmer_name"].iloc[0]
            swimmer_data = df_splits[df_splits["swimmer"] == best_male]
            if not swimmer_data.empty:
                label = f"{best_male} ({swimmer_data['gender'].iloc[0]})"
                ax.scatter(
                    swimmer_data["split_distance"].iloc[-1],
                    swimmer_data["split_speed"].iloc[-1],
                    s=150,
                    color=palette_for_plot[label],
                    marker="*",
                    zorder=5,
                )

        if not df_top_women.empty:
            best_female = df_top_women.nsmallest(1, "SwimTimeSeconds")["swimmer_name"].iloc[0]
            swimmer_data = df_splits[df_splits["swimmer"] == best_female]
            if not swimmer_data.empty:
                label = f"{best_female} ({swimmer_data['gender'].iloc[0]})"
                ax.scatter(
                    swimmer_data["split_distance"].iloc[-1],
                    swimmer_data["split_speed"].iloc[-1],
                    s=150,
                    color=palette_for_plot[label],
                    marker="*",
                    zorder=5,
                )

        fig.tight_layout()
        return fig, df_splits, {
            "message": "ok",
            "top_men_count": len(df_top_men),
            "top_women_count": len(df_top_women),
        }

    def plot_vitesse_par_split_top_nageurs_uniques_event_periode(
        self,
        df: pd.DataFrame,
        nom_event: str,
        annee_debut: int,
        annee_fin: int,
        top_n: int = 10,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        """Vitesses par split des top N nageurs uniques (meilleure perf chacun).
        
        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            annee_debut (int): Première année incluse.
            annee_fin (int): Dernière année incluse.
            top_n (int): Nombre de nageurs à tracer.
        
        Returns:
            tuple: Figure, splits, top performers et métadonnées.
        """
        df_work = df.copy()
        df_work.columns = df_work.columns.map(lambda x: str(x).strip())

        year_col = None
        if "SwimYear" in df_work.columns:
            year_col = "SwimYear"
        elif "Year" in df_work.columns:
            year_col = "Year"
        else:
            year_candidates = [c for c in df_work.columns if "year" in c.lower()]
            if year_candidates:
                year_col = year_candidates[0]

        if year_col is not None:
            df_work["year"] = pd.to_numeric(df_work[year_col], errors="coerce")
        else:
            date_col = None
            for c in ["SwimDate", "Date", "mpp_date", "MeetDate", "CompetitionDate", "competition_date"]:
                if c in df_work.columns:
                    date_col = c
                    break
            if date_col is None:
                date_candidates = [c for c in df_work.columns if "date" in c.lower()]
                if date_candidates:
                    date_col = date_candidates[0]
            if date_col is None:
                return None, pd.DataFrame(), pd.DataFrame(), {"message": "Aucune colonne pour l'annee trouvee."}
            df_work["year"] = pd.to_datetime(df_work[date_col], errors="coerce").dt.year

        df_event = df_work[
            (df_work["Event"] == nom_event)
            & (df_work["SwimTimeSeconds"].notna())
            & (df_work["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1))
            & (df_work["year"].between(annee_debut, annee_fin))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": f"Aucune performance pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        df_event["swimmer_name"] = df_event["swimmer"].apply(lambda x: x[0].get("Name"))
        df_event["swimmer_gender"] = df_event["swimmer"].apply(lambda x: x[0].get("Gender"))

        df_best_per_swimmer = (
            df_event.sort_values("SwimTimeSeconds", ascending=True).drop_duplicates(subset=["swimmer_name"], keep="first")
        )
        df_top_all = df_best_per_swimmer.nsmallest(top_n, "SwimTimeSeconds").copy()
        if df_top_all.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": f"Aucun nageur unique trouve pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        split_data: list[dict[str, object]] = []
        for _, row in df_top_all.iterrows():
            swimmer_name = row["swimmer_name"]
            gender = row["swimmer_gender"]
            splits = row["splits"]
            if not isinstance(splits, list):
                continue
            for split in splits:
                if not isinstance(split, dict):
                    continue
                if split.get("split_speed") is None or split.get("split_distance") is None:
                    continue
                try:
                    distance = int(str(split["split_distance"]).replace(" m", "").strip())
                    speed = float(split["split_speed"])
                except (TypeError, ValueError):
                    continue
                split_data.append(
                    {
                        "swimmer": swimmer_name,
                        "gender": gender,
                        "split_distance": distance,
                        "split_speed": speed,
                    }
                )

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {"message": "Aucun split valide trouve pour les top nageurs."}

        df_splits["swimmer_label"] = df_splits["swimmer"] + " (" + df_splits["gender"].fillna("?") + ")"
        palette_colors = {"M": NON_CORRIDOR_COLOR_MALE, "F": NON_CORRIDOR_COLOR_FEMALE}
        labels_gender = df_splits[["swimmer_label", "gender"]].drop_duplicates()
        palette_for_plot = {
            row["swimmer_label"]: palette_colors.get(row["gender"], NON_CORRIDOR_COLOR_NEUTRAL)
            for _, row in labels_gender.iterrows()
        }

        fig, ax = plt.subplots(figsize=(14, 8))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            hue="swimmer_label",
            style="swimmer_label",
            data=df_splits,
            markers=True,
            dashes=False,
            palette=palette_for_plot,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(
            f"Vitesse par split - Top {top_n} nageurs uniques "
            f"({localize_event_string(nom_event)}, {annee_debut}-{annee_fin})",
            fontsize=16,
        )
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse (m/s)", fontsize=14)
        ax.grid(True)
        ax.legend(title="Nageur (Genre)", bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=11)
        fig.tight_layout()

        return fig, df_splits, df_top_all, {"message": "ok"}

    def plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres(
        self,
        df: pd.DataFrame,
        nageur_cible: str,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        """Heatmaps côte à côte : nageur cible vs peloton (vitesse médiane).

        Trois vues coordonnées (Perin et al., 2013 ; Du & Yuan, 2021) :
        nageur cible, peloton de référence, et écart cible − peloton.
        Échelle commune, effectifs par cellule, thème Pacing unifié.

        Args:
            df (pd.DataFrame): Données de performances.
            nageur_cible (str): Nom du nageur de référence.

        Returns:
            tuple[Optional[plt.Figure], dict[str, object]]: Figure et métadonnées
                (message, effectifs, exemples de noms).
        """
        long_df = self._get_cached_speed_heatmap_long_df(df)
        if long_df.empty:
            return None, {
                "message": "Aucune performance solo exploitable pour la heatmap.",
                "target_count": 0,
            }

        target_norm = corridor_norm_name(nageur_cible)
        target_mask = long_df["Name_norm"] == target_norm
        nb_target = int(target_mask.sum())
        if nb_target == 0:
            return None, {
                "message": f"Aucune ligne trouvée pour le nageur « {nageur_cible} ».",
                "examples": long_df["Name"].dropna().value_counts().head(30).to_dict(),
                "target_count": 0,
            }

        pivot_target, count_target = _speed_heatmap_pivot_tables(
            long_df,
            mask=target_mask,
        )
        pivot_others, count_others = _speed_heatmap_pivot_tables(
            long_df,
            mask=~target_mask,
        )
        stroke_cols = _canonical_heatmap_stroke_columns(pivot_target, pivot_others)
        pivot_target, count_target = _reindex_heatmap_grid(
            pivot_target, count_target, stroke_cols=stroke_cols
        )
        pivot_others, count_others = _reindex_heatmap_grid(
            pivot_others, count_others, stroke_cols=stroke_cols
        )
        delta = (pivot_target - pivot_others).reindex(
            index=list(_HEATMAP_STANDARD_DISTANCES),
            columns=stroke_cols,
        )

        speed_vals = pd.concat(
            [
                pivot_target.stack(future_stack=True),
                pivot_others.stack(future_stack=True),
            ]
        )
        if speed_vals.empty:
            return None, {
                "message": "Pas assez de données pour tracer la comparaison.",
                "target_count": nb_target,
            }
        vmin = float(speed_vals.min())
        vmax = float(speed_vals.max())
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            vmin, vmax = 0.8, 1.8

        delta_vals = delta.stack(future_stack=True)
        if delta_vals.empty:
            delta_lim = 0.1
        else:
            delta_lim = max(0.05, float(np.nanmax(np.abs(delta_vals.to_numpy()))))

        display_name = str(
            long_df.loc[target_mask, "Name"].iloc[0]
        ).strip() or nageur_cible

        fig, axes = plt.subplots(
            1,
            3,
            figsize=(24, 8),
            sharey=True,
            gridspec_kw={"width_ratios": [1.0, 1.0, 1.0], "wspace": 0.12},
            constrained_layout=True,
        )
        speed_mesh = _draw_speed_heatmap_panel(
            axes[0],
            pivot_target,
            count_target,
            title=f"{display_name} — vitesse médiane",
            vmin=vmin,
            vmax=vmax,
            cmap=NON_CORRIDOR_CMAP_SEQUENTIAL,
            cbar=False,
            cbar_label="Vitesse médiane (m/s)",
            show_counts=True,
        )
        _draw_speed_heatmap_panel(
            axes[1],
            pivot_others,
            count_others,
            title="Peloton — vitesse médiane",
            vmin=vmin,
            vmax=vmax,
            cmap=NON_CORRIDOR_CMAP_SEQUENTIAL,
            cbar=False,
            cbar_label="Vitesse médiane (m/s)",
            show_counts=False,
        )
        delta_mesh = _draw_speed_heatmap_panel(
            axes[2],
            delta,
            count_target,
            title="Écart cible − peloton",
            vmin=-delta_lim,
            vmax=delta_lim,
            cmap=NON_CORRIDOR_CMAP_DIVERGING,
            cbar=False,
            cbar_label="Écart (m/s)",
            center=0.0,
            show_counts=False,
        )
        n_rows = len(_HEATMAP_STANDARD_DISTANCES)
        for panel_ax in axes:
            panel_ax.set_ylim(n_rows, 0)
            panel_ax.set_xlim(0, len(stroke_cols))
        if speed_mesh is not None:
            speed_cbar = fig.colorbar(
                speed_mesh,
                ax=axes[:2],
                location="right",
                fraction=0.025,
                pad=0.02,
            )
            speed_cbar.set_label("Vitesse médiane (m/s)", fontsize=10)
        if delta_mesh is not None:
            delta_cbar = fig.colorbar(
                delta_mesh,
                ax=axes[2],
                location="right",
                fraction=0.035,
                pad=0.02,
            )
            delta_cbar.set_label("Écart (m/s)", fontsize=10)
        fig.suptitle(
            (
                f"{display_name} vs peloton · vitesse médiane (m/s) par distance et nage · "
                f"{nb_target} performances cible"
            ),
            fontsize=14,
            fontweight="bold",
        )
        return fig, {
            "message": "ok",
            "target_count": nb_target,
            "display_name": display_name,
        }

    def plot_temps_median_vs_meilleur_nageur_par_split_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        """Compare la vitesse médiane par segment du peloton au meilleur nageur.

        Visualisation alignée sur la littérature pacing (Robertson et al., 2009 ;
        McGibbon et al., 2018) : vitesses de segment (m/s), bande IQR peloton,
        courbe du recordman de l'épreuve. Les temps cumulés sont évités car ils
        masquent la stratégie de pacing intra-course.

        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.

        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
                Figure, stats peloton, splits du meilleur nageur et métadonnées.
        """
        event_distance = parse_event_distance_m(nom_event)
        long_df = self._get_cached_split_speed_rows(df, nom_event)
        performances_count = (
            int(long_df["swim_key"].nunique()) if not long_df.empty else 0
        )
        if long_df.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": (
                    f"Aucune vitesse de split exploitable pour "
                    f"{localize_event_string(nom_event)}."
                ),
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_VS_BEST_CHART_STYLE_VERSION,
            }

        resolved = _resolve_fastest_solo_swim_for_event(df, nom_event)
        if resolved is None:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": f"Aucune performance solo pour {localize_event_string(nom_event)}.",
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_VS_BEST_CHART_STYLE_VERSION,
            }
        swim_key, best_name, best_gender, best_swim_time = resolved
        best_rows = long_df.loc[long_df["swim_key"] == swim_key].sort_values("split_no")
        if best_rows.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": "Splits indisponibles pour le meilleur nageur de l'épreuve.",
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_VS_BEST_CHART_STYLE_VERSION,
            }

        stats = (
            long_df.groupby("split_no")["split_speed"]
            .agg(
                median="median",
                q1=lambda values: values.quantile(0.25),
                q3=lambda values: values.quantile(0.75),
                n="count",
            )
            .reset_index()
            .sort_values("split_no")
        )
        distance_by_no = (
            long_df.groupby("split_no")["split_distance"].first().astype(int).to_dict()
        )
        stats["split_distance"] = stats["split_no"].map(distance_by_no)

        fig, ax = plt.subplots(figsize=(13, 7))
        _apply_standard_chart_theme(fig, ax)
        ax.fill_between(
            stats["split_no"],
            stats["q1"],
            stats["q3"],
            color="#FDE68A",
            alpha=0.32,
            linewidth=0,
            label="IQR peloton (Q1–Q3)",
            zorder=2,
        )
        ax.plot(
            stats["split_no"],
            stats["median"],
            color=NON_CORRIDOR_COLOR_SECONDARY,
            linewidth=2.8,
            linestyle="--",
            marker="s",
            markersize=7,
            markeredgecolor="white",
            markeredgewidth=0.8,
            label="Vitesse médiane — peloton",
            zorder=5,
        )
        best_color = (
            NON_CORRIDOR_COLOR_MALE
            if best_gender == "M"
            else NON_CORRIDOR_COLOR_FEMALE
        )
        ax.plot(
            best_rows["split_no"],
            best_rows["split_speed"],
            color=best_color,
            linewidth=3.2,
            linestyle="-",
            marker="o",
            markersize=8,
            markeredgecolor="white",
            markeredgewidth=0.9,
            label=f"Meilleur nageur : {best_name} ({best_gender})",
            zorder=7,
        )

        ticks = stats["split_no"].astype(int).tolist()
        labels = _split_segment_tick_labels(ticks, distance_by_no)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        time_label = _format_swim_time_display(best_swim_time, precision=2)
        ax.set_title(
            (
                f"Vitesse par segment — peloton vs meilleur nageur\n"
                f"{localize_event_string(nom_event)} · record {time_label} ({best_name})"
            ),
            fontsize=14,
            fontweight="bold",
            pad=10,
        )
        ax.set_xlabel("Segment de course", fontsize=12)
        ax.set_ylabel("Vitesse (m/s)", fontsize=12)
        ax.grid(alpha=0.25, color="#cbd5e1")
        ax.legend(frameon=False, fontsize=10, loc="best")
        fig.tight_layout()
        return fig, stats, best_rows, {
            "message": "ok",
            "best_name": best_name,
            "best_gender": best_gender,
            "best_swim_time": best_swim_time,
            "performances_count": performances_count,
            "event_distance": event_distance,
            "chart_style_version": MEDIAN_VS_BEST_CHART_STYLE_VERSION,
        }

    def plot_temps_median_vs_top10_nageurs_par_split_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        """Compare la vitesse médiane par segment du peloton au top 10.

        Même logique que ``plot_temps_median_vs_meilleur_nageur_par_split_event`` :
        vitesses de segment (m/s), bande IQR peloton, courbe médiane des
        ``top_n`` meilleurs temps de l'épreuve (Robertson et al., 2009).

        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.

        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
                Figure, stats peloton, stats top 10 et métadonnées.
        """
        event_distance = parse_event_distance_m(nom_event)
        long_df = self._get_cached_split_speed_rows(df, nom_event)
        performances_count = (
            int(long_df["swim_key"].nunique()) if not long_df.empty else 0
        )
        if long_df.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": (
                    f"Aucune vitesse de split exploitable pour "
                    f"{localize_event_string(nom_event)}."
                ),
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
            }

        top_keys = _top_n_swim_keys_for_event(df, nom_event, top_n=10)
        if not top_keys:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": f"Aucune performance solo pour {localize_event_string(nom_event)}.",
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
            }

        top_rows = long_df.loc[long_df["swim_key"].isin(top_keys)].copy()
        if top_rows.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": "Splits indisponibles pour le top 10 de l'épreuve.",
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
            }

        stats = (
            long_df.groupby("split_no")["split_speed"]
            .agg(
                median="median",
                q1=lambda values: values.quantile(0.25),
                q3=lambda values: values.quantile(0.75),
                n="count",
            )
            .reset_index()
            .sort_values("split_no")
        )
        top_stats = (
            top_rows.groupby("split_no")["split_speed"]
            .median()
            .reset_index()
            .rename(columns={"split_speed": "median"})
            .sort_values("split_no")
        )
        distance_by_no = (
            long_df.groupby("split_no")["split_distance"].first().astype(int).to_dict()
        )
        stats["split_distance"] = stats["split_no"].map(distance_by_no)
        top_stats["split_distance"] = top_stats["split_no"].map(distance_by_no)

        fig, ax = plt.subplots(figsize=(13, 7))
        _apply_standard_chart_theme(fig, ax)
        ax.fill_between(
            stats["split_no"],
            stats["q1"],
            stats["q3"],
            color="#FDE68A",
            alpha=0.32,
            linewidth=0,
            label="IQR peloton (Q1–Q3)",
            zorder=2,
        )
        ax.plot(
            stats["split_no"],
            stats["median"],
            color=NON_CORRIDOR_COLOR_SECONDARY,
            linewidth=2.8,
            linestyle="--",
            marker="s",
            markersize=7,
            markeredgecolor="white",
            markeredgewidth=0.8,
            label="Vitesse médiane — peloton",
            zorder=5,
        )
        ax.plot(
            top_stats["split_no"],
            top_stats["median"],
            color=NON_CORRIDOR_COLOR_MALE,
            linewidth=3.2,
            linestyle="-",
            marker="o",
            markersize=8,
            markeredgecolor="white",
            markeredgewidth=0.9,
            label=f"Vitesse médiane — top {len(top_keys)} (meilleurs temps)",
            zorder=7,
        )

        ticks = stats["split_no"].astype(int).tolist()
        labels = _split_segment_tick_labels(ticks, distance_by_no)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        ax.set_title(
            (
                f"Vitesse par segment — peloton vs top {len(top_keys)}\n"
                f"{localize_event_string(nom_event)}"
            ),
            fontsize=14,
            fontweight="bold",
            pad=10,
        )
        ax.set_xlabel("Segment de course", fontsize=12)
        ax.set_ylabel("Vitesse (m/s)", fontsize=12)
        ax.grid(alpha=0.25, color="#cbd5e1")
        ax.legend(frameon=False, fontsize=10, loc="best")
        fig.tight_layout()
        return fig, stats, top_stats, {
            "message": "ok",
            "top10_count": len(top_keys),
            "performances_count": performances_count,
            "event_distance": event_distance,
            "chart_style_version": MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
        }

    def plot_vitesse_mediane_par_split_selon_genre_top_n_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
        top_n: int = 10,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
        """Compare les vitesses médianes par segment entre femmes et hommes.

        Utilise ``extract_event_split_speed_rows`` (segments complets), médiane
        et bande IQR par genre. Si ``top_n > 0``, seules les ``top_n`` meilleures
        performances par genre sont retenues (comparaison élite F vs M).

        Args:
            df (pd.DataFrame): Données de performances.
            nom_event (str): Libellé de l'épreuve.
            top_n (int): Meilleures performances par genre ; ``0`` = peloton entier.

        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
                Figure, statistiques par genre/split et métadonnées.
        """
        event_distance = parse_event_distance_m(nom_event)
        long_df = self._get_cached_split_speed_rows(df, nom_event)
        performances_count = (
            int(long_df["swim_key"].nunique()) if not long_df.empty else 0
        )
        if long_df.empty:
            return None, pd.DataFrame(), {
                "message": (
                    f"Aucune vitesse de split exploitable pour "
                    f"{localize_event_string(nom_event)}."
                ),
                "performances_count": performances_count,
                "chart_style_version": MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
            }

        work_df = long_df.copy()
        top_men = 0
        top_women = 0
        if int(top_n) > 0:
            keys_by_gender = _top_n_swim_keys_for_event_by_gender(
                df, nom_event, top_n=int(top_n)
            )
            top_men = len(keys_by_gender.get("M", []))
            top_women = len(keys_by_gender.get("F", []))
            allowed_keys = set(keys_by_gender.get("F", [])) | set(keys_by_gender.get("M", []))
            if not allowed_keys:
                return None, pd.DataFrame(), {
                    "message": f"Aucune performance solo pour {localize_event_string(nom_event)}.",
                    "performances_count": performances_count,
                    "chart_style_version": MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
                }
            work_df = work_df.loc[work_df["swim_key"].isin(allowed_keys)].copy()
            if work_df.empty:
                return None, pd.DataFrame(), {
                    "message": "Splits indisponibles pour le top par genre.",
                    "performances_count": performances_count,
                    "chart_style_version": MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
                }

        stats = (
            work_df.groupby(["Gender", "split_no"])["split_speed"]
            .agg(
                median="median",
                q1=lambda values: values.quantile(0.25),
                q3=lambda values: values.quantile(0.75),
                n="count",
            )
            .reset_index()
            .sort_values(["Gender", "split_no"])
        )
        distance_by_no = (
            work_df.groupby("split_no")["split_distance"].first().astype(int).to_dict()
        )
        stats["split_distance"] = stats["split_no"].map(distance_by_no)

        style_by_gender = {
            "F": {
                "fill": "#F6D5E8",
                "median": NON_CORRIDOR_COLOR_FEMALE,
                "label": "Femmes",
            },
            "M": {
                "fill": "#D2E8F8",
                "median": NON_CORRIDOR_COLOR_MALE,
                "label": "Hommes",
            },
        }

        fig, ax = plt.subplots(figsize=(13, 7))
        _apply_standard_chart_theme(fig, ax)
        for gender in ("F", "M"):
            data_gender = stats[stats["Gender"] == gender].sort_values("split_no")
            if data_gender.empty:
                continue
            style = style_by_gender[gender]
            ax.fill_between(
                data_gender["split_no"],
                data_gender["q1"],
                data_gender["q3"],
                color=style["fill"],
                alpha=0.32,
                linewidth=0,
                label=f"IQR {style['label']} (Q1–Q3)",
                zorder=2,
            )
            ax.plot(
                data_gender["split_no"],
                data_gender["median"],
                color=style["median"],
                linewidth=3.0,
                linestyle="-",
                marker="o",
                markersize=8,
                markeredgecolor="white",
                markeredgewidth=0.9,
                label=f"Vitesse médiane — {style['label']}",
                zorder=6,
            )

        ticks = sorted(work_df["split_no"].dropna().astype(int).unique().tolist())
        labels = _split_segment_tick_labels(ticks, distance_by_no)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        scope_label = (
            f"top {int(top_n)} par genre"
            if int(top_n) > 0
            else "peloton complet"
        )
        ax.set_title(
            (
                f"Vitesse par segment selon le genre ({scope_label})\n"
                f"{localize_event_string(nom_event)}"
            ),
            fontsize=14,
            fontweight="bold",
            pad=10,
        )
        ax.set_xlabel("Segment de course", fontsize=12)
        ax.set_ylabel("Vitesse (m/s)", fontsize=12)
        ax.grid(alpha=0.25, color="#cbd5e1")
        ax.legend(frameon=False, fontsize=10, loc="best", title="Genre")
        fig.tight_layout()
        return fig, stats, {
            "message": "ok",
            "top_men_count": top_men if int(top_n) > 0 else int(
                work_df.loc[work_df["Gender"] == "M", "swim_key"].nunique()
            ),
            "top_women_count": top_women if int(top_n) > 0 else int(
                work_df.loc[work_df["Gender"] == "F", "swim_key"].nunique()
            ),
            "performances_count": performances_count,
            "event_distance": event_distance,
            "chart_style_version": MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
        }

    def plot_relais_split_speed_par_distance(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
        """Analyse des vitesses de split en relais par segment de course.

        Nuage de points (chaque passage relais), médiane et bande IQR par segment.
        L'axe des abscisses utilise des libellés de segments (``0–50 m``, …)
        plutôt que des distances cumulées mal alignées (Robertson et al., 2009 ;
        Du & Yuan, 2021 : comparaison de distributions par segment).

        Args:
            df (pd.DataFrame): Données de performances (relais uniquement).
            nom_event (str): Libellé de l'épreuve.

        Returns:
            tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
                Figure, points bruts, moyennes et médianes par segment, métadonnées.
        """
        long_df = self._get_cached_relay_split_rows(df, nom_event)
        relay_perf_count = (
            int(long_df["relay_key"].nunique()) if not long_df.empty else 0
        )
        if long_df.empty:
            return None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {
                "message": (
                    f"Aucun split relais exploitable pour "
                    f"{localize_event_string(nom_event)}."
                ),
                "relay_perf_count": relay_perf_count,
                "chart_style_version": RELAY_SPLIT_CHART_STYLE_VERSION,
            }

        stats = (
            long_df.groupby("split_no")["split_speed"]
            .agg(
                mean="mean",
                median="median",
                q1=lambda values: values.quantile(0.25),
                q3=lambda values: values.quantile(0.75),
                n="count",
            )
            .reset_index()
            .sort_values("split_no")
        )
        distance_by_no = (
            long_df.groupby("split_no")["split_distance"].first().astype(int).to_dict()
        )
        stats["split_distance"] = stats["split_no"].map(distance_by_no)

        mean_by_dist = stats[["split_no", "split_distance", "mean"]].rename(
            columns={"mean": "split_speed"}
        )
        median_by_dist = stats[["split_no", "split_distance", "median"]].rename(
            columns={"median": "split_speed"}
        )
        df_pts = long_df.rename(columns={"split_distance": "split_distance_m"}).copy()

        fig, ax = plt.subplots(figsize=(13, 7))
        _apply_standard_chart_theme(fig, ax)
        rng = np.random.default_rng(42)
        jitter = (rng.random(len(long_df)) - 0.5) * 0.14
        ax.scatter(
            long_df["split_no"].to_numpy() + jitter,
            long_df["split_speed"].to_numpy(),
            alpha=0.22,
            s=22,
            color=NON_CORRIDOR_COLOR_PRIMARY,
            edgecolors="none",
            label="Performances relais",
            zorder=1,
        )
        ax.fill_between(
            stats["split_no"],
            stats["q1"],
            stats["q3"],
            color="#D2E8F8",
            alpha=0.45,
            linewidth=0,
            label="IQR relais (Q1–Q3)",
            zorder=2,
        )
        ax.plot(
            stats["split_no"],
            stats["median"],
            color=NON_CORRIDOR_COLOR_MALE,
            linewidth=3.0,
            linestyle="-",
            marker="s",
            markersize=8,
            markeredgecolor="white",
            markeredgewidth=0.9,
            label="Vitesse médiane — relais",
            zorder=6,
        )
        ax.plot(
            stats["split_no"],
            stats["mean"],
            color=NON_CORRIDOR_COLOR_SECONDARY,
            linewidth=2.4,
            linestyle="--",
            marker="o",
            markersize=6,
            markeredgecolor="white",
            markeredgewidth=0.7,
            label="Vitesse moyenne — relais",
            zorder=5,
        )

        ticks = stats["split_no"].astype(int).tolist()
        labels = _split_segment_tick_labels(ticks, distance_by_no)
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        ax.set_title(
            (
                f"Vitesse par segment — relais uniquement\n"
                f"{localize_event_string(nom_event)} · "
                f"{relay_perf_count:,} relais".replace(",", " ")
            ),
            fontsize=14,
            fontweight="bold",
            pad=10,
        )
        ax.set_xlabel("Segment de course", fontsize=12)
        ax.set_ylabel("Vitesse (m/s)", fontsize=12)
        ax.grid(alpha=0.25, color="#cbd5e1")
        ax.legend(frameon=False, fontsize=10, loc="best")
        fig.tight_layout()
        return fig, df_pts, mean_by_dist, median_by_dist, {
            "message": "ok",
            "relay_perf_count": relay_perf_count,
            "points_count": len(long_df),
            "chart_style_version": RELAY_SPLIT_CHART_STYLE_VERSION,
        }

    def plot_pacing_profile_normalized_corridor(
        self,
        df: pd.DataFrame,
        nom_event: str,
        nom_nageur: Optional[str] = None,
        year_of_birth: Optional[int] = None,
        min_points: int = 5,
        figsize: tuple[int, int] = (12, 8),
        overlay_nageur: Optional[str] = None,
        overlay_year_of_birth: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
        gender_filter: Optional[str] = None,
        swimmer_specs: Optional[List[CorridorSwimmerSpec]] = None,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        """Profil de pacing normalisé : couloir percentile + courbe(s) nageur(s).

        Le groupe de référence (France/USA) est affiché en bandes P10–P90 et
        P25–P75 avec la médiane. Chaque nageur cible est tracé en ligne, sa
        vitesse par split étant exprimée en % de sa vitesse moyenne sur la nage.

        Args:
            df (pd.DataFrame): Peloton de référence (Extranat ou USA Swimming).
            nom_event (str): Libellé de l'épreuve.
            nom_nageur (Optional[str]): Nageur cible principal (legacy UI).
            year_of_birth (Optional[int]): Année de naissance du nageur principal.
            min_points (int): Effectif minimal par split pour le couloir.
            figsize (tuple[int, int]): Taille de la figure matplotlib.
            overlay_nageur (Optional[str]): Nageur de surcouche (ex. marocain).
            overlay_year_of_birth (Optional[int]): Année de naissance overlay.
            overlay_df (Optional[pd.DataFrame]): Performances supplémentaires (MAR).
            gender_filter (Optional[str]): Filtre F/M sur le peloton de référence.
            swimmer_specs (Optional[List[CorridorSwimmerSpec]]): Nageurs à tracer.

        Returns:
            tuple[Optional[plt.Figure], dict[str, object]]: Figure et métadonnées.
        """
        ref_splits = extract_event_split_speed_rows(df, nom_event)
        if ref_splits.empty:
            event_distance = parse_event_distance_m(nom_event)
            if event_distance is not None and event_distance <= 50:
                message = (
                    f"Aucune performance avec splits intermédiaires pour {nom_event}. "
                    "Le 50 m n'est pas couvert par les splits Extranat/USA : "
                    "choisir une distance ≥ 100 m ou le couloir âge × temps."
                )
            else:
                message = (
                    f"Aucune performance avec splits complets pour {nom_event}"
                )
            return None, {"message": message}

        plot_parts: List[pd.DataFrame] = [ref_splits]
        if overlay_df is not None and not overlay_df.empty:
            extra = extract_event_split_speed_rows(overlay_df, nom_event)
            if not extra.empty:
                plot_parts.append(extra)
        plot_splits = pd.concat(plot_parts, ignore_index=True).drop_duplicates(
            subset=["swim_key", "split_no"], keep="first"
        )

        specs = merge_corridor_swimmer_specs_for_plot(
            swimmer_specs,
            nom_nageur=nom_nageur,
            year_of_birth=year_of_birth,
            overlay_nageur=overlay_nageur,
            overlay_year_of_birth=overlay_year_of_birth,
            overlay_label=CORRIDOR_OVERLAY_SWIMMER_LABEL,
        )
        gender = resolve_corridor_plot_gender(plot_splits, gender_filter, specs)
        if gender in ("F", "M"):
            ref_splits = ref_splits[
                ref_splits["Gender"].astype(str).str.strip().str.upper() == gender
            ].copy()
            plot_splits = plot_splits[
                plot_splits["Gender"].astype(str).str.strip().str.upper() == gender
            ].copy()

        ref_splits = exclude_corridor_swimmer_specs_from_df(ref_splits, specs)
        ref_norm = add_within_swim_speed_pct(ref_splits)
        if ref_norm.empty:
            return None, {
                "message": "Impossible de normaliser les profils du groupe de référence.",
                "gender": gender,
            }

        percentiles = STANDARD_CORRIDOR_PERCENTILES
        df_percentiles = compute_group_percentiles_df(
            ref_norm,
            "split_distance",
            "speed_pct",
            percentiles,
            min_points=min_points,
        )
        if df_percentiles is None or df_percentiles.empty:
            return None, {
                "message": "Pas assez de points par split pour calculer le couloir.",
                "gender": gender,
            }

        plot_norm = add_within_swim_speed_pct(plot_splits)

        fig, ax = plt.subplots(figsize=figsize)
        draw_percentile_corridor_bands(
            ax,
            df_percentiles.index,
            df_percentiles,
            outer_label_below="Référence sous médiane (P10–P50)",
            outer_label_above="Référence au-dessus médiane (P50–P90)",
            inner_label_below="Référence P25–P50",
            inner_label_above="Référence P50–P75",
            median_label="Médiane du groupe de référence",
        )
        trace_messages = plot_normalized_pacing_profiles_on_ax(ax, plot_norm, specs)

        ticks = [int(x) for x in df_percentiles.index.tolist()]
        ax.set_xticks(ticks)
        ax.set_xticklabels([f"{t} m" for t in ticks])
        ax.axhline(
            100.0,
            color=CORRIDOR_REFERENCE_LINE_COLOR,
            linewidth=1.0,
            linestyle=":",
            zorder=0,
            label="Vitesse moyenne de la nage (100 %)",
        )
        ax.set_xlabel("Segment de nage")
        ax.set_ylabel("Vitesse normalisée (% de la vitesse moyenne de la nage)")
        title_event = localize_event_string(nom_event)
        ref_swims = int(ref_norm["swim_key"].nunique())
        _apply_corridor_consistent_styling(
            fig,
            ax,
            title=f"Profil de pacing normalisé — {title_event}",
            gender=gender,
            reference_count=ref_swims,
            legend_fontsize=9,
        )
        mono_segment_msg: Optional[str] = None
        if len(ticks) <= 1:
            mono_segment_msg = (
                "Épreuve mono-segment (25/50 m) : le profil normalisé se réduit "
                "à un point proche de 100 %."
            )
            ax.text(
                0.5,
                0.05,
                mono_segment_msg,
                transform=ax.transAxes,
                ha="center",
                va="bottom",
                fontsize=9,
                color=CORRIDOR_ANNOTATION_COLOR,
                bbox={
                    "boxstyle": "round,pad=0.3",
                    "facecolor": "#ffffff",
                    "edgecolor": "#cbd5e1",
                    "alpha": 0.92,
                },
            )
        fig.tight_layout()

        meta: dict[str, object] = {
            "message": "ok",
            "gender": gender,
            "splits_available": ticks,
            "reference_swims": int(ref_norm["swim_key"].nunique()),
            "swimmer_trace_messages": trace_messages,
        }
        if mono_segment_msg:
            meta["mono_segment_message"] = mono_segment_msg
        if trace_messages:
            meta["overlay_swimmer_message"] = "; ".join(trace_messages)
        return fig, meta

    def plot_performance_corridor_plot_time(
        self,
        df: pd.DataFrame,
        nom_event: str,
        nom_nageur: Optional[str] = None,
        year_of_birth: Optional[int] = None,
        age_min: int = 14,
        age_max: int = 35,
        solo_only: bool = True,
        min_points: int = 5,
        figsize: tuple[int, int] = (12, 8),
        overlay_nageur: Optional[str] = None,
        overlay_year_of_birth: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
        gender_filter: Optional[str] = None,
        swimmer_specs: Optional[List[CorridorSwimmerSpec]] = None,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        """Couloir de performance âge × temps pour une épreuve avec nageur(s) cible(s).

        Args:
            df (pd.DataFrame): Données de référence Extranat/USA.
            nom_event (str): Libellé de l'épreuve.
            nom_nageur (Optional[str]): Nageur cible à superposer (legacy).
            year_of_birth (Optional[int]): Année de naissance du nageur cible.
            age_min (int): Âge minimum du couloir.
            age_max (int): Âge maximum du couloir.
            solo_only (bool): Ne garder que les nages individuelles.
            min_points (int): Minimum de points par âge pour les percentiles.
            figsize (tuple[int, int]): Taille de la figure.
            overlay_nageur (Optional[str]): Nageur de surcouche (ex. marocain).
            overlay_year_of_birth (Optional[int]): Année de naissance de surcouche.
            overlay_df (Optional[pd.DataFrame]): Performances supplémentaires.
            gender_filter (Optional[str]): Filtre F/M ou None.
            swimmer_specs (Optional[List[CorridorSwimmerSpec]]): Nageurs à tracer.

        Returns:
            tuple[Optional[plt.Figure], dict[str, object]]: Figure et métadonnées du couloir.
        """
        long_ref = prepare_corridor_long_df(
            df, nom_event, solo_only=solo_only, require_name=False
        )
        if long_ref.empty:
            return None, {"message": f"Aucune donnee pour {nom_event}"}

        long_plot = prepare_corridor_long_df_combined(
            df, nom_event, df_extra=overlay_df, solo_only=solo_only
        )
        specs = merge_corridor_swimmer_specs_for_plot(
            swimmer_specs,
            nom_nageur=nom_nageur,
            year_of_birth=year_of_birth,
            overlay_nageur=overlay_nageur,
            overlay_year_of_birth=overlay_year_of_birth,
            overlay_label=CORRIDOR_OVERLAY_SWIMMER_LABEL,
        )
        gender = resolve_corridor_plot_gender(long_plot, gender_filter, specs)
        if gender in ("F", "M"):
            long_ref = filter_corridor_long_df_gender(long_ref, gender)
            long_plot = filter_corridor_long_df_gender(long_plot, gender)

        long_ref = exclude_corridor_swimmer_specs_from_df(long_ref, specs)

        swimmer_frames: List[pd.DataFrame] = []
        for spec in specs:
            df_s, _, _ = resolve_corridor_swimmer_flexible(
                long_plot, spec.name, spec.year_of_birth
            )
            if not df_s.empty:
                swimmer_frames.append(df_s)

        age_lo, age_hi = corridor_age_limits(
            long_ref, swimmer_frames, default_min=age_min, default_max=age_max
        )

        percentiles = STANDARD_CORRIDOR_PERCENTILES
        df_percentiles = compute_corridor_percentiles_df(
            long_ref,
            percentiles,
            age_min=age_lo,
            age_max=age_hi,
            min_points=min_points,
        )
        if df_percentiles is None or df_percentiles.empty:
            return None, {
                "message": "Pas assez de points pour calculer les percentiles.",
                "gender": gender,
            }

        fig, ax = plt.subplots(figsize=figsize)
        draw_percentile_corridor_bands(ax, df_percentiles.index, df_percentiles)
        trace_messages = plot_corridor_swimmer_specs(
            ax, long_plot, specs, source_df=df, nom_event=nom_event
        )
        ax.invert_yaxis()
        ax.set_xlabel("Âge")
        ax.set_ylabel("Temps (secondes)")
        _apply_corridor_consistent_styling(
            fig,
            ax,
            title=f"Couloir de performance — {localize_event_string(nom_event)}",
            gender=gender,
            reference_count=int(long_ref["SwimTimeSeconds"].notna().sum()),
            legend_fontsize=9,
        )
        fig.tight_layout()

        meta: dict[str, object] = {
            "message": "ok",
            "gender": gender,
            "ages_available": [int(x) for x in df_percentiles.index.tolist()],
            "age_min_used": age_lo,
            "age_max_used": age_hi,
            "swimmer_trace_messages": trace_messages,
        }
        if specs and trace_messages:
            meta["overlay_swimmer_message"] = "; ".join(trace_messages)
        return fig, meta

    def plot_performance_corridor_global_plot_time(
        self,
        df: pd.DataFrame,
        nom_event: str,
        age_min: int = 14,
        age_max: int = 35,
        solo_only: bool = True,
        min_points: int = 5,
        figsize: tuple[int, int] = (12, 8),
        overlay_nageur: Optional[str] = None,
        overlay_year_of_birth: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
        gender_filter: Optional[str] = None,
        swimmer_specs: Optional[List[CorridorSwimmerSpec]] = None,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        """Couloir global âge × temps (percentiles 10–90) avec overlays nageurs.
        
        Args:
            df (pd.DataFrame): Données de référence.
            nom_event (str): Libellé de l'épreuve.
            age_min (int): Âge minimum du couloir.
            age_max (int): Âge maximum du couloir.
            solo_only (bool): Ne garder que les nages individuelles.
            min_points (int): Minimum de points par âge pour les percentiles.
            figsize (tuple[int, int]): Taille de la figure.
            overlay_nageur (Optional[str]): Nageur de surcouche (legacy).
            overlay_year_of_birth (Optional[int]): Année de naissance de surcouche.
            overlay_df (Optional[pd.DataFrame]): Performances supplémentaires.
            gender_filter (Optional[str]): Filtre F/M ou None.
            swimmer_specs (Optional[List[CorridorSwimmerSpec]]): Nageurs à tracer.
        
        Returns:
            tuple[Optional[plt.Figure], dict[str, object]]: Figure et métadonnées.
        """
        long_ref = prepare_corridor_long_df(
            df, nom_event, solo_only=solo_only, require_name=False
        )
        if long_ref.empty:
            return None, {"message": f"Aucune donnee exploitable pour {nom_event}"}

        long_plot = prepare_corridor_long_df_combined(
            df, nom_event, df_extra=overlay_df, solo_only=solo_only
        )
        specs = merge_corridor_swimmer_specs_for_plot(
            swimmer_specs,
            overlay_nageur=overlay_nageur,
            overlay_year_of_birth=overlay_year_of_birth,
            overlay_label=CORRIDOR_OVERLAY_SWIMMER_LABEL,
        )
        gender = resolve_corridor_plot_gender(long_plot, gender_filter, specs)
        if gender in ("F", "M"):
            long_ref = filter_corridor_long_df_gender(long_ref, gender)
            long_plot = filter_corridor_long_df_gender(long_plot, gender)

        long_ref = exclude_corridor_swimmer_specs_from_df(long_ref, specs)

        swimmer_frames: List[pd.DataFrame] = []
        for spec in specs:
            df_s, _, _ = resolve_corridor_swimmer_flexible(
                long_plot, spec.name, spec.year_of_birth
            )
            if not df_s.empty:
                swimmer_frames.append(df_s)

        age_lo, age_hi = corridor_age_limits(
            long_ref, swimmer_frames, default_min=age_min, default_max=age_max
        )

        percentiles = STANDARD_CORRIDOR_PERCENTILES
        df_percentiles = compute_corridor_percentiles_df(
            long_ref,
            percentiles,
            age_min=age_lo,
            age_max=age_hi,
            min_points=min_points,
        )
        if df_percentiles is None or df_percentiles.empty:
            return None, {
                "message": "Aucune tranche d'age disponible sur la plage demandee.",
                "gender": gender,
            }

        fig, ax = plt.subplots(figsize=figsize)
        draw_percentile_corridor_bands(ax, df_percentiles.index, df_percentiles)
        trace_messages = plot_corridor_swimmer_specs(
            ax, long_plot, specs, source_df=df, nom_event=nom_event
        )
        ax.invert_yaxis()
        ax.set_xlabel("Âge")
        ax.set_ylabel("Temps (secondes)")
        _apply_corridor_consistent_styling(
            fig,
            ax,
            title=f"Couloir de performance global — {localize_event_string(nom_event)}",
            gender=gender,
            reference_count=int(long_ref["SwimTimeSeconds"].notna().sum()),
            legend_fontsize=9,
        )
        fig.tight_layout()

        meta: dict[str, object] = {
            "message": "ok",
            "gender": gender,
            "event": str(nom_event),
            "ages_available": [int(x) for x in df_percentiles.index.tolist()],
            "points_count": int(len(long_ref)),
            "age_min_used": age_lo,
            "age_max_used": age_hi,
            "swimmer_trace_messages": trace_messages,
        }
        if trace_messages:
            meta["overlay_swimmer_message"] = "; ".join(trace_messages)
        return fig, meta

    _DEFAULT_AGEGROUP_ORDER: Tuple[str, ...] = (
        "10 & Under",
        "11-12",
        "13-14",
        "15-18",
        "19 & Over",
        "Not Applicable",
    )

    def plot_performance_corridor_global_by_agegroup(
        self,
        df: pd.DataFrame,
        nom_event: str,
        nom_nageur: Optional[str] = None,
        year_of_birth: Optional[int] = None,
        gender: Optional[str] = None,
        min_points: int = 5,
        agegroup_order: Optional[List[str]] = None,
        figsize: tuple[int, int] = (12, 8),
        overlay_nageur: Optional[str] = None,
        overlay_year_of_birth: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        """Couloir de performance global : SwimTimeSeconds vs AgeGroup (catégories USA Swimming)."""
        required_cols = ["Event", "SwimTimeSeconds", "AgeGroup"]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return None, {"message": f"Colonnes manquantes: {', '.join(missing_cols)}"}

        optional_cols = [c for c in ("Gender", "Name", "Year_of_birth") if c in df.columns]
        data = df.loc[:, required_cols + optional_cols].copy()
        data["AgeGroup"] = (
            data["AgeGroup"].fillna("").astype(str).str.strip()
        )
        data = data[
            (data["Event"] == nom_event)
            & (data["SwimTimeSeconds"].notna())
            & (data["AgeGroup"] != "")
        ].copy()
        if data.empty:
            return None, {"message": f"Aucune donnee exploitable pour {nom_event}"}

        if gender is not None and "Gender" in data.columns:
            gender_filter = str(gender).strip().upper()
            data["Gender"] = data["Gender"].astype(str).str.strip().str.upper()
            data = data[data["Gender"] == gender_filter].copy()
            if data.empty:
                return None, {"message": f"Aucune performance pour le genre {gender_filter}."}

        grouped = data.groupby("AgeGroup")["SwimTimeSeconds"].agg(list)
        grouped = grouped.apply(lambda x: x if len(x) >= min_points else np.nan).dropna()
        if grouped.empty:
            return None, {
                "message": "Pas assez de points par AgeGroup pour calculer les percentiles.",
            }

        percentiles = STANDARD_CORRIDOR_PERCENTILES
        df_percentiles = pd.DataFrame(
            {f"p{p}": grouped.apply(lambda x: np.percentile(x, p)) for p in percentiles}
        )

        order = list(agegroup_order or self._DEFAULT_AGEGROUP_ORDER)
        extra_groups = [g for g in df_percentiles.index if g not in order]
        ordered_index = [g for g in order if g in df_percentiles.index] + sorted(extra_groups)
        df_percentiles = df_percentiles.loc[ordered_index]
        if df_percentiles.empty:
            return None, {"message": "Aucun AgeGroup disponible apres filtrage."}

        x_positions = np.arange(len(df_percentiles))
        fig, ax = plt.subplots(figsize=figsize)
        draw_percentile_corridor_bands(ax, x_positions, df_percentiles)

        meta: dict[str, object] = {
            "message": "ok",
            "event": str(nom_event),
            "agegroups_available": ordered_index,
            "points_count": int(len(data)),
        }

        if nom_nageur and "Name" in data.columns:
            name_mask = data["Name"].astype(str).str.strip() == str(nom_nageur).strip()
            if year_of_birth is not None and "Year_of_birth" in data.columns:
                yob_series = pd.to_numeric(data["Year_of_birth"], errors="coerce")
                name_mask = name_mask & (yob_series == int(year_of_birth))
            swimmer_data = data[name_mask].copy()
            if not swimmer_data.empty:
                swimmer_curve = swimmer_data.groupby("AgeGroup")["SwimTimeSeconds"].mean()
                swimmer_curve = swimmer_curve.reindex(ordered_index).dropna()
                if not swimmer_curve.empty:
                    swimmer_x = [ordered_index.index(ag) for ag in swimmer_curve.index]
                    ax.plot(
                        swimmer_x,
                        swimmer_curve.values,
                        color="red",
                        linewidth=2.5,
                        marker="o",
                        label="Nageur cible (moyenne)",
                        zorder=4,
                    )
                    meta["swimmer_name"] = str(swimmer_data.iloc[0]["Name"]).strip()
                    if year_of_birth is not None:
                        meta["year_of_birth"] = int(year_of_birth)
                    meta["points_swimmer"] = int(len(swimmer_data))
                else:
                    meta["swimmer_message"] = (
                        f"Nageur trouve ({len(swimmer_data)} perf.) "
                        "mais aucun AgeGroup exploitable pour la courbe."
                    )
            else:
                meta["swimmer_message"] = f"Nageur introuvable : {nom_nageur}"

        if overlay_nageur and overlay_year_of_birth is not None:
            src = overlay_df if overlay_df is not None else df
            if "Event" in src.columns:
                overlay_src = src[
                    (src["Event"].astype(str).str.strip() == str(nom_event).strip())
                    & (src["SwimTimeSeconds"].notna())
                ].copy()
            else:
                overlay_src = src
            if gender is not None and "Gender" in overlay_src.columns:
                gender_filter = str(gender).strip().upper()
                overlay_src["Gender"] = (
                    overlay_src["Gender"].astype(str).str.strip().str.upper()
                )
                overlay_src = overlay_src[overlay_src["Gender"] == gender_filter]
            name_mask = overlay_src["Name"].astype(str).str.strip() == str(
                overlay_nageur
            ).strip()
            if overlay_year_of_birth is not None and "Year_of_birth" in overlay_src.columns:
                yob_series = pd.to_numeric(overlay_src["Year_of_birth"], errors="coerce")
                name_mask = name_mask & (yob_series == int(overlay_year_of_birth))
            elif "Year_of_birth" in overlay_src.columns:
                yob_series = pd.to_numeric(overlay_src["Year_of_birth"], errors="coerce")
                if yob_series.notna().any():
                    best_yob = int(yob_series.loc[name_mask].mode().iloc[0])
                    name_mask = name_mask & (yob_series == best_yob)
            swimmer_overlay = overlay_src[name_mask].copy()
            if not swimmer_overlay.empty:
                swimmer_curve = swimmer_overlay.groupby("AgeGroup")[
                    "SwimTimeSeconds"
                ].mean()
                swimmer_curve = swimmer_curve.reindex(ordered_index).dropna()
                if not swimmer_curve.empty:
                    swimmer_x = [ordered_index.index(ag) for ag in swimmer_curve.index]
                    ax.plot(
                        swimmer_x,
                        swimmer_curve.values,
                        color=CORRIDOR_OVERLAY_SWIMMER_COLOR,
                        linewidth=2.5,
                        marker="s",
                        label=CORRIDOR_OVERLAY_SWIMMER_LABEL,
                        zorder=4,
                    )
                    meta["overlay_swimmer_name"] = str(
                        swimmer_overlay.iloc[0]["Name"]
                    ).strip()
                    meta["overlay_points_swimmer"] = int(len(swimmer_overlay))
                else:
                    meta["overlay_swimmer_message"] = (
                        f"Nageur marocain trouve ({len(swimmer_overlay)} perf.) "
                        "mais aucun AgeGroup exploitable pour la courbe."
                    )
            else:
                meta["overlay_swimmer_message"] = (
                    f"Nageur marocain introuvable : {overlay_nageur}"
                )

        ax.set_xticks(x_positions)
        ax.set_xticklabels(ordered_index, rotation=20, ha="right")
        ax.invert_yaxis()
        ax.set_xlabel("Catégorie d'âge")
        ax.set_ylabel("Temps (secondes)")
        _apply_corridor_consistent_styling(
            fig,
            ax,
            title=(
                "Couloir de performance global (catégorie d'âge) — "
                f"{localize_event_string(nom_event)}"
            ),
            gender=gender,
            reference_count=int(len(data)),
            legend_fontsize=9,
        )
        fig.tight_layout()

        return fig, meta

    def plot_performance_corridor_global_deciles_plot_time(
        self,
        df: pd.DataFrame,
        nom_event: str,
        nom_nageur: Optional[str] = None,
        year_of_birth: Optional[int] = None,
        age_min: int = 14,
        age_max: int = 35,
        solo_only: bool = True,
        min_points: int = 5,
        figsize: tuple[int, int] = (12, 8),
        overlay_nageur: Optional[str] = None,
        overlay_year_of_birth: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
        gender_filter: Optional[str] = None,
        swimmer_specs: Optional[List[CorridorSwimmerSpec]] = None,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        """Couloir global avec 10 bandes déciles (10 % du peloton chacune).

        Chaque décile est matérialisé par une bande colorée entre les bornes
        min/P10, P10/P20, …, P90/max. La médiane (P50, décile 5) est tracée
        en ligne. Les nageurs cibles confirmés peuvent être superposés.

        Args:
            df (pd.DataFrame): Données de référence.
            nom_event (str): Libellé de l'épreuve.
            nom_nageur (Optional[str]): Nageur cible (legacy).
            year_of_birth (Optional[int]): Année de naissance du nageur cible.
            age_min (int): Âge minimum du couloir.
            age_max (int): Âge maximum du couloir.
            solo_only (bool): Ne garder que les nages individuelles.
            min_points (int): Minimum de points par âge.
            figsize (tuple[int, int]): Taille de la figure.
            overlay_nageur (Optional[str]): Nageur de surcouche.
            overlay_year_of_birth (Optional[int]): Année de naissance de surcouche.
            overlay_df (Optional[pd.DataFrame]): Performances supplémentaires.
            gender_filter (Optional[str]): Filtre F/M ou None.
            swimmer_specs (Optional[List[CorridorSwimmerSpec]]): Nageurs à tracer.
        
        Returns:
            tuple[Optional[plt.Figure], dict[str, object]]: Figure et métadonnées.
        """
        long_ref = prepare_corridor_long_df(
            df, nom_event, solo_only=solo_only, require_name=False
        )
        if long_ref.empty:
            return None, {"message": f"Aucune donnee exploitable pour {nom_event}"}

        long_plot = prepare_corridor_long_df_combined(
            df, nom_event, df_extra=overlay_df, solo_only=solo_only
        )
        specs = merge_corridor_swimmer_specs_for_plot(
            swimmer_specs,
            nom_nageur=nom_nageur,
            year_of_birth=year_of_birth,
            overlay_nageur=overlay_nageur,
            overlay_year_of_birth=overlay_year_of_birth,
            overlay_label=CORRIDOR_OVERLAY_SWIMMER_LABEL,
        )
        gender = resolve_corridor_plot_gender(long_plot, gender_filter, specs)
        if gender in ("F", "M"):
            long_ref = filter_corridor_long_df_gender(long_ref, gender)
            long_plot = filter_corridor_long_df_gender(long_plot, gender)

        long_ref = exclude_corridor_swimmer_specs_from_df(long_ref, specs)

        swimmer_frames: List[pd.DataFrame] = []
        for spec in specs:
            df_s, _, _ = resolve_corridor_swimmer_flexible(
                long_plot, spec.name, spec.year_of_birth, fuzzy_min_ratio=0.85
            )
            if not df_s.empty:
                swimmer_frames.append(df_s)

        age_lo, age_hi = corridor_age_limits(
            long_ref, swimmer_frames, default_min=age_min, default_max=age_max
        )

        df_deciles = compute_corridor_deciles_df(
            long_ref,
            age_min=age_lo,
            age_max=age_hi,
            min_points=min_points,
        )
        if df_deciles is None or df_deciles.empty:
            return None, {
                "message": "Aucune tranche d'age disponible sur la plage demandee.",
                "gender": gender,
            }

        fig, ax = plt.subplots(figsize=figsize)
        draw_decile_corridor_bands(ax, df_deciles.index, df_deciles)

        trace_messages = plot_corridor_swimmer_specs(
            ax,
            long_plot,
            specs,
            fuzzy_min_ratio=0.85,
            source_df=df,
            nom_event=nom_event,
        )

        ax.invert_yaxis()
        ax.set_xlabel("Âge")
        ax.set_ylabel("Temps (secondes)")
        _apply_corridor_consistent_styling(
            fig,
            ax,
            title=(
                "Couloir de performance global (10 déciles) — "
                f"{localize_event_string(nom_event)}"
            ),
            gender=gender,
            reference_count=int(long_ref["SwimTimeSeconds"].notna().sum()),
            legend_fontsize=8,
        )
        fig.tight_layout()

        return fig, {
            "message": "ok",
            "gender": gender,
            "event": str(nom_event),
            "ages_available": [int(x) for x in df_deciles.index.tolist()],
            "points_count": int(len(long_ref)),
            "percentiles": list(DECILE_CORRIDOR_PERCENTILES),
            "age_min_used": age_lo,
            "age_max_used": age_hi,
            "swimmer_trace_messages": trace_messages,
            "overlay_swimmer_message": (
                "; ".join(trace_messages) if trace_messages else None
            ),
        }

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
        """Construit la figure pour le menu desktop Flet (noms tels que dans ``GRAPH_CATEGORIES``)."""
        fig: Optional[plt.Figure] = None
        chart_title = selected_graph
        svc = self
        corridor_df = (
            corridor_reference_df
            if corridor_reference_df is not None and not corridor_reference_df.empty
            else df
        )
        if corridor_plot_kwargs is not None:
            overlay_kwargs = dict(corridor_plot_kwargs)
        else:
            gender = corridor_gender_filter
            if gender not in ("F", "M"):
                gender = None
            overlay_kwargs = build_corridor_chart_plot_kwargs(
                gender_filter=gender,
                french_name=selected_corridor_swimmer_name,
                french_yob=selected_corridor_swimmer_yob,
                moroccan_name=moroccan_corridor_swimmer_name,
                moroccan_yob=moroccan_corridor_swimmer_yob,
                moroccan_df=moroccan_corridor_df,
            )

        if selected_graph in {
            "Histogramme simple",
            "Histogramme cumulatif",
        }:
            chart_title = "Distribution des temps de nage"
            if not df_filtered.empty:
                if selected_graph == "Histogramme simple":
                    fig = svc.plot_histogramme_simple(df_filtered)
                else:
                    fig = svc.plot_histogramme_cumulatif(df_filtered)

        elif selected_graph == GRAPH_NOMBRE_PERF_EPREUVE:
            sort_by_total = event_counts_sort == EVENT_COUNTS_SORT_TOTAL_DESC
            if pool and stroke:
                stroke_label = stroke_code_to_label(stroke)
                chart_title = (
                    f"Nombre de performances par épreuve — {stroke_label} ({pool})"
                )
                fig = svc.plot_nombre_performances_par_epreuve(
                    df_scope,
                    course_type=str(pool),
                    sort_by_total=sort_by_total,
                )

        elif selected_graph == GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM:
            sort_by_total = event_counts_sort == EVENT_COUNTS_SORT_TOTAL_DESC
            if stroke:
                stroke_label = stroke_code_to_label(stroke)
                chart_title = (
                    f"Nombre de performances par épreuve (LCM + SCM) — {stroke_label}"
                )
            else:
                chart_title = "Nombre de performances par épreuve (LCM + SCM)"
            fig = svc.plot_nombre_performances_par_epreuve_lcm_scm(
                df_scope,
                sort_by_total=sort_by_total,
            )

        elif selected_graph in {"Comptage par sexe (global)", "Comptage par sexe (épreuve)"}:
            chart_title = (
                "Nombre de performances par sexe – global"
                if selected_graph == "Comptage par sexe (global)"
                else "Nombre de performances par sexe – filtres actuels"
            )
            fig = svc.plot_nombre_performances_par_sexe(df_filtered, title=chart_title)

        elif selected_graph == "Camembert par sexe (global)":
            chart_title = "Répartition globale par sexe"
            fig = svc.plot_camembert_sexe_global(df_filtered, title=chart_title)

        elif selected_graph == "Camembert par sexe (épreuve)":
            chart_title = "Proportion des performances par sexe – filtres actuels"
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                fig = svc.plot_camembert_sexe_par_event(
                    df_filtered,
                    nom_event=nom_event,
                    title=chart_title,
                )

        elif selected_graph == "Distribution des temps par type de nage (boxplot)":
            try:
                distance_label = (
                    str(int(float(selected_distance)))
                    if selected_distance is not None
                    else ""
                )
            except (TypeError, ValueError):
                distance_label = str(selected_distance)
            chart_title = (
                f"Distribution des temps par type de nage pour la distance {distance_label} m"
            )
            fig = svc.plot_boxplot_temps_par_nage(df_scope, title=chart_title)

        elif selected_graph == "Top 10 clubs par participation (épreuve)":
            if distance and stroke and pool:
                chart_title = (
                    f"Top 10 des clubs – {format_event_label(distance, stroke, pool)}"
                )
            else:
                chart_title = "Top 10 des clubs par nombre de participations – filtres actuels"
            fig = svc.plot_top10_clubs(df_scope, title=chart_title)

        elif selected_graph == "Temps médian des 10 meilleurs clubs":
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = f"Temps médian des 10 meilleurs clubs - {format_event_label(distance, stroke, pool)}"
                fig, _meta = svc.plot_temps_median_top10_clubs_par_event(
                    df_scope, nom_event=nom_event, title=chart_title
                )

        elif selected_graph == GRAPH_CHRONOS_PAR_NAGE:
            chart_title = "Évolution des temps médians par nage (à partir de 2000)"
            fig = svc.plot_evolution_temps_nage(
                df,
                start_year=2000,
                sample_size=max(0, int(selected_chronos_sample_size)),
                title=chart_title,
            )

        elif selected_graph == GRAPH_VITESSE_DISTANCE_NAGE:
            chart_title = "Vitesse médiane par distance et type de nage"
            fig = svc.plot_swimming_speed_by_distance_and_stroke(
                df_scope,
                title=chart_title,
            )

        elif selected_graph == GRAPH_VITESSE_MAX_SPLIT_NAGE:
            chart_title = GRAPH_VITESSE_MAX_SPLIT_NAGE
            fig, _dfm = svc.plot_vitesse_max_par_split_et_nage(df_scope)

        elif selected_graph == "Vitesse de split - F vs M + nageurs cibles":
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = (
                    f"{format_event_label(distance, stroke, pool)} - vitesse de split - F vs M + nageurs cibles"
                )
                pacing = selected_pacing_swimmers[:3]
                target_colors: Dict[str, str] = {}
                if pacing:
                    pal = sns.color_palette("Dark2", n_colors=len(pacing))
                    target_colors = {n: to_hex(c) for n, c in zip(pacing, pal)}
                fig, _a, _b, meta = svc.plot_split_speed_analysis_by_gender_with_targets(
                    df_scope,
                    nom_event=nom_event,
                    swimmer_targets=list(pacing),
                    target_colors=target_colors,
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err and err != "ok":
                        chart_title = err

        elif selected_graph == MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME:
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = (
                    f"Vitesse par segment — peloton vs meilleur nageur · "
                    f"{format_event_label(distance, stroke, pool)}"
                )
                fig, _a, _b, meta = svc.plot_temps_median_vs_meilleur_nageur_par_split_event(
                    df_scope, nom_event=nom_event
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err and err != "ok":
                        chart_title = err
                elif isinstance(meta, dict) and meta.get("message") == "ok":
                    best_name = meta.get("best_name")
                    best_time = meta.get("best_swim_time")
                    if isinstance(best_name, str) and best_name.strip():
                        if isinstance(best_time, (int, float)):
                            time_label = _format_swim_time_display(
                                float(best_time), precision=2
                            )
                            chart_title = (
                                f"Vitesse par segment — {format_event_label(distance, stroke, pool)} "
                                f"· record {time_label} ({best_name.strip()})"
                            )

        elif selected_graph == MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME:
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = (
                    f"Vitesse par segment — peloton vs top 10 · "
                    f"{format_event_label(distance, stroke, pool)}"
                )
                fig, _a, _b, meta = svc.plot_temps_median_vs_top10_nageurs_par_split_event(
                    df_scope, nom_event=nom_event
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err and err != "ok":
                        chart_title = err
                elif isinstance(meta, dict) and meta.get("message") == "ok":
                    top_count = meta.get("top10_count")
                    if isinstance(top_count, int) and top_count > 0:
                        chart_title = (
                            f"Vitesse par segment — peloton vs top {top_count} · "
                            f"{format_event_label(distance, stroke, pool)}"
                        )

        elif selected_graph == MEDIAN_SPEED_BY_GENDER_GRAPH_NAME:
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = (
                    f"Vitesse par segment selon le genre · "
                    f"{format_event_label(distance, stroke, pool)}"
                )
                fig, _med, meta = svc.plot_vitesse_mediane_par_split_selon_genre_top_n_event(
                    df_scope, nom_event=nom_event, top_n=10
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err and err != "ok":
                        chart_title = err
                elif isinstance(meta, dict) and meta.get("message") == "ok":
                    chart_title = (
                        f"Vitesse par segment F/M (top 10) · "
                        f"{format_event_label(distance, stroke, pool)}"
                    )

        elif selected_graph == "Heatmap vitesse moyenne (distance x nage)":
            chart_title = "Synthèse des vitesses – heatmap comparative"
            if selected_heatmap_swimmer:
                fig, meta = svc.plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres(
                    df_scope,
                    nageur_cible=selected_heatmap_swimmer,
                )
                if isinstance(meta, dict):
                    if meta.get("message") == "ok" and meta.get("display_name"):
                        chart_title = (
                            f"Synthèse des vitesses – {meta['display_name']} vs peloton"
                        )
                    else:
                        err = str(meta.get("message", ""))
                        if err and err != "ok":
                            chart_title = err

        elif selected_graph == "Couloir de performance (âge) - nageur cible":
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                fr_name = selected_corridor_swimmer_name
                fr_yob = selected_corridor_swimmer_yob
                has_fr = isinstance(fr_name, str) and fr_name.strip()
                has_ma = (
                    isinstance(moroccan_corridor_swimmer_name, str)
                    and moroccan_corridor_swimmer_name.strip()
                    and moroccan_corridor_df is not None
                    and not moroccan_corridor_df.empty
                )
                has_specs = bool(overlay_kwargs.get("swimmer_specs"))
                if has_fr or has_ma or has_specs:
                    chart_title = f"Couloir de performance - {format_event_label(distance, stroke, pool)}"
                    plot_kwargs = dict(overlay_kwargs)
                    if plot_kwargs.get("swimmer_specs"):
                        plot_kwargs.pop("overlay_nageur", None)
                        plot_kwargs.pop("overlay_year_of_birth", None)
                    fig, meta = svc.plot_performance_corridor_plot_time(
                        corridor_df,
                        nom_event=nom_event,
                        nom_nageur=None
                        if plot_kwargs.get("swimmer_specs")
                        else (fr_name if has_fr else None),
                        year_of_birth=None
                        if plot_kwargs.get("swimmer_specs")
                        else fr_yob,
                        **plot_kwargs,
                    )
                    if isinstance(meta, dict):
                        warn_parts: List[str] = []
                        if meta.get("overlay_swimmer_message"):
                            warn_parts.append(str(meta["overlay_swimmer_message"]))
                        elif meta.get("swimmer_trace_messages"):
                            msgs = meta.get("swimmer_trace_messages")
                            if isinstance(msgs, list) and msgs:
                                warn_parts.append("; ".join(str(m) for m in msgs))
                        if fig is None:
                            err = str(meta.get("message", ""))
                            chart_title = err or (warn_parts[0] if warn_parts else chart_title)
                        elif warn_parts:
                            chart_title = f"{chart_title} — {warn_parts[0]}"
                elif overlay_kwargs.get("swimmer_specs") or overlay_kwargs:
                    chart_title = (
                        f"Couloir de performance global - {format_event_label(distance, stroke, pool)}"
                    )
                    fig, meta = svc.plot_performance_corridor_global_plot_time(
                        corridor_df,
                        nom_event=nom_event,
                        **overlay_kwargs,
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err:
                            chart_title = err
                        elif meta.get("overlay_swimmer_message"):
                            chart_title = str(meta["overlay_swimmer_message"])
                else:
                    # Au démarrage du mode "nageur cible", afficher Graphe28 (global)
                    # tant qu'aucun nageur n'a été confirmé.
                    chart_title = (
                        f"Couloir de performance global - {format_event_label(distance, stroke, pool)}"
                    )
                    fig, meta = svc.plot_performance_corridor_global_plot_time(
                        corridor_df,
                        nom_event=nom_event,
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err:
                            chart_title = err

        elif selected_graph == "Couloir de performance global (âge)":
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = (
                    f"Couloir de performance global - {format_event_label(distance, stroke, pool)}"
                )
                fig, meta = svc.plot_performance_corridor_global_plot_time(
                    corridor_df,
                    nom_event=nom_event,
                    **overlay_kwargs,
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err:
                        chart_title = err
                    elif meta.get("overlay_swimmer_message"):
                        chart_title = str(meta["overlay_swimmer_message"])

        elif selected_graph == "Couloir de performance global (déciles 10-90)":
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                chart_title = (
                    f"Couloir global (déciles 10-90) - {format_event_label(distance, stroke, pool)}"
                )
                deciles_kwargs: Dict[str, Any] = dict(overlay_kwargs)
                if selected_corridor_swimmer_name:
                    deciles_kwargs["nom_nageur"] = selected_corridor_swimmer_name
                    if selected_corridor_swimmer_yob is not None:
                        deciles_kwargs["year_of_birth"] = int(
                            selected_corridor_swimmer_yob
                        )
                fig, meta = svc.plot_performance_corridor_global_deciles_plot_time(
                    corridor_df,
                    nom_event=nom_event,
                    **deciles_kwargs,
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err:
                        chart_title = err
                    elif meta.get("overlay_swimmer_message"):
                        chart_title = str(meta["overlay_swimmer_message"])

        elif selected_graph == GRAPH_RELAY_SPLIT_DISTANCE:
            if distance and stroke and pool:
                nom_event = f"{distance} {stroke} {pool}"
                nom_event_label = format_event_label(distance, stroke, pool)
                chart_title = (
                    f"Vitesse par segment — relais · {nom_event_label}"
                )
                fig, _p, _m, _md, meta = svc.plot_relais_split_speed_par_distance(
                    df_scope, nom_event=nom_event
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err and err != "ok":
                        chart_title = err
                elif isinstance(meta, dict) and meta.get("message") == "ok":
                    relay_count = meta.get("relay_perf_count")
                    if isinstance(relay_count, int) and relay_count > 0:
                        chart_title = (
                            f"Vitesse par segment — relais ({relay_count:,} relais) · "
                            f"{nom_event_label}".replace(",", " ")
                        )

        return fig, chart_title


# les graphiques a précharger dans le prefetch
Graphe1 = GraphSpec(
    key="histogramme_simple",
    name="Histogramme simple",
    category="Distributions de temps",
    method_name="plot_histogramme_simple",
)
Graphe2 = GraphSpec(
    key="camembert_sexe_global",
    name="Camembert par sexe (global)",
    category="Effectifs et repartition par sexe",
    method_name="plot_camembert_sexe_global",
)
Graphe3 = GraphSpec(
    key="boxplot_temps_par_nage",
    name="Distribution des temps par type de nage (boxplot)",
    category="Comparaison des temps par nage",
    method_name="plot_boxplot_temps_par_nage",
)
Graphe4 = GraphSpec(
    key="top10_clubs",
    name="Top 10 clubs par participation",
    category="Clubs",
    method_name="plot_top10_clubs",
)
Graphe5 = GraphSpec(
    key="heatmap_vitesse_moyenne",
    name="Heatmap vitesse moyenne (distance x nage)",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_heatmap_vitesse_moyenne",
)
Graphe7 = GraphSpec(
    key="histogramme_cumulatif",
    name="Histogramme cumulatif",
    category="Distributions de temps",
    method_name="plot_histogramme_cumulatif",
)
Graphe8 = GraphSpec(
    key="nombre_performances_par_epreuve",
    name="Nombre de performances par epreuve",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_epreuve",
)
Graphe9 = GraphSpec(
    key="nombre_performances_par_epreuve_lcm_scm",
    name="Nombre de performances par epreuve (LCM + SCM)",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_epreuve_lcm_scm",
)
Graphe10 = GraphSpec(
    key="nombre_performances_par_sexe",
    name="Nombre de performances par sexe",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_sexe",
)
Graphe11 = GraphSpec(
    key="temps_median_top10_clubs_par_event",
    name="Temps médian top 10 clubs par event",
    category="Clubs",
    method_name="plot_temps_median_top10_clubs_par_event",
)
Graphe12 = GraphSpec(
    key="evolution_temps_nage",
    name="Évolution des temps de nage",
    category="Distributions de temps",
    method_name="plot_evolution_temps_nage",
)
Graphe13 = GraphSpec(
    key="top10_nageurs_meilleur_temps_par_event",
    name="Top 10 nageurs meilleur temps par event",
    category="Classements par epreuve",
    method_name="plot_top10_nageurs_meilleur_temps_par_event",
)
Graphe14 = GraphSpec(
    key="camembert_sexe_par_event",
    name="Camembert par sexe (par event)",
    category="Effectifs et repartition par sexe",
    method_name="plot_camembert_sexe_par_event",
)
Graphe15 = GraphSpec(
    key="vitesse_max_par_split_et_nage",
    name="Vitesse max par split et nage",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_vitesse_max_par_split_et_nage",
)
Graphe16 = GraphSpec(
    key="vitesse_moyenne_mediane_par_split_et_nage",
    name="Vitesse moyenne et mediane par split et nage",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_vitesse_moyenne_mediane_par_split_et_nage",
)
Graphe17 = GraphSpec(
    key="split_speed_analysis_by_gender_with_targets",
    name="Analyse split_speed par genre avec nageurs cibles",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_split_speed_analysis_by_gender_with_targets",
)
Graphe18 = GraphSpec(
    key="vitesse_par_split_pour_nageur_event",
    name="Vitesse par split pour un nageur et un event",
    category="Analyse individuelle par epreuve",
    method_name="plot_vitesse_par_split_pour_nageur_event",
)
Graphe19 = GraphSpec(
    key="vitesse_par_split_meilleur_nageur_event_periode",
    name="Vitesse par split du meilleur nageur par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_meilleur_nageur_event_periode",
)
Graphe20 = GraphSpec(
    key="vitesse_par_split_top_nageurs_hf_event_periode",
    name="Vitesse par split des top nageurs H/F par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_top_nageurs_hf_event_periode",
)
Graphe21 = GraphSpec(
    key="vitesse_par_split_top_nageurs_uniques_event_periode",
    name="Vitesse par split des top nageurs uniques par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_top_nageurs_uniques_event_periode",
)
Graphe22 = GraphSpec(
    key="comparaison_vitesse_moyenne_heatmap_nageur_vs_autres",
    name="Comparaison heatmap vitesse moyenne nageur vs autres",
    category="Analyse individuelle par epreuve",
    method_name="plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres",
)
Graphe23 = GraphSpec(
    key="temps_median_vs_meilleur_nageur_par_split_event",
    name="Temps median vs meilleur nageur par split et event",
    category="Analyse individuelle par epreuve",
    method_name="plot_temps_median_vs_meilleur_nageur_par_split_event",
)
Graphe24 = GraphSpec(
    key="temps_median_vs_top10_nageurs_par_split_event",
    name="Temps median vs top10 nageurs par split et event",
    category="Analyse individuelle par epreuve",
    method_name="plot_temps_median_vs_top10_nageurs_par_split_event",
)
Graphe25 = GraphSpec(
    key="vitesse_mediane_par_split_selon_genre_top_n_event",
    name="Vitesse mediane par split selon genre top-n event",
    category="Classements par epreuve",
    method_name="plot_vitesse_mediane_par_split_selon_genre_top_n_event",
)
Graphe26 = GraphSpec(
    key="relais_split_speed_par_distance",
    name="Vitesse split relais par distance",
    category="Analyse individuelle par epreuve",
    method_name="plot_relais_split_speed_par_distance",
)
Graphe27 = GraphSpec(
    key="performance_corridor_plot_time",
    name="Couloir de performance sur SwimTime",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_plot_time",
)
Graphe28 = GraphSpec(
    key="performance_corridor_global_plot_time",
    name="Couloir de performance global (âge)",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_global_plot_time",
)
Graphe29 = GraphSpec(
    key="performance_corridor_global_deciles_plot_time",
    name="Couloir de performance global (déciles 10-90)",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_global_deciles_plot_time",
)
Graphe30 = GraphSpec(
    key="performance_corridor_global_by_agegroup",
    name="Couloir de performance global (AgeGroup)",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_global_by_agegroup",
)
GRAPHES_NOTEBOOK: List[GraphSpec] = [
    Graphe1, Graphe2, Graphe3, Graphe4, Graphe5, Graphe7, Graphe8, Graphe9,
    Graphe10, Graphe11, Graphe12, Graphe13, Graphe14, Graphe15, Graphe16, Graphe17,
    Graphe18, Graphe19, Graphe20, Graphe21, Graphe22, Graphe23, Graphe24, Graphe25,
    Graphe26, Graphe27, Graphe28, Graphe29, Graphe30,
]
GRAPHES_PAR_KEY: Dict[str, GraphSpec] = {g.key: g for g in GRAPHES_NOTEBOOK}

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

