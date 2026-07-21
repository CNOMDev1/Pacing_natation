"""Construction des figures matplotlib pour le menu desktop Flet.

Extrait de ``ServiceGraphe.desktop_build_figure`` pour alléger
``services.graph_service`` : le dispatch par nom de graphe (catalogue UI)
reste ici ; le service conserve un mince wrapper.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.colors import to_hex

from services.corridor_data import build_corridor_chart_plot_kwargs
from services.graph_catalog import (
    EVENT_COUNTS_SORT_STROKE_DISTANCE,
    EVENT_COUNTS_SORT_TOTAL_DESC,
    GRAPH_CHRONOS_PAR_NAGE,
    GRAPH_NOMBRE_PERF_EPREUVE,
    GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM,
    GRAPH_RELAY_SPLIT_DISTANCE,
    GRAPH_VITESSE_DISTANCE_NAGE,
    GRAPH_VITESSE_MAX_SPLIT_NAGE,
    MEDIAN_SPEED_BY_GENDER_GRAPH_NAME,
    MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME,
    MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME,
)
from services.rendering.chart_plots import _format_swim_time_display
from services.stroke_labels import format_event_label, stroke_code_to_label

if TYPE_CHECKING:
    from services.graph_service import ServiceGraphe


def desktop_build_figure(
    svc: "ServiceGraphe",
    selected_graph: str,
    *,
    df: pd.DataFrame,
    df_scope: pd.DataFrame,
    df_filtered: pd.DataFrame,
    stroke: Optional[str],
    distance: Optional[int],
    pool: Optional[str],
    selected_distance: Any,
    selected_chronos_sample_size: int,
    selected_pacing_swimmers: List[str],
    selected_heatmap_swimmer: Optional[str],
    selected_corridor_swimmer_name: Optional[str],
    selected_corridor_swimmer_yob: Optional[int],
    moroccan_corridor_swimmer_name: Optional[str] = None,
    moroccan_corridor_swimmer_yob: Optional[int] = None,
    moroccan_corridor_df: Optional[pd.DataFrame] = None,
    corridor_plot_kwargs: Optional[Dict[str, Any]] = None,
    corridor_gender_filter: Optional[str] = None,
    corridor_reference_df: Optional[pd.DataFrame] = None,
    event_counts_sort: str = EVENT_COUNTS_SORT_STROKE_DISTANCE,
) -> Tuple[Optional[plt.Figure], str]:
    """
    Construit la figure pour le menu desktop Flet (noms tels que dans ``GRAPH_CATEGORIES``).

    Args:
        svc (ServiceGraphe): Service graphe fournissant les méthodes ``plot_*``.
        selected_graph (str): Nom du graphe tel qu'affiché dans le menu desktop.
        df (pd.DataFrame): Jeu de données complet (hors scope éventuel).
        df_scope (pd.DataFrame): Données après résolution du scope épreuve.
        df_filtered (pd.DataFrame): Données filtrées pour les graphes globaux.
        stroke (Optional[str]): Code de nage sélectionné.
        distance (Optional[int]): Distance sélectionnée (mètres).
        pool (Optional[str]): Bassin sélectionné (LCM/SCM).
        selected_distance (Any): Distance UI (peut être non numérique).
        selected_chronos_sample_size (int): Taille d'échantillon pour les chronos.
        selected_pacing_swimmers (List[str]): Nageurs cibles pour le pacing.
        selected_heatmap_swimmer (Optional[str]): Nageur cible heatmap.
        selected_corridor_swimmer_name (Optional[str]): Nom du nageur FR couloir.
        selected_corridor_swimmer_yob (Optional[int]): Année de naissance FR.
        moroccan_corridor_swimmer_name (Optional[str]): Nom du nageur MA couloir.
        moroccan_corridor_swimmer_yob (Optional[int]): Année de naissance MA.
        moroccan_corridor_df (Optional[pd.DataFrame]): Données MA pour overlay.
        corridor_plot_kwargs (Optional[Dict[str, Any]]): Kwargs précalculés couloir.
        corridor_gender_filter (Optional[str]): Filtre genre couloir (F/M).
        corridor_reference_df (Optional[pd.DataFrame]): Référence couloir alternative.
        event_counts_sort (str): Mode de tri des graphes de comptage d'épreuves.

    Returns:
        Tuple[Optional[plt.Figure], str]: Figure matplotlib (ou None) et titre affiché.
    """
    fig: Optional[plt.Figure] = None
    chart_title = selected_graph
    corridor_df = (
        corridor_reference_df
        if corridor_reference_df is not None and not corridor_reference_df.empty
        else df
    )
    if corridor_plot_kwargs is not None:
        overlay_kwargs = dict(corridor_plot_kwargs)
    else:
        gender = corridor_gender_filter
        if gender not in ("F", "M"):
            gender = None
        overlay_kwargs = build_corridor_chart_plot_kwargs(
            gender_filter=gender,
            french_name=selected_corridor_swimmer_name,
            french_yob=selected_corridor_swimmer_yob,
            moroccan_name=moroccan_corridor_swimmer_name,
            moroccan_yob=moroccan_corridor_swimmer_yob,
            moroccan_df=moroccan_corridor_df,
        )

    if selected_graph in {
        "Histogramme simple",
        "Histogramme cumulatif",
    }:
        chart_title = "Distribution des temps de nage"
        if not df_filtered.empty:
            if selected_graph == "Histogramme simple":
                fig = svc.plot_histogramme_simple(df_filtered)
            else:
                fig = svc.plot_histogramme_cumulatif(df_filtered)

    elif selected_graph == GRAPH_NOMBRE_PERF_EPREUVE:
        sort_by_total = event_counts_sort == EVENT_COUNTS_SORT_TOTAL_DESC
        if pool and stroke:
            stroke_label = stroke_code_to_label(stroke)
            chart_title = (
                f"Nombre de performances par épreuve — {stroke_label} ({pool})"
            )
            fig = svc.plot_nombre_performances_par_epreuve(
                df_scope,
                course_type=str(pool),
                sort_by_total=sort_by_total,
            )

    elif selected_graph == GRAPH_NOMBRE_PERF_EPREUVE_LCM_SCM:
        sort_by_total = event_counts_sort == EVENT_COUNTS_SORT_TOTAL_DESC
        if stroke:
            stroke_label = stroke_code_to_label(stroke)
            chart_title = (
                f"Nombre de performances par épreuve (LCM + SCM) — {stroke_label}"
            )
        else:
            chart_title = "Nombre de performances par épreuve (LCM + SCM)"
        fig = svc.plot_nombre_performances_par_epreuve_lcm_scm(
            df_scope,
            sort_by_total=sort_by_total,
        )

    elif selected_graph in {"Comptage par sexe (global)", "Comptage par sexe (épreuve)"}:
        chart_title = (
            "Nombre de performances par sexe – global"
            if selected_graph == "Comptage par sexe (global)"
            else "Nombre de performances par sexe – filtres actuels"
        )
        fig = svc.plot_nombre_performances_par_sexe(df_filtered, title=chart_title)

    elif selected_graph == "Camembert par sexe (global)":
        chart_title = "Répartition globale par sexe"
        fig = svc.plot_camembert_sexe_global(df_filtered, title=chart_title)

    elif selected_graph == "Camembert par sexe (épreuve)":
        chart_title = "Proportion des performances par sexe – filtres actuels"
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            fig = svc.plot_camembert_sexe_par_event(
                df_filtered,
                nom_event=nom_event,
                title=chart_title,
            )

    elif selected_graph == "Distribution des temps par type de nage (boxplot)":
        try:
            distance_label = (
                str(int(float(selected_distance)))
                if selected_distance is not None
                else ""
            )
        except (TypeError, ValueError):
            distance_label = str(selected_distance)
        chart_title = (
            f"Distribution des temps par type de nage pour la distance {distance_label} m"
        )
        fig = svc.plot_boxplot_temps_par_nage(df_scope, title=chart_title)

    elif selected_graph == "Top 10 clubs par participation (épreuve)":
        if distance and stroke and pool:
            chart_title = (
                f"Top 10 des clubs – {format_event_label(distance, stroke, pool)}"
            )
        else:
            chart_title = "Top 10 des clubs par nombre de participations – filtres actuels"
        fig = svc.plot_top10_clubs(df_scope, title=chart_title)

    elif selected_graph == "Temps médian des 10 meilleurs clubs":
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = f"Temps médian des 10 meilleurs clubs - {format_event_label(distance, stroke, pool)}"
            fig, _meta = svc.plot_temps_median_top10_clubs_par_event(
                df_scope, nom_event=nom_event, title=chart_title
            )

    elif selected_graph == GRAPH_CHRONOS_PAR_NAGE:
        chart_title = "Évolution des temps médians par nage (à partir de 2000)"
        fig = svc.plot_evolution_temps_nage(
            df,
            start_year=2000,
            sample_size=max(0, int(selected_chronos_sample_size)),
            title=chart_title,
        )

    elif selected_graph == GRAPH_VITESSE_DISTANCE_NAGE:
        chart_title = "Vitesse médiane par distance et type de nage"
        fig = svc.plot_swimming_speed_by_distance_and_stroke(
            df_scope,
            title=chart_title,
        )

    elif selected_graph == GRAPH_VITESSE_MAX_SPLIT_NAGE:
        chart_title = GRAPH_VITESSE_MAX_SPLIT_NAGE
        fig, _dfm = svc.plot_vitesse_max_par_split_et_nage(df_scope)

    elif selected_graph == "Vitesse de split - F vs M + nageurs cibles":
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = (
                f"{format_event_label(distance, stroke, pool)} - vitesse de split - F vs M + nageurs cibles"
            )
            pacing = selected_pacing_swimmers[:3]
            target_colors: Dict[str, str] = {}
            if pacing:
                pal = sns.color_palette("Dark2", n_colors=len(pacing))
                target_colors = {n: to_hex(c) for n, c in zip(pacing, pal)}
            fig, _a, _b, meta = svc.plot_split_speed_analysis_by_gender_with_targets(
                df_scope,
                nom_event=nom_event,
                swimmer_targets=list(pacing),
                target_colors=target_colors,
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err and err != "ok":
                    chart_title = err

    elif selected_graph == MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME:
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = (
                f"Vitesse par segment — peloton vs meilleur nageur · "
                f"{format_event_label(distance, stroke, pool)}"
            )
            fig, _a, _b, meta = svc.plot_temps_median_vs_meilleur_nageur_par_split_event(
                df_scope, nom_event=nom_event
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err and err != "ok":
                    chart_title = err
            elif isinstance(meta, dict) and meta.get("message") == "ok":
                best_name = meta.get("best_name")
                best_time = meta.get("best_swim_time")
                if isinstance(best_name, str) and best_name.strip():
                    if isinstance(best_time, (int, float)):
                        time_label = _format_swim_time_display(
                            float(best_time), precision=2
                        )
                        chart_title = (
                            f"Vitesse par segment — {format_event_label(distance, stroke, pool)} "
                            f"· record {time_label} ({best_name.strip()})"
                        )

    elif selected_graph == MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME:
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = (
                f"Vitesse par segment — peloton vs top 10 · "
                f"{format_event_label(distance, stroke, pool)}"
            )
            fig, _a, _b, meta = svc.plot_temps_median_vs_top10_nageurs_par_split_event(
                df_scope, nom_event=nom_event
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err and err != "ok":
                    chart_title = err
            elif isinstance(meta, dict) and meta.get("message") == "ok":
                top_count = meta.get("top10_count")
                if isinstance(top_count, int) and top_count > 0:
                    chart_title = (
                        f"Vitesse par segment — peloton vs top {top_count} · "
                        f"{format_event_label(distance, stroke, pool)}"
                    )

    elif selected_graph == MEDIAN_SPEED_BY_GENDER_GRAPH_NAME:
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = (
                f"Vitesse par segment selon le genre · "
                f"{format_event_label(distance, stroke, pool)}"
            )
            fig, _med, meta = svc.plot_vitesse_mediane_par_split_selon_genre_top_n_event(
                df_scope, nom_event=nom_event, top_n=10
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err and err != "ok":
                    chart_title = err
            elif isinstance(meta, dict) and meta.get("message") == "ok":
                chart_title = (
                    f"Vitesse par segment F/M (top 10) · "
                    f"{format_event_label(distance, stroke, pool)}"
                )

    elif selected_graph == "Heatmap vitesse moyenne (distance x nage)":
        chart_title = "Synthèse des vitesses – heatmap comparative"
        if selected_heatmap_swimmer:
            fig, meta = svc.plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres(
                df_scope,
                nageur_cible=selected_heatmap_swimmer,
            )
            if isinstance(meta, dict):
                if meta.get("message") == "ok" and meta.get("display_name"):
                    chart_title = (
                        f"Synthèse des vitesses – {meta['display_name']} vs peloton"
                    )
                else:
                    err = str(meta.get("message", ""))
                    if err and err != "ok":
                        chart_title = err

    elif selected_graph == "Couloir de performance (âge) - nageur cible":
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            fr_name = selected_corridor_swimmer_name
            fr_yob = selected_corridor_swimmer_yob
            has_fr = isinstance(fr_name, str) and fr_name.strip()
            has_ma = (
                isinstance(moroccan_corridor_swimmer_name, str)
                and moroccan_corridor_swimmer_name.strip()
                and moroccan_corridor_df is not None
                and not moroccan_corridor_df.empty
            )
            has_specs = bool(overlay_kwargs.get("swimmer_specs"))
            if has_fr or has_ma or has_specs:
                chart_title = f"Couloir de performance - {format_event_label(distance, stroke, pool)}"
                plot_kwargs = dict(overlay_kwargs)
                if plot_kwargs.get("swimmer_specs"):
                    plot_kwargs.pop("overlay_nageur", None)
                    plot_kwargs.pop("overlay_year_of_birth", None)
                fig, meta = svc.plot_performance_corridor_plot_time(
                    corridor_df,
                    nom_event=nom_event,
                    nom_nageur=None
                    if plot_kwargs.get("swimmer_specs")
                    else (fr_name if has_fr else None),
                    year_of_birth=None
                    if plot_kwargs.get("swimmer_specs")
                    else fr_yob,
                    **plot_kwargs,
                )
                if isinstance(meta, dict):
                    warn_parts: List[str] = []
                    if meta.get("overlay_swimmer_message"):
                        warn_parts.append(str(meta["overlay_swimmer_message"]))
                    elif meta.get("swimmer_trace_messages"):
                        msgs = meta.get("swimmer_trace_messages")
                        if isinstance(msgs, list) and msgs:
                            warn_parts.append("; ".join(str(m) for m in msgs))
                    if fig is None:
                        err = str(meta.get("message", ""))
                        chart_title = err or (warn_parts[0] if warn_parts else chart_title)
                    elif warn_parts:
                        chart_title = f"{chart_title} — {warn_parts[0]}"
            elif overlay_kwargs.get("swimmer_specs") or overlay_kwargs:
                chart_title = (
                    f"Couloir de performance global - {format_event_label(distance, stroke, pool)}"
                )
                fig, meta = svc.plot_performance_corridor_global_plot_time(
                    corridor_df,
                    nom_event=nom_event,
                    **overlay_kwargs,
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err:
                        chart_title = err
                    elif meta.get("overlay_swimmer_message"):
                        chart_title = str(meta["overlay_swimmer_message"])
            else:
                # Au démarrage du mode "nageur cible", afficher Graphe28 (global)
                # tant qu'aucun nageur n'a été confirmé.
                chart_title = (
                    f"Couloir de performance global - {format_event_label(distance, stroke, pool)}"
                )
                fig, meta = svc.plot_performance_corridor_global_plot_time(
                    corridor_df,
                    nom_event=nom_event,
                )
                if fig is None and isinstance(meta, dict):
                    err = str(meta.get("message", ""))
                    if err:
                        chart_title = err

    elif selected_graph == "Couloir de performance global (âge)":
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = (
                f"Couloir de performance global - {format_event_label(distance, stroke, pool)}"
            )
            fig, meta = svc.plot_performance_corridor_global_plot_time(
                corridor_df,
                nom_event=nom_event,
                **overlay_kwargs,
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err:
                    chart_title = err
                elif meta.get("overlay_swimmer_message"):
                    chart_title = str(meta["overlay_swimmer_message"])

    elif selected_graph == "Couloir de performance global (déciles 10-90)":
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            chart_title = (
                f"Couloir global (déciles 10-90) - {format_event_label(distance, stroke, pool)}"
            )
            deciles_kwargs: Dict[str, Any] = dict(overlay_kwargs)
            if selected_corridor_swimmer_name:
                deciles_kwargs["nom_nageur"] = selected_corridor_swimmer_name
                if selected_corridor_swimmer_yob is not None:
                    deciles_kwargs["year_of_birth"] = int(
                        selected_corridor_swimmer_yob
                    )
            fig, meta = svc.plot_performance_corridor_global_deciles_plot_time(
                corridor_df,
                nom_event=nom_event,
                **deciles_kwargs,
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err:
                    chart_title = err
                elif meta.get("overlay_swimmer_message"):
                    chart_title = str(meta["overlay_swimmer_message"])

    elif selected_graph == GRAPH_RELAY_SPLIT_DISTANCE:
        if distance and stroke and pool:
            nom_event = f"{distance} {stroke} {pool}"
            nom_event_label = format_event_label(distance, stroke, pool)
            chart_title = (
                f"Vitesse par segment — relais · {nom_event_label}"
            )
            fig, _p, _m, _md, meta = svc.plot_relais_split_speed_par_distance(
                df_scope, nom_event=nom_event
            )
            if fig is None and isinstance(meta, dict):
                err = str(meta.get("message", ""))
                if err and err != "ok":
                    chart_title = err
            elif isinstance(meta, dict) and meta.get("message") == "ok":
                relay_count = meta.get("relay_perf_count")
                if isinstance(relay_count, int) and relay_count > 0:
                    chart_title = (
                        f"Vitesse par segment — relais ({relay_count:,} relais) · "
                        f"{nom_event_label}".replace(",", " ")
                    )

    return fig, chart_title
