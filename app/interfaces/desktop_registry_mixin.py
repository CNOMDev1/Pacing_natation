"""Mixin registre / caches event-swimmers pour l'UI desktop Flet.

Extrait de ``desktop_flet.PacingDesktopApp`` : estimation et persistance du
cache nageurs-par-événement, clés de rendu, lecture/écriture du registre JSON
des graphiques précalculés.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, List, Optional, Tuple

import flet as ft
import pandas as pd

from project_path import ensure_project_imports

ensure_project_imports()

from desktop_helpers import _normalize_text, _primary_swimmer_name_and_yob, _slugify
from services.app_service import CORRIDOR_CHART_STYLE_VERSION
from services.graph_catalog import (
    GRAPH_RELAY_SPLIT_DISTANCE,
    MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION,
    MEDIAN_SPEED_BY_GENDER_GRAPH_NAME,
    MEDIAN_VS_BEST_CHART_STYLE_VERSION,
    MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME,
    MEDIAN_VS_TOP10_CHART_STYLE_VERSION,
    MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME,
    RELAY_SPLIT_CHART_STYLE_VERSION,
)
from desktop_settings import (
    CORRIDOR_CATEGORY,
    CORRIDOR_GLOBAL_DECILES_GRAPH_NAME,
    CORRIDOR_GLOBAL_GRAPH_NAME,
    CORRIDOR_SWIMMER_UI_GRAPHS,
    ENABLE_PERSISTENT_GRAPH_CACHE,
    EVENT_SWIMMERS_EXPORT_PATH,
    EXPORT_IMAGE_BASE64_TO_JSON,
    GRAPH_EXPORT_PATH,
    HEATMAP_DROPDOWN_SWIMMER_LIMIT,
)


class DesktopRegistryMixin:
    """Mixin : registre graphiques et cache event-swimmers.

    À mélanger avec ``PacingDesktopApp``. Gère le JSON disque
    (``prefetched_graphs.json``, ``prefetched_event_swimmers.json``) et les
    helpers de clé de rendu associés.

    Attributes:
        graph_render_registry (dict): Cache des graphiques précalculés.
        chart_image_cache (dict): Images base64 indexées par clé de rendu.
    """

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
                    if self._startup_prefetch_ui is not None:
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

    def _corridor_swimmer_labels_from_nav(
        self,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        gender: str = "all",
    ) -> List[str]:
        """
        Liste des nageurs pour le couloir France : calculée en direct sur df_nav
        (même épreuve que le graphique), pas seulement le JSON prefetched_event_swimmers.
        """
        if not stroke or distance is None or not pool:
            return []
        gender_key = self._normalize_gender_value(gender)
        if gender_key not in ("all", "F", "M"):
            gender_key = "all"

        dist_num = int(distance)
        stroke_key = str(stroke).strip()
        pool_key = str(pool).strip()
        mask = (
            (self.df_nav["Stroke"].astype(str).str.strip() == stroke_key)
            & (pd.to_numeric(self.df_nav["Distance"], errors="coerce") == dist_num)
            & (self.df_nav["Course"].astype(str).str.strip() == pool_key)
        )
        scoped = self.df_nav.loc[mask]
        if "Event" in scoped.columns:
            nom_event = f"{dist_num} {stroke_key} {pool_key}"
            scoped = scoped[scoped["Event"].astype(str).str.strip() == nom_event]
        if scoped.empty:
            return []

        labels: set[str] = set()
        for row in scoped.itertuples(index=False):
            swim_seconds = getattr(row, "SwimTimeSeconds", None)
            try:
                if swim_seconds is None or swim_seconds != swim_seconds:
                    continue
            except (TypeError, ValueError):
                continue
            swimmers_raw = getattr(row, "swimmer", None)
            if not (isinstance(swimmers_raw, list) and len(swimmers_raw) == 1):
                continue
            swimmers = swimmers_raw
            for swimmer in swimmers:
                if not isinstance(swimmer, dict):
                    continue
                swimmer_gender = self._normalize_gender_value(swimmer.get("Gender"))
                if gender_key in ("F", "M") and swimmer_gender != gender_key:
                    continue
                nm, yob = _primary_swimmer_name_and_yob([swimmer])
                if nm and yob is not None:
                    labels.add(f"{nm} ({yob})")
                elif isinstance(swimmer.get("Name"), str) and swimmer["Name"].strip():
                    labels.add(swimmer["Name"].strip())

        return sorted(labels, key=lambda label: _normalize_text(label))

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
        gender = (
            self.selected_corridor_gender
            if self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
            else "all"
        )
        if (
            self.selected_graph in CORRIDOR_SWIMMER_UI_GRAPHS
            and not self._is_usa_corridor_mode()
        ):
            self._selected_event_swimmers = self._corridor_swimmer_labels_from_nav(
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
                gender,
            )
            self._event_swimmer_options_cache.clear()
            return
        self._selected_event_swimmers = self._cached_event_swimmers_for_filters(
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            gender,
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
            len(self.graph_render_registry),
        )
        if (
            self._registry_swimmer_names_cache_key == key
            and self._registry_swimmer_names_cache is not None
        ):
            return self._registry_swimmer_names_cache

        names: set[str] = set()
        for item in self.graph_render_registry.values():
            if not isinstance(item, dict):
                continue
            if not DesktopRegistryMixin._is_corridor_registry_item(item):
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
        self._registry_swimmer_names_cache = out
        self._registry_swimmer_names_cache_key = key
        return out

    def _build_heatmap_swimmer_dropdown_options(self) -> List[str]:
        """Construit la liste des nageurs proposés dans le dropdown heatmap.

        Priorise les nageurs du registre couloir, puis complète avec les noms
        les plus fréquents dans ``df_nav`` (colonne ``SwimmerName``). La liste
        est bornée pour garder l'UI réactive.

        Returns:
            List[str]: Noms uniques prêts pour le dropdown heatmap.
        """
        options: List[str] = []
        seen: set[str] = set()

        def add_name(raw: object) -> None:
            if not isinstance(raw, str):
                return
            cleaned = raw.strip()
            if cleaned.startswith("- "):
                cleaned = cleaned[2:].strip()
            if not cleaned:
                return
            norm = _normalize_text(cleaned)
            if norm in seen:
                return
            seen.add(norm)
            options.append(cleaned)

        for name in self._swimmer_names_from_corridor_registry():
            add_name(name)

        limit = max(1, int(HEATMAP_DROPDOWN_SWIMMER_LIMIT))
        if (
            len(options) < limit
            and not self.df_nav.empty
            and "SwimmerName" in self.df_nav.columns
        ):
            top_names = self.df_nav["SwimmerName"].dropna().value_counts().index
            for name in top_names:
                add_name(str(name))
                if len(options) >= limit:
                    break

        options.sort(key=lambda item: _normalize_text(item))
        self._heatmap_dropdown_options = options
        self._heatmap_dropdown_options_ready = True
        self._heatmap_dropdown_df_len = len(self.df_nav)
        return options

    def _heatmap_swimmer_dropdown_options(self) -> List[str]:
        """Retourne les options du dropdown heatmap (cache mémoire).

        Returns:
            List[str]: Noms de nageurs pour le menu déroulant heatmap.
        """
        if (
            self._heatmap_dropdown_options_ready
            and self._heatmap_dropdown_options is not None
            and self._heatmap_dropdown_df_len == len(self.df_nav)
        ):
            return self._heatmap_dropdown_options
        return self._build_heatmap_swimmer_dropdown_options()

    def _render_key_for_category_graph_options(
        self, category: str, graph_name: str, options: Dict[str, Any]
    ) -> Tuple[str, str]:
        chart_id = f"{_slugify(category)}__{_slugify(graph_name)}"
        render_key = (
            f"{chart_id}::"
            f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        )
        return chart_id, render_key

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
        toujours ``heatmap_swimmer=None`` et ``pacing_swimmers=[]``. Sinon la clé
        ne matche pas le JSON et Matplotlib est relancé à chaque fois.
        """
        heatmap = self.selected_heatmap_swimmer
        pacing = self.selected_pacing_swimmers[:3]
        if graph_name in CORRIDOR_SWIMMER_UI_GRAPHS:
            heatmap = None
            pacing = []
        corridor_swimmer_name = self.selected_corridor_swimmer_name
        corridor_swimmer_yob = self.selected_corridor_swimmer_yob
        # Couloir global (âge) sans surcouche nageur : pas de corridor_* dans la clé.
        if graph_name == CORRIDOR_GLOBAL_GRAPH_NAME:
            corridor_swimmer_name = None
            corridor_swimmer_yob = None
        elif graph_name == CORRIDOR_GLOBAL_DECILES_GRAPH_NAME:
            corridor_swimmer_name = self.corridor_deciles_confirmed_name
            corridor_swimmer_yob = self.corridor_deciles_confirmed_yob
        moroccan_name = self.corridor_ma_confirmed_name
        moroccan_yob = self.corridor_ma_confirmed_yob
        if not self._needs_moroccan_corridor_swimmer_dd():
            moroccan_name = None
            moroccan_yob = None
        options: Dict[str, Any] = {
            "stroke": stroke,
            "distance": int(distance) if distance is not None else None,
            "pool": pool,
            "heatmap_swimmer": heatmap,
            "corridor_swimmer_name": corridor_swimmer_name,
            "corridor_swimmer_yob": corridor_swimmer_yob,
            "moroccan_corridor_swimmer_name": moroccan_name,
            "moroccan_corridor_swimmer_yob": moroccan_yob,
            "pacing_swimmers": pacing,
            "chronos_sample_size": int(self.selected_chronos_sample_size),
        }
        if graph_name in CORRIDOR_SWIMMER_UI_GRAPHS:
            options["chart_style_version"] = CORRIDOR_CHART_STYLE_VERSION
        if graph_name == MEDIAN_VS_BEST_SWIMMER_GRAPH_NAME:
            options["chart_style_version"] = MEDIAN_VS_BEST_CHART_STYLE_VERSION
        if graph_name == MEDIAN_VS_TOP10_SWIMMER_GRAPH_NAME:
            options["chart_style_version"] = MEDIAN_VS_TOP10_CHART_STYLE_VERSION
        if graph_name == MEDIAN_SPEED_BY_GENDER_GRAPH_NAME:
            options["chart_style_version"] = MEDIAN_SPEED_BY_GENDER_CHART_STYLE_VERSION
        if graph_name == GRAPH_RELAY_SPLIT_DISTANCE:
            options["chart_style_version"] = RELAY_SPLIT_CHART_STYLE_VERSION
        return options

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
            render_key = DesktopRegistryMixin._registry_item_to_render_key(item)
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
            if not DesktopRegistryMixin._is_corridor_registry_item(item)
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
        if DesktopRegistryMixin._is_corridor_registry_item(item):
            self._write_corridor_graphs_json()
        else:
            self._write_graph_registry_json()


