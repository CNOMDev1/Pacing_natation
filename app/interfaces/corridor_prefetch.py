import asyncio
import concurrent.futures
import datetime as dt
import os
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import matplotlib.pyplot as plt
from desktop_helpers import _figure_to_base64, _materialize_df_scope, _slugify
from services.graph_service import ServiceGraphe
if TYPE_CHECKING:
    from desktop_flet import PacingDesktopApp


CorridorTask = Tuple[str, int, str, str, int, int] # tâche de calcul couloir (stroke, distance, pool, swimmer_name, swimmer_yob, chronos_sample_size)
CorridorRender = Tuple[str, str, Dict[str, Any], str, str, int, Optional[str], Optional[str]] # résultat d’un calcul (render_key, chart_id, options, status, chart_title, row_count, image_base64, error)


class CorridorPrefetchManager:
    """Encapsule la collecte, le calcul et l'enregistrement du préfetch couloir."""
    def __init__(
        self,
        app: "PacingDesktopApp",
        *,
        corridor_category: str,
        corridor_graph_name: str,
        max_renders: Optional[int] = None,
    ) -> None:
        """Stocke le contexte nécessaire"""
        self.app = app
        self.corridor_category = corridor_category
        self.corridor_graph_name = corridor_graph_name
        self.max_renders = int(max_renders) if max_renders is not None else 0

    @staticmethod
    def corridor_prefetch_render_options_dict(
        stroke: str,
        distance: int,
        pool: str,
        swimmer_name: str,
        swimmer_yob: int,
        chronos_sample_size: int,
    ) -> Dict[str, Any]:
        """Construit les options normalisées d’un rendu couloir (pour générer une clé et lancer le calcul avec les bons paramètres)."""
        return {
            "stroke": stroke,
            "distance": int(distance),
            "pool": pool,
            "heatmap_swimmer": None,
            "corridor_swimmer_name": swimmer_name,
            "corridor_swimmer_yob": int(swimmer_yob),
            "pacing_swimmers": [],
            "chronos_sample_size": int(chronos_sample_size),
        }

    def collect_tasks(self) -> List[CorridorTask]:
        """
        Transforme le cache des nageurs/événements en une liste de tâches.
        Liste (stroke, distance, pool, nom_nageur, yob, chronos_sample_size) pour préfetch couloir.
        Respecte max_renders (0 = pas de plafond).
        """
        chronos = int(self.app.selected_chronos_sample_size)
        tasks: List[CorridorTask] = []
        for stroke, by_d in self.app._event_swimmers_cache.items():
            if not isinstance(stroke, str) or not isinstance(by_d, dict):
                continue
            for d_str, by_pool in by_d.items():
                if not isinstance(d_str, str) or not isinstance(by_pool, dict):
                    continue
                try:
                    d_i = int(d_str)
                except ValueError:
                    continue
                for pool, swimmers_payload in by_pool.items():
                    if not isinstance(pool, str):
                        continue
                    if isinstance(swimmers_payload, dict):
                        labels = swimmers_payload.get("all", [])
                    elif isinstance(swimmers_payload, list):
                        labels = swimmers_payload
                    else:
                        continue
                    for label in labels:
                        if not isinstance(label, str):
                            continue
                        name, yob = self.app._parse_corridor_swimmer_label(label)
                        if name is None or yob is None:
                            continue
                        tasks.append((stroke, d_i, pool, name, yob, chronos))
                        if self.max_renders > 0 and len(tasks) >= self.max_renders:
                            return tasks
        return tasks

    def compute_render(self, task: CorridorTask) -> Optional[CorridorRender]:
        """
        Exécute un calcul complet pour une tâche
        Retourne (render_key, chart_id, options, status, chart_title, row_count, image_base64, error).
        """
        stroke, distance, pool, nom, yob, chronos_sz = task
        options = self.corridor_prefetch_render_options_dict(
            stroke, int(distance), pool, nom, int(yob), chronos_sz
        )
        chart_id, render_key = self.app._render_key_for_category_graph_options(
            self.corridor_category, self.corridor_graph_name, options
        )
        graph_svc = ServiceGraphe()
        df_scope = _materialize_df_scope(
            self.app.df_nav, self.corridor_graph_name, stroke, int(distance), pool
        )
        if df_scope.empty:
            return (
                render_key,
                chart_id,
                options,
                "empty_scope",
                self.corridor_graph_name,
                0,
                None,
                None,
            )
        df_filtered = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
        try:
            fig, chart_title = graph_svc.desktop_build_figure(
                self.corridor_graph_name,
                df=self.app.df,
                df_scope=df_scope,
                df_filtered=df_filtered,
                stroke=stroke,
                distance=int(distance),
                pool=pool,
                selected_distance=int(distance),
                selected_chronos_sample_size=chronos_sz,
                selected_pacing_swimmers=[],
                selected_heatmap_swimmer=None,
                selected_corridor_swimmer_name=nom,
                selected_corridor_swimmer_yob=int(yob),
            )
        except Exception as exc:
            return (
                render_key,
                chart_id,
                options,
                "error",
                self.corridor_graph_name,
                len(df_scope),
                None,
                str(exc),
            )

        if fig is None:
            return (
                render_key,
                chart_id,
                options,
                "no_figure",
                chart_title,
                len(df_scope),
                None,
                None,
            )

        image_base64 = _figure_to_base64(fig)
        plt.close(fig)
        return (
            render_key,
            chart_id,
            options,
            "ok",
            chart_title,
            len(df_scope),
            image_base64,
            None,
        )

    def register_render(
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
        """Enregistre un résultat dans les caches mémoire de l’app."""
        with self.app._registry_json_lock:
            self.app.graph_render_registry[render_key] = {
                "id": chart_id,
                "name": self.corridor_graph_name,
                "category": self.corridor_category,
                "method": f"render_{_slugify(self.corridor_graph_name)}",
                "status": status,
                "chart_title": chart_title,
                "row_count": int(row_count),
                "error": error,
                "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "options": options,
                "image_base64": image_base64,
            }
            if image_base64:
                self.app.chart_image_cache[render_key] = image_base64
        if not skip_json_write:
            self.app._write_corridor_graphs_json()

    def _error_result_for_task(
        self,
        task: CorridorTask,
        exc: Exception,
    ) -> CorridorRender:
        """Convertit une exception en résultat “propre” de type CorridorRender avec status="error"""
        stroke, distance, pool, nom, yob, chronos_sz = task
        options = self.corridor_prefetch_render_options_dict(
            stroke, int(distance), pool, nom, int(yob), chronos_sz
        )
        _, render_key = self.app._render_key_for_category_graph_options(
            self.corridor_category, self.corridor_graph_name, options
        )
        return (
            render_key,
            f"{_slugify(self.corridor_category)}__{_slugify(self.corridor_graph_name)}",
            options,
            "error",
            self.corridor_graph_name,
            0,
            None,
            str(exc),
        )

    def _ingest_prefetch_result(self, result: CorridorRender) -> None:
        """Prend un résultat final, l’enregistre si utile (status ok + image), puis met à jour la progression UI couloir."""
        (
            render_key,
            chart_id,
            options,
            status,
            chart_title,
            row_count,
            image_base64,
            error,
        ) = result
        if status == "ok" and image_base64:
            self.register_render(
                render_key=render_key,
                chart_id=chart_id,
                options=options,
                chart_title=chart_title,
                status=status,
                row_count=row_count,
                image_base64=image_base64,
                error=error,
                skip_json_write=True,
            )
        self.app._advance_startup_corridor(
            str(options.get("corridor_swimmer_name", "")),
            units=1,
            show_graph_progress=True,
        )

    @staticmethod
    def _recommended_worker_count(task_count: int) -> int:
        """Choisit automatiquement le nombre de workers selon le CPU."""
        if task_count <= 0:
            return 1
        cpu_count = os.cpu_count() or 1 # 14
        cap = max(1, min(16, cpu_count))
        return max(1, min(cap, int(task_count))) # si task_count = 100 alors on aura workers = 14 (pour cpu_count = 14)

    async def _prefetch_pending_async(self, pending: List[CorridorTask]) -> None:
        """
        Orchestration parallèle via asyncio: crée un thread pool, lance chaque calcul via run_in_executor, récupère les résultats avec as_completed, ingère chaque résultat au fil de l’eau.
        """
        worker_count = 1 # self._recommended_worker_count(len(pending))
        print("le nombre de pending est ",len(pending))
        loop = asyncio.get_running_loop() # récupère la boucle asyncio active

        async def _run_one(executor: concurrent.futures.ThreadPoolExecutor, task: CorridorTask) -> Tuple[CorridorTask, Optional[CorridorRender], Optional[Exception]]:
            """
            coroutine interne qui exécute une tâche CPU/blocking dans le ThreadPoolExecutor via loop.run_in_executor(...), puis renvoie un triplet :
            (task, result, None) si succès
            (task, None, exc) si erreur capturée
            """
            try:
                result = await loop.run_in_executor(executor, self.compute_render, task)
                return task, result, None
            except Exception as exc:
                return task, None, exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            coros = [_run_one(executor, task) for task in pending]
            for done in asyncio.as_completed(coros):
                task, result, exc = await done
                if exc is not None:
                    result = self._error_result_for_task(task, exc)
                if result is None:
                    continue
                self._ingest_prefetch_result(result)

    def prefetch_skip_existing(self, tasks: List[CorridorTask]) -> None:
        """Précalcule les graphes couloir ; ignore les entrées déjà OK dans le JSON."""
        if not tasks or self.app.df.empty:
            return

        pending: List[CorridorTask] = []
        for task in tasks:
            stroke, distance, pool, nom, yob, chronos_sz = task
            options = self.corridor_prefetch_render_options_dict(
                stroke, int(distance), pool, nom, int(yob), chronos_sz
            )
            _, render_key = self.app._render_key_for_category_graph_options(
                self.corridor_category, self.corridor_graph_name, options
            )
            with self.app._registry_json_lock:
                cached = self.app.graph_render_registry.get(render_key)
            img = cached.get("image_base64") if isinstance(cached, dict) else None
            if (
                cached
                and cached.get("status") == "ok"
                and isinstance(img, str)
                and len(img) > 0
            ):
                with self.app._registry_json_lock:
                    self.app.chart_image_cache[render_key] = img
                self.app._advance_startup_corridor(
                    f"{stroke} {distance} {pool} — {nom}",
                    units=1,
                    show_graph_progress=True,
                )
                continue
            pending.append(task)

        if pending:
            try:
                asyncio.run(self._prefetch_pending_async(pending))
            except RuntimeError:
                # Impossible d'utiliser asyncio.run si une boucle existe déjà.
                # Dans ce contexte synchrone, on n'effectue pas de fallback.
                pass

        if not getattr(self.app, "_defer_prefetch_json_write", False):
            self.app._write_corridor_graphs_json()
