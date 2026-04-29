from __future__ import annotations
from typing import Any, List, Optional, Tuple
import flet as ft

class SwimmerSearch:
    """
    Recherche + autocompletion pour le "Nageur cible (couloir de perf.)".
    """
    def __init__(self, app: Any, *, width: int) -> None:
        self.app = app
        self._autocomplete_event_key: Optional[Tuple[str, int, str, str]] = None
        input_width = max(int(width) - 46, 120)
        # Intitulé discret (pour retrouver l'effet "label TextField")
        self.label = ft.Text(
            "Rechercher un nageur (couloir)",
            size=12,
            color="#9ca3af",
        )
        # `on_change` met à jour la query dans l'app puis relance le refresh UI.
        self.input = ft.AutoComplete(
            width=input_width,
            suggestions=[],
            tooltip="Nom ou année de naissance",
            on_change=self._handle_change,
        )
        self.confirm_btn = ft.IconButton(
            icon=ft.icons.Icons.CHECK,
            icon_color="#ffffff",
            bgcolor="#4ade80",
            tooltip="Confirmer le nageur cible",
            on_click=self.app._on_confirm_corridor_swimmer,
            visible=False,
        )
        self.input_row = ft.Row(
            controls=[self.input, self.confirm_btn],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.container = ft.Column(
            controls=[self.label, self.input_row],
            spacing=2,
            visible=False,
        )

    # UI interactions
    def _handle_change(self, e: ft.ControlEvent) -> None:
        self.app.corridor_swimmer_search_query = (e.control.value or "").strip()
        self.app._refresh_filters_from_data()

    def set_visible(self, visible: bool) -> bool:
        changed = self.container.visible is not visible
        self.container.visible = visible
        return changed

    def set_confirm_visible(self, visible: bool) -> bool:
        changed = self.confirm_btn.visible is not visible
        self.confirm_btn.visible = visible
        return changed

    def sync_value_to_query(self) -> bool:
        """
        Sync: `self.input.value` <- `app.corridor_swimmer_search_query`.
        """
        query = self.app.corridor_swimmer_search_query or ""
        changed = (self.input.value or "") != query
        if changed:
            self.input.value = query
        return changed

    # Suggestions helpers
    def _clear_autocomplete(self) -> None:
        self._autocomplete_event_key = None
        if self.input.suggestions:
            self.input.suggestions = []

    def clear_suggestions(self) -> bool:
        """
        Nettoyage léger: suggestions uniquement (pas la query).
        """
        had = bool(self.input.suggestions)
        self._autocomplete_event_key = None
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
        if self.input.suggestions:
            self.input.suggestions = []
            dirty = True

        if (self.input.value or "") != "":
            self.input.value = ""
            dirty = True

        if clear_query and (self.app.corridor_swimmer_search_query or "") != "":
            self.app.corridor_swimmer_search_query = ""
            dirty = True

        return dirty

    def maybe_sync_suggestions(
        self,
        labels_all: List[str],
        event_key: Tuple[str, int, str, str],
    ) -> bool:
        """
        Met à jour `input.suggestions` uniquement si le contexte change
        (Stroke/Distance/Bassin/Sexe).
        """
        if event_key == self._autocomplete_event_key:
            return False

        self._autocomplete_event_key = event_key
        self.input.suggestions = [
            ft.AutoCompleteSuggestion(key=label, value=label) for label in labels_all
        ]
        return True

