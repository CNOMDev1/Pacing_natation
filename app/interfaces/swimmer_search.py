from __future__ import annotations
from typing import Any, Callable, List, Optional, Tuple
import flet as ft

SEARCH_RESULTS_ROW_HEIGHT = 36
SEARCH_RESULTS_PANEL_MAX_HEIGHT = 320


class SwimmerSearch:
    def __init__(
        self,
        app: Any,
        *,
        width: int,
        label_text: str = "Rechercher un nageur",
        tooltip: str = "Nom ou annee de naissance",
        query_attr: str = "corridor_swimmer_search_query",
        refresh_method_name: str = "_refresh_filters_from_data",
        confirm_callback_name: str = "_on_confirm_corridor_swimmer",
        keystroke_callback_name: str = "_on_corridor_swimmer_search_keystroke",
        schedule_ui_refresh_callback_name: str = "_schedule_corridor_swimmer_search_ui_refresh",
        pick_callback_name: str = "_on_corridor_swimmer_search_pick",
        show_confirm_button: bool = False,
    ) -> None:
        self.app = app
        self._autocomplete_event_key: Optional[Tuple[Any, ...]] = None
        self._last_suggestion_keys: Optional[Tuple[str, ...]] = None
        self._query_attr = query_attr
        self._refresh_method_name = refresh_method_name
        self._confirm_callback_name = confirm_callback_name
        self._keystroke_callback_name = keystroke_callback_name
        self._schedule_ui_refresh_callback_name = schedule_ui_refresh_callback_name
        self._pick_callback_name = pick_callback_name
        self._show_confirm_slot = show_confirm_button
        self._busy = False
        self._confirm_available = False
        slot_width = 40 if show_confirm_button else 0
        input_width = max(int(width) - slot_width, 120)
        self.label = ft.Text(label_text, size=12, color="#9ca3af")
        self.input = ft.AutoComplete(
            width=input_width,
            suggestions=[],
            suggestions_max_height=320,
            tooltip=tooltip,
            on_change=self._handle_change,
            on_select=self._handle_autocomplete_select,
        )
        self.loading_btn = ft.IconButton(
            icon=ft.icons.Icons.AUTORENEW,
            icon_size=20,
            icon_color="#9ca3af",
            tooltip="Recherche en cours...",
            visible=False,
            disabled=True,
        )
        self.confirm_btn = ft.IconButton(
            icon=ft.icons.Icons.CHECK,
            icon_color="#ffffff",
            bgcolor="#4ade80",
            tooltip="Confirmer la recherche",
            on_click=self._handle_confirm_click,
            visible=False,
        )
        self.input_row = ft.Row(
            controls=[self.input, self.loading_btn, self.confirm_btn],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.results_empty = ft.Text(
            "Aucun nageur trouvé",
            size=12,
            color="#9ca3af",
            visible=False,
        )
        self.results_list = ft.ListView(
            controls=[],
            spacing=0,
            padding=0,
            auto_scroll=True,
            height=0,
        )
        self.results_panel = ft.Container(
            content=ft.Column(
                controls=[self.results_empty, self.results_list],
                spacing=4,
                tight=True,
            ),
            visible=False,
            border=ft.Border.all(1, "#374151"),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=4, vertical=4),
            bgcolor="#1f2937",
            width=input_width,
        )
        self.container = ft.Column(
            controls=[self.label, self.input_row, self.results_panel],
            spacing=4,
            visible=False,
        )

    def _apply_trailing_visibility(self) -> bool:
        if not self._show_confirm_slot:
            load_vis = False
            confirm_vis = False
        else:
            load_vis = self._busy
            confirm_vis = (not self._busy) and self._confirm_available
        changed = False
        for ctrl, vis in (
            (self.loading_btn, load_vis),
            (self.confirm_btn, confirm_vis),
        ):
            if ctrl.visible is not vis:
                ctrl.visible = vis
                changed = True
        return changed

    def set_busy(self, busy: bool) -> bool:
        self._busy = bool(busy)
        return self._apply_trailing_visibility()

    def set_confirm_available(self, available: bool) -> bool:
        self._confirm_available = bool(available)
        return self._apply_trailing_visibility()

    def sync_trailing(
        self,
        *,
        busy: Optional[bool] = None,
        confirm_available: Optional[bool] = None,
    ) -> bool:
        if busy is not None:
            self._busy = bool(busy)
        if confirm_available is not None:
            self._confirm_available = bool(confirm_available)
        return self._apply_trailing_visibility()

    def _handle_change(self, e: ft.ControlEvent) -> None:
        setattr(self.app, self._query_attr, (e.control.value or "").strip())
        if getattr(self.app, "selected_category", None) == "Couloirs de performance":
            if self._show_confirm_slot:
                self.set_busy(True)
            self.clear_suggestions()
            self.clear_search_results()
            keystroke = getattr(self.app, self._keystroke_callback_name, None)
            if callable(keystroke):
                keystroke()
            schedule = getattr(self.app, self._schedule_ui_refresh_callback_name, None)
            if callable(schedule):
                schedule()
            self._update_search_controls()
            return
        refresh_callback = getattr(self.app, self._refresh_method_name, None)
        if callable(refresh_callback):
            refresh_callback()

    def _update_search_controls(self) -> None:
        """Rafraîchit uniquement la zone recherche (évite un page.update() complet)."""
        for control in (
            self.input,
            self.loading_btn,
            self.confirm_btn,
            self.results_panel,
        ):
            try:
                control.update()
            except Exception:
                self.app.page.update()
                return

    def _handle_autocomplete_select(self, e: ft.AutoCompleteSelectEvent) -> None:
        selection = getattr(e, "selection", None)
        label = ""
        if selection is not None:
            label = str(getattr(selection, "value", "") or getattr(selection, "key", ""))
        if label.strip():
            self._pick_label(label.strip())

    def _pick_label(self, label: str) -> None:
        self.set_query(label)
        self.clear_suggestions()
        self.clear_search_results()
        pick_callback = getattr(self.app, self._pick_callback_name, None)
        if callable(pick_callback):
            pick_callback(label)
        self._update_search_controls()

    def _handle_confirm_click(self, e: ft.ControlEvent) -> None:
        confirm_callback = getattr(self.app, self._confirm_callback_name, None)
        if callable(confirm_callback):
            confirm_callback(e)

    def set_visible(self, visible: bool) -> bool:
        changed = self.container.visible is not visible
        self.container.visible = visible
        return changed

    def sync_value_to_query(self) -> bool:
        """Sync: `self.input.value` <- `app.corridor_swimmer_search_query`."""
        query = getattr(self.app, self._query_attr, "") or ""
        changed = (self.input.value or "") != query
        if changed:
            self.input.value = query
        return changed

    def set_query(self, value: str) -> bool:
        """Sync: `app.corridor_swimmer_search_query` et `self.input.value` <- `value`."""
        text = (value or "").strip()
        dirty = False
        if (getattr(self.app, self._query_attr, "") or "") != text:
            setattr(self.app, self._query_attr, text)
            dirty = True
        if (self.input.value or "") != text:
            self.input.value = text
            dirty = True
        return dirty

    def clear_suggestions(self) -> bool:
        """Nettoyage léger: suggestions uniquement (pas la query)"""
        had = bool(self.input.suggestions)
        self._autocomplete_event_key = None
        self._last_suggestion_keys = None
        self.input.suggestions = []
        return had

    def reset(self, *, clear_query: bool) -> bool:
        """
        Reset complet "recherche":
        - suggestions vidées
        - input.value vidée
        - (optionnel) query app vidée
        """
        dirty = False

        self._autocomplete_event_key = None
        self._last_suggestion_keys = None
        if self.input.suggestions:
            self.input.suggestions = []
            dirty = True

        if (self.input.value or "") != "":
            self.input.value = ""
            dirty = True

        current_query = getattr(self.app, self._query_attr, "") or ""
        if clear_query and current_query != "":
            setattr(self.app, self._query_attr, "")
            dirty = True

        if self.set_busy(False):
            dirty = True
        if self.clear_search_results():
            dirty = True
        return dirty

    def clear_search_results(self) -> bool:
        changed = self.results_panel.visible
        self.results_panel.visible = False
        self.results_empty.visible = False
        if self.results_list.controls:
            self.results_list.controls = []
            changed = True
        if self.results_list.height != 0:
            self.results_list.height = 0
            changed = True
        return changed

    def set_search_results(
        self,
        labels: List[str],
        *,
        query: str,
        max_rows: int = 12,
    ) -> bool:
        """Affiche les nageurs trouvés sous la barre de recherche."""
        q = (query or "").strip()
        if not q:
            return self.clear_search_results()

        cap = max(1, int(max_rows))
        subset = list(labels[:cap])
        changed = False

        if not subset:
            if not self.results_empty.visible:
                self.results_empty.visible = True
                changed = True
            if self.results_list.controls:
                self.results_list.controls = []
                changed = True
            panel_height = 36
        else:
            if self.results_empty.visible:
                self.results_empty.visible = False
                changed = True
            row_controls = [
                self._result_row(label) for label in subset
            ]
            if len(self.results_list.controls) != len(row_controls):
                changed = True
            else:
                for ctrl, label in zip(self.results_list.controls, subset):
                    title = getattr(ctrl, "data", None)
                    if title != label:
                        changed = True
                        break
            if changed:
                self.results_list.controls = row_controls

            panel_height = min(
                SEARCH_RESULTS_PANEL_MAX_HEIGHT,
                len(subset) * SEARCH_RESULTS_ROW_HEIGHT + 8,
            )

        if self.results_list.height != panel_height:
            self.results_list.height = panel_height
            changed = True
        if not self.results_panel.visible:
            self.results_panel.visible = True
            changed = True
        return changed

    def _result_row(self, label: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(label, size=13, color="#e5e7eb"),
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            data=label,
            on_click=self._row_click(label),
            ink=True,
        )

    def _row_click(self, label: str) -> Callable[[ft.ControlEvent], None]:
        def _handler(_: ft.ControlEvent) -> None:
            self._pick_label(label)

        return _handler

    def maybe_sync_suggestions(
        self,
        labels_all: List[str],
        event_key: Tuple[str, int, str, str],
        *,
        max_suggestions: int = 80,
    ) -> bool:
        """
        Met à jour `input.suggestions` uniquement si le contexte change
        (Stroke/Distance/Bassin/Sexe). Limite le nombre de widgets Flet créés.
        """
        if event_key == self._autocomplete_event_key:
            return False

        self._autocomplete_event_key = event_key
        cap = max(1, int(max_suggestions))
        subset = labels_all[:cap]
        keys = tuple(subset)
        if keys == self._last_suggestion_keys:
            return False
        self._last_suggestion_keys = keys
        self.input.suggestions = [
            ft.AutoCompleteSuggestion(key=label, value=label) for label in subset
        ]
        return True

    def reset_suggestion_context(self) -> None:
        """Force le prochain maybe_sync_suggestions à réappliquer les suggestions."""
        self._autocomplete_event_key = None
        self._last_suggestion_keys = None

    def set_filtered_suggestions(self, labels: List[str], *, max_suggestions: int = 80) -> bool:
        """Met à jour les suggestions pour une recherche (sans recréer des milliers d'entrées)."""
        cap = max(1, int(max_suggestions))
        subset = labels[:cap]
        suggestions = [
            ft.AutoCompleteSuggestion(key=label, value=label) for label in subset
        ]
        return self.apply_suggestions(suggestions)

    def apply_suggestions(self, suggestions: List[ft.AutoCompleteSuggestion]) -> bool:
        """Applique une liste de suggestions (clés Flet adaptées au filtre interne)."""
        keys = tuple(
            (str(s.key or ""), str(s.value or "")) for s in (suggestions or [])
        )
        if keys == self._last_suggestion_keys:
            return False
        self._last_suggestion_keys = keys
        self.input.suggestions = list(suggestions or [])
        return True
