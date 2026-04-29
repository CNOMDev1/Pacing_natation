from __future__ import annotations
from typing import Any, List, Optional, Tuple
import flet as ft

class SwimmerSearch:
    """
    Recherche + autocompletion pour le "Nageur cible (couloir de perf.)".

    - Le champ est un `ft.AutoComplete`
    - Le filtrage par query continue d'être géré côté app pour le dropdown (cibles).
    - L'autocompletion propose la liste complète des nageurs pour le contexte
      (Stroke/Distance/Bassin/Sexe), et l'UI filtre ensuite selon ce que l'utilisateur
      tape via `ft.AutoComplete`.
    """

    def __init__(self, app: Any, *, width: int) -> None:
        self.app = app

        self._autocomplete_event_key: Optional[Tuple[str, int, str, str]] = None

        # Intitulé discret (pour retrouver l'effet "label TextField")
        self.label = ft.Text(
            "Rechercher un nageur (couloir)",
            size=12,
            color="#9ca3af",
        )

        # `on_change` met à jour la query dans l'app puis relance le refresh UI.
        self.input = ft.AutoComplete(
            width=width,
            suggestions=[],
            tooltip="Nom ou année de naissance",
            on_change=self._handle_change,
        )

        self.container = ft.Column(
            controls=[self.label, self.input],
            spacing=2,
            visible=False,
        )

    # ---------------------------------------------------------------- UI interactions
    def _handle_change(self, e: ft.ControlEvent) -> None:
        self.app.corridor_swimmer_search_query = (e.control.value or "").strip()
        self.app._refresh_filters_from_data()

    def set_visible(self, visible: bool) -> bool:
        changed = self.container.visible is not visible
        self.container.visible = visible
        return changed

    def sync_value_to_query(self) -> bool:
        """
        Sync: `self.input.value` <- `app.corridor_swimmer_search_query`.
        """
        query = self.app.corridor_swimmer_search_query or ""
        # `ft.AutoComplete.value` existe et reflète le texte saisi.
        changed = (self.input.value or "") != query
        if changed:
            self.input.value = query
        return changed

    # ---------------------------------------------------------------- Suggestions helpers
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

