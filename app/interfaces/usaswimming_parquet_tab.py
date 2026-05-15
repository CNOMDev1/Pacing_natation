from __future__ import annotations
import json
import unicodedata
from pathlib import Path
from typing import Any, Optional
import flet as ft
import pandas as pd
from project_path import ensure_project_imports

ensure_project_imports()

from services.usaswimming_competitions_data_loader import (
    DEFAULT_USASWIMMING_PARQUET_DIR,
    UsaswimmingCompetitionsDataLoader,
)
from swimmer_search import SwimmerSearch

DEFAULT_PREVIEW_LIMIT = 25
MAX_CELL_LENGTH = 120
PANEL_BG = "#0b1220"
CARD_BG = "#111827"
CARD_BORDER = "#243041"
TEXT_MUTED = "#94a3b8"
TEXT_MAIN = "#e2e8f0"
HEADER_BG = "#0f172a"
SUCCESS_BG = "#052e16"
WARNING_BG = "#3f2a06"
ERROR_BG = "#450a0a"
PREFERRED_COLUMN_GROUPS = (
    ("name",),
    ("gender",),
    ("swimtime",),
    ("swimtimesecondes", "swimtimeseconds"),
    ("stroke",),
    ("distance",),
    ("course",),
)
TRAILING_COLUMN_GROUPS = (("swimmer",),)
SWIMMER_SEARCH_COLUMN_ALIASES = ("name", "swimmer", "swimmer_name", "swimmername")


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        text = str(value)
    else:
        try:
            if pd.isna(value):
                return ""
        except TypeError:
            pass
        text = str(value)

    text = " ".join(text.splitlines())
    if len(text) > MAX_CELL_LENGTH:
        return f"{text[:MAX_CELL_LENGTH - 3]}..."
    return text


def _parquet_overview(parquet_file: Path) -> tuple[int, int]:
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(parquet_file)
        return parquet.metadata.num_rows, len(parquet.schema_arrow.names)
    except Exception:
        df = pd.read_parquet(parquet_file)
        return len(df), len(df.columns)


def _normalize_search_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(value).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


class UsaswimmingParquetTab:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.parquet_dir: Path = DEFAULT_USASWIMMING_PARQUET_DIR
        self.parquet_files: list[Path] = []
        self.files_by_name: dict[str, Path] = {}
        self.current_file: Optional[Path] = None
        self.current_df: pd.DataFrame = pd.DataFrame()
        self.filtered_df: pd.DataFrame = pd.DataFrame()
        self.corridor_swimmer_search_query: str = ""
        self._cache_check_started = False

        self.path_field = ft.TextField(
            label="Dossier parquet",
            value=str(self.parquet_dir),
            expand=True,
            filled=True,
            bgcolor=CARD_BG,
            border_color=CARD_BORDER,
        )
        self.file_dropdown = ft.Dropdown(
            label="Fichier parquet",
            expand=True,
            filled=True,
            bgcolor=CARD_BG,
            border_color=CARD_BORDER,
            on_select=self._on_file_change,
        )
        self.limit_dropdown = ft.Dropdown(
            label="Nb lignes",
            width=150,
            value=str(DEFAULT_PREVIEW_LIMIT),
            filled=True,
            bgcolor=CARD_BG,
            border_color=CARD_BORDER,
            options=[
                ft.dropdown.Option("10"),
                ft.dropdown.Option("25"),
                ft.dropdown.Option("50"),
                ft.dropdown.Option("100"),
            ],
            on_select=self._on_limit_change,
        )
        self.swimmer_search = SwimmerSearch(
            self,
            width=460,
            label_text="Rechercher un nageur",
            tooltip="Nom du nageur",
        )
        self.swimmer_search.set_visible(True)
        self.swimmer_search.input.disabled = True

        self.status_text = ft.Text(
            "Pret",
            size=12,
            weight=ft.FontWeight.W_600,
            color="#bbf7d0",
        )
        self.status_badge = ft.Container(
            content=self.status_text,
            padding=ft.Padding(left=12, top=8, right=12, bottom=8),
            bgcolor=SUCCESS_BG,
            border=ft.border.all(1, "#166534"),
            border_radius=999,
        )

        self.total_files_value = ft.Text("0", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.total_size_value = ft.Text("0.00 Mo", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.row_count_value = ft.Text("0", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")
        self.column_count_value = ft.Text("0", size=24, weight=ft.FontWeight.BOLD, color="#f8fafc")

        self.table_canvas = ft.Row(
            controls=[self._build_empty_table("Aucune donnee disponible.")],
            scroll=ft.ScrollMode.AUTO,
        )
        self.table_host = ft.Column(
            controls=[self.table_canvas],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        self.content = ft.Container(
            expand=True,
            padding=20,
            bgcolor="#020617",
            content=ft.Column(
                controls=[
                    ft.Text(
                        "USA Swimming - lecteur parquet",
                        size=28,
                        weight=ft.FontWeight.BOLD,
                        color="#f8fafc",
                    ),
                    ft.Text(
                        "Explore le cache parquet dans une vue tabulaire propre et lisible.",
                        size=13,
                        color=TEXT_MUTED,
                    ),
                    ft.Container(
                        bgcolor=PANEL_BG,
                        border=ft.border.all(1, CARD_BORDER),
                        border_radius=16,
                        padding=16,
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        self.path_field,
                                        ft.ElevatedButton("Actualiser", on_click=self._refresh_files),
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.END,
                                ),
                                ft.Row(
                                    controls=[
                                        self.file_dropdown,
                                        self.limit_dropdown,
                                        self.status_badge,
                                    ],
                                    vertical_alignment=ft.CrossAxisAlignment.END,
                                ),
                                self.swimmer_search.container,
                            ],
                            spacing=14,
                        ),
                    ),
                    ft.ResponsiveRow(
                        controls=[
                            self._build_stat_card("Fichiers parquet", self.total_files_value, "Disponibles dans le dossier"),
                            self._build_stat_card("Taille totale", self.total_size_value, "Poids du cache"),
                            self._build_stat_card("Lignes", self.row_count_value, "Total du fichier courant"),
                            self._build_stat_card("Colonnes", self.column_count_value, "Structure du fichier"),
                        ],
                        spacing=12,
                        run_spacing=12,
                    ),
                    ft.Container(
                        expand=True,
                        bgcolor=PANEL_BG,
                        border=ft.border.all(1, CARD_BORDER),
                        border_radius=16,
                        padding=16,
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(
                                            "Table de donnees",
                                            size=16,
                                            weight=ft.FontWeight.BOLD,
                                            color="#f8fafc",
                                        ),
                                        ft.Text(
                                            "Defilement horizontal et vertical disponible",
                                            size=12,
                                            color=TEXT_MUTED,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Divider(height=1, color=CARD_BORDER),
                                ft.Container(
                                    expand=True,
                                    height=560,
                                    content=self.table_host,
                                ),
                            ],
                            spacing=12,
                            expand=True,
                        ),
                    ),
                ],
                expand=True,
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
            ),
        )

        self._refresh_files_impl(update_page=False)

    def build_view(self) -> ft.Control:
        return self.content

    @staticmethod
    def _is_default_parquet_dir(path: Path) -> bool:
        return path.resolve() == DEFAULT_USASWIMMING_PARQUET_DIR.resolve()

    def _safe_page_update(self) -> None:
        try:
            self.page.update()
        except RuntimeError:
            pass

    def start_background_cache_check(self) -> None:
        if self._cache_check_started:
            return

        requested_dir = Path(self.path_field.value or "").expanduser()
        if not self._is_default_parquet_dir(requested_dir):
            return

        self._cache_check_started = True
        self.page.run_thread(self._ensure_default_parquet_cache_in_background)

    def _ensure_default_parquet_cache(self, requested_dir: Path) -> tuple[str, str] | None:
        if not self._is_default_parquet_dir(requested_dir):
            return None

        existing_files = (
            sorted(requested_dir.glob("*.parquet"))
            if requested_dir.exists() and requested_dir.is_dir()
            else []
        )
        if existing_files:
            return None

        loader = UsaswimmingCompetitionsDataLoader(parquet_dir=requested_dir)
        try:
            written_files = loader.build_parquet_cache()
        except Exception as exc:
            return (
                f"Impossible de creer automatiquement le cache parquet: {exc}",
                "#fca5a5",
            )

        if written_files:
            return (
                f"Cache parquet cree automatiquement ({len(written_files)} fichier(s)).",
                "#86efac",
            )

        return (
            "Cache parquet absent et aucune donnee source n'a pu etre convertie.",
            "#fbbf24",
        )

    def _ensure_default_parquet_cache_in_background(self) -> None:
        requested_dir = Path(self.path_field.value or "").expanduser()
        status = self._ensure_default_parquet_cache(requested_dir)
        if status is None:
            return

        self._refresh_files_impl(update_page=False)
        self._set_status(status[0], color=status[1])
        self._safe_page_update()

    def _build_stat_card(self, title: str, value: ft.Text, subtitle: str) -> ft.Control:
        return ft.Container(
            col={"xs": 12, "sm": 6, "lg": 3},
            bgcolor=CARD_BG,
            border=ft.border.all(1, CARD_BORDER),
            border_radius=16,
            padding=16,
            content=ft.Column(
                controls=[
                    ft.Text(title, size=12, color=TEXT_MUTED),
                    value,
                    ft.Text(subtitle, size=11, color="#64748b"),
                ],
                spacing=6,
            ),
        )

    def _build_empty_table(self, message: str) -> ft.Control:
        return ft.Container(
            width=960,
            padding=24,
            bgcolor=HEADER_BG,
            border=ft.border.all(1, CARD_BORDER),
            border_radius=12,
            content=ft.Column(
                controls=[
                    ft.Text("Apercu des donnees", size=16, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                    ft.Text(message, size=13, color=TEXT_MUTED),
                ],
                spacing=6,
            ),
        )

    def _candidate_swimmer_columns(self, df: pd.DataFrame) -> list[Any]:
        return [
            column
            for column in df.columns
            if str(column).strip().lower() in SWIMMER_SEARCH_COLUMN_ALIASES
        ]

    def _extract_swimmer_labels_from_value(self, value: Any) -> list[str]:
        if value is None:
            return []
        try:
            if pd.isna(value):
                return []
        except (TypeError, ValueError):
            pass

        if isinstance(value, dict):
            for key in ("Name", "name"):
                label = value.get(key)
                if label:
                    return [" ".join(str(label).split())]
            return []

        if isinstance(value, list):
            labels: list[str] = []
            for item in value:
                labels.extend(self._extract_swimmer_labels_from_value(item))
            return labels

        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return []
            if raw_value[:1] in ("[", "{"):
                try:
                    return self._extract_swimmer_labels_from_value(json.loads(raw_value))
                except json.JSONDecodeError:
                    pass
            return [" ".join(raw_value.split())]

        return [" ".join(str(value).split())]

    @staticmethod
    def _matches_swimmer_query(label: str, query: str) -> bool:
        search_norm = _normalize_search_text(query)
        if not search_norm:
            return True

        label_norm = _normalize_search_text(label)
        words = [word for word in label_norm.replace("(", " ").replace(")", " ").split() if word]
        if any(word.startswith(search_norm) for word in words):
            return True
        return search_norm in label_norm

    def _available_swimmer_labels(self, df: pd.DataFrame) -> list[str]:
        labels_by_norm: dict[str, str] = {}
        for column in self._candidate_swimmer_columns(df):
            for value in df[column].tolist():
                for label in self._extract_swimmer_labels_from_value(value):
                    normalized = _normalize_search_text(label)
                    if normalized and normalized not in labels_by_norm:
                        labels_by_norm[normalized] = label
        return sorted(labels_by_norm.values(), key=_normalize_search_text)

    def _sync_swimmer_search_state(self) -> None:
        if self.current_file is None or self.current_df.empty:
            self.swimmer_search.input.disabled = True
            self.swimmer_search.label.value = "Rechercher un nageur"
            self.swimmer_search.clear_suggestions()
            return

        search_columns = self._candidate_swimmer_columns(self.current_df)
        has_searchable_columns = bool(search_columns)
        self.swimmer_search.input.disabled = not has_searchable_columns
        self.swimmer_search.label.value = (
            "Rechercher un nageur"
            if has_searchable_columns
            else "Recherche nageur indisponible pour ce fichier"
        )
        if not has_searchable_columns:
            self.swimmer_search.clear_suggestions()
            return

        labels_all = self._available_swimmer_labels(self.current_df)
        event_key = (
            self.current_file.name,
            len(self.current_df),
            "|".join(str(column) for column in search_columns),
            str(len(labels_all)),
        )
        self.swimmer_search.maybe_sync_suggestions(labels_all, event_key)

    def _filter_dataframe_for_swimmer_query(self, df: pd.DataFrame) -> pd.DataFrame:
        query = (self.corridor_swimmer_search_query or "").strip()
        if df.empty or not query:
            return df

        search_columns = self._candidate_swimmer_columns(df)
        if not search_columns:
            return df

        matches = pd.Series(False, index=df.index)
        for column in search_columns:
            matches = matches | df[column].apply(
                lambda value: any(
                    self._matches_swimmer_query(label, query)
                    for label in self._extract_swimmer_labels_from_value(value)
                )
            )
        return df.loc[matches].copy()

    def _ordered_columns(self, columns: list[Any]) -> list[Any]:
        normalized_to_column: dict[str, Any] = {}
        for column in columns:
            key = str(column).strip().lower()
            if key not in normalized_to_column:
                normalized_to_column[key] = column

        prioritized: list[Any] = []
        for aliases in PREFERRED_COLUMN_GROUPS:
            for alias in aliases:
                column = normalized_to_column.get(alias)
                if column is not None and column not in prioritized:
                    prioritized.append(column)
                    break

        trailing: list[Any] = []
        for aliases in TRAILING_COLUMN_GROUPS:
            for alias in aliases:
                column = normalized_to_column.get(alias)
                if column is not None and column not in trailing:
                    trailing.append(column)
                    break

        remaining = [
            column for column in columns if column not in prioritized and column not in trailing
        ]
        return prioritized + remaining + trailing

    def _build_table(self, df: pd.DataFrame, limit: int) -> ft.Control:
        preview = df.head(limit).reset_index(drop=True)
        visible_columns = self._ordered_columns(list(preview.columns))
        preview = preview.loc[:, visible_columns]
        numeric_columns = {
            column for column in visible_columns if pd.api.types.is_numeric_dtype(df[column])
        }

        columns = [
            ft.DataColumn(
                label=ft.Text("Rang", color="#f8fafc", weight=ft.FontWeight.BOLD),
                numeric=True,
            )
        ]
        for column in visible_columns:
            columns.append(
                ft.DataColumn(
                    label=ft.Text(str(column), color="#f8fafc", weight=ft.FontWeight.BOLD),
                    numeric=column in numeric_columns,
                )
            )

        rows: list[ft.DataRow] = []
        for row_index, row in enumerate(preview.itertuples(index=False), start=1):
            cells = [
                ft.DataCell(
                    ft.Container(
                        width=56,
                        alignment=ft.Alignment(1, 0),
                        content=ft.Text(
                            str(row_index),
                            size=12,
                            color="#93c5fd",
                            weight=ft.FontWeight.W_600,
                        ),
                    )
                )
            ]
            for column_name, value in zip(visible_columns, row):
                is_numeric = column_name in numeric_columns
                cell_width = 140 if is_numeric else 220
                cells.append(
                    ft.DataCell(
                        ft.Container(
                            width=cell_width,
                            padding=ft.Padding(left=0, top=4, right=0, bottom=4),
                            alignment=ft.Alignment(1, 0) if is_numeric else ft.Alignment(-1, 0),
                            content=ft.Text(
                                _format_cell(value) or "-",
                                size=12,
                                color=TEXT_MAIN,
                                max_lines=3,
                                no_wrap=False,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        )
                    )
                )
            rows.append(
                ft.DataRow(
                    cells=cells,
                    color=HEADER_BG if row_index % 2 else CARD_BG,
                )
            )

        return ft.DataTable(
            columns=columns,
            rows=rows,
            column_spacing=18,
            horizontal_margin=16,
            divider_thickness=0.6,
            data_row_min_height=52,
            data_row_max_height=72,
            heading_row_height=52,
            heading_row_color=HEADER_BG,
            data_row_color=CARD_BG,
            bgcolor="#020617",
            border=ft.border.all(1, CARD_BORDER),
            border_radius=12,
            horizontal_lines=ft.BorderSide(1, CARD_BORDER),
            vertical_lines=ft.BorderSide(1, "#162032"),
            heading_text_style=ft.TextStyle(color="#f8fafc", size=13, weight=ft.FontWeight.BOLD),
            data_text_style=ft.TextStyle(color=TEXT_MAIN, size=12),
            show_bottom_border=True,
        )

    def _set_status(self, message: str, color: str = "#86efac") -> None:
        self.status_text.value = message
        self.status_text.color = color
        if color == "#fca5a5":
            self.status_badge.bgcolor = ERROR_BG
            self.status_badge.border = ft.border.all(1, "#991b1b")
        elif color == "#fbbf24":
            self.status_badge.bgcolor = WARNING_BG
            self.status_badge.border = ft.border.all(1, "#a16207")
        else:
            self.status_badge.bgcolor = SUCCESS_BG
            self.status_badge.border = ft.border.all(1, "#166534")

    def _selected_preview_limit(self) -> int:
        raw_value = self.limit_dropdown.value or str(DEFAULT_PREVIEW_LIMIT)
        try:
            return max(1, int(raw_value))
        except ValueError:
            return DEFAULT_PREVIEW_LIMIT

    def _set_directory_metrics(self, total_files: int, total_size_mb: float) -> None:
        self.total_files_value.value = str(total_files)
        self.total_size_value.value = f"{total_size_mb:.2f} Mo"

    def _set_table_content(self, control: ft.Control) -> None:
        self.table_canvas.controls = [control]

    def _clear_preview(self) -> None:
        self.current_file = None
        self.current_df = pd.DataFrame()
        self.filtered_df = pd.DataFrame()
        self.row_count_value.value = "0"
        self.column_count_value.value = "0"
        self._set_table_content(self._build_empty_table("Aucune donnee disponible."))
        self.swimmer_search.reset(clear_query=True)
        self.swimmer_search.input.disabled = True
        self.swimmer_search.label.value = "Rechercher un nageur"

    def _render_current_preview(self, *, row_count: Optional[int] = None, column_count: Optional[int] = None) -> None:
        if self.current_file is None or self.current_df.empty:
            self.filtered_df = pd.DataFrame()
            self._sync_swimmer_search_state()
            self._set_table_content(self._build_empty_table("Aucune donnee disponible."))
            return

        filtered_df = self._filter_dataframe_for_swimmer_query(self.current_df)
        self.filtered_df = filtered_df
        preview_limit = self._selected_preview_limit()
        preview_count = min(preview_limit, len(filtered_df))
        resolved_row_count = row_count if row_count is not None else len(self.current_df)
        resolved_column_count = (
            column_count if column_count is not None else len(self.current_df.columns)
        )

        self.row_count_value.value = str(resolved_row_count)
        self.column_count_value.value = str(resolved_column_count)
        self._sync_swimmer_search_state()
        query = (self.corridor_swimmer_search_query or "").strip()
        if filtered_df.empty:
            message = (
                f"Aucun nageur ne correspond a la recherche: {query}"
                if query
                else "Aucune donnee disponible."
            )
            self._set_table_content(self._build_empty_table(message))
            return
        self._set_table_content(self._build_table(filtered_df, preview_limit))

    def _refresh_filters_from_data(self) -> None:
        self._render_current_preview()
        self.page.update()

    def _on_confirm_corridor_swimmer(self, _event: ft.ControlEvent) -> None:
        self.corridor_swimmer_search_query = (self.swimmer_search.input.value or "").strip()
        self._refresh_filters_from_data()

    def _refresh_files_impl(self, *, update_page: bool) -> None:
        requested_dir = Path(self.path_field.value or "").expanduser()

        if not requested_dir.exists():
            self.parquet_files = []
            self.files_by_name = {}
            self.file_dropdown.options = []
            self.file_dropdown.value = None
            self._set_directory_metrics(0, 0.0)
            self._clear_preview()
            self._set_status(f"Dossier introuvable: {requested_dir}", color="#fca5a5")
            if update_page:
                self.page.update()
            return

        if not requested_dir.is_dir():
            self.parquet_files = []
            self.files_by_name = {}
            self.file_dropdown.options = []
            self.file_dropdown.value = None
            self._set_directory_metrics(0, 0.0)
            self._clear_preview()
            self._set_status(f"Le chemin n'est pas un dossier: {requested_dir}", color="#fca5a5")
            if update_page:
                self.page.update()
            return

        self.parquet_dir = requested_dir.resolve()
        self.parquet_files = sorted(self.parquet_dir.glob("*.parquet"))
        self.files_by_name = {parquet_file.name: parquet_file for parquet_file in self.parquet_files}
        self.file_dropdown.options = [
            ft.dropdown.Option(parquet_file.name) for parquet_file in self.parquet_files
        ]

        total_size_mb = (
            sum(parquet_file.stat().st_size for parquet_file in self.parquet_files) / (1024 * 1024)
            if self.parquet_files
            else 0.0
        )
        self._set_directory_metrics(len(self.parquet_files), total_size_mb)

        if not self.parquet_files:
            self.file_dropdown.value = None
            self._clear_preview()
            self._set_status("Aucun fichier parquet disponible.", color="#fbbf24")
            if update_page:
                self.page.update()
            return

        selected_name = self.file_dropdown.value
        if selected_name not in self.files_by_name:
            selected_name = self.parquet_files[0].name
            self.file_dropdown.value = selected_name

        self._load_file(self.files_by_name[selected_name])
        if update_page:
            self.page.update()

    def _refresh_files(self, _event: Optional[ft.ControlEvent] = None) -> None:
        self._refresh_files_impl(update_page=True)

    def _load_file(self, parquet_file: Path) -> None:
        try:
            row_count, column_count = _parquet_overview(parquet_file)
            df = pd.read_parquet(parquet_file)
        except Exception as exc:
            self.current_file = parquet_file
            self.current_df = pd.DataFrame()
            self.row_count_value.value = "0"
            self.column_count_value.value = "0"
            self._set_table_content(
                self._build_empty_table(f"Impossible de lire {parquet_file.name}: {exc}")
            )
            self._set_status(f"Impossible de lire {parquet_file.name}: {exc}", color="#fca5a5")
            return

        self.current_file = parquet_file
        self.current_df = df
        self._render_current_preview(row_count=row_count, column_count=column_count)
        self._set_status(f"{parquet_file.name} charge avec succes.")

    def _on_file_change(self, _event: ft.ControlEvent) -> None:
        selected_name = self.file_dropdown.value
        if not selected_name:
            self._clear_preview()
            self._set_status("Aucun fichier selectionne.", color="#fbbf24")
            self.page.update()
            return

        parquet_file = self.files_by_name.get(selected_name)
        if parquet_file is None:
            self._set_status("Fichier introuvable dans la liste.", color="#fca5a5")
            self.page.update()
            return

        self._load_file(parquet_file)
        self.page.update()

    def _on_limit_change(self, _event: ft.ControlEvent) -> None:
        if self.current_file is None or self.current_df.empty:
            self.page.update()
            return

        self._render_current_preview()
        self.page.update()


def build_usaswimming_parquet_tab(page: ft.Page) -> ft.Control:
    return UsaswimmingParquetTab(page).build_view()
