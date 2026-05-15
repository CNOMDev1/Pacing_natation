from __future__ import annotations
import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
import pandas as pd

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_USASWIMMING_COMPETITIONS_DIR = (_PROJECT_DIR / "data" / "processed" / "usaswimming")
DEFAULT_USASWIMMING_PARQUET_DIR = (DEFAULT_USASWIMMING_COMPETITIONS_DIR / "_parquet_cache")


def _default_parquet_engine() -> str:
    if importlib.util.find_spec("pyarrow") is not None:
        return "pyarrow"
    raise ImportError("Aucun moteur Parquet detecte.")


class UsaswimmingCompetitionsDataLoader:
    """Charge les competitions USA Swimming depuis JSON ou cache Parquet."""
    
    def __init__(self, base_dir: Optional[Path] = None, parquet_dir: Optional[Path] = None, max_workers: Optional[int] = None) -> None:
        self.base_dir = (base_dir if base_dir is not None else DEFAULT_USASWIMMING_COMPETITIONS_DIR)
        self.parquet_dir = (parquet_dir if parquet_dir is not None else DEFAULT_USASWIMMING_PARQUET_DIR)
        self.max_workers = max_workers
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
        """Convertit la liste de nageurs en chaine JSON pour le stockage Parquet."""
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
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            return []

        return self._build_rows_from_comp(
            comp=comp,
            source_year=source_year,
            source_file=file.name,
        )

    def _load_year_directory(self, year_dir: Path) -> List[Dict[str, Any]]:
        try:
            source_year = int(year_dir.name)
        except ValueError:
            source_year = None

        rows: List[Dict[str, Any]] = []
        for file in sorted(year_dir.glob("*.json")):
            rows.extend(self._load_single_file(file, source_year=source_year))
        return rows

    def _resolve_year_directories(
        self,
        years: Optional[Iterable[int | str]] = None,
    ) -> List[Path]:
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

    def available_years(
        self,
        years: Optional[Iterable[int | str]] = None,
    ) -> List[str]:
        """Retourne les annees source disponibles pour la conversion parquet."""
        return [year_dir.name for year_dir in self._resolve_year_directories(years=years)]

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
        prepared = df.copy()
        if "swimmer" in prepared.columns:
            prepared["swimmer"] = prepared["swimmer"].apply(cls._serialize_swimmers)
        return prepared

    @classmethod
    def _restore_dataframe_from_parquet(cls, df: pd.DataFrame) -> pd.DataFrame:
        restored = df.copy()
        if "swimmer" in restored.columns:
            restored["swimmer"] = restored["swimmer"].apply(cls._deserialize_swimmers)
        return cls._normalize_dataframe(restored)

    def _load_from_json_years(self, year_dirs: List[Path]) -> pd.DataFrame:
        if not year_dirs:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for year_rows in executor.map(self._load_year_directory, year_dirs):
                rows.extend(year_rows)

        return self._normalize_dataframe(pd.DataFrame(rows))

    def _read_single_parquet(self, parquet_file: Path) -> pd.DataFrame:
        try:
            df = pd.read_parquet(parquet_file, engine=self.parquet_engine)
        except Exception:
            return pd.DataFrame()
        return self._restore_dataframe_from_parquet(df)

    def _load_from_parquet_years(self, years: List[int | str]) -> pd.DataFrame:
        parquet_files = [
            self._parquet_path_for_year(year)
            for year in years
            if self._parquet_path_for_year(year).exists()
        ]
        if not parquet_files:
            return pd.DataFrame()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            frames = list(executor.map(self._read_single_parquet, parquet_files))

        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

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

        written_files: List[Path] = []
        total_years = len(year_dirs)
        for index, year_dir in enumerate(year_dirs, start=1):
            parquet_file = self._parquet_path_for_year(year_dir.name)
            json_file_count = len(list(year_dir.glob("*.json")))
            if parquet_file.exists() and not overwrite:
                message = (
                    f"[{index}/{total_years}] {year_dir.name}: "
                    f"cache deja present ({parquet_file.name}), ignore."
                )
                if progress_callback is not None:
                    progress_callback(message)
                if progress_step_callback is not None:
                    progress_step_callback(message, index, total_years)
                written_files.append(parquet_file)
                continue

            start_time = time.perf_counter()
            if progress_callback is not None:
                progress_callback(
                    f"[{index}/{total_years}] {year_dir.name}: "
                    f"conversion de {json_file_count} fichier(s) JSON..."
                )

            year_df = self._load_from_json_years([year_dir])
            if year_df.empty:
                message = (
                    f"[{index}/{total_years}] {year_dir.name}: "
                    "aucune ligne detectee, aucun Parquet ecrit."
                )
                if progress_callback is not None:
                    progress_callback(message)
                if progress_step_callback is not None:
                    progress_step_callback(message, index, total_years)
                continue

            parquet_df = self._prepare_dataframe_for_parquet(year_df)
            parquet_df.to_parquet(
                parquet_file,
                engine=self.parquet_engine,
                index=False,
            )
            elapsed = time.perf_counter() - start_time
            message = (
                f"[{index}/{total_years}] {year_dir.name}: "
                f"{len(year_df):,} ligne(s) -> {parquet_file.name} "
                f"en {elapsed:.1f}s".replace(",", " ")
            )
            if progress_callback is not None:
                progress_callback(message)
            if progress_step_callback is not None:
                progress_step_callback(message, index, total_years)
            written_files.append(parquet_file)

        return written_files

    def load(
        self,
        years: Optional[Iterable[int | str]] = None,
        prefer_parquet: bool = True,
    ) -> pd.DataFrame:
        """Charge toutes les annees demandees en preferant le cache Parquet."""
        year_dirs = self._resolve_year_directories(years=years)
        if not year_dirs:
            return pd.DataFrame()

        requested_years = [year_dir.name for year_dir in year_dirs]
        if not prefer_parquet:
            return self._load_from_json_years(year_dirs)

        cached_years = [
            year for year in requested_years if self._parquet_path_for_year(year).exists()
        ]
        missing_year_dirs = [
            year_dir
            for year_dir in year_dirs
            if not self._parquet_path_for_year(year_dir.name).exists()
        ]

        frames: List[pd.DataFrame] = []
        parquet_df = self._load_from_parquet_years(cached_years)
        if not parquet_df.empty:
            frames.append(parquet_df)

        json_df = self._load_from_json_years(missing_year_dirs)
        if not json_df.empty:
            frames.append(json_df)

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)
