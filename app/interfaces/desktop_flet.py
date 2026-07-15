"""Application desktop Pacing (Flet) : présentation uniquement.

L'UI gère widgets, interactions et cache d'images. Le métier (chargement,
calculs, figures) passe par ``services.app_service.PacingAppService``.

Point d'entrée : ``python app/interfaces/desktop_flet.py``.
"""
import asyncio
import concurrent.futures
from collections import OrderedDict
import datetime as dt
import json
import threading
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple
import flet as ft
import pandas as pd

from project_path import PROJECT_DIR, ensure_project_imports

ensure_project_imports()

from loading_progress import TriplePrefetchProgress
from swimmer_search import SwimmerSearch
from desktop_prefetch_mixin import DesktopPrefetchMixin
from desktop_registry_mixin import DesktopRegistryMixin
from desktop_corridor_swimmer_mixin import DesktopCorridorSwimmerMixin
from desktop_helpers import (
    _event_combinations,
    _normalize_text,
    _pick_preferred_corridor_distance,
    _pick_preferred_corridor_stroke,
    _primary_swimmer_name,
    _primary_swimmer_name_and_yob,
    _resolve_scope_filters,
    _slugify,
)
from services.app_service import CORRIDOR_CHART_STYLE_VERSION, PacingAppService
from services.graph_catalog import (
    EVENT_COUNTS_SORT_OPTIONS,
    EVENT_COUNTS_SORT_STROKE_DISTANCE,
    GRAPH_CATEGORIES,
    GRAPH_CHRONOS_PAR_NAGE,
    GRAPHES_NOTEBOOK,
    SCOPE_EVENT_COUNTS_GRAPHS,
    SCOPE_GENDER_FILTER_GRAPHS,
    SCOPE_NO_FILTER_GRAPHS,
    SCOPE_NO_STROKE_GRAPHS,
    SCOPE_POOL_ONLY_GRAPHS,
    SCOPE_POOL_STROKE_GRAPHS,
    SCOPE_STROKE_ONLY_GRAPHS,
    HEATMAP_GRAPH_NAME,
    MEDIAN_VS_BEST_CHART_STYLE_VERSION,
    MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME,
    MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
    MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME,
    MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
    MEDIAN_SPEED_BY_GENDER_GRAPH_NAME,
    GRAPH_RELAY_SPLIT_DISTANCE,
    RELAY_SPLIT_CHART_STYLE_VERSION,
)
from services.stroke_labels import stroke_code_to_label
from services.paths import USASWIMMING_PARQUET_DIR as DEFAULT_USASWIMMING_PARQUET_DIR
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
    ENABLE_CORRIDOR_CHART_PREFETCH_ON_START,
    ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START,
    ENABLE_HEATMAP_CHART_PREFETCH_ON_START,
    ENABLE_MEDIAN_VS_BEST_CHART_PREFETCH_ON_START,
    ENABLE_NOTEBOOK_PREFETCH_ON_START,
    ENABLE_PERSISTENT_GRAPH_CACHE,
    ENABLE_RELAY_CHART_PREFETCH_ON_START,
    ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START,
    EVENT_SWIMMERS_EXPORT_PATH,
    EXPORT_IMAGE_BASE64_TO_JSON,
    GRAPH_EXPORT_PATH,
    HEATMAP_DROPDOWN_SWIMMER_LIMIT,
    USA_CORRIDOR_COLS,
    USA_CORRIDOR_GRAPH_NAME,
    USA_CORRIDOR_MIN_POINTS,
)

# --- Constantes UI locales ---

CHART_UPDATE_AFTER_FILTER_DEBOUNCE_SEC = 0.1
SCOPE_PERFORMANCES_CACHE_MAX_ENTRIES = 64
HEATMAP_SWIMMER_SEARCH_LABEL = "Rechercher un nageur (heatmap)"
HEATMAP_SWIMMER_SEARCH_TOOLTIP = "Nom du nageur — toutes les performances Extranat"
CORRIDOR_SWIMMER_SUGGESTIONS_MAX = 200
CORRIDOR_SWIMMER_DROPDOWN_OPTIONS_MAX = 100
CORRIDOR_SEARCH_DEBOUNCE_SEC = 0.12

USA_CORRIDOR_SWIMMER_SEARCH_LABEL = "Rechercher un nageur (USA Swimming)"
USA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP = "Nom du nageur"
FR_CORRIDOR_SWIMMER_SEARCH_LABEL = "Rechercher un nageur"
FR_CORRIDOR_SWIMMER_SEARCH_TOOLTIP = "Nom ou annee de naissance"
MA_CORRIDOR_SWIMMER_SEARCH_LABEL = "Rechercher un nageur (Maroc)"
MA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP = "Nom ou annee de naissance"


class PacingDesktopApp(DesktopPrefetchMixin, DesktopRegistryMixin, DesktopCorridorSwimmerMixin):
    """Application desktop Flet : état global, prefetch et rendu des graphiques.

    Centralise le DataFrame Extranat, les caches de rendu (images base64,
    event swimmers, scope performances), la navigation par catégorie/graphique
    et les widgets de recherche nageur (France, USA, Maroc).

    Attributes:
        page (ft.Page): Page Flet principale.
        df (pd.DataFrame): Performances Extranat chargées.
        graph_render_registry (dict): Cache des graphiques précalculés.
    """

    def __init__(self, page: ft.Page) -> None:
        """Initialise la page Flet et lance le bootstrap en arrière-plan.

        Args:
            page (ft.Page): Page fournie par Flet au démarrage.

        Returns:
            None
        """
        self.page = page
        self.page.title = "Pacing"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#020617"
        self.page.padding = 0

        self._startup_prefetch_ui: Optional[TriplePrefetchProgress] = None
        self._defer_prefetch_json_write: bool = False
        self._ui_light_mode: bool = False
        self._sidebar_container: Optional[ft.Container] = None
        self._main_area_container: Optional[ft.Container] = None
        self._theme_toggle_btn: Optional[ft.IconButton] = None
        self._nav_title_text: Optional[ft.Text] = None
        self.page.run_thread(self._bootstrap_startup)

    def _bootstrap_startup(self) -> None:
        """pipeline de démarrrage"""
        try:
            self.app = PacingAppService()
            self.df: pd.DataFrame = self.app.load_extranat()
            self.df_nav: pd.DataFrame = self.df.copy()
            self._frm_df_cache: Optional[pd.DataFrame] = None
            self._usa_events_cache: Optional[List[str]] = None
            self._usa_df_by_event: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
            self._usa_names_by_event_key: "OrderedDict[Tuple[str, str], List[str]]" = (
                OrderedDict()
            )

            # Selections courantes
            self.selected_country: str = COUNTRY_FRANCE
            self.selected_usa_event: Optional[str] = None
            self.selected_category: str = list[str](GRAPH_CATEGORIES.keys())[0]
            self.selected_graph: str = GRAPH_CATEGORIES[self.selected_category][0]
            self.selected_stroke: Optional[str] = None
            self.selected_distance: Optional[int] = None
            self.selected_pool: Optional[str] = None
            self.selected_event_counts_sort: str = EVENT_COUNTS_SORT_STROKE_DISTANCE
            self.selected_corridor_gender: str = "all"
            self.selected_heatmap_swimmer: Optional[str] = None
            self.selected_corridor_swimmer_name: Optional[str] = None
            self.selected_corridor_swimmer_yob: Optional[int] = None
            # Déciles 10-90 : nageur réellement tracé après clic sur le bouton ✓ (pas via recherche/liste seuls).
            self.corridor_deciles_confirmed_name: Optional[str] = None
            self.corridor_deciles_confirmed_yob: Optional[int] = None
            # USA / France : nageur tracé sur le couloir « nageur cible » après confirmation ✓.
            self.corridor_usa_confirmed_name: Optional[str] = None
            self.corridor_fr_confirmed_name: Optional[str] = None
            self.corridor_fr_confirmed_yob: Optional[int] = None
            self.selected_moroccan_corridor_swimmer_name: Optional[str] = None
            self.selected_moroccan_corridor_swimmer_yob: Optional[int] = None
            self.corridor_ma_confirmed_name: Optional[str] = None
            self.corridor_ma_confirmed_yob: Optional[int] = None
            self._moroccan_corridor_dd_options_key: Optional[Tuple[Any, ...]] = None
            self.moroccan_corridor_swimmer_search_query: str = ""
            self._moroccan_corridor_swimmer_labels_all: List[str] = []
            self._moroccan_corridor_swimmer_labels_filter_key: Optional[
                Tuple[Any, ...]
            ] = None
            self._moroccan_corridor_swimmer_labels_set: Optional[set] = None
            self._moroccan_corridor_swimmer_search_index_key: Optional[int] = None
            self._moroccan_corridor_swimmer_search_index: Optional[
                List[Tuple[str, str, Tuple[str, ...]]]
            ] = None
            self._moroccan_corridor_search_ui_gen: int = 0
            self.corridor_swimmer_search_query: str = ""
            self.selected_pacing_swimmers: List[str] = []
            self.selected_chronos_sample_size: int = 5000
            self._last_corridor_filter: Optional[
                Tuple[Optional[str], Optional[int], Optional[str], str]
            ] = None
            self.graph_render_registry: Dict[str, Dict[str, Any]] = {}
            self.chart_image_cache: Dict[str, str] = {}
            self._prefetched_json_mtime: float = 0.0 # la ref temporelle en memoire (prefetched_graphs.json)
            self._registry_json_lock = threading.Lock()
            self._nav_combos_cache_key: Optional[Tuple[Any, ...]] = None
            self._nav_combos_cache: Optional[Dict[str, Dict[int, List[str]]]] = None
            self._event_swimmers_cache: Dict[str, Dict[str, Dict[str, Dict[str, List[str]]]]] = {}
            self._selected_event_swimmers: List[str] = []
            self._event_swimmer_options_cache: Dict[
                Tuple[str, int, str, str], List[ft.dropdown.Option]
            ] = {}
            self._corridor_dd_options_event_key: Optional[Tuple[str, int, str, str]] = None
            self._corridor_swimmer_labels_all: List[str] = []
            self._corridor_swimmer_labels_filter_key: Optional[
                Tuple[str, int, str, str]
            ] = None
            self._corridor_swimmer_search_index_key: Optional[int] = None
            self._corridor_swimmer_search_index: Optional[
                List[Tuple[str, str, Tuple[str, ...]]]
            ] = None
            self._corridor_swimmer_labels_set: Optional[set] = None
            self._corridor_search_ui_gen: int = 0
            self.corridor_swimmer_search: Optional[SwimmerSearch] = None
            self._chart_schedule_gen: int = 0
            self._corridor_swimmer_schedule_gen: int = 0
            self._usa_swimmer_schedule_gen: int = 0
            self._usa_bootstrap_gen: int = 0
            self._usa_events_load_lock = threading.Lock()
            self._pacing_swimmer_options_key: Optional[Tuple[str, ...]] = None
            self._is_syncing_pacing_dropdowns: bool = False
            self._heatmap_swimmer_names_cache_id: Optional[int] = None
            self._heatmap_swimmer_names_cache: Optional[List[str]] = None
            self.heatmap_swimmer_search_query: str = ""
            self._heatmap_swimmer_labels_all: List[str] = []
            self._heatmap_swimmer_labels_set: Optional[set] = None
            self._heatmap_swimmer_search_index_key: Optional[int] = None
            self._heatmap_swimmer_search_index: Optional[
                List[Tuple[str, str, Tuple[str, ...]]]
            ] = None
            self._heatmap_search_ui_gen: int = 0
            self.heatmap_swimmer_search: Optional[SwimmerSearch] = None
            self._heatmap_dropdown_options: Optional[List[str]] = None
            self._heatmap_dropdown_options_ready: bool = False
            self._heatmap_dropdown_df_len: Optional[int] = None
            self._registry_swimmer_names_cache: Optional[List[str]] = None
            self._registry_swimmer_names_cache_key: Optional[Tuple[float, int]] = None
            self._scope_performances_cache: "OrderedDict[Tuple[Any, ...], pd.DataFrame]" = (
                OrderedDict()
            )
            self._scope_performances_prefetched_on_startup: bool = False
            self._corridor_charts_prefetched_on_startup: bool = False
            self._heatmap_charts_prefetched_on_startup: bool = False
            self._median_vs_best_charts_prefetched_on_startup: bool = False
            self._relay_charts_prefetched_on_startup: bool = False
            self._chart_render_gen: int = 0
            self._chart_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="pacing-chart",
            )
            # Widgets Flet
            self.country_dd: ft.Dropdown
            self.usa_event_dd: ft.Dropdown
            self.category_dd: ft.Dropdown
            self.graph_dd: ft.Dropdown
            self.stroke_dd: ft.Dropdown
            self.distance_dd: ft.Dropdown
            self.pool_dd: ft.Dropdown
            self.corridor_gender_dd: ft.Dropdown
            self.heatmap_swimmer_dd: ft.Dropdown
            self.heatmap_swimmer_search_container: ft.Column
            self.corridor_swimmer_dd: ft.Dropdown
            self.corridor_moroccan_swimmer_dd: ft.Dropdown
            self.moroccan_corridor_swimmer_search: Optional[SwimmerSearch]
            self.moroccan_corridor_swimmer_search_container: ft.Column
            self.moroccan_corridor_swimmer_confirm_btn: ft.IconButton
            self.corridor_swimmer_confirm_btn: ft.IconButton
            self.corridor_swimmer_search_tf: ft.AutoComplete
            self.corridor_swimmer_search_container: ft.Column
            self.corridor_swimmer_search_label: ft.Text
            self.corridor_mode_switch: ft.Switch
            self.pacing_swimmer_dd_1: ft.Dropdown
            self.pacing_swimmer_dd_2: ft.Dropdown
            self.pacing_swimmer_dd_3: ft.Dropdown

            self.image = ft.Image(
                src="",
                expand=True, 
                fit=ft.BoxFit.CONTAIN,
                border_radius=ft.BorderRadius.all(4),
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
            self.chart_busy_icon = ft.Icon(
                ft.icons.Icons.AUTORENEW,
                size=14,
                color="#22c55e",
                visible=False,
            )
            self.chart_busy_text = ft.Text(
                "Chargement...",
                size=11,
                color="#9ca3af",
                visible=False,
            )
            self.loader = ft.ProgressRing(
                visible=False, width=32, height=32, color="#22c55e"
            )
            if ENABLE_PERSISTENT_GRAPH_CACHE:
                self._load_graph_registry_json()
            if not ENABLE_EVENT_SWIMMERS_CACHE_PREFETCH_ON_START:
                self._load_event_swimmers_cache_json()
            self._load_scope_performances_cache_json()
            self._build_heatmap_swimmer_dropdown_options()

            graph_json_path = GRAPH_EXPORT_PATH.name
            event_swimmers_json_path = EVENT_SWIMMERS_EXPORT_PATH.name
            try:
                parquet_cache_path = str(
                    DEFAULT_USASWIMMING_PARQUET_DIR.relative_to(PROJECT_DIR)
                )
            except ValueError:
                parquet_cache_path = str(DEFAULT_USASWIMMING_PARQUET_DIR)

            if ENABLE_PERSISTENT_GRAPH_CACHE:
                left_total = (
                    max(1, len(GRAPHES_NOTEBOOK))
                    if (
                        ENABLE_NOTEBOOK_PREFETCH_ON_START
                        and not self.df.empty
                    )
                    else 1
                )
                middle_total = 1
                parquet_total = max(
                    1,
                    len(self.app.available_years_usa()),
                )
                startup = TriplePrefetchProgress(
                    self.page,
                    left_total,
                    middle_total,
                    parquet_total,
                    graph_json_path,
                    event_swimmers_json_path,
                    parquet_cache_path,
                    middle_header="Nageurs événements — prefetched_event_swimmers.json",
                    right_header="Parquet USA Swimming — _parquet_cache",
                    middle_progress_label="Nageurs par événement",
                    right_progress_label="Cache Parquet",
                )
                startup.mount()
                self._startup_prefetch_ui = startup
                self._defer_prefetch_json_write = True
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                        f_nb = pool.submit(self._run_notebook_prefetch_worker)
                        f_ev = pool.submit(self._run_event_swimmers_cache_prefetch_worker)
                        f_pq = pool.submit(self._run_usaswimming_parquet_cache_worker)
                        concurrent.futures.wait((f_nb, f_ev, f_pq))
                        for fut in (f_nb, f_ev, f_pq):
                            fut.result()
                finally:
                    self._defer_prefetch_json_write = False
                    self._startup_prefetch_ui = None
                    self._write_graph_registry_json()
            if (
                ENABLE_SCOPE_PERFORMANCES_CACHE_PREFETCH_ON_START
                and not self.df_nav.empty
                and not self._scope_performances_prefetched_on_startup
            ):
                self._prefetch_scope_performances_cache_on_startup()
            self.page.clean()
            self._build_ui()
            self.page.run_thread(self._warm_usa_events_cache)
            self._update_chart()
            if (
                ENABLE_CORRIDOR_CHART_PREFETCH_ON_START
                and not self.df_nav.empty
                and not self._corridor_charts_prefetched_on_startup
            ):
                self.page.run_thread(self._prefetch_corridor_chart_images_on_startup)
            if (
                ENABLE_HEATMAP_CHART_PREFETCH_ON_START
                and not self.df_nav.empty
                and not self._heatmap_charts_prefetched_on_startup
            ):
                self.page.run_thread(self._prefetch_heatmap_charts_on_startup)
            if (
                ENABLE_MEDIAN_VS_BEST_CHART_PREFETCH_ON_START
                and not self.df_nav.empty
                and not self._median_vs_best_charts_prefetched_on_startup
            ):
                self.page.run_thread(self._prefetch_median_vs_best_charts_on_startup)
            if (
                ENABLE_RELAY_CHART_PREFETCH_ON_START
                and not self.df_nav.empty
                and not self._relay_charts_prefetched_on_startup
            ):
                self.page.run_thread(self._prefetch_relay_charts_on_startup)
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
        self._chart_render_gen += 1
        token = self._chart_render_gen

        async def _runner() -> None:
            await asyncio.sleep(0)
            await asyncio.sleep(delay_sec)
            if token != self._chart_render_gen:
                return
            self._begin_chart_render(update_ui=True, token=token)

        self.page.run_task(_runner)

    def _apply_theme_palette(self) -> None:
        """Aligne page, panneaux et textes sur ``_ui_light_mode`` (le thème Material seul ne suffit pas)."""
        light = self._ui_light_mode
        self.page.theme_mode = ft.ThemeMode.LIGHT if light else ft.ThemeMode.DARK
        if light:
            self.page.bgcolor = "#e2e8f0"
            sidebar_bg = "#ffffff"
            main_bg = "#f8fafc"
            nav_title = "#0f172a"
            row_muted = "#475569"
            err = "#b91c1c"
        else:
            self.page.bgcolor = "#020617"
            sidebar_bg = "#020617"
            main_bg = "#020617"
            nav_title = "#f8fafc"
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

        self.row_count_text.color = row_muted
        self.status_text.color = err

    def _build_ui(self) -> None:
        """Construit la mise en page Flet (sidebar + zone graphique).

        Args:
            None: Cette méthode n'accepte aucun paramètre explicite.

        Returns:
            None: Instancie les contrôles UI puis les attache à la page.
        """
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

        if self.selected_country == COUNTRY_MOROCCO:
            self.selected_country = COUNTRY_FRANCE
        self.country_dd = ft.Dropdown(
            label="Pays",
            options=[
                ft.dropdown.Option(COUNTRY_FRANCE),
                ft.dropdown.Option(COUNTRY_USA),
            ],
            value=self.selected_country,
            on_select=self._on_country_change,
            filled=True,
            menu_height=120,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.usa_event_dd = ft.Dropdown(
            label="Épreuve (USA Swimming)",
            options=[],
            value=None,
            on_select=self._on_usa_event_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
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
            label="Nage",
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
        self.event_counts_sort_dd = ft.Dropdown(
            label="Tri des épreuves",
            options=[
                ft.dropdown.Option(key=key, text=label)
                for key, label in EVENT_COUNTS_SORT_OPTIONS.items()
            ],
            value=self.selected_event_counts_sort,
            on_select=self._on_filter_change,
            filled=True,
            menu_height=220,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
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
        self.heatmap_swimmer_search = SwimmerSearch(
            self,
            width=dropdown_width,
            label_text=HEATMAP_SWIMMER_SEARCH_LABEL,
            tooltip=HEATMAP_SWIMMER_SEARCH_TOOLTIP,
            query_attr="heatmap_swimmer_search_query",
            keystroke_callback_name="_on_heatmap_swimmer_search_keystroke",
            schedule_ui_refresh_callback_name="_schedule_heatmap_swimmer_search_ui_refresh",
            pick_callback_name="_on_heatmap_swimmer_search_pick",
            show_confirm_button=False,
            debounced_search=True,
        )
        self.heatmap_swimmer_search_container = self.heatmap_swimmer_search.container
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
        self.corridor_moroccan_swimmer_dd = ft.Dropdown(
            label="Nageur marocain (FRM Natation)",
            options=[],
            on_select=self._on_moroccan_corridor_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.moroccan_corridor_swimmer_search = SwimmerSearch(
            self,
            width=dropdown_width,
            label_text=MA_CORRIDOR_SWIMMER_SEARCH_LABEL,
            tooltip=MA_CORRIDOR_SWIMMER_SEARCH_TOOLTIP,
            query_attr="moroccan_corridor_swimmer_search_query",
            keystroke_callback_name="_on_moroccan_corridor_swimmer_search_keystroke",
            schedule_ui_refresh_callback_name="_schedule_moroccan_corridor_swimmer_search_ui_refresh",
            confirm_callback_name="_on_confirm_moroccan_corridor_swimmer",
            pick_callback_name="_on_moroccan_corridor_swimmer_search_pick",
            show_confirm_button=True,
        )
        self.moroccan_corridor_swimmer_search_container = (
            self.moroccan_corridor_swimmer_search.container
        )
        self.moroccan_corridor_swimmer_confirm_btn = (
            self.moroccan_corridor_swimmer_search.confirm_btn
        )
        self.corridor_swimmer_search = SwimmerSearch(
            self, width=dropdown_width, show_confirm_button=True
        )
        self.corridor_swimmer_search_label = self.corridor_swimmer_search.label
        self.corridor_swimmer_search_tf = self.corridor_swimmer_search.input
        self.corridor_swimmer_search_container = self.corridor_swimmer_search.container
        self.corridor_swimmer_confirm_btn = self.corridor_swimmer_search.confirm_btn
        self.corridor_mode_switch = ft.Switch(
            label="Mode couloir déciles 10-90",
            value=self.selected_graph == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
            visible=self.selected_category == CORRIDOR_CATEGORY,
            on_change=self._on_corridor_mode_switch_change,
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

        self._nav_title_text = ft.Text(
            "Navigation",
            size=20,
            weight=ft.FontWeight.BOLD,
        )
        self._theme_toggle_btn = ft.IconButton(
            icon=ft.icons.Icons.LIGHT_MODE,
            icon_color="#facc15",
            tooltip="Basculer mode clair / sombre",
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
                        [
                            self._nav_title_text,
                            ft.Row(
                                [self.corridor_mode_switch, self._theme_toggle_btn],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=10),
                    self.category_dd,
                    self.graph_dd,
                    ft.Divider(),
                    self.country_dd,
                    self.usa_event_dd,
                    self.stroke_dd,
                    self.distance_dd,
                    self.pool_dd,
                    self.event_counts_sort_dd,
                    self.corridor_gender_dd,
                    self.pacing_swimmer_dd_1,
                    self.pacing_swimmer_dd_2,
                    self.pacing_swimmer_dd_3,
                    self.heatmap_swimmer_search_container,
                    self.heatmap_swimmer_dd,
                    self.corridor_swimmer_search_container,
                    self.corridor_swimmer_dd,
                    self.moroccan_corridor_swimmer_search_container,
                    self.corridor_moroccan_swimmer_dd,
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
                                ft.Row(
                                    [self.chart_busy_icon, self.chart_busy_text],
                                    alignment=ft.MainAxisAlignment.CENTER,
                                    spacing=6,
                                ),
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
        name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
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
        name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
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
        name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
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
            name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
            if not name:
                return
            self.corridor_usa_confirmed_name = name
            self.selected_corridor_swimmer_name = name
            self.selected_corridor_swimmer_yob = yob
            self._schedule_deferred_chart_update()
            return
        name, yob = PacingDesktopApp._parse_corridor_swimmer_label(label)
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

        df_scope = self.app.materialize_scope(
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

    def _chart_render_snapshot(self) -> Dict[str, Any]:
        corridor_name = self.selected_corridor_swimmer_name
        corridor_yob = self.selected_corridor_swimmer_yob
        deciles_name = self.corridor_deciles_confirmed_name
        deciles_yob = self.corridor_deciles_confirmed_yob
        graph = self.selected_graph
        if self._is_usa_corridor_mode():
            corridor_name = self.corridor_usa_confirmed_name
            corridor_yob = self.selected_corridor_swimmer_yob
        elif (
            self.selected_country == COUNTRY_FRANCE
            and graph in CORRIDOR_FR_TARGET_SWIMMER_GRAPHS
        ):
            corridor_name = (
                self.corridor_fr_confirmed_name
                or self.selected_corridor_swimmer_name
            )
            corridor_yob = (
                self.corridor_fr_confirmed_yob
                if self.corridor_fr_confirmed_name
                else self.selected_corridor_swimmer_yob
            )
        elif self.selected_country == COUNTRY_MOROCCO:
            corridor_name = self.selected_corridor_swimmer_name
            corridor_yob = self.selected_corridor_swimmer_yob
        elif graph == CORRIDOR_GLOBAL_GRAPH_NAME:
            corridor_name = None
            corridor_yob = None
        elif graph == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME:
            corridor_name = deciles_name
            corridor_yob = deciles_yob
        return {
            "country": self.selected_country,
            "category": self.selected_category,
            "graph": graph,
            "usa_event": self.selected_usa_event,
            "stroke": self.selected_stroke,
            "distance": self.selected_distance,
            "pool": self.selected_pool,
            "corridor_gender": self.selected_corridor_gender,
            "corridor_name": corridor_name,
            "corridor_yob": corridor_yob,
            "moroccan_corridor_name": self.corridor_ma_confirmed_name,
            "moroccan_corridor_yob": self.corridor_ma_confirmed_yob,
            "deciles_name": deciles_name,
            "deciles_yob": deciles_yob,
            "heatmap": self.selected_heatmap_swimmer,
            "pacing": self.selected_pacing_swimmers[:3],
            "chronos_sample_size": int(self.selected_chronos_sample_size),
            "event_counts_sort": self.selected_event_counts_sort,
        }

    def _build_render_key_from_snapshot(self, snapshot: Dict[str, Any]) -> Tuple[str, Dict[str, Any], str]:
        """Fabriquer la clé de cache (et les options associées) à partir d'un instantané d'UI, pour savoir si un PNG déjà calculé peut être réutilisé"""
        if snapshot.get("country") == COUNTRY_USA:
            gender = snapshot.get("corridor_gender") or "all"
            gender_key = (
                gender if gender in ("F", "M") else "all"
            )
            options = {
                "country": COUNTRY_USA,
                "usa_event": snapshot.get("usa_event"),
                "gender": gender_key,
                "swimmer_name": snapshot.get("corridor_name"),
                "moroccan_corridor_swimmer_name": snapshot.get("moroccan_corridor_name"),
                "moroccan_corridor_swimmer_yob": snapshot.get("moroccan_corridor_yob"),
            }
            chart_id, render_key = self._render_key_for_category_graph_options(
                str(snapshot["category"]),
                str(snapshot["graph"]),
                options,
            )
            return chart_id, options, render_key

        graph_name = str(snapshot["graph"])
        heatmap = snapshot.get("heatmap")
        pacing = snapshot.get("pacing") or []
        if graph_name in CORRIDOR_SWIMMER_UI_GRAPHS:
            heatmap = None
            pacing = []
        corridor_name = snapshot.get("corridor_name")
        corridor_yob = snapshot.get("corridor_yob")
        if graph_name == CORRIDOR_GLOBAL_GRAPH_NAME:
            corridor_name = None
            corridor_yob = None
        elif graph_name == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME:
            corridor_name = snapshot.get("deciles_name")
            corridor_yob = snapshot.get("deciles_yob")
        options = {
            "stroke": snapshot.get("stroke"),
            "distance": int(snapshot["distance"])
            if snapshot.get("distance") is not None
            else None,
            "pool": snapshot.get("pool"),
            "heatmap_swimmer": heatmap,
            "corridor_swimmer_name": corridor_name,
            "corridor_swimmer_yob": corridor_yob,
            "moroccan_corridor_swimmer_name": snapshot.get("moroccan_corridor_name"),
            "moroccan_corridor_swimmer_yob": snapshot.get("moroccan_corridor_yob"),
            "pacing_swimmers": pacing,
            "chronos_sample_size": int(snapshot.get("chronos_sample_size", 5000)),
        }
        if graph_name in SCOPE_EVENT_COUNTS_GRAPHS:
            options["event_counts_sort"] = snapshot.get(
                "event_counts_sort", EVENT_COUNTS_SORT_STROKE_DISTANCE
            )
        if graph_name in CORRIDOR_SWIMMER_UI_GRAPHS:
            options["chart_style_version"] = CORRIDOR_CHART_STYLE_VERSION
        chart_id, render_key = self._render_key_for_category_graph_options(
            str(snapshot["category"]),
            graph_name,
            options,
        )
        return chart_id, options, render_key

    def _corridor_fallback_render_keys(self, snapshot: Dict[str, Any]) -> List[str]:
        """Clés cache du même graphique sans nageur (stale-while-revalidate).

        Ne propose qu'une variante du graphique courant (même épreuve, sans
        nageur cible) pour éviter d'afficher brièvement un autre type de couloir
        puis de le masquer au recalcul.
        """
        fallback = {
            **snapshot,
            "corridor_name": None,
            "corridor_yob": None,
            "moroccan_corridor_name": None,
            "moroccan_corridor_yob": None,
            "deciles_name": None,
            "deciles_yob": None,
        }
        _, _, render_key = self._build_render_key_from_snapshot(fallback)
        return [render_key]

    def _try_show_stale_corridor_chart(self, *, update_ui: bool) -> bool:
        """Affiche une image couloir déjà en cache pendant le recalcul (stale-while-revalidate)."""
        if self._is_usa_corridor_mode():
            snapshot = self._chart_render_snapshot()
            _, _, exact_key = self._build_render_key_from_snapshot(snapshot)
            return self._try_apply_chart_from_cache(exact_key, update_ui=update_ui)
        if self.selected_graph not in CORRIDOR_SWIMMER_UI_GRAPHS:
            return False
        snapshot = self._chart_render_snapshot()
        _, _, exact_key = self._build_render_key_from_snapshot(snapshot)
        if self._try_apply_chart_from_cache(exact_key, update_ui=update_ui):
            return True
        for render_key in self._corridor_fallback_render_keys(snapshot):
            if render_key != exact_key and self._try_apply_chart_from_cache(
                render_key, update_ui=update_ui
            ):
                return True
        return False

    def _refresh_corridor_swimmer_options_lightweight(self) -> None:
        """Met à jour recherche + dropdown nageur (même logique France / USA)."""
        if self._is_usa_corridor_mode():
            if not self.selected_usa_event:
                return
            labels_all = self._corridor_swimmer_labels_for_search()
            if not labels_all:
                return
            self._refresh_corridor_swimmer_ui_from_labels(labels_all)
            return

        if self.selected_graph not in CORRIDOR_SWIMMER_UI_GRAPHS:
            return
        if not (
            self.selected_stroke
            and self.selected_distance is not None
            and self.selected_pool
        ):
            return

        labels_all = self._corridor_swimmer_labels_for_search()
        if not labels_all:
            return
        self._refresh_corridor_swimmer_ui_from_labels(labels_all)

    def _lookup_chart_cache(self, render_key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        with self._registry_json_lock:
            cached = self.graph_render_registry.get(render_key)
            cached_image = self.chart_image_cache.get(render_key)
            if cached_image is None and isinstance(cached, dict):
                img = cached.get("image_base64")
                if isinstance(img, str) and len(img) > 0:
                    cached_image = img
                    self.chart_image_cache[render_key] = img
        return cached, cached_image

    def _format_performance_count_text(self, row_count: int) -> str:
        """Formate le libellé d'effectif affiché sous chaque graphique.

        Args:
            row_count (int): Nombre de performances disponibles pour les filtres actifs.

        Returns:
            str: Texte localisé du type « Nombre de performances disponibles : N ».
        """
        return (
            f"Nombre de performances disponibles : {int(row_count):,}".replace(",", " ")
        )

    def _try_apply_chart_from_cache(self, render_key: str, *, update_ui: bool) -> bool:
        cached, cached_image = self._lookup_chart_cache(render_key)
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
                row_count = int(cached.get("row_count", 0))
                self.row_count_text.value = self._format_performance_count_text(row_count)
                self.page.update()
            return True
        return False

    def _compute_usa_corridor_chart_payload(self, snap: Dict[str, Any]) -> Dict[str, Any]:
        """prépare l'image du couloir USA pour l'interface (cache UI + façade métier)."""
        category = str(snap["category"])
        graph_name = str(snap["graph"])
        usa_event = snap.get("usa_event")
        _, _, render_key = self._build_render_key_from_snapshot(snap)

        cached, cached_image = self._lookup_chart_cache(render_key)
        if (
            cached is not None
            and cached.get("status") == "ok"
            and cached_image is not None
        ):
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "country": COUNTRY_USA,
                "usa_event": usa_event,
                "status": "cached",
                "image_base64": cached_image,
                "chart_title": str(cached.get("chart_title", graph_name)),
                "row_count": int(cached.get("row_count", 0)),
                "error": None,
            }

        return self.app.compute_usa_corridor_chart_payload(snap, render_key=render_key)

    def _compute_chart_payload(self, *, snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Cache UI puis délégation métier à ``PacingAppService``."""
        snap = snapshot if snapshot is not None else self._chart_render_snapshot()
        if snap.get("country") == COUNTRY_USA:
            return self._compute_usa_corridor_chart_payload(snap)

        graph_name = str(snap["graph"])
        category = str(snap["category"])
        stroke = snap.get("stroke")
        distance = snap.get("distance")
        pool = snap.get("pool")

        _, _, render_key = self._build_render_key_from_snapshot(snap)
        cached, cached_image = self._lookup_chart_cache(render_key)
        if (
            cached is not None
            and cached.get("status") == "ok"
            and cached_image is not None
        ):
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "stroke": stroke,
                "distance": distance,
                "pool": pool,
                "status": "cached",
                "image_base64": cached_image,
                "chart_title": str(cached.get("chart_title", graph_name)),
                "row_count": int(cached.get("row_count", 0)),
                "error": None,
            }

        return self.app.compute_chart_payload(
            snap,
            df_extranat=self.df,
            df_nav=self.df_nav,
            render_key=render_key,
            needs_moroccan_overlay=self._needs_moroccan_corridor_swimmer_dd(),
        )

    def _register_chart_payload(self, payload: Dict[str, Any]) -> None:
        status = str(payload.get("status", ""))
        if status in ("cached",):
            return
        if status not in ("ok", "no_figure", "empty_scope", "error"):
            return
        render_key = str(payload["render_key"])
        chart_id, options, _ = self._build_render_key_from_snapshot(
            {
                "country": payload.get("country", self.selected_country),
                "category": payload["category"],
                "graph": payload["graph_name"],
                "usa_event": payload.get("usa_event"),
                "stroke": payload.get("stroke"),
                "distance": payload.get("distance"),
                "pool": payload.get("pool"),
                "corridor_gender": payload.get("corridor_gender"),
                "corridor_name": payload.get("corridor_name"),
                "corridor_yob": payload.get("corridor_yob"),
                "deciles_name": payload.get("deciles_name"),
                "deciles_yob": payload.get("deciles_yob"),
                "heatmap": payload.get("heatmap"),
                "pacing": payload.get("pacing") or [],
                "chronos_sample_size": payload.get(
                    "chronos_sample_size", self.selected_chronos_sample_size
                ),
            }
        )
        with self._registry_json_lock:
            self.graph_render_registry[render_key] = {
                "id": chart_id,
                "name": str(payload["graph_name"]),
                "category": str(payload["category"]),
                "method": f"render_{_slugify(str(payload['graph_name']))}",
                "status": status,
                "chart_title": str(payload.get("chart_title", payload["graph_name"])),
                "row_count": int(payload.get("row_count", 0)),
                "error": payload.get("error"),
                "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "options": options,
                "image_base64": payload.get("image_base64"),
            }
            image_base64 = payload.get("image_base64")
            if image_base64:
                self.chart_image_cache[render_key] = image_base64
        item = self.graph_render_registry[render_key]
        if PacingDesktopApp._is_corridor_registry_item(item):
            self._write_corridor_graphs_json()
        else:
            self._write_graph_registry_json()

    def _apply_chart_payload(self, payload: Dict[str, Any], *, update_ui: bool) -> None:
        """Applique le résultat de rendu sur l'UI et met à jour les caches.

        Args:
            payload (Dict[str, Any]): Résultat produit par ``_compute_chart_payload``.
            update_ui (bool): Indique s'il faut pousser immédiatement les changements visuels.

        Returns:
            None: Met à jour l'image, les messages de statut et les caches.
        """
        status = str(payload.get("status", ""))
        try:
            if status == "cached":
                self._try_apply_chart_from_cache(
                    str(payload["render_key"]), update_ui=update_ui
                )
                return
            if status == "empty_scope":
                if update_ui:
                    self.image.visible = False
                    self.row_count_text.value = self._format_performance_count_text(
                        int(payload.get("row_count", 0))
                    )
                    self.status_text.value = "Aucune donnée pour les filtres sélectionnés."
            elif status == "no_figure":
                if update_ui:
                    self.image.visible = False
                    chart_title = str(payload.get("chart_title", ""))
                    self.row_count_text.value = self._format_performance_count_text(
                        int(payload.get("row_count", 0))
                    )
                    if chart_title and chart_title != payload.get("graph_name"):
                        self.status_text.value = chart_title
                    else:
                        self.status_text.value = (
                            "Graphique non encore implémenté dans la version PyFlet "
                            "ou aucune donnée exploitable pour ces filtres."
                        )
            elif status == "ok" and payload.get("image_base64"):
                if update_ui:
                    self.image.visible = True
                    self.image.src = payload["image_base64"]
                    self.status_text.value = ""
                    self.row_count_text.value = self._format_performance_count_text(
                        int(payload.get("row_count", 0))
                    )
            if status not in ("cached",):
                self._register_chart_payload(payload)
        except Exception as exc:  # type: ignore[bare-except]
            if update_ui:
                self.image.visible = False
                self.row_count_text.value = self._format_performance_count_text(
                    int(payload.get("row_count", 0))
                )
                self.status_text.value = f"Erreur lors de la génération du graphique: {exc}"
        finally:
            if update_ui:
                self.loader.visible = False
                self.chart_busy_icon.visible = False
                self.chart_busy_text.visible = False
                self.page.update()

    def _begin_chart_render(self, *, update_ui: bool, token: int) -> None:
        """Lance le rendu asynchrone du graphique courant.

        Args:
            update_ui (bool): Indique s'il faut afficher l'état de chargement.
            token (int): Jeton de génération pour ignorer les rendus obsolètes.

        Returns:
            None: Programme le rendu et applique le payload à la fin.
        """
        snapshot = self._chart_render_snapshot()
        _, _, render_key = self._build_render_key_from_snapshot(snapshot)
        if self._try_apply_chart_from_cache(render_key, update_ui=update_ui):
            return
        stale_shown = False
        if self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS or self._is_usa_corridor_mode():
            stale_shown = self._try_show_stale_corridor_chart(update_ui=update_ui)
        if update_ui and not stale_shown:
            self.loader.visible = True
            self.chart_busy_icon.visible = True
            self.chart_busy_text.visible = True
            self.status_text.value = ""
            self.page.update()

        async def _runner() -> None:
            loop = asyncio.get_running_loop()
            payload = await loop.run_in_executor(
                self._chart_executor,
                lambda snap=snapshot: self._compute_chart_payload(snapshot=snap),
            )
            if token != self._chart_render_gen:
                return
            self._apply_chart_payload(payload, update_ui=update_ui)

        self.page.run_task(_runner)

    def _refresh_corridor_swimmer_ui_from_labels(self, labels_all: List[str]) -> None:
        """Met à jour panneau de recherche, dropdown et sélection (France = USA)."""
        self._set_corridor_swimmer_labels_all(labels_all)
        query = (self.corridor_swimmer_search_query or "").strip()
        if self.corridor_swimmer_search is not None:
            self.corridor_swimmer_search.clear_suggestions()
        self._apply_corridor_swimmer_pick()
        labels, shown = self._filter_corridor_swimmer_labels_with_count(
            labels_all, query
        )
        cap_dd = CORRIDOR_SWIMMER_DROPDOWN_OPTIONS_MAX
        dd_labels = labels[:cap_dd]
        pick = self._corridor_swimmer_dropdown_value(labels_all, has_query=bool(query))
        labels_set = self._corridor_swimmer_labels_set or set()
        if pick and pick not in dd_labels and pick in labels_set:
            self.corridor_swimmer_dd.options = [
                ft.dropdown.Option(label) for label in ([pick] + dd_labels)[:cap_dd]
            ]
            dd_labels = ([pick] + dd_labels)[:cap_dd]
        self._sync_dropdown(
            self.corridor_swimmer_dd,
            new_option_keys=tuple(dd_labels),
            build_options=lambda dl=dd_labels: [ft.dropdown.Option(l) for l in dl],
            value=pick,
            visible=not self._active_corridor_swimmer_search(query),
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
        scope = self._corridor_swimmer_dropdown_scope_label()
        self.corridor_swimmer_dd.label = (
            f"Nageur cible ({scope}) — {total} disponibles{suffix}"
        )
        search_norm = _normalize_text(query)
        self._corridor_dd_options_event_key = (
            self._corridor_swimmer_autocomplete_event_key() + (search_norm,)
        )
        self._refresh_moroccan_corridor_swimmer_dropdown()
        self._sync_corridor_confirm_button()
        if self._active_corridor_swimmer_search(query):
            self._push_corridor_search_results_to_bar(labels_all)
        elif self.corridor_swimmer_search is not None:
            self.corridor_swimmer_search.clear_search_results()

    def _refresh_usa_corridor_swimmer_ui_from_labels(self, labels_all: List[str]) -> None:
        self._refresh_corridor_swimmer_ui_from_labels(labels_all)

    def _refresh_filters_usa_corridor(
        self,
        update_ui: bool = True,
        *,
        skip_swimmer_options: bool = False,
        skip_usa_events: bool = False,
    ) -> None:
        """Filtres couloir USA Swimming (épreuve + nageur, sans stroke/distance/bassin Extranat)."""
        dirty = False
        if skip_usa_events:
            events: List[str] = list(self._usa_events_cache or [])
        else:
            events = self._ensure_usa_events_loaded()
            if not events:
                if self.status_text.value != "Cache Parquet USA Swimming introuvable.":
                    self.status_text.value = "Cache Parquet USA Swimming introuvable."
                    dirty = True
            elif self.selected_usa_event not in events:
                self.selected_usa_event = events[0]

        if skip_usa_events:
            waiting_event_label = "Épreuve (USA Swimming) — chargement..."
            if self.usa_event_dd.label != waiting_event_label:
                self.usa_event_dd.label = waiting_event_label
                dirty = True
            if self._sync_dropdown(
                self.usa_event_dd,
                new_option_keys=tuple(),
                build_options=lambda: [],
                value=None,
                visible=True,
            ):
                dirty = True
        else:
            if self.usa_event_dd.label != "Épreuve (USA Swimming)":
                self.usa_event_dd.label = "Épreuve (USA Swimming)"
                dirty = True
            event_keys = tuple(str(e) for e in events)
            if self._sync_dropdown(
                self.usa_event_dd,
                new_option_keys=event_keys,
                build_options=lambda ev=events: [ft.dropdown.Option(e) for e in ev],
                value=self.selected_usa_event,
                visible=True,
            ):
                dirty = True

        for dd, visible in (
            (self.stroke_dd, False),
            (self.distance_dd, False),
            (self.pool_dd, False),
            (self.event_counts_sort_dd, False),
        ):
            if self._sync_dropdown(
                dd,
                new_option_keys=tuple(),
                build_options=lambda: [],
                value=None,
                visible=visible,
            ):
                dirty = True

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

        if self.corridor_mode_switch.visible is not False:
            self.corridor_mode_switch.visible = False
            dirty = True

        if self.corridor_swimmer_search_container.visible is not True:
            self.corridor_swimmer_search_container.visible = True
            dirty = True
        usa_search_label, usa_search_tooltip = self._corridor_swimmer_search_labels()
        if self.corridor_swimmer_search_label.value != usa_search_label:
            self.corridor_swimmer_search_label.value = usa_search_label
            dirty = True
        if self.corridor_swimmer_search_tf.tooltip != usa_search_tooltip:
            self.corridor_swimmer_search_tf.tooltip = usa_search_tooltip
            dirty = True
        if self.corridor_swimmer_search is not None:
            if self.corridor_swimmer_search.sync_value_to_query():
                dirty = True

        if self.selected_usa_event:
            if skip_swimmer_options:
                self._set_corridor_swimmer_labels_all([])
                if self.corridor_swimmer_search is not None:
                    if self.corridor_swimmer_search.clear_suggestions():
                        dirty = True
                waiting_label = "Nageur cible (USA) — chargement..."
                if self.corridor_swimmer_dd.label != waiting_label:
                    self.corridor_swimmer_dd.label = waiting_label
                    dirty = True
                if self.corridor_swimmer_dd.menu_height != self._menu_height_for_count(1):
                    self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(1)
                    dirty = True
                if self.corridor_swimmer_dd.visible is not True:
                    self.corridor_swimmer_dd.visible = True
                    dirty = True
            else:
                labels_all = self._usa_swimmer_names_for_event(self.selected_usa_event)
                self._refresh_usa_corridor_swimmer_ui_from_labels(labels_all)
                dirty = True

        if self._refresh_moroccan_corridor_swimmer_dropdown():
            dirty = True
        if self._sync_corridor_confirm_button():
            dirty = True
        if self._sync_moroccan_corridor_confirm_button():
            dirty = True

        self._sync_corridor_mode_switch(update_ui=False)
        if update_ui:
            self.page.update()

    def _apply_corridor_scope_defaults(
        self,
        combos: Dict[str, Dict[int, List[str]]],
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """Applique des filtres par défaut adaptés aux graphiques couloir.

        Privilégie nage libre, distance 100 m et bassin SCM lorsque disponibles,
        afin d'afficher dès la première ouverture un couloir âge×temps lisible.

        Args:
            combos (Dict[str, Dict[int, List[str]]]): Combinaisons nage/distance/bassin.
            stroke (Optional[str]): Nage courante.
            distance (Optional[int]): Distance courante.
            pool (Optional[str]): Bassin courant.

        Returns:
            Tuple[Optional[str], Optional[int], Optional[str]]: Filtres effectifs.
        """
        stroke_vals = sorted(
            combos.keys(),
            key=lambda s: stroke_code_to_label(str(s)),
        )
        if not stroke_vals:
            return stroke, distance, pool
        if stroke not in stroke_vals:
            stroke = _pick_preferred_corridor_stroke(stroke_vals)

        dist_vals = [int(d) for d in combos.get(stroke or "", {}).keys()]
        if not dist_vals:
            return stroke, distance, pool
        if distance not in dist_vals:
            distance = _pick_preferred_corridor_distance(dist_vals)

        pool_vals = list(
            combos.get(stroke or "", {}).get(int(distance) if distance is not None else -1, [])
        )
        if not pool_vals:
            return stroke, distance, pool
        if pool not in pool_vals:
            pool = "SCM" if "SCM" in pool_vals else str(pool_vals[0])
        return stroke, distance, pool

    def _refresh_filters_from_data(
        self,
        update_ui: bool = True,
        *,
        skip_corridor_swimmer_options: bool = False,
        skip_usa_swimmer_options: bool = False,
        skip_usa_events: bool = False,
    ) -> None:
        """Met à jour les listes d'options des filtres en fonction du graphique choisi."""
        dirty = False
        in_corridor = self.selected_category == CORRIDOR_CATEGORY

        if not in_corridor and self.selected_country != COUNTRY_FRANCE:
            self.selected_country = COUNTRY_FRANCE
            self.country_dd.value = COUNTRY_FRANCE

        if self.country_dd.visible is not in_corridor:
            self.country_dd.visible = in_corridor
            dirty = True

        cat_vals = self._available_categories_for_country()
        if self.selected_category not in cat_vals:
            self.selected_category = cat_vals[0]
        if self._sync_dropdown(
            self.category_dd,
            new_option_keys=tuple(cat_vals),
            build_options=lambda cv=cat_vals: [ft.dropdown.Option(c) for c in cv],
            value=self.selected_category,
            visible=True,
        ):
            dirty = True

        graphs = self._available_graphs_for_category(self.selected_category)
        if self.selected_graph not in graphs:
            if not (
                in_corridor
                and self.selected_graph
                in (
                    CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
                    CORRIDOR_GLOBAL_GRAPH_NAME,
                )
            ):
                self.selected_graph = graphs[0] if graphs else self.selected_graph
        graph_keys = tuple(graphs)
        graph_dd_value = (
            self.selected_graph
            if self.selected_graph in graphs
            else (graphs[0] if graphs else self.selected_graph)
        )
        if self._sync_dropdown(
            self.graph_dd,
            new_option_keys=graph_keys,
            build_options=lambda gv=graphs: [ft.dropdown.Option(g) for g in gv],
            value=graph_dd_value,
            visible=True,
        ):
            dirty = True

        if self._is_usa_corridor_mode():
            self._refresh_filters_usa_corridor(
                update_ui=update_ui,
                skip_swimmer_options=skip_usa_swimmer_options,
                skip_usa_events=skip_usa_events,
            )
            return

        if self.usa_event_dd.visible is not False:
            self.usa_event_dd.visible = False
            dirty = True

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
                df_scope_mem = self._get_cached_scope_performances(
                    graph_name=self.selected_graph,
                    stroke=self.selected_stroke,
                    distance=self.selected_distance,
                    pool=self.selected_pool,
                )
            return df_scope_mem

        if self.selected_graph in SCOPE_NO_FILTER_GRAPHS:
            combos: Dict[str, Dict[int, List[str]]] = {}
        elif self.selected_graph in SCOPE_GENDER_FILTER_GRAPHS:
            combos = {}
        else:
            nav_id = id(df_nav)
            use_swimmers_file_for_triplet = (
                self.selected_graph not in SCOPE_NO_STROKE_GRAPHS
                and self.selected_graph not in SCOPE_POOL_ONLY_GRAPHS
                and self.selected_graph not in SCOPE_POOL_STROKE_GRAPHS
                and self.selected_graph not in SCOPE_STROKE_ONLY_GRAPHS
                and bool(self._event_swimmers_cache)
                and not (
                    self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
                    and not self._is_usa_corridor_mode()
                )
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

        if in_corridor and combos:
            stroke, distance, pool = self._apply_corridor_scope_defaults(
                combos,
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
            )
            self.selected_stroke = stroke
            self.selected_distance = distance
            self.selected_pool = pool

        # Options de nage (libellés français, clés internes inchangées)
        stroke_vals = sorted(
            combos.keys(),
            key=lambda s: stroke_code_to_label(str(s)),
        )
        if self.selected_stroke not in stroke_vals:
            self.selected_stroke = (
                _pick_preferred_corridor_stroke(stroke_vals)
                if in_corridor
                else (stroke_vals[0] if stroke_vals else None)
            )
        stroke_keys = tuple(str(s) for s in stroke_vals)
        if self._sync_dropdown(
            self.stroke_dd,
            new_option_keys=stroke_keys,
            build_options=lambda sv=stroke_vals: [
                ft.dropdown.Option(key=str(s), text=stroke_code_to_label(str(s)))
                for s in sv
            ],
            value=self.selected_stroke,
            visible=self.selected_graph
            not in (
                SCOPE_NO_FILTER_GRAPHS
                | SCOPE_GENDER_FILTER_GRAPHS
                | SCOPE_POOL_ONLY_GRAPHS
                | SCOPE_NO_STROKE_GRAPHS
            ),
        ):
            dirty = True

        hide_distance_for_graph = (
            SCOPE_NO_FILTER_GRAPHS
            | SCOPE_GENDER_FILTER_GRAPHS
            | SCOPE_POOL_ONLY_GRAPHS
            | SCOPE_POOL_STROKE_GRAPHS
            | SCOPE_STROKE_ONLY_GRAPHS
        )
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
            self.selected_distance = (
                _pick_preferred_corridor_distance([int(d) for d in dist_vals])
                if in_corridor
                else (dist_vals[0] if dist_vals else None)
            )
        dist_keys = tuple(str(d) for d in dist_vals)
        dist_value = (
            str(self.selected_distance) if self.selected_distance is not None else None
        )
        if self._sync_dropdown(
            self.distance_dd,
            new_option_keys=dist_keys,
            build_options=lambda dv=dist_vals: [ft.dropdown.Option(str(d)) for d in dv],
            value=dist_value,
            visible=self.selected_graph not in hide_distance_for_graph,
        ):
            dirty = True

        if self.selected_graph in SCOPE_POOL_STROKE_GRAPHS:
            if self.selected_stroke:
                smask = df_nav["Stroke"] == self.selected_stroke
                pool_vals = sorted(df_nav.loc[smask, "Course"].dropna().unique().tolist())
            else:
                pool_vals = []
        elif self.selected_graph in SCOPE_POOL_ONLY_GRAPHS:
            pool_vals = sorted(df_nav["Course"].dropna().unique().tolist())
        elif self.selected_graph in SCOPE_GENDER_FILTER_GRAPHS:
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
            if in_corridor and pool_vals:
                self.selected_pool = (
                    "SCM" if "SCM" in pool_vals else str(pool_vals[0])
                )
            else:
                self.selected_pool = pool_vals[0] if pool_vals else None
        pool_keys = tuple(str(p) for p in pool_vals)
        if self._sync_dropdown(
            self.pool_dd,
            new_option_keys=pool_keys,
            build_options=lambda pv=pool_vals: [
                ft.dropdown.Option(key=str(p), text=str(p)) for p in pv
            ],
            value=self.selected_pool,
            visible=self.selected_graph
            not in (SCOPE_NO_FILTER_GRAPHS | SCOPE_STROKE_ONLY_GRAPHS),
        ):
            dirty = True

        sort_keys = tuple(EVENT_COUNTS_SORT_OPTIONS.keys())
        if self.selected_event_counts_sort not in EVENT_COUNTS_SORT_OPTIONS:
            self.selected_event_counts_sort = EVENT_COUNTS_SORT_STROKE_DISTANCE
        if self._sync_dropdown(
            self.event_counts_sort_dd,
            new_option_keys=sort_keys,
            build_options=lambda: [
                ft.dropdown.Option(key=key, text=label)
                for key, label in EVENT_COUNTS_SORT_OPTIONS.items()
            ],
            value=self.selected_event_counts_sort,
            visible=self.selected_graph in SCOPE_EVENT_COUNTS_GRAPHS,
        ):
            dirty = True

        # Options spécifiques pour heatmap (recherche nageur)
        if self.selected_graph == HEATMAP_GRAPH_NAME:
            labels_all = self._heatmap_swimmer_labels_for_search()
            labels_set = self._heatmap_swimmer_labels_set
            if labels_set is None and labels_all:
                self._ensure_heatmap_swimmer_search_index(labels_all)
                labels_set = self._heatmap_swimmer_labels_set or set()
            if labels_all:
                if (
                    not self.selected_heatmap_swimmer
                    or self.selected_heatmap_swimmer not in labels_set
                ):
                    registry_names = self._swimmer_names_from_corridor_registry()
                    picked: Optional[str] = None
                    for name in registry_names:
                        if name in labels_set:
                            picked = name
                            break
                    if picked is None:
                        picked = labels_all[0]
                    self.selected_heatmap_swimmer = picked
                if (
                    self.selected_heatmap_swimmer
                    and not (self.heatmap_swimmer_search_query or "").strip()
                ):
                    self._set_heatmap_swimmer_search_query(
                        self.selected_heatmap_swimmer
                    )
            else:
                self.selected_heatmap_swimmer = None
            self._refresh_heatmap_swimmer_ui_from_labels(labels_all)
            if self.heatmap_swimmer_search_container.visible is not True:
                self.heatmap_swimmer_search_container.visible = True
                dirty = True
            if self._sync_dropdown(
                self.heatmap_swimmer_dd,
                new_option_keys=tuple(),
                build_options=lambda: [],
                value=None,
                visible=False,
            ):
                dirty = True
        else:
            if self.heatmap_swimmer_search is not None:
                if self.heatmap_swimmer_search.reset(clear_query=True):
                    dirty = True
            if self.heatmap_swimmer_search_container.visible is not False:
                self.heatmap_swimmer_search_container.visible = False
                dirty = True
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
            if (
                in_corridor
                and not self._is_usa_corridor_mode()
                and self.corridor_mode_switch.visible is not True
            ):
                self.corridor_mode_switch.visible = True
                dirty = True
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
                self.corridor_deciles_confirmed_name = None
                self.corridor_deciles_confirmed_yob = None
                self.corridor_fr_confirmed_name = None
                self.corridor_fr_confirmed_yob = None
                self._corridor_dd_options_event_key = None
                self._invalidate_moroccan_corridor_swimmer_label_cache()
                self._clear_corridor_swimmer_labels_cache()
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
            search_label, search_tooltip = self._corridor_swimmer_search_labels()
            if self.corridor_swimmer_search_label.value != search_label:
                self.corridor_swimmer_search_label.value = search_label
                dirty = True
            if self.corridor_swimmer_search_tf.tooltip != search_tooltip:
                self.corridor_swimmer_search_tf.tooltip = search_tooltip
                dirty = True
            if self.corridor_swimmer_search is not None:
                if self.corridor_swimmer_search.sync_value_to_query():
                    dirty = True
            scope_label = self._corridor_swimmer_dropdown_scope_label()
            if skip_corridor_swimmer_options:
                self._clear_corridor_swimmer_labels_cache()
                if self.corridor_swimmer_dd.visible is not True:
                    self.corridor_swimmer_dd.visible = True
                    dirty = True
                waiting_label = f"Nageur cible ({scope_label}) — chargement..."
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
                labels_all = self._corridor_swimmer_labels_for_current_scope()
                self._refresh_corridor_swimmer_ui_from_labels(labels_all)
                dirty = True
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
                zl = f"Nageur cible ({scope_label}) — 0 disponible"
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
                self.corridor_deciles_confirmed_name = None
                self.corridor_deciles_confirmed_yob = None
            if self._refresh_moroccan_corridor_swimmer_dropdown():
                dirty = True
            if self._sync_corridor_confirm_button():
                dirty = True
            if self._sync_moroccan_corridor_confirm_button():
                dirty = True
        else:
            gender_filter_visible = self.selected_graph in SCOPE_GENDER_FILTER_GRAPHS
            if self._sync_dropdown(
                self.corridor_gender_dd,
                new_option_keys=("all", "F", "M"),
                build_options=lambda: [
                    ft.dropdown.Option(key="all", text="Tous"),
                    ft.dropdown.Option(key="F", text="Femme"),
                    ft.dropdown.Option(key="M", text="Homme"),
                ],
                value=self.selected_corridor_gender if gender_filter_visible else "all",
                visible=gender_filter_visible,
            ):
                dirty = True
            if not gender_filter_visible:
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
            if self._sync_dropdown(
                self.corridor_moroccan_swimmer_dd,
                new_option_keys=tuple(),
                build_options=lambda: [],
                value=None,
                visible=False,
            ):
                dirty = True
            self._clear_moroccan_corridor_swimmer_selection()
            if self.corridor_swimmer_dd.label != "Nageur cible (couloir de perf.)":
                self.corridor_swimmer_dd.label = "Nageur cible (couloir de perf.)"
                dirty = True
            if self.corridor_swimmer_search_container.visible is not False:
                self.corridor_swimmer_search_container.visible = False
                dirty = True
            if self.moroccan_corridor_swimmer_search_container.visible is not False:
                self.moroccan_corridor_swimmer_search_container.visible = False
                dirty = True
            if self.corridor_swimmer_search is not None:
                if self.corridor_swimmer_search.sync_trailing(
                    busy=False, confirm_available=False
                ):
                    dirty = True
            if self.moroccan_corridor_swimmer_search is not None:
                if self.moroccan_corridor_swimmer_search.sync_trailing(
                    busy=False, confirm_available=False
                ):
                    dirty = True
            self.selected_corridor_swimmer_name = None
            self.selected_corridor_swimmer_yob = None
            self.corridor_deciles_confirmed_name = None
            self.corridor_deciles_confirmed_yob = None

        # Option spécifique pacing comparatif (nageur cible)
        if self.selected_graph == "Vitesse de split - F vs M + nageurs cibles":
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

            self._is_syncing_pacing_dropdowns = True
            try:
                for dd, val in (
                    (self.pacing_swimmer_dd_1, current[0]),
                    (self.pacing_swimmer_dd_2, current[1]),
                    (self.pacing_swimmer_dd_3, current[2]),
                ):
                    if dd.value != val:
                        dd.value = val
                        dirty = True
            finally:
                self._is_syncing_pacing_dropdowns = False

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
        if self.selected_graph == GRAPH_CHRONOS_PAR_NAGE:
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
        self._sync_corridor_mode_switch(update_ui=False)

        # Toujours pousser l’UI après un changement de filtres : Flet peut laisser les
        # dropdowns dépendants visuellement bloqués si on omet page.update() lorsque
        # dirty est resté False (options « identiques » sur la forme, etc.).
        if update_ui:
            self.page.update()

    def _update_chart(self, update_ui: bool = True) -> None:
        self._chart_render_gen += 1
        token = self._chart_render_gen
        self._begin_chart_render(update_ui=update_ui, token=token)


def main(page: ft.Page) -> None:
    """Point d'entrée Flet : instancie ``PacingDesktopApp`` sur la page fournie.

    Args:
        page (ft.Page): Page créée par ``ft.run``.

    Returns:
        None
    """
    PacingDesktopApp(page)


if __name__ == "__main__":
    ft.run(main)

