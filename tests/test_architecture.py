"""Tests unitaires Pacing (normalize, scope, catalogue, façade)."""
from __future__ import annotations

import pandas as pd

from pacing.application.graph_service import (
    GRAPH_CATEGORIES,
    GRAPHES_NOTEBOOK,
    SCOPE_NO_FILTER_GRAPHS,
    GraphSpec,
)
from pacing.application.scope import (
    event_combinations,
    materialize_df_scope,
    resolve_scope_filters,
)
from pacing.domain.normalize import (
    normalize_gender_code,
    normalize_name,
    normalize_text,
    slugify,
)


def test_normalize_text_strips_accents() -> None:
    """La normalisation retire les accents et abaisse la casse."""
    assert normalize_text("Éléonore DUPONT") == "eleonore dupont"


def test_normalize_name_alias() -> None:
    """normalize_name délègue à normalize_text."""
    assert normalize_name("Jean-Pierre") == normalize_text("Jean-Pierre")


def test_normalize_gender_code() -> None:
    """Les libellés genre connus deviennent F ou M."""
    assert normalize_gender_code("Femme") == "F"
    assert normalize_gender_code("MALE") == "M"
    assert normalize_gender_code("inconnu") is None


def test_slugify() -> None:
    """slugify produit un identifiant kebab-case."""
    assert slugify("100 FR LCM") == "100-fr-lcm"


def test_graph_catalog_not_empty() -> None:
    """Le catalogue UI expose des catégories et des specs notebook."""
    assert len(GRAPH_CATEGORIES) >= 5
    assert len(GRAPHES_NOTEBOOK) >= 10
    assert all(isinstance(g, GraphSpec) for g in GRAPHES_NOTEBOOK)


def test_resolve_scope_no_filter() -> None:
    """Les graphes sans filtre renvoient None, None, None."""
    df = pd.DataFrame(
        {"Stroke": ["FR"], "Distance": [100], "Course": ["LCM"]}
    )
    graph = next(iter(SCOPE_NO_FILTER_GRAPHS))
    assert resolve_scope_filters(df, graph, "FR", 100, "LCM") == (None, None, None)


def test_materialize_scope_full_event() -> None:
    """Le scope standard filtre stroke/distance/pool/Event."""
    df = pd.DataFrame(
        {
            "Stroke": ["FR", "FR", "BK"],
            "Distance": [100, 100, 100],
            "Course": ["LCM", "SCM", "LCM"],
            "Event": ["100 FR LCM", "100 FR SCM", "100 BK LCM"],
            "SwimTimeSeconds": [55.0, 54.0, 60.0],
        }
    )
    out = materialize_df_scope(df, "Couloir de performance global (âge)", "FR", 100, "LCM")
    assert len(out) == 1
    assert out.iloc[0]["Event"] == "100 FR LCM"


def test_event_combinations() -> None:
    """Les combinaisons stroke→distance→pools sont construites."""
    df = pd.DataFrame(
        {
            "Stroke": ["FR", "FR"],
            "Distance": [100, 100],
            "Course": ["LCM", "SCM"],
        }
    )
    combos = event_combinations(df)
    assert "FR" in combos
    assert 100 in combos["FR"]
    assert set(combos["FR"][100]) == {"LCM", "SCM"}


def test_pacing_app_service_catalog() -> None:
    """La façade expose le catalogue sans charger les données."""
    from services.app_service import PacingAppService

    svc = PacingAppService()
    cats = svc.available_categories("France")
    assert "Couloirs de performance" in cats
    graphs = svc.available_graphs("France", "Couloirs de performance")
    assert any("âge" in g for g in graphs)
