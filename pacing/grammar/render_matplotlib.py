"""Moteur Matplotlib de la grammaire Pacing.

Ce module traduit une ``ChartSpec`` en primitives Matplotlib. C'est le seul
endroit du code Python où l'on appelle ``fill_between``, ``bar``, ``bxp``,
``imshow``, ``plot`` ou ``scatter`` à partir d'une recette.

Il ne prend aucune décision d'apparence : couleurs, opacités, épaisseurs, sens
d'axe, unités et libellés viennent tous de la recette. Les trois interfaces
Python (Flet, NiceGUI, DearPyGUI) partagent ce moteur.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.figure import Figure

from pacing.grammar.spec import (
    Annotation,
    Area,
    Bar,
    Boxplot,
    ChartSpec,
    Heatmap,
    Histogram,
    Line,
    Point,
    Rule,
    Span,
    numeric_series,
)

_MARKERS: Dict[str, str] = {
    "circle": "o",
    "square": "s",
    "tick": "_",
}

_NO_LEGEND = "_nolegend_"

DEFAULT_FIGSIZE: Tuple[float, float] = (10.0, 5.5)


def _legend_label(label: Optional[str]) -> str:
    """Traduit un libellé de recette en libellé Matplotlib."""
    return label if label else _NO_LEGEND


def _draw_area(ax: Any, spec: ChartSpec, layer: Area) -> None:
    """Trace une géométrie « aire »."""
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
    """Trace une géométrie « ligne »."""
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
        kwargs["marker"] = _MARKERS.get(layer.marker, layer.marker)
        kwargs["markersize"] = layer.marker_size or 6.0
        kwargs["markeredgecolor"] = spec.theme.marker_edge_color
        kwargs["markeredgewidth"] = 1.0
    ax.plot(xs, ys, **kwargs)


def _draw_point(ax: Any, spec: ChartSpec, layer: Point) -> None:
    """Trace une géométrie « points »."""
    xs, ys = numeric_series(spec.table(layer.source), "x", layer.y)
    if not xs:
        return
    kwargs: Dict[str, Any] = {
        "color": layer.color,
        "s": layer.size,
        "marker": _MARKERS.get(layer.marker, layer.marker),
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


def _bar_series(spec: ChartSpec) -> List[Bar]:
    """Retourne les couches barres, pour le décalage groupé."""
    return [layer for layer in spec.layers if isinstance(layer, Bar)]


def _bar_xs(spec: ChartSpec, layer: Bar) -> List[float]:
    """Abscisses d'une couche barres."""
    xs, _ = numeric_series(spec.table(layer.source), "x", layer.y)
    return xs


def _bar_label(value: float, custom: Optional[str]) -> str:
    """Libellé d'une barre : texte fourni, sinon format numérique."""
    if custom:
        return custom
    if float(value).is_integer():
        return f"{value:.0f}"
    return f"{value:.2f}"


def _draw_bar(ax: Any, spec: ChartSpec, layer: Bar, *, series_index: int, series_count: int, dodge: bool) -> None:
    """Trace une géométrie « barres », avec décalage si séries groupées."""
    xs: List[float] = []
    ys: List[float] = []
    texts: List[Optional[str]] = []
    for row in spec.table(layer.source):
        try:
            xs.append(float(row["x"]))
            ys.append(float(row[layer.y]))
        except (KeyError, TypeError, ValueError):
            continue
        if layer.label_field:
            raw = row.get(layer.label_field)
            texts.append(None if raw is None else str(raw))
        else:
            texts.append(None)
    if not xs:
        return
    width = layer.width
    if dodge and series_count > 1:
        offset = (series_index - (series_count - 1) / 2.0) * width
        positions = [x + offset for x in xs]
    else:
        positions = list(xs)
    common = {
        "color": layer.fill,
        "alpha": layer.alpha,
        "edgecolor": "#ffffff",
        "linewidth": 0.7,
        "label": _legend_label(layer.label),
        "zorder": layer.zorder,
    }
    if layer.orientation == "horizontal":
        artists = ax.barh(positions, ys, height=width, **common)
        if layer.value_labels:
            xmax = max(ys) if ys else 0.0
            pad = xmax * 0.02 if xmax else 0.4
            for artist, value, custom in zip(artists, ys, texts):
                ax.text(
                    value + pad,
                    artist.get_y() + artist.get_height() / 2,
                    _bar_label(value, custom),
                    ha="left",
                    va="center",
                    fontsize=9,
                    color=spec.theme.annotation_color,
                    zorder=layer.zorder + 1,
                )
    else:
        artists = ax.bar(positions, ys, width=width, **common)
        if layer.value_labels:
            ymax = max(ys) if ys else 0.0
            pad = ymax * 0.015 if ymax else 0.4
            for artist, value, custom in zip(artists, ys, texts):
                ax.text(
                    artist.get_x() + artist.get_width() / 2,
                    value + pad,
                    _bar_label(value, custom),
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    color=spec.theme.annotation_color,
                    zorder=layer.zorder + 1,
                )


def _draw_histogram(ax: Any, spec: ChartSpec, layer: Histogram) -> None:
    """Trace un histogramme à partir de classes précalculées."""
    xs, ys = numeric_series(spec.table(layer.source), "x", layer.y)
    if not xs:
        return
    ax.bar(
        xs,
        ys,
        width=layer.width,
        color=layer.fill,
        alpha=layer.alpha,
        edgecolor="#ffffff",
        linewidth=0.8,
        align="center",
        label=_legend_label(layer.label),
        zorder=layer.zorder,
    )


def _draw_boxplot(ax: Any, spec: ChartSpec, layer: Boxplot) -> None:
    """Trace des boîtes à moustaches à partir de quartiles déclarés."""
    rows = spec.table(layer.source)
    stats: List[Dict[str, Any]] = []
    positions: List[float] = []
    for row in rows:
        try:
            positions.append(float(row["x"]))
            stats.append(
                {
                    "med": float(row["median"]),
                    "q1": float(row["q1"]),
                    "q3": float(row["q3"]),
                    "whislo": float(row["whislo"]),
                    "whishi": float(row["whishi"]),
                    "fliers": [],
                    "label": str(row.get("category", "")),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not stats:
        return
    ax.bxp(
        stats,
        positions=positions,
        widths=layer.width,
        showfliers=False,
        patch_artist=True,
        boxprops={
            "facecolor": layer.fill,
            "edgecolor": layer.edge_color,
            "alpha": 0.9,
            "linewidth": 1.3,
        },
        medianprops={"color": layer.median_color, "linewidth": 2.2},
        whiskerprops={"color": layer.edge_color, "linewidth": 1.1},
        capprops={"color": layer.edge_color, "linewidth": 1.1},
        zorder=layer.zorder,
    )


def _draw_heatmap(ax: Any, spec: ChartSpec, layer: Heatmap) -> None:
    """Trace une heatmap (matrice x × y)."""
    rows = spec.table(layer.source)
    if not rows:
        return
    xs = sorted({int(row[layer.x_field]) for row in rows if layer.x_field in row})
    ys = sorted({int(row[layer.y_field]) for row in rows if layer.y_field in row})
    if not xs or not ys:
        return
    matrix = np.full((len(ys), len(xs)), np.nan)
    annots = np.full((len(ys), len(xs)), "", dtype=object)
    x_index = {value: i for i, value in enumerate(xs)}
    y_index = {value: i for i, value in enumerate(ys)}
    for row in rows:
        try:
            col = x_index[int(row[layer.x_field])]
            lin = y_index[int(row[layer.y_field])]
            matrix[lin, col] = float(row[layer.value])
            if layer.annot:
                text = row.get(layer.annot)
                annots[lin, col] = "" if text is None else str(text)
        except (KeyError, TypeError, ValueError):
            continue
    vmin = layer.vmin
    vmax = layer.vmax
    finite = matrix[np.isfinite(matrix)]
    if vmin is None and finite.size:
        vmin = float(np.nanmin(finite))
    if vmax is None and finite.size:
        vmax = float(np.nanmax(finite))
    if vmin is None or vmax is None or not np.isfinite(vmin) or not np.isfinite(vmax):
        vmin, vmax = 0.0, 1.0
    if vmin >= vmax:
        vmax = vmin + 1.0
    norm = None
    if layer.center is not None:
        norm = TwoSlopeNorm(vmin=vmin, vcenter=layer.center, vmax=vmax)
    mesh = ax.imshow(
        matrix,
        origin="upper",
        aspect="auto",
        cmap=layer.cmap,
        vmin=None if norm else vmin,
        vmax=None if norm else vmax,
        norm=norm,
        zorder=layer.zorder,
    )
    if layer.annot:
        cmap = plt.get_cmap(layer.cmap)
        color_norm: Any = norm if norm is not None else Normalize(vmin=vmin, vmax=vmax)
        for lin in range(matrix.shape[0]):
            for col in range(matrix.shape[1]):
                text = annots[lin, col]
                if not text:
                    continue
                cell = matrix[lin, col]
                text_color = "#0f172a"
                if np.isfinite(cell):
                    rgba = cmap(color_norm(cell))
                    luminance = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
                    text_color = "#f8fafc" if luminance < 0.58 else "#0f172a"
                ax.text(
                    col,
                    lin,
                    text,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=text_color,
                    zorder=layer.zorder + 1,
                )
    if spec.x.categories:
        ax.set_xticks(list(range(len(spec.x.categories))))
        ax.set_xticklabels(list(spec.x.categories), rotation=45, ha="right")
    if spec.y.categories:
        ax.set_yticks(list(range(len(spec.y.categories))))
        ax.set_yticklabels(list(spec.y.categories))
    spec.meta.setdefault("_mappable", mesh)


def _draw_rule(ax: Any, spec: ChartSpec, layer: Rule) -> None:
    """Trace une ligne de référence constante."""
    kwargs: Dict[str, Any] = {
        "color": layer.color,
        "linewidth": layer.width,
        "alpha": layer.alpha,
        "label": _legend_label(layer.label),
        "zorder": layer.zorder,
    }
    if layer.dash:
        kwargs["linestyle"] = (0, tuple(layer.dash))
    if layer.axis == "x":
        ax.axvline(layer.value, **kwargs)
    else:
        ax.axhline(layer.value, **kwargs)


def _draw_span(ax: Any, spec: ChartSpec, layer: Span) -> None:
    """Trace une bande de référence."""
    kwargs: Dict[str, Any] = {
        "color": layer.fill,
        "alpha": layer.alpha,
        "label": _legend_label(layer.label),
        "zorder": layer.zorder,
        "linewidth": 0,
    }
    if layer.axis == "x":
        ax.axvspan(layer.start, layer.end, **kwargs)
    else:
        ax.axhspan(layer.start, layer.end, **kwargs)


def draw_layers(ax: Any, spec: ChartSpec) -> None:
    """Dessine les géométries d'une recette sur un axe existant."""
    bar_layers = _bar_series(spec)
    dodge = False
    if len(bar_layers) > 1:
        xs_tuples = [tuple(_bar_xs(spec, layer)) for layer in bar_layers]
        dodge = len(set(xs_tuples)) == 1
    bar_index = 0
    for layer in spec.layers:
        if isinstance(layer, Area):
            _draw_area(ax, spec, layer)
        elif isinstance(layer, Line):
            _draw_line(ax, spec, layer)
        elif isinstance(layer, Point):
            _draw_point(ax, spec, layer)
        elif isinstance(layer, Bar):
            _draw_bar(
                ax,
                spec,
                layer,
                series_index=bar_index,
                series_count=len(bar_layers),
                dodge=dodge,
            )
            bar_index += 1
        elif isinstance(layer, Histogram):
            _draw_histogram(ax, spec, layer)
        elif isinstance(layer, Boxplot):
            _draw_boxplot(ax, spec, layer)
        elif isinstance(layer, Heatmap):
            _draw_heatmap(ax, spec, layer)
        elif isinstance(layer, Rule):
            _draw_rule(ax, spec, layer)
        elif isinstance(layer, Span):
            _draw_span(ax, spec, layer)


def apply_theme(fig: Figure, ax: Any, spec: ChartSpec) -> None:
    """Applique la charte visuelle de la recette."""
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
    for spine_name in ("top", "right"):
        ax.spines[spine_name].set_visible(False)


def apply_scales(ax: Any, spec: ChartSpec) -> None:
    """Applique les échelles de la recette : libellés, ticks et sens d'axe."""
    if spec.x.label:
        ax.set_xlabel(spec.x.label)
    if spec.y.label:
        ax.set_ylabel(spec.y.label)
    heatmap_layers = [layer for layer in spec.layers if isinstance(layer, Heatmap)]
    if spec.x.kind == "categorical" and spec.x.categories and not heatmap_layers:
        positions = list(range(len(spec.x.categories)))
        if any(
            isinstance(layer, Bar) and layer.orientation == "horizontal"
            for layer in spec.layers
        ):
            ax.set_yticks(positions)
            ax.set_yticklabels(list(spec.x.categories))
        else:
            ax.set_xticks(positions)
            rotation = 45 if len(spec.x.categories) > 6 else 0
            ax.set_xticklabels(
                list(spec.x.categories),
                rotation=rotation,
                ha="right" if rotation else "center",
            )
    if spec.y.reverse:
        ax.invert_yaxis()
    if spec.x.reverse:
        ax.invert_xaxis()


def draw_annotations(fig: Figure, ax: Any, spec: ChartSpec) -> None:
    """Dessine les annotations déclarées (limites C5, message vide, notes)."""
    color = spec.theme.annotation_color
    for note in spec.annotations:
        note_color = note.color or color
        if note.loc == "footnote":
            fig.text(
                0.5,
                0.01,
                note.text,
                ha="center",
                va="bottom",
                fontsize=note.size,
                color=note_color,
                wrap=True,
            )
        elif note.loc == "center":
            ax.text(
                0.5,
                0.5,
                note.text,
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontsize=max(note.size, 11),
                color=note_color,
            )
            ax.set_axis_off()
        elif note.loc == "axes":
            ax.text(
                note.x if note.x is not None else 0.01,
                note.y if note.y is not None else 0.99,
                note.text,
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=note.size,
                color=note_color,
            )
        elif note.loc == "data" and note.x is not None and note.y is not None:
            ax.annotate(
                note.text,
                xy=(note.x, note.y),
                fontsize=note.size,
                color=note_color,
            )


def _draw_single_axes(fig: Figure, ax: Any, spec: ChartSpec) -> None:
    """Thème + couches + échelles + titre + légende sur un axe."""
    apply_theme(fig, ax, spec)
    draw_layers(ax, spec)
    apply_scales(ax, spec)
    heatmap_layer = next((layer for layer in spec.layers if isinstance(layer, Heatmap)), None)
    mappable = spec.meta.pop("_mappable", None)
    if (
        heatmap_layer is not None
        and heatmap_layer.colorbar
        and mappable is not None
        and getattr(mappable, "axes", None) is ax
    ):
        colorbar = fig.colorbar(mappable, ax=ax, shrink=0.85)
        if heatmap_layer.colorbar_label:
            colorbar.set_label(heatmap_layer.colorbar_label)
        ax.grid(False)
    if spec.title:
        ax.set_title(spec.title)
    handles, _labels = ax.get_legend_handles_labels()
    if handles and heatmap_layer is None:
        ax.legend(loc="best", frameon=False)
    draw_annotations(fig, ax, spec)


def render_figure(
    spec: ChartSpec,
    *,
    figsize: Optional[Tuple[float, float]] = None,
) -> Figure:
    """Rend une recette en figure Matplotlib complète.

    Si ``spec.panels`` est renseigné, produit des petits multiples (facettes).

    Args:
        spec (ChartSpec): Recette à rendre.
        figsize (Optional[Tuple[float, float]]): Surcharge de taille.

    Returns:
        Figure: Figure prête à être exportée ou affichée.
    """
    size = figsize or spec.figsize or DEFAULT_FIGSIZE
    if spec.panels:
        n_panels = len(spec.panels)
        ncol = spec.facet.ncol if spec.facet is not None else min(3, n_panels)
        ncol = max(1, ncol)
        nrow = int(math.ceil(n_panels / ncol))
        sharex = spec.facet.sharex if spec.facet is not None else False
        sharey = spec.facet.sharey if spec.facet is not None else False
        fig, axes = plt.subplots(
            nrow,
            ncol,
            figsize=size,
            layout="constrained",
            sharex=sharex,
            sharey=sharey,
        )
        axes_list: Sequence[Any]
        if n_panels == 1:
            axes_list = [axes]
        else:
            axes_list = list(np.array(axes).ravel())
        for index, axis in enumerate(axes_list):
            if index >= n_panels:
                axis.set_axis_off()
                continue
            panel = spec.panels[index]
            _draw_single_axes(fig, axis, panel)
        if spec.title:
            fig.suptitle(spec.title)
        draw_annotations(fig, axes_list[0] if axes_list else None, spec)
        return fig

    fig, ax = plt.subplots(figsize=size, layout="constrained")
    _draw_single_axes(fig, ax, spec)
    return fig
