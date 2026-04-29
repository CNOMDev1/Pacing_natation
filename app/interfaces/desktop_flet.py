import asyncio
import concurrent.futures
from collections import OrderedDict
import datetime as dt
import json
import os
import threading
import traceback
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import flet as ft
import matplotlib.pyplot as plt
import pandas as pd

from project_path import PROJECT_DIR, ensure_project_imports

ensure_project_imports()

from corridor_prefetch import CorridorPrefetchManager
from SwimmerSearch import SwimmerSearch
from desktop_helpers import (
    _build_df_nav,
    _event_combinations,
    _figure_to_base64,
    _materialize_df_scope,
    _normalize_text,
    _primary_swimmer_name,
    _primary_swimmer_name_and_yob,
    _resolve_scope_filters,
    _slugify,
    load_data,
)
from services.graph_service import (
    GRAPH_CATEGORIES,
    GRAPHES_NOTEBOOK,
    SCOPE_NO_FILTER_GRAPHS,
    SCOPE_NO_STROKE_GRAPHS,
    SCOPE_POOL_ONLY_GRAPHS,
    GraphSpec,
    ServiceGraphe,
    unwrap_matplotlib_figure,
)

EXTRANAT_OUTPUT_BASE_DIR = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "extranat"
    / "competitions_per_type"
)

GRAPH_EXPORT_PATH = PROJECT_DIR / "data" / "exports" / "prefetched_graphs.json"
CORRIDOR_GRAPHS_EXPORT_PATH = (
    PROJECT_DIR / "data" / "exports" / "prefetched_corridor_graphs.json"
)
EVENT_SWIMMERS_EXPORT_PATH = (
    PROJECT_DIR / "data" / "exports" / "prefetched_event_swimmers.json"
)
EXPORT_IMAGE_BASE64_TO_JSON = True
ENABLE_PERSISTENT_GRAPH_CACHE = True
if ENABLE_PERSISTENT_GRAPH_CACHE:
    EXPORT_IMAGE_BASE64_TO_JSON = True
ENABLE_NOTEBOOK_PREFETCH_ON_START = True
ENABLE_CORRIDOR_PREFETCH_ON_START = False
ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START = True
ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START = True
SCOPE_PERFORMANCES_PREFETCH_LIMIT = int(
    os.environ.get("PACING_SCOPE_PERFORMANCES_PREFETCH_LIMIT", "48")
)
CORRIDOR_PREFETCH_MAX_RENDERS = int(os.environ.get("PACING_CORRIDOR_PREFETCH_MAX", "2500"))
CORRIDOR_GRAPH_NAME = "Couloir de performance (âge) - nageur cible"
CORRIDOR_GLOBAL_GRAPH_NAME = "Couloir de performance global (âge)"
CORRIDOR_CATEGORY = "Couloirs de performance"
CORRIDOR_SWIMMER_UI_GRAPHS: Tuple[str, ...] = (
    CORRIDOR_GRAPH_NAME,
    CORRIDOR_GLOBAL_GRAPH_NAME,
)
CHART_UPDATE_AFTER_FILTER_DEBOUNCE_SEC = 0.12
SCOPE_PERFORMANCES_CACHE_MAX_ENTRIES = 64
SCOPE_PERFORMANCES_PREFETCH_GRAPHS: Tuple[str, ...] = (
    CORRIDOR_GRAPH_NAME,
    CORRIDOR_GLOBAL_GRAPH_NAME,
)


class LoadingBar:
    def __init__(
        self,
        page: ft.Page,
        total_units: int,
        *,
        header: str = "CHARGEMENT",
        subheader: str = "Demarrage de l'application",
    ) -> None:
        self.page = page
        self.total_units = max(int(total_units), 1)
        self.completed = 0
        self.progress = ft.ProgressBar(width=520, value=0.0, color="#f8fafc", bgcolor="#1f2937")
        self.percent_text = ft.Text(
            "0%",
            size=16,
            weight=ft.FontWeight.BOLD,
            color="#f8fafc",
        )
        self.detail_text = ft.Text("Initialisation...", size=12, color="#9ca3af")
        self.header_text = ft.Text(header, size=30, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.subheader_text = ft.Text(subheader, size=11, color="#9ca3af")
        self.container = ft.Container(
            expand=True,
            content=ft.Column(
                controls=[
                    self.header_text,
                    self.subheader_text,
                    ft.Container(height=12),
                    self.progress,
                    self.percent_text,
                    self.detail_text,
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            bgcolor="#000000",
            padding=ft.Padding(left=48, top=0, right=48, bottom=0),
        )

    def mount(self) -> None:
        self.page.bgcolor = "#000000"
        self.page.clean()
        self.page.add(self.container)
        self.page.update()
        time.sleep(0.06)

    def advance(self, detail: str, units: int = 1, *, show_graph_progress: bool = False) -> None:
        self.completed += max(int(units), 0)
        ratio = min(self.completed / self.total_units, 1.0)
        pct_str = f"{int(round(ratio * 100))}%"
        n, t = self.completed, self.total_units
        if show_graph_progress:
            detail_str = f"Graphes configurés : {n}/{t} — {detail}"
        else:
            detail_str = f"{n}/{t} — {detail}"
        page = self.page

        async def _flush_ui() -> None:
            self.progress.value = ratio
            self.percent_text.value = pct_str
            self.detail_text.value = detail_str
            page.update()

        page.run_task(_flush_ui)

    def reconfigure_phase(
        self,
        *,
        total_units: int,
        header: str,
        subheader: str,
    ) -> None:
        """Deuxième barre / étape suivante : remet la progression à zéro et change les libellés."""
        self.total_units = max(int(total_units), 1)
        self.completed = 0
        hdr, sub = header, subheader
        page = self.page

        async def _apply() -> None:
            self.header_text.value = hdr
            self.subheader_text.value = sub
            self.progress.value = 0.0
            self.percent_text.value = "0%"
            self.detail_text.value = "Initialisation..."
            page.update()

        page.run_task(_apply)
        time.sleep(0.06)

    def close_gap_to_100(self, detail: str = "Terminé") -> None:
        """Complète la barre si des unités n’ont pas été consommées."""
        gap = self.total_units - self.completed
        if gap > 0:
            self.advance(detail, units=gap, show_graph_progress=True)


class DualPrefetchProgress:
    """Deux barres de progression en parallèle (gauche : graphes généraux, droite : couloirs)."""

    def __init__(
        self,
        page: ft.Page,
        total_left: int,
        total_right: int,
        left_path: str,
        right_path: str,
        *,
        right_header: str = "Couloirs — prefetched_corridor_graphs.json",
        right_progress_label: str = "Couloirs",
    ) -> None:
        self.page = page
        self._lock = threading.Lock()
        self.left_total = max(1, int(total_left))
        self.right_total = max(1, int(total_right))
        self.left_done = 0
        self.right_done = 0
        self.right_progress_label = right_progress_label
        self.left_pb = ft.ProgressBar(width=360, value=0.0, color="#f8fafc", bgcolor="#1f2937")
        self.right_pb = ft.ProgressBar(width=360, value=0.0, color="#93c5fd", bgcolor="#1f2937")
        self.left_pct = ft.Text("0%", size=14, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.right_pct = ft.Text("0%", size=14, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.left_detail = ft.Text("…", size=11, color="#9ca3af")
        self.right_detail = ft.Text("…", size=11, color="#9ca3af")
        self.container = ft.Container(
            expand=True,
            bgcolor="#000000",
            padding=ft.Padding(left=24, top=32, right=24, bottom=32),
            content=ft.Column(
                [
                    ft.Text(
                        "CHARGEMENT (parallèle)",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color="#f8fafc",
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(height=16),
                    ft.Row(
                        [
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    [
                                        ft.Text("Graphes — prefetched_graphs.json", size=13, weight=ft.FontWeight.BOLD, color="#e5e7eb"),
                                        ft.Text(left_path, size=10, color="#6b7280"),
                                        self.left_pb,
                                        self.left_pct,
                                        self.left_detail,
                                    ],
                                    spacing=8,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ),
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    [
                                        ft.Text(right_header, size=13, weight=ft.FontWeight.BOLD, color="#e5e7eb"),
                                        ft.Text(right_path, size=10, color="#6b7280"),
                                        self.right_pb,
                                        self.right_pct,
                                        self.right_detail,
                                    ],
                                    spacing=8,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ),
                        ],
                        expand=True,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def mount(self) -> None:
        self.page.bgcolor = "#000000"
        self.page.clean()
        self.page.add(self.container)
        self.page.update()
        time.sleep(0.06)

    def _flush_left(self, ratio: float, detail_str: str) -> None:
        page = self.page

        async def _run() -> None:
            self.left_pb.value = ratio
            self.left_pct.value = f"{int(round(ratio * 100))}%"
            self.left_detail.value = detail_str
            page.update()

        page.run_task(_run)

    def _flush_right(self, ratio: float, detail_str: str) -> None:
        page = self.page

        async def _run() -> None:
            self.right_pb.value = ratio
            self.right_pct.value = f"{int(round(ratio * 100))}%"
            self.right_detail.value = detail_str
            page.update()

        page.run_task(_run)

    def advance_left(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        with self._lock:
            self.left_done += max(int(units), 0)
            ratio = min(self.left_done / self.left_total, 1.0)
            n, t = self.left_done, self.left_total
        if show_graph_progress:
            detail_str = f"Graphes : {n}/{t} — {detail}"
        else:
            detail_str = f"{n}/{t} — {detail}"
        self._flush_left(ratio, detail_str)

    def advance_right(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        with self._lock:
            self.right_done += max(int(units), 0)
            ratio = min(self.right_done / self.right_total, 1.0)
            n, t = self.right_done, self.right_total
        if show_graph_progress:
            detail_str = f"{self.right_progress_label} : {n}/{t} — {detail}"
        else:
            detail_str = f"{n}/{t} — {detail}"
        self._flush_right(ratio, detail_str)

    def close_gap_left(self, detail: str = "Terminé") -> None:
        with self._lock:
            gap = self.left_total - self.left_done
        if gap > 0:
            self.advance_left(detail, units=gap, show_graph_progress=True)

    def close_gap_right(self, detail: str = "Terminé") -> None:
        with self._lock:
            gap = self.right_total - self.right_done
        if gap > 0:
            self.advance_right(detail, units=gap, show_graph_progress=True)

    def reconfigure_right_total(self, total_units: int, *, reset_done: bool = True) -> None:
        """Met à jour la taille de la barre droite (utile quand on découvre le total au runtime)."""
        with self._lock:
            self.right_total = max(1, int(total_units))
            if reset_done:
                self.right_done = 0
            ratio = 0.0
        # On rafraîchit l'affichage sans avancer la progression.
        self._flush_right(ratio, f"0/{self.right_total} — Initialisation...")


class PacingDesktopApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.page.title = "Pacing – Desktop"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#020617"
        self.page.padding = 0

        self.loading_bar: Optional[LoadingBar] = None
        self._dual_prefetch_ui: Optional[DualPrefetchProgress] = None
        self._defer_prefetch_json_write: bool = False
        self._ui_light_mode: bool = False
        self._sidebar_container: Optional[ft.Container] = None
        self._main_area_container: Optional[ft.Container] = None
        self._theme_toggle_btn: Optional[ft.IconButton] = None
        self._nav_title_text: Optional[ft.Text] = None
        self.page.run_thread(self._bootstrap_startup)

    def _advance_startup_notebook(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        dual = self._dual_prefetch_ui
        if dual is not None:
            dual.advance_left(detail, units, show_graph_progress=show_graph_progress)
        elif self.loading_bar is not None:
            self.loading_bar.advance(
                detail=detail, units=units, show_graph_progress=show_graph_progress
            )

    def _advance_startup_corridor(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        dual = self._dual_prefetch_ui
        if dual is not None:
            dual.advance_right(detail, units, show_graph_progress=show_graph_progress)
        elif self.loading_bar is not None:
            self.loading_bar.advance(
                detail=detail, units=units, show_graph_progress=show_graph_progress
            )

    def _advance_startup_event_swimmers(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        dual = self._dual_prefetch_ui
        if dual is not None:
            dual.advance_right(detail, units, show_graph_progress=show_graph_progress)
        elif self.loading_bar is not None:
            self.loading_bar.advance(
                detail=detail, units=units, show_graph_progress=show_graph_progress
            )

    def _run_notebook_prefetch_worker(self) -> None:
        dual = self._dual_prefetch_ui
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
            if dual is not None:
                dual.close_gap_left("prefetched_graphs.json")

    def _run_corridor_prefetch_worker(
        self, corridor_tasks: List[Tuple[str, int, str, str, int, int]]
    ) -> None:
        dual = self._dual_prefetch_ui
        try:
            if (
                corridor_tasks
                and ENABLE_PERSISTENT_GRAPH_CACHE
                and not self.df.empty
            ):
                self._prefetch_corridor_graphs_skip_existing(corridor_tasks)
            else:
                self._advance_startup_corridor(
                    "Aucun préchargement couloir (liste vide ou cache inactif)",
                    units=1,
                    show_graph_progress=True,
                )
        finally:
            if dual is not None:
                dual.close_gap_right("prefetched_corridor_graphs.json")

    def _run_event_swimmers_cache_prefetch_worker(self) -> None:
        dual = self._dual_prefetch_ui
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
                    if dual is not None:
                        dual.reconfigure_right_total(total_events, reset_done=True)
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
            if dual is not None:
                dual.close_gap_right("prefetched_event_swimmers.json")

    def _bootstrap_startup(self) -> None:
        """pipeline de démarrrage"""
        try:
            self.df: pd.DataFrame = load_data()
            self.df_nav: pd.DataFrame = _build_df_nav(self.df) 

            # Selections courantes
            self.selected_category: str = list[str](GRAPH_CATEGORIES.keys())[0]
            self.selected_graph: str = GRAPH_CATEGORIES[self.selected_category][0]
            self.selected_stroke: Optional[str] = None
            self.selected_distance: Optional[int] = None
            self.selected_pool: Optional[str] = None
            self.selected_corridor_gender: str = "all"
            self.selected_heatmap_swimmer: Optional[str] = None
            self.selected_corridor_swimmer_name: Optional[str] = None
            self.selected_corridor_swimmer_yob: Optional[int] = None
            self.corridor_swimmer_search_query: str = ""
            self.selected_pacing_swimmers: List[str] = []
            self.selected_chronos_sample_size: int = 5000
            self._last_corridor_filter: Optional[
                Tuple[Optional[str], Optional[int], Optional[str], str]
            ] = None
            self.graph_render_registry: Dict[str, Dict[str, Any]] = {}
            self.chart_image_cache: Dict[str, str] = {}
            self._prefetched_json_mtime: float = 0.0 # la ref temporelle en memoire (prefetched_graphs.json)
            self._corridor_graphs_json_mtime: float = 0.0
            self._registry_json_lock = threading.Lock()
            self._registry_json_timer: Optional[threading.Timer] = None
            self._nav_combos_cache_key: Optional[Tuple[Any, ...]] = None
            self._nav_combos_cache: Optional[Dict[str, Dict[int, List[str]]]] = None
            self._event_swimmers_cache: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {}
            self._selected_event_swimmers: List[str] = []
            self._event_swimmer_options_cache: Dict[
                Tuple[str, int, str, str], List[ft.dropdown.Option]
            ] = {}
            self._corridor_dd_options_event_key: Optional[Tuple[str, int, str, str]] = None
            self.corridor_swimmer_search: Optional[SwimmerSearch] = None
            self._chart_schedule_gen: int = 0
            self._corridor_swimmer_schedule_gen: int = 0
            self._pacing_swimmer_options_key: Optional[Tuple[str, ...]] = None
            self._heatmap_swimmer_names_cache_id: Optional[int] = None
            self._heatmap_swimmer_names_cache: Optional[List[str]] = None
            self._registry_swimmer_names_cache_key: Optional[Tuple[float, float, int]] = None
            self._scope_performances_cache: "OrderedDict[Tuple[Any, ...], pd.DataFrame]" = (
                OrderedDict()
            )
            self._scope_performances_prefetched_on_startup: bool = False
            self.graph_svc = ServiceGraphe()
            self._corridor_prefetch_manager = CorridorPrefetchManager(
                self,
                corridor_category=CORRIDOR_CATEGORY,
                corridor_graph_name=CORRIDOR_GRAPH_NAME,
                max_renders=CORRIDOR_PREFETCH_MAX_RENDERS,
            )

            # Widgets Flet
            self.category_dd: ft.Dropdown
            self.graph_dd: ft.Dropdown
            self.stroke_dd: ft.Dropdown
            self.distance_dd: ft.Dropdown
            self.pool_dd: ft.Dropdown
            self.corridor_gender_dd: ft.Dropdown
            self.heatmap_swimmer_dd: ft.Dropdown
            self.corridor_swimmer_dd: ft.Dropdown
            self.corridor_swimmer_confirm_btn: ft.IconButton
            self.corridor_swimmer_search_tf: ft.AutoComplete
            self.corridor_swimmer_search_container: ft.Column
            self.corridor_swimmer_search_label: ft.Text
            self.pacing_swimmer_dd_1: ft.Dropdown
            self.pacing_swimmer_dd_2: ft.Dropdown
            self.pacing_swimmer_dd_3: ft.Dropdown

            self.image = ft.Image(
                src="",
                expand=True, 
                fit=ft.BoxFit.CONTAIN,
                border_radius=ft.BorderRadius.all(4),
            )
            self.chart_title_text = ft.Text(
                "",
                size=16,
                weight=ft.FontWeight.BOLD,
                color="#e5e7eb",
                text_align=ft.TextAlign.CENTER,
            )
            self.row_count_text = ft.Text(
                "",
                size=12,
                color="#9ca3af",
                text_align=ft.TextAlign.CENTER,
            )
            self.status_text = ft.Text(
                "",
                size=12,
                color="#f97373",
                text_align=ft.TextAlign.CENTER,
            )
            self.loader = ft.ProgressRing(
                visible=False, width=32, height=32, color="#22c55e"
            )
            if ENABLE_PERSISTENT_GRAPH_CACHE:
                self._load_graph_registry_json()
            if not ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START:
                self._load_event_swimmers_cache_json()
            self._load_scope_performances_cache_json()

            graph_json_path = GRAPH_EXPORT_PATH.name
            event_swimmers_json_path = EVENT_SWIMMERS_EXPORT_PATH.name

            if ENABLE_PERSISTENT_GRAPH_CACHE:
                left_total = (
                    max(1, len(GRAPHES_NOTEBOOK))
                    if (
                        ENABLE_NOTEBOOK_PREFETCH_ON_START
                        and not self.df.empty
                    )
                    else 1
                )
                right_total = 1
                dual = DualPrefetchProgress(
                    self.page,
                    left_total,
                    right_total,
                    graph_json_path,
                    event_swimmers_json_path,
                    right_header="Nageurs événements — prefetched_event_swimmers.json",
                    right_progress_label="Event swimmers",
                )
                dual.mount()
                self._dual_prefetch_ui = dual
                self._defer_prefetch_json_write = True
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                        f_nb = pool.submit(self._run_notebook_prefetch_worker)
                        f_co = pool.submit(self._run_event_swimmers_cache_prefetch_worker)
                        concurrent.futures.wait((f_nb, f_co))
                        for fut in (f_nb, f_co):
                            fut.result()
                finally:
                    self._defer_prefetch_json_write = False
                    self._dual_prefetch_ui = None
                    self._write_graph_registry_json()
                    if ENABLE_CORRIDOR_PREFETCH_ON_START:
                        self._write_corridor_graphs_json()
            if (
                ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START
                and not self.df_nav.empty
                and not self._scope_performances_prefetched_on_startup
            ):
                self._prefetch_scope_performances_cache_on_startup()

            self.page.clean()
            self._build_ui()
            self._update_chart()
        except Exception as exc:
            traceback.print_exc()
            err_msg = f"Démarrage: {exc!s}"

            async def _show_err() -> None:
                self.page.snack_bar = ft.SnackBar(
                    content=ft.Text(err_msg, color="#fecaca"),
                    bgcolor="#450a0a",
                )
                self.page.snack_bar.open = True
                self.page.update()

            try:
                self.page.run_task(_show_err)
            except Exception:
                pass

    def _schedule_deferred_chart_update(self, delay_sec: float = CHART_UPDATE_AFTER_FILTER_DEBOUNCE_SEC) -> None:
        """Reporte le rendu du graphique pour ne pas bloquer la mise à jour des dropdowns."""
        self._chart_schedule_gen += 1
        token = self._chart_schedule_gen

        async def _runner() -> None:
            await asyncio.sleep(0)
            await asyncio.sleep(delay_sec)
            if token != self._chart_schedule_gen:
                return
            self._update_chart()

        self.page.run_task(_runner)

    def _estimate_event_swimmers_total_events(self) -> int:
        """Compte le nombre d'unités 'événement' (Stroke/Distance/Course) à générer."""
        df_nav = self.df_nav
        required_cols = {"Stroke", "Distance", "Course", "swimmer"}
        if df_nav.empty or not required_cols.issubset(df_nav.columns):
            return 1

        event_keys: set[tuple[str, int, str]] = set()
        for row in df_nav[["Stroke", "Distance", "Course", "swimmer"]].itertuples(index=False):
            stroke_raw, distance_raw, pool_raw, swimmers_raw = row
            if (
                stroke_raw is None
                or pool_raw is None
                or pd.isna(stroke_raw)
                or pd.isna(pool_raw)
            ):
                continue

            stroke = str(stroke_raw).strip()
            pool = str(pool_raw).strip()
            if not stroke or not pool:
                continue

            try:
                distance = int(float(distance_raw))
            except (TypeError, ValueError):
                continue

            if isinstance(swimmers_raw, list):
                swimmers = swimmers_raw
            elif isinstance(swimmers_raw, dict):
                swimmers = [swimmers_raw]
            else:
                swimmers = []

            if not swimmers:
                continue

            event_keys.add((stroke, distance, pool))

        return len(event_keys) if event_keys else 1

    def _write_event_swimmers_cache_json(self) -> None:
        """
        Génère un cache des nageurs par événement (Stroke/Distance/Bassin).
        Le fichier est regénéré au démarrage de l'application.
        """
        payload: Dict[str, Any] = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "total_events": 0,
            "events": {},
        }
        events: Dict[str, Dict[str, Dict[str, Dict[str, set[str]]]]] = {}
        df_nav = self.df_nav

        required_cols = {"Stroke", "Distance", "Course", "swimmer"}
        if not df_nav.empty and required_cols.issubset(df_nav.columns):
            for row in df_nav[["Stroke", "Distance", "Course", "swimmer"]].itertuples(
                index=False
            ):
                stroke_raw, distance_raw, pool_raw, swimmers_raw = row
                if (
                    stroke_raw is None
                    or pool_raw is None
                    or pd.isna(stroke_raw)
                    or pd.isna(pool_raw)
                ):
                    continue
                stroke = str(stroke_raw).strip()
                pool = str(pool_raw).strip()
                if not stroke or not pool:
                    continue

                try:
                    distance = int(float(distance_raw))
                except (TypeError, ValueError):
                    continue

                swimmers: List[Any]
                if isinstance(swimmers_raw, list):
                    swimmers = swimmers_raw
                elif isinstance(swimmers_raw, dict):
                    swimmers = [swimmers_raw]
                else:
                    swimmers = []

                if not swimmers:
                    continue

                event_swimmers = events.setdefault(stroke, {}).setdefault(
                    str(distance), {}
                ).setdefault(pool, {"all": set(), "F": set(), "M": set()})
                for swimmer in swimmers:
                    if not isinstance(swimmer, dict):
                        continue
                    nm, yob = _primary_swimmer_name_and_yob([swimmer])
                    gender = self._normalize_gender_value(swimmer.get("Gender"))
                    if nm and yob is not None:
                        label = f"{nm} ({yob})"
                        event_swimmers["all"].add(label)
                        if gender in ("F", "M"):
                            event_swimmers[gender].add(label)
                    elif isinstance(swimmer.get("Name"), str):
                        stripped = swimmer["Name"].strip()
                        if stripped:
                            event_swimmers["all"].add(stripped)
                            if gender in ("F", "M"):
                                event_swimmers[gender].add(stripped)

        payload_events: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {}
        total_events = 0
        for stroke in sorted(events.keys()):
            payload_events[stroke] = {}
            for distance in sorted(events[stroke].keys(), key=lambda d: int(d)):
                payload_events[stroke][distance] = {}
                for pool in sorted(events[stroke][distance].keys()):
                    by_gender = events[stroke][distance][pool]
                    payload_events[stroke][distance][pool] = {
                        "all": sorted(by_gender.get("all", set()), key=lambda label: _normalize_text(label)),
                        "F": sorted(by_gender.get("F", set()), key=lambda label: _normalize_text(label)),
                        "M": sorted(by_gender.get("M", set()), key=lambda label: _normalize_text(label)),
                    }
                    total_events += 1
                    # Avance la barre pour chaque événement (stroke/distance/pool) finalisé.
                    if self._dual_prefetch_ui is not None:
                        try:
                            d_i = int(distance)
                        except Exception:
                            d_i = distance  # fallback texte
                        self._advance_startup_event_swimmers(
                            f"{stroke}/{d_i}/{pool} terminé",
                            units=1,
                            show_graph_progress=True,
                        )

        payload["events"] = payload_events
        payload["total_events"] = total_events
        EVENT_SWIMMERS_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_SWIMMERS_EXPORT_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load_event_swimmers_cache_json(self) -> None:
        self._event_swimmers_cache = {}
        self._event_swimmer_options_cache = {}
        try:
            with EVENT_SWIMMERS_EXPORT_PATH.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return

        raw_events = payload.get("events")
        if not isinstance(raw_events, dict):
            return

        normalized: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {}
        for stroke, by_distance in raw_events.items():
            if not isinstance(stroke, str) or not isinstance(by_distance, dict):
                continue
            stroke_payload: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
            for distance, by_pool in by_distance.items():
                if not isinstance(distance, str) or not isinstance(by_pool, dict):
                    continue
                pool_payload: Dict[str, Dict[str, List[str]]] = {}
                for pool, swimmers_payload in by_pool.items():
                    if not isinstance(pool, str):
                        continue
                    if isinstance(swimmers_payload, list):
                        all_swimmers = [
                            s.strip()
                            for s in swimmers_payload
                            if isinstance(s, str) and s.strip()
                        ]
                        pool_payload[pool] = {"all": all_swimmers, "F": [], "M": []}
                        continue
                    if not isinstance(swimmers_payload, dict):
                        continue
                    all_swimmers = swimmers_payload.get("all", [])
                    women_swimmers = swimmers_payload.get("F", [])
                    men_swimmers = swimmers_payload.get("M", [])
                    pool_payload[pool] = {
                        "all": [
                            s.strip()
                            for s in all_swimmers
                            if isinstance(s, str) and s.strip()
                        ],
                        "F": [
                            s.strip()
                            for s in women_swimmers
                            if isinstance(s, str) and s.strip()
                        ],
                        "M": [
                            s.strip()
                            for s in men_swimmers
                            if isinstance(s, str) and s.strip()
                        ],
                    }
                stroke_payload[distance] = pool_payload
            normalized[stroke] = stroke_payload

        self._event_swimmers_cache = normalized

    def _event_combinations_from_swimmers_cache(
        self,
    ) -> Dict[str, Dict[int, List[str]]]:
        """
        Reconstruit la même structure que ``_event_combinations`` (Stroke -> Distance -> [Course])
        à partir du cache JSON ``prefetched_event_swimmers.json`` (mémoire : ``_event_swimmers_cache``).
        """
        out: Dict[str, Dict[int, set[str]]] = {}
        pool_rank = {"SCM": 0, "LCM": 1}
        for stroke, by_distance in self._event_swimmers_cache.items():
            if not isinstance(stroke, str) or not isinstance(by_distance, dict):
                continue
            stroke_s = stroke.strip()
            if not stroke_s:
                continue
            for d_str, by_pool in by_distance.items():
                if not isinstance(d_str, str) or not isinstance(by_pool, dict):
                    continue
                try:
                    d_i = int(d_str)
                except ValueError:
                    continue
                for pool in by_pool.keys():
                    if not isinstance(pool, str):
                        continue
                    p = pool.strip()
                    if not p:
                        continue
                    out.setdefault(stroke_s, {}).setdefault(d_i, set()).add(p)

        ordered: Dict[str, Dict[int, List[str]]] = {}
        for stroke in sorted(out.keys()):
            ordered[stroke] = {}
            for distance in sorted(out[stroke].keys()):
                pools = sorted(
                    out[stroke][distance],
                    key=lambda p: (pool_rank.get(p), p),
                )
                ordered[stroke][distance] = pools
        return ordered

    def _cached_event_swimmers_for_filters(
        self,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        gender: str = "all",
    ) -> List[str]:
        if not stroke or distance is None or not pool:
            return []
        gender_key = self._normalize_gender_value(gender)
        if gender_key not in ("all", "F", "M"):
            gender_key = "all"
        return (
            self._event_swimmers_cache.get(stroke, {})
            .get(str(int(distance)), {})
            .get(pool, {})
            .get(gender_key, [])
        )

    def _cached_event_swimmer_options_for_filters(
        self,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        gender: str = "all",
    ) -> List[ft.dropdown.Option]:
        if not stroke or distance is None or not pool:
            return []
        gender_key = self._normalize_gender_value(gender)
        key = (stroke, int(distance), pool, gender_key)
        cached_options = self._event_swimmer_options_cache.get(key)
        if cached_options is not None:
            return cached_options
        labels = self._cached_event_swimmers_for_filters(stroke, distance, pool, gender_key)
        options = [ft.dropdown.Option(label) for label in labels]
        self._event_swimmer_options_cache[key] = options
        return options

    def _refresh_selected_event_swimmers_from_cache(self) -> None:
        self._selected_event_swimmers = self._cached_event_swimmers_for_filters(
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            self.selected_corridor_gender
            if self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
            else "all",
        )

    @staticmethod
    def _normalize_gender_value(value: Any) -> str:
        if value is None:
            return "all"
        s = str(value).strip().upper()
        if s in ("F", "FEMME", "FEMALE", "W"):
            return "F"
        if s in ("M", "H", "HOMME", "MALE", "MAN"):
            return "M"
        if s in ("ALL", "TOUS", "TOUTES"):
            return "all"
        return "all"

    def _swimmer_names_from_corridor_registry(self) -> List[str]:
        """
        Extrait des nageurs cibles depuis les options des rendus couloir
        chargés depuis ``prefetched_corridor_graphs.json``.
        """
        self._refresh_graph_registry_from_disk_if_changed()
        key = (
            float(getattr(self, "_prefetched_json_mtime", 0.0)),
            float(getattr(self, "_corridor_graphs_json_mtime", 0.0)),
            len(self.graph_render_registry),
        )
        if (
            self._registry_swimmer_names_cache_key == key
            and self._heatmap_swimmer_names_cache is not None
        ):
            return self._heatmap_swimmer_names_cache

        names: set[str] = set()
        for item in self.graph_render_registry.values():
            if not isinstance(item, dict):
                continue
            if not PacingDesktopApp._is_corridor_registry_item(item):
                continue
            options = item.get("options")
            if not isinstance(options, dict):
                continue
            nm = options.get("corridor_swimmer_name")
            if isinstance(nm, str):
                nm = nm.strip()
                if nm:
                    names.add(nm)

        out = sorted(names, key=lambda name: _normalize_text(name))
        self._heatmap_swimmer_names_cache = out
        self._registry_swimmer_names_cache_key = key
        return out

    def _render_key_for_category_graph_options(
        self, category: str, graph_name: str, options: Dict[str, Any]
    ) -> Tuple[str, str]:
        chart_id = f"{_slugify(category)}__{_slugify(graph_name)}"
        render_key = (
            f"{chart_id}::"
            f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        )
        return chart_id, render_key

    @staticmethod
    def _corridor_prefetch_render_options_dict(
        stroke: str,
        distance: int,
        pool: str,
        swimmer_name: str,
        swimmer_yob: int,
        chronos_sample_size: int,
    ) -> Dict[str, Any]:
        return CorridorPrefetchManager.corridor_prefetch_render_options_dict(
            stroke,
            distance,
            pool,
            swimmer_name,
            swimmer_yob,
            chronos_sample_size,
        )

    def _build_render_key(
        self,
        category: str,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Tuple[str, Dict[str, Any], str]:
        options = self._current_render_options(
            stroke, distance, pool, graph_name=graph_name
        )
        chart_id, render_key = self._render_key_for_category_graph_options(
            category, graph_name, options
        )
        return chart_id, options, render_key

    def _current_render_options(
        self,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        *,
        graph_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Options sérialisées dans la clé de cache disque / mémoire.

        Pour le couloir, on n’inclut pas heatmap ni pacing : le préfetch utilise
        toujours ``heatmap_swimmer=None`` et ``pacing_swimmers=[]`` (voir
        ``_corridor_prefetch_render_options_dict``). Sinon la clé ne matche pas
        le JSON et Matplotlib est relancé à chaque fois.
        """
        heatmap = self.selected_heatmap_swimmer
        pacing = self.selected_pacing_swimmers[:3]
        if graph_name in CORRIDOR_SWIMMER_UI_GRAPHS:
            heatmap = None
            pacing = []
        corridor_swimmer_name = self.selected_corridor_swimmer_name
        corridor_swimmer_yob = self.selected_corridor_swimmer_yob
        if graph_name == CORRIDOR_GLOBAL_GRAPH_NAME:
            corridor_swimmer_name = None
            corridor_swimmer_yob = None
        return {
            "stroke": stroke,
            "distance": int(distance) if distance is not None else None,
            "pool": pool,
            "heatmap_swimmer": heatmap,
            "corridor_swimmer_name": corridor_swimmer_name,
            "corridor_swimmer_yob": corridor_swimmer_yob,
            "pacing_swimmers": pacing,
            "chronos_sample_size": int(self.selected_chronos_sample_size),
        }

    @staticmethod
    def _is_corridor_registry_item(item: Dict[str, Any]) -> bool:
        return item.get("category") == CORRIDOR_CATEGORY

    @staticmethod
    def _registry_item_to_render_key(item: Dict[str, Any]) -> Optional[str]:
        category = item.get("category")
        name = item.get("name")
        options = item.get("options")
        if not isinstance(category, str) or not isinstance(name, str) or not isinstance(options, dict):
            return None
        chart_id = f"{_slugify(category)}__{_slugify(name)}"
        return (
            f"{chart_id}::"
            f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        )

    def _ingest_registry_payload(
        self,
        payload: Any,
        loaded_registry: Dict[str, Dict[str, Any]],
        loaded_cache: Dict[str, str],
    ) -> None:
        if not isinstance(payload, dict):
            return
        raw_renders = payload.get("renders")
        if not isinstance(raw_renders, list):
            return
        for item in raw_renders:
            if not isinstance(item, dict):
                continue
            render_key = PacingDesktopApp._registry_item_to_render_key(item)
            if render_key is None:
                continue
            loaded_registry[render_key] = item
            image_base64 = item.get("image_base64")
            status = item.get("status")
            if status == "ok" and isinstance(image_base64, str) and image_base64:
                loaded_cache[render_key] = image_base64

    def _write_graph_registry_json(self) -> None:
        """Écrit uniquement les rendus hors couloir dans ``prefetched_graphs.json``."""
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        GRAPH_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._registry_json_lock:
            registry_snapshot = dict(self.graph_render_registry)
        renders = [
            item
            for item in registry_snapshot.values()
            if not PacingDesktopApp._is_corridor_registry_item(item)
        ]
        if not EXPORT_IMAGE_BASE64_TO_JSON:
            renders = [
                {k: v for k, v in item.items() if k != "image_base64"}
                for item in renders
            ]
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "total_renders": len(renders),
            "renders": sorted(
                renders,
                key=lambda item: (item["category"], item["name"], item["rendered_at"]),
            ),
        }
        with GRAPH_EXPORT_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._touch_prefetched_json_mtime()

    def _write_corridor_graphs_json(self) -> None:
        """Stockage disque couloir désactivé : cache uniquement en mémoire."""
        return

    def _touch_prefetched_json_mtime(self) -> None:
        try:
            if GRAPH_EXPORT_PATH.exists():
                self._prefetched_json_mtime = float(GRAPH_EXPORT_PATH.stat().st_mtime)
        except OSError:
            pass

    def _touch_corridor_graphs_json_mtime(self) -> None:
        try:
            if CORRIDOR_GRAPHS_EXPORT_PATH.exists():
                self._corridor_graphs_json_mtime = float(CORRIDOR_GRAPHS_EXPORT_PATH.stat().st_mtime)
        except OSError:
            pass

    def _refresh_graph_registry_from_disk_if_changed(self) -> None:
        """Recharge le cache disque si ``prefetched_graphs.json`` change."""
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        try:
            main_mtime = (
                float(GRAPH_EXPORT_PATH.stat().st_mtime) if GRAPH_EXPORT_PATH.exists() else 0.0
            )
            if main_mtime > self._prefetched_json_mtime:
                self._load_graph_registry_json()
        except OSError:
            pass

    def _load_graph_registry_json(self) -> None:
        """Charge le registre depuis ``prefetched_graphs.json``."""
        loaded_registry: Dict[str, Dict[str, Any]] = {}
        loaded_cache: Dict[str, str] = {}

        try:
            with GRAPH_EXPORT_PATH.open("r", encoding="utf-8") as f:
                self._ingest_registry_payload(json.load(f), loaded_registry, loaded_cache)
        except Exception:
            pass

        with self._registry_json_lock:
            self.graph_render_registry = loaded_registry
            self.chart_image_cache = loaded_cache
        self._touch_prefetched_json_mtime()

    def _notebook_prefetch_options(self, spec_key: str) -> Dict[str, Any]:
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
        Retour:
        (spec, render_key, options, status, chart_title, image_base64, error)
        """
        options = self._notebook_prefetch_options(spec.key)
        render_key = self._notebook_service_render_key(spec)
        graph_svc = ServiceGraphe()
        try:
            raw = graph_svc.build_figure_prefetch(spec, self.df, self.df_nav)
            if raw is None:
                return (spec, render_key, options, "no_figure", spec.name, None, None)
            fig = unwrap_matplotlib_figure(raw)
        except Exception as exc: 
            return (spec, render_key, options, "error", spec.name, None, str(exc))

        if fig is None:
            return (spec, render_key, options, "no_figure", spec.name, None, None)

        image_base64 = _figure_to_base64(fig)
        plt.close(fig)
        return (spec, render_key, options, "ok", spec.name, image_base64, None)

    def _prefetch_service_notebook_graphs_skip_existing(self) -> None:
        """Parcourt ``GRAPHES_NOTEBOOK`` : si le rendu est déjà dans le JSON, sinon génère et enregistre."""
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

    def _collect_corridor_prefetch_tasks(self) -> List[Tuple[str, int, str, str, int, int]]:
        return self._corridor_prefetch_manager.collect_tasks()

    def _compute_corridor_prefetch_render(
        self,
        task: Tuple[str, int, str, str, int, int],
    ) -> Optional[
        Tuple[str, str, Dict[str, Any], str, str, int, Optional[str], Optional[str]]
    ]:
        return self._corridor_prefetch_manager.compute_render(task)

    def _register_corridor_prefetch_render(
        self,
        *,
        render_key: str,
        chart_id: str,
        options: Dict[str, Any],
        chart_title: str,
        status: str,
        row_count: int,
        image_base64: Optional[str],
        error: Optional[str] = None,
        skip_json_write: bool = False,
    ) -> None:
        self._corridor_prefetch_manager.register_render(
            render_key=render_key,
            chart_id=chart_id,
            options=options,
            chart_title=chart_title,
            status=status,
            row_count=row_count,
            image_base64=image_base64,
            error=error,
            skip_json_write=skip_json_write,
        )

    def _prefetch_corridor_graphs_skip_existing(
        self, tasks: List[Tuple[str, int, str, str, int, int]]
    ) -> None:
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        self._corridor_prefetch_manager.prefetch_skip_existing(tasks)

    def _register_graph_render(
        self,
        *,
        category: str,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        chart_title: str,
        status: str,
        row_count: int,
        image_base64: Optional[str],
        error: Optional[str] = None,
    ) -> None:
        chart_id, options, render_key = self._build_render_key(
            category,
            graph_name,
            stroke,
            distance,
            pool,
        )
        with self._registry_json_lock:
            self.graph_render_registry[render_key] = {
                "id": chart_id,
                "name": graph_name,
                "category": category,
                "method": f"render_{_slugify(graph_name)}",
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
            item = self.graph_render_registry[render_key]
        if PacingDesktopApp._is_corridor_registry_item(item):
            self._write_corridor_graphs_json()
        else:
            self._write_graph_registry_json()

    def _apply_theme_palette(self) -> None:
        """Aligne page, panneaux et textes sur ``_ui_light_mode`` (le thème Material seul ne suffit pas)."""
        light = self._ui_light_mode
        self.page.theme_mode = ft.ThemeMode.LIGHT if light else ft.ThemeMode.DARK
        if light:
            self.page.bgcolor = "#e2e8f0"
            sidebar_bg = "#ffffff"
            main_bg = "#f8fafc"
            nav_title = "#0f172a"
            chart_title = "#0f172a"
            row_muted = "#475569"
            err = "#b91c1c"
        else:
            self.page.bgcolor = "#020617"
            sidebar_bg = "#020617"
            main_bg = "#020617"
            nav_title = "#f8fafc"
            chart_title = "#e5e7eb"
            row_muted = "#9ca3af"
            err = "#f97373"

        sc = self._sidebar_container
        if isinstance(sc, ft.Container):
            sc.bgcolor = sidebar_bg
        ma = self._main_area_container
        if isinstance(ma, ft.Container):
            ma.bgcolor = main_bg

        if self._nav_title_text is not None:
            self._nav_title_text.color = nav_title
        if self._theme_toggle_btn is not None:
            if light:
                self._theme_toggle_btn.icon = ft.icons.Icons.DARK_MODE
                self._theme_toggle_btn.icon_color = "#312e81"
            else:
                self._theme_toggle_btn.icon = ft.icons.Icons.LIGHT_MODE
                self._theme_toggle_btn.icon_color = "#facc15"

        self.chart_title_text.color = chart_title
        self.row_count_text.color = row_muted
        self.status_text.color = err

    def _build_ui(self) -> None:
        if self.df.empty:
            self._sidebar_container = None
            self._main_area_container = None
            self._theme_toggle_btn = None
            self._nav_title_text = None
            self.page.add(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Aucune donnée trouvée. Vérifie les JSON Extranat.",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color="#f97373",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                )
            )
            return

        # Sidebar widgets
        dropdown_width = 420
        dropdown_menu_width = 420

        self.category_dd = ft.Dropdown(
            label="Catégorie",
            options=[ft.dropdown.Option(k) for k in GRAPH_CATEGORIES.keys()],
            value=self.selected_category,
            on_select=self._on_category_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.graph_dd = ft.Dropdown(
            label="Graphique",
            options=[
                ft.dropdown.Option(g)
                for g in self._available_graphs_for_category(self.selected_category)
            ],
            value=self.selected_graph,
            on_select=self._on_graph_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.stroke_dd = ft.Dropdown(
            label="Stroke",
            options=[],
            on_select=self._on_filter_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.distance_dd = ft.Dropdown(
            label="Distance",
            options=[],
            on_select=self._on_filter_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.pool_dd = ft.Dropdown(
            label="Bassin",
            options=[],
            on_select=self._on_filter_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.corridor_gender_dd = ft.Dropdown(
            label="Sexe (couloir)",
            options=[
                ft.dropdown.Option(key="all", text="Tous"),
                ft.dropdown.Option(key="F", text="Femme"),
                ft.dropdown.Option(key="M", text="Homme"),
            ],
            value="all",
            on_select=self._on_filter_change,
            filled=True,
            menu_height=220,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.heatmap_swimmer_dd = ft.Dropdown(
            label="Nageur cible (heatmap)",
            options=[],
            on_select=self._on_heatmap_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.corridor_swimmer_dd = ft.Dropdown(
            label="Nageur cible (couloir de perf.)",
            options=[],
            on_select=self._on_corridor_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.corridor_swimmer_search = SwimmerSearch(self, width=dropdown_width)
        self.corridor_swimmer_search_label = self.corridor_swimmer_search.label
        self.corridor_swimmer_search_tf = self.corridor_swimmer_search.input
        self.corridor_swimmer_search_container = self.corridor_swimmer_search.container
        self.corridor_swimmer_confirm_btn = self.corridor_swimmer_search.confirm_btn
        self.pacing_swimmer_dd_1 = ft.Dropdown(
            label="Nageur cible 1 (pacing)",
            options=[],
            on_select=self._on_pacing_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.pacing_swimmer_dd_2 = ft.Dropdown(
            label="Nageur cible 2 (pacing)",
            options=[],
            on_select=self._on_pacing_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.pacing_swimmer_dd_3 = ft.Dropdown(
            label="Nageur cible 3 (pacing)",
            options=[],
            on_select=self._on_pacing_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )

        self._nav_title_text = ft.Text(
            "Navigation",
            size=20,
            weight=ft.FontWeight.BOLD,
        )
        self._theme_toggle_btn = ft.IconButton(
            icon=ft.icons.Icons.LIGHT_MODE,
            icon_color="#facc15",
            tooltip="Basculer light/dark mode",
            on_click=self._toggle_theme,
        )

        sidebar = ft.Container(
            bgcolor="#020617",
            padding=16,
            expand=3,
            clip_behavior=ft.ClipBehavior.NONE,
            content=ft.Column(
                controls=[
                    ft.Row(
                        [self._nav_title_text, self._theme_toggle_btn],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=10),
                    self.category_dd,
                    self.graph_dd,
                    ft.Divider(),
                    self.stroke_dd,
                    self.distance_dd,
                    self.pool_dd,
                    self.corridor_gender_dd,
                    self.pacing_swimmer_dd_1,
                    self.pacing_swimmer_dd_2,
                    self.pacing_swimmer_dd_3,
                    self.heatmap_swimmer_dd,
                    self.corridor_swimmer_search_container,
                    self.corridor_swimmer_dd,
                    ft.Divider(),
                    ft.Row(
                        [self.loader],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=10,
                expand=False,
            ),
        )

        main_area = ft.Container(
            expand=7,
            padding=16,
            bgcolor="#020617",
            content=ft.Column(
                [
                    ft.Container(
                        content=self.image,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                self.chart_title_text,
                                self.row_count_text,
                                self.status_text,
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        padding=ft.Padding(left=0, top=8, right=0, bottom=0),
                    ),
                ],
                expand=True,
                spacing=8,
            ),
        )

        self._sidebar_container = sidebar
        self._main_area_container = main_area

        layout = ft.Row(
            controls=[sidebar, main_area],
            expand=True,
        )
        self._apply_theme_palette()
        self.page.add(layout)
        self._refresh_filters_from_data()

    def _toggle_theme(self, _: ft.ControlEvent) -> None:
        self._ui_light_mode = not self._ui_light_mode
        self._apply_theme_palette()
        self.page.update()

    def _available_graphs_for_category(self, category: str) -> List[str]:
        graphs = list(GRAPH_CATEGORIES.get(category, []))
        return [g for g in graphs if g != CORRIDOR_GLOBAL_GRAPH_NAME]

    def _on_category_change(self, e: ft.ControlEvent) -> None:
        self.selected_category = e.control.value
        graphs = self._available_graphs_for_category(self.selected_category)
        if not graphs:
            return
        self.selected_graph = graphs[0]
        self.graph_dd.options = [ft.dropdown.Option(g) for g in graphs]
        self.graph_dd.value = self.selected_graph
        self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    def _on_graph_change(self, e: ft.ControlEvent) -> None:
        self.selected_graph = e.control.value
        self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    def _on_filter_change(self, e: ft.ControlEvent) -> None:
        self.selected_stroke = self.stroke_dd.value
        self.selected_distance = int(self.distance_dd.value) if self.distance_dd.value else None
        self.selected_pool = self.pool_dd.value
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

    async def _refresh_corridor_swimmers_async(self, token: int) -> None:
        await asyncio.sleep(0)
        if token != self._corridor_swimmer_schedule_gen:
            return
        self._refresh_filters_from_data()

    def _on_heatmap_swimmer_change(self, e: ft.ControlEvent) -> None:
        self.selected_heatmap_swimmer = e.control.value
        self._update_chart()

    def _on_pacing_swimmer_change(self, e: ft.ControlEvent) -> None:
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
        self.selected_pacing_swimmers = cleaned[:3]
        self._update_chart()

    def _on_corridor_swimmer_change(self, e: ft.ControlEvent) -> None:
        label = e.control.value
        name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
        self.selected_corridor_swimmer_name = name
        self.selected_corridor_swimmer_yob = yob
        if self.selected_graph == CORRIDOR_GLOBAL_GRAPH_NAME:
            self._refresh_filters_from_data()
            return
        self._update_chart()

    def _on_confirm_corridor_swimmer(self, _: ft.ControlEvent) -> None:
        label = self.corridor_swimmer_dd.value
        name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
        if not name:
            return
        self.selected_corridor_swimmer_name = name
        self.selected_corridor_swimmer_yob = yob
        # Depuis le mode "global", la confirmation ouvre le couloir du nageur choisi.
        self.selected_graph = CORRIDOR_GRAPH_NAME
        self.graph_dd.value = self.selected_graph
        self._refresh_filters_from_data()
        self._schedule_deferred_chart_update()

    def _on_corridor_swimmer_search_change(self, e: ft.ControlEvent) -> None:
        self.corridor_swimmer_search_query = (e.control.value or "").strip()
        self._refresh_filters_from_data()

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

    @staticmethod
    def _filter_corridor_swimmer_labels(
        labels: List[str],
        query: str,
    ) -> List[str]:
        """
        Filtre en 2 passes:
        1) match préfixe sur au moins un mot (premières lettres),
        2) si vide, fallback sur recherche "contains" dans le label complet.
        """
        search_norm = _normalize_text(query)
        if not search_norm:
            return labels

        prefix_matches: List[str] = []
        for label in labels:
            label_norm = _normalize_text(label)
            words = [w for w in label_norm.replace("(", " ").replace(")", " ").split() if w]
            if any(word.startswith(search_norm) for word in words):
                prefix_matches.append(label)

        if prefix_matches:
            return prefix_matches

        return [
            label
            for label in labels
            if search_norm in _normalize_text(label)
        ]

    # ----------------------------------------------------------------- Data-driven filters
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

    def _get_cached_scope_performances(
        self,
        *,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> pd.DataFrame:
        """
        Cache mémoire LRU des performances filtrées (df_scope) pour éviter
        de rematérialiser le même périmètre à chaque interaction UI.
        """
        key: Tuple[Any, ...] = (
            id(self.df_nav),
            graph_name,
            stroke,
            int(distance) if distance is not None else None,
            pool,
        )
        cached = self._scope_performances_cache.get(key)
        if cached is not None:
            self._scope_performances_cache.move_to_end(key)
            return cached

        df_scope = _materialize_df_scope(
            self.df_nav,
            graph_name,
            stroke,
            distance,
            pool,
        )
        self._scope_performances_cache[key] = df_scope
        self._scope_performances_cache.move_to_end(key)
        if len(self._scope_performances_cache) > SCOPE_PERFORMANCES_CACHE_MAX_ENTRIES:
            self._scope_performances_cache.popitem(last=False)
        return df_scope

    def _write_scope_performances_cache_json(self) -> None:
        """Persistance disque désactivée: cache scope conservé uniquement en mémoire."""
        return

    def _load_scope_performances_cache_json(self) -> None:
        self._scope_performances_cache = OrderedDict()
        return

    def _prefetch_scope_performances_cache_on_startup(self) -> None:
        """
        Préchauffe un sous-ensemble du cache mémoire des performances (df_scope)
        pour accélérer les premières interactions liées aux nageurs.
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

    def _refresh_filters_from_data(
        self,
        update_ui: bool = True,
        *,
        skip_corridor_swimmer_options: bool = False,
    ) -> None:
        """Met à jour les listes d'options des filtres en fonction du graphique choisi."""
        dirty = False
        df_nav = self.df_nav

        stroke, distance, pool = _resolve_scope_filters(
            df_nav,
            self.selected_graph,
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
        )
        self.selected_stroke = stroke
        self.selected_distance = distance
        self.selected_pool = pool
        self._refresh_selected_event_swimmers_from_cache()
        df_scope_mem: Optional[pd.DataFrame] = None

        def _df_scope() -> pd.DataFrame:
            nonlocal df_scope_mem
            if df_scope_mem is None:
                df_scope_mem = self._get_cached_scope_performances(
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                )
            return df_scope_mem

        if self.selected_graph in SCOPE_NO_FILTER_GRAPHS:
            combos: Dict[str, Dict[int, List[str]]] = {}
        else:
            nav_id = id(df_nav)
            use_swimmers_file_for_triplet = (
                self.selected_graph not in SCOPE_NO_STROKE_GRAPHS
                and self.selected_graph not in SCOPE_POOL_ONLY_GRAPHS
                and bool(self._event_swimmers_cache)
            )
            if use_swimmers_file_for_triplet:
                combos_key: Tuple[Any, ...] = (
                    "event_swimmers",
                    nav_id,
                    id(self._event_swimmers_cache),
                )
            else:
                combos_key = ("df_nav", nav_id)
            if self._nav_combos_cache_key != combos_key or self._nav_combos_cache is None:
                if use_swimmers_file_for_triplet:
                    self._nav_combos_cache = self._event_combinations_from_swimmers_cache()
                else:
                    self._nav_combos_cache = _event_combinations(df_nav)
                self._nav_combos_cache_key = combos_key
            combos = self._nav_combos_cache

        # Stroke options
        stroke_vals = list(combos.keys())
        if self.selected_stroke not in stroke_vals:
            self.selected_stroke = stroke_vals[0] if stroke_vals else None
        stroke_keys = tuple(str(s) for s in stroke_vals)
        if self._sync_dropdown(
            self.stroke_dd,
            new_option_keys=stroke_keys,
            build_options=lambda sv=stroke_vals: [ft.dropdown.Option(s) for s in sv],
            value=self.selected_stroke,
            visible=self.selected_graph
            not in (
                SCOPE_NO_FILTER_GRAPHS | SCOPE_POOL_ONLY_GRAPHS | SCOPE_NO_STROKE_GRAPHS
            ),
        ):
            dirty = True

        if self.selected_graph in SCOPE_NO_STROKE_GRAPHS:
            dist_vals = sorted(
                pd.to_numeric(df_nav["Distance"], errors="coerce")
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )
        else:
            dist_vals = (
                list(combos.get(self.selected_stroke, {}).keys())
                if self.selected_stroke
                else []
            )
        if self.selected_distance not in dist_vals:
            self.selected_distance = dist_vals[0] if dist_vals else None
        dist_keys = tuple(str(d) for d in dist_vals)
        dist_value = (
            str(self.selected_distance) if self.selected_distance is not None else None
        )
        if self._sync_dropdown(
            self.distance_dd,
            new_option_keys=dist_keys,
            build_options=lambda dv=dist_vals: [ft.dropdown.Option(str(d)) for d in dv],
            value=dist_value,
            visible=self.selected_graph
            not in (SCOPE_NO_FILTER_GRAPHS | SCOPE_POOL_ONLY_GRAPHS),
        ):
            dirty = True

        if self.selected_graph in SCOPE_POOL_ONLY_GRAPHS:
            pool_vals = sorted(df_nav["Course"].dropna().unique().tolist())
        elif self.selected_graph in SCOPE_NO_STROKE_GRAPHS:
            if self.selected_distance is not None:
                dmask = pd.to_numeric(df_nav["Distance"], errors="coerce") == self.selected_distance
                pool_vals = sorted(df_nav.loc[dmask, "Course"].dropna().unique().tolist())
            else:
                pool_vals = []
        else:
            pool_vals = (
                combos.get(self.selected_stroke, {}).get(self.selected_distance, [])
                if (self.selected_stroke and self.selected_distance is not None)
                else []
            )
        if self.selected_pool not in pool_vals:
            self.selected_pool = pool_vals[0] if pool_vals else None
        pool_keys = tuple(str(p) for p in pool_vals)
        if self._sync_dropdown(
            self.pool_dd,
            new_option_keys=pool_keys,
            build_options=lambda pv=pool_vals: [
                ft.dropdown.Option(key=str(p), text=str(p)) for p in pv
            ],
            value=self.selected_pool,
            visible=self.selected_graph not in SCOPE_NO_FILTER_GRAPHS,
        ):
            dirty = True

        # Options spécifiques pour heatmap
        if self.selected_graph == "Heatmap vitesse moyenne (distance x nage)":
            swimmer_options = self._swimmer_names_from_corridor_registry()
            if not swimmer_options:
                hid = id(df_nav)
                if (
                    self._heatmap_swimmer_names_cache_id != hid
                    or self._heatmap_swimmer_names_cache is None
                ):
                    self._heatmap_swimmer_names_cache = sorted(
                        {
                            name
                            for name in df_nav["swimmer"].apply(_primary_swimmer_name).tolist()
                            if name
                        },
                        key=lambda name: _normalize_text(name),
                    )
                    self._heatmap_swimmer_names_cache_id = hid
                swimmer_options = self._heatmap_swimmer_names_cache
            heat_keys = tuple(swimmer_options)
            if swimmer_options:
                if self.selected_heatmap_swimmer not in swimmer_options:
                    self.selected_heatmap_swimmer = swimmer_options[0]
            else:
                self.selected_heatmap_swimmer = None
            if self._sync_dropdown(
                self.heatmap_swimmer_dd,
                new_option_keys=heat_keys,
                build_options=lambda so=swimmer_options: [
                    ft.dropdown.Option(name) for name in so
                ],
                value=self.selected_heatmap_swimmer,
                visible=True,
            ):
                dirty = True
        else:
            if self._sync_dropdown(
                self.heatmap_swimmer_dd,
                new_option_keys=tuple(),
                build_options=lambda: [],
                value=None,
                visible=False,
            ):
                dirty = True

        # Options spécifiques pour couloir de performance
        if self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS:
            if self._sync_dropdown(
                self.corridor_gender_dd,
                new_option_keys=("all", "F", "M"),
                build_options=lambda: [
                    ft.dropdown.Option(key="all", text="Tous"),
                    ft.dropdown.Option(key="F", text="Femme"),
                    ft.dropdown.Option(key="M", text="Homme"),
                ],
                value=self.selected_corridor_gender,
                visible=True,
            ):
                dirty = True
            current_corridor_filter = (
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
                self.selected_corridor_gender,
            )
            if self._last_corridor_filter != current_corridor_filter:
                self.corridor_swimmer_dd.value = None
                self.selected_corridor_swimmer_name = None
                self.selected_corridor_swimmer_yob = None
                if self.corridor_swimmer_search is not None:
                    self.corridor_swimmer_search.clear_suggestions()
                if self.corridor_swimmer_search_query:
                    if self.corridor_swimmer_search is not None:
                        self.corridor_swimmer_search.reset(clear_query=True)
                self._last_corridor_filter = current_corridor_filter
                dirty = True
            if self.corridor_swimmer_search_container.visible is not True:
                self.corridor_swimmer_search_container.visible = True
                dirty = True
            if self.corridor_swimmer_search is not None:
                if self.corridor_swimmer_search.sync_value_to_query():
                    dirty = True
            if skip_corridor_swimmer_options:
                if self.corridor_swimmer_dd.visible is not True:
                    self.corridor_swimmer_dd.visible = True
                    dirty = True
                waiting_label = "Nageur cible (couloir) — chargement..."
                if self.corridor_swimmer_dd.label != waiting_label:
                    self.corridor_swimmer_dd.label = waiting_label
                    dirty = True
                if self.corridor_swimmer_dd.menu_height != self._menu_height_for_count(1):
                    self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(1)
                    dirty = True
                if self.corridor_swimmer_search is not None:
                    if self.corridor_swimmer_search.clear_suggestions():
                        dirty = True
            elif (
                self.selected_stroke
                and self.selected_distance is not None
                and self.selected_pool
            ):
                labels_all = self._selected_event_swimmers
                labels = labels_all
                search_norm = _normalize_text(self.corridor_swimmer_search_query)
                labels = self._filter_corridor_swimmer_labels(
                    labels,
                    self.corridor_swimmer_search_query,
                )
                autocomplete_event_key = (
                    self.selected_stroke,
                    int(self.selected_distance),
                    self.selected_pool,
                    self.selected_corridor_gender,
                )
                if self.corridor_swimmer_search is not None:
                    if self.corridor_swimmer_search.maybe_sync_suggestions(
                        labels_all, autocomplete_event_key
                    ):
                        dirty = True
                event_key = (
                    self.selected_stroke,
                    int(self.selected_distance),
                    self.selected_pool,
                    self.selected_corridor_gender,
                    search_norm,
                )
                if event_key != self._corridor_dd_options_event_key:
                    self._corridor_dd_options_event_key = event_key
                    self.corridor_swimmer_dd.options = [
                        ft.dropdown.Option(label) for label in labels
                    ]
                    dirty = True
                new_label = f"Nageur cible (couloir) — {len(labels)} disponibles"
                if self.corridor_swimmer_dd.label != new_label:
                    self.corridor_swimmer_dd.label = new_label
                    dirty = True
                mh = self._menu_height_for_count(len(labels) if labels else 1)
                if self.corridor_swimmer_dd.menu_height != mh:
                    self.corridor_swimmer_dd.menu_height = mh
                    dirty = True
                if self.corridor_swimmer_dd.visible is not True:
                    self.corridor_swimmer_dd.visible = True
                    dirty = True
                if labels:
                    pick = self.corridor_swimmer_dd.value
                    query_pick = (self.corridor_swimmer_search_query or "").strip()
                    # Si l'utilisateur valide via l'autocomplete (input),
                    # on synchronise automatiquement la sélection dropdown.
                    if query_pick and query_pick in labels:
                        pick = query_pick
                    elif query_pick and len(labels) == 1:
                        pick = labels[0]
                    if pick not in labels:
                        pick = None
                    if self.corridor_swimmer_dd.value != pick:
                        self.corridor_swimmer_dd.value = pick
                        dirty = True
                    if pick:
                        name, yob = self._parse_corridor_swimmer_label(pick)
                        self.selected_corridor_swimmer_name = name
                        self.selected_corridor_swimmer_yob = yob
                    else:
                        self.selected_corridor_swimmer_name = None
                        self.selected_corridor_swimmer_yob = None
                else:
                    if self.corridor_swimmer_dd.value is not None:
                        self.corridor_swimmer_dd.value = None
                        dirty = True
                    zero_label = "Nageur cible (couloir) — 0 disponible"
                    if self.corridor_swimmer_dd.label != zero_label:
                        self.corridor_swimmer_dd.label = zero_label
                        dirty = True
                    self.selected_corridor_swimmer_name = None
                    self.selected_corridor_swimmer_yob = None
            else:
                self._corridor_dd_options_event_key = None
                if self.corridor_swimmer_search is not None:
                    if self.corridor_swimmer_search.reset(clear_query=True):
                        dirty = True
                if self._dropdown_option_keys(self.corridor_swimmer_dd) != tuple():
                    self.corridor_swimmer_dd.options = []
                    dirty = True
                if self.corridor_swimmer_dd.value is not None:
                    self.corridor_swimmer_dd.value = None
                    dirty = True
                zl = "Nageur cible (couloir) — 0 disponible"
                if self.corridor_swimmer_dd.label != zl:
                    self.corridor_swimmer_dd.label = zl
                    dirty = True
                mh0 = self._menu_height_for_count(1)
                if self.corridor_swimmer_dd.menu_height != mh0:
                    self.corridor_swimmer_dd.menu_height = mh0
                    dirty = True
                if self.corridor_swimmer_dd.visible is not True:
                    self.corridor_swimmer_dd.visible = True
                    dirty = True
                if self.corridor_swimmer_search_container.visible is not True:
                    self.corridor_swimmer_search_container.visible = True
                    dirty = True
                self.selected_corridor_swimmer_name = None
                self.selected_corridor_swimmer_yob = None
            confirm_visible = (
                self.selected_graph in (CORRIDOR_GLOBAL_GRAPH_NAME, CORRIDOR_GRAPH_NAME)
                and bool(self.corridor_swimmer_dd.value)
            )
            if self.corridor_swimmer_confirm_btn.visible is not confirm_visible:
                self.corridor_swimmer_confirm_btn.visible = confirm_visible
                dirty = True
        else:
            if self._sync_dropdown(
                self.corridor_gender_dd,
                new_option_keys=("all", "F", "M"),
                build_options=lambda: [
                    ft.dropdown.Option(key="all", text="Tous"),
                    ft.dropdown.Option(key="F", text="Femme"),
                    ft.dropdown.Option(key="M", text="Homme"),
                ],
                value="all",
                visible=False,
            ):
                dirty = True
            self.selected_corridor_gender = "all"
            self._corridor_dd_options_event_key = None
            if self.corridor_swimmer_search is not None:
                if self.corridor_swimmer_search.reset(clear_query=True):
                    dirty = True
            if self._sync_dropdown(
                self.corridor_swimmer_dd,
                new_option_keys=tuple(),
                build_options=lambda: [],
                value=None,
                visible=False,
            ):
                dirty = True
            if self.corridor_swimmer_dd.label != "Nageur cible (couloir de perf.)":
                self.corridor_swimmer_dd.label = "Nageur cible (couloir de perf.)"
                dirty = True
            if self.corridor_swimmer_search_container.visible is not False:
                self.corridor_swimmer_search_container.visible = False
                dirty = True
            if self.corridor_swimmer_confirm_btn.visible is not False:
                self.corridor_swimmer_confirm_btn.visible = False
                dirty = True
            self.selected_corridor_swimmer_name = None
            self.selected_corridor_swimmer_yob = None

        # Option spécifique pacing comparatif (nageur cible)
        if self.selected_graph == "Split speed - F vs M + nageurs cibles":
            pacing_scope_key = (
                id(df_nav),
                stroke,
                distance,
                pool,
            )
            if pacing_scope_key != getattr(self, "_pacing_scope_key", None):
                self._pacing_scope_key = pacing_scope_key
                self._pacing_swimmer_options_key = None
            if self._pacing_swimmer_options_key is None:
                swimmer_options = self._swimmer_names_from_corridor_registry()
                if not swimmer_options:
                    swimmer_options = sorted(
                        {
                            n
                            for n in _df_scope()["swimmer"].apply(_primary_swimmer_name).tolist()
                            if n
                        },
                        key=lambda x: _normalize_text(x),
                    )
                self._pacing_swimmer_options_key = ("",) + tuple(swimmer_options)
            else:
                swimmer_options = list(self._pacing_swimmer_options_key[1:])
            pacing_keys = self._pacing_swimmer_options_key or ("",)
            options = [ft.dropdown.Option(key="", text="(aucun)")] + [
                ft.dropdown.Option(name) for name in swimmer_options
            ]
            pacing_mh = self._menu_height_for_count(len(options))
            for dd in (
                self.pacing_swimmer_dd_1,
                self.pacing_swimmer_dd_2,
                self.pacing_swimmer_dd_3,
            ):
                if self._dropdown_option_keys(dd) != pacing_keys:
                    dd.options = list(options)
                    dirty = True
                if dd.menu_height != pacing_mh:
                    dd.menu_height = pacing_mh
                    dirty = True
                if dd.visible is not True:
                    dd.visible = True
                    dirty = True

            default_vals = swimmer_options[:3]
            while len(default_vals) < 3:
                default_vals.append("")

            current = self.selected_pacing_swimmers[:]
            while len(current) < 3:
                current.append("")
            for i in range(3):
                if current[i] and current[i] not in swimmer_options:
                    current[i] = default_vals[i]
            if not any(current) and swimmer_options:
                current = default_vals

            for dd, val in (
                (self.pacing_swimmer_dd_1, current[0]),
                (self.pacing_swimmer_dd_2, current[1]),
                (self.pacing_swimmer_dd_3, current[2]),
            ):
                if dd.value != val:
                    dd.value = val
                    dirty = True

            cleaned: List[str] = []
            for s in current:
                if s and s not in cleaned:
                    cleaned.append(s)
            self.selected_pacing_swimmers = cleaned[:3]
        else:
            self._pacing_scope_key = None
            self._pacing_swimmer_options_key = None
            for dd in (
                self.pacing_swimmer_dd_1,
                self.pacing_swimmer_dd_2,
                self.pacing_swimmer_dd_3,
            ):
                if self._sync_dropdown(
                    dd,
                    new_option_keys=tuple(),
                    build_options=lambda: [],
                    value=None,
                    visible=False,
                ):
                    dirty = True
            self.selected_pacing_swimmers = []

        # Chronos dans le temps: borne la taille d'échantillon aux données disponibles
        if self.selected_graph == "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000":
            if self.df.empty:
                max_count = 0
            else:
                swim_dt = pd.to_datetime(self.df["SwimDate"], errors="coerce")
                sts = pd.to_numeric(self.df["SwimTimeSeconds"], errors="coerce")
                mask = swim_dt.notna() & sts.notna() & (swim_dt.dt.year >= 2000)
                max_count = int(mask.sum())
            if max_count < 0:
                max_count = 0
            if self.selected_chronos_sample_size > max_count:
                self.selected_chronos_sample_size = max_count
                dirty = True
            if self.selected_chronos_sample_size < 0:
                self.selected_chronos_sample_size = 0
                dirty = True

        # Catégorie / Graphique
        cat_mh = self._menu_height_for_count(len(self.category_dd.options))
        if self.category_dd.menu_height != cat_mh:
            self.category_dd.menu_height = cat_mh
            dirty = True
        graph_mh = self._menu_height_for_count(len(self.graph_dd.options))
        if self.graph_dd.menu_height != graph_mh:
            self.graph_dd.menu_height = graph_mh
            dirty = True

        # Toujours pousser l’UI après un changement de filtres : Flet peut laisser les
        # dropdowns dépendants visuellement bloqués si on omet page.update() lorsque
        # dirty est resté False (options « identiques » sur la forme, etc.).
        if update_ui:
            self.page.update()

    def _update_chart(self, update_ui: bool = True) -> None:
        try:
            stroke, distance, pool = _resolve_scope_filters(
                self.df_nav,
                self.selected_graph,
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
            )
            _, _, render_key = self._build_render_key(
                self.selected_category,
                self.selected_graph,
                stroke,
                distance,
                pool,
            )
            # Fast path: tenter d'abord le cache mémoire (très fréquent en usage normal).
            with self._registry_json_lock:
                cached = self.graph_render_registry.get(render_key)
                cached_image = self.chart_image_cache.get(render_key)
                if cached_image is None and isinstance(cached, dict):
                    img = cached.get("image_base64")
                    if isinstance(img, str) and len(img) > 0:
                        cached_image = img
                        self.chart_image_cache[render_key] = img
            if (
                cached is not None
                and cached.get("status") == "ok"
                and cached_image is not None
            ):
                if update_ui:
                    self.loader.visible = False
                    self.status_text.value = ""
                    self.image.visible = True
                    self.image.src = cached_image
                    self.chart_title_text.value = str(cached.get("chart_title", self.selected_graph))
                    row_count = int(cached.get("row_count", 0))
                    self.row_count_text.value = (
                        f"Nombre de performances disponibles : {row_count:,}".replace(",", " ")
                    )
                    self.page.update()
                return

            # Fallback disque uniquement en cas de miss mémoire.
            self._refresh_graph_registry_from_disk_if_changed()
            with self._registry_json_lock:
                cached = self.graph_render_registry.get(render_key)
                cached_image = self.chart_image_cache.get(render_key)
                if cached_image is None and isinstance(cached, dict):
                    img = cached.get("image_base64")
                    if isinstance(img, str) and len(img) > 0:
                        cached_image = img
                        self.chart_image_cache[render_key] = img
            if (
                cached is not None
                and cached.get("status") == "ok"
                and cached_image is not None
            ):
                if update_ui:
                    self.loader.visible = False
                    self.status_text.value = ""
                    self.image.visible = True
                    self.image.src = cached_image
                    self.chart_title_text.value = str(cached.get("chart_title", self.selected_graph))
                    row_count = int(cached.get("row_count", 0))
                    self.row_count_text.value = (
                        f"Nombre de performances disponibles : {row_count:,}".replace(",", " ")
                    )
                    self.page.update()
                return

            if update_ui:
                self.loader.visible = True
                self.status_text.value = ""
                self.page.update()

            df_scope = self._get_cached_scope_performances(
                graph_name=self.selected_graph,
                stroke=stroke,
                distance=distance,
                pool=pool,
            )

            if df_scope.empty:
                if update_ui:
                    self.image.visible = False
                    self.chart_title_text.value = self.selected_graph
                    self.row_count_text.value = "Aucune donnée pour les filtres sélectionnés."
                self._register_graph_render(
                    category=self.selected_category,
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                    chart_title=self.selected_graph,
                    status="empty_scope",
                    row_count=0,
                    image_base64=None,
                )
                return

            df_filtered = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
            fig, chart_title = self.graph_svc.desktop_build_figure(
                self.selected_graph,
                df=self.df,
                df_scope=df_scope,
                df_filtered=df_filtered,
                stroke=stroke,
                distance=distance,
                pool=pool,
                selected_distance=self.selected_distance,
                selected_chronos_sample_size=self.selected_chronos_sample_size,
                selected_pacing_swimmers=self.selected_pacing_swimmers,
                selected_heatmap_swimmer=self.selected_heatmap_swimmer,
                selected_corridor_swimmer_name=self.selected_corridor_swimmer_name,
                selected_corridor_swimmer_yob=self.selected_corridor_swimmer_yob,
            )

            if fig is None:
                if update_ui:
                    self.image.visible = False
                    self.chart_title_text.value = chart_title
                    self.row_count_text.value = (
                        "Graphique non encore implémenté dans la version PyFlet "
                        "ou aucune donnée exploitable pour ces filtres."
                    )
                self._register_graph_render(
                    category=self.selected_category,
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                    chart_title=chart_title,
                    status="no_figure",
                    row_count=len(df_scope),
                    image_base64=None,
                )
            else:
                image_base64 = _figure_to_base64(fig)
                if update_ui:
                    self.image.visible = True
                    self.image.src = image_base64
                    self.chart_title_text.value = chart_title
                    self.row_count_text.value = (
                        f"Nombre de performances disponibles : {len(df_scope):,}".replace(
                            ",", " "
                        )
                    )
                self._register_graph_render(
                    category=self.selected_category,
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                    chart_title=chart_title,
                    status="ok",
                    row_count=len(df_scope),
                    image_base64=image_base64,
                )
                plt.close(fig)

        except Exception as exc:  # type: ignore[bare-except]
            if update_ui:
                self.image.visible = False
                self.chart_title_text.value = self.selected_graph
                self.row_count_text.value = ""
                self.status_text.value = f"Erreur lors de la génération du graphique: {exc}"
            self._register_graph_render(
                category=self.selected_category,
                graph_name=self.selected_graph,
                stroke=self.selected_stroke,
                distance=self.selected_distance,
                pool=self.selected_pool,
                chart_title=self.selected_graph,
                status="error",
                row_count=0,
                image_base64=None,
                error=str(exc),
            )
        finally:
            if update_ui:
                self.loader.visible = False
                self.page.update()


def main(page: ft.Page) -> None:
    PacingDesktopApp(page)


if __name__ == "__main__":
    ft.run(main)

