"""Charge les JSON Extranat prétraités en un DataFrame pandas.

Ce module lit récursivement les fichiers JSON produits par le scraping Extranat
(sous ``data/processed/extranat/competitions_per_type/**/*.json``) et les
aplatit en lignes tabulaires pour les requêtes de l'interface (couloirs,
graphiques, filtres).

Le flux de données :
1. **Découverte** — ``load()`` parcourt récursivement tous les ``*.json`` du
   dossier source (un fichier par compétition / type).
2. **Aplatissement** — chaque JSON est converti en lignes via
   ``_build_rows_from_comp()`` (hiérarchie compétition → épreuves → performances).
3. **Enrichissement** — coercion de ``SwimTimeSeconds`` et extraction du genre
   depuis le premier nageur de la liste ``swimmer``.
4. **Consommation** — le DataFrame résultant est utilisé par ``graph_service``
   et les autres services d'analyse.

La colonne ``swimmer`` reste une ``list[dict]`` (format Extranat natif) ;
``splits`` conserve les passages intermédiaires par performance.
"""
from __future__ import annotations
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
import pandas as pd

# --- Chemins par défaut ---

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXTRANAT_COMPETITIONS_DIR = (
    _PROJECT_DIR / "data" / "processed" / "extranat" / "competitions_per_type"
)


class ExtranatCompetitionsDataLoader:
    """Lit tous les JSON Extranat sous le répertoire de base et renvoie un DataFrame.

    La classe centralise l'aplatissement JSON → lignes tabulaires et la lecture
    parallèle des fichiers. Point d'entrée principal : ``load()``.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Configure le répertoire racine des JSON Extranat traités.

        Args:
            base_dir (Optional[Path]): Dossier source. Par défaut
                ``data/processed/extranat/competitions_per_type``.

        Returns:
            None
        """
        self.base_dir = base_dir if base_dir is not None else DEFAULT_EXTRANAT_COMPETITIONS_DIR

    @staticmethod
    def _build_rows_from_comp(comp: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Aplatit une compétition JSON Extranat en lignes de performance.

        Parcourt la hiérarchie ``competition → epreuves → performances`` et
        conserve ``swimmer`` (list ou dict) et ``splits`` tels quels pour
        compatibilité avec le format source.

        Args:
            comp (Dict[str, Any]): Objet JSON d'une compétition.

        Returns:
            List[Dict[str, Any]]: Une ligne par performance.
        """
        rows: List[Dict[str, Any]] = []
        for epreuve in comp.get("epreuves", []):
            for perf in epreuve.get("performances", []):
                swimmers = perf.get("swimmer", [])
                # Le JSON source peut fournir un seul nageur (dict) ou une liste
                if isinstance(swimmers, dict):
                    swimmers = [swimmers]

                row = {
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
                    "points": perf.get("points"),
                    "mpp": perf.get("mpp"),
                    "mpp_date": perf.get("mpp_date"),
                    "SwimTime": perf.get("SwimTime"),
                    "SwimTimeSeconds": perf.get("SwimTimeSeconds"),
                    "Status": perf.get("Status"),
                    "Speed": perf.get("Speed"),
                    "swimmer": swimmers,
                    "splits": perf.get("splits", []),
                }
                rows.append(row)
        return rows

    def _load_single_file(self, file: Path) -> List[Dict[str, Any]]:
        """Charge un fichier JSON de compétition et retourne les lignes aplaties.

        Args:
            file (Path): Chemin vers le fichier JSON à lire.

        Returns:
            List[Dict[str, Any]]: Lignes de performance extraites, ou liste vide en cas d'erreur.
        """
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            return []
        return self._build_rows_from_comp(comp)

    def load(self) -> pd.DataFrame:
        """Charge tous les JSON en parallèle et renvoie un DataFrame agrégé.

        Parcourt récursivement ``base_dir`` avec ``ThreadPoolExecutor``, agrège
        les lignes puis enrichit les colonnes ``SwimTimeSeconds`` et ``Gender``.

        Returns:
            pd.DataFrame: Performances aplaties ; DataFrame vide si le dossier
                est absent ou ne contient aucun JSON.
        """
        if not self.base_dir.exists():
            return pd.DataFrame()

        files = list(self.base_dir.rglob("*.json"))
        if not files:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        # Parallélisme I/O : volume important de petits fichiers JSON
        with ThreadPoolExecutor() as executor:
            for file_rows in executor.map(self._load_single_file, files):
                rows.extend(file_rows)

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")
        # Genre dénormalisé depuis le premier nageur pour les filtres pandas
        df["Gender"] = df["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )
        return df
