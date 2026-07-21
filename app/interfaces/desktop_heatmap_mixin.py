"""Mixin recherche nageurs heatmap pour l'UI desktop Flet.

Extrait de ``desktop_flet.PacingDesktopApp`` : index / filtrage / barre de
recherche et rafraîchissement léger des options nageur pour la heatmap.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

import flet as ft

from project_path import ensure_project_imports

ensure_project_imports()

from desktop_helpers import _normalize_text
from services.graph_catalog import HEATMAP_GRAPH_NAME

# Constantes UI partagées avec ``desktop_flet`` (mêmes valeurs littérales).
HEATMAP_SWIMMER_SEARCH_LABEL = "Rechercher un nageur (heatmap)"
CORRIDOR_SWIMMER_SUGGESTIONS_MAX = 200
CORRIDOR_SEARCH_DEBOUNCE_SEC = 0.12


class DesktopHeatmapMixin:
    """Mixin : UI recherche / sélection nageurs heatmap.

    À mélanger avec ``PacingDesktopApp``. Les méthodes s'appuient sur l'état
    et les widgets Flet de l'application (``heatmap_swimmer_search``, etc.).

    Attributes:
        selected_heatmap_swimmer (str | None): Nageur heatmap sélectionné.
        heatmap_swimmer_search_query (str): Requête courante de la barre heatmap.
    """

    def _on_heatmap_swimmer_change(self, e: ft.ControlEvent) -> None:
        """Met à jour le nageur heatmap et planifie un rendu différé.

        Args:
            e (ft.ControlEvent): Événement Flet du dropdown heatmap.

        Returns:
            None: Met à jour la sélection et programme le rafraîchissement.
        """
        next_swimmer = e.control.value
        if next_swimmer == self.selected_heatmap_swimmer:
            return
        self.selected_heatmap_swimmer = next_swimmer
        self._schedule_deferred_chart_update()

    def _invalidate_heatmap_swimmer_search_index(self) -> None:
        """Réinitialise l'index de recherche heatmap (labels ou jeu de données changé).

        Returns:
            None: Vide les caches d'index et de labels connus.
        """
        self._heatmap_swimmer_search_index_key = None
        self._heatmap_swimmer_search_index = None
        self._heatmap_swimmer_labels_set = None

    def _ensure_heatmap_swimmer_search_index(
        self, labels: List[str]
    ) -> List[Tuple[str, str, Tuple[str, ...]]]:
        """Construit ou retourne l'index normalisé pour filtrer les nageurs heatmap.

        Args:
            labels (List[str]): Liste complète des noms de nageurs.

        Returns:
            List[Tuple[str, str, Tuple[str, ...]]]: Index (label, norm, mots).
        """
        key = id(labels)
        if (
            self._heatmap_swimmer_search_index is not None
            and self._heatmap_swimmer_search_index_key == key
        ):
            return self._heatmap_swimmer_search_index
        index: List[Tuple[str, str, Tuple[str, ...]]] = []
        for label in labels:
            norm = _normalize_text(label)
            words = tuple(
                w for w in norm.replace("(", " ").replace(")", " ").split() if w
            )
            index.append((label, norm, words))
        self._heatmap_swimmer_search_index = index
        self._heatmap_swimmer_search_index_key = key
        self._heatmap_swimmer_labels_set = set(labels)
        return index

    def _filter_heatmap_swimmer_labels_with_count(
        self,
        labels: List[str],
        query: str,
        *,
        max_results: Optional[int] = None,
    ) -> Tuple[List[str], int]:
        """Filtre les nageurs heatmap (préfixe mot puis contains).

        Args:
            labels (List[str]): Noms candidats.
            query (str): Texte saisi dans la barre de recherche.
            max_results (Optional[int]): Limite de résultats retournés.

        Returns:
            Tuple[List[str], int]: Correspondances et total estimé.
        """
        if not labels:
            return [], 0
        search_norm = _normalize_text(query)
        if not search_norm:
            total = len(labels)
            if max_results is not None:
                return labels[:max_results], total
            return list(labels), total

        index = self._ensure_heatmap_swimmer_search_index(labels)
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

    def _heatmap_swimmer_labels_for_search(self) -> List[str]:
        """Liste triée de tous les nageurs disponibles pour la heatmap.

        Returns:
            List[str]: Noms uniques issus de ``df_nav["SwimmerName"]``.
        """
        nav_id = id(self.df_nav)
        if (
            self._heatmap_swimmer_labels_all
            and self._heatmap_swimmer_names_cache_id == nav_id
        ):
            return self._heatmap_swimmer_labels_all
        if self.df_nav.empty or "SwimmerName" not in self.df_nav.columns:
            self._heatmap_swimmer_labels_all = []
            self._heatmap_swimmer_names_cache_id = nav_id
            self._invalidate_heatmap_swimmer_search_index()
            return []
        names = sorted(
            {
                str(name).strip()
                for name in self.df_nav["SwimmerName"].dropna().unique()
                if str(name).strip()
            },
            key=_normalize_text,
        )
        self._heatmap_swimmer_labels_all = names
        self._heatmap_swimmer_names_cache_id = nav_id
        self._invalidate_heatmap_swimmer_search_index()
        return names

    def _heatmap_swimmer_query_is_exact_label(self, query: str) -> bool:
        """Indique si la requête correspond exactement à un nageur connu.

        Args:
            query (str): Texte saisi.

        Returns:
            bool: ``True`` si le nom existe dans l'index heatmap.
        """
        q = (query or "").strip()
        if not q:
            return False
        labels_set = self._heatmap_swimmer_labels_set
        if labels_set is None:
            labels_all = self._heatmap_swimmer_labels_all or []
            if labels_all:
                self._ensure_heatmap_swimmer_search_index(labels_all)
                labels_set = self._heatmap_swimmer_labels_set
        return bool(labels_set and q in labels_set)

    def _active_heatmap_swimmer_search(self, query: Optional[str] = None) -> bool:
        """Recherche heatmap active (requête non vide et pas de correspondance exacte).

        Args:
            query (Optional[str]): Requête à tester ; sinon celle de l'app.

        Returns:
            bool: ``True`` si le panneau de résultats doit s'afficher.
        """
        q = (
            query
            if query is not None
            else (self.heatmap_swimmer_search_query or "")
        ).strip()
        return bool(q) and not self._heatmap_swimmer_query_is_exact_label(q)

    def _set_heatmap_swimmer_search_query(self, value: str) -> bool:
        """Met à jour la requête heatmap et le champ AutoComplete.

        Args:
            value (str): Nom ou fragment de recherche.

        Returns:
            bool: ``True`` si la valeur a changé.
        """
        if self.heatmap_swimmer_search is not None:
            return self.heatmap_swimmer_search.set_query(value)
        text = (value or "").strip()
        changed = (self.heatmap_swimmer_search_query or "") != text
        if changed:
            self.heatmap_swimmer_search_query = text
        return changed

    def _apply_heatmap_swimmer_pick(self) -> bool:
        """Synchronise ``selected_heatmap_swimmer`` depuis la barre de recherche.

        Returns:
            bool: ``True`` si le nageur sélectionné a changé.
        """
        labels_all = self._heatmap_swimmer_labels_for_search()
        query_pick = (self.heatmap_swimmer_search_query or "").strip()
        if not query_pick:
            return False
        labels_set = self._heatmap_swimmer_labels_set
        if labels_set is None and labels_all:
            self._ensure_heatmap_swimmer_search_index(labels_all)
            labels_set = self._heatmap_swimmer_labels_set or set()
        pick: Optional[str] = None
        if labels_set and query_pick in labels_set:
            pick = query_pick
        else:
            labels, _ = self._filter_heatmap_swimmer_labels_with_count(
                labels_all, query_pick, max_results=2
            )
            if len(labels) == 1:
                pick = labels[0]
        if not pick:
            return False
        changed = self.selected_heatmap_swimmer != pick
        self.selected_heatmap_swimmer = pick
        return changed

    def _on_heatmap_swimmer_search_pick(self, label: str) -> None:
        """Sélection d'un nageur depuis la barre de recherche heatmap.

        Args:
            label (str): Nom du nageur choisi.

        Returns:
            None: Met à jour la sélection et planifie le rendu.
        """
        cleaned = (label or "").strip()
        if not cleaned:
            return
        if self.selected_heatmap_swimmer != cleaned:
            self.selected_heatmap_swimmer = cleaned
            self._schedule_deferred_chart_update()

    def _on_heatmap_swimmer_search_keystroke(self) -> None:
        """Précharge la liste complète des nageurs heatmap à la première frappe."""

    def _schedule_heatmap_swimmer_search_ui_refresh(self) -> None:
        """Debounce : suggestions et panneau résultats après la frappe heatmap."""
        self._heatmap_search_ui_gen += 1
        token = self._heatmap_search_ui_gen

        async def _runner() -> None:
            await asyncio.sleep(CORRIDOR_SEARCH_DEBOUNCE_SEC)
            if token != self._heatmap_search_ui_gen:
                return
            self._refresh_heatmap_swimmer_options_lightweight()
            self._update_heatmap_search_sidebar_controls()

        self.page.run_task(_runner)

    def _push_heatmap_search_results_to_bar(self, labels_all: List[str]) -> None:
        """Alimente le panneau de résultats sous la barre de recherche heatmap.

        Args:
            labels_all (List[str]): Noms candidats pour le filtrage.

        Returns:
            None: Met à jour le widget ``SwimmerSearch``.
        """
        search = self.heatmap_swimmer_search
        if search is None:
            return
        search.clear_suggestions()
        query = (self.heatmap_swimmer_search_query or "").strip()
        if not query:
            search.clear_search_results()
            return
        if self._heatmap_swimmer_query_is_exact_label(query):
            search.clear_search_results()
            return
        labels, _ = self._filter_heatmap_swimmer_labels_with_count(
            labels_all,
            query,
            max_results=CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
        )
        search.set_search_results(
            labels,
            query=query,
            max_rows=min(12, CORRIDOR_SWIMMER_SUGGESTIONS_MAX),
        )

    def _sync_heatmap_swimmer_autocomplete(
        self,
        labels_all: List[str],
        query: str,
        *,
        cap_ac: int = CORRIDOR_SWIMMER_SUGGESTIONS_MAX,
    ) -> bool:
        """Met à jour les suggestions AutoComplete pour la heatmap.

        Args:
            labels_all (List[str]): Noms disponibles.
            query (str): Requête courante.
            cap_ac (int): Nombre maximal de suggestions.

        Returns:
            bool: ``True`` si l'UI a été modifiée.
        """
        search = self.heatmap_swimmer_search
        if search is None or not labels_all:
            return False
        if query and self._heatmap_swimmer_query_is_exact_label(query):
            return search.clear_suggestions()
        if query:
            labels, _ = self._filter_heatmap_swimmer_labels_with_count(
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
            ("heatmap", id(labels_all)),
            max_suggestions=cap_ac,
        )

    def _finish_heatmap_search_ui(self) -> bool:
        """Termine l'état « chargement » de la barre de recherche heatmap.

        Returns:
            bool: ``True`` si un contrôle a été mis à jour.
        """
        if self.heatmap_swimmer_search is None:
            return False
        return self.heatmap_swimmer_search.sync_trailing(busy=False)

    def _update_heatmap_search_sidebar_controls(self) -> None:
        """Rafraîchit suggestions et panneau résultats heatmap après debounce."""
        self._finish_heatmap_search_ui()
        query = (self.heatmap_swimmer_search_query or "").strip()
        labels_all = self._heatmap_swimmer_labels_for_search()
        search = self.heatmap_swimmer_search
        if search is not None and labels_all and query:
            if self._heatmap_swimmer_query_is_exact_label(query):
                search.clear_suggestions()
                search.clear_search_results()
                if self._apply_heatmap_swimmer_pick():
                    self._schedule_deferred_chart_update()
            elif self._active_heatmap_swimmer_search(query):
                self._push_heatmap_search_results_to_bar(labels_all)
            else:
                search.clear_search_results()
        elif search is not None:
            search.clear_suggestions()
            search.clear_search_results()
        controls: List[ft.Control] = []
        if search is not None:
            controls.extend(
                [
                    search.input,
                    search.loading_btn,
                    search.results_panel,
                ]
            )
        for control in controls:
            try:
                control.update()
            except Exception:
                self.page.update()
                return

    def _refresh_heatmap_swimmer_ui_from_labels(self, labels_all: List[str]) -> None:
        """Met à jour la barre de recherche heatmap (suggestions et compteur).

        Args:
            labels_all (List[str]): Noms disponibles pour la heatmap.

        Returns:
            None: Synchronise l'UI de recherche.
        """
        query = (self.heatmap_swimmer_search_query or "").strip()
        search = self.heatmap_swimmer_search
        if search is not None:
            search.clear_suggestions()
        total = len(labels_all)
        if search is not None:
            count_text = f"{total:,}".replace(",", " ")
            search.label.value = (
                f"{HEATMAP_SWIMMER_SEARCH_LABEL} — {count_text} nageurs"
            )
        self._sync_heatmap_swimmer_autocomplete(labels_all, query)
        if self._active_heatmap_swimmer_search(query):
            self._push_heatmap_search_results_to_bar(labels_all)
        elif search is not None:
            search.clear_search_results()
        if query and self._heatmap_swimmer_query_is_exact_label(query):
            self._apply_heatmap_swimmer_pick()

    def _refresh_heatmap_swimmer_options_lightweight(self) -> None:
        """Rafraîchissement léger de la recherche heatmap (après debounce)."""
        if self.selected_graph != HEATMAP_GRAPH_NAME:
            return
        labels_all = self._heatmap_swimmer_labels_for_search()
        if not labels_all:
            return
        self._refresh_heatmap_swimmer_ui_from_labels(labels_all)
