"""Chargement et cache Parquet des compétitions USA Swimming.

Ce module convertit les JSON bruts (un fichier par compétition, regroupés par
année sous ``data/processed/usaswimming/{year}/``) en fichiers Parquet annuels
(``_parquet_cache/{year}.parquet``) pour accélérer les lectures ultérieures.

Le flux de données :
1. **Construction du cache** — ``build_parquet_cache()`` lit les JSON et écrit
   un Parquet par année (appelé depuis l'UI).
2. **Lecture** — ``load()`` ne lit que le cache Parquet, jamais les JSON
   à la volée, afin de garantir des temps de réponse prévisibles.

La colonne ``swimmer`` (liste de dictionnaires imbriqués) est sérialisée en
chaîne JSON à l'écriture Parquet, car le format ne gère pas nativement ce type
de structure.
"""
from __future__ import annotations
import importlib.util
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
import pandas as pd

from services.machine_workers import recommended_cache_build_workers

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_USASWIMMING_COMPETITIONS_DIR = (_PROJECT_DIR / "data" / "processed" / "usaswimming")
DEFAULT_USASWIMMING_PARQUET_DIR = (DEFAULT_USASWIMMING_COMPETITIONS_DIR / "_parquet_cache")


def _default_parquet_engine() -> str:
    """Retourne le moteur Parquet disponible pour pandas.

    Returns:
        str: Nom du moteur (``"pyarrow"``).

    Raises:
        ImportError: Si pyarrow n'est pas installé.
    """
    if importlib.util.find_spec("pyarrow") is not None:
        return "pyarrow"
    raise ImportError("Aucun moteur Parquet detecte.")


class UsaswimmingCompetitionsDataLoader:
    """Convertit les JSON USA Swimming en Parquet, puis charge uniquement le cache.

    La classe centralise la conversion JSON → lignes tabulaires, l'écriture du
    cache annuel et la lecture optimisée (filtre par colonnes, pushdown sur
    l'épreuve). Les méthodes publiques ``load()`` et ``build_parquet_cache()``
    constituent les deux points d'entrée principaux.
    """

    def __init__(self, base_dir: Optional[Path] = None, parquet_dir: Optional[Path] = None, max_workers: Optional[int] = None, cache_build_max_workers: Optional[int] = None) -> None:
        """Configure les chemins source/Parquet et le parallélisme.

        Args:
            base_dir (Optional[Path]): Dossier des JSON annuels. Par défaut
                ``data/processed/usaswimming``.
            parquet_dir (Optional[Path]): Dossier du cache Parquet. Par défaut
                ``base_dir/_parquet_cache``.
            max_workers (Optional[int]): Threads pour les lectures parallèles.
            cache_build_max_workers (Optional[int]): Threads pour la conversion
                JSON → Parquet (défaut : ``recommended_cache_build_workers()``).

        Returns:
            None

        Raises:
            ImportError: Si pyarrow est absent (détecté à l'initialisation).
        """
        self.base_dir = (base_dir if base_dir is not None else DEFAULT_USASWIMMING_COMPETITIONS_DIR)
        self.parquet_dir = (parquet_dir if parquet_dir is not None else DEFAULT_USASWIMMING_PARQUET_DIR)
        self.max_workers = max_workers
        self.cache_build_max_workers = (
            cache_build_max_workers
            if cache_build_max_workers is not None
            else recommended_cache_build_workers()
        )
        self.parquet_engine = _default_parquet_engine()

    @staticmethod
    def _normalize_swimmers(swimmers: Any) -> List[Dict[str, Any]]:
        """Uniformise le champ ``swimmer`` en ``list[dict]``.

        Les JSON source peuvent fournir un seul nageur (dict) ou une liste ;
        en renvoyant toujours une liste, le reste du code n'a plus à gérer
        ces deux cas séparément.

        Args:
            swimmers (Any): Valeur brute du champ ``swimmer``.

        Returns:
            List[Dict[str, Any]]: Liste de dictionnaires nageur.
        """
        if isinstance(swimmers, dict):
            return [swimmers]
        if isinstance(swimmers, list):
            return [item for item in swimmers if isinstance(item, dict)]
        return []

    @classmethod
    def _serialize_swimmers(cls, swimmers: Any) -> str:
        """Sérialise la liste de nageurs en chaîne JSON pour Parquet.

        Parquet ne supporte pas proprement les listes de dicts imbriquées ;
        on stocke donc une chaîne JSON.

        Args:
            swimmers (Any): Valeur brute ou normalisée du champ ``swimmer``.

        Returns:
            str: Représentation JSON (tableau vide si aucun nageur).
        """
        return json.dumps(cls._normalize_swimmers(swimmers), ensure_ascii=False)

    @classmethod
    def _deserialize_swimmers(cls, swimmers: Any) -> List[Dict[str, Any]]:
        """Reconvertit une valeur lue depuis Parquet en ``list[dict]``.

        Gère les anciennes écritures (list/dict natifs) et le format courant
        (chaîne JSON).

        Args:
            swimmers (Any): Valeur de la colonne ``swimmer`` lue depuis Parquet.

        Returns:
            List[Dict[str, Any]]: Liste de dictionnaires nageur.
        """
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
        """Aplatit une compétition JSON en une ligne par performance.

        Parcourt la hiérarchie ``competition → epreuves → performances`` et dénormalise les
        champs du nageur principal (premier de la liste) en colonnes à plat
        (``Name``, ``Gender``, etc.) pour faciliter les filtres pandas.

        Args:
            comp (Dict[str, Any]): Objet JSON d'une compétition.
            source_year (Optional[int]): Année déduite du dossier parent.
            source_file (Optional[str]): Nom du fichier JSON source.

        Returns:
            List[Dict[str, Any]]: Lignes tabulaires prêtes pour un DataFrame.
        """
        rows: List[Dict[str, Any]] = []

        for epreuve in comp.get("epreuves", []):
            for perf in epreuve.get("performances", []):
                swimmers = cls._normalize_swimmers(perf.get("swimmer", []))
                # Colonnes à plat : on expose le 1er nageur pour les requêtes courantes.
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
        """Lit un fichier JSON de compétition et retourne les lignes aplaties.

        Args:
            file (Path): Chemin vers le fichier ``.json``.
            source_year (Optional[int]): Année associée au dossier parent.

        Returns:
            List[Dict[str, Any]]: Lignes extraites, ou liste vide si lecture impossible.
        """
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            return []
        return self._build_rows_from_comp(comp=comp, source_year=source_year, source_file=file.name)

    def _load_year_directory(self, year_dir: Path) -> List[Dict[str, Any]]:
        """Charge tous les ``*.json`` d'un dossier annuel et agrège les lignes.

        Args:
            year_dir (Path): Dossier nommé par l'année (ex. ``2024/``).

        Returns:
            List[Dict[str, Any]]: Ensemble des performances de l'année.
        """
        try:
            source_year = int(year_dir.name)
        except ValueError:
            source_year = None

        rows: List[Dict[str, Any]] = []
        for file in sorted(year_dir.glob("*.json")):
            rows.extend(self._load_single_file(file, source_year=source_year))
        return rows

    def _resolve_year_directories(self, years: Optional[Iterable[int | str]] = None) -> List[Path]:
        """Liste ou filtre les dossiers année sous ``base_dir``.

        Args:
            years (Optional[Iterable[int | str]]): Sous-ensemble d'années demandées.
                ``None`` retourne tous les dossiers.

        Returns:
            List[Path]: Chemins des dossiers année, triés par nom.
        """
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
        """Retourne les années source JSON disponibles pour la conversion Parquet.

        Args:
            years (Optional[Iterable[int | str]]): Filtre optionnel sur les années.

        Returns:
            List[str]: Noms de dossiers année (ex. ``["2023", "2024"]``).
        """
        return [year_dir.name for year_dir in self._resolve_year_directories(years=years)]

    def _resolve_parquet_years(self, years: Optional[Iterable[int | str]] = None) -> List[str]:
        """Liste les années déjà présentes dans le cache Parquet.

        Args:
            years (Optional[Iterable[int | str]]): Filtre optionnel ; seules les
                années avec un fichier ``{year}.parquet`` existant sont retenues.

        Returns:
            List[str]: Années disponibles dans ``parquet_dir``.
        """
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

    def _parquet_path_for_year(self, year: int | str) -> Path:
        """Construit le chemin du fichier Parquet associé à une année.

        Args:
            year (int | str): Année cible.

        Returns:
            Path: Chemin ``parquet_dir/{year}.parquet``.
        """
        return self.parquet_dir / f"{year}.parquet"

    @staticmethod
    def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce les colonnes temporelles et numériques vers les types attendus.

        Args:
            df (pd.DataFrame): DataFrame brut issu des JSON ou Parquet.

        Returns:
            pd.DataFrame: Copie avec ``SwimDate``, ``SwimTimeSeconds`` et ``Year`` typés.
        """
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
        """Prépare un DataFrame avant écriture Parquet.

        Sérialise la colonne ``swimmer`` en chaîne JSON.

        Args:
            df (pd.DataFrame): DataFrame en mémoire avec ``swimmer`` en list[dict].

        Returns:
            pd.DataFrame: Copie prête pour ``to_parquet``.
        """
        prepared = df.copy()
        if "swimmer" in prepared.columns:
            prepared["swimmer"] = prepared["swimmer"].apply(cls._serialize_swimmers)
        return prepared

    @classmethod
    def _restore_dataframe_from_parquet(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Restaure un DataFrame après lecture Parquet.

        Désérialise ``swimmer`` puis normalise les types de colonnes.

        Args:
            df (pd.DataFrame): DataFrame lu depuis Parquet.

        Returns:
            pd.DataFrame: DataFrame avec types et structures restaurés.
        """
        restored = df.copy()
        if "swimmer" in restored.columns:
            restored["swimmer"] = restored["swimmer"].apply(cls._deserialize_swimmers)
        return cls._normalize_dataframe(restored)

    def _load_from_json_years(self, year_dirs: List[Path]) -> pd.DataFrame:
        """Charge plusieurs dossiers année en parallèle depuis les JSON.

        Utilisé uniquement lors de la construction du cache, pas par ``load()``.

        Args:
            year_dirs (List[Path]): Dossiers année à convertir.

        Returns:
            pd.DataFrame: Données concaténées et normalisées.
        """
        if not year_dirs:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for year_rows in executor.map(self._load_year_directory, year_dirs):
                rows.extend(year_rows)

        return self._normalize_dataframe(pd.DataFrame(rows))

    def _read_single_parquet(self, parquet_file: Path, columns: Optional[List[str]] = None, event: Optional[str] = None) -> pd.DataFrame:
        """Lit un fichier Parquet annuel avec filtre pushdown optionnel sur l'épreuve.

        Args:
            parquet_file (Path): Chemin du fichier Parquet à lire.
            columns (Optional[List[str]]): Sous-ensemble de colonnes à charger.
            event (Optional[str]): Épreuve pour filtrage PyArrow (pushdown).

        Returns:
            pd.DataFrame: Données désérialisées et normalisées, vide en cas d'erreur.
        """
        # Filtre pushdown PyArrow : le moteur élimine les row groups hors épreuve
        # avant de charger les colonnes en RAM — gain majeur sur les gros fichiers.
        read_kwargs: Dict[str, Any] = {"engine": self.parquet_engine}
        if columns is not None:
            read_columns = list(dict.fromkeys(columns))
            # Event doit être lu même si absent de columns, pour appliquer le filtre.
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

    def _load_from_parquet_years(self, years: List[int | str], columns: Optional[List[str]] = None, event: Optional[str] = None) -> pd.DataFrame:
        """Lit plusieurs années Parquet en parallèle et concatène.

        Args:
            years (List[int | str]): Années à charger.
            columns (Optional[List[str]]): Colonnes à lire (projection).
            event (Optional[str]): Filtre pushdown sur l'épreuve.

        Returns:
            pd.DataFrame: Données multi-années, ou DataFrame vide.
        """
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
        """Convertit un dossier année JSON en fichier Parquet (tâche parallèle).

        Args:
            year_dir (Path): Dossier annuel contenant les JSON.
            index (int): Indice de progression (1-based).
            total_years (int): Nombre total d'années à traiter.
            overwrite (bool): Si False, conserve un Parquet existant sans relecture.
            progress_callback (Optional[Callable[[str], None]]): Journalisation ligne à ligne.
            progress_step_callback (Optional[Callable[[str, int, int], None]]): Callback
                appelé à la fin de chaque année pour signaler qu'une étape de plus est terminé (message, index, total).
            progress_lock (Optional[threading.Lock]): Verrou pour les callbacks thread-safe.

        Returns:
            Optional[Path]: Chemin du Parquet écrit ou déjà présent, ``None`` si vide.
        """
        def _report(message: str, *, year_finished: bool = False) -> None:
            """Émet un message de progression de façon thread-safe.

            Args:
                message (str): Texte à afficher ou journaliser.
                year_finished (bool): Si True, déclenche aussi le callback d'étape.

            Returns:
                None
            """
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

        # Cache incrémental : on ne reconvertit pas une année déjà en Parquet sauf --overwrite.
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
        """Construit ou met à jour le cache Parquet annuel depuis les JSON source.

        Une tâche parallèle est lancée par dossier année ; chaque tâche charge
        l'intégralité des JSON de l'année en RAM avant d'écrire un seul fichier
        ``{year}.parquet``. Le parallélisme est volontairement limité
        (``cache_build_max_workers``) pour éviter les pics mémoire.

        Args:
            years (Optional[Iterable[int | str]]): Années à convertir. ``None``
                traite tous les dossiers sous ``base_dir``.
            overwrite (bool): Si True, régénère les Parquet même s'ils existent.
            progress_callback (Optional[Callable[[str], None]]): Affichage de la progression.
            progress_step_callback (Optional[Callable[[str, int, int], None]]): Callback
                fin d'année (message, index courant, total).

        Returns:
            List[Path]: Fichiers Parquet écrits ou déjà présents, triés par année.
        """
        year_dirs = self._resolve_year_directories(years=years)
        if not year_dirs:
            return []

        self.parquet_dir.mkdir(parents=True, exist_ok=True)

        # Granularité = 1 année : compromis RAM / parallélisme (voir cache_build_max_workers).
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
        """Liste triée des épreuves présentes dans le cache Parquet.

        Ne charge que la colonne ``Event`` pour limiter l'I/O.

        Args:
            years (Optional[Iterable[int | str]]): Filtre optionnel sur les années.

        Returns:
            List[str]: Libellés d'épreuves distincts (ex. ``"100 FR LCM"``).
        """
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
        """Retourne les noms distincts pour une épreuve donnée.

        Args:
            event (str): Libellé d'épreuve (filtre pushdown Parquet).
            gender (Optional[str]): ``"F"`` ou ``"M"`` pour restreindre le résultat.
            years (Optional[Iterable[int | str]]): Années à interroger.

        Returns:
            List[str]: Noms de nageurs triés, sans doublons ni chaînes vides.
        """
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
        """Charge les années demandées depuis le cache Parquet uniquement.

        Ne lit jamais les JSON source : si le cache est absent, retourne un
        DataFrame vide. Appeler ``build_parquet_cache()`` au préalable.

        Args:
            years (Optional[Iterable[int | str]]): Années à charger. ``None`` =
                toutes les années présentes dans ``parquet_dir``.
            columns (Optional[Iterable[str]]): Projection de colonnes (réduit
                l'I/O ; exclure ``swimmer`` si non nécessaire).
            event (Optional[str]): Filtre sur ``Event`` via pushdown PyArrow
                (ex. ``"100 FR LCM"``), beaucoup plus rapide qu'un filtre pandas.

        Returns:
            pd.DataFrame: Performances concaténées, ou DataFrame vide si aucun cache.
        """
        parquet_years = self._resolve_parquet_years(years=years)
        if not parquet_years:
            return pd.DataFrame()
        column_list = list(columns) if columns is not None else None
        return self._load_from_parquet_years(
            parquet_years, columns=column_list, event=event
        )
