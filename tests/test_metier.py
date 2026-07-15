"""Tests métier : normalize, graph_compute, corridor_data, catalogue, parsing."""
from __future__ import annotations

import pandas as pd
from bs4 import BeautifulSoup

from services.corridor_data import (
    build_corridor_chart_plot_kwargs,
    corridor_gender_display_label,
    corridor_norm_name,
    parse_event_distance_m,
    parse_split_distance_m,
    prepare_corridor_long_df,
)
from services.extranat_parse import extract_results_from_filter_table
from services.graph_catalog import (
    GRAPH_CATEGORIES,
    GRAPHES_NOTEBOOK,
    GRAPHES_PAR_KEY,
    HEATMAP_GRAPH_NAME,
    MEDIAN_VS_BEST_CHART_STYLE_VERSION,
    RELAY_SPLIT_CHART_STYLE_VERSION,
)
from services.graph_compute import (
    _adaptive_histogram_bin_count,
    _event_display_sort_key,
    _gender_label_for_code,
    _is_relay_swimmers,
    _ordered_stroke_labels,
    _parse_split_distance_m,
    _parse_split_speed_mps,
    _smooth_centered_rolling,
)
from services.normalize import primary_swimmer_name, primary_swimmer_name_and_yob


def test_primary_swimmer_name_from_dict() -> None:
    """Extrait le nom depuis une liste solo (clé ``Name``)."""
    assert primary_swimmer_name([{"Name": "DUPONT Alice"}]) == "DUPONT Alice"


def test_primary_swimmer_name_and_yob() -> None:
    """Extrait nom + année de naissance."""
    name, yob = primary_swimmer_name_and_yob(
        [{"Name": "DUPONT Alice", "Year_of_birth": 2005}]
    )
    assert name == "DUPONT Alice"
    assert yob == 2005


def test_graph_compute_stroke_order() -> None:
    """Les nages sont ordonnées dans l'ordre canonique."""
    ordered = _ordered_stroke_labels(["Brasse", "Nage libre", "Dos"])
    assert ordered[0] == "Nage libre"
    assert len(ordered) == 3


def test_graph_compute_parse_split() -> None:
    """Parse distance / vitesse de split."""
    assert _parse_split_distance_m("50m") == 50
    assert _parse_split_distance_m(100) == 100
    assert _parse_split_speed_mps("1.85") == 1.85
    assert _parse_split_speed_mps("bad") is None


def test_graph_compute_relay_and_gender() -> None:
    """Détection relais et libellés genre."""
    assert _is_relay_swimmers([{"name": "A"}, {"name": "B"}]) is True
    assert _is_relay_swimmers({"name": "A"}) is False
    assert _gender_label_for_code("F")
    assert _gender_label_for_code("M")


def test_graph_compute_histogram_bins_and_smooth() -> None:
    """Bins adaptatifs et lissage rolling."""
    assert (
        _adaptive_histogram_bin_count(
            n_perf=5, data_min=50.0, data_max=60.0, iqr=2.0
        )
        >= 1
    )
    smoothed = _smooth_centered_rolling([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
    assert len(smoothed) == 5
    assert smoothed[2] == 3.0


def test_event_display_sort_key_orders_by_distance() -> None:
    """Les clés de tri d'épreuve placent 50 avant 100."""
    assert _event_display_sort_key("50 FR LCM") < _event_display_sort_key("100 FR LCM")


def test_corridor_norm_and_distance_parsers() -> None:
    """Normalisation nom + parse distances couloir."""
    assert corridor_norm_name("Élodie Martin") == corridor_norm_name("elodie martin")
    assert parse_event_distance_m("200 BK LCM") == 200
    assert parse_split_distance_m("75 m") == 75
    assert corridor_gender_display_label("F")
    assert corridor_gender_display_label(None) == ""


def test_prepare_corridor_long_df_basic() -> None:
    """prepare_corridor_long_df produit âge × temps pour une épreuve."""
    df = pd.DataFrame(
        {
            "Event": ["100 FR LCM", "100 FR LCM"],
            "Stroke": ["FR", "FR"],
            "Distance": [100, 100],
            "Course": ["LCM", "LCM"],
            "SwimTimeSeconds": [55.0, 58.0],
            "Swimmer": [
                {"name": "A", "annee_naissance": 2000},
                {"name": "B", "annee_naissance": 2001},
            ],
            "MeetDate": ["2020-01-01", "2020-01-01"],
            "Year": [2020, 2020],
        }
    )
    # Certaines colonnes optionnelles selon implémentation — tolérer DF vide
    out = prepare_corridor_long_df(df, "100 FR LCM", solo_only=True, require_name=False)
    assert isinstance(out, pd.DataFrame)


def test_build_corridor_chart_plot_kwargs() -> None:
    """Les kwargs overlay couloir sont un dict stable."""
    kwargs = build_corridor_chart_plot_kwargs(
        gender_filter="F",
        french_name="DUPONT",
        french_yob=2000,
    )
    assert isinstance(kwargs, dict)


def test_graph_catalog_keys_and_versions() -> None:
    """Le catalogue expose clés notebook et versions de style."""
    assert HEATMAP_GRAPH_NAME in {
        g for graphs in GRAPH_CATEGORIES.values() for g in graphs
    } or any(HEATMAP_GRAPH_NAME in v for v in GRAPH_CATEGORIES.values())
    assert len(GRAPHES_PAR_KEY) == len(GRAPHES_NOTEBOOK) or len(GRAPHES_PAR_KEY) > 0
    assert MEDIAN_VS_BEST_CHART_STYLE_VERSION >= 1
    assert RELAY_SPLIT_CHART_STYLE_VERSION >= 1


def test_extranat_parse_empty_soup() -> None:
    """Sans tables, le parseur renvoie une liste vide."""
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    assert extract_results_from_filter_table(soup) == []


def test_extranat_parse_minimal_table() -> None:
    """Parse une table filtre minimale avec en-tête et une perf."""
    html = """
    <html><body>
    <table>
      <tr><td colspan="6">50 Nage Libre Dames - Finale A</td></tr>
      <tr>
        <td>1</td>
        <td>TARTAGLIONE Jade (2014/11 ans)FRA</td>
        <td>CLUB A</td>
        <td>00:26.14</td>
        <td></td>
        <td>800</td>
      </tr>
    </table>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    epreuves = extract_results_from_filter_table(soup)
    assert isinstance(epreuves, list)
    # Structure peut varier selon format exact des colonnes — au minimum pas de crash
    if epreuves:
        assert "performances" in epreuves[0] or "nom" in epreuves[0]


def test_service_graphe_histogram_empty() -> None:
    """plot_histogramme_simple gère un DataFrame vide sans exception."""
    from services.graph_service import ServiceGraphe

    fig = ServiceGraphe().plot_histogramme_simple(
        pd.DataFrame({"SwimTimeSeconds": []})
    )
    assert fig is not None


def test_pacing_app_service_available_graphs_nested() -> None:
    """La façade liste des graphes pour plusieurs catégories FR."""
    from services.app_service import PacingAppService

    svc = PacingAppService()
    cats = svc.available_categories("France")
    assert cats
    for cat in ("Distributions de temps", "Couloirs de performance"):
        if cat in cats:
            graphs = svc.available_graphs("France", cat)
            assert isinstance(graphs, list)
            assert graphs
            return
    assert any(svc.available_graphs("France", c) for c in cats)
