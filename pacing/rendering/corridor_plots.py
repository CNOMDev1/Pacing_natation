"""Rendu matplotlib des couloirs de performance et profils de pacing.

Ce module trace les bandes de percentiles/déciles et les nageurs cibles à
partir de données déjà calculées par ``pacing.analytics.corridor_data``. Il ne
calcule ni percentiles ni résolution de nageurs.

Attributes:
    Aucun attribut de module public au-delà des fonctions exportées.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from pacing.analytics.corridor_data import (
    CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR,
    CORRIDOR_ABOVE_MEDIAN_INNER_COLOR,
    CORRIDOR_ABOVE_MEDIAN_OUTER_COLOR,
    CORRIDOR_BAND_EDGE_ALPHA,
    CORRIDOR_BAND_INNER_ALPHA,
    CORRIDOR_BAND_OUTER_ALPHA,
    CORRIDOR_BELOW_MEDIAN_EDGE_COLOR,
    CORRIDOR_BELOW_MEDIAN_INNER_COLOR,
    CORRIDOR_BELOW_MEDIAN_OUTER_COLOR,
    CORRIDOR_CHART_AXES_FACECOLOR,
    CORRIDOR_CHART_FIGURE_FACECOLOR,
    CORRIDOR_GRID_ALPHA,
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
    fig.patch.set_facecolor(CORRIDOR_CHART_FIGURE_FACECOLOR)
    ax.set_facecolor(CORRIDOR_CHART_AXES_FACECOLOR)
    ax.grid(alpha=CORRIDOR_GRID_ALPHA, color="#94a3b8", linestyle="-", linewidth=0.6)


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
    below_median_outer_color: str = CORRIDOR_BELOW_MEDIAN_OUTER_COLOR,
    below_median_inner_color: str = CORRIDOR_BELOW_MEDIAN_INNER_COLOR,
    above_median_outer_color: str = CORRIDOR_ABOVE_MEDIAN_OUTER_COLOR,
    above_median_inner_color: str = CORRIDOR_ABOVE_MEDIAN_INNER_COLOR,
    median_color: str = CORRIDOR_MEDIAN_COLOR,
    median_linewidth: float = CORRIDOR_MEDIAN_LINEWIDTH,
    outer_alpha: float = CORRIDOR_BAND_OUTER_ALPHA,
    inner_alpha: float = CORRIDOR_BAND_INNER_ALPHA,
    outer_label_below: str = "Couloir P10–P50 (sous médiane)",
    outer_label_above: str = "Couloir P50–P90 (au-dessus médiane)",
    inner_label_below: str = "_nolegend_",
    inner_label_above: str = "_nolegend_",
    median_label: str = "Médiane du groupe",
    zorder_bands: int = 1,
    zorder_median: int = 3,
) -> None:
    """Trace un couloir percentile divergent autour de la médiane (P50).

    Les domaines P10–P90 et P25–P75 sont scindés en deux moitiés : sous la
    médiane (bleu, dégradé clair→foncé vers P50) et au-dessus (ambre, idem).
    La ligne médiane matérialise le point neutre (carte divergente, Munzner 2014).

    Args:
        ax: Axe matplotlib cible.
        x_values (Sequence): Abscisses alignées sur l'index de ``df_percentiles``.
        df_percentiles (pd.DataFrame): Colonnes ``p10``…``p90`` (ou équivalent).
        outer_low (str): Colonne borne basse externe (ex. ``p10``).
        outer_high (str): Colonne borne haute externe (ex. ``p90``).
        inner_low (str): Colonne borne basse interne (ex. ``p25``).
        inner_high (str): Colonne borne haute interne (ex. ``p75``).
        median_col (str): Colonne médiane (ex. ``p50``).
        below_median_outer_color (str): Couleur bande externe sous la médiane.
        below_median_inner_color (str): Couleur bande interne sous la médiane.
        above_median_outer_color (str): Couleur bande externe au-dessus de la médiane.
        above_median_inner_color (str): Couleur bande interne au-dessus de la médiane.
        median_color (str): Couleur ligne médiane (point neutre divergent).
        median_linewidth (float): Épaisseur de la ligne médiane.
        outer_alpha (float): Transparence bandes externes.
        inner_alpha (float): Transparence bandes internes.
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

    x = list(x_values)
    median = df_percentiles[median_col]

    has_outer = outer_low in df_percentiles.columns and outer_high in df_percentiles.columns
    has_inner = inner_low in df_percentiles.columns and inner_high in df_percentiles.columns

    if has_outer and len(x) > 1:
        ax.fill_between(
            x,
            df_percentiles[outer_low],
            median,
            color=below_median_outer_color,
            alpha=outer_alpha,
            linewidth=0,
            label=outer_label_below,
            zorder=zorder_bands,
        )
        ax.fill_between(
            x,
            median,
            df_percentiles[outer_high],
            color=above_median_outer_color,
            alpha=outer_alpha,
            linewidth=0,
            label=outer_label_above,
            zorder=zorder_bands,
        )
        for edge_col, edge_color in (
            (outer_low, CORRIDOR_BELOW_MEDIAN_EDGE_COLOR),
            (outer_high, CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR),
        ):
            ax.plot(
                x,
                df_percentiles[edge_col],
                color=edge_color,
                alpha=CORRIDOR_BAND_EDGE_ALPHA,
                linewidth=0.8,
                linestyle="-",
                label="_nolegend_",
                zorder=zorder_bands + 1,
            )

    if has_inner and len(x) > 1:
        ax.fill_between(
            x,
            df_percentiles[inner_low],
            median,
            color=below_median_inner_color,
            alpha=inner_alpha,
            linewidth=0,
            label=inner_label_below,
            zorder=zorder_bands + 2,
        )
        ax.fill_between(
            x,
            median,
            df_percentiles[inner_high],
            color=above_median_inner_color,
            alpha=inner_alpha,
            linewidth=0,
            label=inner_label_above,
            zorder=zorder_bands + 2,
        )

    ax.plot(
        x,
        median,
        color=median_color,
        linewidth=median_linewidth,
        linestyle="-",
        solid_capstyle="round",
        label=median_label,
        zorder=zorder_median,
    )
    if len(x) == 1:
        x0 = x[0]
        median_v = float(median.iloc[0])
        if has_outer:
            ax.scatter(
                [x0, x0],
                [
                    float(df_percentiles[outer_low].iloc[0]),
                    float(df_percentiles[outer_high].iloc[0]),
                ],
                color=[
                    CORRIDOR_BELOW_MEDIAN_EDGE_COLOR,
                    CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR,
                ],
                s=45,
                marker="_",
                linewidths=2.2,
                zorder=zorder_median + 1,
                label="_nolegend_",
            )
        if has_inner:
            ax.scatter(
                [x0, x0],
                [
                    float(df_percentiles[inner_low].iloc[0]),
                    float(df_percentiles[inner_high].iloc[0]),
                ],
                color=[
                    below_median_inner_color,
                    above_median_inner_color,
                ],
                s=40,
                marker="o",
                edgecolors="#1e293b",
                linewidths=0.8,
                alpha=0.9,
                zorder=zorder_median + 1,
                label="_nolegend_",
            )
        ax.scatter(
            [x0],
            [median_v],
            color=median_color,
            s=55,
            marker="o",
            edgecolors="#1e293b",
            linewidths=0.8,
            zorder=zorder_median + 2,
            label="_nolegend_",
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
