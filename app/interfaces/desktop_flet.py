import base64
import datetime as dt
import io
import json
import re
import sys
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import flet as ft
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import to_hex

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from services.graph_service import (
    GRAPHES_NOTEBOOK,
    SERVICE_NOTEBOOK_JSON_CATEGORY,
    GraphSpec,
    ServiceGraphe,
    notebook_prefetch_kwargs_for_spec,
    unwrap_matplotlib_figure,
)

APP_DIR = PROJECT_DIR / "app"
EXTRANAT_OUTPUT_BASE_DIR = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "extranat"
    / "competitions_per_type"
)


GRAPH_CATEGORIES: Dict[str, List[str]] = {
    "Distributions de temps": [
        "Histogramme simple",
        "Histogramme + densité",
        "Histogramme cumulatif",
    ],
    "Effectifs et répartition par sexe": [
        "Nombre de performances par épreuve",
        "Nombre de performances par épreuve (LCM + SCM)",
        "Comptage par sexe (global)",
        "Camembert par sexe (global)",
        "Camembert par sexe (épreuve)",
    ],
    "Comparaison des temps par nage": [
        "Distribution des temps par type de nage (boxplot)",
    ],
    "Clubs": [
        "Top 10 clubs par participation (épreuve)",
        "Temps médian des 10 meilleurs clubs",
    ],
    "Chronos dans le temps": [
        "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000",
    ],
    "Vitesse globale": [
        "Swimming Speed by Distance and Stroke Type",
        "Max Speed per Split Distance and Stroke",
    ],
    "Pacing comparatif": [
        "Split speed - F vs M + nageurs cibles",
    ],
    "Synthèse des vitesses par distance et nage": [
        "Heatmap vitesse moyenne (distance x nage)",
    ],
    "Évolution de la vitesse par splits": [
        "Lineplot of Speed ​​per split for a precise Swimmer and Event",
        "Lineplot of split speed for the best swimmer for a specific event",
        "Lineplot of split speed for the best swimmers for a specific event (women vs men)",
        "Line plot of Split Speed Progression of Top 10 Swimmers in a given Event (Women vs Men)",
    ],
    "Comparaisons de pacing par splits (à partir de la médiane)": [
        "Temps médian vs meilleur nageur",
        "Temps médian vs Top 10 nageurs",
        "Vitesse médiane par split selon le genre",
    ],
    "Pacing en relais": [
        "Split Speed vs Distance (Relay Events) with Mean Trend Line",
    ],
    "Couloirs de performance": [
        "Couloir de performance (âge) - nageur cible",
    ],
}

GRAPH_EXPORT_PATH = PROJECT_DIR / "data" / "exports" / "prefetched_graphs.json"
ENABLE_STARTUP_WARMUP = False
# Métadonnées + image PNG (base64) dans ``prefetched_graphs.json`` pour réaffichage sans régénérer la figure.
EXPORT_IMAGE_BASE64_TO_JSON = True
# True : charge / enregistre les rendus dans ``GRAPH_EXPORT_PATH`` (cache disque + mémoire).
ENABLE_PERSISTENT_GRAPH_CACHE = True
# Avec le cache persistant, les graphes doivent être stockés avec leur image pour être réutilisables.
if ENABLE_PERSISTENT_GRAPH_CACHE:
    EXPORT_IMAGE_BASE64_TO_JSON = True
# Précharge ``GRAPHES_NOTEBOOK`` au démarrage : saute si la clé existe déjà dans prefetched_graphs.json.
ENABLE_NOTEBOOK_PREFETCH_ON_START = True
# DPI d'export PNG : plus bas = encodage plus rapide et JSON plus léger (lisibilité OK à l'écran).
CHART_PNG_DPI = 96
# Regroupe les écritures sur disque après navigation rapide entre graphes (secondes).
GRAPH_REGISTRY_DEBOUNCE_S = 0.45


def build_graph_definitions() -> List[Dict[str, str]]:
    """
    Construit une liste d'objets décrivant chaque graphe UI:
    - name: nom du graphe
    - group: catégorie (groupe)
    - ui_method: nom de la méthode UI associée
    """
    graph_definitions: List[Dict[str, str]] = []
    for group_name, graph_names in GRAPH_CATEGORIES.items():
        for graph_name in graph_names:
            graph_definitions.append(
                {
                    "name": graph_name,
                    "group": group_name,
                    "ui_method": f"render_{_slugify(graph_name)}",
                }
            )
    return graph_definitions


def _primary_swimmer_name(swimmers: Any) -> Optional[str]:
    if not isinstance(swimmers, list) or len(swimmers) == 0:
        return None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None
    return first.get("Name")


def _primary_swimmer_name_and_yob(
    swimmers: Any,
) -> Tuple[Optional[str], Optional[int]]:
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None, None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None, None
    name = first.get("Name")
    yob = first.get("Year_of_birth")
    yob_int: Optional[int] = None
    try:
        if yob is not None and yob == yob:
            yob_int = int(yob)
    except (TypeError, ValueError):
        yob_int = None
    return name, yob_int


def _pool_label_from_length(value: Any) -> Optional[str]:
    text = str(value).strip()
    if text in {"50", "50.0", "LCM"}:
        return "LCM"
    if text in {"25", "25.0", "SCM"}:
        return "SCM"
    return None


def _pool_display_label(pool_code: Optional[str]) -> str:
    if pool_code == "SCM":
        return "SCM (25 m)"
    if pool_code == "LCM":
        return "LCM (50 m)"
    return str(pool_code) if pool_code is not None else ""


def _normalize_text(value: Any) -> str:
    import unicodedata

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _slugify(text: str) -> str:
    value = _normalize_text(text)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


@lru_cache(maxsize=1)
def load_data() -> pd.DataFrame:
    """Chargement des JSON Extranat avec cache mémoire (équivalent st.cache_data)."""
    rows: List[Dict[str, Any]] = []

    if not EXTRANAT_OUTPUT_BASE_DIR.exists():
        return pd.DataFrame()

    for file in EXTRANAT_OUTPUT_BASE_DIR.rglob("*.json"):
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            continue

        for epreuve in comp.get("epreuves", []):
            for perf in epreuve.get("performances", []):

                swimmers = perf.get("swimmer", [])
                if isinstance(swimmers, dict):
                    swimmers = [swimmers]

                row = {
                    "Meet": comp.get("Meet"),
                    "SwimDate": comp.get("SwimDate"),
                    "Location": comp.get("location"),
                    "Country": comp.get("Country"),
                    "Event": epreuve.get("Event"),
                    "Distance": epreuve.get("Distance"),
                    "Stroke": epreuve.get("Stroke"),
                    "Course": epreuve.get("Course"),
                    "PoolLength": epreuve.get("PoolLength"),
                    "Tour": epreuve.get("tour"),
                    "Rank": perf.get("Rank"),
                    "Club": perf.get("club"),
                    "points": perf.get("points"),
                    "mpp": perf.get("mpp"),
                    "mpp_date": perf.get("mpp_date"),
                    "SwimTime": perf.get("SwimTime"),
                    "SwimTimeSeconds": perf.get("SwimTimeSeconds"),
                    "Status": perf.get("Status"),
                    "Speed": perf.get("Speed"),
                    "swimmer": swimmers,
                    "splits": perf.get("splits", []),
                }
                rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")
    df["Gender"] = df["swimmer"].apply(
        lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
    )
    return df


def _figure_to_base64(fig: plt.Figure) -> str:
    """Convertit une figure matplotlib en chaîne base64 PNG (DPI ``CHART_PNG_DPI``)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=CHART_PNG_DPI)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _build_df_nav(df: pd.DataFrame) -> pd.DataFrame:
    df_nav = df.copy()
    if "PoolLength" in df_nav.columns:
        df_nav["PoolLabel"] = df_nav["PoolLength"].apply(_pool_label_from_length)
    else:
        # Colonne manquante: on crée un label vide pour éviter les KeyError
        df_nav["PoolLabel"] = None
    return df_nav


def _event_combinations(
    df_nav: pd.DataFrame,
) -> Dict[str, Dict[int, List[str]]]:
    """
    Construit les combinaisons valides Stroke -> Distance -> [PoolLabel]
    à partir des données réellement disponibles.
    Utilise ``drop_duplicates`` (pas ``iterrows`` sur tout le jeu) pour rester rapide sur gros volumes.
    """
    combos: Dict[str, Dict[int, set[str]]] = {}
    if df_nav.empty:
        return {}

    cols = ["Stroke", "Distance", "PoolLabel"]
    if not all(c in df_nav.columns for c in cols):
        return {}

    df_tmp = df_nav[cols].dropna(subset=cols)
    if df_tmp.empty:
        return {}

    d_num = pd.to_numeric(df_tmp["Distance"], errors="coerce")
    df_tmp = df_tmp.assign(Distance=d_num)
    df_tmp = df_tmp[df_tmp["Distance"].notna()]
    if df_tmp.empty:
        return {}

    uniq = df_tmp.drop_duplicates(subset=cols)
    strokes = uniq["Stroke"].astype(str).str.strip()
    pools = uniq["PoolLabel"].astype(str).str.strip()
    dists = uniq["Distance"]
    for stroke, distance, pool in zip(strokes, dists, pools):
        if not stroke or not pool:
            continue
        try:
            dist_i = int(distance)
        except (TypeError, ValueError):
            continue
        combos.setdefault(stroke, {}).setdefault(dist_i, set()).add(pool)

    ordered: Dict[str, Dict[int, List[str]]] = {}
    pool_rank = {"SCM": 0, "LCM": 1}
    for stroke in sorted(combos.keys()):
        ordered[stroke] = {}
        for distance in sorted(combos[stroke].keys()):
            pools = sorted(
                combos[stroke][distance],
                key=lambda p: (pool_rank.get(p, 99), p),
            )
            ordered[stroke][distance] = pools
    return ordered


# Jeux de graphes pour le périmètre de données (alignés sur Streamlit / filtres).
_SCOPE_NO_FILTER_GRAPHS = frozenset(
    {
        "Nombre de performances par épreuve (LCM + SCM)",
        "Comptage par sexe (global)",
        "Camembert par sexe (global)",
        "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000",
        "Swimming Speed by Distance and Stroke Type",
        "Max Speed per Split Distance and Stroke",
        "Heatmap vitesse moyenne (distance x nage)",
    }
)
_SCOPE_POOL_ONLY_GRAPHS = frozenset({"Nombre de performances par épreuve"})
_SCOPE_NO_STROKE_GRAPHS = frozenset({"Distribution des temps par type de nage (boxplot)"})


def _resolve_scope_filters(
    df_nav: pd.DataFrame,
    selected_graph: str,
    selected_stroke: Optional[str],
    selected_distance: Optional[int],
    selected_pool: Optional[str],
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Choisit stroke / distance / pool pour le graphe courant sans copier ``df_nav``.
    Utilisé pour construire la clé de cache avant toute matérialisation lourde.
    """
    if selected_graph in _SCOPE_NO_FILTER_GRAPHS:
        return None, None, None

    if selected_graph in _SCOPE_POOL_ONLY_GRAPHS:
        pool_options = sorted(df_nav["PoolLabel"].dropna().unique().tolist())
        if not pool_options:
            return None, None, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        return None, None, selected_pool

    if selected_graph in _SCOPE_NO_STROKE_GRAPHS:
        distance_options = sorted(df_nav["Distance"].dropna().unique().tolist())
        if not distance_options:
            return None, None, None
        if selected_distance not in distance_options:
            selected_distance = distance_options[0]
        pool_options = sorted(
            df_nav.loc[
                df_nav["Distance"] == selected_distance,
                "PoolLabel",
            ]
            .dropna()
            .unique()
            .tolist()
        )
        if not pool_options:
            return None, selected_distance, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        return None, selected_distance, selected_pool

    stroke_options = sorted(df_nav["Stroke"].dropna().unique().tolist())
    if not stroke_options:
        return None, None, None
    if selected_stroke not in stroke_options:
        selected_stroke = stroke_options[0]

    stroke_mask = df_nav["Stroke"] == selected_stroke
    distance_options = sorted(df_nav.loc[stroke_mask, "Distance"].dropna().unique().tolist())
    if not distance_options:
        return selected_stroke, None, None
    if selected_distance not in distance_options:
        selected_distance = distance_options[0]

    dist_mask = stroke_mask & (df_nav["Distance"] == selected_distance)
    pool_options = sorted(df_nav.loc[dist_mask, "PoolLabel"].dropna().unique().tolist())
    if not pool_options:
        return selected_stroke, selected_distance, None
    if selected_pool not in pool_options:
        selected_pool = pool_options[0]

    return selected_stroke, selected_distance, selected_pool


def _materialize_df_scope(
    df_nav: pd.DataFrame,
    selected_graph: str,
    stroke: Optional[str],
    distance: Optional[int],
    pool: Optional[str],
) -> pd.DataFrame:
    """Construit ``df_scope`` (copie filtrée) à partir des filtres déjà résolus."""
    if selected_graph in _SCOPE_NO_FILTER_GRAPHS:
        return df_nav.copy()

    if selected_graph in _SCOPE_POOL_ONLY_GRAPHS:
        if pool is None:
            return pd.DataFrame()
        return df_nav[df_nav["PoolLabel"] == pool].copy()

    if selected_graph in _SCOPE_NO_STROKE_GRAPHS:
        if distance is None or pool is None:
            return pd.DataFrame()
        df_distance = df_nav[df_nav["Distance"] == distance].copy()
        return df_distance[df_distance["PoolLabel"] == pool].copy()

    if stroke is None or distance is None or pool is None:
        return pd.DataFrame()
    df_stroke = df_nav[df_nav["Stroke"] == stroke].copy()
    df_distance = df_stroke[df_stroke["Distance"] == distance].copy()
    return df_distance[df_distance["PoolLabel"] == pool].copy()


def _build_scope_and_widgets_data(
    df_nav: pd.DataFrame,
    selected_graph: str,
    selected_stroke: Optional[str],
    selected_distance: Optional[int],
    selected_pool: Optional[str],
) -> Tuple[pd.DataFrame, Optional[str], Optional[int], Optional[str]]:
    """
    Reproduit la logique de filtrage principale de la sidebar Streamlit
    mais sans UI (purement data). Les paramètres déjà sélectionnés sont
    utilisés quand ils ne sont pas None, sinon on prend les premières
    valeurs disponibles dans df_nav.
    """
    stroke, distance, pool = _resolve_scope_filters(
        df_nav,
        selected_graph,
        selected_stroke,
        selected_distance,
        selected_pool,
    )
    df_scope = _materialize_df_scope(df_nav, selected_graph, stroke, distance, pool)
    return df_scope, stroke, distance, pool



class PacingDesktopApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.page.title = "Pacing – Desktop (PyFlet)"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#020617"
        self.page.padding = 0

        self.df: pd.DataFrame = load_data()
        self.total_rows: int = int(self.df.shape[0])
        self.df_nav: pd.DataFrame = _build_df_nav(self.df)

        # Sélections courantes
        self.selected_category: str = list(GRAPH_CATEGORIES.keys())[0]
        self.selected_graph: str = GRAPH_CATEGORIES[self.selected_category][0]
        self.selected_stroke: Optional[str] = None
        self.selected_distance: Optional[int] = None
        self.selected_pool: Optional[str] = None
        self.selected_heatmap_swimmer: Optional[str] = None
        self.selected_corridor_swimmer_name: Optional[str] = None
        self.selected_corridor_swimmer_yob: Optional[int] = None
        self.selected_pacing_swimmers: List[str] = []
        self.selected_chronos_sample_size: int = 5000
        self._last_corridor_filter: Optional[Tuple[Optional[str], Optional[int], Optional[str]]] = None
        self.graph_render_registry: Dict[str, Dict[str, Any]] = {}
        self.chart_image_cache: Dict[str, str] = {}
        self._prefetched_json_mtime: float = 0.0
        self._registry_json_lock = threading.Lock()
        self._registry_json_timer: Optional[threading.Timer] = None
        self._nav_combos_cache_id: Optional[int] = None
        self._nav_combos_cache: Optional[Dict[str, Dict[int, List[str]]]] = None
        self._heatmap_swimmer_names_cache_id: Optional[int] = None
        self._heatmap_swimmer_names_cache: Optional[List[str]] = None
        self.graph_definitions: List[Dict[str, str]] = build_graph_definitions()
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
        self.loader = ft.ProgressRing(visible=False, width=32, height=32, color="#22c55e")

        if ENABLE_PERSISTENT_GRAPH_CACHE:
            self._load_graph_registry_json()

        if ENABLE_NOTEBOOK_PREFETCH_ON_START:
            self._prefetch_service_notebook_graphs_skip_existing()

        self._build_ui()
        if ENABLE_STARTUP_WARMUP:
            self._warmup_graph_registry()
        self._update_chart()

    def _graph_method_name(self, graph_name: str) -> str:
        return f"render_{_slugify(graph_name)}"

    def _chart_id(self, category: str, graph_name: str) -> str:
        return f"{_slugify(category)}__{_slugify(graph_name)}"

    def _build_render_key(
        self,
        category: str,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Tuple[str, Dict[str, Any], str]:
        options = self._current_render_options(stroke, distance, pool)
        chart_id = self._chart_id(category, graph_name)
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

    def _schedule_graph_registry_persist(self) -> None:
        """Enregistre ``prefetched_graphs.json`` après un court délai (évite de bloquer l'UI)."""
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        with self._registry_json_lock:
            if self._registry_json_timer is not None:
                self._registry_json_timer.cancel()
            t = threading.Timer(
                GRAPH_REGISTRY_DEBOUNCE_S,
                self._persist_graph_registry_json_worker,
            )
            t.daemon = True
            self._registry_json_timer = t
            t.start()

    def _persist_graph_registry_json_worker(self) -> None:
        with self._registry_json_lock:
            self._registry_json_timer = None
        try:
            self._write_graph_registry_json()
        except Exception:
            pass

    def _flush_graph_registry_json_now(self) -> None:
        """Annule le timer différé et écrit le JSON immédiatement (warmup, prefetch, etc.)."""
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
        # Copie pour éviter les courses avec le timer d'écriture différée.
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
                self._prefetched_json_mtime = float(GRAPH_EXPORT_PATH.stat().st_mtime)
        except OSError:
            pass

    def _maybe_refresh_graph_registry_from_disk(self, render_key: str) -> None:
        """
        Si le rendu demandé est déjà en mémoire (métadonnées + image), ne pas relire le JSON
        (parse d'un gros fichier = très lent).
        """
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        hit = self.graph_render_registry.get(render_key)
        if isinstance(hit, dict) and hit.get("status") == "ok":
            img = self.chart_image_cache.get(render_key) or hit.get("image_base64")
            if isinstance(img, str) and len(img) > 0:
                if render_key not in self.chart_image_cache:
                    self.chart_image_cache[render_key] = img
                return
        self._refresh_graph_registry_from_disk_if_changed()

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
        if not GRAPH_EXPORT_PATH.exists():
            return
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

            chart_id = self._chart_id(category, name)
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
        """Options JSON alignées sur ``_current_render_options`` + clé stable du notebook."""
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
        chart_id = self._chart_id(SERVICE_NOTEBOOK_JSON_CATEGORY, spec.key)
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
        chart_id = self._chart_id(SERVICE_NOTEBOOK_JSON_CATEGORY, spec.key)
        self.graph_render_registry[render_key] = {
            "id": chart_id,
            "name": spec.key,
            "category": SERVICE_NOTEBOOK_JSON_CATEGORY,
            "method": spec.method_name,
            "status": status,
            "chart_title": chart_title,
            "row_count": int(row_count),
            "warmup": True,
            "error": error,
            "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "options": options,
            "image_base64": image_base64,
        }
        if image_base64:
            self.chart_image_cache[render_key] = image_base64
        if not skip_json_write:
            self._flush_graph_registry_json_now()

    def _prefetch_service_notebook_graphs_skip_existing(self) -> None:
        """Parcourt ``GRAPHES_NOTEBOOK`` : si le rendu est déjà dans le JSON, sinon génère et enregistre."""
        if not ENABLE_PERSISTENT_GRAPH_CACHE:
            return
        if self.df.empty:
            return

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
                continue

            kwargs = notebook_prefetch_kwargs_for_spec(spec, self.df, self.df_nav)
            if kwargs is None:
                continue

            try:
                raw = self.graph_svc.build_figure(spec, self.df, **kwargs)
                fig = unwrap_matplotlib_figure(raw)
            except Exception as exc:  # type: ignore[bare-except]
                self._register_notebook_service_render(
                    spec=spec,
                    render_key=render_key,
                    options=options,
                    chart_title=spec.name,
                    status="error",
                    row_count=len(self.df),
                    image_base64=None,
                    error=str(exc),
                    skip_json_write=True,
                )
                continue

            if fig is None:
                self._register_notebook_service_render(
                    spec=spec,
                    render_key=render_key,
                    options=options,
                    chart_title=spec.name,
                    status="no_figure",
                    row_count=len(self.df),
                    image_base64=None,
                    skip_json_write=True,
                )
                continue

            image_base64 = _figure_to_base64(fig)
            plt.close(fig)
            self._register_notebook_service_render(
                spec=spec,
                render_key=render_key,
                options=options,
                chart_title=spec.name,
                status="ok",
                row_count=len(self.df),
                image_base64=image_base64,
                skip_json_write=True,
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
        warmup: bool,
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
            "method": self._graph_method_name(graph_name),
            "status": status,
            "chart_title": chart_title,
            "row_count": int(row_count),
            "warmup": bool(warmup),
            "error": error,
            "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "options": options,
            "image_base64": image_base64,
        }
        if image_base64:
            self.chart_image_cache[render_key] = image_base64
        if not warmup:
            self._schedule_graph_registry_persist()

    def _warmup_graph_registry(self) -> None:
        if self.df.empty:
            self._flush_graph_registry_json_now()
            return

        saved_state = (
            self.selected_category,
            self.selected_graph,
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            self.selected_heatmap_swimmer,
            self.selected_corridor_swimmer_name,
            self.selected_corridor_swimmer_yob,
            self.selected_pacing_swimmers[:],
            self.selected_chronos_sample_size,
        )

        for category, graphs in GRAPH_CATEGORIES.items():
            self.selected_category = category
            for graph_name in graphs:
                self.selected_graph = graph_name
                self._refresh_filters_from_data(update_ui=False)
                self._update_chart(update_ui=False, warmup=True)

        (
            self.selected_category,
            self.selected_graph,
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            self.selected_heatmap_swimmer,
            self.selected_corridor_swimmer_name,
            self.selected_corridor_swimmer_yob,
            self.selected_pacing_swimmers,
            self.selected_chronos_sample_size,
        ) = saved_state
        self._refresh_filters_from_data(update_ui=False)
        self._flush_graph_registry_json_now()

    # ------------------------------------------------------------------ UI
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
                        padding=ft.padding.only(top=8),
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

    # ------------------------------------------------------------------ Events
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
        # Recalcule les options dépendantes quand Stroke/Distance changent
        # pour éviter de garder une ancienne liste incohérente.
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

    # ------------------------------------------------------------------ Data-driven filters
    @staticmethod
    def _menu_height_for_count(option_count: int) -> int:
        # 56px ~ hauteur visuelle par ligne dans ce thème/material.
        return max(72, min(320, 56 * max(1, option_count)))

    def _refresh_filters_from_data(self, update_ui: bool = True) -> None:
        """Met à jour les listes d'options des filtres en fonction du graphique choisi."""
        df_nav = self.df_nav

        # Résolution légère des filtres ; ``df_scope`` n'est matérialisé que pour couloir / pacing.
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

        # Combinaisons Stroke/Distance/Pool : coûteux sur gros jeux → cache par ``df_nav`` + skip si graphe sans filtres.
        if self.selected_graph in _SCOPE_NO_FILTER_GRAPHS:
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

        # Distance options:
        # - graphes "no stroke": distances globales
        # - sinon: liées au stroke choisi
        if self.selected_graph in _SCOPE_NO_STROKE_GRAPHS:
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

        # Pool options:
        # - graphe "pool only": options globales (SCM/LCM disponibles)
        # - graphes "no stroke": liées à la distance choisie (tous strokes confondus)
        # - sinon: liées au couple stroke+distance choisi
        if self.selected_graph in _SCOPE_POOL_ONLY_GRAPHS:
            pool_vals = sorted(df_nav["PoolLabel"].dropna().unique().tolist())
        elif self.selected_graph in _SCOPE_NO_STROKE_GRAPHS:
            if self.selected_distance is not None:
                dmask = pd.to_numeric(df_nav["Distance"], errors="coerce") == self.selected_distance
                pool_vals = sorted(df_nav.loc[dmask, "PoolLabel"].dropna().unique().tolist())
            else:
                pool_vals = []
        else:
            pool_vals = (
                combos.get(self.selected_stroke, {}).get(self.selected_distance, [])
                if (self.selected_stroke and self.selected_distance is not None)
                else []
            )
        self.pool_dd.options = [
            ft.dropdown.Option(key=p, text=_pool_display_label(p)) for p in pool_vals
        ]
        self.pool_dd.menu_height = self._menu_height_for_count(len(pool_vals))
        if self.selected_pool not in pool_vals:
            self.selected_pool = pool_vals[0] if pool_vals else None
        self.pool_dd.value = self.selected_pool

        # Affichage conditionnel des filtres principaux selon le graphe
        if self.selected_graph in _SCOPE_NO_FILTER_GRAPHS:
            self.stroke_dd.visible = False
            self.distance_dd.visible = False
            self.pool_dd.visible = False
        elif self.selected_graph in _SCOPE_POOL_ONLY_GRAPHS:
            self.stroke_dd.visible = False
            self.distance_dd.visible = False
            self.pool_dd.visible = True
        elif self.selected_graph in _SCOPE_NO_STROKE_GRAPHS:
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

    # ------------------------------------------------------------------ Chart rendering
    def _update_chart(self, update_ui: bool = True, warmup: bool = False) -> None:
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
            self._maybe_refresh_graph_registry_from_disk(render_key)
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
                    warmup=warmup,
                )
                return

            df_filtered = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
            fig: Optional[plt.Figure] = None
            chart_title = self.selected_graph

            svc = self.graph_svc

            if self.selected_graph in {
                "Histogramme simple",
                "Histogramme + densité",
                "Histogramme cumulatif",
            }:
                chart_title = "Distribution des temps de nage"
                if not df_filtered.empty:
                    if self.selected_graph == "Histogramme simple":
                        fig = svc.plot_histogramme_simple(df_filtered)
                    elif self.selected_graph == "Histogramme + densité":
                        fig = svc.plot_histogramme_densite(df_filtered)
                    else:
                        fig = svc.plot_histogramme_cumulatif(df_filtered)

            elif self.selected_graph == "Nombre de performances par épreuve":
                if pool:
                    chart_title = f"Nombre de performances par épreuve ({pool})"
                    fig = svc.plot_nombre_performances_par_epreuve(
                        df_scope, course_type=str(pool)
                    )

            elif self.selected_graph == "Nombre de performances par épreuve (LCM + SCM)":
                chart_title = "Nombre de performances par épreuve (LCM + SCM)"
                fig = svc.plot_nombre_performances_par_epreuve_lcm_scm(df_scope)

            elif self.selected_graph in {"Comptage par sexe (global)", "Comptage par sexe (épreuve)"}:
                chart_title = (
                    "Nombre de performances par sexe – global"
                    if self.selected_graph == "Comptage par sexe (global)"
                    else "Nombre de performances par sexe – filtres actuels"
                )
                fig = svc.plot_nombre_performances_par_sexe(df_filtered)

            elif self.selected_graph == "Camembert par sexe (global)":
                chart_title = "Répartition des performances par sexe – global"
                fig = svc.plot_camembert_sexe_global(df_filtered)

            elif self.selected_graph == "Camembert par sexe (épreuve)":
                chart_title = "Répartition des performances par sexe – filtres actuels"
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    fig = svc.plot_camembert_sexe_par_event(df_filtered, nom_event=nom_event)

            elif self.selected_graph == "Distribution des temps par type de nage (boxplot)":
                try:
                    distance_label = (
                        str(int(float(self.selected_distance)))
                        if self.selected_distance is not None
                        else ""
                    )
                except (TypeError, ValueError):
                    distance_label = str(self.selected_distance)
                chart_title = (
                    f"Distribution des temps par type de nage pour la distance {distance_label} m"
                )
                fig = svc.plot_boxplot_temps_par_nage(df_scope)

            elif self.selected_graph == "Top 10 clubs par participation (épreuve)":
                chart_title = "Top 10 des clubs par nombre de participations – filtres actuels"
                fig = svc.plot_top10_clubs(df_scope)

            elif self.selected_graph == "Temps médian des 10 meilleurs clubs":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = f"Temps médian des 10 meilleurs clubs - {nom_event}"
                    fig, _meta = svc.plot_temps_median_top10_clubs_par_event(
                        df_scope, nom_event=nom_event
                    )

            elif self.selected_graph == "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000":
                chart_title = "Évolution des temps de nage dans le temps (à partir de 2000)"
                fig = svc.plot_evolution_temps_nage(
                    self.df,
                    start_year=2000,
                    sample_size=max(0, int(self.selected_chronos_sample_size)),
                )

            elif self.selected_graph == "Swimming Speed by Distance and Stroke Type":
                chart_title = "Swimming Speed by Distance and Stroke Type"
                fig = svc.plot_swimming_speed_by_distance_and_stroke(df_scope)

            elif self.selected_graph == "Max Speed per Split Distance and Stroke":
                chart_title = "Max Speed per Split Distance and Stroke"
                fig, _dfm = svc.plot_vitesse_max_par_split_et_nage(df_scope)

            elif self.selected_graph == "Split speed - F vs M + nageurs cibles":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = f"{nom_event} - split_speed - F vs M + nageurs cibles"
                    pacing = self.selected_pacing_swimmers[:3]
                    target_colors: Dict[str, str] = {}
                    if pacing:
                        pal = sns.color_palette("Dark2", n_colors=len(pacing))
                        target_colors = {n: to_hex(c) for n, c in zip(pacing, pal)}
                    fig, _a, _b, _meta = svc.plot_split_speed_analysis_by_gender_with_targets(
                        df_scope,
                        nom_event=nom_event,
                        swimmer_targets=list(pacing),
                        target_colors=target_colors,
                    )

            elif self.selected_graph == "Temps médian vs meilleur nageur":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = f"Temps médian vs meilleur nageur - Event {nom_event}"
                    fig, _a, _b, meta = svc.plot_temps_median_vs_meilleur_nageur_par_split_event(
                        df_scope, nom_event=nom_event
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err and err != "ok":
                            chart_title = err

            elif self.selected_graph == "Temps médian vs Top 10 nageurs":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = f"Temps médian vs Top 10 nageurs - Event {nom_event}"
                    fig, _a, _b, meta = svc.plot_temps_median_vs_top10_nageurs_par_split_event(
                        df_scope, nom_event=nom_event
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err and err != "ok":
                            chart_title = err

            elif self.selected_graph == "Vitesse médiane par split selon le genre":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = f"Vitesse médiane par split selon le genre - {nom_event}"
                    fig, _med, meta = svc.plot_vitesse_mediane_par_split_selon_genre_top_n_event(
                        df_scope, nom_event=nom_event, top_n=10
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err and err != "ok":
                            chart_title = err

            elif self.selected_graph == "Heatmap vitesse moyenne (distance x nage)":
                chart_title = "Synthèse des vitesses – heatmap comparative"
                if self.selected_heatmap_swimmer:
                    fig, meta = svc.plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres(
                        df_scope,
                        nageur_cible=self.selected_heatmap_swimmer,
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err:
                            chart_title = err

            elif self.selected_graph == "Couloir de performance (âge) - nageur cible":
                if (
                    distance
                    and stroke
                    and pool
                    and self.selected_corridor_swimmer_name
                    and self.selected_corridor_swimmer_yob is not None
                ):
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = f"Couloir de performance - {nom_event}"
                    fig, meta = svc.plot_performance_corridor_plot_time(
                        df_scope,
                        nom_event=nom_event,
                        nom_nageur=self.selected_corridor_swimmer_name,
                        year_of_birth=int(self.selected_corridor_swimmer_yob),
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err:
                            chart_title = err

            elif self.selected_graph == "Split Speed vs Distance (Relay Events) with Mean Trend Line":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = (
                        f"{nom_event} — relais uniquement — split_speed en fonction de la distance"
                    )
                    fig, _p, _m, _md, meta = svc.plot_relais_split_speed_par_distance(
                        df_scope, nom_event=nom_event
                    )
                    if fig is None and isinstance(meta, dict):
                        err = str(meta.get("message", ""))
                        if err:
                            chart_title = err

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
                    warmup=warmup,
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
                    warmup=warmup,
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
                warmup=warmup,
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

