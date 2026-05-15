"""Barres de progression au démarrage (chargement prefetch) pour l’UI Flet."""

from __future__ import annotations

import threading
import time

import flet as ft


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


class TriplePrefetchProgress:
    """Trois barres de progression en parallèle pour le démarrage."""

    def __init__(
        self,
        page: ft.Page,
        total_left: int,
        total_middle: int,
        total_right: int,
        left_path: str,
        middle_path: str,
        right_path: str,
        *,
        left_header: str = "Graphes — prefetched_graphs.json",
        middle_header: str = "Nageurs événements — prefetched_event_swimmers.json",
        right_header: str = "Parquet USA Swimming",
        left_progress_label: str = "Graphes",
        middle_progress_label: str = "Event swimmers",
        right_progress_label: str = "Parquet",
    ) -> None:
        self.page = page
        self._lock = threading.Lock()
        self.left_total = max(1, int(total_left))
        self.middle_total = max(1, int(total_middle))
        self.right_total = max(1, int(total_right))
        self.left_done = 0
        self.middle_done = 0
        self.right_done = 0
        self.left_progress_label = left_progress_label
        self.middle_progress_label = middle_progress_label
        self.right_progress_label = right_progress_label

        self.left_pb = ft.ProgressBar(width=280, value=0.0, color="#f8fafc", bgcolor="#1f2937")
        self.middle_pb = ft.ProgressBar(width=280, value=0.0, color="#93c5fd", bgcolor="#1f2937")
        self.right_pb = ft.ProgressBar(width=280, value=0.0, color="#34d399", bgcolor="#1f2937")

        self.left_pct = ft.Text("0%", size=14, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.middle_pct = ft.Text("0%", size=14, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.right_pct = ft.Text("0%", size=14, weight=ft.FontWeight.BOLD, color="#f8fafc")

        self.left_detail = ft.Text("…", size=11, color="#9ca3af")
        self.middle_detail = ft.Text("…", size=11, color="#9ca3af")
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
                            self._build_panel(
                                header=left_header,
                                path=left_path,
                                progress=self.left_pb,
                                percent=self.left_pct,
                                detail=self.left_detail,
                            ),
                            self._build_panel(
                                header=middle_header,
                                path=middle_path,
                                progress=self.middle_pb,
                                percent=self.middle_pct,
                                detail=self.middle_detail,
                            ),
                            self._build_panel(
                                header=right_header,
                                path=right_path,
                                progress=self.right_pb,
                                percent=self.right_pct,
                                detail=self.right_detail,
                            ),
                        ],
                        expand=True,
                        alignment=ft.MainAxisAlignment.SPACE_AROUND,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    @staticmethod
    def _build_panel(
        *,
        header: str,
        path: str,
        progress: ft.ProgressBar,
        percent: ft.Text,
        detail: ft.Text,
    ) -> ft.Control:
        return ft.Container(
            expand=True,
            content=ft.Column(
                [
                    ft.Text(header, size=13, weight=ft.FontWeight.BOLD, color="#e5e7eb"),
                    ft.Text(path, size=10, color="#6b7280"),
                    progress,
                    percent,
                    detail,
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def mount(self) -> None:
        self.page.bgcolor = "#000000"
        self.page.clean()
        self.page.add(self.container)
        self.page.update()
        time.sleep(0.06)

    def _flush_slot(
        self,
        *,
        progress_bar: ft.ProgressBar,
        percent_text: ft.Text,
        detail_text: ft.Text,
        ratio: float,
        detail_str: str,
    ) -> None:
        page = self.page

        async def _run() -> None:
            progress_bar.value = ratio
            percent_text.value = f"{int(round(ratio * 100))}%"
            detail_text.value = detail_str
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
            detail_str = f"{self.left_progress_label} : {n}/{t} — {detail}"
        else:
            detail_str = f"{n}/{t} — {detail}"
        self._flush_slot(
            progress_bar=self.left_pb,
            percent_text=self.left_pct,
            detail_text=self.left_detail,
            ratio=ratio,
            detail_str=detail_str,
        )

    def advance_middle(
        self, detail: str, units: int = 1, *, show_graph_progress: bool = True
    ) -> None:
        with self._lock:
            self.middle_done += max(int(units), 0)
            ratio = min(self.middle_done / self.middle_total, 1.0)
            n, t = self.middle_done, self.middle_total
        if show_graph_progress:
            detail_str = f"{self.middle_progress_label} : {n}/{t} — {detail}"
        else:
            detail_str = f"{n}/{t} — {detail}"
        self._flush_slot(
            progress_bar=self.middle_pb,
            percent_text=self.middle_pct,
            detail_text=self.middle_detail,
            ratio=ratio,
            detail_str=detail_str,
        )

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
        self._flush_slot(
            progress_bar=self.right_pb,
            percent_text=self.right_pct,
            detail_text=self.right_detail,
            ratio=ratio,
            detail_str=detail_str,
        )

    def close_gap_left(self, detail: str = "Terminé") -> None:
        with self._lock:
            gap = self.left_total - self.left_done
        if gap > 0:
            self.advance_left(detail, units=gap, show_graph_progress=True)

    def close_gap_middle(self, detail: str = "Terminé") -> None:
        with self._lock:
            gap = self.middle_total - self.middle_done
        if gap > 0:
            self.advance_middle(detail, units=gap, show_graph_progress=True)

    def close_gap_right(self, detail: str = "Terminé") -> None:
        with self._lock:
            gap = self.right_total - self.right_done
        if gap > 0:
            self.advance_right(detail, units=gap, show_graph_progress=True)

    def reconfigure_middle_total(self, total_units: int, *, reset_done: bool = True) -> None:
        with self._lock:
            self.middle_total = max(1, int(total_units))
            if reset_done:
                self.middle_done = 0
        self._flush_slot(
            progress_bar=self.middle_pb,
            percent_text=self.middle_pct,
            detail_text=self.middle_detail,
            ratio=0.0,
            detail_str=f"0/{self.middle_total} — Initialisation...",
        )

    def reconfigure_right_total(self, total_units: int, *, reset_done: bool = True) -> None:
        with self._lock:
            self.right_total = max(1, int(total_units))
            if reset_done:
                self.right_done = 0
        self._flush_slot(
            progress_bar=self.right_pb,
            percent_text=self.right_pct,
            detail_text=self.right_detail,
            ratio=0.0,
            detail_str=f"0/{self.right_total} — Initialisation...",
        )
