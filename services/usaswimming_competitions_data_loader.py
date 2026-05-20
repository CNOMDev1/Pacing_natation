from __future__ import annotations
import importlib.util
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
import pandas as pd

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_USASWIMMING_COMPETITIONS_DIR = (_PROJECT_DIR / "data" / "processed" / "usaswimming")
DEFAULT_USASWIMMING_PARQUET_DIR = (DEFAULT_USASWIMMING_COMPETITIONS_DIR / "_parquet_cache")


def _default_cache_build_workers() -> int:
    """Limite le parallélisme de conversion : chaque année charge tout le JSON en RAM."""
    return min(2, os.cpu_count() or 1)


def _default_parquet_engine() -> str:
    if importlib.util.find_spec("pyarrow") is not None:
        return "pyarrow"
    raise ImportError("Aucun moteur Parquet detecte.")


class UsaswimmingCompetitionsDataLoader:
    """Convertit les JSON USA Swimming en Parquet, puis charge uniquement le cache Parquet."""
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        parquet_dir: Optional[Path] = None,
        max_workers: Optional[int] = None,
        cache_build_max_workers: Optional[int] = None,
    ) -> None:
        self.base_dir = (base_dir if base_dir is not None else DEFAULT_USASWIMMING_COMPETITIONS_DIR)
        self.parquet_dir = (parquet_dir if parquet_dir is not None else DEFAULT_USASWIMMING_PARQUET_DIR)
        self.max_workers = max_workers
        self.cache_build_max_workers = (
            cache_build_max_workers
            if cache_build_max_workers is not None
            else _default_cache_build_workers()
        )
        self.parquet_engine = _default_parquet_engine()

    @staticmethod
    def _normalize_swimmers(swimmers: Any) -> List[Dict[str, Any]]:
        """Uniformise le champ swimmer en une list[dict]"""
        if isinstance(swimmers, dict):
            return [swimmers]
        if isinstance(swimmers, list):
            return [item for item in swimmers if isinstance(item, dict)]
        return []

    @classmethod
    def _serialize_swimmers(cls, swimmers: Any) -> str:
        """Convertit la liste de nageurs en chaine JSON pour le stockage Parquet (Parquet gère mal les listes de dict imbriquées)"""
        return json.dumps(cls._normalize_swimmers(swimmers), ensure_ascii=False)

    @classmethod
    def _deserialize_swimmers(cls, swimmers: Any) -> List[Dict[str, Any]]:
        """Reconvertit une valeur lue depuis Parquet en list[dict]"""
        if isinstance(swimmers, list):
            return cls._normalize_swimmers(swimmers)
        if isinstance(swimmers, dict):
            return [swimmers]
        if isinstance(swimmers, str) and swimmers.strip():
            try:
                return cls._normalize_swimmers(json.loads(swimmers))
            except json.JSONDecodeError:
                return []
        return []

    @classmethod
    def _build_rows_from_comp(cls, comp: Dict[str, Any], source_year: Optional[int] = None, source_file: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parcourt une compétition JSON (epreuves → performances) et produit une ligne par performance"""
        rows: List[Dict[str, Any]] = []

        for epreuve in comp.get("epreuves", []):
            for perf in epreuve.get("performances", []):
                swimmers = cls._normalize_swimmers(perf.get("swimmer", []))
                primary_swimmer = swimmers[0] if swimmers else {}

                row = {
                    "Year": source_year,
                    "SourceFile": source_file,
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
                    "SwimTime": perf.get("SwimTime"),
                    "SwimTimeSeconds": perf.get("SwimTimeSeconds"),
                    "Status": perf.get("Status"),
                    "Speed": perf.get("Speed"),
                    "TimeStandard": perf.get("TimeStandard"),
                    "AgeGroup": perf.get("AgeGroup"),
                    "Session": perf.get("Session"),
                    "swimmer": swimmers,
                    "Name": primary_swimmer.get("Name"),
                    "Gender": primary_swimmer.get("Gender"),
                    "Year_of_birth": primary_swimmer.get("Year_of_birth"),
                    "Age_at_Performance": primary_swimmer.get("Age_at_Performance"),
                    "Nationality": primary_swimmer.get("Nationality"),
                }
                rows.append(row)

        return rows

    def _load_single_file(self, file: Path, source_year: Optional[int]) -> List[Dict[str, Any]]:
        """Lit un fichier .json, appelle _build_rows_from_comp"""
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            return []
        return self._build_rows_from_comp(comp=comp, source_year=source_year, source_file=file.name)

    def _load_year_directory(self, year_dir: Path) -> List[Dict[str, Any]]:
        """Charge tous les *.json d'un dossier année et agrège les lignes"""
        try:
            source_year = int(year_dir.name)
        except ValueError:
            source_year = None

        rows: List[Dict[str, Any]] = []
        for file in sorted(year_dir.glob("*.json")):
            rows.extend(self._load_single_file(file, source_year=source_year))
        return rows

    def _resolve_year_directories(self, years: Optional[Iterable[int | str]] = None) -> List[Path]:
        """filtre / liste les dossiers année sous base_dir """
        if not self.base_dir.exists():
            return []

        if years is None:
            return sorted(path for path in self.base_dir.iterdir() if path.is_dir())

        requested_years = {str(year) for year in years}
        return sorted(
            path
            for path in self.base_dir.iterdir()
            if path.is_dir() and path.name in requested_years
        )

    def available_years(self, years: Optional[Iterable[int | str]] = None) -> List[str]:
        """Retourne les annees source JSON disponibles pour la conversion Parquet."""
        return [year_dir.name for year_dir in self._resolve_year_directories(years=years)]

    def _resolve_parquet_years(self, years: Optional[Iterable[int | str]] = None) -> List[str]:
        """filtre/liste les années déjà converties en Parquet"""
        if not self.parquet_dir.exists():
            return []

        if years is None:
            return sorted(path.stem for path in self.parquet_dir.glob("*.parquet"))

        requested_years = {str(year) for year in years}
        return sorted(
            year
            for year in requested_years
            if self._parquet_path_for_year(year).exists()
        )

    def available_parquet_years(self, years: Optional[Iterable[int | str]] = None) -> List[str]:
        """Retourne les annees disponibles dans le cache Parquet."""
        return self._resolve_parquet_years(years=years)

    def _parquet_path_for_year(self, year: int | str) -> Path:
        """Construit le chemin du fichier Parquet associe a une annee."""
        return self.parquet_dir / f"{year}.parquet"

    @staticmethod
    def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        normalized = df.copy()
        if "SwimDate" in normalized.columns:
            normalized["SwimDate"] = pd.to_datetime(
                normalized["SwimDate"], errors="coerce"
            )
        if "SwimTimeSeconds" in normalized.columns:
            normalized["SwimTimeSeconds"] = pd.to_numeric(
                normalized["SwimTimeSeconds"], errors="coerce"
            )
        if "Year" in normalized.columns:
            normalized["Year"] = pd.to_numeric(
                normalized["Year"], errors="coerce"
            ).astype("Int64")
        return normalized

    @classmethod
    def _prepare_dataframe_for_parquet(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Avant écriture : sérialise la colonne swimmer en JSON string."""
        prepared = df.copy()
        if "swimmer" in prepared.columns:
            prepared["swimmer"] = prepared["swimmer"].apply(cls._serialize_swimmers)
        return prepared

    @classmethod
    def _restore_dataframe_from_parquet(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Après lecture : désérialise swimmer, puis applique _normalize_dataframe."""
        restored = df.copy()
        if "swimmer" in restored.columns:
            restored["swimmer"] = restored["swimmer"].apply(cls._deserialize_swimmers)
        return cls._normalize_dataframe(restored)

    def _load_from_json_years(self, year_dirs: List[Path]) -> pd.DataFrame:
        """Charge plusieurs dossiers année en parallèle (ThreadPoolExecutor) → un seul DataFrame normalisé"""
        if not year_dirs:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for year_rows in executor.map(self._load_year_directory, year_dirs):
                rows.extend(year_rows)

        return self._normalize_dataframe(pd.DataFrame(rows))

    def _read_single_parquet(
        self,
        parquet_file: Path,
        columns: Optional[List[str]] = None,
        event: Optional[str] = None,
    ) -> pd.DataFrame:
        read_kwargs: Dict[str, Any] = {"engine": self.parquet_engine}
        if columns is not None:
            read_columns = list(dict.fromkeys(columns))
            if event is not None and "Event" not in read_columns:
                read_columns.insert(0, "Event")
            read_kwargs["columns"] = read_columns
        if event is not None:
            read_kwargs["filters"] = [("Event", "==", str(event).strip())]

        try:
            df = pd.read_parquet(parquet_file, **read_kwargs)
        except Exception:
            return pd.DataFrame()
        return self._restore_dataframe_from_parquet(df)

    def _load_from_parquet_years(
        self,
        years: List[int | str],
        columns: Optional[List[str]] = None,
        event: Optional[str] = None,
    ) -> pd.DataFrame:
        """Lit plusieurs années en parallèle et concatène."""
        parquet_files = [
            self._parquet_path_for_year(year)
            for year in years
            if self._parquet_path_for_year(year).exists()
        ]
        if not parquet_files:
            return pd.DataFrame()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            frames = list(
                executor.map(
                    lambda path: self._read_single_parquet(
                        path, columns=columns, event=event
                    ),
                    parquet_files,
                )
            )

        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _build_parquet_for_year_directory(
        self,
        year_dir: Path,
        *,
        index: int,
        total_years: int,
        overwrite: bool,
        progress_callback: Optional[Callable[[str], None]] = None,
        progress_step_callback: Optional[Callable[[str, int, int], None]] = None,
        progress_lock: Optional[threading.Lock] = None,
    ) -> Optional[Path]:
        """Convertit un dossier année JSON en fichier Parquet (appelé en parallèle)."""
        def _report(message: str, *, year_finished: bool = False) -> None:
            if progress_lock is not None:
                progress_lock.acquire()
            try:
                if progress_callback is not None:
                    progress_callback(message)
                if year_finished and progress_step_callback is not None:
                    progress_step_callback(message, index, total_years)
            finally:
                if progress_lock is not None:
                    progress_lock.release()

        parquet_file = self._parquet_path_for_year(year_dir.name)
        json_file_count = len(list(year_dir.glob("*.json")))

        if parquet_file.exists() and not overwrite:
            _report(
                f"[{index}/{total_years}] {year_dir.name}: "
                f"cache deja present ({parquet_file.name}), ignore.",
                year_finished=True,
            )
            return parquet_file

        start_time = time.perf_counter()
        _report(
            f"[{index}/{total_years}] {year_dir.name}: "
            f"conversion de {json_file_count} fichier(s) JSON...",
        )

        year_df = self._load_from_json_years([year_dir])
        if year_df.empty:
            _report(
                f"[{index}/{total_years}] {year_dir.name}: "
                "aucune ligne detectee, aucun Parquet ecrit.",
                year_finished=True,
            )
            return None

        parquet_df = self._prepare_dataframe_for_parquet(year_df)
        parquet_df.to_parquet(
            parquet_file,
            engine=self.parquet_engine,
            index=False,
        )
        elapsed = time.perf_counter() - start_time
        _report(
            f"[{index}/{total_years}] {year_dir.name}: "
            f"{len(year_df):,} ligne(s) -> {parquet_file.name} "
            f"en {elapsed:.1f}s".replace(",", " "),
            year_finished=True,
        )
        return parquet_file

    def build_parquet_cache(
        self,
        years: Optional[Iterable[int | str]] = None,
        overwrite: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
        progress_step_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> List[Path]:
        """Construit un cache Parquet par annee sous data/processed/usaswimming."""
        year_dirs = self._resolve_year_directories(years=years)
        if not year_dirs:
            return []

        self.parquet_dir.mkdir(parents=True, exist_ok=True)

        total_years = len(year_dirs)
        progress_lock = (
            threading.Lock()
            if progress_callback is not None or progress_step_callback is not None
            else None
        )
        written_files: List[Path] = []

        with ThreadPoolExecutor(max_workers=self.cache_build_max_workers) as executor:
            futures = [
                executor.submit(
                    self._build_parquet_for_year_directory,
                    year_dir,
                    index=index,
                    total_years=total_years,
                    overwrite=overwrite,
                    progress_callback=progress_callback,
                    progress_step_callback=progress_step_callback,
                    progress_lock=progress_lock,
                )
                for index, year_dir in enumerate(year_dirs, start=1)
            ]
            for future in futures:
                parquet_file = future.result()
                if parquet_file is not None:
                    written_files.append(parquet_file)

        return sorted(written_files, key=lambda path: path.stem)

    def available_events(self, years: Optional[Iterable[int | str]] = None) -> List[str]:
        """Liste triée des épreuves présentes dans le cache Parquet."""
        parquet_years = self._resolve_parquet_years(years=years)
        events: set[str] = set()
        for year in parquet_years:
            parquet_file = self._parquet_path_for_year(year)
            try:
                events_df = pd.read_parquet(
                    parquet_file,
                    columns=["Event"],
                    engine=self.parquet_engine,
                )
            except Exception:
                continue
            if events_df.empty or "Event" not in events_df.columns:
                continue
            for value in events_df["Event"].dropna().astype(str).str.strip().unique():
                if value:
                    events.add(value)
        return sorted(events)

    def list_names_for_event(
        self,
        event: str,
        *,
        gender: Optional[str] = None,
        years: Optional[Iterable[int | str]] = None,
    ) -> List[str]:
        """Noms distincts pour une épreuve (optionnellement filtrés par genre)."""
        columns = ["Name", "Gender"]
        df = self.load(years=years, columns=columns, event=event)
        if df.empty or "Name" not in df.columns:
            return []
        names = df["Name"].dropna().astype(str).str.strip()
        if gender and gender.upper() in ("F", "M") and "Gender" in df.columns:
            g = df["Gender"].astype(str).str.strip().str.upper()
            names = df.loc[g == gender.upper(), "Name"].dropna().astype(str).str.strip()
        return sorted({n for n in names if n})

    def load(
        self,
        years: Optional[Iterable[int | str]] = None,
        columns: Optional[Iterable[str]] = None,
        event: Optional[str] = None,
    ) -> pd.DataFrame:
        """Charge les annees demandees depuis le cache Parquet uniquement.

        columns: sous-ensemble de colonnes (evite de lire swimmer, Meet, etc.).
        event: filtre Parquet sur Event (ex. "100 FR LCM") — beaucoup plus rapide.
        """
        parquet_years = self._resolve_parquet_years(years=years)
        if not parquet_years:
            return pd.DataFrame()
        column_list = list(columns) if columns is not None else None
        return self._load_from_parquet_years(
            parquet_years, columns=column_list, event=event
        )
