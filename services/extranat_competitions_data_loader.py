from __future__ import annotations
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
import pandas as pd

_PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXTRANAT_COMPETITIONS_DIR = (
    _PROJECT_DIR / "data" / "processed" / "extranat" / "competitions_per_type"
)


class ExtranatCompetitionsDataLoader:
    """Lit tous les *.json sous le répertoire de base et renvoie un DataFrame."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Stocke le chemin"""
        self.base_dir = base_dir if base_dir is not None else DEFAULT_EXTRANAT_COMPETITIONS_DIR

    @staticmethod
    def _build_rows_from_comp(comp: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Prend une cmp déjà chargée et retourne une liste des lignes"""
        rows: List[Dict[str, Any]] = []
        for epreuve in comp.get("epreuves", []):
            for perf in epreuve.get("performances", []):
                swimmers = perf.get("swimmer", [])
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
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            return []
        return self._build_rows_from_comp(comp)

    def load(self) -> pd.DataFrame:
        """Lance le chargement en parallèle thread avec ThreadPoolExecutor"""
        if not self.base_dir.exists():
            return pd.DataFrame()

        files = list(self.base_dir.rglob("*.json"))
        if not files:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        with ThreadPoolExecutor() as executor:
            for file_rows in executor.map(self._load_single_file, files):
                rows.extend(file_rows)

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")
        df["Gender"] = df["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )
        return df
