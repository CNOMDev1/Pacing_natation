"""Charge les résultats FRM Natation (Maroc) extraits depuis des pages HTML.

Les JSON sous ``data/processed/frmnatation/html_results/`` alimentent les
couloirs de performance avec une surcouche « nageur marocain » et la
recherche de nageurs dans l'interface desktop.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FRMNATATION_HTML_RESULTS_DIR = (
    _PROJECT_DIR / "data" / "processed" / "frmnatation" / "html_results"
)


def _normalize_gender(value: Any) -> str:
    """Unifie les libellés de genre (F/M) issus des pages HTML marocaines."""
    if value is None:
        return "all"
    s = str(value).strip().upper()
    if s in ("F", "FEMME", "FEMALE", "W"):
        return "F"
    if s in ("M", "H", "HOMME", "MALE", "MAN"):
        return "M"
    return "all"


def _swimmer_label(name: str, yob: Any) -> str:
    """Formate un libellé d'affichage « Nom (année) » pour un nageur.

    Args:
        name (str): Nom du nageur.
        yob (Any): Année de naissance (optionnelle).

    Returns:
        str: Libellé formaté, ou chaîne vide si le nom est absent.
    """
    nm = str(name).strip()
    if not nm:
        return ""
    try:
        if yob is not None and yob == yob:
            return f"{nm} ({int(yob)})"
    except (TypeError, ValueError):
        pass
    return nm


class FrmnatationHtmlResultsDataLoader:
    """Charge les JSON FRM Natation (html_results) en DataFrame."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Configure le répertoire source et initialise le cache mémoire."""
        self.base_dir = (
            base_dir if base_dir is not None else DEFAULT_FRMNATATION_HTML_RESULTS_DIR
        )
        # Cache en mémoire : les JSON marocains sont peu nombreux mais relus souvent.
        self._df_cache: Optional[pd.DataFrame] = None

    @staticmethod
    def _normalize_swimmer(swimmer: Any) -> Dict[str, Any]:
        """Uniformise le champ nageur en dictionnaire.

        Args:
            swimmer (Any): Valeur brute du champ ``swimmer``.

        Returns:
            Dict[str, Any]: Dictionnaire nageur ou dict vide si le type est invalide.
        """
        return swimmer if isinstance(swimmer, dict) else {}

    @classmethod
    def _build_rows_from_comp(cls, comp: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Aplatit une compétition JSON FRM Natation en lignes de performance.

        Args:
            comp (Dict[str, Any]): Structure compétition (épreuves → performances).

        Returns:
            List[Dict[str, Any]]: Une ligne par performance avec métadonnées nageur.
        """
        rows: List[Dict[str, Any]] = []
        for epreuve in comp.get("epreuves") or []:
            if not isinstance(epreuve, dict):
                continue
            for perf in epreuve.get("performances") or []:
                if not isinstance(perf, dict):
                    continue
                swimmer = cls._normalize_swimmer(perf.get("swimmer"))
                rows.append(
                    {
                        "SwimDate": comp.get("SwimDate"),
                        "SwimYear": comp.get("SwimYear"),
                        "Meet": comp.get("Meet"),
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
                        "swimmer": [swimmer] if swimmer else [],
                        "Name": swimmer.get("Name"),
                        "Gender": swimmer.get("Gender"),
                        "Year_of_birth": swimmer.get("Year_of_birth"),
                        "Age": swimmer.get("Age"),
                        "AgeGroup": swimmer.get("AgeGroup"),
                        "Nationality": swimmer.get("Nationality"),
                    }
                )
        return rows

    def _load_single_file(self, file: Path) -> List[Dict[str, Any]]:
        """Charge un fichier JSON et retourne les lignes de performance extraites.

        Args:
            file (Path): Chemin vers le fichier JSON à lire.

        Returns:
            List[Dict[str, Any]]: Lignes aplaties, ou liste vide en cas d'erreur.
        """
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            return []
        if not isinstance(comp, dict):
            return []
        return self._build_rows_from_comp(comp)

    def load(self) -> pd.DataFrame:
        """Charge tous les JSON (avec cache) et renvoie une copie du DataFrame."""
        if self._df_cache is not None:
            return self._df_cache.copy()
        if not self.base_dir.exists():
            self._df_cache = pd.DataFrame()
            return self._df_cache.copy()
        files = sorted(self.base_dir.glob("*.json"))
        if not files:
            self._df_cache = pd.DataFrame()
            return self._df_cache.copy()
        rows: List[Dict[str, Any]] = []
        with ThreadPoolExecutor() as executor:
            for file_rows in executor.map(self._load_single_file, files):
                rows.extend(file_rows)
        self._df_cache = pd.DataFrame(rows)
        return self._df_cache.copy()

    def _filter_df(
        self,
        df: pd.DataFrame,
        *,
        stroke: Optional[str] = None,
        distance: Optional[int] = None,
        pool: Optional[str] = None,
        event: Optional[str] = None,
        gender: str = "all",
    ) -> pd.DataFrame:
        """Filtre le DataFrame par épreuve, bassin et genre avec chronos valides.

        Args:
            df (pd.DataFrame): Données chargées depuis les JSON marocains.
            stroke (Optional[str]): Type de nage (ex. « NL »).
            distance (Optional[int]): Distance en mètres.
            pool (Optional[str]): Type de bassin (ex. « LCM »).
            event (Optional[str]): Libellé complet de l'épreuve.
            gender (str): Filtre genre (« F », « M » ou « all »).

        Returns:
            pd.DataFrame: Sous-ensemble filtré avec ``SwimTimeSeconds`` non nul.
        """
        if df.empty:
            return df
        scoped = df
        if event:
            scoped = scoped[
                scoped["Event"].astype(str).str.strip() == str(event).strip()
            ]
        if stroke and distance is not None and pool:
            nom_event = f"{int(distance)} {str(stroke).strip()} {str(pool).strip()}"
            scoped = scoped[
                (scoped["Stroke"].astype(str).str.strip() == str(stroke).strip())
                & (pd.to_numeric(scoped["Distance"], errors="coerce") == int(distance))
                & (scoped["Course"].astype(str).str.strip() == str(pool).strip())
            ]
            if "Event" in scoped.columns:
                scoped = scoped[
                    scoped["Event"].astype(str).str.strip() == nom_event
                ]
        gender_key = _normalize_gender(gender)
        if gender_key in ("F", "M") and "Gender" in scoped.columns:
            g = scoped["Gender"].astype(str).str.strip().str.upper()
            scoped = scoped[g == gender_key]
        return scoped[scoped["SwimTimeSeconds"].notna()].copy()

    def list_swimmer_labels(
        self,
        *,
        stroke: Optional[str] = None,
        distance: Optional[int] = None,
        pool: Optional[str] = None,
        event: Optional[str] = None,
        gender: str = "all",
    ) -> List[str]:
        """Liste les nageurs au format « Nom (année) » pour une épreuve donnée."""
        df = self.load()
        scoped = self._filter_df(
            df,
            stroke=stroke,
            distance=distance,
            pool=pool,
            event=event,
            gender=gender,
        )
        labels: set[str] = set()
        for _, row in scoped.iterrows():
            name = row.get("Name")
            yob = row.get("Year_of_birth")
            label = _swimmer_label(name, yob) if name else ""
            if label:
                labels.add(label)
        return sorted(labels, key=lambda x: x.lower())

    def rows_for_swimmer(
        self,
        *,
        nom_event: str,
        nom_nageur: str,
        year_of_birth: Optional[int],
    ) -> pd.DataFrame:
        """Retourne les performances d'un nageur au format Extranat (pour fusion UI)."""
        df = self.load()
        if df.empty:
            return pd.DataFrame()
        scoped = df[df["Event"].astype(str).str.strip() == str(nom_event).strip()]
        if scoped.empty:
            return pd.DataFrame()
        target_name = str(nom_nageur).strip()
        mask = scoped["Name"].astype(str).str.strip() == target_name
        if year_of_birth is not None and "Year_of_birth" in scoped.columns:
            yob_series = pd.to_numeric(scoped["Year_of_birth"], errors="coerce")
            mask = mask & (yob_series == int(year_of_birth))
        elif "Year_of_birth" in scoped.columns:
            yob_series = pd.to_numeric(scoped["Year_of_birth"], errors="coerce")
            if yob_series.loc[mask].notna().any():
                best_yob = int(yob_series.loc[mask].mode().iloc[0])
                mask = mask & (yob_series == best_yob)
        out = scoped.loc[mask].copy()
        if out.empty:
            return out
        extranat_rows: List[Dict[str, Any]] = []
        for _, row in out.iterrows():
            raw_swimmers = row.get("swimmer")
            if isinstance(raw_swimmers, list) and raw_swimmers:
                swimmer = self._normalize_swimmer(raw_swimmers[0])
            else:
                swimmer = {}
            if not swimmer:
                swimmer = {
                    "Name": row.get("Name"),
                    "Gender": row.get("Gender"),
                    "Year_of_birth": row.get("Year_of_birth"),
                    "Age": row.get("Age"),
                    "AgeGroup": row.get("AgeGroup"),
                    "Nationality": row.get("Nationality"),
                }
            extranat_rows.append(
                {
                    "Meet": row.get("Meet"),
                    "SwimDate": row.get("SwimDate"),
                    "Location": row.get("Location"),
                    "Country": row.get("Country"),
                    "Event": row.get("Event"),
                    "Distance": row.get("Distance"),
                    "Stroke": row.get("Stroke"),
                    "Course": row.get("Course"),
                    "PoolLength": row.get("PoolLength"),
                    "Tour": row.get("Tour"),
                    "Rank": row.get("Rank"),
                    "Club": row.get("Club"),
                    "SwimTime": row.get("SwimTime"),
                    "SwimTimeSeconds": row.get("SwimTimeSeconds"),
                    "Status": row.get("Status"),
                    "Speed": row.get("Speed"),
                    "swimmer": [swimmer],
                    "splits": [],
                }
            )
        return pd.DataFrame(extranat_rows)

    def usa_overlay_rows_for_swimmer(
        self,
        *,
        nom_event: str,
        nom_nageur: str,
        year_of_birth: Optional[int],
    ) -> pd.DataFrame:
        """Colonnes minimales pour superposer un nageur marocain sur un couloir USA Swimming."""
        df = self.load()
        if df.empty:
            return pd.DataFrame()
        scoped = df[df["Event"].astype(str).str.strip() == str(nom_event).strip()]
        target_name = str(nom_nageur).strip()
        mask = scoped["Name"].astype(str).str.strip() == target_name
        if year_of_birth is not None and "Year_of_birth" in scoped.columns:
            yob_series = pd.to_numeric(scoped["Year_of_birth"], errors="coerce")
            mask = mask & (yob_series == int(year_of_birth))
        elif "Year_of_birth" in scoped.columns:
            yob_series = pd.to_numeric(scoped["Year_of_birth"], errors="coerce")
            if yob_series.loc[mask].notna().any():
                best_yob = int(yob_series.loc[mask].mode().iloc[0])
                mask = mask & (yob_series == best_yob)
        rows = scoped.loc[mask]
        if rows.empty:
            return pd.DataFrame()
        overlay: List[Dict[str, Any]] = []
        for _, row in rows.iterrows():
            overlay.append(
                {
                    "Event": row.get("Event"),
                    "SwimTimeSeconds": row.get("SwimTimeSeconds"),
                    "AgeGroup": row.get("AgeGroup"),
                    "Gender": row.get("Gender"),
                    "Name": row.get("Name"),
                    "Year_of_birth": row.get("Year_of_birth"),
                }
            )
        return pd.DataFrame(overlay)
