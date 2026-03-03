import requests
import json
import pandas as pd
import time
import os
import sys
import re
import subprocess

# Répertoire de stockage des données 
USASWIMMING_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "usaswimming"))

# URL de l'API
url = "https://usaswimming.sisense.com/api/datasources/USA%20Swimming%20Times%20Elasticube/jaql?trc=sdk-ui-1.11.0"

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "bearer_token.txt")

def load_bearer_token() -> str:
    """Charge le token Bearer ; génère via get_token_usaswimming.py si le fichier est absent.

    - Cherche le fichier TOKEN_FILE dans le même dossier que ce script
    - Si absent, exécute get_token_usaswimming.py avec l'interpréteur courant
    - Relit le fichier et retourne le token (préfixé par 'Bearer ' si nécessaire)
    """
    if not os.path.exists(TOKEN_FILE):
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "scripts", "get_token_usaswimming.py")
        )
        if not os.path.exists(script_path):
            raise FileNotFoundError(
                f"{TOKEN_FILE} introuvable et {script_path} également manquant."
            )
        # Tente de générer le token
        try:
            subprocess.run([sys.executable, script_path], check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Échec d'exécution de get_token_usaswimming.py (code {exc.returncode})."
            ) from exc

    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} introuvable après exécution de get_token_usaswimming.py."
        )

    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    return raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"

# Header avec ton token Bearer
headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "fr,fr-FR;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "authorization": load_bearer_token(),
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://data.usaswimming.org",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
}

# Taille de page et délais pour limiter la charge côté API (éviter SafeModeException)
PAGE_SIZE = int(os.getenv("USASWIMMING_PAGE_SIZE", "5000"))
DELAY_BETWEEN_REQUESTS_S = float(os.getenv("USASWIMMING_DELAY_REQUESTS", "0.5"))
DELAY_BETWEEN_PERIODS_S = float(os.getenv("USASWIMMING_DELAY_PERIODS", "2.0"))

# Construit le payload JSON pour les requêtes API avec pagination et filtres de dates
def make_payload(offset, from_iso: str | None = None, to_iso: str | None = None, count: int | None = None):
    from_value = from_iso or "1900-01-01T00:00:00"
    to_value = to_iso or "2025-12-31T23:59:59"
    page_size = count if count is not None else PAGE_SIZE
    return {
        "metadata": [
            {"jaql": {"title": "Name", "dim": "[BestTimes.FullName]", "datatype": "text"}},
            {"jaql": {"title": "Federation", "dim": "[OrgUnit.TeamName]", "datatype": "text"}},
            {"jaql": {"title": "Event", "dim": "[SwimEvent.EventCode]", "datatype": "text"}},
            {"jaql": {"title": "Gender", "dim": "[EventCompetitionCategory.TypeName]", "datatype": "text"}},
            {"jaql": {"title": "Meet", "dim": "[Meet.MeetName]", "datatype": "text"}},
            {
                "jaql": {
                    "title": "SwimDate",
                    "dim": "[SeasonCalendar.CalendarDate (Calendar)]",
                    "datatype": "datetime",
                    "level": "days",
                    "filter": {
                        "from": from_value,
                        "to": to_value,
                        "inclusive": True
                    }
                },
                "format": {"mask": {"days": "M/d/yyyy"}}
            },
            {"jaql": {"title": "SwimTime", "dim": "[BestTimes.SwimTimeFormatted]", "datatype": "text"}},
            {"jaql": {"title": "SwimTimeSeconds", "dim": "[BestTimes.SwimTimeSeconds]", "datatype": "numeric"}}
        ],
        "datasource": "FINA Times",
        "by": "ComposeSDK",
        "queryGuid": f"page-{offset}",
        "count": page_size,
        "offset": offset
    }


def fetch_min_swim_date_from_api() -> int | None:
    """
    Interroge l'API pour obtenir la date de nage la plus ancienne (une ligne triée par date croissante).
    Retourne l'année (int) ou None si l'API ne répond pas ou ne renvoie pas de donnée.
    """
    from_iso = "1900-01-01T00:00:00"
    to_iso = "2030-12-31T23:59:59"
    payload = {
        "metadata": [
            {"jaql": {"title": "Name", "dim": "[BestTimes.FullName]", "datatype": "text"}},
            {
                "jaql": {
                    "title": "SwimDate",
                    "dim": "[SeasonCalendar.CalendarDate (Calendar)]",
                    "datatype": "datetime",
                    "level": "days",
                    "sort": "asc",
                    "filter": {"from": from_iso, "to": to_iso, "inclusive": True},
                },
                "format": {"mask": {"days": "M/d/yyyy"}},
            },
        ],
        "datasource": "FINA Times",
        "by": "ComposeSDK",
        "queryGuid": "min-date",
        "count": 1,
        "offset": 0,
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            return None
        data = response.json()
        if not data.get("values") or not data["values"]:
            return None
        headers_list = data.get("headers") or []
        row = data["values"][0]
        date_idx = next((i for i, h in enumerate(headers_list) if h == "SwimDate"), 0)
        date_cell = row[date_idx]["data"] if date_idx < len(row) else (row[0]["data"] if row else None)
        if not date_cell:
            return None
        ts = pd.to_datetime(date_cell, errors="coerce")
        if pd.isna(ts):
            return None
        return int(ts.year)
    except Exception:
        return None


# Fichier state pour le polling (dernière date vue), dans data/usaswimming
LATEST_SWIMDATE_FILE = os.path.join(USASWIMMING_DATA_DIR, "_latest_swimdate.txt")


def _read_latest_swimdate() -> pd.Timestamp | None:
    """Lit la dernière date de nage enregistrée (pour le polling)."""
    if not os.path.exists(LATEST_SWIMDATE_FILE):
        return None
    try:
        with open(LATEST_SWIMDATE_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        return pd.to_datetime(raw, errors="coerce")
    except Exception:
        return None


def _write_latest_swimdate(ts: pd.Timestamp) -> None:
    """Enregistre la dernière date de nage (pour le polling)."""
    os.makedirs(USASWIMMING_DATA_DIR, exist_ok=True)
    with open(LATEST_SWIMDATE_FILE, "w", encoding="utf-8") as f:
        f.write(ts.isoformat())


KEY_COLUMNS = [
    "Name",
    "Federation",
    "Event",
    "Gender",
    "Meet",
    "SwimDate",
    "SwimTimeSeconds",
]


def _sanitize_meet_filename(meet_name: str, max_length: int = 120) -> str:
    """Retourne un nom de fichier sûr à partir du nom de compétition."""
    if pd.isna(meet_name) or meet_name == "":
        return "_unknown"
    s = re.sub(r'[<>:"/\\|?*]', "", str(meet_name).strip())
    s = re.sub(r"\s+", "_", s)
    s = s[:max_length].rstrip("_") or "_unknown"
    return s or "_unknown"


def save_data_by_competition(df: pd.DataFrame, append: bool = False) -> None:
    """Enregistre le DataFrame dans data/usaswimming, groupé par date (année) puis par compétition.

    Structure : data/usaswimming/<année>/<compétition>.json
    - Chaque sous-dossier est une année (ex. 2020, 2021).
    - Chaque fichier JSON correspond à une compétition (Meet) pour cette année.

    - append=False : écrase les fichiers existants pour chaque (année, Meet).
    - append=True  : charge le fichier existant si présent, fusionne, déduplique selon KEY_COLUMNS, ré-enregistre.
    """
    if df.empty:
        return
    df = df.copy()
    df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
    df["_year"] = df["SwimDate"].dt.year

    for (year, meet_name), group in df.groupby(["_year", "Meet"], dropna=False):
        year_dir = os.path.join(USASWIMMING_DATA_DIR, str(int(year)))
        os.makedirs(year_dir, exist_ok=True)
        fname = _sanitize_meet_filename(meet_name) + ".json"
        path = os.path.join(year_dir, fname)
        if append and os.path.exists(path):
            try:
                existing = pd.read_json(path, orient="records")
                existing["SwimDate"] = pd.to_datetime(existing["SwimDate"], errors="coerce")
                combined = pd.concat([existing, group], ignore_index=True)
                combined = combined.drop_duplicates(subset=KEY_COLUMNS, keep="last")
            except Exception:
                combined = group
        else:
            combined = group
        combined = combined.drop(columns=["_year"], errors="ignore")
        combined.to_json(path, orient="records", date_format="iso", force_ascii=False, indent=2)
    print(f"Données enregistrées par année et compétition dans {USASWIMMING_DATA_DIR}")


# Récupère les données depuis une date donnée jusqu'à maintenant
def fetch_since(from_ts: pd.Timestamp) -> pd.DataFrame:
    all_rows: list[list] = []
    columns: list[str] | None = None
    offset = 0
    from_iso = from_ts.strftime("%Y-%m-%dT%H:%M:%S")
    to_iso = pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    while True:
        payload = make_payload(offset, from_iso=from_iso, to_iso=to_iso)
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"Erreur HTTP {response.status_code}")
            print(response.text)
            break
        data = response.json()
        if "values" not in data:
            print("Aucune clé 'values' dans la réponse.")
            print(json.dumps(data, indent=2))
            break
        if columns is None:
            columns = data["headers"]
        rows = [[cell["data"] for cell in row] for row in data["values"]]
        if not rows:
            break
        all_rows.extend(rows)
        offset += len(rows)
        time.sleep(0.2)
    if not all_rows:
        return pd.DataFrame(columns=columns or [])
    df = pd.DataFrame(all_rows, columns=columns)
    df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
    return df

def _fetch_date_range(from_iso: str, to_iso: str, columns_ref: list | None) -> tuple[list, list | None]:
    """
    Récupère toutes les pages pour une plage de dates.
    Retourne (all_rows, columns). En cas d'erreur API (ex. SafeMode), retourne ([], None).
    """
    all_rows = []
    columns = columns_ref
    offset = 0
    while True:
        payload = make_payload(offset, from_iso=from_iso, to_iso=to_iso)
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"  Erreur HTTP {response.status_code}")
            return ([], None)
        data = response.json()
        if "values" not in data:
            if data.get("error"):
                print(f"  Erreur API (ex. SafeMode): {data.get('details', data)[:200]}...")
            return ([], None)
        if columns is None:
            columns = data["headers"]
        rows = [[cell["data"] for cell in row] for row in data["values"]]
        if not rows:
            break
        all_rows.extend(rows)
        offset += len(rows)
        time.sleep(DELAY_BETWEEN_REQUESTS_S)
    return (all_rows, columns)


# Télécharge les données pour toutes les années par tranches annuelles (puis semestrielles en secours) pour éviter SafeMode
def run_one_shot_full_download():
    """Récupère toutes les données : année min détectée via l'API (ou 1900 par défaut) → année en cours."""
    to_year = int(os.getenv("USASWIMMING_TO_YEAR", str(pd.Timestamp.utcnow().year)))
    from_year_env = os.getenv("USASWIMMING_FROM_YEAR")
    if from_year_env is not None:
        from_year = int(from_year_env)
        print(f"Année de début (env USASWIMMING_FROM_YEAR) : {from_year}")
    else:
        print("Détection de la date minimale dans l'API...", end=" ", flush=True)
        from_year = fetch_min_swim_date_from_api()
        if from_year is None:
            from_year = 1900
            print(f"indisponible, utilisation de {from_year} par défaut.")
        else:
            print(f"première donnée en {from_year}.")
    all_rows = []
    columns = None

    print(f"Récupération des données pour toutes les années ({from_year} → {to_year}), page size={PAGE_SIZE}...")
    for year in range(from_year, to_year + 1):
        from_iso = f"{year}-01-01T00:00:00"
        to_iso = f"{year}-12-31T23:59:59"
        print(f"  Année {year}...", end=" ", flush=True)
        rows, columns = _fetch_date_range(from_iso, to_iso, columns)
        if rows:
            all_rows.extend(rows)
            print(f"{len(rows)} lignes")
        elif columns is None:
            # Erreur API sur l'année entière : tenter par semestre
            print("erreur, tentative par semestre...")
            for start_month, end_month in [(1, 6), (7, 12)]:
                from_iso = f"{year}-{start_month:02d}-01T00:00:00"
                to_iso = f"{year}-{end_month:02d}-{pd.Timestamp(year, end_month, 1).days_in_month:02d}T23:59:59"
                rows, columns = _fetch_date_range(from_iso, to_iso, columns)
                if rows:
                    all_rows.extend(rows)
                    print(f"    S{start_month}-S{end_month}: {len(rows)} lignes")
            if columns is None:
                print(f"    Année {year} ignorée (API en erreur).")
        else:
            print("0 lignes")
        time.sleep(DELAY_BETWEEN_PERIODS_S)

    if not all_rows:
        print("Aucune donnée récupérée.")
        return
    df = pd.DataFrame(all_rows, columns=columns or [])
    df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
    df = df.sort_values(by="SwimDate", ascending=False)
    print(f"\nTotal : {len(df)} lignes récupérées.")
    print(df.head(20))
    save_data_by_competition(df, append=False)


# Boucle de surveillance continue pour récupérer les nouvelles données (stockage JSON uniquement)
def run_polling_loop():
    latest = _read_latest_swimdate()
    if latest is None:
        days = int(os.getenv("POLL_SINCE_DAYS", "30"))
        from_ts = pd.Timestamp.utcnow() - pd.Timedelta(days=days)
    else:
        from_ts = latest - pd.Timedelta(days=1)

    interval_s = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
    print(f"Démarrage du polling: from={from_ts.isoformat()} interval={interval_s}s")
    while True:
        try:
            df_new = fetch_since(from_ts)
            if df_new.empty:
                print("Aucune nouvelle donnée.")
            else:
                save_data_by_competition(df_new, append=True)
                max_new = df_new["SwimDate"].max()
                if pd.notna(max_new):
                    from_ts = max_new
                    _write_latest_swimdate(from_ts)
                print(f"Nouvelles lignes enregistrées: {len(df_new)}")
        except Exception as e:
            print(f"Erreur pendant le polling: {e}")
        time.sleep(interval_s)


def get_all_results() -> dict:
    """
    Agrège tous les résultats stockés dans USASWIMMING_DATA_DIR.

    Retourne un dict de la forme :
    {
        "count_competitions": <nombre de fichiers JSON de compétitions>,
        "count_results": <nombre total de lignes>,
        "competitions": [
            {
                "year": "<année>",
                "file": "<chemin relatif du fichier>",
                "meet": "<nom de la compétition ou None>",
                "count_results": <nombre de lignes dans ce fichier>,
            },
            ...
        ],
    }
    """
    if not os.path.isdir(USASWIMMING_DATA_DIR):
        return {
            "count_competitions": 0,
            "count_results": 0,
            "competitions": [],
        }

    competitions: list[dict] = []
    total_results = 0

    for root, _dirs, files in os.walk(USASWIMMING_DATA_DIR):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            # Fichiers techniques exclus (commençant par "_")
            if fname.startswith("_"):
                continue

            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                # Fichier illisible ou JSON invalide : on l'ignore
                continue

            if isinstance(data, dict):
                records = [data]
            elif isinstance(data, list):
                records = data
            else:
                records = []

            if not records:
                continue

            nb = len(records)
            total_results += nb

            rel_path = os.path.relpath(path, USASWIMMING_DATA_DIR)
            year = os.path.basename(os.path.dirname(path))
            first = records[0] if isinstance(records, list) else None
            meet_name = first.get("Meet") if isinstance(first, dict) else None

            competitions.append(
                {
                    "year": year,
                    "file": rel_path,
                    "meet": meet_name,
                    "count_results": nb,
                }
            )

    return {
        "count_competitions": len(competitions),
        "count_results": total_results,
        "competitions": competitions,
    }


if __name__ == "__main__":
    polling_on = os.getenv("POLLING_ENABLED", "false").lower() in {"1", "true", "yes"}
    if polling_on:
        run_polling_loop()
    else:
        run_one_shot_full_download()
