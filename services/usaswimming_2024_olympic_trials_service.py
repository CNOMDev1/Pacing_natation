import os
import sys
from typing import Any, Dict, List

import pandas as pd
import requests

# Supporte à la fois l'import comme module du package `services`
# et l'exécution directe `python usaswimming_2024_olympic_trials_service.py`
try:  # import relatif (contexte package)
    from .usaswimming_service import load_bearer_token
except ImportError:  # exécution directe dans le dossier `services`
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    PARENT_DIR = os.path.dirname(CURRENT_DIR)
    if PARENT_DIR not in sys.path:
        sys.path.append(PARENT_DIR)
    from usaswimming_service import load_bearer_token  # type: ignore[no-redef]


MEET_NAME = "2024 Olympic Trials"

# Informations issues du payload Network du site USA Swimming
USAS_TIMES_URL = (
    "https://usaswimming.sisense.com/api/datasources/"
    "USA%20Swimming%20Times%20Elasticube/jaql?trc=sdk-ui-1.11.0"
)

# MeetKey correspondant aux Trials 2024 (fourni par ton payload)
TRIALS_2024_MEET_KEY = 255239

USAS_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "fr,fr-FR;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "authorization": load_bearer_token(),
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://data.usaswimming.org",
}
BASE_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw", "usaswimming")
)
OUTPUT_JSON_PATH = os.path.join(BASE_DATA_DIR, "usaswimming_2024_olympic_trials.json")
OUTPUT_CSV_PATH = os.path.join(BASE_DATA_DIR, "usaswimming_2024_olympic_trials.csv")


def fetch_2024_olympic_trials_results() -> pd.DataFrame:
    """
    Récupère toutes les performances du meet '2024 Olympic Trials' depuis l'API USA Swimming.

    La fonction interroge directement le cube "USA Swimming Times Elasticube"
    (même datasource que le site), en utilisant le MeetKey des Trials 2024
    et la dimension de rang `[UsasSwimTime.FinishPosition]`.

    On enlève volontairement les filtres "Female", "50 FR LCM", "Final"
    pour récupérer tout le meeting (tous sexes / épreuves / sessions).
    """
    payload: Dict[str, Any] = {
        "metadata": [
            # Rang officiel (place) tel qu'utilisé par le site
            {
                "jaql": {
                    "title": "Place",
                    "dim": "[UsasSwimTime.FinishPosition]",
                    "datatype": "numeric",
                    "sort": "asc",
                }
            },
            {"jaql": {"title": "Event", "dim": "[SwimEvent.EventCode]", "datatype": "text"}},
            {"jaql": {"title": "Session", "dim": "[Session.SessionName]", "datatype": "text"}},
            {"jaql": {"title": "Name", "dim": "[UsasSwimTime.FullName]", "datatype": "text"}},
            {"jaql": {"title": "Gender", "dim": "[EventCompetitionCategory.TypeName]", "datatype": "text"}},
            {"jaql": {"title": "AgeGroup", "dim": "[Age.AgeGroup1]", "datatype": "text"}},
            {"jaql": {"title": "SwimTime", "dim": "[UsasSwimTime.SwimTimeFormatted]", "datatype": "text"}},
            {"jaql": {"title": "TimeStandard", "dim": "[TimeStandard.TimeStandardName]", "datatype": "text"}},
            # Filtre principal : MeetKey Trials 2024
            {
                "jaql": {
                    "title": "MeetKey",
                    "dim": "[Meet.MeetKey]",
                    "datatype": "numeric",
                    "filter": {"equals": TRIALS_2024_MEET_KEY},
                },
                "panel": "scope",
            },
        ],
        "datasource": "USA Swimming Times Elasticube",
        "by": "ComposeSDK",
        "queryGuid": "2024-olympic-trials-full-meet",
        "count": 5000,
    }

    resp = requests.post(USAS_TIMES_URL, headers=USAS_HEADERS, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Erreur HTTP {resp.status_code} sur USA Swimming Times Elasticube: {resp.text[:200]}"
        )

    data = resp.json()
    headers_list: List[str] = data.get("headers") or []
    values = data.get("values") or []
    records: List[Dict[str, Any]] = []

    for row in values:
        if not isinstance(row, list):
            continue
        rec: Dict[str, Any] = {}
        for i, header in enumerate(headers_list):
            if i >= len(row):
                continue
            cell = row[i]
            if isinstance(cell, dict) and "data" in cell:
                rec[header] = cell.get("data")
            else:
                rec[header] = cell
        records.append(rec)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # Harmonisation minimale avec tes autres datasets :
    # - on renomme Place -> Rank (rang officiel)
    if "Place" in df.columns and "Rank" not in df.columns:
        try:
            df["Rank"] = df["Place"].astype(int)
        except Exception:
            df["Rank"] = df["Place"]

    return df


def fetch_and_save_2024_olympic_trials_results() -> Dict[str, Any]:
    """
    Récupère toutes les performances du meet '2024 Olympic Trials' et les enregistre
    dans la structure standard de `data/raw/usaswimming` via `save_data_by_competition`.

    Retourne un petit résumé pour utilisation éventuelle dans une API ou un script.
    """
    df_meet = fetch_2024_olympic_trials_results()

    if df_meet.empty:
        return {
            "success": False,
            "message": f"Aucune donnée trouvée pour le meet '{MEET_NAME}' en 2024.",
            "count_results": 0,
        }

    os.makedirs(BASE_DATA_DIR, exist_ok=True)
    # Sauvegarde en JSON et CSV dans `data/raw/usaswimming/`
    df_meet.to_json(OUTPUT_JSON_PATH, orient="records", date_format="iso", force_ascii=False, indent=2)
    df_meet.to_csv(OUTPUT_CSV_PATH, index=False)

    return {
        "success": True,
        "message": f"{len(df_meet)} lignes pour '{MEET_NAME}' récupérées et enregistrées.",
        "count_results": int(len(df_meet)),
        "output_json": OUTPUT_JSON_PATH,
        "output_csv": OUTPUT_CSV_PATH,
    }


if __name__ == "__main__":
    summary = fetch_and_save_2024_olympic_trials_results()
    print(summary)

