import concurrent.futures
import datetime as dt
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import flet as ft
import matplotlib.pyplot as plt
import pandas as pd

from project_path import PROJECT_DIR, ensure_project_imports

ensure_project_imports()

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
EXPORT_IMAGE_BASE64_TO_JSON = True
ENABLE_PERSISTENT_GRAPH_CACHE = True
if ENABLE_PERSISTENT_GRAPH_CACHE:
    EXPORT_IMAGE_BASE64_TO_JSON = True
ENABLE_NOTEBOOK_PREFETCH_ON_START = True
GRAPH_REGISTRY_DEBOUNCE_S = 0.45
STARTUP_PREFETCH_MAX_WORKERS = 4


class LoadingBar:
    def __init__(self, page: ft.Page, total_units: int) -> None:
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
        self.header_text = ft.Text("CHARGEMENT", size=30, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.subheader_text = ft.Text("Demarrage de l'application", size=11, color="#9ca3af")
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

    def advance(
        self,
        detail: str,
        units: int = 1,
        *,
        show_graph_progress: bool = False,
    ) -> None:
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


class PacingDesktopApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.page.title = "Pacing – Desktop"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#020617"
        self.page.padding = 0

        self._startup_graph_target = len(GRAPHES_NOTEBOOK) if ENABLE_NOTEBOOK_PREFETCH_ON_START else 0
        self._startup_graph_done = 0
        self.loading_bar: Optional[LoadingBar] = LoadingBar(self.page, total_units=self._startup_graph_target)
        self.loading_bar.mount()
        self.page.run_thread(self._bootstrap_startup)

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
            self.selected_heatmap_swimmer: Optional[str] = None
            self.selected_corridor_swimmer_name: Optional[str] = None
            self.selected_corridor_swimmer_yob: Optional[int] = None
            self.selected_pacing_swimmers: List[str] = []
            self.selected_chronos_sample_size: int = 5000
            self._last_corridor_filter: Optional[
                Tuple[Optional[str], Optional[int], Optional[str]]
            ] = None
            self.graph_render_registry: Dict[str, Dict[str, Any]] = {}
            self.chart_image_cache: Dict[str, str] = {}
            self._prefetched_json_mtime: float = 0.0
            self._registry_json_lock = threading.Lock()
            self._registry_json_timer: Optional[threading.Timer] = None
            self._nav_combos_cache_id: Optional[int] = None
            self._nav_combos_cache: Optional[Dict[str, Dict[int, List[str]]]] = None
            self._heatmap_swimmer_names_cache_id: Optional[int] = None
            self._heatmap_swimmer_names_cache: Optional[List[str]] = None
            self.graph_svc = ServiceGraphe()

            # Widgets Flet
            self.category_dd: ft.Dropdown
            self.graph_dd: ft.Dropdown
            self.stroke_dd: ft.Dropdown
            self.distance_dd: ft.Dropdown
            self.pool_dd: ft.Dropdown
            self.heatmap_swimmer_dd: ft.Dropdown
            self.corridor_swimmer_dd: ft.Dropdown
            self.pacing_swimmer_dd_1: ft.Dropdown
            self.pacing_swimmer_dd_2: ft.Dropdown
            self.pacing_swimmer_dd_3: ft.Dropdown
            self.chronos_sample_text: ft.Text
            self.chronos_sample_slider: ft.Slider

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

            if ENABLE_NOTEBOOK_PREFETCH_ON_START:
                self._prefetch_service_notebook_graphs_skip_existing()

            gap = self._startup_graph_target - self._startup_graph_done
            if gap > 0:
                if self.loading_bar is not None:
                    self.loading_bar.advance(
                        detail="Synchronisation menu / prefetch",
                        units=gap,
                        show_graph_progress=True,
                    )
                self._startup_graph_done = self._startup_graph_target

            self.page.clean()
            self._build_ui()
            self._update_chart()
            if self.loading_bar is not None:
                self.loading_bar.advance(detail="Premier rendu termine", units=0)
        except Exception as exc:
            page = self.page

            page.run_task()

    def _build_render_key(
        self,
        category: str,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Tuple[str, Dict[str, Any], str]:
        options = self._current_render_options(stroke, distance, pool)
        chart_id = f"{_slugify(category)}__{_slugify(graph_name)}"
        render_key = (
            f"{chart_id}::"
            f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        )
        return chart_id, options, render_key

    def _current_render_options(
        self,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "stroke": stroke,
            "distance": int(distance) if distance is not None else None,
            "pool": pool,
            "heatmap_swimmer": self.selected_heatmap_swimmer,
            "corridor_swimmer_name": self.selected_corridor_swimmer_name,
            "corridor_swimmer_yob": self.selected_corridor_swimmer_yob,
            "pacing_swimmers": self.selected_pacing_swimmers[:3],
            "chronos_sample_size": int(self.selected_chronos_sample_size),
        }

    def _persist_graph_registry_json_worker(self) -> None:
        with self._registry_json_lock:
            self._registry_json_timer = None
        try:
            self._write_graph_registry_json()
        except Exception:
            pass

    def _flush_graph_registry_json_now(self) -> None:
        """Annule le timer différé et écrit le JSON immédiatement (prefetch, etc.)."""
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        with self._registry_json_lock:
            if self._registry_json_timer is not None:
                self._registry_json_timer.cancel()
                self._registry_json_timer = None
        self._write_graph_registry_json()

    def _write_graph_registry_json(self) -> None:
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        GRAPH_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        registry_snapshot = dict(self.graph_render_registry)
        renders = list(registry_snapshot.values())
        if not EXPORT_IMAGE_BASE64_TO_JSON:
            renders = [
                {k: v for k, v in item.items() if k != "image_base64"}
                for item in renders
            ]
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "total_renders": len(registry_snapshot),
            "renders": sorted(
                renders,
                key=lambda item: (item["category"], item["name"], item["rendered_at"]),
            ),
        }
        with GRAPH_EXPORT_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._touch_prefetched_json_mtime()

    def _touch_prefetched_json_mtime(self) -> None:
        try:
            if GRAPH_EXPORT_PATH.exists():
                self._prefetched_json_mtime = float(GRAPH_EXPORT_PATH.stat().st_mtime) # lire la date/heure de derniere modification du fichier
        except OSError:
            pass

    def _refresh_graph_registry_from_disk_if_changed(self) -> None:
        """Recharge ``prefetched_graphs.json`` si le fichier a été modifié depuis le dernier chargement."""
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        try:
            if not GRAPH_EXPORT_PATH.exists():
                return
            mtime = float(GRAPH_EXPORT_PATH.stat().st_mtime)
            if mtime > self._prefetched_json_mtime:
                self._load_graph_registry_json()
        except OSError:
            pass

    def _load_graph_registry_json(self) -> None:
        try:
            with GRAPH_EXPORT_PATH.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            self._touch_prefetched_json_mtime()
            return

        raw_renders = payload.get("renders")
        if not isinstance(raw_renders, list):
            self._touch_prefetched_json_mtime()
            return

        loaded_registry: Dict[str, Dict[str, Any]] = {}
        loaded_cache: Dict[str, str] = {}
        for item in raw_renders:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            name = item.get("name")
            options = item.get("options")
            if not isinstance(category, str) or not isinstance(name, str) or not isinstance(options, dict):
                continue

            chart_id = f"{_slugify(category)}__{_slugify(name)}"
            render_key = (
                f"{chart_id}::"
                f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
            )
            loaded_registry[render_key] = item
            image_base64 = item.get("image_base64")
            status = item.get("status")
            if status == "ok" and isinstance(image_base64, str) and image_base64:
                loaded_cache[render_key] = image_base64

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
            self._flush_graph_registry_json_now()

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
        # Instance locale pour éviter le partage d'état mutable entre threads.
        graph_svc = ServiceGraphe()
        try:
            raw = graph_svc.build_figure_prefetch(spec, self.df, self.df_nav)
            if raw is None:
                # Ne pas ignorer le spec: on l'enregistre en "no_figure" pour garder
                # un inventaire complet de GRAPHES_NOTEBOOK dans le JSON.
                return (spec, render_key, options, "no_figure", spec.name, None, None)
            fig = unwrap_matplotlib_figure(raw)
        except Exception as exc:  # type: ignore[bare-except]
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
            cached = self.graph_render_registry.get(render_key)
            img = cached.get("image_base64") if isinstance(cached, dict) else None
            if (
                cached
                and cached.get("status") == "ok"
                and isinstance(img, str)
                and len(img) > 0
            ):
                self.chart_image_cache[render_key] = img
                self._startup_graph_done += 1
                if self.loading_bar is not None:
                    self.loading_bar.advance(
                        detail=spec.name, show_graph_progress=True
                    )
                continue
            pending_specs.append(spec)

        if pending_specs:
            worker_count = max(1, min(STARTUP_PREFETCH_MAX_WORKERS, len(pending_specs)))
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
                    self._startup_graph_done += 1
                    if self.loading_bar is not None:
                        self.loading_bar.advance(
                            detail=spec.name, show_graph_progress=True
                        )

        self._flush_graph_registry_json_now()

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
        self._flush_graph_registry_json_now()

    def _build_ui(self) -> None:
        if self.df.empty:
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
            options=[ft.dropdown.Option(g) for g in GRAPH_CATEGORIES[self.selected_category]],
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
        self.chronos_sample_text = ft.Text(
            "",
            size=12,
            color="#cbd5e1",
            visible=False,
        )
        self.chronos_sample_slider = ft.Slider(
            min=0,
            max=5000,
            value=float(self.selected_chronos_sample_size),
            round=0,
            on_change=self._on_chronos_sample_change,
            label="{value}",
            visible=False,
            width=dropdown_width,
        )

        dark_toggle = ft.IconButton(
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
                        [ft.Text("Navigation", size=20, weight=ft.FontWeight.BOLD), dark_toggle],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=10),
                    self.category_dd,
                    self.graph_dd,
                    ft.Divider(),
                    self.stroke_dd,
                    self.distance_dd,
                    self.pool_dd,
                    self.pacing_swimmer_dd_1,
                    self.pacing_swimmer_dd_2,
                    self.pacing_swimmer_dd_3,
                    self.heatmap_swimmer_dd,
                    self.corridor_swimmer_dd,
                    self.chronos_sample_text,
                    self.chronos_sample_slider,
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

        layout = ft.Row(
            controls=[sidebar, main_area],
            expand=True,
        )
        self.page.add(layout)
        self._refresh_filters_from_data()

    def _toggle_theme(self, _: ft.ControlEvent) -> None:
        self.page.theme_mode = (
            ft.ThemeMode.LIGHT if self.page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        )
        self.page.update()

    def _on_category_change(self, e: ft.ControlEvent) -> None:
        self.selected_category = e.control.value
        graphs = GRAPH_CATEGORIES[self.selected_category]
        self.selected_graph = graphs[0]
        self.graph_dd.options = [ft.dropdown.Option(g) for g in graphs]
        self.graph_dd.value = self.selected_graph
        self._refresh_filters_from_data()
        self._update_chart()

    def _on_graph_change(self, e: ft.ControlEvent) -> None:
        self.selected_graph = e.control.value
        self._refresh_filters_from_data()
        self._update_chart()

    def _on_filter_change(self, _: ft.ControlEvent) -> None:
        self.selected_stroke = self.stroke_dd.value
        self.selected_distance = int(self.distance_dd.value) if self.distance_dd.value else None
        self.selected_pool = self.pool_dd.value
        self._refresh_filters_from_data()
        self._update_chart()

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

    def _on_chronos_sample_change(self, e: ft.ControlEvent) -> None:
        try:
            self.selected_chronos_sample_size = int(float(e.control.value or 0))
        except (TypeError, ValueError):
            self.selected_chronos_sample_size = 0
        self.chronos_sample_text.value = (
            f"Taille échantillon chronos: {self.selected_chronos_sample_size:,}".replace(
                ",", " "
            )
        )
        self.page.update()
        self._update_chart()

    def _on_corridor_swimmer_change(self, e: ft.ControlEvent) -> None:
        label = e.control.value
        name, yob = self._parse_corridor_swimmer_label(label)
        self.selected_corridor_swimmer_name = name
        self.selected_corridor_swimmer_yob = yob
        self._update_chart()

    def _parse_corridor_swimmer_label(
        self, label: Optional[str]
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Parse le format : "Name (YYYY)".
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
        return None, None

    # ----------------------------------------------------------------- Data-driven filters
    @staticmethod
    def _menu_height_for_count(option_count: int) -> int:
        return max(72, min(320, 56 * max(1, option_count)))

    def _refresh_filters_from_data(self, update_ui: bool = True) -> None:
        """Met à jour les listes d'options des filtres en fonction du graphique choisi."""
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
        df_scope_mem: Optional[pd.DataFrame] = None

        def _df_scope() -> pd.DataFrame:
            nonlocal df_scope_mem
            if df_scope_mem is None:
                df_scope_mem = _materialize_df_scope(
                    df_nav, self.selected_graph, stroke, distance, pool
                )
            return df_scope_mem

        if self.selected_graph in SCOPE_NO_FILTER_GRAPHS:
            combos: Dict[str, Dict[int, List[str]]] = {}
        else:
            nav_id = id(df_nav)
            if self._nav_combos_cache_id != nav_id or self._nav_combos_cache is None:
                self._nav_combos_cache = _event_combinations(df_nav)
                self._nav_combos_cache_id = nav_id
            combos = self._nav_combos_cache

        # Stroke options
        stroke_vals = list(combos.keys())
        self.stroke_dd.options = [ft.dropdown.Option(s) for s in stroke_vals]
        self.stroke_dd.menu_height = self._menu_height_for_count(len(stroke_vals))
        if self.selected_stroke not in stroke_vals:
            self.selected_stroke = stroke_vals[0] if stroke_vals else None
        self.stroke_dd.value = self.selected_stroke

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
        self.distance_dd.options = [ft.dropdown.Option(str(d)) for d in dist_vals]
        self.distance_dd.menu_height = self._menu_height_for_count(len(dist_vals))
        if self.selected_distance not in dist_vals:
            self.selected_distance = dist_vals[0] if dist_vals else None
        self.distance_dd.value = (
            str(self.selected_distance) if self.selected_distance is not None else None
        )

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
        self.pool_dd.options = [
            ft.dropdown.Option(key=str(p), text=str(p)) for p in pool_vals
        ]
        self.pool_dd.menu_height = self._menu_height_for_count(len(pool_vals))
        if self.selected_pool not in pool_vals:
            self.selected_pool = pool_vals[0] if pool_vals else None
        self.pool_dd.value = self.selected_pool

        if self.selected_graph in SCOPE_NO_FILTER_GRAPHS:
            self.stroke_dd.visible = False
            self.distance_dd.visible = False
            self.pool_dd.visible = False
        elif self.selected_graph in SCOPE_POOL_ONLY_GRAPHS:
            self.stroke_dd.visible = False
            self.distance_dd.visible = False
            self.pool_dd.visible = True
        elif self.selected_graph in SCOPE_NO_STROKE_GRAPHS:
            self.stroke_dd.visible = False
            self.distance_dd.visible = True
            self.pool_dd.visible = True
        else:
            self.stroke_dd.visible = True
            self.distance_dd.visible = True
            self.pool_dd.visible = True

        # Options spécifiques pour heatmap
        if self.selected_graph == "Heatmap vitesse moyenne (distance x nage)":
            self.heatmap_swimmer_dd.visible = True
            hid = id(df_nav)
            if self._heatmap_swimmer_names_cache_id != hid or self._heatmap_swimmer_names_cache is None:
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
            self.heatmap_swimmer_dd.options = [
                ft.dropdown.Option(name) for name in swimmer_options
            ]
            self.heatmap_swimmer_dd.menu_height = self._menu_height_for_count(
                len(swimmer_options)
            )
            if swimmer_options and not self.selected_heatmap_swimmer:
                self.selected_heatmap_swimmer = swimmer_options[0]
            self.heatmap_swimmer_dd.value = self.selected_heatmap_swimmer
        else:
            self.heatmap_swimmer_dd.options = []
            self.heatmap_swimmer_dd.value = None
            self.heatmap_swimmer_dd.menu_height = self._menu_height_for_count(1)
            self.heatmap_swimmer_dd.visible = False

        # Options spécifiques pour couloir de performance
        if self.selected_graph == "Couloir de performance (âge) - nageur cible":
            self.corridor_swimmer_dd.visible = True
            current_corridor_filter = (
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
            )
            if self._last_corridor_filter != current_corridor_filter:
                # Force la remise à zéro de la sélection quand les filtres changent
                # pour que la mise à jour de liste soit immédiatement visible.
                self.corridor_swimmer_dd.value = None
                self.selected_corridor_swimmer_name = None
                self.selected_corridor_swimmer_yob = None
                self._last_corridor_filter = current_corridor_filter
            nom_event = (
                f"{self.selected_distance} {self.selected_stroke} {self.selected_pool}"
                if self.selected_distance and self.selected_stroke and self.selected_pool
                else None
            )
            if nom_event:
                dfs = _df_scope()
                df_event = dfs[dfs["Event"] == nom_event].copy()
                df_event = df_event[
                    df_event["swimmer"].apply(
                        lambda x: isinstance(x, list) and len(x) == 1
                    )
                ].copy()
                swimmer_pairs = {
                    pair
                    for pair in df_event["swimmer"]
                    .apply(_primary_swimmer_name_and_yob)
                    .tolist()
                    if pair[0] is not None and pair[1] is not None
                }
                swimmer_pairs = sorted(
                    swimmer_pairs, key=lambda t: (str(t[0]).lower(), int(t[1]))
                )
                labels = [f"{name} ({yob})" for name, yob in swimmer_pairs]
                self.corridor_swimmer_dd.options = [
                    ft.dropdown.Option(label) for label in labels
                ]
                self.corridor_swimmer_dd.label = (
                    f"Nageur cible (couloir) — {len(labels)} disponibles"
                )
                self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(
                    len(labels)
                )
                if labels:
                    # Garde la valeur choisie si elle reste valide, sinon fallback.
                    if self.corridor_swimmer_dd.value not in labels:
                        self.corridor_swimmer_dd.value = labels[0]
                    name, yob = self._parse_corridor_swimmer_label(
                        self.corridor_swimmer_dd.value
                    )
                    self.selected_corridor_swimmer_name = name
                    self.selected_corridor_swimmer_yob = yob
            else:
                self.corridor_swimmer_dd.options = []
                self.corridor_swimmer_dd.value = None
                self.corridor_swimmer_dd.label = "Nageur cible (couloir) — 0 disponible"
                self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(1)
                self.selected_corridor_swimmer_name = None
                self.selected_corridor_swimmer_yob = None
        else:
            self.corridor_swimmer_dd.options = []
            self.corridor_swimmer_dd.value = None
            self.corridor_swimmer_dd.label = "Nageur cible (couloir de perf.)"
            self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(1)
            self.corridor_swimmer_dd.visible = False
            self.selected_corridor_swimmer_name = None
            self.selected_corridor_swimmer_yob = None

        # Option spécifique pacing comparatif (nageur cible)
        if self.selected_graph == "Split speed - F vs M + nageurs cibles":
            swimmer_options = sorted(
                {
                    n
                    for n in _df_scope()["swimmer"].apply(_primary_swimmer_name).tolist()
                    if n
                },
                key=lambda x: _normalize_text(x),
            )
            options = [ft.dropdown.Option(key="", text="(aucun)")] + [
                ft.dropdown.Option(name) for name in swimmer_options
            ]
            for dd in [self.pacing_swimmer_dd_1, self.pacing_swimmer_dd_2, self.pacing_swimmer_dd_3]:
                dd.options = options
                dd.menu_height = self._menu_height_for_count(len(options))
                dd.visible = True

            # Valeurs initiales par défaut: 3 premiers nageurs dispo
            default_vals = swimmer_options[:3]
            while len(default_vals) < 3:
                default_vals.append("")

            current = self.selected_pacing_swimmers[:]
            while len(current) < 3:
                current.append("")
            # Si une valeur n'existe plus, retombe sur défaut
            for i in range(3):
                if current[i] and current[i] not in swimmer_options:
                    current[i] = default_vals[i]
            if not any(current) and swimmer_options:
                current = default_vals

            self.pacing_swimmer_dd_1.value = current[0]
            self.pacing_swimmer_dd_2.value = current[1]
            self.pacing_swimmer_dd_3.value = current[2]

            cleaned: List[str] = []
            for s in current:
                if s and s not in cleaned:
                    cleaned.append(s)
            self.selected_pacing_swimmers = cleaned[:3]
        else:
            for dd in [self.pacing_swimmer_dd_1, self.pacing_swimmer_dd_2, self.pacing_swimmer_dd_3]:
                dd.options = []
                dd.value = None
                dd.menu_height = self._menu_height_for_count(1)
                dd.visible = False
            self.selected_pacing_swimmers = []

        # Option spécifique Chronos dans le temps (taille échantillon)
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
            if self.selected_chronos_sample_size < 0:
                self.selected_chronos_sample_size = 0
            self.chronos_sample_slider.min = 0
            self.chronos_sample_slider.max = float(max_count)
            self.chronos_sample_slider.value = float(self.selected_chronos_sample_size)
            self.chronos_sample_text.value = (
                f"Taille échantillon chronos: {self.selected_chronos_sample_size:,} / {max_count:,}".replace(
                    ",", " "
                )
            )
            self.chronos_sample_text.visible = True
            self.chronos_sample_slider.visible = True
        else:
            self.chronos_sample_text.visible = False
            self.chronos_sample_slider.visible = False

        # Catégorie / Graphique
        self.category_dd.menu_height = self._menu_height_for_count(len(self.category_dd.options))
        self.graph_dd.menu_height = self._menu_height_for_count(len(self.graph_dd.options))

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
            self._refresh_graph_registry_from_disk_if_changed()
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

            df_scope = _materialize_df_scope(
                self.df_nav,
                self.selected_graph,
                stroke,
                distance,
                pool,
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

