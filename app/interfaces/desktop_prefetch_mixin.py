"""Mixin de préchargement au démarrage pour l'UI desktop Flet.

Extrait de ``desktop_flet.PacingDesktopApp`` : workers notebook / event-swimmers /
parquet, et préfetch corridor / heatmap / median / relay / scope. Le mixin
s'appuie sur les helpers de registre et de rendu restés sur l'application.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
from typing import Any, Dict, List, Optional, Tuple

from project_path import ensure_project_imports

ensure_project_imports()

from desktop_helpers import _event_combinations, _slugify
from desktop_settings import (
    CORRIDOR_CATEGORY,
    CORRIDOR_CHART_PREFETCH_GRAPH_NAMES,
    CORRIDOR_CHART_PREFETCH_LIMIT,
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_GRAPH_NAME,
    ENABLE_CORRIDOR_CHART_PREFETCH_ON_START,
    ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START,
    ENABLE_HEATMAP_CHART_PREFETCH_ON_START,
    ENABLE_MEDIAN_VS_BEST_CHART_PREFETCH_ON_START,
    ENABLE_NOTEBOOK_PREFETCH_ON_START,
    ENABLE_PERSISTENT_GRAPH_CACHE,
    ENABLE_RELAY_CHART_PREFETCH_ON_START,
    ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START,
    HEATMAP_CHART_PREFETCH_SWIMMER_LIMIT,
    MEDIAN_VS_BEST_CHART_PREFETCH_LIMIT,
    RELAY_CHART_PREFETCH_LIMIT,
    SCOPE_PERFORMANCES_PREFETCH_GRAPHS,
    SCOPE_PERFORMANCES_PREFETCH_LIMIT,
)
from services.graph_catalog import (
    GRAPH_RELAY_SPLIT_DISTANCE,
    GRAPHES_NOTEBOOK,
    GraphSpec,
    HEATMAP_CATEGORY_NAME,
    HEATMAP_GRAPH_NAME,
    MEDIAN_SPEED_BY_GENDER_GRAPH_NAME,
    MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME,
    MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME,
    RELAY_CATEGORY_NAME,
    SPLIT_COMPARISON_CATEGORY_NAME,
)

# Aligné sur ``desktop_flet`` (cache LRU scope performances).
SCOPE_PERFORMANCES_CACHE_MAX_ENTRIES = 64
SPLIT_COMPARISON_PREFETCH_GRAPH_NAMES: Tuple[str, ...] = (
    MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME,
    MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME,
    MEDIAN_SPEED_BY_GENDER_GRAPH_NAME,
)


class DesktopPrefetchMixin:
    """Mixin : préfetch démarrage (notebook, caches, graphiques).

    À mélanger avec ``PacingDesktopApp``. Les méthodes appellent des helpers
    de l'app (registre JSON, rendu chart, caches event-swimmers / scope).

    Attributes:
        _startup_prefetch_ui: Barre de progression triple au démarrage (optionnel).
        _defer_prefetch_json_write (bool): Diffère l'écriture JSON pendant le pool.
    """

    def _advance_startup_notebook(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        """
        Avance la barre gauche (notebook) de la progression de démarrage.

        Args:
            detail (str): Libellé affiché pour l'étape en cours.
            units (int): Unités à ajouter à la progression.
            show_graph_progress (bool): Affiche la progression graphique si True.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        if startup is not None:
            startup.advance_left(detail, units, show_graph_progress=show_graph_progress)

    def _advance_startup_corridor(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        """
        Avance la barre milieu (couloir) de la progression de démarrage.

        Args:
            detail (str): Libellé affiché pour l'étape en cours.
            units (int): Unités à ajouter à la progression.
            show_graph_progress (bool): Affiche la progression graphique si True.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        if startup is not None:
            startup.advance_middle(detail, units, show_graph_progress=show_graph_progress)

    def _advance_startup_event_swimmers(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        """
        Avance la barre milieu (nageurs / événements) de la progression.

        Args:
            detail (str): Libellé affiché pour l'étape en cours.
            units (int): Unités à ajouter à la progression.
            show_graph_progress (bool): Affiche la progression graphique si True.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        if startup is not None:
            startup.advance_middle(detail, units, show_graph_progress=show_graph_progress)

    def _advance_startup_parquet(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        """
        Avance la barre droite (parquet USA) de la progression de démarrage.

        Args:
            detail (str): Libellé affiché pour l'étape en cours.
            units (int): Unités à ajouter à la progression.
            show_graph_progress (bool): Affiche la progression graphique si True.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        if startup is not None:
            startup.advance_right(detail, units, show_graph_progress=show_graph_progress)

    def _run_notebook_prefetch_worker(self) -> None:
        """
        Worker thread : préfetch des graphiques notebook au démarrage.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        try:
            if (
                ENABLE_NOTEBOOK_PREFETCH_ON_START
                and ENABLE_PERSISTENT_GRAPH_CACHE
                and not self.df.empty
            ):
                self._prefetch_service_notebook_graphs_skip_existing()
            else:
                self._advance_startup_notebook(
                    "Préfetch ignoré (données ou cache disque)",
                    units=1,
                    show_graph_progress=True,
                )
        finally:
            if startup is not None:
                startup.close_gap_left("prefetched_graphs.json")

    def _run_event_swimmers_cache_prefetch_worker(self) -> None:
        """
        Worker thread : charge ou régénère le cache nageurs/événements.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        try:
            if ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START and not self.df.empty:
                self._load_event_swimmers_cache_json()
                if self._event_swimmers_cache:
                    self._advance_startup_event_swimmers(
                        "Cache chargé depuis le disque",
                        units=1,
                        show_graph_progress=True,
                    )
                else:
                    # Pas de cache exploitable : on régénère pour avoir des suggestions rapides.
                    total_events = self._estimate_event_swimmers_total_events()
                    if startup is not None:
                        startup.reconfigure_middle_total(total_events, reset_done=True)
                    self._advance_startup_event_swimmers(
                        "Cache absent/vidé, génération",
                        units=0,
                        show_graph_progress=True,
                    )
                    self._write_event_swimmers_cache_json()
                    self._load_event_swimmers_cache_json()
                self._prefetch_scope_performances_cache_on_startup()
            else:
                self._advance_startup_event_swimmers(
                    "Préchargement désactivé",
                    units=1,
                    show_graph_progress=True,
                )
        finally:
            if startup is not None:
                startup.close_gap_middle("prefetched_event_swimmers.json")

    def _run_usaswimming_parquet_cache_worker(self) -> None:
        """
        Worker thread : vérifie / construit le cache parquet USA Swimming.

        Returns:
            None
        """
        startup = self._startup_prefetch_ui
        try:
            years = self.app.available_years_usa()
            if not years:
                self._advance_startup_parquet(
                    "Aucune source USA Swimming detectee",
                    units=1,
                    show_graph_progress=True,
                )
                return
            self._advance_startup_parquet(
                "Verification du cache parquet",
                units=0,
                show_graph_progress=True,
            )
            self.app.ensure_usa_parquet_cache(
                progress=lambda message: self._advance_startup_parquet(
                    message,
                    units=0,
                    show_graph_progress=True,
                ),
                progress_step=lambda message, _index, _total: self._advance_startup_parquet(
                    message,
                    units=1,
                    show_graph_progress=True,
                ),
            )
        finally:
            if startup is not None:
                startup.close_gap_right("_parquet_cache")

    def _notebook_prefetch_options(self, spec_key: str) -> Dict[str, Any]:
        """
        Construit les options de rendu pour un préfetch notebook.

        Args:
            spec_key (str): Clé de la spécification graphique notebook.

        Returns:
            Dict[str, Any]: Options sérialisables pour la clé de cache.
        """
        return {
            "stroke": None,
            "distance": None,
            "pool": None,
            "heatmap_swimmer": None,
            "corridor_swimmer_name": None,
            "corridor_swimmer_yob": None,
            "pacing_swimmers": [],
            "chronos_sample_size": int(self.selected_chronos_sample_size),
            "service_spec_key": spec_key,
        }

    def _notebook_service_render_key(self, spec: GraphSpec) -> str:
        """
        Calcule la clé de registre pour un rendu notebook préfetché.

        Args:
            spec (GraphSpec): Spécification du graphique notebook.

        Returns:
            str: Clé unique dans ``graph_render_registry``.
        """
        opts = self._notebook_prefetch_options(spec.key)
        chart_id = f"{_slugify('_service_notebook')}__{_slugify(spec.key)}"
        return (
            f"{chart_id}::"
            f"{json.dumps(opts, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        )

    def _register_notebook_service_render(
        self,
        *,
        spec: GraphSpec,
        render_key: str,
        options: Dict[str, Any],
        chart_title: str,
        status: str,
        row_count: int,
        image_base64: Optional[str],
        error: Optional[str] = None,
        skip_json_write: bool = False,
    ) -> None:
        """
        Enregistre un rendu notebook dans le registre et le cache image.

        Args:
            spec (GraphSpec): Spécification du graphique.
            render_key (str): Clé de cache.
            options (Dict[str, Any]): Options de rendu associées.
            chart_title (str): Titre du graphique.
            status (str): Statut du rendu (``ok`` / ``error``).
            row_count (int): Nombre de lignes utilisées.
            image_base64 (Optional[str]): Image encodée, si disponible.
            error (Optional[str]): Message d'erreur éventuel.
            skip_json_write (bool): Si True, n'écrit pas le JSON immédiatement.

        Returns:
            None
        """
        chart_id = f"{_slugify('_service_notebook')}__{_slugify(spec.key)}"
        with self._registry_json_lock:
            self.graph_render_registry[render_key] = {
                "id": chart_id,
                "name": spec.key,
                "category": "_service_notebook",
                "method": spec.method_name,
                "status": status,
                "chart_title": chart_title,
                "row_count": int(row_count),
                "error": error,
                "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "options": options,
                "image_base64": image_base64,
            }
            if image_base64:
                self.chart_image_cache[render_key] = image_base64
        if not skip_json_write:
            self._write_graph_registry_json()

    def _compute_notebook_prefetch_render(
        self, spec: GraphSpec
    ) -> Optional[Tuple[GraphSpec, str, Dict[str, Any], str, str, Optional[str], Optional[str]]]:
        """
        Calcule un rendu notebook préfetchable.

        Args:
            spec (GraphSpec): Spécification du graphique notebook.

        Returns:
            Optional[Tuple]: ``(spec, render_key, options, status, chart_title,
            image_base64, error)`` ou None.
        """
        options = self._notebook_prefetch_options(spec.key)
        render_key = self._notebook_service_render_key(spec)
        result = self.app.compute_notebook_prefetch(spec, self.df, self.df_nav)
        return (
            spec,
            render_key,
            options,
            str(result.get("status", "error")),
            str(result.get("chart_title") or spec.name),
            result.get("image_base64"),
            result.get("error"),
        )

    def _prefetch_service_notebook_graphs_skip_existing(self) -> None:
        """
        Parcourt ``GRAPHES_NOTEBOOK`` : réutilise le cache ou génère et enregistre.

        Returns:
            None
        """
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        if self.df.empty:
            return

        pending_specs: List[GraphSpec] = []
        for spec in GRAPHES_NOTEBOOK:
            options = self._notebook_prefetch_options(spec.key)
            render_key = self._notebook_service_render_key(spec)
            with self._registry_json_lock:
                cached = self.graph_render_registry.get(render_key)
            img = cached.get("image_base64") if isinstance(cached, dict) else None
            if (
                cached
                and cached.get("status") == "ok"
                and isinstance(img, str)
                and len(img) > 0
            ):
                with self._registry_json_lock:
                    self.chart_image_cache[render_key] = img
                self._advance_startup_notebook(
                    spec.name, units=1, show_graph_progress=True
                )
                continue
            pending_specs.append(spec)

        if pending_specs:
            worker_count = max(1, min(4, len(pending_specs)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_spec = {
                    executor.submit(self._compute_notebook_prefetch_render, spec): spec
                    for spec in pending_specs
                }
                for future in concurrent.futures.as_completed(future_to_spec):
                    spec = future_to_spec[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = (
                            spec,
                            self._notebook_service_render_key(spec),
                            self._notebook_prefetch_options(spec.key),
                            "error",
                            spec.name,
                            None,
                            str(exc),
                        )

                    if result is not None:
                        (
                            r_spec,
                            render_key,
                            options,
                            status,
                            chart_title,
                            image_base64,
                            error,
                        ) = result
                        self._register_notebook_service_render(
                            spec=r_spec,
                            render_key=render_key,
                            options=options,
                            chart_title=chart_title,
                            status=status,
                            row_count=len(self.df),
                            image_base64=image_base64,
                            error=error,
                            skip_json_write=True,
                        )
                    self._advance_startup_notebook(
                        spec.name, units=1, show_graph_progress=True
                    )

        if not getattr(self, "_defer_prefetch_json_write", False):
            self._write_graph_registry_json()

    def _prefetch_scope_performances_cache_on_startup(self) -> None:
        """
        Préchauffe un sous-ensemble du cache mémoire des performances (df_scope).

        Accélère les premières interactions liées aux nageurs.

        Returns:
            None
        """
        if (
            not ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START
            or self.df_nav.empty
            or SCOPE_PERFORMANCES_PREFETCH_LIMIT <= 0
            or self._scope_performances_prefetched_on_startup
        ):
            return

        event_combos = self._event_combinations_from_swimmers_cache()
        if not event_combos:
            event_combos = _event_combinations(self.df_nav)
        if not event_combos:
            return

        # Garde de la place dans le LRU pour les interactions post-démarrage.
        available_slots = max(
            0, SCOPE_PERFORMANCES_CACHE_MAX_ENTRIES - len(self._scope_performances_cache)
        )
        if available_slots <= 0:
            return
        target = min(int(SCOPE_PERFORMANCES_PREFETCH_LIMIT), available_slots)
        prefetch_graphs = tuple(
            graph
            for graph in SCOPE_PERFORMANCES_PREFETCH_GRAPHS
            if isinstance(graph, str) and graph.strip()
        ) or (CORRIDOR_GRAPH_NAME,)
        per_graph_target = max(1, target // max(1, len(prefetch_graphs)))

        warmed = 0
        for graph_name in prefetch_graphs:
            warmed_for_graph = 0
            for stroke in sorted(event_combos.keys()):
                by_distance = event_combos.get(stroke, {})
                if not isinstance(by_distance, dict):
                    continue
                for distance in sorted(by_distance.keys()):
                    pools = by_distance.get(distance, [])
                    if not isinstance(pools, list):
                        continue
                    for pool in pools:
                        if not isinstance(pool, str):
                            continue
                        self._get_cached_scope_performances(
                            graph_name=graph_name,
                            stroke=stroke,
                            distance=distance,
                            pool=pool,
                        )
                        warmed += 1
                        warmed_for_graph += 1
                        if warmed >= target:
                            self._write_scope_performances_cache_json()
                            self._scope_performances_prefetched_on_startup = True
                            return
                        if warmed_for_graph >= per_graph_target:
                            break
                    if warmed_for_graph >= per_graph_target:
                        break
                if warmed_for_graph >= per_graph_target:
                    break
        self._write_scope_performances_cache_json()
        self._scope_performances_prefetched_on_startup = True

    def _prefetch_corridor_chart_images_on_startup(self) -> None:
        """
        Pré-rend les couloirs globaux (sans nageur) pour affichage instantané.

        Returns:
            None
        """
        if (
            not ENABLE_CORRIDOR_CHART_PREFETCH_ON_START
            or self.df_nav.empty
            or CORRIDOR_CHART_PREFETCH_LIMIT <= 0
            or self._corridor_charts_prefetched_on_startup
        ):
            return

        event_combos = self._event_combinations_from_swimmers_cache()
        if not event_combos:
            event_combos = _event_combinations(self.df_nav)
        if not event_combos:
            return

        prefetch_graphs = tuple(
            g
            for g in CORRIDOR_CHART_PREFETCH_GRAPH_NAMES
            if isinstance(g, str) and g.strip()
        ) or (CORRIDOR_GLOBAL_GRAPH_NAME,)
        target = int(CORRIDOR_CHART_PREFETCH_LIMIT)
        warmed = 0

        for graph_name in prefetch_graphs:
            for stroke in sorted(event_combos.keys()):
                by_distance = event_combos.get(stroke, {})
                if not isinstance(by_distance, dict):
                    continue
                for distance in sorted(by_distance.keys()):
                    pools = by_distance.get(distance, [])
                    if not isinstance(pools, list):
                        continue
                    for pool in pools:
                        if not isinstance(pool, str):
                            continue
                        snapshot = {
                            "category": CORRIDOR_CATEGORY,
                            "graph": graph_name,
                            "stroke": stroke,
                            "distance": int(distance),
                            "pool": pool,
                            "corridor_name": None,
                            "corridor_yob": None,
                            "deciles_name": None,
                            "deciles_yob": None,
                            "heatmap": None,
                            "pacing": [],
                            "chronos_sample_size": int(self.selected_chronos_sample_size),
                        }
                        _, _, render_key = self._build_render_key_from_snapshot(snapshot)
                        with self._registry_json_lock:
                            cached = self.graph_render_registry.get(render_key)
                            img = (
                                self.chart_image_cache.get(render_key)
                                or (cached or {}).get("image_base64")
                            )
                        if isinstance(img, str) and len(img) > 0:
                            warmed += 1
                            if warmed >= target:
                                self._corridor_charts_prefetched_on_startup = True
                                return
                            continue
                        payload = self._compute_chart_payload(snapshot=snapshot)
                        if payload.get("status") == "ok" and payload.get("image_base64"):
                            self._register_chart_payload(payload)
                        warmed += 1
                        if warmed >= target:
                            self._corridor_charts_prefetched_on_startup = True
                            return
        self._corridor_charts_prefetched_on_startup = True

    def _prefetch_heatmap_charts_on_startup(self) -> None:
        """
        Pré-rend les heatmaps nageur vs peloton pour affichage instantané.

        Les rendus sont enregistrés dans ``prefetched_graphs.json`` avec une clé
        incluant ``heatmap_swimmer`` pour réutilisation immédiate à la sélection.

        Returns:
            None
        """
        if (
            not ENABLE_HEATMAP_CHART_PREFETCH_ON_START
            or not ENABLE_PERSISTENT_GRAPH_CACHE
            or self.df_nav.empty
            or HEATMAP_CHART_PREFETCH_SWIMMER_LIMIT <= 0
            or self._heatmap_charts_prefetched_on_startup
        ):
            return

        swimmers = self._heatmap_swimmer_dropdown_options()[: int(HEATMAP_CHART_PREFETCH_SWIMMER_LIMIT)]
        if not swimmers:
            self._heatmap_charts_prefetched_on_startup = True
            return

        warmed = 0
        for swimmer_name in swimmers:
            snapshot = {
                "country": self.selected_country,
                "category": HEATMAP_CATEGORY_NAME,
                "graph": HEATMAP_GRAPH_NAME,
                "usa_event": None,
                "stroke": None,
                "distance": None,
                "pool": None,
                "corridor_gender": "all",
                "corridor_name": None,
                "corridor_yob": None,
                "moroccan_corridor_name": None,
                "moroccan_corridor_yob": None,
                "deciles_name": None,
                "deciles_yob": None,
                "heatmap": swimmer_name,
                "pacing": [],
                "chronos_sample_size": int(self.selected_chronos_sample_size),
            }
            _, _, render_key = self._build_render_key_from_snapshot(snapshot)
            with self._registry_json_lock:
                cached = self.graph_render_registry.get(render_key)
                img = self.chart_image_cache.get(render_key) or (
                    (cached or {}).get("image_base64")
                )
            if isinstance(img, str) and len(img) > 0:
                warmed += 1
                continue

            payload = self._compute_chart_payload(snapshot=snapshot)
            if payload.get("status") == "ok" and payload.get("image_base64"):
                self._register_chart_payload(payload)
            warmed += 1

        if warmed > 0:
            self._write_graph_registry_json()
        self._heatmap_charts_prefetched_on_startup = True

    def _prefetch_median_vs_best_charts_on_startup(self) -> None:
        """
        Pré-rend les graphiques peloton vs meilleur / top 10 par épreuve.

        Les images sont persistées dans ``prefetched_graphs.json`` pour un affichage
        instantané lors du changement stroke / distance / bassin.

        Returns:
            None
        """
        if (
            not ENABLE_MEDIAN_VS_BEST_CHART_PREFETCH_ON_START
            or not ENABLE_PERSISTENT_GRAPH_CACHE
            or self.df_nav.empty
            or MEDIAN_VS_BEST_CHART_PREFETCH_LIMIT <= 0
            or self._median_vs_best_charts_prefetched_on_startup
        ):
            return

        event_combos = self._event_combinations_from_swimmers_cache()
        if not event_combos:
            event_combos = _event_combinations(self.df_nav)
        if not event_combos:
            self._median_vs_best_charts_prefetched_on_startup = True
            return

        prefetch_graphs = tuple(
            g for g in SPLIT_COMPARISON_PREFETCH_GRAPH_NAMES if isinstance(g, str) and g.strip()
        )
        target = int(MEDIAN_VS_BEST_CHART_PREFETCH_LIMIT)
        warmed = 0
        for graph_name in prefetch_graphs:
            for stroke in sorted(event_combos.keys()):
                by_distance = event_combos.get(stroke, {})
                if not isinstance(by_distance, dict):
                    continue
                for distance in sorted(by_distance.keys()):
                    pools = by_distance.get(distance, [])
                    if not isinstance(pools, list):
                        continue
                    for pool in pools:
                        if not isinstance(pool, str):
                            continue
                        snapshot = {
                            "country": self.selected_country,
                            "category": SPLIT_COMPARISON_CATEGORY_NAME,
                            "graph": graph_name,
                            "usa_event": None,
                            "stroke": stroke,
                            "distance": int(distance),
                            "pool": pool,
                            "corridor_gender": "all",
                            "corridor_name": None,
                            "corridor_yob": None,
                            "moroccan_corridor_name": None,
                            "moroccan_corridor_yob": None,
                            "deciles_name": None,
                            "deciles_yob": None,
                            "heatmap": None,
                            "pacing": [],
                            "chronos_sample_size": int(self.selected_chronos_sample_size),
                        }
                        _, _, render_key = self._build_render_key_from_snapshot(snapshot)
                        with self._registry_json_lock:
                            cached = self.graph_render_registry.get(render_key)
                            img = self.chart_image_cache.get(render_key) or (
                                (cached or {}).get("image_base64")
                            )
                        if isinstance(img, str) and len(img) > 0:
                            warmed += 1
                            if warmed >= target:
                                self._write_graph_registry_json()
                                self._median_vs_best_charts_prefetched_on_startup = True
                                return
                            continue
                        payload = self._compute_chart_payload(snapshot=snapshot)
                        if payload.get("status") == "ok" and payload.get("image_base64"):
                            self._register_chart_payload(payload)
                        warmed += 1
                        if warmed >= target:
                            self._write_graph_registry_json()
                            self._median_vs_best_charts_prefetched_on_startup = True
                            return
        if warmed > 0:
            self._write_graph_registry_json()
        self._median_vs_best_charts_prefetched_on_startup = True

    def _prefetch_relay_charts_on_startup(self) -> None:
        """
        Pré-rend les graphiques de pacing relais par épreuve.

        Les images sont persistées dans ``prefetched_graphs.json`` pour un affichage
        instantané lors du changement stroke / distance / bassin.

        Returns:
            None
        """
        if (
            not ENABLE_RELAY_CHART_PREFETCH_ON_START
            or not ENABLE_PERSISTENT_GRAPH_CACHE
            or self.df_nav.empty
            or RELAY_CHART_PREFETCH_LIMIT <= 0
            or self._relay_charts_prefetched_on_startup
        ):
            return

        event_combos = self._event_combinations_from_swimmers_cache()
        if not event_combos:
            event_combos = _event_combinations(self.df_nav)
        if not event_combos:
            self._relay_charts_prefetched_on_startup = True
            return

        target = int(RELAY_CHART_PREFETCH_LIMIT)
        warmed = 0
        for stroke in sorted(event_combos.keys()):
            by_distance = event_combos.get(stroke, {})
            if not isinstance(by_distance, dict):
                continue
            for distance in sorted(by_distance.keys()):
                pools = by_distance.get(distance, [])
                if not isinstance(pools, list):
                    continue
                for pool in pools:
                    if not isinstance(pool, str):
                        continue
                    snapshot = {
                        "country": self.selected_country,
                        "category": RELAY_CATEGORY_NAME,
                        "graph": GRAPH_RELAY_SPLIT_DISTANCE,
                        "usa_event": None,
                        "stroke": stroke,
                        "distance": int(distance),
                        "pool": pool,
                        "corridor_gender": "all",
                        "corridor_name": None,
                        "corridor_yob": None,
                        "moroccan_corridor_name": None,
                        "moroccan_corridor_yob": None,
                        "deciles_name": None,
                        "deciles_yob": None,
                        "heatmap": None,
                        "pacing": [],
                        "chronos_sample_size": int(self.selected_chronos_sample_size),
                    }
                    _, _, render_key = self._build_render_key_from_snapshot(snapshot)
                    with self._registry_json_lock:
                        cached = self.graph_render_registry.get(render_key)
                        img = self.chart_image_cache.get(render_key) or (
                            (cached or {}).get("image_base64")
                        )
                    if isinstance(img, str) and len(img) > 0:
                        warmed += 1
                        if warmed >= target:
                            self._write_graph_registry_json()
                            self._relay_charts_prefetched_on_startup = True
                            return
                        continue
                    payload = self._compute_chart_payload(snapshot=snapshot)
                    if payload.get("status") == "ok" and payload.get("image_base64"):
                        self._register_chart_payload(payload)
                    warmed += 1
                    if warmed >= target:
                        self._write_graph_registry_json()
                        self._relay_charts_prefetched_on_startup = True
                        return
        if warmed > 0:
            self._write_graph_registry_json()
        self._relay_charts_prefetched_on_startup = True
