"""Recettes des familles de graphiques F1–F14.

Les transformations statistiques restent calculées en amont (choix acté de
l'inventaire). Ce module ne fait que *décrire* le graphique : géométries,
échelles, thème, annotations de limites (C5).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pacing.grammar.corridor import PACING_THEME, corridor_band_layers
from pacing.grammar.spec import (
    Annotation,
    Area,
    Bar,
    Boxplot,
    ChartSpec,
    Facet,
    Heatmap,
    Histogram,
    LegendEntry,
    Line,
    Point,
    Rule,
    Scale,
    Span,
)

COLOR_PRIMARY = "#2E5EAA"
COLOR_SECONDARY = "#E69F00"
COLOR_TARGET = "#D55E00"
COLOR_NEUTRAL = "#374151"
COLOR_FEMALE = "#CC79A7"
COLOR_MALE = "#0072B2"
COLOR_IQR = "#FDE68A"
STROKE_COLORS: Dict[str, str] = {
    "Nage libre": "#0072B2",
    "Dos": "#56B4E9",
    "Brasse": "#E69F00",
    "Papillon": "#009E73",
    "4 nages": "#CC79A7",
}


def _note(text: str, *, loc: str = "footnote") -> Annotation:
    """Annotation de limites d'interprétation (critère C5)."""
    return Annotation(text=text, loc=loc)


def empty_spec(title: str, message: str, *, kind: str = "empty") -> ChartSpec:
    """Recette d'état vide, message centré."""
    return ChartSpec(
        kind=kind,
        title=title,
        data={},
        mapping={},
        x=Scale(label=""),
        y=Scale(label=""),
        layers=(),
        theme=PACING_THEME,
        annotations=(_note(message, loc="center"),),
    )


def histogram_spec(
    *,
    centers: Sequence[float],
    counts: Sequence[float],
    bin_width: float,
    mean: float,
    median: float,
    q1: float,
    q3: float,
    title: str,
    stats_text: str,
    n_perf: int,
    xlabel: str = "Temps (s)",
    ylabel: str = "Nombre de performances",
) -> ChartSpec:
    """F1 — histogramme des temps (classes calculées en amont)."""
    bins = tuple(
        {"x": float(center), "y": float(count)}
        for center, count in zip(centers, counts)
    )
    return ChartSpec(
        kind="histogram",
        title=title,
        data={"bins": bins},
        mapping={"x": "SwimTimeSeconds", "y": "count"},
        stat="histogram_bins(adaptive) + percentiles(25,50,75)",
        x=Scale(label=xlabel, unit="s", tick_format="seconds"),
        y=Scale(label=ylabel, tick_format="integer"),
        layers=(
            Span(
                axis="x",
                start=float(q1),
                end=float(q3),
                fill=COLOR_SECONDARY,
                alpha=0.12,
                label="Intervalle interquartile (Q1-Q3)",
            ),
            Histogram(
                source="bins",
                y="y",
                fill=COLOR_PRIMARY,
                width=float(bin_width) * 0.96,
                label="Effectif",
            ),
            Rule(
                axis="x",
                value=float(mean),
                color=COLOR_TARGET,
                dash=(6.0, 3.0),
                width=2.2,
                label="Moyenne",
            ),
            Rule(
                axis="x",
                value=float(median),
                color=COLOR_SECONDARY,
                dash=(3.0, 2.0),
                width=2.4,
                label="Médiane",
            ),
        ),
        theme=PACING_THEME,
        legend=(
            LegendEntry("Effectif", COLOR_PRIMARY, kind="swatch"),
            LegendEntry("Moyenne", COLOR_TARGET, kind="line", dash=(6.0, 3.0)),
            LegendEntry("Médiane", COLOR_SECONDARY, kind="line", dash=(3.0, 2.0)),
        ),
        annotations=(
            _note(stats_text, loc="axes"),
            _note(
                "Limites : le binning dépend du périmètre ; l'histogramme décrit "
                f"la distribution des chronos (n={n_perf}), pas le pacing intra-course."
            ),
        ),
        figsize=(12.0, 8.0),
        meta={"n": n_perf},
    )


def grouped_bar_spec(
    *,
    categories: Sequence[str],
    series: Mapping[str, Sequence[float]],
    colors: Mapping[str, str],
    title: str,
    xlabel: str,
    ylabel: str,
    orientation: str = "horizontal",
    note: str,
    figsize: Optional[Tuple[float, float]] = None,
) -> ChartSpec:
    """F2 / F3 — barres groupées (effectifs par épreuve × sexe, ou par sexe)."""
    if not categories:
        return empty_spec(title, "Aucune performance disponible pour ce périmètre.")
    data: Dict[str, Tuple[Dict[str, Any], ...]] = {}
    layers: List[Any] = []
    legend: List[LegendEntry] = []
    for name, values in series.items():
        rows = tuple(
            {"x": float(index), "y": float(value)}
            for index, value in enumerate(values)
        )
        data[name] = rows
        fill = colors.get(name, COLOR_PRIMARY)
        layers.append(
            Bar(
                source=name,
                y="y",
                fill=fill,
                orientation=orientation,
                width=0.36 if len(series) > 1 else 0.55,
                label=name,
                value_labels=True,
            )
        )
        legend.append(LegendEntry(name, fill, kind="swatch"))
    reverse = orientation == "horizontal"
    n = len(categories)
    height = max(7.0, min(22.0, n * 0.38 + 1.8)) if orientation == "horizontal" else 6.0
    return ChartSpec(
        kind="bar",
        title=title,
        data=data,
        mapping={"x": ylabel, "y": xlabel},
        stat="count group_by=category,series",
        x=Scale(
            label=ylabel if orientation == "horizontal" else xlabel,
            kind="categorical",
            categories=tuple(categories),
            reverse=reverse,
        ),
        y=Scale(
            label=xlabel if orientation == "horizontal" else ylabel,
            tick_format="integer",
        ),
        layers=tuple(layers),
        theme=PACING_THEME,
        legend=tuple(legend),
        annotations=(_note(note),),
        figsize=figsize or ((14.0, height) if orientation == "horizontal" else (10.0, 6.0)),
    )


def category_bar_spec(
    *,
    categories: Sequence[str],
    values: Sequence[float],
    fills: Sequence[str],
    title: str,
    xlabel: str,
    ylabel: str,
    note: str,
    orientation: str = "vertical",
    value_texts: Optional[Sequence[str]] = None,
) -> ChartSpec:
    """F3 — une barre par catégorie, couleurs distinctes, sans décalage."""
    if not categories or not any(values):
        return empty_spec(title, "Aucune performance disponible pour ce périmètre.")
    data: Dict[str, Tuple[Dict[str, Any], ...]] = {}
    layers: List[Any] = []
    legend: List[LegendEntry] = []
    for index, (name, value, fill) in enumerate(zip(categories, values, fills)):
        row: Dict[str, Any] = {"x": float(index), "y": float(value)}
        if value_texts is not None and index < len(value_texts):
            row["text"] = value_texts[index]
        data[name] = (row,)
        layers.append(
            Bar(
                source=name,
                y="y",
                fill=fill,
                orientation=orientation,
                width=0.55,
                label=name,
                value_labels=True,
                label_field="text" if "text" in row else None,
            )
        )
        legend.append(LegendEntry(name, fill, kind="swatch"))
    return ChartSpec(
        kind="bar",
        title=title,
        data=data,
        mapping={"x": xlabel, "y": ylabel},
        stat="count group_by=category",
        x=Scale(
            label=xlabel,
            kind="categorical",
            categories=tuple(categories),
        ),
        y=Scale(label=ylabel, tick_format="integer"),
        layers=tuple(layers),
        theme=PACING_THEME,
        legend=tuple(legend),
        annotations=(_note(note),),
        figsize=(10.0, 6.0),
    )


def ranked_bar_spec(
    *,
    categories: Sequence[str],
    values: Sequence[float],
    fills: Sequence[str],
    title: str,
    xlabel: str,
    ylabel: str,
    note: str,
    value_texts: Optional[Sequence[str]] = None,
) -> ChartSpec:
    """F5 — barres horizontales classées (clubs, nageurs)."""
    if not categories:
        return empty_spec(title, "Aucune performance disponible pour ce périmètre.")
    palette = list(fills) if fills else [COLOR_PRIMARY] * len(values)
    data: Dict[str, Tuple[Dict[str, Any], ...]] = {}
    layers: List[Any] = []
    for index, value in enumerate(values):
        row: Dict[str, Any] = {"x": float(index), "y": float(value)}
        if value_texts is not None and index < len(value_texts):
            row["text"] = value_texts[index]
        key = f"bar{index}"
        data[key] = (row,)
        fill = palette[index] if index < len(palette) else COLOR_PRIMARY
        layers.append(
            Bar(
                source=key,
                y="y",
                fill=fill,
                orientation="horizontal",
                width=0.62,
                value_labels=True,
                label_field="text" if "text" in row else None,
            )
        )
    height = max(5.0, min(12.0, len(categories) * 0.62 + 1.8))
    return ChartSpec(
        kind="ranked_bar",
        title=title,
        data=data,
        mapping={"x": ylabel, "y": xlabel},
        stat="rank(top_n)",
        x=Scale(
            label=ylabel,
            kind="categorical",
            categories=tuple(categories),
            reverse=True,
        ),
        y=Scale(label=xlabel),
        layers=tuple(layers),
        theme=PACING_THEME,
        annotations=(_note(note),),
        figsize=(12.0, height),
    )


def boxplot_spec(
    *,
    categories: Sequence[str],
    stats: Sequence[Mapping[str, float]],
    outliers: Sequence[Mapping[str, float]],
    fills: Sequence[str],
    title: str,
    ylabel: str,
    note: str,
) -> ChartSpec:
    """F4 — boxplot des temps par nage."""
    if not categories:
        return empty_spec(title, "Aucune performance disponible pour ce périmètre.")
    rows = []
    layers: List[Any] = []
    for index, (category, row, fill) in enumerate(zip(categories, stats, fills)):
        key = f"box{index}"
        payload = {
            "x": float(index),
            "category": category,
            "q1": float(row["q1"]),
            "median": float(row["median"]),
            "q3": float(row["q3"]),
            "whislo": float(row["whislo"]),
            "whishi": float(row["whishi"]),
        }
        rows.append(payload)
        layers.append(
            Boxplot(source=key, fill=fill, label=category)
        )
        # une table par boîte pour colorer indépendamment
    data = {f"box{i}": (dict(row),) for i, row in enumerate(rows)}
    outlier_rows = tuple(
        {"x": float(item["x"]), "y": float(item["y"])} for item in outliers
    )
    if outlier_rows:
        data["outliers"] = outlier_rows
        layers.append(
            Point(
                source="outliers",
                y="y",
                color=COLOR_NEUTRAL,
                size=12.0,
                alpha=0.35,
                zorder=4,
            )
        )
    return ChartSpec(
        kind="boxplot",
        title=title,
        data=data,
        mapping={"x": "Stroke", "y": "SwimTimeSeconds"},
        stat="boxplot(q1,median,q3,whiskers) group_by=stroke",
        x=Scale(label="Nage", kind="categorical", categories=tuple(categories)),
        y=Scale(label=ylabel, unit="s", tick_format="seconds"),
        layers=tuple(layers),
        theme=PACING_THEME,
        annotations=(_note(note),),
        figsize=(12.0, 8.0),
    )


def facet_lines_spec(
    *,
    panels: Sequence[Mapping[str, Any]],
    title: str,
    xlabel: str,
    ylabel: str,
    note: str,
    ncol: int = 2,
    sharey: bool = False,
) -> ChartSpec:
    """F6 — petits multiples (une courbe par panneau)."""
    if not panels:
        return empty_spec(title, "Aucune performance disponible pour ce périmètre.")
    children: List[ChartSpec] = []
    for panel in panels:
        label = str(panel["label"])
        color = str(panel.get("color") or STROKE_COLORS.get(label, COLOR_PRIMARY))
        raw = tuple(
            {"x": float(x), "y": float(y)}
            for x, y in zip(panel.get("x_raw") or (), panel.get("y_raw") or ())
        )
        smooth = tuple(
            {"x": float(x), "y": float(y)}
            for x, y in zip(panel.get("x") or (), panel.get("y") or ())
        )
        panel_notes: Tuple[Annotation, ...] = ()
        if not raw and not smooth:
            panel_notes = (_note("Données insuffisantes\n(effectif annuel trop faible).", loc="center"),)
        children.append(
            ChartSpec(
                kind="line",
                title=label,
                data={"raw": raw, "smooth": smooth},
                mapping={"x": xlabel, "y": ylabel},
                x=Scale(label=xlabel),
                y=Scale(label=ylabel, unit=panel.get("unit"), reverse=bool(panel.get("reverse"))),
                layers=(
                    Line(
                        source="raw",
                        y="y",
                        color=color,
                        width=1.0,
                        alpha=0.35,
                        zorder=2,
                    ),
                    Line(
                        source="smooth",
                        y="y",
                        color=color,
                        width=2.4,
                        zorder=3,
                        label=label,
                    ),
                ),
                theme=PACING_THEME,
                annotations=panel_notes,
            )
        )
    n = len(children)
    nrow = int((n + ncol - 1) / ncol)
    return ChartSpec(
        kind="facet_lines",
        title=title,
        data={},
        mapping={},
        x=Scale(label=xlabel),
        y=Scale(label=ylabel),
        layers=(),
        theme=PACING_THEME,
        panels=tuple(children),
        facet=Facet(ncol=ncol, sharex=True, sharey=sharey),
        annotations=(_note(note),),
        figsize=(14.0, max(4.5, 3.6 * nrow)),
        stat="median_by_year + rolling_mean; facet=stroke",
    )


def multiline_spec(
    *,
    series: Sequence[Mapping[str, Any]],
    title: str,
    xlabel: str,
    ylabel: str,
    note: str,
    unit: Optional[str] = "m/s",
    empty_message: str = "Aucune performance disponible pour ce périmètre.",
) -> ChartSpec:
    """F7 / F8 — plusieurs lignes (vitesse × distance × nage, ou splits)."""
    if not series:
        return empty_spec(title, empty_message)
    data: Dict[str, Tuple[Dict[str, Any], ...]] = {}
    layers: List[Any] = []
    legend: List[LegendEntry] = []
    for item in series:
        name = str(item["label"])
        color = str(item.get("color") or STROKE_COLORS.get(name, COLOR_PRIMARY))
        geom = str(item.get("geom") or "line")
        rows = tuple(
            {"x": float(x), "y": float(y)}
            for x, y in zip(item["x"], item["y"])
        )
        data[name] = rows
        if geom == "point":
            layers.append(
                Point(
                    source=name,
                    y="y",
                    color=color,
                    size=float(item.get("size", 28.0)),
                    marker=str(item.get("marker") or "circle"),
                    label=name,
                )
            )
        else:
            layers.append(
                Line(
                    source=name,
                    y="y",
                    color=color,
                    width=2.2,
                    marker=item.get("marker"),
                    marker_size=6.0,
                    label=name,
                )
            )
        legend.append(LegendEntry(name, color, kind="line"))
    return ChartSpec(
        kind="multiline",
        title=title,
        data=data,
        mapping={"x": xlabel, "y": ylabel},
        x=Scale(label=xlabel),
        y=Scale(label=ylabel, unit=unit),
        layers=tuple(layers),
        theme=PACING_THEME,
        legend=tuple(legend),
        annotations=(_note(note),),
        figsize=(14.0, 8.0),
        stat=str(series[0].get("stat") or "median group_by=x,series"),
    )


def heatmap_spec(
    *,
    x_categories: Sequence[str],
    y_categories: Sequence[str],
    cells: Sequence[Mapping[str, Any]],
    title: str,
    cmap: str,
    note: str,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    center: Optional[float] = None,
    xlabel: str = "Nage",
    ylabel: str = "Distance",
    colorbar: bool = True,
    colorbar_label: str = "Valeur",
) -> ChartSpec:
    """F9 — heatmap distance × nage."""
    if not cells:
        return empty_spec(title, "Pas de données disponibles")
    rows = tuple(
        {
            "x": int(cell["x"]),
            "y": int(cell["y"]),
            "value": float(cell["value"]),
            "annot": str(cell.get("annot", "")),
        }
        for cell in cells
    )
    return ChartSpec(
        kind="heatmap",
        title=title,
        data={"cells": rows},
        mapping={"x": xlabel, "y": ylabel, "color": "median_speed"},
        stat="median(speed) group_by=distance,stroke",
        x=Scale(label=xlabel, kind="categorical", categories=tuple(x_categories)),
        y=Scale(label=ylabel, kind="categorical", categories=tuple(y_categories)),
        layers=(
            Heatmap(
                source="cells",
                value="value",
                cmap=cmap,
                annot="annot",
                vmin=vmin,
                vmax=vmax,
                center=center,
                colorbar=colorbar,
                colorbar_label=colorbar_label,
            ),
        ),
        theme=PACING_THEME,
        annotations=(_note(note),),
        figsize=(12.0, 7.0),
    )


def heatmap_panels_spec(
    *,
    panels: Sequence[ChartSpec],
    title: str,
    note: str,
    figsize: Optional[Tuple[float, float]] = None,
) -> ChartSpec:
    """F10 — heatmaps coordonnées nageur / peloton / écart."""
    if not panels:
        return empty_spec(title, "Pas de données disponibles")
    return ChartSpec(
        kind="heatmap_panels",
        title=title,
        data={},
        mapping={},
        x=Scale(label=""),
        y=Scale(label=""),
        layers=(),
        theme=PACING_THEME,
        panels=tuple(panels),
        facet=Facet(ncol=len(panels), sharex=True, sharey=True),
        annotations=(_note(note),),
        figsize=figsize or (16.0, 5.8),
        stat="median(speed) nageur vs peloton; facet=panel",
    )


def pacing_profile_spec(
    *,
    x_values: Sequence[float],
    q1: Sequence[float],
    q3: Sequence[float],
    median: Sequence[float],
    series: Sequence[Mapping[str, Any]],
    title: str,
    xlabel: str,
    ylabel: str,
    note: str,
    x_labels: Optional[Sequence[str]] = None,
    iqr_color: str = COLOR_IQR,
    iqr_label: str = "IQR peloton (Q1–Q3)",
    median_label: str = "Médiane peloton",
    rule_y: Optional[float] = None,
    rule_label: Optional[str] = None,
    unit: str = "m/s",
    additional_bands: Sequence[Mapping[str, Any]] = (),
) -> ChartSpec:
    """F11 / F12 / F14 — profil de pacing (bande IQR + courbes)."""
    band = tuple(
        {"x": float(x), "q1": float(low), "q3": float(high), "median": float(mid)}
        for x, low, high, mid in zip(x_values, q1, q3, median)
    )
    data: Dict[str, Tuple[Dict[str, Any], ...]] = {}
    layers: List[Any] = []
    if band:
        data["band"] = band
        layers.extend(
            [
                Area(
                    source="band",
                    ymin="q1",
                    ymax="q3",
                    fill=iqr_color,
                    alpha=0.35,
                    label=iqr_label,
                    zorder=1,
                ),
                Line(
                    source="band",
                    y="median",
                    color=COLOR_SECONDARY,
                    width=2.4,
                    dash=(5.0, 3.0),
                    marker="square",
                    marker_size=6.0,
                    label=median_label,
                    zorder=4,
                ),
            ]
        )
    for extra_index, extra in enumerate(additional_bands):
        key = f"band{extra_index + 1}"
        extra_rows = tuple(
            {
                "x": float(x),
                "q1": float(low),
                "q3": float(high),
                "median": float(mid),
            }
            for x, low, high, mid in zip(extra["x"], extra["q1"], extra["q3"], extra["median"])
        )
        if not extra_rows:
            continue
        data[key] = extra_rows
        layers.append(
            Area(
                source=key,
                ymin="q1",
                ymax="q3",
                fill=str(extra.get("fill") or COLOR_IQR),
                alpha=0.35,
                label=str(extra.get("label") or "IQR"),
                zorder=1,
            )
        )
        layers.append(
            Line(
                source=key,
                y="median",
                color=str(extra.get("median_color") or COLOR_MALE),
                width=2.4,
                marker="circle",
                marker_size=6.0,
                label=str(extra.get("median_label") or extra.get("label") or "Médiane"),
                zorder=4,
            )
        )
    if rule_y is not None:
        layers.append(
            Rule(
                axis="y",
                value=float(rule_y),
                color="#94a3b8",
                dash=(2.0, 2.0),
                width=1.0,
                label=rule_label or "Référence",
                zorder=0,
            )
        )
    for item in series:
        name = str(item["label"])
        color = str(item.get("color") or COLOR_TARGET)
        rows = tuple(
            {"x": float(x), "y": float(y)}
            for x, y in zip(item["x"], item["y"])
        )
        geom = str(item.get("geom") or "line")
        data[name] = rows
        if geom == "point":
            layers.append(
                Point(
                    source=name,
                    y="y",
                    color=color,
                    size=float(item.get("size", 22.0)),
                    alpha=float(item.get("alpha", 0.25)),
                    label=name,
                    zorder=2,
                )
            )
        else:
            layers.append(
                Line(
                    source=name,
                    y="y",
                    color=color,
                    width=2.6,
                    marker=item.get("marker") or "circle",
                    marker_size=7.0,
                    dash=tuple(item.get("dash") or ()),
                    label=name,
                    zorder=5,
                )
            )
    x_scale = Scale(
        label=xlabel,
        kind="categorical" if x_labels else "linear",
        categories=tuple(x_labels) if x_labels else (),
    )
    return ChartSpec(
        kind="pacing_profile",
        title=title,
        data=data,
        mapping={"x": xlabel, "y": ylabel},
        stat="percentiles(25,50,75) group_by=segment",
        x=x_scale,
        y=Scale(label=ylabel, unit=unit),
        layers=tuple(layers),
        theme=PACING_THEME,
        annotations=(_note(note),),
        figsize=(13.0, 7.0),
    )


def normalized_pacing_spec(
    *,
    x_values: Sequence[float],
    band_rows: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    title: str,
    note: str,
    x_labels: Optional[Sequence[str]] = None,
    xlabel: str = "Segment de nage",
    ylabel: str = "Vitesse normalisée (% de la vitesse moyenne de la nage)",
) -> ChartSpec:
    """F14 — profil de pacing normalisé (couloir percentile + courbes)."""
    rows = tuple(dict(row) for row in band_rows)
    layers: List[Any] = list(
        corridor_band_layers(
            rows,
            outer_label_below="Référence sous médiane (P10–P50)",
            outer_label_above="Référence au-dessus médiane (P50–P90)",
            inner_label_below="Référence P25–P50",
            inner_label_above="Référence P50–P75",
            median_label="Médiane du groupe de référence",
        )
    )
    layers.append(
        Rule(
            axis="y",
            value=100.0,
            color="#94a3b8",
            dash=(2.0, 2.0),
            width=1.0,
            label="Vitesse moyenne de la nage (100 %)",
            zorder=0,
        )
    )
    data: Dict[str, Tuple[Dict[str, Any], ...]] = {"bands": rows}
    for item in series:
        name = str(item["label"])
        color = str(item.get("color") or COLOR_TARGET)
        series_rows = tuple(
            {"x": float(x), "y": float(y)}
            for x, y in zip(item["x"], item["y"])
        )
        data[name] = series_rows
        layers.append(
            Line(
                source=name,
                y="y",
                color=color,
                width=2.8,
                marker=item.get("marker") or "circle",
                marker_size=7.0,
                dash=tuple(item.get("dash") or ()),
                label=name,
                zorder=8,
            )
        )
    unused_x = x_values
    _ = unused_x
    return ChartSpec(
        kind="normalized_pacing",
        title=title,
        data=data,
        mapping={"x": xlabel, "y": ylabel},
        stat="percentiles(10,25,50,75,90) of speed_pct group_by=segment",
        x=Scale(
            label=xlabel,
            kind="categorical" if x_labels else "linear",
            categories=tuple(x_labels) if x_labels else (),
        ),
        y=Scale(label=ylabel, unit="%"),
        layers=tuple(layers),
        theme=PACING_THEME,
        annotations=(_note(note),),
        figsize=(12.0, 8.0),
        meta={"n_segments": len(x_values)},
    )
