"""Rendu matplotlib des couloirs de performance et profils de pacing.

Ce module trace les bandes de percentiles/déciles et les nageurs cibles à
partir de données déjà calculées par ``pacing.analytics.corridor_data``. Il ne
calcule ni percentiles ni résolution de nageurs.

La structure du couloir percentile n'est plus décrite ici : elle vit dans
``pacing.grammar.corridor``, partagée avec NiceGUI, DearPyGUI et iOS. Ce module
n'en est qu'un point d'entrée pour le chemin Flet, qui part d'un DataFrame
pandas au lieu du payload de l'API.

Attributes:
    Aucun attribut de module public au-delà des fonctions exportées.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from pacing.analytics.corridor_data import (
    CORRIDOR_MA_SWIMMER_COLOR,
    CORRIDOR_MEDIAN_COLOR,
    CORRIDOR_MEDIAN_LINEWIDTH,
    CorridorSwimmerSeries,
    CorridorSwimmerSpec,
    DECILE_BAND_ALPHA,
    DECILE_BAND_COLORS_ABOVE_MEDIAN,
    DECILE_BAND_COLORS_BELOW_MEDIAN,
    DECILE_CORRIDOR_PERCENTILES,
    DECILE_EDGE_ABOVE_COLOR,
    DECILE_EDGE_ALPHA,
    DECILE_EDGE_BELOW_COLOR,
    NormalizedPacingSeries,
    build_corridor_swimmer_series,
    build_normalized_pacing_series,
)
from pacing.grammar.corridor import PACING_THEME, percentile_corridor_spec
from pacing.grammar.render_matplotlib import draw_layers


def corridor_swimmer_line_kwargs(spec: CorridorSwimmerSpec) -> Dict[str, Any]:
    """Style matplotlib pour un nageur : teinte + forme redondante (accessibilité).

    Le nageur marocain utilise un trait discontinu et des marqueurs carrés ;
    le nageur français/USA un trait plein et des cercles. La couleur reste
    le canal d'identité principale.

    Args:
        spec (CorridorSwimmerSpec): Nageur à tracer.

    Returns:
        Dict[str, Any]: Arguments ``plot`` / ``scatter`` matplotlib.
    """
    return _line_kwargs_from_color_label(spec.color, spec.label)


def _line_kwargs_from_color_label(color: str, label: str) -> Dict[str, Any]:
    """Construit les kwargs de trait à partir de la couleur et du libellé.

    Args:
        color (str): Couleur hex du nageur.
        label (str): Libellé de légende (détecte le style marocain).

    Returns:
        Dict[str, Any]: Arguments matplotlib pour ``plot`` / ``scatter``.
    """
    is_moroccan = color == CORRIDOR_MA_SWIMMER_COLOR or "maroc" in label.lower()
    if is_moroccan:
        return {
            "color": color,
            "linewidth": 3.2,
            "linestyle": "--",
            "marker": "s",
            "markersize": 8,
            "markeredgecolor": "#1e293b",
            "markeredgewidth": 1.0,
            "zorder": 8,
        }
    return {
        "color": color,
        "linewidth": 3.4,
        "linestyle": "-",
        "marker": "o",
        "markersize": 8,
        "markeredgecolor": "#1e293b",
        "markeredgewidth": 1.0,
        "zorder": 8,
    }


def apply_corridor_chart_theme(fig, ax) -> None:
    """Applique fond et grilles cohérents aux graphiques couloir.

    Args:
        fig: Figure matplotlib.
        ax: Axe principal.

    Returns:
        None
    """
    fig.patch.set_facecolor(PACING_THEME.figure_facecolor)
    ax.set_facecolor(PACING_THEME.axes_facecolor)
    ax.grid(
        alpha=PACING_THEME.grid_alpha,
        color=PACING_THEME.grid_color,
        linestyle="-",
        linewidth=PACING_THEME.grid_linewidth,
    )


def draw_percentile_corridor_bands(
    ax,
    x_values: Sequence,
    df_percentiles: pd.DataFrame,
    *,
    outer_low: str = "p10",
    outer_high: str = "p90",
    inner_low: str = "p25",
    inner_high: str = "p75",
    median_col: str = "p50",
    outer_label_below: str = "Couloir P10–P50 (sous médiane)",
    outer_label_above: str = "Couloir P50–P90 (au-dessus médiane)",
    inner_label_below: str = "_nolegend_",
    inner_label_above: str = "_nolegend_",
    median_label: str = "Médiane du groupe",
    zorder_bands: int = 1,
    zorder_median: int = 3,
) -> None:
    """Trace un couloir percentile divergent autour de la médiane (P50).

    Adaptateur du chemin pandas vers la grammaire : construit la recette avec
    ``percentile_corridor_spec`` puis la fait dessiner par le moteur commun.
    La structure des bandes (moitiés bleue et ambre autour du point neutre,
    carte divergente, Munzner 2014) est décrite dans ``pacing.grammar``.

    Les couleurs, opacités et épaisseurs ne sont plus paramétrables ici : elles
    appartiennent à la recette, afin que les quatre interfaces ne puissent pas
    en diverger.

    Args:
        ax: Axe matplotlib cible.
        x_values (Sequence): Abscisses alignées sur l'index de ``df_percentiles``.
        df_percentiles (pd.DataFrame): Colonnes ``p10``…``p90`` (ou équivalent).
        outer_low (str): Colonne borne basse externe (ex. ``p10``).
        outer_high (str): Colonne borne haute externe (ex. ``p90``).
        inner_low (str): Colonne borne basse interne (ex. ``p25``).
        inner_high (str): Colonne borne haute interne (ex. ``p75``).
        median_col (str): Colonne médiane (ex. ``p50``).
        outer_label_below (str): Libellé légende bande externe sous médiane.
        outer_label_above (str): Libellé légende bande externe au-dessus médiane.
        inner_label_below (str): Libellé légende bande interne sous médiane.
        inner_label_above (str): Libellé légende bande interne au-dessus médiane.
        median_label (str): Libellé légende médiane.
        zorder_bands (int): Plan de dessin des bandes.
        zorder_median (int): Plan de dessin de la médiane.

    Returns:
        None
    """
    if df_percentiles.empty:
        return
    if median_col not in df_percentiles.columns:
        return

    draw_layers(
        ax,
        percentile_corridor_spec(
            x_values,
            df_percentiles,
            outer_low=outer_low,
            outer_high=outer_high,
            inner_low=inner_low,
            inner_high=inner_high,
            median_col=median_col,
            outer_label_below=outer_label_below,
            outer_label_above=outer_label_above,
            inner_label_below=inner_label_below,
            inner_label_above=inner_label_above,
            median_label=median_label,
            zorder_bands=zorder_bands,
            zorder_median=zorder_median,
        ),
    )


def draw_decile_corridor_bands(
    ax,
    x_values: Sequence,
    df_deciles: pd.DataFrame,
    *,
    median_color: str = CORRIDOR_MEDIAN_COLOR,
    median_linewidth: float = CORRIDOR_MEDIAN_LINEWIDTH,
    band_alpha: float = DECILE_BAND_ALPHA,
    zorder_bands: int = 1,
    zorder_median: int = 12,
) -> None:
    """Trace un couloir en 10 bandes déciles (≈ 10 % du peloton chacune).

    Les bandes D10–D6 (Pmin→P50) utilisent une rampe bleue ; D5–D1 (P50→Pmax)
    une rampe ambre, avec la médiane P50 comme point de bascule divergent.

    Args:
        ax: Axe matplotlib cible.
        x_values (Sequence): Abscisses alignées sur l'index de ``df_deciles``.
        df_deciles (pd.DataFrame): Colonnes ``pmin``, ``p10``…``p90``, ``pmax``.
        median_color (str): Couleur de la ligne médiane (point neutre divergent).
        median_linewidth (float): Épaisseur de la ligne médiane.
        band_alpha (float): Transparence des bandes déciles.
        zorder_bands (int): Plan de dessin des bandes.
        zorder_median (int): Plan de dessin de la médiane.

    Returns:
        None
    """
    if df_deciles.empty:
        return
    x = list(x_values)
    boundary_cols = ["pmin"] + [f"p{p}" for p in DECILE_CORRIDOR_PERCENTILES] + ["pmax"]
    for col in boundary_cols:
        if col not in df_deciles.columns:
            return

    decile_labels = (
        "D10 (10 % les plus rapides)",
        "D9",
        "D8",
        "D7",
        "D6",
        "D5",
        "D4",
        "D3",
        "D2",
        "D1 (10 % les plus lents)",
    )
    median_split_idx = 5
    for idx in range(10):
        low_col = boundary_cols[idx]
        high_col = boundary_cols[idx + 1]
        if idx < median_split_idx:
            palette = DECILE_BAND_COLORS_BELOW_MEDIAN
            palette_idx = idx
            edge_color = DECILE_EDGE_BELOW_COLOR
        else:
            palette = DECILE_BAND_COLORS_ABOVE_MEDIAN
            palette_idx = idx - median_split_idx
            edge_color = DECILE_EDGE_ABOVE_COLOR
        color = palette[palette_idx] if palette_idx < len(palette) else "#808080"
        if len(x) > 1:
            ax.fill_between(
                x,
                df_deciles[low_col],
                df_deciles[high_col],
                color=color,
                alpha=band_alpha,
                linewidth=0,
                label=decile_labels[idx] if idx in (0, 9) else "_nolegend_",
                zorder=zorder_bands + idx,
            )
            ax.plot(
                x,
                df_deciles[high_col],
                color=edge_color,
                alpha=DECILE_EDGE_ALPHA,
                linewidth=0.55,
                linestyle="-",
                label="_nolegend_",
                zorder=zorder_bands + idx + 1,
            )
        else:
            x0 = x[0]
            y_mid = float(
                (df_deciles[low_col].iloc[0] + df_deciles[high_col].iloc[0]) / 2.0
            )
            ax.scatter(
                [x0],
                [y_mid],
                color=color,
                alpha=0.95,
                s=36,
                marker="s",
                edgecolors=edge_color,
                linewidths=0.7,
                label=decile_labels[idx] if idx in (0, 9) else "_nolegend_",
                zorder=zorder_bands + idx,
            )

    if "p50" in df_deciles.columns:
        ax.plot(
            x,
            df_deciles["p50"],
            color=median_color,
            linewidth=median_linewidth,
            linestyle="-",
            solid_capstyle="round",
            label="Médiane (D5)",
            zorder=zorder_median,
        )


def draw_corridor_swimmer_series(
    ax,
    series_list: Sequence[CorridorSwimmerSeries],
) -> None:
    """Trace des séries âge × temps déjà résolues sur un axe matplotlib.

    Args:
        ax: Axe matplotlib cible.
        series_list (Sequence[CorridorSwimmerSeries]): Séries métier à dessiner.

    Returns:
        None
    """
    for series in series_list:
        line_kw = _line_kwargs_from_color_label(series.color, series.label)
        ax.plot(
            list(series.ages),
            list(series.times),
            label=series.label,
            **line_kw,
        )
        ax.scatter(
            series.last_age,
            series.last_time,
            color=series.color,
            marker=line_kw.get("marker", "o"),
            s=(line_kw.get("markersize", 7) ** 2) * 1.8,
            edgecolors=line_kw.get("markeredgecolor", "white"),
            linewidths=line_kw.get("markeredgewidth", 0.9),
            zorder=line_kw.get("zorder", 7) + 1,
        )
        ax.annotate(
            series.annotation_text,
            (series.last_age, series.last_time),
            xytext=(8, 0),
            textcoords="offset points",
            color=series.color,
            fontsize=9,
            fontweight="bold",
        )


def draw_normalized_pacing_series(
    ax,
    series_list: Sequence[NormalizedPacingSeries],
) -> None:
    """Trace des profils de pacing normalisés déjà calculés.

    Args:
        ax: Axe matplotlib cible.
        series_list (Sequence[NormalizedPacingSeries]): Profils métier à dessiner.

    Returns:
        None
    """
    for series in series_list:
        line_kw = _line_kwargs_from_color_label(series.color, series.label)
        ax.plot(
            list(series.distances),
            list(series.speed_pct),
            label=series.label,
            **line_kw,
        )


def plot_corridor_swimmer_specs(
    ax,
    long_df: pd.DataFrame,
    specs: Sequence[CorridorSwimmerSpec],
    *,
    fuzzy_min_ratio: float = 0.55,
    source_df: Optional[pd.DataFrame] = None,
    nom_event: Optional[str] = None,
) -> List[str]:
    """Résout puis trace plusieurs nageurs (âge × temps) sur un axe matplotlib.

    Façade rendu : délègue la résolution à ``build_corridor_swimmer_series``
    puis appelle ``draw_corridor_swimmer_series``.

    Args:
        ax: Axe matplotlib cible.
        long_df (pd.DataFrame): Données longues du peloton.
        specs (Sequence[CorridorSwimmerSpec]): Nageurs à tracer.
        fuzzy_min_ratio (float): Seuil fuzzy pour la résolution.
        source_df (Optional[pd.DataFrame]): DataFrame brut pour diagnostics.
        nom_event (Optional[str]): Épreuve pour les messages d'absence.

    Returns:
        List[str]: Messages d'erreur ou d'avertissement par nageur introuvable.
    """
    series_list, messages = build_corridor_swimmer_series(
        long_df,
        specs,
        fuzzy_min_ratio=fuzzy_min_ratio,
        source_df=source_df,
        nom_event=nom_event,
    )
    draw_corridor_swimmer_series(ax, series_list)
    return messages


def plot_normalized_pacing_profiles_on_ax(
    ax,
    split_df: pd.DataFrame,
    specs: Sequence[CorridorSwimmerSpec],
) -> List[str]:
    """Trace les profils de pacing normalisés pour des nageurs cibles.

    Façade rendu : délègue le calcul à ``build_normalized_pacing_series``
    puis appelle ``draw_normalized_pacing_series``.

    Args:
        ax: Axe matplotlib cible.
        split_df (pd.DataFrame): Splits avec ``speed_pct``.
        specs (Sequence[CorridorSwimmerSpec]): Nageurs à superposer.

    Returns:
        List[str]: Messages d'avertissement par nageur introuvable.
    """
    series_list, messages = build_normalized_pacing_series(split_df, specs)
    draw_normalized_pacing_series(ax, series_list)
    return messages
