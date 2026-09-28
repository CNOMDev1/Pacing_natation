"""Grammaire de graphiques Pacing.

Sépare la *description* d'un graphique de son *dessin* :

- ``spec`` : vocabulaire déclaratif (données, mapping, géométries, échelles,
  thème, légende, facettes, annotations), sérialisable en JSON.
- ``corridor`` : recette du couloir de performance.
- ``families`` : recettes F1–F14.
- ``render_matplotlib`` : moteur Matplotlib partagé.

Le moteur iOS (``CorridorChartView.swift``) consomme la même recette via
``ChartSpec.to_dict()``, transmise par l'API.
"""
from pacing.grammar.corridor import (
    CORRIDOR_STAT,
    PACING_THEME,
    compare_spec_from_payload,
    corridor_band_layers,
    corridor_spec_from_payload,
    percentile_corridor_spec,
    swimmer_layers,
)
from pacing.grammar.families import (
    boxplot_spec,
    category_bar_spec,
    empty_spec,
    facet_lines_spec,
    grouped_bar_spec,
    heatmap_panels_spec,
    heatmap_spec,
    histogram_spec,
    multiline_spec,
    normalized_pacing_spec,
    pacing_profile_spec,
    ranked_bar_spec,
)
from pacing.grammar.render_matplotlib import (
    apply_scales,
    apply_theme,
    draw_layers,
    render_figure,
)
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
    Theme,
)

__all__ = [
    "Annotation",
    "Area",
    "Bar",
    "Boxplot",
    "CORRIDOR_STAT",
    "ChartSpec",
    "Facet",
    "Heatmap",
    "Histogram",
    "LegendEntry",
    "Line",
    "PACING_THEME",
    "Point",
    "Rule",
    "Scale",
    "Span",
    "Theme",
    "apply_scales",
    "apply_theme",
    "boxplot_spec",
    "category_bar_spec",
    "compare_spec_from_payload",
    "corridor_band_layers",
    "corridor_spec_from_payload",
    "draw_layers",
    "empty_spec",
    "facet_lines_spec",
    "grouped_bar_spec",
    "heatmap_panels_spec",
    "heatmap_spec",
    "histogram_spec",
    "multiline_spec",
    "normalized_pacing_spec",
    "pacing_profile_spec",
    "percentile_corridor_spec",
    "ranked_bar_spec",
    "render_figure",
    "swimmer_layers",
]
