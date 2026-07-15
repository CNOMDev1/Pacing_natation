"""Mixin recherche nageurs couloir (FR / USA / Maroc) pour l'UI desktop Flet.

Extrait de ``desktop_flet.PacingDesktopApp`` : modes couloir, dropdowns et
recherche nageur (Extranat, USA Swimming, FRM), plus helpers de scope / overlay
associés à cette UI.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import flet as ft
import pandas as pd

from project_path import ensure_project_imports

ensure_project_imports()

from desktop_helpers import _normalize_text
from desktop_settings import (
    CORRIDOR_CATEGORY,
    CORRIDOR_SWIMMER_UI_GRAPHS,
    COUNTRY_FRANCE,
    COUNTRY_MOROCCO,
    COUNTRY_USA,
)

# Constantes UI partagées avec ``desktop_flet`` (mêmes valeurs littérales).
CORRIDOR_SWIMMER_SUGGESTIONS_MAX = 200
CORRIDOR_SWIMMER_DROPDOWN_OPTIONS_MAX = 100
CORRIDOR_SEARCH_DEBOUNCE_SEC = 0.12
USA_CORRIDOR_SWIMMER_SEARCH_LABEL = "Rechercher un nageur (USA Swimming)"
USA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP = "Nom du nageur"
FR_CORRIDOR_SWIMMER_SEARCH_LABEL = "Rechercher un nageur"
FR_CORRIDOR_SWIMMER_SEARCH_TOOLTIP = "Nom ou annee de naissance"
MA_CORRIDOR_SWIMMER_SEARCH_LABEL = "Rechercher un nageur (Maroc)"
MA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP = "Nom ou annee de naissance"


class DesktopCorridorSwimmerMixin:
    """Mixin : UI recherche / dropdown nageurs couloir (FR, USA, Maroc).

    À mélanger avec ``PacingDesktopApp``. Les méthodes s'appuient sur l'état
    et les widgets Flet de l'application, ainsi que sur ``PacingAppService``.

    Attributes:
        selected_corridor_swimmer_name (str | None): Nageur couloir sélectionné.
        selected_moroccan_corridor_swimmer_name (str | None): Nageur FRM sélectionné.
    """

    def _is_usa_corridor_mode(self) -> bool:
        """ renvoie vrai seulement quand : le pays choisi est États-Unis et la catégorie est « Couloirs de performance »."""
        return (
            self.selected_country == COUNTRY_USA
            and self.selected_category == CORRIDOR_CATEGORY
        )

    def _is_morocco_corridor_mode(self) -> bool:
        return (
            self.selected_country == COUNTRY_MOROCCO
            and self.selected_category == CORRIDOR_CATEGORY
        )

    def _needs_moroccan_corridor_swimmer_dd(self) -> bool:
        """France / États-Unis : liste déroulante FRM en plus du nageur Extranat ou USA."""
        return (
            self.selected_category == CORRIDOR_CATEGORY
            and self.selected_country in (COUNTRY_FRANCE, COUNTRY_USA)
            and (
                self._is_usa_corridor_mode()
                or self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
            )
        )

    def _moroccan_corridor_uses_confirm_button(self) -> bool:
        """Recherche marocaine avec ✓ (France âge ou couloir USA AgeGroup)."""
        return self._needs_moroccan_corridor_swimmer_dd() and (
            self._is_usa_corridor_mode()
            or self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
        )

    def _corridor_swimmer_search_labels(self) -> Tuple[str, str]:
        if self._is_usa_corridor_mode():
            return USA_CORRIDOR_SWIMMER_SEARCH_LABEL, USA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP
        if self._is_morocco_corridor_mode():
            return MA_CORRIDOR_SWIMMER_SEARCH_LABEL, MA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP
        return FR_CORRIDOR_SWIMMER_SEARCH_LABEL, FR_CORRIDOR_SWIMMER_SEARCH_TOOLTIP

    def _corridor_swimmer_dropdown_scope_label(self) -> str:
        if self._is_usa_corridor_mode():
            return "USA"
        if self._is_morocco_corridor_mode():
            return "Maroc"
        return "couloir"

    def _moroccan_corridor_swimmer_labels_for_scope(self) -> List[str]:
        if not (
            self.selected_stroke
            and self.selected_distance is not None
            and self.selected_pool
        ):
            return []
        return self.app.morocco_swimmer_labels(
            stroke=self.selected_stroke,
            distance=int(self.selected_distance),
            pool=self.selected_pool,
            gender=self.selected_corridor_gender,
        )

    def _moroccan_corridor_swimmer_labels_for_event(self, event: str) -> List[str]:
        return self.app.morocco_swimmer_labels(
            event=str(event).strip(),
            gender=self.selected_corridor_gender,
        )

    def _moroccan_corridor_swimmer_labels_for_current_scope(self) -> List[str]:
        if self._is_usa_corridor_mode():
            if not self.selected_usa_event:
                return []
            return self._moroccan_corridor_swimmer_labels_for_event(
                str(self.selected_usa_event)
            )
        return self._moroccan_corridor_swimmer_labels_for_scope()

    def _clear_moroccan_corridor_swimmer_selection(self) -> None:
        self.selected_moroccan_corridor_swimmer_name = None
        self.selected_moroccan_corridor_swimmer_yob = None
        self.corridor_ma_confirmed_name = None
        self.corridor_ma_confirmed_yob = None
        self._moroccan_corridor_dd_options_key = None
        self._moroccan_corridor_swimmer_labels_filter_key = None
        self._set_moroccan_corridor_swimmer_labels_all([])
        if hasattr(self, "corridor_moroccan_swimmer_dd"):
            self.corridor_moroccan_swimmer_dd.value = None
        if self.moroccan_corridor_swimmer_search is not None:
            self.moroccan_corridor_swimmer_search.reset(clear_query=True)
        self.moroccan_corridor_swimmer_search_query = ""

    def _moroccan_corridor_confirmed_label(self) -> Optional[str]:
        """Label affichable « Nom (AAAA) » pour le nageur marocain confirmé (✓)."""
        name = self.corridor_ma_confirmed_name
        if not isinstance(name, str) or not name.strip():
            return None
        name = name.strip()
        yob = self.corridor_ma_confirmed_yob
        labels_all = self._moroccan_corridor_swimmer_labels_all or []
        if labels_all:
            labels_set = self._moroccan_corridor_swimmer_labels_set
            if labels_set is None:
                self._ensure_moroccan_corridor_swimmer_search_index(labels_all)
                labels_set = self._moroccan_corridor_swimmer_labels_set or set()
            if yob is not None:
                label = f"{name} ({yob})"
                if label in labels_set:
                    return label
            if name in labels_set:
                return name
            for candidate in labels_all:
                parsed_name, parsed_yob = self._parse_corridor_swimmer_label(candidate)
                if parsed_name == name and (
                    yob is None or parsed_yob == yob or parsed_yob is None
                ):
                    return candidate
        if yob is not None:
            return f"{name} ({yob})"
        return name

    def _restore_moroccan_corridor_swimmer_confirmed_to_ui(self) -> bool:
        """Réaffiche le nageur marocain confirmé après un rafraîchissement des listes."""
        label = self._moroccan_corridor_confirmed_label()
        if not label:
            return False
        changed = False
        name = self.corridor_ma_confirmed_name
        yob = self.corridor_ma_confirmed_yob
        if self.selected_moroccan_corridor_swimmer_name != name:
            self.selected_moroccan_corridor_swimmer_name = name
            changed = True
        if self.selected_moroccan_corridor_swimmer_yob != yob:
            self.selected_moroccan_corridor_swimmer_yob = yob
            changed = True
        if self._set_moroccan_corridor_swimmer_search_query(label):
            changed = True
        if (
            hasattr(self, "corridor_moroccan_swimmer_dd")
            and self.corridor_moroccan_swimmer_dd.value != label
        ):
            self.corridor_moroccan_swimmer_dd.value = label
            changed = True
        return changed

    def _invalidate_moroccan_corridor_swimmer_label_cache(self) -> None:
        """Invalide les caches de labels marocains sans effacer la sélection confirmée."""
        self._moroccan_corridor_swimmer_search_index_key = None
        self._moroccan_corridor_swimmer_search_index = None
        self._moroccan_corridor_swimmer_labels_set = None

    def _moroccan_corridor_swimmer_filter_key(self) -> Optional[Tuple[Any, ...]]:
        if self._is_usa_corridor_mode():
            if not self.selected_usa_event:
                return None
            return (
                "usa",
                str(self.selected_usa_event),
                self.selected_corridor_gender,
            )
        if not (
            self.selected_stroke
            and self.selected_distance is not None
            and self.selected_pool
        ):
            return None
        return (
            "fr",
            str(self.selected_stroke),
            int(self.selected_distance),
            str(self.selected_pool),
            self.selected_corridor_gender,
        )

    def _set_moroccan_corridor_swimmer_labels_all(self, labels: List[str]) -> None:
        self._moroccan_corridor_swimmer_labels_all = labels
        self._moroccan_corridor_swimmer_labels_filter_key = (
            self._moroccan_corridor_swimmer_filter_key()
        )
        self._moroccan_corridor_swimmer_search_index_key = None
        self._moroccan_corridor_swimmer_search_index = None
        self._moroccan_corridor_swimmer_labels_set = None

    def _ensure_moroccan_corridor_swimmer_search_index(
        self, labels: List[str]
    ) -> List[Tuple[str, str, Tuple[str, ...]]]:
        key = id(labels)
        if (
            self._moroccan_corridor_swimmer_search_index is not None
            and self._moroccan_corridor_swimmer_search_index_key == key
        ):
            return self._moroccan_corridor_swimmer_search_index
        index: List[Tuple[str, str, Tuple[str, ...]]] = []
        for label in labels:
            norm = _normalize_text(label)
            words = tuple(
                w for w in norm.replace("(", " ").replace(")", " ").split() if w
            )
            index.append((label, norm, words))
        self._moroccan_corridor_swimmer_search_index = index
        self._moroccan_corridor_swimmer_search_index_key = key
        self._moroccan_corridor_swimmer_labels_set = set(labels)
        return index

    def _moroccan_corridor_swimmer_autocomplete_event_key(self) -> Tuple[Any, ...]:
        fk = self._moroccan_corridor_swimmer_filter_key()
        return fk if fk is not None else ("ma",)

    def _sync_moroccan_corridor_swimmer_autocomplete(
        self,
        labels_all: List[str],
        query: str,
        *,
        cap_ac: int = CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
    ) -> bool:
        search = self.moroccan_corridor_swimmer_search
        if search is None or not labels_all:
            return False
        base_event_key = self._moroccan_corridor_swimmer_autocomplete_event_key()
        if query and self._moroccan_corridor_swimmer_query_is_exact_label(query):
            return search.clear_suggestions()
        if query:
            labels, _ = self._filter_moroccan_corridor_swimmer_labels_with_count(
                labels_all, query, max_results=cap_ac
            )
            subset = labels[:cap_ac]
            suggestions = self._build_corridor_autocomplete_suggestions(
                subset, query, cap=cap_ac
            )
            return search.apply_suggestions(suggestions)
        search.reset_suggestion_context()
        return search.maybe_sync_suggestions(
            labels_all[:cap_ac],
            base_event_key,
            max_suggestions=cap_ac,
        )

    def _set_moroccan_corridor_swimmer_search_query(self, value: str) -> bool:
        if self.moroccan_corridor_swimmer_search is not None:
            return self.moroccan_corridor_swimmer_search.set_query(value)
        text = (value or "").strip()
        changed = (self.moroccan_corridor_swimmer_search_query or "") != text
        if changed:
            self.moroccan_corridor_swimmer_search_query = text
        return changed

    def _moroccan_corridor_swimmer_dropdown_value(
        self, labels_all: List[str], *, has_query: bool
    ) -> Optional[str]:
        if not has_query:
            pick = self.corridor_moroccan_swimmer_dd.value
            if isinstance(pick, str) and pick.strip():
                return pick.strip()
            return None
        query = (self.moroccan_corridor_swimmer_search_query or "").strip()
        labels_set = self._moroccan_corridor_swimmer_labels_set
        if labels_set is None and labels_all:
            self._ensure_moroccan_corridor_swimmer_search_index(labels_all)
            labels_set = self._moroccan_corridor_swimmer_labels_set or set()
        if query and labels_set and query in labels_set:
            return query
        name = self.selected_moroccan_corridor_swimmer_name
        yob = self.selected_moroccan_corridor_swimmer_yob
        if not name:
            return None
        if yob is not None:
            label = f"{name} ({yob})"
            if labels_set and label in labels_set:
                return label
        if labels_set and name in labels_set:
            return name
        for candidate in labels_all:
            parsed_name, parsed_yob = self._parse_corridor_swimmer_label(candidate)
            if parsed_name == name and (
                yob is None or parsed_yob == yob or parsed_yob is None
            ):
                return candidate
        return name

    def _apply_moroccan_corridor_swimmer_pick(self) -> bool:
        labels_all = self._moroccan_corridor_swimmer_labels_all or []
        query_pick = (self.moroccan_corridor_swimmer_search_query or "").strip()
        if not query_pick:
            changed = self.selected_moroccan_corridor_swimmer_name is not None
            self.selected_moroccan_corridor_swimmer_name = None
            self.selected_moroccan_corridor_swimmer_yob = None
            return changed
        labels_set = self._moroccan_corridor_swimmer_labels_set
        if labels_set is None and labels_all:
            self._ensure_moroccan_corridor_swimmer_search_index(labels_all)
            labels_set = self._moroccan_corridor_swimmer_labels_set or set()
        labels, _ = self._filter_moroccan_corridor_swimmer_labels_with_count(
            labels_all, query_pick, max_results=2
        )
        pick: Optional[str] = None
        if labels_set and query_pick in labels_set:
            pick = query_pick
        elif len(labels) == 1:
            pick = labels[0]
        if not pick:
            dd_pick = self.corridor_moroccan_swimmer_dd.value
            if isinstance(dd_pick, str) and dd_pick.strip():
                pick = dd_pick.strip()
        name, yob = self._parse_corridor_swimmer_label(pick)
        resolved_name = name or pick
        changed = self.selected_moroccan_corridor_swimmer_name != resolved_name
        self.selected_moroccan_corridor_swimmer_name = resolved_name
        self.selected_moroccan_corridor_swimmer_yob = yob
        return changed

    def _refresh_moroccan_corridor_swimmer_ui_from_labels(
        self, labels_all: List[str]
    ) -> None:
        """Met à jour recherche + dropdown nageurs marocains (FRM)."""
        self._set_moroccan_corridor_swimmer_labels_all(labels_all)
        query = (self.moroccan_corridor_swimmer_search_query or "").strip()
        if self.moroccan_corridor_swimmer_search is not None:
            self.moroccan_corridor_swimmer_search.clear_suggestions()
        self._apply_moroccan_corridor_swimmer_pick()
        labels, shown = self._filter_moroccan_corridor_swimmer_labels_with_count(
            labels_all, query
        )
        cap_dd = CORRIDOR_SWIMMER_DROPDOWN_OPTIONS_MAX
        dd_labels = labels[:cap_dd]
        pick = self._moroccan_corridor_swimmer_dropdown_value(
            labels_all, has_query=bool(query)
        )
        labels_set = self._moroccan_corridor_swimmer_labels_set or set()
        if pick and pick not in dd_labels and pick in labels_set:
            dd_labels = ([pick] + dd_labels)[:cap_dd]
        self._sync_dropdown(
            self.corridor_moroccan_swimmer_dd,
            new_option_keys=tuple(dd_labels),
            build_options=lambda dl=dd_labels: [ft.dropdown.Option(l) for l in dl],
            value=pick,
            visible=not self._active_moroccan_corridor_swimmer_search(query),
        )
        total = len(labels_all)
        if not query:
            shown = total
        suffix = self._corridor_swimmer_dropdown_label_suffix(
            has_query=bool(query),
            total=total,
            matches=shown,
            in_menu=len(dd_labels),
        )
        self.corridor_moroccan_swimmer_dd.label = (
            f"Nageur marocain (FRM) — {total} disponibles{suffix}"
        )
        self._sync_moroccan_corridor_confirm_button()
        if self._active_moroccan_corridor_swimmer_search(query):
            self._push_moroccan_corridor_search_results_to_bar(labels_all)
        elif self.moroccan_corridor_swimmer_search is not None:
            self.moroccan_corridor_swimmer_search.clear_search_results()

    def _push_corridor_search_results_to_bar(self, labels_all: List[str]) -> None:
        search = self.corridor_swimmer_search
        if search is None:
            return
        search.clear_suggestions()
        query = (self.corridor_swimmer_search_query or "").strip()
        if not query:
            search.clear_search_results()
            return
        if self._corridor_swimmer_query_is_exact_label(query):
            search.clear_search_results()
            return
        labels, _ = self._filter_corridor_swimmer_labels_with_count(
            labels_all,
            query,
            max_results=CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
        )
        search.set_search_results(
            labels,
            query=query,
            max_rows=min(12, CORRIDOR_SWIMMER_SUGGESTIONS_MAX),
        )

    def _push_moroccan_corridor_search_results_to_bar(self, labels_all: List[str]) -> None:
        search = self.moroccan_corridor_swimmer_search
        if search is None:
            return
        search.clear_suggestions()
        query = (self.moroccan_corridor_swimmer_search_query or "").strip()
        if not query:
            search.clear_search_results()
            return
        if self._moroccan_corridor_swimmer_query_is_exact_label(query):
            search.clear_search_results()
            return
        labels, _ = self._filter_moroccan_corridor_swimmer_labels_with_count(
            labels_all,
            query,
            max_results=CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
        )
        search.set_search_results(
            labels,
            query=query,
            max_rows=min(12, CORRIDOR_SWIMMER_SUGGESTIONS_MAX),
        )

    def _refresh_moroccan_corridor_swimmer_options_lightweight(self) -> None:
        if not self._needs_moroccan_corridor_swimmer_dd():
            return
        labels_all = self._moroccan_corridor_swimmer_labels_for_current_scope()
        if not labels_all:
            return
        self._refresh_moroccan_corridor_swimmer_ui_from_labels(labels_all)

    def _on_moroccan_corridor_swimmer_search_keystroke(self) -> None:
        """Précharge les labels ; suggestions affichées après debounce uniquement."""
        if self.selected_category != CORRIDOR_CATEGORY:
            return
        if not self._needs_moroccan_corridor_swimmer_dd():
            return
        if self._moroccan_corridor_swimmer_labels_all:
            return
        fk = self._moroccan_corridor_swimmer_filter_key()
        if fk is None:
            return
        labels_all = self._moroccan_corridor_swimmer_labels_for_current_scope()
        if labels_all:
            self._set_moroccan_corridor_swimmer_labels_all(labels_all)

    def _schedule_moroccan_corridor_swimmer_search_ui_refresh(self) -> None:
        self._moroccan_corridor_search_ui_gen += 1
        token = self._moroccan_corridor_search_ui_gen

        async def _runner() -> None:
            await asyncio.sleep(CORRIDOR_SEARCH_DEBOUNCE_SEC)
            if token != self._moroccan_corridor_search_ui_gen:
                return
            self._refresh_moroccan_corridor_swimmer_options_lightweight()
            self._update_moroccan_corridor_search_sidebar_controls()

        self.page.run_task(_runner)

    def _update_moroccan_corridor_search_sidebar_controls(self) -> None:
        self._finish_moroccan_search_ui()
        labels_all = self._moroccan_corridor_swimmer_labels_all or []
        if not labels_all:
            fk = self._moroccan_corridor_swimmer_filter_key()
            if fk is not None:
                labels_all = self._moroccan_corridor_swimmer_labels_for_current_scope()
                if labels_all:
                    self._set_moroccan_corridor_swimmer_labels_all(labels_all)
        query = (self.moroccan_corridor_swimmer_search_query or "").strip()
        search = self.moroccan_corridor_swimmer_search
        dd_visible = True
        if search is not None and labels_all and query:
            if self._moroccan_corridor_swimmer_query_is_exact_label(query):
                search.clear_suggestions()
                search.clear_search_results()
            elif self._active_moroccan_corridor_swimmer_search(query):
                self._push_moroccan_corridor_search_results_to_bar(labels_all)
                dd_visible = False
            else:
                search.clear_search_results()
        elif search is not None:
            search.clear_suggestions()
            search.clear_search_results()
        if self.corridor_moroccan_swimmer_dd.visible is not dd_visible:
            self.corridor_moroccan_swimmer_dd.visible = dd_visible
        controls: List[ft.Control] = []
        if self.moroccan_corridor_swimmer_search is not None:
            controls.extend(
                [
                    self.moroccan_corridor_swimmer_search.input,
                    self.moroccan_corridor_swimmer_search.loading_btn,
                    self.moroccan_corridor_swimmer_search.confirm_btn,
                    self.moroccan_corridor_swimmer_search.results_panel,
                ]
            )
        controls.append(self.corridor_moroccan_swimmer_dd)
        for control in controls:
            try:
                control.update()
            except Exception:
                self.page.update()
                return

    def _refresh_moroccan_corridor_swimmer_dropdown(self) -> bool:
        """Recherche + liste déroulante des nageurs marocains (html_results)."""
        visible = self._needs_moroccan_corridor_swimmer_dd()
        changed = False
        if self.moroccan_corridor_swimmer_search_container.visible is not visible:
            self.moroccan_corridor_swimmer_search_container.visible = visible
            changed = True
        if not visible:
            if self.corridor_moroccan_swimmer_dd.visible is not False:
                self.corridor_moroccan_swimmer_dd.visible = False
                changed = True
            if self.corridor_moroccan_swimmer_dd.value is not None:
                self.corridor_moroccan_swimmer_dd.value = None
                changed = True
            return changed

        scope_key = self._moroccan_corridor_swimmer_filter_key()
        if scope_key != self._moroccan_corridor_dd_options_key:
            self._moroccan_corridor_dd_options_key = scope_key
            self._invalidate_moroccan_corridor_swimmer_label_cache()
            changed = True

        labels_all = self._moroccan_corridor_swimmer_labels_for_current_scope()
        if labels_all:
            before = (
                self.selected_moroccan_corridor_swimmer_name,
                self.selected_moroccan_corridor_swimmer_yob,
                self.corridor_moroccan_swimmer_dd.value,
                self.moroccan_corridor_swimmer_search_query,
            )
            self._refresh_moroccan_corridor_swimmer_ui_from_labels(labels_all)
            if self._restore_moroccan_corridor_swimmer_confirmed_to_ui():
                changed = True
            after = (
                self.selected_moroccan_corridor_swimmer_name,
                self.selected_moroccan_corridor_swimmer_yob,
                self.corridor_moroccan_swimmer_dd.value,
                self.moroccan_corridor_swimmer_search_query,
            )
            if before != after:
                changed = True
        elif self.corridor_moroccan_swimmer_dd.visible is not True:
            self.corridor_moroccan_swimmer_dd.visible = True
            changed = True
        if self.moroccan_corridor_swimmer_search is not None:
            if self.moroccan_corridor_swimmer_search.sync_value_to_query():
                changed = True
        if self._sync_moroccan_corridor_confirm_button():
            changed = True
        return changed

    def _infer_frmnatation_year_of_birth(
        self, nom_event: str, nom_nageur: str
    ) -> Optional[int]:
        return self.app.infer_frmnatation_year_of_birth(nom_event, nom_nageur)

    def _infer_yob_from_df_scope(
        self, df_scope: pd.DataFrame, nom_event: str, nom_nageur: str
    ) -> Optional[int]:
        return self.app.infer_yob_from_df_scope(df_scope, nom_event, nom_nageur)

    def _frm_rows_for_corridor_swimmer(
        self,
        *,
        nom_event: str,
        nom_nageur: str,
        year_of_birth: Optional[int],
    ) -> Tuple[Optional[str], Optional[int], pd.DataFrame]:
        return self.app.frm_rows_for_corridor_swimmer(
            nom_event=nom_event,
            nom_nageur=nom_nageur,
            year_of_birth=year_of_birth,
        )

    def _build_corridor_chart_plot_kwargs(
        self,
        *,
        primary_name: Optional[str],
        primary_yob: Optional[int],
        primary_df: Optional[pd.DataFrame],
        overlay_name: Optional[str] = None,
        overlay_yob: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
        gender: Optional[str] = None,
        primary_label: str = "Nageur cible (France)",
        primary_color: Optional[str] = None,
        morocco_primary: bool = False,
        df_scope: Optional[pd.DataFrame] = None,
        nom_event: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.app.build_corridor_plot_kwargs(
            primary_name=primary_name,
            primary_yob=primary_yob,
            primary_df=primary_df,
            overlay_name=overlay_name,
            overlay_yob=overlay_yob,
            overlay_df=overlay_df,
            gender=gender or self.selected_corridor_gender,
            primary_label=primary_label,
            morocco_primary=morocco_primary,
            df_scope=df_scope,
            nom_event=nom_event,
        )

    def _moroccan_corridor_overlay_bundle(
        self,
        *,
        ma_name: Optional[str],
        ma_yob: Optional[int],
        nom_event: str,
        usa_mode: bool = False,
    ) -> Tuple[Optional[str], Optional[int], pd.DataFrame]:
        return self.app.moroccan_corridor_overlay_bundle(
            ma_name=ma_name,
            ma_yob=ma_yob,
            nom_event=nom_event,
            usa_mode=usa_mode,
        )

    def _get_frmnatation_nav_df(self) -> pd.DataFrame:
        return self.app.get_frmnatation_df()

    def _apply_nav_df_for_country(self) -> None:
        self._nav_combos_cache_key = None
        self._nav_combos_cache = None
        self._event_swimmer_options_cache.clear()
        self._heatmap_swimmer_names_cache_id = None
        self._heatmap_swimmer_names_cache = None
        self._heatmap_swimmer_labels_all = []
        self._invalidate_heatmap_swimmer_search_index()
        self._heatmap_dropdown_options = None
        self._heatmap_dropdown_options_ready = False
        self._heatmap_dropdown_df_len = None
        self._registry_swimmer_names_cache = None
        self._scope_performances_cache.clear()
        self.app.clear_scope_cache()
        self.df_nav = self.app.nav_df_for_country(self.selected_country, self.df)

    def _available_categories_for_country(self) -> List[str]:
        return self.app.available_categories(self.selected_country)

    def _available_graphs_for_category(self, category: str) -> List[str]:
        return self.app.available_graphs(self.selected_country, category)

    def _ensure_usa_events_loaded(self) -> List[str]:
        return self.app.list_usa_events()

    def _warm_usa_events_cache(self) -> None:
        """Précharge la liste d'épreuves USA (thread de fond)."""
        try:
            self._ensure_usa_events_loaded()
        except Exception:
            pass

    def _get_usa_corridor_df(self, event: str) -> pd.DataFrame:
        return self.app.get_usa_corridor_df(event)

    def _usa_swimmer_names_for_event(self, event: str) -> List[str]:
        """Noms distincts USA Swimming pour une épreuve."""
        return self.app.usa_swimmer_names(
            event, gender=self._normalize_gender_value(self.selected_corridor_gender)
        )

    def _corridor_swimmer_labels_for_current_scope(self) -> List[str]:
        """Liste des nageurs pour la recherche / dropdown (USA, France ou Maroc)."""
        if self._is_usa_corridor_mode():
            if not self.selected_usa_event:
                return []
            return self._usa_swimmer_names_for_event(str(self.selected_usa_event))
        if self._is_morocco_corridor_mode():
            return self._moroccan_corridor_swimmer_labels_for_scope()
        gender = (
            self.selected_corridor_gender
            if self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
            else "all"
        )
        return self._corridor_swimmer_labels_from_nav(
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            gender,
        )

    def _corridor_swimmer_autocomplete_event_key(self) -> Tuple[Any, ...]:
        if self._is_usa_corridor_mode():
            return (str(self.selected_usa_event or ""), self.selected_corridor_gender)
        return (
            str(self.selected_stroke or ""),
            int(self.selected_distance)
            if self.selected_distance is not None
            else None,
            str(self.selected_pool or ""),
            self.selected_corridor_gender,
        )

    def _corridor_swimmer_query_is_exact_label(self, query: str) -> bool:
        q = (query or "").strip()
        if not q:
            return False
        labels_set = self._corridor_swimmer_labels_set
        if labels_set is None:
            labels_all = self._corridor_swimmer_labels_all or []
            if labels_all:
                self._ensure_corridor_swimmer_search_index(labels_all)
                labels_set = self._corridor_swimmer_labels_set
        return bool(labels_set and q in labels_set)

    def _moroccan_corridor_swimmer_query_is_exact_label(self, query: str) -> bool:
        q = (query or "").strip()
        if not q:
            return False
        labels_set = self._moroccan_corridor_swimmer_labels_set
        if labels_set is None:
            labels_all = self._moroccan_corridor_swimmer_labels_all or []
            if labels_all:
                self._ensure_moroccan_corridor_swimmer_search_index(labels_all)
                labels_set = self._moroccan_corridor_swimmer_labels_set
        return bool(labels_set and q in labels_set)

    def _active_corridor_swimmer_search(self, query: Optional[str] = None) -> bool:
        q = (
            query
            if query is not None
            else (self.corridor_swimmer_search_query or "")
        ).strip()
        return bool(q) and not self._corridor_swimmer_query_is_exact_label(q)

    def _active_moroccan_corridor_swimmer_search(
        self, query: Optional[str] = None
    ) -> bool:
        q = (
            query
            if query is not None
            else (self.moroccan_corridor_swimmer_search_query or "")
        ).strip()
        return bool(q) and not self._moroccan_corridor_swimmer_query_is_exact_label(q)

    def _corridor_swimmer_dropdown_value(
        self, labels_all: List[str], *, has_query: bool
    ) -> Optional[str]:
        """Valeur du dropdown alignée sur la sélection (label complet « Nom (AAAA) » si possible)."""
        if not has_query:
            return None
        query = (self.corridor_swimmer_search_query or "").strip()
        labels_set = self._corridor_swimmer_labels_set
        if labels_set is None and labels_all:
            self._ensure_corridor_swimmer_search_index(labels_all)
            labels_set = self._corridor_swimmer_labels_set or set()
        if query and labels_set and query in labels_set:
            return query
        name = self.selected_corridor_swimmer_name
        yob = self.selected_corridor_swimmer_yob
        if not name:
            return None
        if yob is not None:
            label = f"{name} ({yob})"
            if labels_set and label in labels_set:
                return label
        if labels_set and name in labels_set:
            return name
        for candidate in labels_all:
            parsed_name, parsed_yob = self._parse_corridor_swimmer_label(candidate)
            if parsed_name == name and (
                yob is None or parsed_yob == yob or parsed_yob is None
            ):
                return candidate
        return name

    def _apply_corridor_swimmer_pick(self) -> bool:
        """Synchronise la sélection nageur depuis la recherche (ou le dropdown)."""
        labels_all = self._corridor_swimmer_labels_all or []
        query_pick = (self.corridor_swimmer_search_query or "").strip()
        if not query_pick:
            changed = self.selected_corridor_swimmer_name is not None
            self.selected_corridor_swimmer_name = None
            self.selected_corridor_swimmer_yob = None
            return changed
        labels_set = self._corridor_swimmer_labels_set
        if labels_set is None and labels_all:
            self._ensure_corridor_swimmer_search_index(labels_all)
            labels_set = self._corridor_swimmer_labels_set or set()
        labels, _ = self._filter_corridor_swimmer_labels_with_count(
            labels_all, query_pick, max_results=2
        )
        pick: Optional[str] = None
        if labels_set and query_pick in labels_set:
            pick = query_pick
        elif len(labels) == 1:
            pick = labels[0]
        if not pick:
            dd_pick = self.corridor_swimmer_dd.value
            if isinstance(dd_pick, str) and dd_pick.strip():
                pick = dd_pick.strip()
        name, yob = self._parse_corridor_swimmer_label(pick)
        resolved_name = name or pick
        changed = self.selected_corridor_swimmer_name != resolved_name
        self.selected_corridor_swimmer_name = resolved_name
        self.selected_corridor_swimmer_yob = yob
        return changed


