"""Façade application desktop : métier + rendu, sans Flet.

``PacingAppService`` est le seul point d'entrée métier pour l'UI desktop.
Il encapsule loaders, ``ServiceGraphe``, ``corridor_data`` et l'export PNG.
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd

from pacing.analytics.corridor_data import (
    CORRIDOR_CHART_STYLE_VERSION,
    CORRIDOR_FR_SWIMMER_COLOR,
    CORRIDOR_MA_SWIMMER_COLOR,
)
from pacing.application.build_corridor_chart import BuildCorridorChart
from pacing.application.graph_service import (
    EVENT_COUNTS_SORT_STROKE_DISTANCE,
    GRAPH_CATEGORIES,
    GRAPHES_NOTEBOOK,
    GRAPHES_PAR_KEY,
    ServiceGraphe,
    unwrap_matplotlib_figure,
)
from pacing.application.prefetch_graphs import PrefetchGraphs
from pacing.application.scope import materialize_df_scope, resolve_scope_filters
from pacing.config.paths import (
    EXTRANAT_PROCESSED_DIR,
    FRMNATATION_PROCESSED_DIR,
    USASWIMMING_PARQUET_DIR,
    USASWIMMING_PROCESSED_DIR,
)
from pacing.data.frmnatation_loader import (
    DEFAULT_FRMNATATION_HTML_RESULTS_DIR,
    FrmnatationHtmlResultsDataLoader,
)
from pacing.data.usaswimming_loader import UsaswimmingCompetitionsDataLoader
from pacing.domain.normalize import normalize_gender_code

# Constantes partagées (évite les imports circulaires avec l'UI desktop)
COUNTRY_FRANCE = "France"
COUNTRY_MOROCCO = "Maroc"
COUNTRY_USA = "États-Unis"
USA_CORRIDOR_GRAPH_NAME = "Couloir de performance (AgeGroup) - USA Swimming"
USA_CORRIDOR_COLS = ("Event", "SwimTimeSeconds", "AgeGroup", "Gender", "Name")
USA_CORRIDOR_MIN_POINTS = 100
CORRIDOR_GRAPH_NAME = "Couloir de performance (âge) - nageur cible"
CORRIDOR_GLOBAL_GRAPH_NAME = "Couloir de performance global (âge)"
CORRIDOR_GLOBAL_DECILES_GRAPH_NAME = "Couloir de performance global (déciles 10-90)"
CORRIDOR_CATEGORY = "Couloirs de performance"
CORRIDOR_SWIMMER_UI_GRAPHS: Tuple[str, ...] = (
    CORRIDOR_GRAPH_NAME,
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
)
CHART_PNG_DPI = 96
CORRIDOR_CHART_PNG_DPI = 72


def _figure_to_base64(fig: plt.Figure, *, dpi: Optional[int] = None) -> str:
    """
    Convertit une figure matplotlib en data-URI PNG base64.

    Args:
        fig (plt.Figure): Figure à exporter.
        dpi (Optional[int]): Résolution ; défaut ``CHART_PNG_DPI``.

    Returns:
        str: URI ``data:image/png;base64,…``.
    """
    import base64
    import io

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=int(dpi or CHART_PNG_DPI))
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@lru_cache(maxsize=1)
def _load_extranat_cached() -> pd.DataFrame:
    """
    Charge le DataFrame Extranat (cache processus).

    Returns:
        pd.DataFrame: Performances Extranat aplaties.
    """
    from pacing.data.extranat_loader import ExtranatCompetitionsDataLoader

    return ExtranatCompetitionsDataLoader(EXTRANAT_PROCESSED_DIR).load()


class PacingAppService:
    """
    Façade métier pour l'application desktop Pacing.

    Centralise chargement des données, listes de nageurs, construction des
    figures et export PNG. L'UI Flet ne doit plus importer loaders,
    ``corridor_data`` ni ``ServiceGraphe`` directement.

    Attributes:
        graph_svc (ServiceGraphe): Orchestrateur graphes.
        usaswimming_loader (UsaswimmingCompetitionsDataLoader): Loader USA.
        frmnatation_loader (FrmnatationHtmlResultsDataLoader): Loader Maroc.
    """

    def __init__(self) -> None:
        """
        Initialise loaders, service graphes et caches LRU.

        Returns:
            None
        """
        self.graph_svc = ServiceGraphe()
        self.corridor_charts = BuildCorridorChart(self.graph_svc)
        self.prefetch_graphs = PrefetchGraphs(self.graph_svc)
        self.usaswimming_loader = UsaswimmingCompetitionsDataLoader(
            base_dir=USASWIMMING_PROCESSED_DIR,
            parquet_dir=USASWIMMING_PARQUET_DIR,
        )
        self.frmnatation_loader = FrmnatationHtmlResultsDataLoader(
            base_dir=DEFAULT_FRMNATATION_HTML_RESULTS_DIR or FRMNATATION_PROCESSED_DIR,
        )
        self._frm_df_cache: Optional[pd.DataFrame] = None
        self._usa_events_cache: Optional[List[str]] = None
        self._usa_df_by_event: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
        self._usa_names_by_event_key: Dict[Tuple[str, str], List[str]] = {}
        self._scope_performances_cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
        self._scope_performances_cache_max = 64

    # --- catalogue (lecture seule pour menus UI) ---

    @property
    def graph_categories(self) -> Dict[str, List[str]]:
        """
        Catalogue des catégories / graphes pour les menus.

        Returns:
            Dict[str, List[str]]: Catégorie → liste de libellés de graphes.
        """
        return GRAPH_CATEGORIES

    @property
    def notebook_specs(self) -> Dict[str, Any]:
        """
        Spécifications des graphes notebook à précharger.

        Returns:
            Dict[str, Any]: Catalogue ``GRAPHES_NOTEBOOK``.
        """
        return GRAPHES_NOTEBOOK

    def available_categories(self, country: str) -> List[str]:
        """
        Liste les catégories disponibles pour un pays.

        Args:
            country (str): Pays sélectionné.

        Returns:
            List[str]: Libellés de catégories.
        """
        return list(GRAPH_CATEGORIES.keys())

    def available_graphs(self, country: str, category: str) -> List[str]:
        """
        Liste les graphes d'une catégorie pour un pays.

        Args:
            country (str): Pays sélectionné.
            category (str): Catégorie UI.

        Returns:
            List[str]: Libellés de graphes.
        """
        if country == COUNTRY_USA and category == CORRIDOR_CATEGORY:
            return [USA_CORRIDOR_GRAPH_NAME]
        graphs = list(GRAPH_CATEGORIES.get(category, []))
        return [
            g
            for g in graphs
            if g not in (CORRIDOR_GLOBAL_GRAPH_NAME, USA_CORRIDOR_GRAPH_NAME)
        ]

    # --- données ---

    def load_extranat(self) -> pd.DataFrame:
        """
        Charge le DataFrame Extranat.

        Returns:
            pd.DataFrame: Performances France.
        """
        return _load_extranat_cached()

    def get_frmnatation_df(self) -> pd.DataFrame:
        """
        Charge (avec cache) le DataFrame FRM Natation.

        Returns:
            pd.DataFrame: Performances Maroc.
        """
        if self._frm_df_cache is None:
            self._frm_df_cache = self.frmnatation_loader.load()
        return self._frm_df_cache.copy()

    def nav_df_for_country(
        self, country: str, extranat_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Retourne le DataFrame de navigation selon le pays.

        Args:
            country (str): Pays UI.
            extranat_df (pd.DataFrame): Données Extranat déjà chargées.

        Returns:
            pd.DataFrame: DF navigable (FR ou MA).
        """
        if country == COUNTRY_MOROCCO:
            return self.get_frmnatation_df()
        return extranat_df.copy()

    def ensure_usa_parquet_cache(
        self,
        *,
        progress: Optional[Callable[[str], None]] = None,
        progress_step: Optional[Callable[[str, int, int], None]] = None,
    ) -> None:
        """
        Construit le cache Parquet USA Swimming si besoin.

        Args:
            progress (Optional[Callable[[str], None]]): Callback détail.
            progress_step (Optional[Callable[[str, int, int], None]]): Progression.

        Returns:
            None
        """
        self.usaswimming_loader.build_parquet_cache(
            progress_callback=progress,
            progress_step_callback=progress_step,
        )

    def list_usa_events(self) -> List[str]:
        """
        Liste les épreuves USA disponibles.

        Returns:
            List[str]: Libellés d'épreuves.
        """
        if self._usa_events_cache is not None:
            return self._usa_events_cache
        self._usa_events_cache = self.usaswimming_loader.available_events()
        return self._usa_events_cache

    def available_years_usa(self) -> List[int]:
        """
        Années présentes dans le cache USA.

        Returns:
            List[int]: Années disponibles.
        """
        return list(self.usaswimming_loader.available_years())

    def get_usa_corridor_df(self, event: str) -> pd.DataFrame:
        """
        Charge le DataFrame USA pour une épreuve (cache LRU).

        Args:
            event (str): Libellé d'épreuve.

        Returns:
            pd.DataFrame: Performances USA filtrées.
        """
        event_key = str(event).strip()
        cached = self._usa_df_by_event.get(event_key)
        if cached is not None:
            self._usa_df_by_event.move_to_end(event_key)
            return cached
        df_usa = self.usaswimming_loader.load(
            columns=list(USA_CORRIDOR_COLS),
            event=event_key,
        )
        self._usa_df_by_event[event_key] = df_usa
        self._usa_df_by_event.move_to_end(event_key)
        if len(self._usa_df_by_event) > 32:
            self._usa_df_by_event.popitem(last=False)
        return df_usa

    def usa_swimmer_names(self, event: str, gender: str = "all") -> List[str]:
        """
        Noms distincts USA pour une épreuve.

        Args:
            event (str): Épreuve.
            gender (str): ``F``, ``M`` ou ``all``.

        Returns:
            List[str]: Noms de nageurs.
        """
        g = normalize_gender_code(gender) or "all"
        gender_key = g if g in ("F", "M") else "all"
        cache_key = (str(event).strip(), gender_key)
        cached = self._usa_names_by_event_key.get(cache_key)
        if cached is not None:
            return cached
        loader_gender = g if g in ("F", "M") else None
        names = self.usaswimming_loader.list_names_for_event(
            str(event).strip(),
            gender=loader_gender,
        )
        self._usa_names_by_event_key[cache_key] = names
        return names

    def morocco_swimmer_labels(
        self,
        *,
        stroke: Optional[str] = None,
        distance: Optional[int] = None,
        pool: Optional[str] = None,
        event: Optional[str] = None,
        gender: str = "all",
    ) -> List[str]:
        """
        Libellés nageurs marocains pour filtres / épreuve.

        Args:
            stroke (Optional[str]): Code nage.
            distance (Optional[int]): Distance.
            pool (Optional[str]): Bassin.
            event (Optional[str]): Libellé d'épreuve complet.
            gender (str): Filtre genre.

        Returns:
            List[str]: Libellés ``Nom (YOB)``.
        """
        g = normalize_gender_code(gender)
        return self.frmnatation_loader.list_swimmer_labels(
            stroke=stroke,
            distance=distance,
            pool=pool,
            event=event,
            gender=g if g in ("F", "M") else "all",
        )

    # --- scope / filtres ---

    def materialize_scope(
        self,
        df_nav: pd.DataFrame,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> pd.DataFrame:
        """
        Matérialise le DataFrame scopé pour un graphe (cache LRU).

        Args:
            df_nav (pd.DataFrame): Navigation.
            graph_name (str): Libellé graphe.
            stroke (Optional[str]): Nage.
            distance (Optional[int]): Distance.
            pool (Optional[str]): Bassin.

        Returns:
            pd.DataFrame: Sous-ensemble filtré.
        """
        cache_key = (
            id(df_nav),
            str(graph_name),
            str(stroke) if stroke is not None else "",
            int(distance) if distance is not None else -1,
            str(pool) if pool is not None else "",
        )
        cached = self._scope_performances_cache.get(cache_key)
        if cached is not None:
            self._scope_performances_cache.move_to_end(cache_key)
            return cached

        out = materialize_df_scope(df_nav, graph_name, stroke, distance, pool)
        self._scope_performances_cache[cache_key] = out
        self._scope_performances_cache.move_to_end(cache_key)
        if len(self._scope_performances_cache) > self._scope_performances_cache_max:
            self._scope_performances_cache.popitem(last=False)
        return out

    def clear_scope_cache(self) -> None:
        """
        Vide le cache de scopes performances.

        Returns:
            None
        """
        self._scope_performances_cache.clear()

    # --- helpers couloirs ---

    def infer_frmnatation_year_of_birth(
        self, nom_event: str, nom_nageur: str
    ) -> Optional[int]:
        """
        Déduit l'année de naissance la plus fréquente (FRM).

        Args:
            nom_event (str): Épreuve.
            nom_nageur (str): Nom du nageur.

        Returns:
            Optional[int]: Année de naissance ou None.
        """
        df = self.frmnatation_loader.load()
        if df.empty:
            return None
        scoped = df[
            (df["Event"].astype(str).str.strip() == str(nom_event).strip())
            & (df["Name"].astype(str).str.strip() == str(nom_nageur).strip())
        ]
        if scoped.empty or "Year_of_birth" not in scoped.columns:
            return None
        yobs = pd.to_numeric(scoped["Year_of_birth"], errors="coerce").dropna()
        if yobs.empty:
            return None
        return int(yobs.mode().iloc[0])

    def infer_yob_from_df_scope(
        self, df_scope: pd.DataFrame, nom_event: str, nom_nageur: str
    ) -> Optional[int]:
        """
        Année de naissance la plus fréquente dans un périmètre Extranat.

        Args:
            df_scope (pd.DataFrame): Périmètre courant.
            nom_event (str): Épreuve.
            nom_nageur (str): Nom.

        Returns:
            Optional[int]: YOB ou None.
        """
        if df_scope.empty or "Event" not in df_scope.columns:
            return None
        scoped = df_scope[
            df_scope["Event"].astype(str).str.strip() == str(nom_event).strip()
        ]
        if scoped.empty:
            return None
        target = str(nom_nageur).strip()
        yobs: List[int] = []
        for row in scoped.itertuples(index=False):
            swimmers = getattr(row, "swimmer", None)
            if not isinstance(swimmers, list):
                continue
            for sw in swimmers:
                if not isinstance(sw, dict):
                    continue
                if str(sw.get("Name", "")).strip() != target:
                    continue
                try:
                    yob = sw.get("Year_of_birth")
                    if yob is not None and yob == yob:
                        yobs.append(int(yob))
                except (TypeError, ValueError):
                    pass
        if not yobs:
            return None
        return int(pd.Series(yobs).mode().iloc[0])

    def frm_rows_for_corridor_swimmer(
        self,
        *,
        nom_event: str,
        nom_nageur: str,
        year_of_birth: Optional[int],
    ) -> Tuple[Optional[str], Optional[int], pd.DataFrame]:
        """
        Performances FRM au format Extranat pour un nageur cible.

        Args:
            nom_event (str): Épreuve.
            nom_nageur (str): Nom.
            year_of_birth (Optional[int]): YOB optionnel.

        Returns:
            Tuple[Optional[str], Optional[int], pd.DataFrame]: Nom, YOB, lignes.
        """
        if not isinstance(nom_nageur, str) or not nom_nageur.strip():
            return None, None, pd.DataFrame()
        yob = year_of_birth
        if yob is None:
            yob = self.infer_frmnatation_year_of_birth(nom_event, nom_nageur.strip())
        rows = self.frmnatation_loader.rows_for_swimmer(
            nom_event=nom_event,
            nom_nageur=nom_nageur.strip(),
            year_of_birth=yob,
        )
        if rows.empty and yob is not None:
            rows = self.frmnatation_loader.rows_for_swimmer(
                nom_event=nom_event,
                nom_nageur=nom_nageur.strip(),
                year_of_birth=None,
            )
            if not rows.empty and "Year_of_birth" in rows.columns:
                yob_series = pd.to_numeric(rows["Year_of_birth"], errors="coerce")
                if yob_series.notna().any():
                    yob = int(yob_series.mode().iloc[0])
        return nom_nageur.strip(), yob, rows

    def moroccan_corridor_overlay_bundle(
        self,
        *,
        ma_name: Optional[str],
        ma_yob: Optional[int],
        nom_event: str,
        usa_mode: bool = False,
    ) -> Tuple[Optional[str], Optional[int], pd.DataFrame]:
        """
        Données FRM pour tracer le nageur marocain en overlay.

        Args:
            ma_name (Optional[str]): Nom marocain.
            ma_yob (Optional[int]): Année de naissance.
            nom_event (str): Épreuve.
            usa_mode (bool): Format overlay USA si True.

        Returns:
            Tuple[Optional[str], Optional[int], pd.DataFrame]: Nom, YOB, lignes.
        """
        if not isinstance(ma_name, str) or not ma_name.strip():
            return None, None, pd.DataFrame()
        yob_int: Optional[int] = None
        if ma_yob is not None:
            try:
                yob_int = int(ma_yob)
            except (TypeError, ValueError):
                yob_int = None
        if yob_int is None:
            yob_int = self.infer_frmnatation_year_of_birth(
                str(nom_event).strip(), ma_name.strip()
            )
        if usa_mode:
            rows = self.frmnatation_loader.usa_overlay_rows_for_swimmer(
                nom_event=str(nom_event).strip(),
                nom_nageur=ma_name.strip(),
                year_of_birth=yob_int,
            )
        else:
            rows = self.frmnatation_loader.rows_for_swimmer(
                nom_event=nom_event,
                nom_nageur=ma_name.strip(),
                year_of_birth=yob_int,
            )
        return ma_name.strip(), yob_int, rows

    def build_corridor_plot_kwargs(
        self,
        *,
        primary_name: Optional[str],
        primary_yob: Optional[int],
        primary_df: Optional[pd.DataFrame],
        overlay_name: Optional[str] = None,
        overlay_yob: Optional[int] = None,
        overlay_df: Optional[pd.DataFrame] = None,
        gender: Optional[str] = None,
        primary_label: str = "Nageur cible (France)",
        morocco_primary: bool = False,
        df_scope: Optional[pd.DataFrame] = None,
        nom_event: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Construit les kwargs de tracé couloir.

        Args:
            primary_name (Optional[str]): Nageur principal.
            primary_yob (Optional[int]): YOB principal.
            primary_df (Optional[pd.DataFrame]): DF nageur principal.
            overlay_name (Optional[str]): Overlay.
            overlay_yob (Optional[int]): YOB overlay.
            overlay_df (Optional[pd.DataFrame]): DF overlay.
            gender (Optional[str]): Filtre genre.
            primary_label (str): Libellé légende.
            morocco_primary (bool): Couleur / résolution MA.
            df_scope (Optional[pd.DataFrame]): Scope pour infer YOB.
            nom_event (Optional[str]): Épreuve.

        Returns:
            Dict[str, Any]: Kwargs pour le rendu couloir.
        """
        primary_yob_resolved = primary_yob
        if (
            primary_yob_resolved is None
            and isinstance(primary_name, str)
            and primary_name.strip()
        ):
            if morocco_primary and nom_event:
                primary_yob_resolved = self.infer_frmnatation_year_of_birth(
                    nom_event, primary_name.strip()
                )
            elif (
                not morocco_primary
                and df_scope is not None
                and nom_event
            ):
                primary_yob_resolved = self.infer_yob_from_df_scope(
                    df_scope, nom_event, primary_name.strip()
                )

        ov_yob = overlay_yob
        if (
            ov_yob is None
            and isinstance(overlay_name, str)
            and overlay_name.strip()
            and overlay_df is not None
            and not overlay_df.empty
        ):
            ev = (
                str(overlay_df["Event"].iloc[0])
                if "Event" in overlay_df.columns
                else (nom_event or "")
            )
            if ev:
                ov_yob = self.infer_frmnatation_year_of_birth(ev, overlay_name.strip())

        g = normalize_gender_code(gender) if gender else None
        gender_filter = g if g in ("F", "M") else None
        color = (
            CORRIDOR_MA_SWIMMER_COLOR if morocco_primary else CORRIDOR_FR_SWIMMER_COLOR
        )
        return self.corridor_charts.build_plot_kwargs(
            gender_filter=gender_filter,
            primary_name=primary_name,
            primary_yob=primary_yob_resolved,
            primary_df=primary_df,
            primary_label=primary_label,
            primary_color=color,
            overlay_name=overlay_name,
            overlay_yob=ov_yob,
            overlay_df=overlay_df,
        )

    # --- construction figures (cœur métier pour l'UI) ---

    def compute_usa_corridor_chart_payload(
        self, snap: Dict[str, Any], *, render_key: str
    ) -> Dict[str, Any]:
        """
        Calcule le payload image du couloir USA (sans cache UI).

        Args:
            snap (Dict[str, Any]): Snapshot de sélection UI.
            render_key (str): Clé de rendu fournie par l'UI.

        Returns:
            Dict[str, Any]: Payload (status, image_base64, titres, etc.).
        """
        category = str(snap["category"])
        graph_name = str(snap["graph"])
        usa_event = snap.get("usa_event")

        if not usa_event:
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "country": COUNTRY_USA,
                "usa_event": usa_event,
                "status": "empty_scope",
                "image_base64": None,
                "chart_title": "Sélectionnez une épreuve USA Swimming",
                "row_count": 0,
                "error": None,
            }

        df_usa = self.get_usa_corridor_df(str(usa_event))
        if df_usa.empty:
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "country": COUNTRY_USA,
                "usa_event": usa_event,
                "status": "empty_scope",
                "image_base64": None,
                "chart_title": f"Aucune donnée pour {usa_event}",
                "row_count": 0,
                "error": None,
            }

        spec = GRAPHES_PAR_KEY["performance_corridor_global_by_agegroup"]
        gender = normalize_gender_code(snap.get("corridor_gender") or "all")
        kwargs: Dict[str, Any] = {
            "nom_event": str(usa_event),
            "min_points": USA_CORRIDOR_MIN_POINTS,
        }
        if gender in ("F", "M"):
            kwargs["gender"] = gender
        swimmer_name = snap.get("corridor_name")
        corridor_yob = snap.get("corridor_yob")
        if isinstance(swimmer_name, str) and swimmer_name.strip():
            kwargs["nom_nageur"] = swimmer_name.strip()
            if corridor_yob is not None:
                try:
                    kwargs["year_of_birth"] = int(corridor_yob)
                except (TypeError, ValueError):
                    pass

        ma_name = snap.get("moroccan_corridor_name")
        ma_yob = snap.get("moroccan_corridor_yob")
        _, ma_plot_yob, ma_overlay_df = self.moroccan_corridor_overlay_bundle(
            ma_name=ma_name if isinstance(ma_name, str) else None,
            ma_yob=ma_yob if ma_yob is not None else None,
            nom_event=str(usa_event),
            usa_mode=True,
        )
        if not ma_overlay_df.empty and isinstance(ma_name, str) and ma_name.strip():
            kwargs["overlay_nageur"] = ma_name.strip()
            if ma_plot_yob is not None:
                kwargs["overlay_year_of_birth"] = int(ma_plot_yob)
            kwargs["overlay_df"] = ma_overlay_df

        fig, meta = self.graph_svc.build_figure(spec, df_usa, **kwargs)
        chart_title = f"Couloir de performance global (AgeGroup) - {usa_event}"
        if isinstance(meta, dict):
            if meta.get("message") != "ok":
                err = str(meta.get("message", ""))
                if err:
                    chart_title = err
            elif meta.get("overlay_swimmer_message"):
                chart_title = str(meta["overlay_swimmer_message"])
            elif meta.get("swimmer_message"):
                chart_title = str(meta["swimmer_message"])

        if fig is None:
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "country": COUNTRY_USA,
                "usa_event": usa_event,
                "status": "no_figure",
                "image_base64": None,
                "chart_title": chart_title,
                "row_count": len(df_usa),
                "error": None,
                "corridor_name": snap.get("corridor_name"),
                "corridor_gender": snap.get("corridor_gender"),
            }

        image_base64 = _figure_to_base64(fig, dpi=CORRIDOR_CHART_PNG_DPI)
        plt.close(fig)
        return {
            "render_key": render_key,
            "category": category,
            "graph_name": graph_name,
            "country": COUNTRY_USA,
            "usa_event": usa_event,
            "status": "ok",
            "image_base64": image_base64,
            "chart_title": chart_title,
            "row_count": len(df_usa),
            "error": None,
            "corridor_name": snap.get("corridor_name"),
            "corridor_gender": snap.get("corridor_gender"),
        }

    def compute_chart_payload(
        self,
        snap: Dict[str, Any],
        *,
        df_extranat: pd.DataFrame,
        df_nav: pd.DataFrame,
        render_key: str,
        needs_moroccan_overlay: bool = False,
    ) -> Dict[str, Any]:
        """
        Calcule le payload image d'un graphe (FR/MA/USA), sans cache UI.

        Args:
            snap (Dict[str, Any]): Snapshot de sélection.
            df_extranat (pd.DataFrame): Données Extranat complètes.
            df_nav (pd.DataFrame): DF de navigation courant.
            render_key (str): Clé de rendu UI.
            needs_moroccan_overlay (bool): Activer overlay MA sur couloir FR.

        Returns:
            Dict[str, Any]: Payload affichable (PNG base64 ou statut).
        """
        if snap.get("country") == COUNTRY_USA:
            return self.compute_usa_corridor_chart_payload(snap, render_key=render_key)

        graph_name = str(snap["graph"])
        category = str(snap["category"])
        stroke = snap.get("stroke")
        distance = snap.get("distance")
        pool = snap.get("pool")

        stroke_r, distance_r, pool_r = resolve_scope_filters(
            df_nav, graph_name, stroke, distance, pool
        )
        df_scope = self.materialize_scope(
            df_nav, graph_name, stroke_r, distance_r, pool_r
        )
        country = str(snap.get("country") or COUNTRY_FRANCE)
        is_morocco = country == COUNTRY_MOROCCO
        corridor_ref_df = self.get_frmnatation_df() if is_morocco else df_extranat

        ma_name = snap.get("moroccan_corridor_name")
        ma_yob = snap.get("moroccan_corridor_yob")
        ma_plot_name: Optional[str] = None
        ma_plot_yob: Optional[int] = None
        ma_plot_df = pd.DataFrame()
        primary_name = snap.get("corridor_name")
        primary_yob = snap.get("corridor_yob")
        primary_df = pd.DataFrame()
        nom_event: Optional[str] = None
        if stroke_r and distance_r is not None and pool_r:
            nom_event = f"{int(distance_r)} {stroke_r} {pool_r}"

        if (
            is_morocco
            and graph_name in CORRIDOR_SWIMMER_UI_GRAPHS
            and nom_event
            and isinstance(primary_name, str)
            and primary_name.strip()
        ):
            primary_name, primary_yob, primary_df = self.frm_rows_for_corridor_swimmer(
                nom_event=nom_event,
                nom_nageur=primary_name,
                year_of_birth=primary_yob if primary_yob is not None else None,
            )
        elif (
            needs_moroccan_overlay
            and graph_name in CORRIDOR_SWIMMER_UI_GRAPHS
            and nom_event
        ):
            ma_plot_name, ma_plot_yob, ma_plot_df = self.moroccan_corridor_overlay_bundle(
                ma_name=ma_name if isinstance(ma_name, str) else None,
                ma_yob=ma_yob if ma_yob is not None else None,
                nom_event=nom_event,
                usa_mode=False,
            )

        if df_scope.empty:
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "stroke": stroke_r,
                "distance": distance_r,
                "pool": pool_r,
                "status": "empty_scope",
                "image_base64": None,
                "chart_title": graph_name,
                "row_count": 0,
                "error": None,
                "corridor_name": snap.get("corridor_name"),
                "corridor_yob": snap.get("corridor_yob"),
                "deciles_name": snap.get("deciles_name"),
                "deciles_yob": snap.get("deciles_yob"),
                "heatmap": snap.get("heatmap"),
                "pacing": snap.get("pacing"),
                "chronos_sample_size": snap.get("chronos_sample_size"),
            }

        df_filtered = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
        corridor_plot_kwargs = self.build_corridor_plot_kwargs(
            primary_name=primary_name if is_morocco else snap.get("corridor_name"),
            primary_yob=primary_yob if is_morocco else snap.get("corridor_yob"),
            primary_df=primary_df if not primary_df.empty else None,
            overlay_name=None if is_morocco else ma_plot_name,
            overlay_yob=None if is_morocco else ma_plot_yob,
            overlay_df=ma_plot_df if not is_morocco and not ma_plot_df.empty else None,
            gender=snap.get("corridor_gender"),
            primary_label=(
                "Nageur cible (Maroc)" if is_morocco else "Nageur cible (France)"
            ),
            morocco_primary=is_morocco,
            df_scope=df_scope,
            nom_event=nom_event,
        )
        fig, chart_title = self.graph_svc.desktop_build_figure(
            graph_name,
            df=corridor_ref_df,
            df_scope=df_scope,
            df_filtered=df_filtered,
            stroke=stroke_r,
            distance=distance_r,
            pool=pool_r,
            selected_distance=distance,
            selected_chronos_sample_size=int(snap.get("chronos_sample_size", 5000)),
            selected_pacing_swimmers=list(snap.get("pacing") or []),
            selected_heatmap_swimmer=snap.get("heatmap"),
            selected_corridor_swimmer_name=primary_name or snap.get("corridor_name"),
            selected_corridor_swimmer_yob=(
                primary_yob if is_morocco else snap.get("corridor_yob")
            ),
            moroccan_corridor_swimmer_name=ma_plot_name,
            moroccan_corridor_swimmer_yob=ma_plot_yob,
            moroccan_corridor_df=ma_plot_df if not ma_plot_df.empty else None,
            corridor_plot_kwargs=corridor_plot_kwargs,
            corridor_reference_df=corridor_ref_df,
            event_counts_sort=str(
                snap.get("event_counts_sort", EVENT_COUNTS_SORT_STROKE_DISTANCE)
            ),
        )
        if fig is None:
            return {
                "render_key": render_key,
                "category": category,
                "graph_name": graph_name,
                "stroke": stroke_r,
                "distance": distance_r,
                "pool": pool_r,
                "status": "no_figure",
                "image_base64": None,
                "chart_title": chart_title,
                "row_count": len(df_scope),
                "error": None,
                "corridor_name": snap.get("corridor_name"),
                "corridor_yob": snap.get("corridor_yob"),
                "deciles_name": snap.get("deciles_name"),
                "deciles_yob": snap.get("deciles_yob"),
                "heatmap": snap.get("heatmap"),
                "pacing": snap.get("pacing"),
                "chronos_sample_size": snap.get("chronos_sample_size"),
            }

        png_dpi = (
            CORRIDOR_CHART_PNG_DPI
            if graph_name in CORRIDOR_SWIMMER_UI_GRAPHS
            else None
        )
        image_base64 = _figure_to_base64(fig, dpi=png_dpi)
        plt.close(fig)
        return {
            "render_key": render_key,
            "category": category,
            "graph_name": graph_name,
            "stroke": stroke_r,
            "distance": distance_r,
            "pool": pool_r,
            "status": "ok",
            "image_base64": image_base64,
            "chart_title": chart_title,
            "row_count": len(df_scope),
            "error": None,
            "corridor_name": snap.get("corridor_name"),
            "corridor_yob": snap.get("corridor_yob"),
            "deciles_name": snap.get("deciles_name"),
            "deciles_yob": snap.get("deciles_yob"),
            "heatmap": snap.get("heatmap"),
            "pacing": snap.get("pacing"),
            "chronos_sample_size": snap.get("chronos_sample_size"),
        }

    def compute_notebook_prefetch(
        self,
        spec: Any,
        df: pd.DataFrame,
        df_nav: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Construit une figure notebook et renvoie son PNG.

        Args:
            spec (Any): Spécification ``GraphSpec``.
            df (pd.DataFrame): Données Extranat.
            df_nav (pd.DataFrame): Navigation.

        Returns:
            Dict[str, Any]: status, image_base64, chart_title, row_count, error.
        """
        try:
            raw = self.graph_svc.build_figure_prefetch(spec, df, df_nav)
            fig = unwrap_matplotlib_figure(raw)
            if fig is None:
                return {
                    "status": "no_figure",
                    "image_base64": None,
                    "chart_title": getattr(spec, "title", ""),
                    "row_count": 0,
                    "error": None,
                }
            image_base64 = _figure_to_base64(fig)
            plt.close(fig)
            return {
                "status": "ok",
                "image_base64": image_base64,
                "chart_title": getattr(spec, "title", ""),
                "row_count": len(df_nav),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 — surface à l'UI
            return {
                "status": "error",
                "image_base64": None,
                "chart_title": getattr(spec, "title", ""),
                "row_count": 0,
                "error": str(exc),
            }
