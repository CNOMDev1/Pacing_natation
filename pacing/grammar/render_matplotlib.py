"""Moteur Matplotlib de la grammaire Pacing.

Ce module traduit une ``ChartSpec`` en primitives Matplotlib. C'est désormais
le seul endroit du code Python où l'on appelle ``fill_between``, ``plot`` ou
``scatter`` pour un couloir de performance.

Il ne prend aucune décision d'apparence : couleurs, opacités, épaisseurs, sens
d'axe, unités et libellés viennent tous de la recette. Les trois interfaces
Python (Flet, NiceGUI, DearPyGUI) partagent ce moteur ; elles ne diffèrent que
par la manière de porter la ``Figure`` à l'écran — base64 pour le navigateur,
texture GPU pour DearPyGUI, widget image pour Flet.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from pacing.grammar.spec import Area, ChartSpec, Line, Point, numeric_series

#: Traduction des formes de marqueurs de la recette vers Matplotlib.
_MARKERS: Dict[str, str] = {
    "circle": "o",
    "square": "s",
    "tick": "_",
}

#: Matplotlib exclut de la légende les artistes portant ce libellé.
_NO_LEGEND = "_nolegend_"

#: Dimensions par défaut d'une figure couloir (pouces).
DEFAULT_FIGSIZE: Tuple[float, float] = (10.0, 5.5)


def _legend_label(label: Optional[str]) -> str:
    """Traduit un libellé de recette en libellé Matplotlib.

    Args:
        label (Optional[str]): Libellé, ``None`` si hors légende.

    Returns:
        str: Libellé Matplotlib.
    """
    return label if label else _NO_LEGEND


def _draw_area(ax: Any, spec: ChartSpec, layer: Area) -> None:
    """Trace une géométrie « aire ».

    Args:
        ax (Any): Axe Matplotlib cible.
        spec (ChartSpec): Recette fournissant les données.
        layer (Area): Géométrie à tracer.

    Returns:
        None
    """
    xs, lows, highs = numeric_series(
        spec.table(layer.source), "x", layer.ymin, layer.ymax
    )
    if len(xs) < 2:
        return
    ax.fill_between(
        xs,
        lows,
        highs,
        color=layer.fill,
        alpha=layer.alpha,
        linewidth=0,
        label=_legend_label(layer.label),
        zorder=layer.zorder,
    )


def _draw_line(ax: Any, spec: ChartSpec, layer: Line) -> None:
    """Trace une géométrie « ligne ».

    Args:
        ax (Any): Axe Matplotlib cible.
        spec (ChartSpec): Recette fournissant les données.
        layer (Line): Géométrie à tracer.

    Returns:
        None
    """
    xs, ys = numeric_series(spec.table(layer.source), "x", layer.y)
    if not xs:
        return
    kwargs: Dict[str, Any] = {
        "color": layer.color,
        "linewidth": layer.width,
        "alpha": layer.alpha,
        "label": _legend_label(layer.label),
        "zorder": layer.zorder,
        "solid_capstyle": "round",
    }
    if layer.dash:
        kwargs["linestyle"] = (0, tuple(layer.dash))
    else:
        kwargs["linestyle"] = "-"
    if layer.marker:
        kwargs["marker"] = _MARKERS.get(layer.marker, "o")
        kwargs["markersize"] = layer.marker_size or 6.0
        kwargs["markeredgecolor"] = spec.theme.marker_edge_color
        kwargs["markeredgewidth"] = 1.0
    ax.plot(xs, ys, **kwargs)


def _draw_point(ax: Any, spec: ChartSpec, layer: Point) -> None:
    """Trace une géométrie « points ».

    Args:
        ax (Any): Axe Matplotlib cible.
        spec (ChartSpec): Recette fournissant les données.
        layer (Point): Géométrie à tracer.

    Returns:
        None
    """
    xs, ys = numeric_series(spec.table(layer.source), "x", layer.y)
    if not xs:
        return
    kwargs: Dict[str, Any] = {
        "color": layer.color,
        "s": layer.size,
        "marker": _MARKERS.get(layer.marker, "o"),
        "alpha": layer.alpha,
        "label": _legend_label(layer.label),
        "zorder": layer.zorder,
    }
    if layer.marker == "tick":
        kwargs["linewidths"] = 2.2
    else:
        kwargs["edgecolors"] = spec.theme.marker_edge_color
        kwargs["linewidths"] = 0.8
    ax.scatter(xs, ys, **kwargs)


def draw_layers(ax: Any, spec: ChartSpec) -> None:
    """Dessine les géométries d'une recette sur un axe existant.

    Utile lorsqu'un écran superpose d'autres tracés autour du couloir : l'axe,
    le titre et le thème restent sous le contrôle de l'appelant.

    Args:
        ax (Any): Axe Matplotlib cible.
        spec (ChartSpec): Recette à dessiner.

    Returns:
        None
    """
    for layer in spec.layers:
        if isinstance(layer, Area):
            _draw_area(ax, spec, layer)
        elif isinstance(layer, Line):
            _draw_line(ax, spec, layer)
        elif isinstance(layer, Point):
            _draw_point(ax, spec, layer)


def apply_theme(fig: Figure, ax: Any, spec: ChartSpec) -> None:
    """Applique la charte visuelle de la recette.

    Args:
        fig (Figure): Figure Matplotlib.
        ax (Any): Axe principal.
        spec (ChartSpec): Recette portant le thème.

    Returns:
        None
    """
    theme = spec.theme
    fig.patch.set_facecolor(theme.figure_facecolor)
    ax.set_facecolor(theme.axes_facecolor)
    ax.grid(
        True,
        alpha=theme.grid_alpha,
        color=theme.grid_color,
        linestyle="-",
        linewidth=theme.grid_linewidth,
    )


def apply_scales(ax: Any, spec: ChartSpec) -> None:
    """Applique les échelles de la recette : libellés, ticks et sens d'axe.

    Le sens de l'axe des temps est une décision de la recette
    (``Scale.reverse``) ; seule sa mise en œuvre est propre à Matplotlib.

    Args:
        ax (Any): Axe Matplotlib cible.
        spec (ChartSpec): Recette portant les échelles.

    Returns:
        None
    """
    ax.set_xlabel(spec.x.label)
    ax.set_ylabel(spec.y.label)
    if spec.x.kind == "categorical" and spec.x.categories:
        positions = list(range(len(spec.x.categories)))
        ax.set_xticks(positions)
        ax.set_xticklabels(list(spec.x.categories), rotation=45, ha="right")
    if spec.y.reverse:
        ax.invert_yaxis()
    if spec.x.reverse:
        ax.invert_xaxis()


def render_figure(
    spec: ChartSpec,
    *,
    figsize: Tuple[float, float] = DEFAULT_FIGSIZE,
) -> Figure:
    """Rend une recette en figure Matplotlib complète.

    Args:
        spec (ChartSpec): Recette à rendre.
        figsize (Tuple[float, float]): Dimensions de la figure en pouces.

    Returns:
        Figure: Figure prête à être exportée ou affichée.
    """
    fig, ax = plt.subplots(figsize=figsize, layout="constrained")
    apply_theme(fig, ax, spec)
    draw_layers(ax, spec)
    apply_scales(ax, spec)
    if spec.title:
        ax.set_title(spec.title)
    if spec.legend:
        ax.legend(loc="best", frameon=False)
    return fig
