"""Mixin handlers d'événements UI pour l'UI desktop Flet.

Extrait de ``desktop_flet.PacingDesktopApp`` : changements pays / catégorie /
graphique / filtres, bascule mode couloir, planification différée USA/couloir,
handlers de sélection nageur (pacing, couloir, Maroc) et helpers dropdown.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional, Tuple

import flet as ft

from project_path import ensure_project_imports

ensure_project_imports()

from desktop_helpers import _normalize_text
from services.graph_catalog import EVENT_COUNTS_SORT_OPTIONS
from desktop_settings import (
    CORRIDOR_CATEGORY,
    CORRIDOR_FR_TARGET_SWIMMER_GRAPHS,
    CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_GRAPH_NAME,
    CORRIDOR_SWIMMER_UI_GRAPHS,
    COUNTRY_FRANCE,
    COUNTRY_MOROCCO,
    COUNTRY_USA,
    USA_CORRIDOR_GRAPH_NAME,
)

# Constantes UI partagées avec ``desktop_flet`` (mêmes valeurs littérales).
CORRIDOR_SWIMMER_SUGGESTIONS_MAX = 200
CORRIDOR_SEARCH_DEBOUNCE_SEC = 0.12


class DesktopHandlersMixin:
    """Mixin : handlers Flet et synchronisation UI associée.

    À mélanger avec ``PacingDesktopApp``. Couvre les callbacks ``on_change``
    de navigation / filtres, la planification asynchrone des listes nageurs
    couloir, et les handlers de pick / confirm recherche.

    Attributes:
        selected_country (str): Pays courant de navigation.
        selected_category (str): Catégorie de graphique sélectionnée.
        selected_graph (str): Graphique sélectionné.
    """

    def _on_country_change(self, e: ft.ControlEvent) -> None:
        """est appelée quand l'utilisateur change le menu « Pays » pour mettre a jour selected_country et préparer un redraw du graphique."""
        self._corridor_search_ui_gen += 1
        self._usa_swimmer_schedule_gen += 1
        self._usa_bootstrap_gen += 1
        picked = e.control.value or COUNTRY_FRANCE
        if picked == COUNTRY_MOROCCO:
            picked = COUNTRY_FRANCE
        self.selected_country = picked
        if self.country_dd.value != picked:
            self.country_dd.value = picked
        self.corridor_usa_confirmed_name = None
        self.corridor_fr_confirmed_name = None
        self.corridor_fr_confirmed_yob = None
        self._apply_nav_df_for_country()
        self._clear_corridor_swimmer_labels_cache()
        if self.corridor_swimmer_search is not None:
            self.corridor_swimmer_search.reset(clear_query=True)
        self.corridor_swimmer_search_query = ""
        if self.heatmap_swimmer_search is not None:
            self.heatmap_swimmer_search.reset(clear_query=True)
        self.heatmap_swimmer_search_query = ""
        defer_usa_bootstrap = False
        defer_fr_swimmers = False
        if self.selected_country == COUNTRY_USA:
            self.selected_graph = USA_CORRIDOR_GRAPH_NAME
            defer_usa_bootstrap = True
        else:
            graphs = self._available_graphs_for_category(self.selected_category)
            if self.selected_graph not in graphs:
                self.selected_graph = graphs[0] if graphs else self.selected_graph
            defer_fr_swimmers = (
                self.selected_category == CORRIDOR_CATEGORY
                and self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
                and self.selected_country == COUNTRY_FRANCE
            )
        self._refresh_filters_from_data(
            skip_usa_swimmer_options=defer_usa_bootstrap,
            skip_usa_events=defer_usa_bootstrap and self._usa_events_cache is None,
            skip_corridor_swimmer_options=defer_fr_swimmers,
        )
        if defer_usa_bootstrap:
            self._try_show_stale_corridor_chart(update_ui=True)
            self._schedule_deferred_usa_corridor_bootstrap()
        elif defer_fr_swimmers:
            self._try_show_stale_corridor_chart(update_ui=True)
            self._schedule_deferred_corridor_swimmer_update()
        self._schedule_deferred_chart_update()

    def _on_usa_event_change(self, e: ft.ControlEvent) -> None:
        self.selected_usa_event = e.control.value
        self.corridor_usa_confirmed_name = None
        self.corridor_fr_confirmed_name = None
        self.corridor_fr_confirmed_yob = None
        self._clear_corridor_swimmer_labels_cache()
        self.corridor_swimmer_search_query = ""
        if self.corridor_swimmer_search is not None:
            self.corridor_swimmer_search.reset(clear_query=True)
        self._refresh_filters_from_data(skip_usa_swimmer_options=True)
        self._try_show_stale_corridor_chart(update_ui=True)
        self._schedule_deferred_usa_corridor_swimmer_update()
        self._schedule_deferred_chart_update()

    def _on_category_change(self, e: ft.ControlEvent) -> None:
        self.selected_category = e.control.value
        graphs = self._available_graphs_for_category(self.selected_category)
        if not graphs:
            return
        self.selected_graph = graphs[0]
        if self.selected_graph != CORRIDOR_GLOBAL_DECILES_GRAPH_NAME:
            self.corridor_deciles_confirmed_name = None
            self.corridor_deciles_confirmed_yob = None
        if self.selected_category == CORRIDOR_CATEGORY:
            self.selected_stroke = None
            self.selected_distance = None
            self.selected_pool = None
        self.graph_dd.options = [ft.dropdown.Option(g) for g in graphs]
        self.graph_dd.value = self.selected_graph
        self._sync_corridor_mode_switch(update_ui=False)
        self._refresh_filters_from_data()
        if self.selected_category == CORRIDOR_CATEGORY:
            self._try_show_stale_corridor_chart(update_ui=True)
        self._schedule_deferred_chart_update()

    def _on_graph_change(self, e: ft.ControlEvent) -> None:
        self.selected_graph = e.control.value
        if self.selected_graph != CORRIDOR_GLOBAL_DECILES_GRAPH_NAME:
            self.corridor_deciles_confirmed_name = None
            self.corridor_deciles_confirmed_yob = None
        if self.selected_graph not in CORRIDOR_FR_TARGET_SWIMMER_GRAPHS:
            self.corridor_fr_confirmed_name = None
            self.corridor_fr_confirmed_yob = None
        self._sync_corridor_mode_switch(update_ui=False)
        self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    def _resolve_corridor_deciles_toggle_target(self, e: ft.ControlEvent) -> bool:
        """
        Déduit l'état cible du switch « déciles 10-90 ».
        Flet peut parfois envoyer l'ancienne valeur dans on_change : on bascule alors
        par rapport au graphique déjà sélectionné.
        """
        want_deciles = bool(e.control.value)
        is_deciles_graph = self.selected_graph == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME
        if want_deciles == is_deciles_graph:
            want_deciles = not is_deciles_graph
        return want_deciles

    def _on_corridor_mode_switch_change(self, e: ft.ControlEvent) -> None:
        if self.selected_category != CORRIDOR_CATEGORY or self._is_usa_corridor_mode():
            return
        want_deciles = self._resolve_corridor_deciles_toggle_target(e)
        self.selected_graph = (
            CORRIDOR_GLOBAL_DECILES_GRAPH_NAME
            if want_deciles
            else CORRIDOR_GRAPH_NAME
        )
        self.corridor_mode_switch.value = want_deciles
        graphs = self._available_graphs_for_category(self.selected_category)
        if self.selected_graph in graphs:
            self.graph_dd.value = self.selected_graph
        if not want_deciles:
            self.corridor_deciles_confirmed_name = None
            self.corridor_deciles_confirmed_yob = None
        self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    def _sync_corridor_mode_switch(self, *, update_ui: bool = True) -> None:
        should_be_visible = (
            self.selected_category == CORRIDOR_CATEGORY
            and not self._is_usa_corridor_mode()
        )
        if self.corridor_mode_switch.visible is not should_be_visible:
            self.corridor_mode_switch.visible = should_be_visible
        should_be_deciles = self.selected_graph == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME
        if self.corridor_mode_switch.value is not should_be_deciles:
            self.corridor_mode_switch.value = should_be_deciles
        if update_ui:
            self.page.update()

    def _on_filter_change(self, e: ft.ControlEvent) -> None:
        if self._is_usa_corridor_mode():
            self.selected_corridor_gender = self._normalize_gender_value(
                self.corridor_gender_dd.value
            )
            self.corridor_usa_confirmed_name = None
            self.corridor_fr_confirmed_name = None
            self.corridor_fr_confirmed_yob = None
            self._usa_names_by_event_key.clear()
            self._refresh_filters_from_data(skip_usa_swimmer_options=True)
            self._try_show_stale_corridor_chart(update_ui=True)
            self._schedule_deferred_usa_corridor_swimmer_update()
            self._schedule_deferred_chart_update()
            return

        self.selected_stroke = self.stroke_dd.value
        self.selected_distance = int(self.distance_dd.value) if self.distance_dd.value else None
        self.selected_pool = self.pool_dd.value
        if self.event_counts_sort_dd.value in EVENT_COUNTS_SORT_OPTIONS:
            self.selected_event_counts_sort = str(self.event_counts_sort_dd.value)
        self.selected_corridor_gender = self._normalize_gender_value(
            self.corridor_gender_dd.value
        )
        # Optimisation UX couloir: update immédiat des filtres, puis chargement
        # asynchrone des nageurs (potentiellement volumineux).
        if self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS and e.control in (
            self.stroke_dd,
            self.distance_dd,
            self.pool_dd,
            self.corridor_gender_dd,
        ):
            self._refresh_filters_from_data(skip_corridor_swimmer_options=True)
            self._try_show_stale_corridor_chart(update_ui=True)
            self._schedule_deferred_corridor_swimmer_update()
        else:
            self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    def _schedule_deferred_corridor_swimmer_update(self) -> None:
        self._corridor_swimmer_schedule_gen += 1
        token = self._corridor_swimmer_schedule_gen

        async def _runner() -> None:
            await self._refresh_corridor_swimmers_async(token)

        self.page.run_task(_runner)

    def _schedule_deferred_usa_corridor_swimmer_update(self) -> None:
        self._usa_swimmer_schedule_gen += 1
        token = self._usa_swimmer_schedule_gen

        async def _runner() -> None:
            await self._refresh_usa_corridor_swimmers_async(token)

        self.page.run_task(_runner)

    def _schedule_deferred_usa_corridor_bootstrap(self) -> None:
        """Charge épreuves (1ère fois) puis nageurs USA sans bloquer l'UI."""
        self._usa_bootstrap_gen += 1
        token = self._usa_bootstrap_gen

        async def _runner() -> None:
            await self._usa_corridor_bootstrap_async(token)

        self.page.run_task(_runner)

    async def _refresh_corridor_swimmers_async(self, token: int) -> None:
        await asyncio.sleep(0)
        if token != self._corridor_swimmer_schedule_gen:
            return
        if self.corridor_swimmer_search is not None:
            self.corridor_swimmer_search.set_busy(True)
        if self.moroccan_corridor_swimmer_search is not None:
            self.moroccan_corridor_swimmer_search.set_busy(True)
        try:
            self._refresh_corridor_swimmer_options_lightweight()
            self._refresh_moroccan_corridor_swimmer_options_lightweight()
            self._refresh_moroccan_corridor_swimmer_dropdown()
        finally:
            self._finish_corridor_search_ui()
            self._finish_moroccan_search_ui()
        self.page.update()

    async def _refresh_usa_corridor_swimmers_async(self, token: int) -> None:
        await asyncio.sleep(0)
        if token != self._usa_swimmer_schedule_gen or not self._is_usa_corridor_mode():
            return
        event = self.selected_usa_event
        if not event:
            return
        loop = asyncio.get_running_loop()
        try:
            labels_all = await loop.run_in_executor(
                self._chart_executor,
                lambda ev=event: self._usa_swimmer_names_for_event(ev),
            )
        except Exception:
            return
        if token != self._usa_swimmer_schedule_gen or not self._is_usa_corridor_mode():
            return
        if self.corridor_swimmer_search is not None:
            self.corridor_swimmer_search.set_busy(True)
        if self.moroccan_corridor_swimmer_search is not None:
            self.moroccan_corridor_swimmer_search.set_busy(True)
        try:
            self._set_corridor_swimmer_labels_all(labels_all)
            self._refresh_usa_corridor_swimmer_ui_from_labels(labels_all)
            self._refresh_moroccan_corridor_swimmer_dropdown()
        finally:
            self._finish_corridor_search_ui()
            self._finish_moroccan_search_ui()
        self.page.update()

    async def _usa_corridor_bootstrap_async(self, token: int) -> None:
        await asyncio.sleep(0)
        if token != self._usa_bootstrap_gen or not self._is_usa_corridor_mode():
            return
        loop = asyncio.get_running_loop()
        if self._usa_events_cache is None:
            try:
                await loop.run_in_executor(
                    self._chart_executor, self._ensure_usa_events_loaded
                )
            except Exception:
                pass
            if token != self._usa_bootstrap_gen or not self._is_usa_corridor_mode():
                return
            events = self._usa_events_cache or []
            if events and self.selected_usa_event not in events:
                self.selected_usa_event = events[0]
            self._refresh_filters_from_data(
                update_ui=False,
                skip_usa_swimmer_options=True,
            )
        if token != self._usa_bootstrap_gen or not self._is_usa_corridor_mode():
            return
        event = self.selected_usa_event
        if not event:
            self.page.update()
            return
        try:
            labels_all = await loop.run_in_executor(
                self._chart_executor,
                lambda ev=event: self._usa_swimmer_names_for_event(ev),
            )
        except Exception:
            self.page.update()
            return
        if token != self._usa_bootstrap_gen or not self._is_usa_corridor_mode():
            return
        self._set_corridor_swimmer_labels_all(labels_all)
        self._refresh_usa_corridor_swimmer_ui_from_labels(labels_all)
        self._refresh_moroccan_corridor_swimmer_dropdown()
        self.page.update()

    def _on_pacing_swimmer_change(self, e: ft.ControlEvent) -> None:
        """Met à jour les nageurs pacing puis planifie un rendu différé.

        Cette méthode ignore les événements déclenchés pendant une
        synchronisation programmatique des dropdowns pour éviter les
        boucles de rendu coûteuses.

        Args:
            e (ft.ControlEvent): Événement Flet déclenché par un dropdown pacing.

        Returns:
            None: Met à jour l'état interne puis programme le rafraîchissement.
        """
        if self._is_syncing_pacing_dropdowns:
            return
        selected = [
            self.pacing_swimmer_dd_1.value,
            self.pacing_swimmer_dd_2.value,
            self.pacing_swimmer_dd_3.value,
        ]
        # Nettoyage: ignore vides et doublons, conserve l'ordre
        cleaned: List[str] = []
        for s in selected:
            if s and s not in cleaned:
                cleaned.append(s)
        next_swimmers = cleaned[:3]
        if next_swimmers == self.selected_pacing_swimmers:
            return
        self.selected_pacing_swimmers = next_swimmers
        self._schedule_deferred_chart_update()

    def _apply_moroccan_corridor_swimmer_label_pick(self, label: str) -> None:
        if isinstance(label, str) and label.strip():
            if self._set_moroccan_corridor_swimmer_search_query(label):
                if self.moroccan_corridor_swimmer_search is not None:
                    self.moroccan_corridor_swimmer_search.clear_suggestions()
                    self.moroccan_corridor_swimmer_search.clear_search_results()
                    try:
                        self.moroccan_corridor_swimmer_search.input.update()
                        self.moroccan_corridor_swimmer_search.results_panel.update()
                    except Exception:
                        self.page.update()
        name, yob = DesktopHandlersMixin._parse_corridor_swimmer_label(label)
        self.selected_moroccan_corridor_swimmer_name = name
        self.selected_moroccan_corridor_swimmer_yob = yob
        if self._moroccan_corridor_uses_confirm_button():
            self._sync_moroccan_corridor_confirm_button()
            try:
                self.page.update()
            except Exception:
                pass
            return
        self._schedule_deferred_chart_update()

    def _on_moroccan_corridor_swimmer_search_pick(self, label: str) -> None:
        if self.corridor_moroccan_swimmer_dd.value != label:
            self.corridor_moroccan_swimmer_dd.value = label
        self._apply_moroccan_corridor_swimmer_label_pick(label)

    def _on_moroccan_corridor_swimmer_change(self, e: ft.ControlEvent) -> None:
        label = e.control.value
        if not isinstance(label, str) or not label.strip():
            return
        self._apply_moroccan_corridor_swimmer_label_pick(label.strip())

    def _resolved_moroccan_corridor_swimmer_label(self) -> Optional[str]:
        """Label nageur marocain depuis la recherche ou le dropdown (bouton ✓)."""
        query = (self.moroccan_corridor_swimmer_search_query or "").strip()
        labels_all = self._moroccan_corridor_swimmer_labels_all or []
        name, yob = self._parse_corridor_swimmer_label(query or None)
        if name:
            self.selected_moroccan_corridor_swimmer_name = name
            self.selected_moroccan_corridor_swimmer_yob = yob
        if query and labels_all:
            labels_set = self._moroccan_corridor_swimmer_labels_set
            if labels_set is None:
                self._ensure_moroccan_corridor_swimmer_search_index(labels_all)
                labels_set = self._moroccan_corridor_swimmer_labels_set or set()
            if query in labels_set:
                return query
            filtered, _ = self._filter_moroccan_corridor_swimmer_labels_with_count(
                labels_all, query, max_results=2
            )
            if query in filtered:
                return query
            if len(filtered) == 1:
                return filtered[0]
        pick = self.corridor_moroccan_swimmer_dd.value
        if isinstance(pick, str) and pick.strip():
            return pick.strip()
        return None

    def _on_confirm_moroccan_corridor_swimmer(self, _: ft.ControlEvent) -> None:
        label = (
            self._resolved_moroccan_corridor_swimmer_label()
            or self.corridor_moroccan_swimmer_dd.value
        )
        if label and self.corridor_moroccan_swimmer_dd.value != label:
            self.corridor_moroccan_swimmer_dd.value = label
        name, yob = DesktopHandlersMixin._parse_corridor_swimmer_label(label)
        if not name:
            return
        self.selected_moroccan_corridor_swimmer_name = name
        self.selected_moroccan_corridor_swimmer_yob = yob
        self.corridor_ma_confirmed_name = name
        self.corridor_ma_confirmed_yob = yob
        if self._set_moroccan_corridor_swimmer_search_query(label or ""):
            if self.moroccan_corridor_swimmer_search is not None:
                try:
                    self.moroccan_corridor_swimmer_search.input.update()
                except Exception:
                    pass
        self._schedule_deferred_chart_update()

    def _moroccan_confirm_visible(self) -> bool:
        return self._moroccan_corridor_uses_confirm_button() and bool(
            self._resolved_moroccan_corridor_swimmer_label()
        )

    def _finish_moroccan_search_ui(self) -> bool:
        if self.moroccan_corridor_swimmer_search is None:
            return False
        return self.moroccan_corridor_swimmer_search.sync_trailing(
            busy=False,
            confirm_available=self._moroccan_confirm_visible(),
        )

    def _sync_moroccan_corridor_confirm_button(self) -> bool:
        if self.moroccan_corridor_swimmer_search is None:
            return False
        return self.moroccan_corridor_swimmer_search.sync_trailing(
            confirm_available=self._moroccan_confirm_visible()
        )

    def _apply_corridor_swimmer_label_pick(self, label: str) -> None:
        if isinstance(label, str) and label.strip():
            if self._set_corridor_swimmer_search_query(label):
                if self.corridor_swimmer_search is not None:
                    self.corridor_swimmer_search.clear_suggestions()
                    self.corridor_swimmer_search.clear_search_results()
                    try:
                        self.corridor_swimmer_search.input.update()
                        self.corridor_swimmer_search.results_panel.update()
                    except Exception:
                        self.page.update()
        name, yob = DesktopHandlersMixin._parse_corridor_swimmer_label(label)
        self.selected_corridor_swimmer_name = name
        self.selected_corridor_swimmer_yob = yob
        if self._is_usa_corridor_mode() or (
            self.selected_country == COUNTRY_FRANCE
            and self.selected_graph in CORRIDOR_FR_TARGET_SWIMMER_GRAPHS
        ):
            self._refresh_filters_from_data()
            return
        if self.selected_graph in (
            CORRIDOR_GLOBAL_GRAPH_NAME,
            CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
        ):
            self._refresh_filters_from_data()
            return
        self._update_chart()

    def _on_corridor_swimmer_search_pick(self, label: str) -> None:
        if self.corridor_swimmer_dd.value != label:
            self.corridor_swimmer_dd.value = label
        self._apply_corridor_swimmer_label_pick(label)
        self._sync_corridor_confirm_button()

    def _on_corridor_swimmer_change(self, e: ft.ControlEvent) -> None:
        label = e.control.value
        if not isinstance(label, str) or not label.strip():
            return
        self._apply_corridor_swimmer_label_pick(label.strip())

    def _on_confirm_corridor_swimmer(self, _: ft.ControlEvent) -> None:
        label = self._resolved_corridor_swimmer_label() or self.corridor_swimmer_dd.value
        if label and self.corridor_swimmer_dd.value != label:
            self.corridor_swimmer_dd.value = label
        if self._is_usa_corridor_mode():
            if not label:
                return
            name, yob = DesktopHandlersMixin._parse_corridor_swimmer_label(label)
            if not name:
                return
            self.corridor_usa_confirmed_name = name
            self.selected_corridor_swimmer_name = name
            self.selected_corridor_swimmer_yob = yob
            self._schedule_deferred_chart_update()
            return
        name, yob = DesktopHandlersMixin._parse_corridor_swimmer_label(label)
        if not name:
            return
        self.selected_corridor_swimmer_name = name
        self.selected_corridor_swimmer_yob = yob
        if (
            self.selected_country == COUNTRY_FRANCE
            and self.selected_graph in CORRIDOR_FR_TARGET_SWIMMER_GRAPHS
        ):
            self.corridor_fr_confirmed_name = name
            self.corridor_fr_confirmed_yob = yob
            self._schedule_deferred_chart_update()
            return
        if self.selected_graph == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME:
            self.corridor_deciles_confirmed_name = name
            self.corridor_deciles_confirmed_yob = yob
        # Depuis le couloir global (âge), la confirmation ouvre le couloir « nageur cible ».
        # En mode déciles 10-90, on reste sur ce graphe et on trace le nageur sur les percentiles.
        if self.selected_graph == CORRIDOR_GLOBAL_GRAPH_NAME:
            self.selected_graph = CORRIDOR_GRAPH_NAME
            self.graph_dd.value = self.selected_graph
        self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    @staticmethod
    def _parse_corridor_swimmer_label(
        label: Optional[str],
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Parse le format : "Name" ou "Name (YYYY)".
        Retourne (None, None) si format invalide.
        """
        if not label:
            return None, None
        if "(" in label and label.endswith(")"):
            name, yob_str = label.rsplit("(", 1)
            name = name.strip()
            yob_str = yob_str[:-1]
            try:
                yob = int(yob_str)
            except ValueError:
                yob = None
            return name, yob
        plain = label.strip()
        if plain:
            return plain, None
        return None, None

    def _resolved_corridor_swimmer_label(self) -> Optional[str]:
        """Label nageur depuis la recherche ou le dropdown (pour afficher le bouton ✓)."""
        query = (self.corridor_swimmer_search_query or "").strip()
        labels_all = self._corridor_swimmer_labels_all or []
        name, yob = self._parse_corridor_swimmer_label(query or None)
        if name:
            self.selected_corridor_swimmer_name = name
            self.selected_corridor_swimmer_yob = yob
        if query and labels_all:
            labels_set = self._corridor_swimmer_labels_set
            if labels_set is None:
                self._ensure_corridor_swimmer_search_index(labels_all)
                labels_set = self._corridor_swimmer_labels_set or set()
            if query in labels_set:
                return query
            filtered, _ = self._filter_corridor_swimmer_labels_with_count(
                labels_all, query, max_results=2
            )
            if query in filtered:
                return query
            if len(filtered) == 1:
                return filtered[0]
        pick = self.corridor_swimmer_dd.value
        if isinstance(pick, str) and pick.strip():
            return pick.strip()
        return None

    def _corridor_confirm_visible(self) -> bool:
        if self._is_usa_corridor_mode():
            return bool(self._resolved_corridor_swimmer_label())
        if self.selected_graph not in CORRIDOR_SWIMMER_UI_GRAPHS:
            return False
        return bool(self._resolved_corridor_swimmer_label())

    def _finish_corridor_search_ui(self) -> bool:
        """Fin de recherche : icône rechargement → bouton ✓ si nageur résolu."""
        if self.corridor_swimmer_search is None:
            return False
        return self.corridor_swimmer_search.sync_trailing(
            busy=False,
            confirm_available=self._corridor_confirm_visible(),
        )

    def _sync_corridor_confirm_button(self) -> bool:
        if self.corridor_swimmer_search is None:
            return False
        return self.corridor_swimmer_search.sync_trailing(
            confirm_available=self._corridor_confirm_visible()
        )

    def _invalidate_corridor_swimmer_search_index(self) -> None:
        self._corridor_swimmer_search_index_key = None
        self._corridor_swimmer_search_index = None
        self._corridor_swimmer_labels_set = None

    def _corridor_swimmer_filter_key(self) -> Optional[Tuple[Any, ...]]:
        if self._is_usa_corridor_mode():
            if not self.selected_usa_event:
                return None
            return (
                "usa",
                str(self.selected_usa_event),
                str(self.selected_corridor_gender),
            )
        if (
            not self.selected_stroke
            or self.selected_distance is None
            or not self.selected_pool
        ):
            return None
        return (
            str(self.selected_stroke),
            int(self.selected_distance),
            str(self.selected_pool),
            str(self.selected_corridor_gender),
        )

    def _clear_corridor_swimmer_labels_cache(self) -> None:
        self._corridor_swimmer_labels_filter_key = None
        self._set_corridor_swimmer_labels_all([])

    def _set_corridor_swimmer_labels_all(self, labels: List[str]) -> None:
        self._corridor_swimmer_labels_all = labels
        self._corridor_swimmer_labels_filter_key = self._corridor_swimmer_filter_key()
        self._invalidate_corridor_swimmer_search_index()

    def _ensure_corridor_swimmer_search_index(
        self, labels: List[str]
    ) -> List[Tuple[str, str, Tuple[str, ...]]]:
        key = id(labels)
        if (
            self._corridor_swimmer_search_index is not None
            and self._corridor_swimmer_search_index_key == key
        ):
            return self._corridor_swimmer_search_index
        index: List[Tuple[str, str, Tuple[str, ...]]] = []
        for label in labels:
            norm = _normalize_text(label)
            words = tuple(
                w
                for w in norm.replace("(", " ").replace(")", " ").split()
                if w
            )
            index.append((label, norm, words))
        self._corridor_swimmer_search_index = index
        self._corridor_swimmer_search_index_key = key
        self._corridor_swimmer_labels_set = set(labels)
        return index

    def _filter_corridor_swimmer_labels_with_count(
        self,
        labels: List[str],
        query: str,
        *,
        max_results: Optional[int] = None,
    ) -> Tuple[List[str], int]:
        """
        Filtre en 2 passes (préfixe mot, puis contains) avec index pré-calculé.
        max_results: arrête la collecte après N correspondances (autocomplete rapide).
        """
        if not labels:
            return [], 0
        search_norm = _normalize_text(query)
        if not search_norm:
            total = len(labels)
            if max_results is not None:
                return labels[:max_results], total
            return list(labels), total

        index = self._ensure_corridor_swimmer_search_index(labels)
        prefix_matches: List[str] = []
        for label, _norm_full, words in index:
            if any(word.startswith(search_norm) for word in words):
                prefix_matches.append(label)
                if max_results is not None and len(prefix_matches) >= max_results:
                    break

        if prefix_matches:
            if max_results is None or len(prefix_matches) < max_results:
                return prefix_matches, len(prefix_matches)
            total_prefix = 0
            for _label, _norm_full, words in index:
                if any(word.startswith(search_norm) for word in words):
                    total_prefix += 1
            return prefix_matches, total_prefix

        contains_matches: List[str] = []
        for label, norm_full, _words in index:
            if search_norm in norm_full:
                contains_matches.append(label)
                if max_results is not None and len(contains_matches) >= max_results:
                    break
        if max_results is None or len(contains_matches) < max_results:
            return contains_matches, len(contains_matches)
        total_contains = sum(
            1 for _label, norm_full, _words in index if search_norm in norm_full
        )
        return contains_matches, total_contains

    def _filter_corridor_swimmer_labels(
        self,
        labels: List[str],
        query: str,
        *,
        max_results: Optional[int] = None,
    ) -> List[str]:
        matches, _ = self._filter_corridor_swimmer_labels_with_count(
            labels, query, max_results=max_results
        )
        return matches

    def _filter_moroccan_corridor_swimmer_labels_with_count(
        self,
        labels: List[str],
        query: str,
        *,
        max_results: Optional[int] = None,
    ) -> Tuple[List[str], int]:
        if not labels:
            return [], 0
        index = self._ensure_moroccan_corridor_swimmer_search_index(labels)
        search_norm = _normalize_text(query)
        if not search_norm:
            total = len(labels)
            if max_results is not None:
                return labels[:max_results], total
            return list(labels), total
        prefix_matches: List[str] = []
        for label, _norm_full, words in index:
            if any(word.startswith(search_norm) for word in words):
                prefix_matches.append(label)
                if max_results is not None and len(prefix_matches) >= max_results:
                    break
        if prefix_matches:
            if max_results is None or len(prefix_matches) < max_results:
                return prefix_matches, len(prefix_matches)
            total_prefix = sum(
                1
                for _label, _norm_full, words in index
                if any(word.startswith(search_norm) for word in words)
            )
            return prefix_matches, total_prefix
        contains_matches: List[str] = []
        for label, norm_full, _words in index:
            if search_norm in norm_full:
                contains_matches.append(label)
                if max_results is not None and len(contains_matches) >= max_results:
                    break
        if max_results is None or len(contains_matches) < max_results:
            return contains_matches, len(contains_matches)
        total_contains = sum(
            1 for _label, norm_full, _words in index if search_norm in norm_full
        )
        return contains_matches, total_contains

    @staticmethod
    def _autocomplete_suggestion_key(label: str, query_norm: str) -> str:
        """
        Clé Flet pour AutoComplete : doit commencer par le texte tapé (filtre Flet).
        value reste le nom complet affiché à l'utilisateur.
        """
        if not query_norm:
            norm = _normalize_text(label)
            return norm or label
        return f"{query_norm}|{label}"

    def _build_corridor_autocomplete_suggestions(
        self,
        labels: List[str],
        query: str,
        *,
        cap: int = CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
    ) -> List[ft.AutoCompleteSuggestion]:
        query_norm = _normalize_text(query)
        suggestions: List[ft.AutoCompleteSuggestion] = []
        used_keys: set[str] = set()
        for label in labels[: max(1, int(cap))]:
            key = self._autocomplete_suggestion_key(label, query_norm)
            unique_key = key
            suffix = 2
            while unique_key in used_keys:
                unique_key = f"{key}#{suffix}"
                suffix += 1
            used_keys.add(unique_key)
            suggestions.append(
                ft.AutoCompleteSuggestion(key=unique_key, value=label)
            )
        return suggestions

    def _corridor_swimmer_labels_for_search(self) -> List[str]:
        if self._is_usa_corridor_mode():
            if not self.selected_usa_event:
                return []
            filter_key = self._corridor_swimmer_filter_key()
            if (
                self._corridor_swimmer_labels_all
                and filter_key is not None
                and self._corridor_swimmer_labels_filter_key == filter_key
            ):
                return list(self._corridor_swimmer_labels_all)
            labels = self._usa_swimmer_names_for_event(str(self.selected_usa_event))
            if labels:
                self._set_corridor_swimmer_labels_all(labels)
            return labels
        if not (
            self.selected_stroke
            and self.selected_distance is not None
            and self.selected_pool
        ):
            return []
        filter_key = self._corridor_swimmer_filter_key()
        if (
            self._corridor_swimmer_labels_all
            and filter_key is not None
            and self._corridor_swimmer_labels_filter_key == filter_key
        ):
            return self._corridor_swimmer_labels_all
        labels = self._corridor_swimmer_labels_for_current_scope()
        self._set_corridor_swimmer_labels_all(labels)
        return labels

    def _sync_corridor_swimmer_autocomplete(
        self,
        labels_all: List[str],
        query: str,
        *,
        base_event_key: Tuple[Any, ...],
        cap_ac: int = CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
    ) -> bool:
        if self.corridor_swimmer_search is None or not labels_all:
            return False
        if query and self._corridor_swimmer_query_is_exact_label(query):
            return self.corridor_swimmer_search.clear_suggestions()
        if query:
            labels, _ = self._filter_corridor_swimmer_labels_with_count(
                labels_all, query, max_results=cap_ac
            )
            subset = labels[:cap_ac]
            suggestions = self._build_corridor_autocomplete_suggestions(
                subset, query, cap=cap_ac
            )
            return self.corridor_swimmer_search.apply_suggestions(suggestions)
        self.corridor_swimmer_search.reset_suggestion_context()
        return self.corridor_swimmer_search.maybe_sync_suggestions(
            labels_all[:cap_ac],
            base_event_key,
            max_suggestions=cap_ac,
        )

    def _set_corridor_swimmer_search_query(self, value: str) -> bool:
        """Met à jour la query et le champ AutoComplete (ex. sélection dans le dropdown)."""
        if self.corridor_swimmer_search is not None:
            return self.corridor_swimmer_search.set_query(value)
        text = (value or "").strip()
        changed = (self.corridor_swimmer_search_query or "") != text
        if changed:
            self.corridor_swimmer_search_query = text
        return changed

    def _on_corridor_swimmer_search_keystroke(self) -> None:
        """Suggestions et panneau résultats affichés après debounce uniquement."""

    def _schedule_corridor_swimmer_search_ui_refresh(self) -> None:
        """Debounce: suggestions, dropdown et libellés après la frappe."""
        self._corridor_search_ui_gen += 1
        token = self._corridor_search_ui_gen

        async def _runner() -> None:
            await asyncio.sleep(CORRIDOR_SEARCH_DEBOUNCE_SEC)
            if token != self._corridor_search_ui_gen:
                return
            self._refresh_corridor_swimmer_options_lightweight()
            self._update_corridor_search_sidebar_controls()

        self.page.run_task(_runner)

    def _update_corridor_search_sidebar_controls(self) -> None:
        self._finish_corridor_search_ui()
        query = (self.corridor_swimmer_search_query or "").strip()
        labels_all = self._corridor_swimmer_labels_for_search()
        search = self.corridor_swimmer_search
        dd_visible = True
        if search is not None and labels_all and query:
            if self._corridor_swimmer_query_is_exact_label(query):
                search.clear_suggestions()
                search.clear_search_results()
            elif self._active_corridor_swimmer_search(query):
                self._push_corridor_search_results_to_bar(labels_all)
                dd_visible = False
            else:
                search.clear_search_results()
        elif search is not None:
            search.clear_suggestions()
            search.clear_search_results()
        if self.corridor_swimmer_dd.visible is not dd_visible:
            self.corridor_swimmer_dd.visible = dd_visible
        controls: List[ft.Control] = []
        if self.corridor_swimmer_search is not None:
            controls.extend(
                [
                    self.corridor_swimmer_search.input,
                    self.corridor_swimmer_search.loading_btn,
                    self.corridor_swimmer_search.confirm_btn,
                    self.corridor_swimmer_search.results_panel,
                ]
            )
        controls.append(self.corridor_swimmer_dd)
        for control in controls:
            try:
                control.update()
            except Exception:
                self.page.update()
                return

    # ----------------------------------------------------------------- Data-driven filters
    @staticmethod
    def _corridor_swimmer_dropdown_label_suffix(
        *,
        has_query: bool,
        total: int,
        matches: int,
        in_menu: int,
    ) -> str:
        """Suffixe du libellé dropdown (correspondances vs entrées réellement listées)."""
        if not has_query:
            return ""
        if matches > in_menu:
            return f" ({matches} correspondances, {in_menu} dans le menu)"
        if matches < total:
            return f" ({matches} affichés)"
        return ""

    @staticmethod
    def _menu_height_for_count(option_count: int) -> int:
        return max(72, min(320, 56 * max(1, option_count)))

    @staticmethod
    def _dropdown_option_keys(dd: ft.Dropdown) -> Tuple[str, ...]:
        """Empreinte stable des options pour éviter des réassignations inutiles."""
        opts = dd.options or []
        keys: List[str] = []
        for o in opts:
            k = getattr(o, "key", None)
            if k is not None:
                keys.append(str(k))
                continue
            t = getattr(o, "text", None)
            keys.append("" if t is None else str(t))
        return tuple(keys)

    def _sync_dropdown(
        self,
        dd: ft.Dropdown,
        *,
        new_option_keys: Tuple[str, ...],
        build_options: Callable[[], List[ft.dropdown.Option]],
        value: Optional[str],
        visible: bool,
    ) -> bool:
        """Met à jour un dropdown seulement si options, valeur, hauteur menu ou visibilité changent."""
        changed = False
        if self._dropdown_option_keys(dd) != new_option_keys:
            dd.options = build_options()
            changed = True
        mh = self._menu_height_for_count(len(new_option_keys))
        if dd.menu_height != mh:
            dd.menu_height = mh
            changed = True
        if dd.value != value:
            dd.value = value
            changed = True
        if dd.visible != visible:
            dd.visible = visible
            changed = True
        return changed
