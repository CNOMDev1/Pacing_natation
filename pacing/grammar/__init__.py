"""Grammaire de graphiques Pacing.

Sépare la *description* d'un graphique de son *dessin* :

- ``spec`` : vocabulaire déclaratif (données, mapping, géométries, échelles,
  thème, légende), sérialisable en JSON pour les moteurs non-Python.
- ``corridor`` : la recette du couloir de performance, définie une seule fois.
- ``render_matplotlib`` : le moteur Matplotlib partagé par Flet, NiceGUI et
  DearPyGUI.

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
from pacing.grammar.render_matplotlib import (
    apply_scales,
    apply_theme,
    draw_layers,
    render_figure,
)
from pacing.grammar.spec import (
    Area,
    ChartSpec,
    LegendEntry,
    Line,
    Point,
    Scale,
    Theme,
)

__all__ = [
    "Area",
    "CORRIDOR_STAT",
    "ChartSpec",
    "LegendEntry",
    "Line",
    "PACING_THEME",
    "Point",
    "Scale",
    "Theme",
    "apply_scales",
    "apply_theme",
    "compare_spec_from_payload",
    "corridor_band_layers",
    "corridor_spec_from_payload",
    "draw_layers",
    "percentile_corridor_spec",
    "render_figure",
    "swimmer_layers",
]
