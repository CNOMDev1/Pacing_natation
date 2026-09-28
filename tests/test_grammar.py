"""Tests de la grammaire visuelle Pacing (géométries §4.1 et familles F1–F14)."""
from __future__ import annotations

from matplotlib.figure import Figure

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
from pacing.grammar.render_matplotlib import render_figure
from pacing.grammar.spec import (
    Annotation,
    Bar,
    Boxplot,
    Facet,
    Heatmap,
    Histogram,
)


def test_new_geoms_serialize() -> None:
    """Bar, histogram, boxplot, heatmap, facet et annotation sont sérialisables."""
    bar = Bar(source="bars", y="y", fill="#2E5EAA", value_labels=True, label_field="text")
    hist = Histogram(source="bins", y="y", fill="#2E5EAA")
    box = Boxplot(source="box0")
    heat = Heatmap(source="cells", colorbar=True, colorbar_label="v")
    facet = Facet(ncol=2, sharex=True)
    note = Annotation(text="Limites : n=10", loc="footnote")
    assert bar.to_dict()["geom"] == "bar"
    assert hist.to_dict()["geom"] == "histogram"
    assert box.to_dict()["geom"] == "boxplot"
    assert heat.to_dict()["geom"] == "heatmap"
    assert facet.to_dict()["ncol"] == 2
    assert note.to_dict()["loc"] == "footnote"


def test_empty_spec_renders() -> None:
    """L'état vide produit une figure avec annotation centrée."""
    fig = render_figure(empty_spec("Titre", "Aucune donnée"))
    assert isinstance(fig, Figure)


def test_histogram_and_bar_families_render() -> None:
    """F1, F2, F3 et F5 passent par render_figure."""
    hist = histogram_spec(
        centers=[50.0, 51.0, 52.0],
        counts=[2, 5, 1],
        bin_width=1.0,
        mean=51.0,
        median=51.0,
        q1=50.5,
        q3=51.5,
        title="Histogramme",
        stats_text="n=8",
        n_perf=8,
    )
    assert any(isinstance(layer, Histogram) for layer in hist.layers)
    grouped = grouped_bar_spec(
        categories=["100 NL", "200 NL"],
        series={"Femmes": [10, 4], "Hommes": [12, 6]},
        colors={"Femmes": "#CC79A7", "Hommes": "#0072B2"},
        title="Effectifs",
        xlabel="n",
        ylabel="Épreuve",
        note="Limites : test",
    )
    bars = [layer for layer in grouped.layers if isinstance(layer, Bar)]
    assert len(bars) == 2
    category = category_bar_spec(
        categories=["Femmes", "Hommes"],
        values=[10, 20],
        fills=["#CC79A7", "#0072B2"],
        title="Sexe",
        xlabel="Sexe",
        ylabel="n",
        note="Limites : test",
    )
    ranked = ranked_bar_spec(
        categories=["A", "B"],
        values=[3, 1],
        fills=["#2E5EAA", "#b8cce8"],
        title="Top",
        xlabel="n",
        ylabel="Club",
        note="Limites : test",
        value_texts=["3 (75 %)", "1 (25 %)"],
    )
    for spec in (hist, grouped, category, ranked):
        fig = render_figure(spec)
        assert isinstance(fig, Figure)
        payload = spec.to_dict()
        assert payload["kind"]
        assert payload["annotations"]


def test_grouped_bars_dodge_when_x_overlap() -> None:
    """Les barres groupées F2 partagent les mêmes x : le moteur doit les décaler."""
    from pacing.grammar.render_matplotlib import _bar_series, _bar_xs

    spec = grouped_bar_spec(
        categories=["A", "B"],
        series={"F": [1, 2], "M": [3, 4]},
        colors={"F": "#CC79A7", "M": "#0072B2"},
        title="t",
        xlabel="n",
        ylabel="cat",
        note="n",
    )
    layers = _bar_series(spec)
    xs = [tuple(_bar_xs(spec, layer)) for layer in layers]
    assert len(set(xs)) == 1


def test_ranked_bars_do_not_share_x() -> None:
    """Les barres classées F5 ont une abscisse par barre : pas de décalage."""
    from pacing.grammar.render_matplotlib import _bar_series, _bar_xs

    spec = ranked_bar_spec(
        categories=["A", "B"],
        values=[3, 1],
        fills=["#2E5EAA", "#b8cce8"],
        title="t",
        xlabel="n",
        ylabel="cat",
        note="n",
    )
    layers = _bar_series(spec)
    xs = [tuple(_bar_xs(spec, layer)) for layer in layers]
    assert len(set(xs)) == len(layers)


def test_boxplot_heatmap_facet_pacing_render() -> None:
    """F4, F6, F7, F9, F10, F11 et F14 rendent une figure Matplotlib."""
    box = boxplot_spec(
        categories=["NL"],
        stats=[{"q1": 50, "median": 52, "q3": 54, "whislo": 48, "whishi": 58}],
        outliers=[{"x": 0.1, "y": 62}],
        fills=["#0072B2"],
        title="Boxplot",
        ylabel="Temps (s)",
        note="Limites : test",
    )
    assert any(isinstance(layer, Boxplot) for layer in box.layers)
    facet = facet_lines_spec(
        panels=[
            {"label": "NL", "x_raw": [2018, 2019], "y_raw": [55, 54], "x": [2018, 2019], "y": [54.8, 54.2], "unit": "s"},
            {"label": "Dos", "x_raw": [], "y_raw": [], "x": [], "y": [], "unit": "s"},
        ],
        title="Évolution",
        xlabel="Année",
        ylabel="Médiane",
        note="Limites : test",
    )
    assert facet.facet is not None
    lines = multiline_spec(
        series=[{"label": "NL", "x": [50, 100], "y": [1.8, 1.6], "marker": "circle"}],
        title="Vitesse",
        xlabel="Distance (m)",
        ylabel="m/s",
        note="Limites : test",
    )
    heat = heatmap_spec(
        x_categories=["NL", "Dos"],
        y_categories=["50", "100"],
        cells=[
            {"x": 0, "y": 0, "value": 1.8, "annot": "1.80"},
            {"x": 1, "y": 1, "value": 1.4, "annot": "1.40"},
        ],
        title="Heatmap",
        cmap="viridis",
        note="Limites : test",
        colorbar=True,
        colorbar_label="m/s",
    )
    assert any(isinstance(layer, Heatmap) for layer in heat.layers)
    heat_b = heatmap_spec(
        x_categories=["NL", "Dos"],
        y_categories=["50", "100"],
        cells=[
            {"x": 0, "y": 0, "value": 1.7, "annot": "1.70"},
            {"x": 1, "y": 1, "value": 1.3, "annot": "1.30"},
        ],
        title="Peloton",
        cmap="viridis",
        note="",
    )
    panels = heatmap_panels_spec(panels=(heat, heat_b), title="F10", note="Limites : test")
    profile = pacing_profile_spec(
        x_values=[0, 1],
        q1=[1.4, 1.3],
        q3=[1.7, 1.6],
        median=[1.55, 1.45],
        series=[{"label": "Cible", "x": [0, 1], "y": [1.8, 1.7]}],
        title="Profil",
        xlabel="Segment",
        ylabel="m/s",
        note="Limites : test",
        x_labels=["0–50 m", "50–100 m"],
    )
    normalized = normalized_pacing_spec(
        x_values=[50, 100],
        band_rows=[
            {"x": 50, "p10": 95, "p25": 98, "p50": 100, "p75": 102, "p90": 105},
            {"x": 100, "p10": 94, "p25": 97, "p50": 100, "p75": 103, "p90": 106},
        ],
        series=[{"label": "Nageur", "x": [50, 100], "y": [101, 99]}],
        title="Normalisé",
        note="Limites : test",
    )
    for spec in (box, facet, lines, heat, panels, profile, normalized):
        fig = render_figure(spec)
        assert isinstance(fig, Figure)
        dumped = spec.to_dict()
        assert "layers" in dumped
        assert "annotations" in dumped
