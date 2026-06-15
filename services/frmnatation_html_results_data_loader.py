"""Charge les résultats FRM Natation (Maroc) extraits depuis des pages HTML.

Ce module lit les JSON produits par le scraping FRM Natation (un fichier par
compétition sous ``data/processed/frmnatation/html_results/``) et les expose
sous forme de DataFrame pandas pour l'interface desktop.

Le flux de données :
1. **Chargement** — ``load()`` parcourt tous les ``*.json`` du dossier source
   en parallèle (``ThreadPoolExecutor``) et aplatit chaque compétition en lignes
   de performance (une ligne par nageur / temps).
2. **Cache mémoire** — le DataFrame complet est mis en cache après la première
   lecture (volume faible, mais accès fréquent depuis l'UI).
3. **Filtrage** — ``_filter_df()`` restreint par épreuve, bassin, genre et
   exclut les lignes sans chrono valide (``SwimTimeSeconds``).
4. **Consommation UI** — ``list_swimmer_labels()`` alimente les listes déroulantes,
   ``rows_for_swimmer()`` fusionne avec le format Extranat, et
   ``usa_overlay_rows_for_swimmer()`` superpose un nageur marocain sur un couloir
   USA Swimming.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# --- Chemins par défaut ---

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FRMNATATION_HTML_RESULTS_DIR = (
    _PROJECT_DIR / "data" / "processed" / "frmnatation" / "html_results"
)


def _normalize_gender(value: Any) -> str:
    """Unifie les libellés de genre (F/M) issus des pages HTML marocaines.

    Les pages FRM Natation utilisent des variantes (« Femme », « H », etc.) ;
    cette fonction normalise vers ``"F"``, ``"M"`` ou ``"all"`` (pas de filtre).

    Args:
        value (Any): Valeur brute du champ genre (str, None, etc.).

    Returns:
        str: ``"F"``, ``"M"`` ou ``"all"`` si le genre est inconnu ou absent.
    """
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
        # yob == yob exclut NaN sans importer numpy
        if yob is not None and yob == yob:
            return f"{nm} ({int(yob)})"
    except (TypeError, ValueError):
        pass
    return nm


class FrmnatationHtmlResultsDataLoader:
    """Charge les JSON FRM Natation (html_results) en DataFrame pandas.

    La classe centralise l'aplatissement JSON → lignes tabulaires, le cache
    mémoire et les requêtes orientées UI (liste de nageurs, overlay USA
    Swimming, export format Extranat). Point d'entrée principal : ``load()``.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Configure le répertoire source et initialise le cache mémoire.

        Args:
            base_dir (Optional[Path]): Dossier des JSON. Par défaut
                ``data/processed/frmnatation/html_results``.

        Returns:
            None
        """
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

        Parcourt la hiérarchie ``competition → epreuves → performances`` et
        dénormalise les champs du nageur en colonnes à plat (``Name``, ``Gender``,
        etc.) pour faciliter les filtres pandas.

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
                        # Format aligné Extranat : swimmer en list[dict]
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
        """Charge tous les JSON du dossier source (avec cache mémoire).

        Lit chaque ``*.json`` en parallèle, agrège les lignes et met le
        résultat en cache. Les appels suivants renvoient une copie du cache
        sans relire le disque.

        Returns:
            pd.DataFrame: Performances aplaties ; DataFrame vide si le dossier
                est absent ou ne contient aucun JSON.
        """
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
        # Parallélisme léger : peu de fichiers mais parsing JSON coûteux
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
            # Filtre composite : distance + nage + bassin, puis libellé Event exact
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
        # Exclure les performances sans chrono exploitable
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
        """Liste les nageurs au format « Nom (année) » pour une épreuve donnée.

        Utilisé par l'UI desktop pour peupler les sélecteurs de nageurs
        marocains filtrés par épreuve et genre.

        Args:
            stroke (Optional[str]): Type de nage (ex. « NL »).
            distance (Optional[int]): Distance en mètres.
            pool (Optional[str]): Type de bassin (ex. « LCM »).
            event (Optional[str]): Libellé complet de l'épreuve.
            gender (str): Filtre genre (« F », « M » ou « all »).

        Returns:
            List[str]: Libellés triés alphabétiquement (insensible à la casse).
        """
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
        """Retourne les performances d'un nageur au format Extranat (pour fusion UI).

        Filtre par épreuve et nom ; si l'année de naissance n'est pas fournie,
        utilise la valeur la plus fréquente parmi les homonymes pour lever
        l'ambiguïté.

        Args:
            nom_event (str): Libellé de l'épreuve (ex. « 100 NL LCM »).
            nom_nageur (str): Nom exact du nageur.
            year_of_birth (Optional[int]): Année de naissance pour désambiguïser.

        Returns:
            pd.DataFrame: Lignes au format Extranat (avec ``swimmer``, ``splits``),
                ou DataFrame vide si aucune correspondance.
        """
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
            # Homonymes : on retient l'année de naissance la plus fréquente
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
            # Reconstruction du dict nageur si absent du JSON source
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
        """Colonnes minimales pour superposer un nageur marocain sur un couloir USA Swimming.

        Retourne uniquement les champs nécessaires au tracé overlay (chrono,
        âge, genre) pour une épreuve et un nageur donnés.

        Args:
            nom_event (str): Libellé de l'épreuve.
            nom_nageur (str): Nom exact du nageur.
            year_of_birth (Optional[int]): Année de naissance pour désambiguïser.

        Returns:
            pd.DataFrame: Colonnes ``Event``, ``SwimTimeSeconds``, ``AgeGroup``,
                ``Gender``, ``Name``, ``Year_of_birth`` ; vide si aucune ligne.
        """
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
            # Même logique de désambiguïsation que rows_for_swimmer
            yob_series = pd.to_numeric(scoped["Year_of_birth"], errors="coerce")
            if yob_series.loc[mask].notna().any():
                best_yob = int(yob_series.loc[mask].mode().iloc[0])
                mask = mask & (yob_series == best_yob)
        rows = scoped.loc[mask]
        if rows.empty:
            return pd.DataFrame()
        overlay: List[Dict[str, Any]] = []
        for _, row in rows.iterrows():
            # Sous-ensemble minimal pour le graphique de couloir USA
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
