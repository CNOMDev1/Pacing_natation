"""Couche de rendu matplotlib pour les visualisations Pacing.

Sépare le tracé (figures, axes, styles) du cœur métier dans ``services/``.
- ``corridor_plots`` : couloirs de performance
- ``chart_plots`` : autres familles de graphiques
"""
from services.rendering.corridor_plots import (
    apply_corridor_chart_theme,
    corridor_swimmer_line_kwargs,
    draw_corridor_swimmer_series,
    draw_decile_corridor_bands,
    draw_normalized_pacing_series,
    draw_percentile_corridor_bands,
    plot_corridor_swimmer_specs,
    plot_normalized_pacing_profiles_on_ax,
)

__all__ = [
    "apply_corridor_chart_theme",
    "corridor_swimmer_line_kwargs",
    "draw_corridor_swimmer_series",
    "draw_decile_corridor_bands",
    "draw_normalized_pacing_series",
    "draw_percentile_corridor_bands",
    "plot_corridor_swimmer_specs",
    "plot_normalized_pacing_profiles_on_ax",
]
