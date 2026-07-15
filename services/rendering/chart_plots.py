"""Rendu matplotlib des graphiques non-couloir Pacing.

Consomme les résultats de ``services.graph_compute`` et dessine les figures.
Les couloirs restent dans ``services.rendering.corridor_plots``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import Normalize, TwoSlopeNorm, to_hex
from matplotlib.ticker import FuncFormatter, MaxNLocator, MultipleLocator

from services.corridor_data import (
    CORRIDOR_ANNOTATION_COLOR,
    CORRIDOR_FR_SWIMMER_COLOR,
    CORRIDOR_MA_SWIMMER_COLOR,
    CORRIDOR_GRID_ALPHA,
    CORRIDOR_REFERENCE_LINE_COLOR,
    CorridorSwimmerSpec,
    corridor_gender_display_label,
)
from services.graph_compute import (
    _CHRONOS_ROLLING_WINDOW_YEARS,
    _CHRONOS_YEARLY_MIN_PERFORMANCES,
    _GENDER_LABEL_FEMALE,
    _GENDER_LABEL_MALE,
    _drop_zero_count_events,
    _filter_yearly_stats_by_min_count,
    _gender_label_for_code,
    _ordered_stroke_labels,
    _smooth_centered_rolling,
    _sort_event_counts_df,
    CORRIDOR_OVERLAY_SWIMMER_COLOR,
    CORRIDOR_OVERLAY_SWIMMER_LABEL,
)
from services.rendering.corridor_plots import (
    apply_corridor_chart_theme,
    plot_corridor_swimmer_specs,
)
from services.stroke_labels import (
    format_event_label,
    localize_event_string,
    relabel_stroke_column,
    stroke_code_to_label,
    stroke_label_to_code,
)

NON_CORRIDOR_COLOR_MALE = "#0072B2"

NON_CORRIDOR_COLOR_FEMALE = "#CC79A7"

NON_CORRIDOR_COLOR_NEUTRAL = "#374151"

NON_CORRIDOR_COLOR_PRIMARY = "#2E5EAA"

NON_CORRIDOR_COLOR_SECONDARY = "#E69F00"

NON_CORRIDOR_COLOR_ACCENT = "#6A3D9A"

NON_CORRIDOR_COLOR_TARGET = "#D55E00"

NON_CORRIDOR_CMAP_SEQUENTIAL = "viridis"

NON_CORRIDOR_CMAP_DIVERGING = "PuOr"

_STROKE_CATEGORY_COLORS: Dict[str, str] = {
    stroke_code_to_label("FR"): "#0072B2",
    stroke_code_to_label("BK"): "#56B4E9",
    stroke_code_to_label("BR"): "#E69F00",
    stroke_code_to_label("FL"): "#009E73",
    stroke_code_to_label("IM"): "#CC79A7",
    stroke_code_to_label("MD"): "#D55E00",
}

def _stroke_palette_for_labels(labels: List[str]) -> Dict[str, str]:
    """Associe chaque nage à une couleur Okabe-Ito stable.

    Args:
        labels (List[str]): Libellés de nage à colorer.

    Returns:
        Dict[str, str]: Dictionnaire libellé → couleur hexadécimale.
    """
    return {
        label: _STROKE_CATEGORY_COLORS.get(label, NON_CORRIDOR_COLOR_NEUTRAL)
        for label in labels
    }

MEDIAN_VS_BEST_CHART_STYLE_VERSION = 2

MEDIAN_VS_TOP10_CHART_STYLE_VERSION = 2

MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION = 2

def _heatmap_annotations(
    values: pd.DataFrame,
    counts: pd.DataFrame,
    *,
    show_counts: bool = False,
) -> np.ndarray:
    """Construit les annotations texte pour une heatmap vitesse.

    Par défaut n'affiche que la vitesse médiane (lisibilité Tufte). L'effectif
    peut être ajouté pour les petits échantillons (carte nageur cible).

    Args:
        values (pd.DataFrame): Vitesses médianes (distance × nage).
        counts (pd.DataFrame): Effectifs par cellule.
        show_counts (bool): Afficher ``(n=…)`` sous la vitesse si True.

    Returns:
        np.ndarray: Grille d'annotations de forme ``(n_rows, n_cols)``.
    """
    annot = np.empty(values.shape, dtype=object)
    for row_idx in range(values.shape[0]):
        for col_idx in range(values.shape[1]):
            val = values.iat[row_idx, col_idx]
            count = counts.iat[row_idx, col_idx]
            if pd.isna(val) or pd.isna(count) or int(count) <= 0:
                annot[row_idx, col_idx] = ""
            elif show_counts:
                annot[row_idx, col_idx] = f"{float(val):.2f}\n(n={int(count)})"
            else:
                annot[row_idx, col_idx] = f"{float(val):.2f}"
    return annot

def _apply_heatmap_text_contrast(
    ax: plt.Axes,
    values: pd.DataFrame,
    *,
    cmap_name: str,
    vmin: float,
    vmax: float,
    center: Optional[float] = None,
) -> None:
    """Ajuste la couleur des annotations selon la luminance du fond.

    Args:
        ax (plt.Axes): Axe contenant la heatmap seaborn.
        values (pd.DataFrame): Valeurs affichées (même forme que la heatmap).
        cmap_name (str): Nom de la colormap utilisée.
        vmin (float): Borne basse de l'échelle.
        vmax (float): Borne haute de l'échelle.
        center (Optional[float]): Centre pour colormap divergente ; None sinon.

    Returns:
        None
    """
    cmap = plt.get_cmap(cmap_name)
    if center is not None:
        norm: Normalize = TwoSlopeNorm(vmin=vmin, vcenter=center, vmax=vmax)
    else:
        norm = Normalize(vmin=vmin, vmax=vmax)

    text_idx = 0
    for row_idx in range(values.shape[0]):
        for col_idx in range(values.shape[1]):
            val = values.iat[row_idx, col_idx]
            if pd.isna(val):
                continue
            rgba = cmap(norm(float(val)))
            luminance = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
            if text_idx >= len(ax.texts):
                break
            ax.texts[text_idx].set_color("#f8fafc" if luminance < 0.58 else "#0f172a")
            ax.texts[text_idx].set_fontsize(9)
            ax.texts[text_idx].set_fontweight("medium")
            text_idx += 1

def _draw_speed_heatmap_panel(
    ax: plt.Axes,
    values: pd.DataFrame,
    counts: pd.DataFrame,
    *,
    title: str,
    vmin: float,
    vmax: float,
    cmap: str,
    cbar: bool,
    cbar_label: str,
    center: Optional[float] = None,
    show_counts: bool = False,
) -> Optional[Any]:
    """Dessine un panneau heatmap avec thème Pacing et cellules masquées.

    Args:
        ax (plt.Axes): Axe matplotlib cible.
        values (pd.DataFrame): Vitesses à encoder (distance × nage).
        counts (pd.DataFrame): Effectifs par cellule (même forme).
        title (str): Titre du panneau.
        vmin (float): Borne basse de l'échelle couleur.
        vmax (float): Borne haute de l'échelle couleur.
        cmap (str): Nom de la colormap seaborn/matplotlib.
        cbar (bool): Afficher la barre de couleur sur ce panneau.
        cbar_label (str): Libellé de la barre de couleur.
        center (Optional[float]): Centre pour colormap divergente ; None sinon.
        show_counts (bool): Afficher l'effectif dans les cellules.

    Returns:
        Optional[Any]: Collection matplotlib (mappable) pour une colorbar externe.
    """
    _apply_standard_chart_theme(ax.figure, ax)
    if values.empty or values.dropna(how="all").dropna(axis=1, how="all").empty:
        ax.text(
            0.5,
            0.5,
            "Pas de données disponibles",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=11,
            color="#334155",
        )
        ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
        ax.set_xlabel("Nage")
        ax.set_ylabel("Distance (m)")
        ax.set_xticks([])
        ax.set_yticks([])
        return None

    masked = values.copy()
    counts_aligned = counts.reindex(index=values.index, columns=values.columns).fillna(0)
    masked[counts_aligned <= 0] = np.nan
    annot = _heatmap_annotations(masked, counts_aligned, show_counts=show_counts)
    n_rows, n_cols = masked.shape
    heatmap_kwargs: Dict[str, object] = {
        "annot": annot,
        "fmt": "",
        "cmap": cmap,
        "ax": ax,
        "cbar": cbar,
        "vmin": vmin,
        "vmax": vmax,
        "linewidths": 0.6,
        "linecolor": "#cbd5e1",
        "mask": masked.isna(),
        "xticklabels": list(values.columns),
        "yticklabels": [str(distance) for distance in values.index],
    }
    if center is not None:
        heatmap_kwargs["center"] = center
    if cbar:
        heatmap_kwargs["cbar_kws"] = {"label": cbar_label, "shrink": 0.85}
    heatmap = sns.heatmap(masked, **heatmap_kwargs)
    _apply_heatmap_text_contrast(
        ax,
        masked,
        cmap_name=cmap,
        vmin=vmin,
        vmax=vmax,
        center=center,
    )
    ax.set_ylim(n_rows, 0)
    ax.set_xlim(0, n_cols)
    ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
    ax.set_xlabel("Nage", fontsize=11)
    ax.set_ylabel("Distance (m)", fontsize=11)
    ax.tick_params(axis="x", rotation=0, labelsize=9)
    ax.tick_params(axis="y", rotation=0, labelsize=9)
    collections = heatmap.collections
    return collections[0] if collections else None

def _format_swim_time_display(total_seconds: float, *, precision: int = 1) -> str:
    """Formate une durée de nage pour axe ou annotation.

    Sous 60 s : affichage en secondes (``52.3s``). Au-delà : ``M:SS`` ou
    ``M:SS.cc`` selon la précision demandée, sans zéros décimaux superflus
    sur l'axe.

    Args:
        total_seconds (float): Durée en secondes.
        precision (int): Nombre de décimales (1 pour l'axe, 2 pour les médianes).

    Returns:
        str: Libellé formaté pour affichage.
    """
    if total_seconds < 0:
        return ""
    if total_seconds < 60:
        text = f"{total_seconds:.{precision}f}"
        if precision > 0:
            text = text.rstrip("0").rstrip(".")
        return f"{text}s"
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    if precision >= 2:
        return f"{minutes}:{seconds:05.2f}"
    sec_text = f"{seconds:04.1f}"
    if sec_text.endswith(".0"):
        sec_text = sec_text[:-2]
    return f"{minutes}:{sec_text}"

def _format_swim_time_tick(value: float, _: int) -> str:
    """Formate une graduation d'axe temps en secondes lisibles.

    Args:
        value (float): Durée en secondes.
        _ (int): Index de graduation (ignoré, requis par Matplotlib).

    Returns:
        str: Libellé court pour l'axe Y (ex. ``15.2s``, ``1:40``).
    """
    return _format_swim_time_display(value, precision=1)

def _format_swim_time_annotation(seconds: float) -> str:
    """Formate un temps de nage pour annotation sur le graphique.

    Args:
        seconds (float): Durée en secondes.

    Returns:
        str: Libellé compact (ex. ``52.34s`` ou ``2:00.06``).
    """
    return _format_swim_time_display(seconds, precision=2)

_MEDIAN_LABEL_BBOX = {
    "boxstyle": "round,pad=0.28",
    "facecolor": "white",
    "alpha": 0.9,
    "edgecolor": "#e2e8f0",
    "linewidth": 0.6,
}

def _boxplot_category_center_x(ax: plt.Axes, n_categories: int) -> List[float]:
    """Retourne les abscisses centrales des boîtes d'un boxplot Seaborn.

    Lit la position réelle des moustaches ou des lignes médianes dans les
    conteneurs Seaborn, plus fiable que des indices entiers lorsque ``hue``
    et ``x`` partagent la même variable catégorielle.

    Args:
        ax (plt.Axes): Axe contenant le boxplot déjà tracé.
        n_categories (int): Nombre de catégories attendues sur l'axe X.

    Returns:
        List[float]: Centres horizontaux de chaque boîte, dans l'ordre de tracé.
    """
    centers: List[float] = []
    containers = list(ax.containers[:n_categories]) if ax.containers else []
    for container in containers:
        whiskers = getattr(container, "whiskers", None)
        if whiskers and len(whiskers) >= 2:
            x_data = whiskers[1].get_xdata()
            centers.append(float(x_data[0]))
            continue
        medians = getattr(container, "medians", None)
        if medians:
            x_data = medians[0].get_xdata()
            centers.append(float((x_data[0] + x_data[1]) / 2.0))
            continue
    if len(centers) == n_categories:
        return centers
    tick_positions = ax.get_xticks()
    if len(tick_positions) >= n_categories:
        return [float(pos) for pos in tick_positions[:n_categories]]
    return [float(index) for index in range(n_categories)]

def _ranked_sequential_bar_colors(n_bars: int) -> List[str]:
    """Construit un dégradé séquentiel pour des barres classées par rang.

    Du plus foncé (1er) au plus clair (dernier), adapté aux données ordonnées
    (Munzner : luminance pour l'ordre, position pour la comparaison).

    Args:
        n_bars (int): Nombre de barres à colorer.

    Returns:
        List[str]: Couleurs hexadécimales, une par barre.
    """
    if n_bars <= 0:
        return []
    if n_bars == 1:
        return [NON_CORRIDOR_COLOR_PRIMARY]
    palette = sns.color_palette(
        [NON_CORRIDOR_COLOR_PRIMARY, "#b8cce8"],
        n_colors=n_bars,
    )
    return [to_hex(color) for color in palette]

def _plot_ranked_horizontal_counts(
    counts: pd.Series,
    *,
    title: str,
    y_label: str,
    x_label: str = "Nombre de participations",
    total_count: Optional[int] = None,
) -> plt.Figure:
    """Trace un classement horizontal par effectif décroissant.

    Barres horizontales (Cleveland & McGill) : les libellés longs restent lisibles
    sans rotation. Palette séquentielle, thème Pacing et annotations de valeur.

    Args:
        counts (pd.Series): Effectifs indexés par catégorie, tri décroissant attendu.
        title (str): Titre affiché au-dessus du graphique.
        y_label (str): Libellé de l'axe des catégories.
        x_label (str): Libellé de l'axe des effectifs.
        total_count (Optional[int]): Dénominateur pour les parts en % ; par défaut
            la somme des barres affichées.

    Returns:
        plt.Figure: Figure matplotlib du classement.
    """
    ordered = counts.sort_values(ascending=False)
    categories = [str(label) for label in ordered.index.tolist()]
    values = [int(value) for value in ordered.values]
    n_items = len(categories)
    bar_total = int(sum(values)) if values else 0
    denominator = int(total_count) if total_count is not None else bar_total

    fig_height = max(5.0, min(12.0, n_items * 0.62 + 1.8))
    fig, ax = plt.subplots(figsize=(12, fig_height))
    _apply_standard_chart_theme(fig, ax)

    if n_items == 0 or bar_total == 0:
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

    colors = _ranked_sequential_bar_colors(n_items)
    y_pos = np.arange(n_items)
    bars = ax.barh(
        y_pos,
        values,
        height=0.62,
        color=colors,
        edgecolor="#ffffff",
        linewidth=0.8,
        zorder=3,
    )
    xmax = max(values)
    label_offset = xmax * 0.02 if xmax > 0 else 0.5
    for bar, value in zip(bars, values):
        share_pct = (100.0 * value / denominator) if denominator > 0 else 0.0
        ax.text(
            value + label_offset,
            bar.get_y() + bar.get_height() / 2,
            f"{_format_count_display(value)} ({share_pct:.0f} %)",
            ha="left",
            va="center",
            fontsize=10.5,
            color="#334155",
            fontweight="medium",
            zorder=4,
        )

    y_labelsize = 11 if n_items <= 6 else 10
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories)
    ax.tick_params(axis="y", labelsize=y_labelsize)
    ax.invert_yaxis()
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_xlim(0, xmax * 1.22 if xmax > 0 else 1)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=5))
    ax.xaxis.set_major_formatter(FuncFormatter(_format_performance_count_tick))
    ax.grid(
        axis="x",
        alpha=CORRIDOR_GRID_ALPHA,
        color="#94a3b8",
        linestyle="-",
        linewidth=0.6,
        zorder=0,
    )
    fig.tight_layout()
    return fig

def _plot_ranked_horizontal_median_times(
    stats: pd.DataFrame,
    *,
    title: str,
    club_col: str = "Club",
    median_col: str = "median_seconds",
    count_col: str = "n_performances",
    y_label: str = "Club",
    x_label: str = "Temps médian (secondes)",
) -> plt.Figure:
    """Trace un classement horizontal de temps médians croissants.

    Barres horizontales (Cleveland & McGill) : comparaison de chronos sur un
    axe commun, libellés de clubs lisibles, palette séquentielle et fenêtre
    d'axe resserrée autour des valeurs observées (Tufte).

    Args:
        stats (pd.DataFrame): Stats par club, triées par temps médian croissant.
        title (str): Titre affiché au-dessus du graphique.
        club_col (str): Colonne des noms de club.
        median_col (str): Colonne du temps médian en secondes.
        count_col (str): Colonne du nombre de performances par club.
        y_label (str): Libellé de l'axe des catégories.
        x_label (str): Libellé de l'axe des temps.

    Returns:
        plt.Figure: Figure matplotlib du classement par temps médian.

    Raises:
        ValueError: Si une colonne requise est absente de ``stats``.
    """
    for column in (club_col, median_col, count_col):
        if column not in stats.columns:
            raise ValueError(f"Colonne introuvable pour le classement médian: {column}")

    ordered = stats.sort_values(median_col, ascending=True).copy()
    categories = [str(label) for label in ordered[club_col].tolist()]
    values = [float(value) for value in ordered[median_col].tolist()]
    counts = [int(value) for value in ordered[count_col].tolist()]
    n_items = len(categories)

    fig_height = max(5.0, min(12.0, n_items * 0.62 + 1.8))
    fig, ax = plt.subplots(figsize=(12, fig_height))
    _apply_standard_chart_theme(fig, ax)

    if n_items == 0:
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

    xmin = float(min(values))
    xmax = float(max(values))
    x_span = max(xmax - xmin, 0.5)
    x_floor = max(0.0, xmin - x_span * 0.35)
    colors = _ranked_sequential_bar_colors(n_items)
    y_pos = np.arange(n_items)
    bars = ax.barh(
        y_pos,
        [value - x_floor for value in values],
        left=x_floor,
        height=0.62,
        color=colors,
        edgecolor="#ffffff",
        linewidth=0.8,
        zorder=3,
    )
    label_offset = x_span * 0.03 if x_span > 0 else 0.1
    for bar, median_value, perf_count in zip(bars, values, counts):
        ax.text(
            median_value + label_offset,
            bar.get_y() + bar.get_height() / 2,
            f"{_format_swim_time_annotation(median_value)} (n={perf_count})",
            ha="left",
            va="center",
            fontsize=10.5,
            color="#334155",
            fontweight="medium",
            zorder=4,
        )

    y_labelsize = 11 if n_items <= 6 else 10
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories)
    ax.tick_params(axis="y", labelsize=y_labelsize)
    ax.invert_yaxis()
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_xlim(x_floor, xmax + x_span * 0.34)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.xaxis.set_major_formatter(FuncFormatter(_format_swim_time_tick))
    ax.grid(
        axis="x",
        alpha=CORRIDOR_GRID_ALPHA,
        color="#94a3b8",
        linestyle="-",
        linewidth=0.6,
        zorder=0,
    )
    fig.tight_layout()
    return fig

def _plot_yearly_stroke_time_evolution(
    yearly_stats: pd.DataFrame,
    *,
    title: str,
    stroke_col: str = "Stroke",
    year_col: str = "year",
    median_col: str = "median_seconds",
    min_yearly_performances: int = _CHRONOS_YEARLY_MIN_PERFORMANCES,
    rolling_window_years: int = _CHRONOS_ROLLING_WINDOW_YEARS,
) -> plt.Figure:
    """Trace l'évolution annuelle des temps médians en petits multiples par nage.

    Chaque panneau possède sa propre échelle Y (les nages ne sont pas comparables
    sur un même axe lorsque les distances sont mélangées). Les courbes affichées
    sont lissées par moyenne mobile ; la médiane brute reste visible en filigrane.

    Args:
        yearly_stats (pd.DataFrame): Médianes annuelles par nage.
        title (str): Titre principal de la figure.
        stroke_col (str): Colonne des libellés de nage.
        year_col (str): Colonne de l'année.
        median_col (str): Colonne du temps médian en secondes.
        min_yearly_performances (int): Effectif annuel minimal pour tracer un point.
        rolling_window_years (int): Fenêtre de lissage (années) de la tendance.

    Returns:
        plt.Figure: Figure matplotlib de l'évolution temporelle.

    Raises:
        ValueError: Si une colonne requise est absente de ``yearly_stats``.
    """
    for column in (stroke_col, year_col, median_col):
        if column not in yearly_stats.columns:
            raise ValueError(f"Colonne introuvable pour l'évolution annuelle: {column}")

    stroke_order = _ordered_stroke_labels(yearly_stats[stroke_col].astype(str).tolist())
    n_strokes = len(stroke_order)
    if n_strokes == 0:
        fig, ax = plt.subplots(figsize=(12, 5))
        _apply_standard_chart_theme(fig, ax)
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

    ncols = 2 if n_strokes > 1 else 1
    nrows = int(np.ceil(n_strokes / ncols))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(14, 3.9 * nrows + 1.2),
        squeeze=False,
        sharex=False,
    )
    fig.patch.set_facecolor("#ffffff")
    global_year_min: Optional[int] = None
    global_year_max: Optional[int] = None

    for index, stroke_label in enumerate(stroke_order):
        ax = axes[index // ncols][index % ncols]
        _apply_standard_chart_theme(fig, ax)
        stroke_data = yearly_stats.loc[
            yearly_stats[stroke_col].astype(str) == stroke_label
        ].sort_values(year_col)
        stroke_data = _filter_yearly_stats_by_min_count(
            stroke_data,
            year_col=year_col,
            min_performances=min_yearly_performances,
        )
        color = _STROKE_CATEGORY_COLORS.get(stroke_label, NON_CORRIDOR_COLOR_NEUTRAL)
        if stroke_data.empty:
            ax.text(
                0.5,
                0.5,
                "Données insuffisantes\n(effectif annuel trop faible).",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=10,
                color="#64748b",
            )
            ax.set_title(stroke_label, fontsize=12, fontweight="semibold", color=color, pad=8)
            ax.set_xlabel("Année", fontsize=10, labelpad=6)
            ax.tick_params(axis="x", labelbottom=True, labelsize=9)
            continue

        years = stroke_data[year_col].astype(int).tolist()
        medians = stroke_data[median_col].astype(float).tolist()
        smoothed = _smooth_centered_rolling(medians, rolling_window_years)
        global_year_min = years[0] if global_year_min is None else min(global_year_min, years[0])
        global_year_max = years[-1] if global_year_max is None else max(global_year_max, years[-1])

        ax.plot(
            years,
            medians,
            color=color,
            linewidth=1.2,
            linestyle="--",
            alpha=0.35,
            marker="o",
            markersize=3.5,
            markerfacecolor="#ffffff",
            markeredgecolor=color,
            markeredgewidth=1.0,
            zorder=2,
        )
        ax.plot(
            years,
            smoothed,
            color=color,
            linewidth=2.6,
            marker="o",
            markersize=5.5,
            markerfacecolor="#ffffff",
            markeredgecolor=color,
            markeredgewidth=1.6,
            zorder=3,
        )
        ax.set_title(stroke_label, fontsize=12, fontweight="semibold", color=color, pad=8)
        ax.set_ylabel("Médiane", fontsize=10, labelpad=6)
        ax.set_xlabel("Année", fontsize=10, labelpad=6)
        ax.yaxis.set_major_formatter(FuncFormatter(_format_swim_time_tick))
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=7))
        ax.tick_params(axis="x", labelbottom=True, labelsize=9)
        ax.grid(
            axis="y",
            alpha=CORRIDOR_GRID_ALPHA,
            color="#94a3b8",
            linestyle="-",
            linewidth=0.6,
            zorder=0,
        )
        plot_values = medians + smoothed
        ymin = float(min(plot_values))
        ymax = float(max(plot_values))
        y_span = max(ymax - ymin, 0.5)
        ax.set_ylim(ymin - y_span * 0.12, ymax + y_span * 0.18)
        y_top = ymax + y_span * 0.12
        ax.text(
            0.98,
            0.97,
            f"échelle locale\nmax {_format_swim_time_annotation(ymax)}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8,
            color="#64748b",
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": "white",
                "alpha": 0.85,
                "edgecolor": "#e2e8f0",
            },
            zorder=5,
        )

    for index in range(n_strokes, nrows * ncols):
        axes[index // ncols][index % ncols].set_axis_off()

    if global_year_min is not None and global_year_max is not None:
        for index in range(n_strokes):
            ax = axes[index // ncols][index % ncols]
            if ax.has_data():
                ax.set_xlim(global_year_min - 0.6, global_year_max + 0.6)

    subtitle = (
        f"Moyenne mobile {rolling_window_years} ans (trait plein) · "
        f"médiane brute (pointillés) · "
        f"années avec < {min_yearly_performances} perf. exclues · "
        "échelle Y propre à chaque nage"
    )
    fig.suptitle(
        f"{title}\n{subtitle}",
        fontsize=13,
        fontweight="bold",
        color="#1e293b",
        y=1.02,
    )
    fig.tight_layout()
    return fig

def _format_speed_tick(value: float, _: int) -> str:
    """Formate une graduation d'axe vitesse en m/s.

    Args:
        value (float): Vitesse en mètres par seconde.
        _ (int): Index de graduation (ignoré, requis par Matplotlib).

    Returns:
        str: Libellé formaté (ex. ``1.25``).
    """
    if value < 0:
        return ""
    return f"{value:.2f}"

_STROKE_MARKERS: Dict[str, str] = {
    stroke_code_to_label("FR"): "s",
    stroke_code_to_label("BK"): "X",
    stroke_code_to_label("BR"): "o",
    stroke_code_to_label("FL"): "P",
    stroke_code_to_label("IM"): "D",
    stroke_code_to_label("MD"): "v",
}

def _all_split_distance_ticks(distances: List[float]) -> List[float]:
    """Retourne toutes les distances de split présentes dans les données.

    Args:
        distances (List[float]): Distances observées (valeurs uniques ou brutes).

    Returns:
        List[float]: Distances triées pour graduations complètes de l'axe X.
    """
    return sorted({float(distance) for distance in distances})

def _plot_max_split_speed_by_stroke(
    peaks_df: pd.DataFrame,
    *,
    title: str,
    subtitle: str = "",
    empty_message: str = "Aucun split valide pour ce périmètre.",
    stroke_col: str = "Stroke",
    distance_col: str = "SplitDistance",
    speed_col: str = "SplitSpeed",
) -> plt.Figure:
    """Trace les records de vitesse de split par nage (nuage de points).

    Position + couleur + forme de marqueur pour distinguer les nages (Munzner,
    Okabe-Ito), thème Pacing, axe X linéaire avec toutes les distances tracées.

    Args:
        peaks_df (pd.DataFrame): Vitesses maximales par nage et distance de split.
        title (str): Titre affiché au-dessus du graphique.
        subtitle (str): Sous-titre méthodologique optionnel.
        empty_message (str): Message affiché lorsque aucun point n'est traçable.
        stroke_col (str): Colonne du type de nage.
        distance_col (str): Colonne distance cumulée du split (m).
        speed_col (str): Colonne vitesse maximale (m/s).

    Returns:
        plt.Figure: Figure matplotlib du nuage de points.

    Raises:
        ValueError: Si une colonne requise est absente de ``peaks_df``.
    """
    for column in (stroke_col, distance_col, speed_col):
        if column not in peaks_df.columns:
            raise ValueError(
                f"Colonne introuvable pour le graphique splits max: {column}"
            )

    stroke_order = _ordered_stroke_labels(
        peaks_df[stroke_col].astype(str).tolist()
    )
    palette = _stroke_palette_for_labels(stroke_order)
    distances = sorted(peaks_df[distance_col].astype(float).unique())

    fig, ax = plt.subplots(figsize=(14, 8))
    _apply_standard_chart_theme(fig, ax)

    if not stroke_order or not distances:
        ax.text(
            0.5,
            0.5,
            empty_message,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=12,
            color="#334155",
        )
        ax.set_axis_off()
        ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
        if subtitle:
            fig.text(
                0.5,
                0.02,
                subtitle,
                ha="center",
                va="bottom",
                fontsize=9,
                color="#64748B",
            )
        fig.tight_layout()
        return fig

    y_values_all: List[float] = []
    for stroke_label in stroke_order:
        stroke_data = peaks_df.loc[
            peaks_df[stroke_col].astype(str) == stroke_label
        ]
        if stroke_data.empty:
            continue
        color = palette[stroke_label]
        marker = _STROKE_MARKERS.get(stroke_label, "o")
        x_vals = stroke_data[distance_col].astype(float).tolist()
        y_vals = stroke_data[speed_col].astype(float).tolist()
        y_values_all.extend(y_vals)
        ax.scatter(
            x_vals,
            y_vals,
            c=color,
            marker=marker,
            s=95,
            linewidths=1.4,
            edgecolors="#ffffff",
            label=stroke_label,
            alpha=0.9,
            zorder=3,
        )

    tick_values = _all_split_distance_ticks(distances)
    ax.set_xscale("linear")
    ax.set_xticks(tick_values)
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{int(v)}" if v == int(v) else f"{v:g}")
    )
    if len(tick_values) > 8:
        ax.tick_params(axis="x", labelsize=8, rotation=45)
        for label in ax.get_xticklabels():
            label.set_ha("right")
    ax.yaxis.set_major_formatter(FuncFormatter(_format_speed_tick))
    ax.set_xlabel("Distance cumulée du split (m) — échelle linéaire")
    ax.set_ylabel("Vitesse maximale du split (m/s)")
    if subtitle:
        fig.suptitle(
            f"{title}\n{subtitle}",
            fontsize=13,
            fontweight="bold",
            color="#1e293b",
            y=1.02,
        )
    else:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    if distances:
        x_min = min(distances)
        x_max = max(distances)
        x_margin = max((x_max - x_min) * 0.04, 25.0)
        ax.set_xlim(max(0.0, x_min - x_margin), x_max + x_margin)
    if y_values_all:
        y_min = float(min(y_values_all))
        y_max = float(max(y_values_all))
        y_span = max(y_max - y_min, 0.08)
        ax.set_ylim(y_min - y_span * 0.08, y_max + y_span * 0.12)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=10))
    ax.grid(
        axis="y",
        alpha=CORRIDOR_GRID_ALPHA,
        color="#94a3b8",
        linestyle="-",
        linewidth=0.6,
        zorder=0,
    )
    ax.grid(
        axis="x",
        alpha=0.18,
        color="#94a3b8",
        linestyle=":",
        linewidth=0.5,
        zorder=0,
    )
    ax.legend(
        title="Nage",
        loc="upper right",
        framealpha=0.92,
        edgecolor="#cbd5e1",
        fontsize=10,
        title_fontsize=10,
    )
    fig.tight_layout()
    if len(tick_values) > 8:
        fig.subplots_adjust(bottom=0.16)
    return fig

def _plot_mean_speed_by_distance_and_stroke(
    speed_by_dist: pd.DataFrame,
    *,
    title: str,
    subtitle: str = "",
    empty_message: str = "Aucune performance disponible pour ce périmètre.",
    distance_col: str = "Distance",
    speed_col: str = "median_speed",
    stroke_col: str = "Stroke",
    count_col: str = "n",
) -> plt.Figure:
    """Trace la vitesse médiane par distance et type de nage.

    Courbes sur une échelle X linéaire (distance réelle en mètres), palette
    Okabe-Ito par nage, thème Pacing et annotations de lecture.

    Args:
        speed_by_dist (pd.DataFrame): Vitesses médianes agrégées.
        title (str): Titre affiché au-dessus du graphique.
        subtitle (str): Sous-titre méthodologique optionnel.
        empty_message (str): Message affiché lorsque aucun point n'est traçable.
        distance_col (str): Colonne distance en mètres.
        speed_col (str): Colonne vitesse médiane en m/s.
        stroke_col (str): Colonne du type de nage (libellés français).
        count_col (str): Colonne effectif par point.

    Returns:
        plt.Figure: Figure matplotlib des courbes de vitesse.

    Raises:
        ValueError: Si une colonne requise est absente de ``speed_by_dist``.
    """
    for column in (distance_col, speed_col, stroke_col):
        if column not in speed_by_dist.columns:
            raise ValueError(f"Colonne introuvable pour le graphique vitesse: {column}")

    stroke_order = _ordered_stroke_labels(
        speed_by_dist[stroke_col].astype(str).tolist()
    )
    palette = _stroke_palette_for_labels(stroke_order)
    distances = sorted(speed_by_dist[distance_col].astype(float).unique())

    fig, ax = plt.subplots(figsize=(14, 8))
    _apply_standard_chart_theme(fig, ax)

    if not stroke_order or not distances:
        ax.text(
            0.5,
            0.5,
            empty_message,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=12,
            color="#334155",
        )
        ax.set_axis_off()
        ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
        if subtitle:
            fig.text(
                0.5,
                0.02,
                subtitle,
                ha="center",
                va="bottom",
                fontsize=9,
                color="#64748B",
            )
        fig.tight_layout()
        return fig

    y_values_all: List[float] = []
    for stroke_label in stroke_order:
        stroke_data = speed_by_dist.loc[
            speed_by_dist[stroke_col].astype(str) == stroke_label
        ].sort_values(distance_col)
        if stroke_data.empty:
            continue
        color = palette[stroke_label]
        x_vals = stroke_data[distance_col].astype(float).tolist()
        y_vals = stroke_data[speed_col].astype(float).tolist()
        y_values_all.extend(y_vals)
        ax.plot(
            x_vals,
            y_vals,
            color=color,
            linewidth=2.8,
            marker="o",
            markersize=9,
            markerfacecolor="#ffffff",
            markeredgecolor=color,
            markeredgewidth=2.0,
            label=stroke_label,
            zorder=3,
        )
        if count_col in stroke_data.columns:
            counts = stroke_data[count_col].astype(int).tolist()
        else:
            counts = [0] * len(x_vals)
        x_span = max(distances) - min(distances) if len(distances) > 1 else 50.0
        label_dx = max(x_span * 0.012, 1.5)
        for x_val, y_val, perf_n in zip(x_vals, y_vals, counts):
            ax.text(
                x_val + label_dx,
                y_val,
                f"{y_val:.2f}",
                ha="left",
                va="center",
                fontsize=8.5,
                color="#334155",
                fontweight="medium",
                zorder=4,
            )

    ax.set_xscale("linear")
    ax.set_xticks(distances)
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{int(v)}" if v == int(v) else f"{v:g}")
    )
    ax.yaxis.set_major_formatter(FuncFormatter(_format_speed_tick))
    ax.set_xlabel("Distance (m) — échelle linéaire")
    ax.set_ylabel("Vitesse médiane (m/s)")
    if subtitle:
        fig.suptitle(
            f"{title}\n{subtitle}",
            fontsize=13,
            fontweight="bold",
            color="#1e293b",
            y=1.02,
        )
    else:
        ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    if distances:
        x_min = min(distances)
        x_max = max(distances)
        x_margin = max((x_max - x_min) * 0.05, 8.0)
        ax.set_xlim(x_min - x_margin, x_max + x_margin * 1.35)
    if y_values_all:
        y_min = float(min(y_values_all))
        y_max = float(max(y_values_all))
        y_span = max(y_max - y_min, 0.08)
        ax.set_ylim(y_min - y_span * 0.1, y_max + y_span * 0.14)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=10))
    ax.grid(
        axis="y",
        alpha=CORRIDOR_GRID_ALPHA,
        color="#94a3b8",
        linestyle="-",
        linewidth=0.6,
        zorder=0,
    )
    ax.grid(
        axis="x",
        alpha=0.18,
        color="#94a3b8",
        linestyle=":",
        linewidth=0.5,
        zorder=0,
    )
    ax.legend(
        title="Nage",
        loc="upper right",
        framealpha=0.92,
        edgecolor="#cbd5e1",
        fontsize=10,
        title_fontsize=10,
    )
    fig.tight_layout()
    return fig

def _apply_standard_chart_theme(fig: plt.Figure, ax: plt.Axes) -> None:
    """Applique le thème graphique commun Pacing (effectifs et couloirs).

    Réutilise ``apply_corridor_chart_theme`` pour un fond et une grille cohérents,
    puis allège les bordures pour maximiser le ratio données/encre (Tufte).

    Args:
        fig (plt.Figure): Figure matplotlib.
        ax (plt.Axes): Axe principal.

    Returns:
        None
    """
    apply_corridor_chart_theme(fig, ax)
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)
    ax.spines["left"].set_color("#94a3b8")
    ax.spines["bottom"].set_color("#94a3b8")
    ax.tick_params(colors="#334155", labelsize=10)
    ax.xaxis.label.set_color("#334155")
    ax.yaxis.label.set_color("#334155")
    ax.title.set_color("#1e293b")

def _apply_corridor_consistent_styling(
    fig: plt.Figure,
    ax: plt.Axes,
    *,
    title: str,
    gender: Optional[str],
    reference_count: Optional[int] = None,
    legend_fontsize: int = 9,
) -> None:
    """Applique le style final commun aux graphiques de couloirs.

    Cette fonction aligne les graphiques de la catégorie « Couloirs de
    performances » avec la charte Pacing utilisée par les autres visuels :
    thème standard, titre contextualisé (épreuve + genre), encadré d'information
    de référence, et légende homogène.

    Args:
        fig (plt.Figure): Figure matplotlib.
        ax (plt.Axes): Axe principal.
        title (str): Titre principal sans suffixe de genre.
        gender (Optional[str]): Code genre (``F``/``M``) ou None.
        reference_count (Optional[int]): Effectif du groupe de référence à afficher.
        legend_fontsize (int): Taille de police de la légende.

    Returns:
        None: Cette fonction modifie la figure et l'axe en place.
    """
    _apply_standard_chart_theme(fig, ax)
    gender_txt = corridor_gender_display_label(gender)
    final_title = f"{title} ({gender_txt})" if gender_txt else title
    ax.set_title(final_title, fontsize=13, fontweight="bold", pad=10)
    if reference_count is not None:
        ax.text(
            0.01,
            0.99,
            f"Couloir : {int(reference_count)} nages de référence",
            transform=ax.transAxes,
            fontsize=9,
            va="top",
            ha="left",
            color=CORRIDOR_ANNOTATION_COLOR,
        )
    ax.legend(loc="best", fontsize=legend_fontsize, frameon=False)

def _plot_gender_grouped_counts_by_event(
    df_counts: pd.DataFrame,
    *,
    title: str,
    by_total: bool = False,
) -> plt.Figure:
    """Trace des barres horizontales groupées F/M par épreuve.

    Encodage positionnel (Cleveland & McGill) : comparaison F/M sur un axe commun,
    libellés localisés, palette Okabe-Ito et thème aligné sur les couloirs.

    Args:
        df_counts (pd.DataFrame): Effectifs par épreuve et genre (colonnes ``F``, ``M``).
        title (str): Titre de la figure.
        by_total (bool): Tri par effectif total décroissant si True.

    Returns:
        plt.Figure: Figure matplotlib des effectifs par épreuve.
    """
    gender_cols = [col for col in ("F", "M") if col in df_counts.columns]
    df_nonzero = _drop_zero_count_events(df_counts[gender_cols])
    df_sorted = _sort_event_counts_df(df_nonzero, by_total=by_total)
    events = df_sorted.index.tolist()
    n_events = len(events)

    if n_events == 0:
        fig, ax = plt.subplots(figsize=(12, 6))
        _apply_standard_chart_theme(fig, ax)
        ax.text(
            0.5,
            0.5,
            "Aucune performance disponible pour ce bassin.",
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

    female_counts = df_sorted["F"] if "F" in df_sorted.columns else pd.Series(0, index=events)
    male_counts = df_sorted["M"] if "M" in df_sorted.columns else pd.Series(0, index=events)
    labels = [localize_event_string(str(event)) for event in events]

    fig_height = max(7.0, min(22.0, n_events * 0.38 + 1.8))
    fig, ax = plt.subplots(figsize=(14, fig_height))
    _apply_standard_chart_theme(fig, ax)

    y_pos = np.arange(n_events)
    bar_height = 0.36
    female_bars = ax.barh(
        y_pos - bar_height / 2,
        female_counts.values,
        height=bar_height,
        label=_GENDER_LABEL_FEMALE,
        color=NON_CORRIDOR_COLOR_FEMALE,
        edgecolor="#ffffff",
        linewidth=0.6,
        zorder=3,
    )
    male_bars = ax.barh(
        y_pos + bar_height / 2,
        male_counts.values,
        height=bar_height,
        label=_GENDER_LABEL_MALE,
        color=NON_CORRIDOR_COLOR_MALE,
        edgecolor="#ffffff",
        linewidth=0.6,
        zorder=3,
    )

    max_value = float(max(female_counts.max(), male_counts.max(), 1))
    label_offset = max(max_value * 0.012, 8.0)
    label_fontsize = 10 if n_events <= 8 else 9
    for bars, counts in ((female_bars, female_counts), (male_bars, male_counts)):
        for bar, value in zip(bars, counts.values):
            count = int(value)
            if count <= 0:
                continue
            ax.text(
                count + label_offset,
                bar.get_y() + bar.get_height() / 2,
                _format_count_display(count),
                ha="left",
                va="center",
                fontsize=label_fontsize,
                color="#334155",
                fontweight="medium",
                zorder=4,
            )

    y_labelsize = 12 if n_events <= 8 else (11 if n_events <= 14 else 10)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.tick_params(axis="y", labelsize=y_labelsize)
    ax.invert_yaxis()
    ax.set_xlabel("Nombre de performances")
    ax.set_ylabel("Épreuve")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_xlim(0, max_value * 1.14)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=5))
    ax.grid(
        axis="x",
        alpha=CORRIDOR_GRID_ALPHA,
        color="#94a3b8",
        linestyle="-",
        linewidth=0.6,
        zorder=0,
    )
    ax.legend(
        loc="lower right",
        framealpha=0.92,
        edgecolor="#cbd5e1",
        fontsize=10,
    )
    fig.tight_layout()
    return fig

def _format_count_display(value: int) -> str:
    """Formate un effectif avec des espaces ASCII comme séparateurs de milliers.

    Évite les caractères typographiques (espace insécable, fine space) non
    présents dans les polices Matplotlib par défaut (ex. Arial).

    Args:
        value (int): Nombre de performances à afficher.

    Returns:
        str: Chaîne lisible (ex. ``390 000``).
    """
    negative = value < 0
    digits = str(abs(int(value)))
    if len(digits) <= 3:
        formatted = digits
    else:
        groups: List[str] = []
        while digits:
            groups.append(digits[-3:])
            digits = digits[:-3]
        formatted = " ".join(reversed(groups))
    return f"-{formatted}" if negative else formatted

def _format_performance_count_tick(value: float, _: int) -> str:
    """Formate une graduation de l'axe des effectifs.

    Args:
        value (float): Valeur de la graduation.
        _ (int): Index de la graduation (ignoré, requis par Matplotlib).

    Returns:
        str: Libellé ASCII sûr pour l'axe Y.
    """
    if value < 0:
        return ""
    return _format_count_display(int(value))

def _plot_gender_performance_counts(
    counts_by_gender: Dict[str, int],
    *,
    title: str,
) -> plt.Figure:
    """Trace un diagramme en barres verticales F/M pour les effectifs globaux.

    Deux catégories seulement : encodage par longueur sur axe commun (Cleveland &
    McGill), palette Okabe-Ito, thème Pacing et libellés français.

    Args:
        counts_by_gender (Dict[str, int]): Effectifs indexés par code genre (``F``, ``M``).
        title (str): Titre affiché au-dessus du graphique.

    Returns:
        plt.Figure: Figure matplotlib du décompte par sexe.
    """
    gender_order = ("F", "M")
    labels = [_GENDER_LABEL_FEMALE, _GENDER_LABEL_MALE]
    values = [int(counts_by_gender.get(gender, 0)) for gender in gender_order]
    colors = [NON_CORRIDOR_COLOR_FEMALE, NON_CORRIDOR_COLOR_MALE]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(10, 6))
    _apply_standard_chart_theme(fig, ax)

    if total == 0:
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

    x_pos = np.arange(len(gender_order))
    bars = ax.bar(
        x_pos,
        values,
        width=0.55,
        color=colors,
        edgecolor="#ffffff",
        linewidth=0.8,
        zorder=3,
    )
    ymax = max(values)
    label_offset = ymax * 0.015 if ymax > 0 else 0.5
    for bar, value in zip(bars, values):
        share_pct = (100.0 * value / total) if total > 0 else 0.0
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + label_offset,
            f"{_format_count_display(value)} ({share_pct:.1f}%)",
            ha="center",
            va="bottom",
            fontsize=11,
            color="#334155",
            fontweight="medium",
            zorder=4,
        )
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Sexe")
    ax.set_ylabel("Nombre de performances")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_ylim(0, ymax * 1.14 if ymax > 0 else 1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, min_n_ticks=5))
    ax.yaxis.set_major_formatter(FuncFormatter(_format_performance_count_tick))
    ax.grid(
        axis="y",
        alpha=CORRIDOR_GRID_ALPHA,
        color="#94a3b8",
        linestyle="-",
        linewidth=0.6,
        zorder=0,
    )
    fig.tight_layout()
    return fig

_GENDER_PIE_COLORS: Dict[str, str] = {
    "F": NON_CORRIDOR_COLOR_FEMALE,
    "M": NON_CORRIDOR_COLOR_MALE,
}

def _plot_gender_pie_chart(
    counts_by_gender: Dict[str, int],
    *,
    title: str,
) -> plt.Figure:
    """Trace un diagramme en anneau F/M pour la répartition part-to-whole.

    Donut chart : palette Okabe-Ito, thème Pacing, effectif total au centre,
    pourcentages sur l'anneau et légende détaillée (libellés français).

    Args:
        counts_by_gender (Dict[str, int]): Effectifs indexés par code genre (``F``, ``M``).
        title (str): Titre affiché au-dessus du graphique.

    Returns:
        plt.Figure: Figure matplotlib de la répartition par sexe.
    """
    gender_order = ("F", "M")
    slices: List[Tuple[str, int, str, str]] = []
    for gender in gender_order:
        count = int(counts_by_gender.get(gender, 0))
        if count <= 0:
            continue
        slices.append(
            (
                gender,
                count,
                _gender_label_for_code(gender),
                _GENDER_PIE_COLORS.get(gender, NON_CORRIDOR_COLOR_NEUTRAL),
            )
        )
    total = sum(count for _, count, _, _ in slices)

    fig, ax = plt.subplots(figsize=(10, 7))
    _apply_standard_chart_theme(fig, ax)

    if total == 0:
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

    values = [count for _, count, _, _ in slices]
    colors = [color for _, _, _, color in slices]
    donut_width = 0.42

    wedges, _, autotexts = ax.pie(
        values,
        labels=None,
        autopct="%1.1f%%",
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={
            "width": donut_width,
            "edgecolor": "#ffffff",
            "linewidth": 1.4,
        },
        pctdistance=0.79,
        textprops={"fontsize": 11},
    )
    for autotext in autotexts:
        autotext.set_color("#ffffff")
        autotext.set_fontweight("bold")

    ax.text(
        0,
        0.06,
        _format_count_display(total),
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color="#1e293b",
    )
    ax.text(
        0,
        -0.1,
        "performances",
        ha="center",
        va="center",
        fontsize=10,
        color="#64748b",
    )

    legend_labels = [
        f"{label} — {_format_count_display(count)} ({100.0 * count / total:.1f}%)"
        for _, count, label, _ in slices
    ]
    ax.legend(
        wedges,
        legend_labels,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        framealpha=0.92,
        edgecolor="#cbd5e1",
        fontsize=10,
    )
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_aspect("equal")
    fig.tight_layout()
    return fig

def _histogram_time_tick_label(value: float, _: int) -> str:
    """Formate une graduation de l'axe temps selon l'ampleur de la valeur.

    Args:
        value (float): Position en secondes sur l'axe X.
        _ (int): Position de la graduation (ignorée, requise par Matplotlib).

    Returns:
        str: Libellé formaté pour l'axe des temps.
    """
    if value >= 100 or abs(value - round(value)) < 0.05:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"

def _apply_histogram_bin_xaxis(
    ax: plt.Axes,
    bin_edges: np.ndarray,
    nbins: int,
) -> float:
    """Aligne l'axe X sur les bords réels des classes d'histogramme.

    Chaque borne de classe est affichée comme graduation majeure afin que
    l'utilisateur puisse lire précisément les intervalles des bacs.

    Args:
        ax (plt.Axes): Axe matplotlib à configurer.
        bin_edges (np.ndarray): Bornes des classes (longueur ``nbins + 1``).
        nbins (int): Nombre de classes.

    Returns:
        float: Largeur moyenne d'une classe en secondes.
    """
    edges = np.asarray(bin_edges, dtype=float)
    ax.set_xlim(float(edges[0]), float(edges[-1]))
    bin_width = float(edges[1] - edges[0]) if len(edges) > 1 else 0.0

    ax.set_xticks(edges)
    ax.xaxis.set_major_formatter(FuncFormatter(_histogram_time_tick_label))
    label_size = 10
    if nbins > 30:
        label_size = 7
    elif nbins > 20:
        label_size = 8
    elif nbins > 12:
        label_size = 9
    plt.setp(
        ax.get_xticklabels(),
        rotation=90 if nbins > 24 else 45,
        ha="right",
        fontsize=label_size,
    )
    ax.tick_params(axis="x", which="major", length=4, width=0.9)
    if nbins > 12:
        ax.grid(axis="x", which="major", alpha=0.18, linestyle=":", linewidth=0.6)
    return bin_width

_HISTOGRAM_STATS_BBOX = {
    "boxstyle": "round,pad=0.35",
    "facecolor": "white",
    "alpha": 0.92,
    "edgecolor": "#cbd5e1",
}

def _histogram_xaxis_label_band(nbins: int) -> float:
    """Estime la hauteur des étiquettes X en fraction de la hauteur d'axe.

    Args:
        nbins (int): Nombre de classes affichées sur l'histogramme.

    Returns:
        float: Bande verticale réservée sous l'axe X (coordonnées ``axes``).
    """
    if nbins > 30:
        return 0.12
    if nbins > 20:
        return 0.09
    if nbins > 12:
        return 0.07
    return 0.05

def _apply_histogram_yaxis_label(ax: plt.Axes, ylabel: str) -> None:
    """Rapproche le libellé de l'axe Y de la zone de tracé.

    Args:
        ax (plt.Axes): Axe principal de l'histogramme.
        ylabel (str): Texte du libellé vertical ; ignoré si vide.

    Returns:
        None
    """
    if not ylabel:
        return
    label_x = -0.052 - 0.0018 * max(0, len(ylabel) - 18)
    label_x = max(label_x, -0.085)
    ax.set_ylabel(ylabel, labelpad=2)
    ax.yaxis.set_label_coords(label_x, 0.5)

def _place_histogram_stats_footnote(
    fig: plt.Figure,
    stats_text: str,
    *,
    ax: plt.Axes,
    nbins: int = 0,
    xlabel: str = "Temps (secondes)",
    ylabel: str = "Nombre de performances",
) -> None:
    """Place les statistiques descriptives sous la zone de tracé de l'histogramme.

    L'encadré est positionné avec un décalage relatif à la hauteur de l'axe
    (``transAxes``), afin de conserver un espacement stable quelle que soit la
    taille de la figure ou le nombre de classes. Le titre de l'axe X est placé
    entre les graduations et l'encadré statistique.

    Args:
        fig (plt.Figure): Figure matplotlib contenant l'histogramme.
        stats_text (str): Statistiques à afficher (une ou plusieurs lignes).
        ax (plt.Axes): Axe principal de l'histogramme.
        nbins (int): Nombre de classes affichées ; sert à réserver l'espace
            sous l'axe quand toutes les bornes sont étiquetées.
        xlabel (str): Libellé de l'axe des temps à afficher sous les graduations.
        ylabel (str): Libellé de l'axe des effectifs, rapproché du tracé.

    Returns:
        None
    """
    line_count = stats_text.count("\n") + 1
    if line_count <= 1:
        extra_lines = 0.0
    elif line_count == 2:
        extra_lines = 0.015
    else:
        extra_lines = 0.03

    label_band = _histogram_xaxis_label_band(nbins)
    xlabel_band = 0.04
    stats_gap = 0.022
    stats_height = 0.042 + extra_lines
    stats_offset = -(label_band + xlabel_band + stats_gap)
    bottom_margin = 0.06 + label_band + xlabel_band + stats_gap + stats_height

    fig.tight_layout(rect=[0, bottom_margin, 1, 0.98])
    _apply_histogram_yaxis_label(ax, ylabel)
    ax.set_xlabel(xlabel)
    ax.xaxis.set_label_coords(0.5, -(label_band + xlabel_band * 0.42))
    ax.text(
        0.5,
        stats_offset,
        stats_text.replace("\n", "   "),
        transform=ax.transAxes,
        ha="center",
        va="top",
        clip_on=False,
        fontsize=9.5,
        color="#0f172a",
        bbox=_HISTOGRAM_STATS_BBOX,
        zorder=10,
    )

def plot_corridor_swimmer_age_curve(
    ax: plt.Axes,
    long_df: pd.DataFrame,
    nom_nageur: str,
    year_of_birth: Optional[int] = None,
    *,
    color: str = CORRIDOR_OVERLAY_SWIMMER_COLOR,
    label: str = CORRIDOR_OVERLAY_SWIMMER_LABEL,
    fuzzy_min_ratio: float = 0.55,
) -> Optional[str]:
    """Trace un nageur sur un couloir âge/temps. Retourne un message d'erreur ou None."""
    spec = CorridorSwimmerSpec(
        name=str(nom_nageur).strip(),
        year_of_birth=year_of_birth,
        color=color,
        label=label,
    )
    msgs = plot_corridor_swimmer_specs(
        ax, long_df, [spec], fuzzy_min_ratio=fuzzy_min_ratio
    )
    return msgs[0] if msgs else None

RELAY_SPLIT_CHART_STYLE_VERSION = 2
