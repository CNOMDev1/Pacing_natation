"""Catalogue UI des graphiques Pacing (menus, scopes, GraphSpec).

Séparé de ``graph_service`` pour que la présentation importe le catalogue
sans dépendre de l'orchestration matplotlib.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# Versions de style (alignées sur ``services.rendering.chart_plots``)
MEDIAN_VS_BEST_CHART_STYLE_VERSION = 2
MEDIAN_VS_TOP10_CHART_STYLE_VERSION = 2
MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION = 2
RELAY_SPLIT_CHART_STYLE_VERSION = 2

HEATMAP_GRAPH_NAME = "Heatmap vitesse moyenne (distance x nage)"
HEATMAP_CATEGORY_NAME = "Synthèse des vitesses par distance et nage"
MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME = "Temps médian vs meilleur nageur"
MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME = "Temps médian vs Top 10 nageurs"
SPLIT_COMPARISON_CATEGORY_NAME = (
    "Comparaisons de pacing par splits (à partir de la médiane)"
)
MEDIAN_SPEED_BY_GENDER_GRAPH_NAME = "Vitesse médiane par split selon le genre"


@dataclass(frozen=True)
class GraphSpec:
    """dataclass pour la description des graphes """
    key: str
    name: str
    category: str
    method_name: str


@dataclass(frozen=True)
class DesktopGraphCategory:
    """Une rubrique du menu graphes (UI desktop Flet)."""
    title: str
    graph_names: Tuple[str, ...]


GRAPH_CHRONOS_PAR_NAGE = "Évolution des chronos par type de nage (échantillon 5000)"
GRAPH_VITESSE_DISTANCE_NAGE = "Vitesse par distance et type de nage"
GRAPH_VITESSE_MAX_SPLIT_NAGE = "Vitesse maximale par split et type de nage"
GRAPH_RELAY_SPLIT_DISTANCE = "Vitesse de split selon la distance (relais)"
RELAY_CATEGORY_NAME = "Pacing en relais"
DESKTOP_GRAPH_MENU: Tuple[DesktopGraphCategory, ...] = (
    DesktopGraphCategory(
        "Distributions de temps",
        (
            "Histogramme simple",
            "Histogramme cumulatif",
        ),
    ),
    DesktopGraphCategory(
        "Effectifs et répartition par sexe",
        (
            "Nombre de performances par épreuve",
            "Nombre de performances par épreuve (LCM + SCM)",
            "Comptage par sexe (global)",
            "Camembert par sexe (global)",
            "Camembert par sexe (épreuve)",
        ),
    ),
    DesktopGraphCategory(
        "Comparaison des temps par nage",
        ("Distribution des temps par type de nage (boxplot)",),
    ),
    DesktopGraphCategory(
        "Clubs",
        (
            "Top 10 clubs par participation (épreuve)",
            "Temps médian des 10 meilleurs clubs",
        ),
    ),
    DesktopGraphCategory(
        "Chronos dans le temps",
        (
            GRAPH_CHRONOS_PAR_NAGE,
        ),
    ),
    DesktopGraphCategory(
        "Vitesse globale",
        (
            GRAPH_VITESSE_DISTANCE_NAGE,
            GRAPH_VITESSE_MAX_SPLIT_NAGE,
        ),
    ),
    DesktopGraphCategory(
        "Pacing comparatif",
        ("Vitesse de split - F vs M + nageurs cibles",),
    ),
    DesktopGraphCategory(
        "Synthèse des vitesses par distance et nage",
        ("Heatmap vitesse moyenne (distance x nage)",),
    ),
    DesktopGraphCategory(
        "Comparaisons de pacing par splits (à partir de la médiane)",
        (
            "Temps médian vs meilleur nageur",
            "Temps médian vs Top 10 nageurs",
            "Vitesse médiane par split selon le genre",
        ),
    ),
    DesktopGraphCategory(
        "Pacing en relais",
        (GRAPH_RELAY_SPLIT_DISTANCE,),
    ),
    DesktopGraphCategory(
        "Couloirs de performance",
        (
            "Couloir de performance global (âge)",
            "Couloir de performance (âge) - nageur cible",
            "Couloir de performance global (déciles 10-90)",
            "Couloir de performance (AgeGroup) - USA Swimming",
        ),
    ),
)

GRAPH_CATEGORIES: Dict[str, List[str]] = {
    block.title: list[str](block.graph_names) for block in DESKTOP_GRAPH_MENU
}

EVENT_COUNTS_SORT_STROKE_DISTANCE = "stroke_distance"
EVENT_COUNTS_SORT_TOTAL_DESC = "total_desc"
EVENT_COUNTS_SORT_OPTIONS: Dict[str, str] = {
    EVENT_COUNTS_SORT_STROKE_DISTANCE: "Par distance (croissant)",
    EVENT_COUNTS_SORT_TOTAL_DESC: "Par effectif décroissant",
}
GRAPH_NOMBRE_PERF_EPREUVE = "Nombre de performances par épreuve"
GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM = "Nombre de performances par épreuve (LCM + SCM)"
SCOPE_EVENT_COUNTS_GRAPHS = frozenset(
    {
        GRAPH_NOMBRE_PERF_EPREUVE,
        GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM,
    }
)

SCOPE_NO_FILTER_GRAPHS = frozenset(
    {
        "Comptage par sexe (global)",
        "Camembert par sexe (global)",
        GRAPH_CHRONOS_PAR_NAGE,
        GRAPH_VITESSE_DISTANCE_NAGE,
        GRAPH_VITESSE_MAX_SPLIT_NAGE,
        "Heatmap vitesse moyenne (distance x nage)",
    }
)
SCOPE_GENDER_FILTER_GRAPHS: frozenset[str] = frozenset()
SCOPE_POOL_ONLY_GRAPHS: frozenset[str] = frozenset()
SCOPE_POOL_STROKE_GRAPHS = frozenset({GRAPH_NOMBRE_PERF_EPREUVE})
SCOPE_STROKE_ONLY_GRAPHS = frozenset({GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM})
SCOPE_NO_STROKE_GRAPHS = frozenset({"Distribution des temps par type de nage (boxplot)"})



Graphe1 = GraphSpec(
    key="histogramme_simple",
    name="Histogramme simple",
    category="Distributions de temps",
    method_name="plot_histogramme_simple",
)
Graphe2 = GraphSpec(
    key="camembert_sexe_global",
    name="Camembert par sexe (global)",
    category="Effectifs et repartition par sexe",
    method_name="plot_camembert_sexe_global",
)
Graphe3 = GraphSpec(
    key="boxplot_temps_par_nage",
    name="Distribution des temps par type de nage (boxplot)",
    category="Comparaison des temps par nage",
    method_name="plot_boxplot_temps_par_nage",
)
Graphe4 = GraphSpec(
    key="top10_clubs",
    name="Top 10 clubs par participation",
    category="Clubs",
    method_name="plot_top10_clubs",
)
Graphe5 = GraphSpec(
    key="heatmap_vitesse_moyenne",
    name="Heatmap vitesse moyenne (distance x nage)",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_heatmap_vitesse_moyenne",
)
Graphe7 = GraphSpec(
    key="histogramme_cumulatif",
    name="Histogramme cumulatif",
    category="Distributions de temps",
    method_name="plot_histogramme_cumulatif",
)
Graphe8 = GraphSpec(
    key="nombre_performances_par_epreuve",
    name="Nombre de performances par epreuve",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_epreuve",
)
Graphe9 = GraphSpec(
    key="nombre_performances_par_epreuve_lcm_scm",
    name="Nombre de performances par epreuve (LCM + SCM)",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_epreuve_lcm_scm",
)
Graphe10 = GraphSpec(
    key="nombre_performances_par_sexe",
    name="Nombre de performances par sexe",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_sexe",
)
Graphe11 = GraphSpec(
    key="temps_median_top10_clubs_par_event",
    name="Temps médian top 10 clubs par event",
    category="Clubs",
    method_name="plot_temps_median_top10_clubs_par_event",
)
Graphe12 = GraphSpec(
    key="evolution_temps_nage",
    name="Évolution des temps de nage",
    category="Distributions de temps",
    method_name="plot_evolution_temps_nage",
)
Graphe13 = GraphSpec(
    key="top10_nageurs_meilleur_temps_par_event",
    name="Top 10 nageurs meilleur temps par event",
    category="Classements par epreuve",
    method_name="plot_top10_nageurs_meilleur_temps_par_event",
)
Graphe14 = GraphSpec(
    key="camembert_sexe_par_event",
    name="Camembert par sexe (par event)",
    category="Effectifs et repartition par sexe",
    method_name="plot_camembert_sexe_par_event",
)
Graphe15 = GraphSpec(
    key="vitesse_max_par_split_et_nage",
    name="Vitesse max par split et nage",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_vitesse_max_par_split_et_nage",
)
Graphe16 = GraphSpec(
    key="vitesse_moyenne_mediane_par_split_et_nage",
    name="Vitesse moyenne et mediane par split et nage",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_vitesse_moyenne_mediane_par_split_et_nage",
)
Graphe17 = GraphSpec(
    key="split_speed_analysis_by_gender_with_targets",
    name="Analyse split_speed par genre avec nageurs cibles",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_split_speed_analysis_by_gender_with_targets",
)
Graphe18 = GraphSpec(
    key="vitesse_par_split_pour_nageur_event",
    name="Vitesse par split pour un nageur et un event",
    category="Analyse individuelle par epreuve",
    method_name="plot_vitesse_par_split_pour_nageur_event",
)
Graphe19 = GraphSpec(
    key="vitesse_par_split_meilleur_nageur_event_periode",
    name="Vitesse par split du meilleur nageur par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_meilleur_nageur_event_periode",
)
Graphe20 = GraphSpec(
    key="vitesse_par_split_top_nageurs_hf_event_periode",
    name="Vitesse par split des top nageurs H/F par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_top_nageurs_hf_event_periode",
)
Graphe21 = GraphSpec(
    key="vitesse_par_split_top_nageurs_uniques_event_periode",
    name="Vitesse par split des top nageurs uniques par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_top_nageurs_uniques_event_periode",
)
Graphe22 = GraphSpec(
    key="comparaison_vitesse_moyenne_heatmap_nageur_vs_autres",
    name="Comparaison heatmap vitesse moyenne nageur vs autres",
    category="Analyse individuelle par epreuve",
    method_name="plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres",
)
Graphe23 = GraphSpec(
    key="temps_median_vs_meilleur_nageur_par_split_event",
    name="Temps median vs meilleur nageur par split et event",
    category="Analyse individuelle par epreuve",
    method_name="plot_temps_median_vs_meilleur_nageur_par_split_event",
)
Graphe24 = GraphSpec(
    key="temps_median_vs_top10_nageurs_par_split_event",
    name="Temps median vs top10 nageurs par split et event",
    category="Analyse individuelle par epreuve",
    method_name="plot_temps_median_vs_top10_nageurs_par_split_event",
)
Graphe25 = GraphSpec(
    key="vitesse_mediane_par_split_selon_genre_top_n_event",
    name="Vitesse mediane par split selon genre top-n event",
    category="Classements par epreuve",
    method_name="plot_vitesse_mediane_par_split_selon_genre_top_n_event",
)
Graphe26 = GraphSpec(
    key="relais_split_speed_par_distance",
    name="Vitesse split relais par distance",
    category="Analyse individuelle par epreuve",
    method_name="plot_relais_split_speed_par_distance",
)
Graphe27 = GraphSpec(
    key="performance_corridor_plot_time",
    name="Couloir de performance sur SwimTime",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_plot_time",
)
Graphe28 = GraphSpec(
    key="performance_corridor_global_plot_time",
    name="Couloir de performance global (âge)",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_global_plot_time",
)
Graphe29 = GraphSpec(
    key="performance_corridor_global_deciles_plot_time",
    name="Couloir de performance global (déciles 10-90)",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_global_deciles_plot_time",
)
Graphe30 = GraphSpec(
    key="performance_corridor_global_by_agegroup",
    name="Couloir de performance global (AgeGroup)",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_global_by_agegroup",
)
GRAPHES_NOTEBOOK: List[GraphSpec] = [
    Graphe1, Graphe2, Graphe3, Graphe4, Graphe5, Graphe7, Graphe8, Graphe9,
    Graphe10, Graphe11, Graphe12, Graphe13, Graphe14, Graphe15, Graphe16, Graphe17,
    Graphe18, Graphe19, Graphe20, Graphe21, Graphe22, Graphe23, Graphe24, Graphe25,
    Graphe26, Graphe27, Graphe28, Graphe29, Graphe30,
]
GRAPHES_PAR_KEY: Dict[str, GraphSpec] = {g.key: g for g in GRAPHES_NOTEBOOK}

