from __future__ import annotations
from typing import Any, List, Optional, Tuple
import flet as ft

class SwimmerSearch:
    def __init__(self, app: Any, *, width: int, label_text: str = "Rechercher un nageur", tooltip: str = "Nom ou annee de naissance", query_attr: str = "corridor_swimmer_search_query", refresh_method_name: str = "_refresh_filters_from_data", confirm_callback_name: str = "_on_confirm_corridor_swimmer", show_confirm_button: bool = False) -> None:
        self.app = app
        self._autocomplete_event_key: Optional[Tuple[str, int, str, str]] = None
        self._last_suggestion_keys: Optional[Tuple[str, ...]] = None
        self._query_attr = query_attr
        self._refresh_method_name = refresh_method_name
        self._confirm_callback_name = confirm_callback_name
        input_width = max(int(width) - 46, 120)
        self.label = ft.Text(label_text, size=12, color="#9ca3af")
        # `on_change` met à jour la query dans l'app puis relance le refresh UI.
        self.input = ft.AutoComplete(width=input_width, suggestions=[], tooltip=tooltip, on_change=self._handle_change)
        self.confirm_btn = ft.IconButton(icon=ft.icons.Icons.CHECK, icon_color="#ffffff", bgcolor="#4ade80", tooltip="Confirmer la recherche", on_click=self._handle_confirm_click, visible=show_confirm_button)
        self.input_row = ft.Row(controls=[self.input, self.confirm_btn], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.container = ft.Column(controls=[self.label, self.input_row], spacing=2, visible=False)

    # UI interactions
    def _handle_change(self, e: ft.ControlEvent) -> None:
        setattr(self.app, self._query_attr, (e.control.value or "").strip())
        if getattr(self.app, "selected_category", None) == "Couloirs de performance":
            keystroke = getattr(self.app, "_on_corridor_swimmer_search_keystroke", None)
            if callable(keystroke):
                keystroke()
            schedule = getattr(
                self.app, "_schedule_corridor_swimmer_search_ui_refresh", None
            )
            if callable(schedule):
                schedule()
            self._update_search_controls()
            return
        refresh_callback = getattr(self.app, self._refresh_method_name, None)
        if callable(refresh_callback):
            refresh_callback()

    def _update_search_controls(self) -> None:
        """Rafraîchit uniquement la zone recherche (évite un page.update() complet)."""
        for control in (self.input, self.confirm_btn):
            try:
                control.update()
            except Exception:
                self.app.page.update()
                return

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

        return dirty

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
        keys = tuple(subset)
        if keys == self._last_suggestion_keys:
            return False
        self._last_suggestion_keys = keys
        self.input.suggestions = [
            ft.AutoCompleteSuggestion(key=label, value=label) for label in subset
        ]
        return True

