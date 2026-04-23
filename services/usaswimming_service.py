import requests
import json
import pandas as pd
import time
import os
import sys
import re
import subprocess

# Répertoire de stockage des données brutes
USASWIMMING_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw", "usaswimming")
)

# URL de l'API (même datasource que dans usaswimming_2024_olympic_trials_service.py)
url = "https://usaswimming.sisense.com/api/datasources/USA%20Swimming%20Times%20Elasticube/jaql?trc=sdk-ui-1.11.0"

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "bearer_token.txt")
DEBUG = os.getenv("USASWIMMING_DEBUG", "true").lower() in {"1", "true", "yes"}
REQUEST_TIMEOUT_S = float(os.getenv("USASWIMMING_REQUEST_TIMEOUT", "120"))


def debug_log(message: str) -> None:
    """Affiche des logs de debug quand USASWIMMING_DEBUG est activé."""
    if DEBUG:
        print(f"[DEBUG] {message}")

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
PAGE_SIZE = int(os.getenv("USASWIMMING_PAGE_SIZE", "2000"))  # 2000 par défaut pour réduire la charge serveur
DELAY_BETWEEN_REQUESTS_S = float(os.getenv("USASWIMMING_DELAY_REQUESTS", "0.5"))
DELAY_BETWEEN_PERIODS_S = float(os.getenv("USASWIMMING_DELAY_PERIODS", "2.0"))
# En cas de SafeMode, attendre avant de réessayer (le serveur annule ~30 s)
SAFEMODE_RETRY_DELAY_S = float(os.getenv("USASWIMMING_SAFEMODE_RETRY_DELAY", "35"))
SAFEMODE_MAX_RETRIES = int(os.getenv("USASWIMMING_SAFEMODE_MAX_RETRIES", "2"))

# Construit le payload JSON pour les requêtes API avec pagination et filtres de dates
def make_payload(offset, from_iso: str | None = None, to_iso: str | None = None, count: int | None = None):
    from_value = from_iso or "1900-01-01T00:00:00"
    to_value = to_iso or "2025-12-31T23:59:59"
    page_size = count if count is not None else PAGE_SIZE
    return {
        "metadata": [
            # Rang officiel (place) tel qu'utilisé par le site USA Swimming,
            # d'après le payload Network : [UsasSwimTime.FinishPosition]
            {
                "jaql": {
                    "title": "Place",
                    "dim": "[UsasSwimTime.FinishPosition]",
                    "datatype": "numeric",
                    "sort": "asc",
                }
            },
            # Même dimension de nom que dans le service 2024 Trials
            {"jaql": {"title": "Name", "dim": "[UsasSwimTime.FullName]", "datatype": "text"}},
            # La dimension OrgUnit.TeamName n'existe pas dans le cube USA Swimming Times Elasticube,
            # on supprime donc temporairement la colonne Federation pour éviter les erreurs API.
            {"jaql": {"title": "Event", "dim": "[SwimEvent.EventCode]", "datatype": "text"}},
            {"jaql": {"title": "Gender", "dim": "[EventCompetitionCategory.TypeName]", "datatype": "text"}},
            {"jaql": {"title": "Session", "dim": "[Session.SessionName]", "datatype": "text"}},
            {"jaql": {"title": "AgeGroup", "dim": "[Age.AgeGroup1]", "datatype": "text"}},
            {"jaql": {"title": "Meet", "dim": "[Meet.MeetName]", "datatype": "text"}},
            {"jaql": {"title": "TimeStandard", "dim": "[TimeStandard.TimeStandardName]", "datatype": "text"}},
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
            # Dimensions de temps alignées sur le cube USA Swimming Times Elasticube
            {"jaql": {"title": "SwimTime", "dim": "[UsasSwimTime.SwimTimeFormatted]", "datatype": "text"}},
            {"jaql": {"title": "SwimTimeSeconds", "dim": "[UsasSwimTime.SwimTimeSeconds]", "datatype": "numeric"}}
        ],
        # Utilise le même cube "USA Swimming Times Elasticube" que pour les Trials 2024,
        # mais avec les dimensions BestTimes / SeasonCalendar pour couvrir tout l'historique.
        "datasource": "USA Swimming Times Elasticube",
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
        # Même datasource que le scraping Trials, pour homogénéiser toutes les requêtes.
        "datasource": "USA Swimming Times Elasticube",
        "by": "ComposeSDK",
        "queryGuid": "min-date",
        "count": 1,
        "offset": 0,
    }
    try:
        debug_log("fetch_min_swim_date_from_api: envoi requête")
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_S)
        debug_log(f"fetch_min_swim_date_from_api: status={response.status_code}")
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


# Fichier state pour le polling (dernière date vue), dans data/raw/usaswimming
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
    "Session",
    "AgeGroup",
    "Meet",
    "TimeStandard",
    "Place",
    "Rank",
    "SwimDate",
    "SwimTimeSeconds",
]


def _parse_sisense_values(data: dict) -> list[dict]:
    """
    Convertit une réponse Sisense JAQL {headers, values} en liste de dicts.

    La réponse renvoie des lignes sous forme de listes de cellules `{data, text}`.
    On mappe chaque cellule sur son header, puis on normalise quelques champs usuels.
    """
    headers_list = data.get("headers") or []
    values = data.get("values") or []
    records: list[dict] = []

    for row in values:
        if not isinstance(row, list):
            continue
        rec: dict = {}
        for i, header in enumerate(headers_list):
            if i >= len(row):
                continue
            cell = row[i]
            if isinstance(cell, dict) and "data" in cell:
                rec[header] = cell.get("data")
            else:
                rec[header] = cell

        # Normalisation: rang (Place) et session (Final / Prelim)
        if "Place" in rec and "Rank" not in rec:
            try:
                rec["Rank"] = int(rec["Place"])
            except Exception:
                rec["Rank"] = rec["Place"]

        records.append(rec)

    return records


def _sanitize_meet_filename(meet_name: str, max_length: int = 120) -> str:
    """Retourne un nom de fichier sûr à partir du nom de compétition."""
    if pd.isna(meet_name) or meet_name == "":
        return "_unknown"
    s = re.sub(r'[<>:"/\\|?*]', "", str(meet_name).strip())
    s = re.sub(r"\s+", "_", s)
    s = s[:max_length].rstrip("_") or "_unknown"
    return s or "_unknown"


def save_data_by_competition(df: pd.DataFrame, append: bool = False) -> None:
    """Enregistre le DataFrame dans data/raw/usaswimming, groupé par date (année) puis par compétition.

    Structure : data/raw/usaswimming/<année>/<compétition>.json
    - Chaque sous-dossier est une année (ex. 2020, 2021).
    - Chaque fichier JSON correspond à une compétition (Meet) pour cette année.

    - append=False : écrase les fichiers existants pour chaque (année, Meet).
    - append=True  : charge le fichier existant si présent, fusionne, déduplique selon KEY_COLUMNS, ré-enregistre.
    """
    if df.empty:
        return
    df = df.copy()
    if "SwimDate" in df.columns:
        df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
        df["_year"] = df["SwimDate"].dt.year
    else:
        # fallback: si pas de SwimDate dans le dataset, on groupe tout dans une pseudo-année
        df["_year"] = pd.NA

    for (year, meet_name), group in df.groupby(["_year", "Meet"], dropna=False):
        year_dir = os.path.join(USASWIMMING_DATA_DIR, str(int(year)))
        os.makedirs(year_dir, exist_ok=True)
        fname = _sanitize_meet_filename(meet_name) + ".json"
        path = os.path.join(year_dir, fname)
        if append and os.path.exists(path):
            try:
                existing = pd.read_json(path, orient="records")
                if "SwimDate" in existing.columns:
                    existing["SwimDate"] = pd.to_datetime(existing["SwimDate"], errors="coerce")
                combined = pd.concat([existing, group], ignore_index=True)
                subset = [c for c in KEY_COLUMNS if c in combined.columns]
                combined = combined.drop_duplicates(subset=subset, keep="last") if subset else combined
            except Exception:
                combined = group
        else:
            combined = group
        combined = combined.drop(columns=["_year"], errors="ignore")
        combined.to_json(path, orient="records", date_format="iso", force_ascii=False, indent=2)
    print(f"Données enregistrées par année et compétition dans {USASWIMMING_DATA_DIR}")


# Récupère les données depuis une date donnée jusqu'à maintenant
def fetch_since(from_ts: pd.Timestamp) -> pd.DataFrame:
    all_records: list[dict] = []
    columns: list[str] | None = None
    offset = 0
    from_iso = from_ts.strftime("%Y-%m-%dT%H:%M:%S")
    to_iso = pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    while True:
        payload = make_payload(offset, from_iso=from_iso, to_iso=to_iso)
        debug_log(f"fetch_since: offset={offset} from={from_iso} to={to_iso}")
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_S)
        debug_log(f"fetch_since: status={response.status_code} offset={offset}")
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
        records = _parse_sisense_values(data)
        if not records:
            break
        all_records.extend(records)
        offset += len(records)
        time.sleep(0.2)
    if not all_records:
        return pd.DataFrame(columns=columns or [])
    df = pd.DataFrame(all_records)
    if "SwimDate" in df.columns:
        df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
    return df

def _is_safemode_error(data: dict) -> bool:
    """Détecte si la réponse API indique une SafeModeException (serveur en surcharge)."""
    err = data.get("error")
    details = data.get("details", "")

    # Certains champs peuvent être booléens ou d'autres types non itérables :
    # on les convertit explicitement en chaîne avant la recherche.
    err_str = str(err) if err is not None else ""
    details_str = str(details) if details is not None else ""

    return (
        "SafeMode" in err_str
        or "SafeMode" in details_str
        or "Safe-Mode" in details_str
    )


def _fetch_date_range(from_iso: str, to_iso: str, columns_ref: list | None) -> tuple[list, list | None]:
    """
    Récupère toutes les pages pour une plage de dates.
    Retourne (all_rows, columns).
    En cas d'erreur API (ex. SafeMode), réessaie après SAFEMODE_RETRY_DELAY_S.
    """
    all_records: list[dict] = []
    columns = columns_ref
    offset = 0
    retries_left = SAFEMODE_MAX_RETRIES
    # Durée de la plage en jours (pour adapter la stratégie SafeMode sur les très grandes fenêtres)
    try:
        range_days = (pd.to_datetime(to_iso) - pd.to_datetime(from_iso)).days
    except Exception:
        range_days = None
    while True:
        payload = make_payload(offset, from_iso=from_iso, to_iso=to_iso)
        debug_log(f"_fetch_date_range: from={from_iso} to={to_iso} offset={offset}")
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_S)
        debug_log(
            f"_fetch_date_range: status={response.status_code} from={from_iso} to={to_iso} offset={offset}"
        )
        if response.status_code != 200:
            print(f"  Erreur HTTP {response.status_code} sur plage {from_iso} → {to_iso}")
            return ([], columns)
        data = response.json()
        if "values" not in data:
            if _is_safemode_error(data) and retries_left > 0:
                # Pour les très grandes plages (typiquement une année complète),
                # on ne s'acharne pas : on laisse le code appelant retenter
                # avec des plages plus petites (semestres / mois) sans attendre longtemps.
                if range_days is not None and range_days >= 180:
                    print(
                        f"  SafeMode détecté sur une plage large ({from_iso} → {to_iso}), "
                        f"abandon des retries pour forcer le fallback plus fin."
                    )
                    return ([], columns)

                retries_left -= 1
                print(
                    f"  SafeMode détecté, attente {SAFEMODE_RETRY_DELAY_S}s puis retry "
                    f"(reste {retries_left})..."
                )
                time.sleep(SAFEMODE_RETRY_DELAY_S)
                continue
            if data.get("error"):
                print(
                    f"  Erreur API (ex. SafeMode) sur plage {from_iso} → {to_iso}: "
                    f"{str(data.get('details', data))[:200]}..."
                )
            return ([], columns)
        retries_left = SAFEMODE_MAX_RETRIES  # reset après succès
        if columns is None:
            columns = data["headers"]
        records = _parse_sisense_values(data)
        if not records:
            break
        all_records.extend(records)
        offset += len(records)
        time.sleep(DELAY_BETWEEN_REQUESTS_S)
    return (all_records, columns)


# Télécharge les données pour une ou plusieurs années par tranches annuelles (puis semestrielles en secours) pour éviter SafeMode
def run_one_shot_full_download(from_year: int | None = None, to_year: int | None = None) -> dict:
    """
    Récupère toutes les données : année min détectée via l'API (ou 1900 par défaut) → année en cours.

    Retourne un dict de statut pour usage HTTP :
    {
        "success": bool,
        "http_status": int,
        "message": str,
        "count_results": int,
    }
    """
    try:
        # Si les années ne sont pas fournies en arguments, on retombe sur
        # les variables d'environnement / détection automatique comme avant.
        if to_year is None:
            to_year = int(os.getenv("USASWIMMING_TO_YEAR", str(pd.Timestamp.utcnow().year)))

        if from_year is None:
            from_year_env = os.getenv("USASWIMMING_FROM_YEAR")
            if from_year_env is not None:
                from_year = int(from_year_env)
                print(f"Année de début (env USASWIMMING_FROM_YEAR) : {from_year}")
            else:
                print("Détection de la date minimale dans l'API...", end=" ", flush=True)
                from_year_detected = fetch_min_swim_date_from_api()
                if from_year_detected is None:
                    from_year = 1900
                    print(f"indisponible, utilisation de {from_year} par défaut.")
                else:
                    from_year = from_year_detected
                    print(f"première donnée en {from_year}.")

        all_records: list[dict] = []
        columns: list | None = None

        print(
            f"Récupération des données pour toutes les années "
            f"({from_year} → {to_year}), page size={PAGE_SIZE}..."
        )
        for year in range(from_year, to_year + 1):
            year_rows_before = len(all_records)
            from_iso = f"{year}-01-01T00:00:00"
            to_iso = f"{year}-12-31T23:59:59"
            print(f"  Année {year}...", end=" ", flush=True)

            # 1) tentative sur l'année entière
            rows, columns = _fetch_date_range(from_iso, to_iso, columns)
            if rows:
                all_records.extend(rows)
                print(f"{len(rows)} lignes (année complète)")
            else:
                print("0 lignes sur l'année, tentative par semestre...")
                # 2) fallback par semestre
                for start_month, end_month in [(1, 6), (7, 12)]:
                    from_iso = f"{year}-{start_month:02d}-01T00:00:00"
                    last_day = pd.Timestamp(year, end_month, 1).days_in_month
                    to_iso = f"{year}-{end_month:02d}-{last_day:02d}T23:59:59"
                    rows_sem, columns = _fetch_date_range(from_iso, to_iso, columns)
                    if rows_sem:
                        all_records.extend(rows_sem)
                        print(f"    S{start_month}-S{end_month}: {len(rows_sem)} lignes")

            # 3) si toujours rien, fallback par mois (requêtes plus légères pour éviter SafeMode)
            if len(all_records) == year_rows_before:
                print("    Tentative par mois...")
                for month in range(1, 13):
                    from_iso = f"{year}-{month:02d}-01T00:00:00"
                    last_day = pd.Timestamp(year, month, 1).days_in_month
                    to_iso = f"{year}-{month:02d}-{last_day:02d}T23:59:59"
                    rows_mo, columns = _fetch_date_range(from_iso, to_iso, columns)
                    if rows_mo:
                        all_records.extend(rows_mo)
                        print(f"    {year}-{month:02d}: {len(rows_mo)} lignes")
                    time.sleep(DELAY_BETWEEN_REQUESTS_S)

            if len(all_records) == year_rows_before:
                print(f"    Aucune donnée récupérée pour {year} (même après fallback).")

            time.sleep(DELAY_BETWEEN_PERIODS_S)

        if not all_records:
            msg = "Aucune donnée récupérée depuis l'API USA Swimming."
            print(msg)
            return {
                "success": False,
                "http_status": 502,
                "message": msg,
                "count_results": 0,
            }

        df = pd.DataFrame(all_records)
        if "SwimDate" in df.columns:
            df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
            df = df.sort_values(by="SwimDate", ascending=False)
        print(f"\nTotal : {len(df)} lignes récupérées.")
        print(f"Nombre total de performances collectées : {len(df)}")
        print(df.head(20))
        save_data_by_competition(df, append=False)

        return {
            "success": True,
            "http_status": 200,
            "message": f"{len(df)} lignes récupérées et enregistrées.",
            "count_results": int(len(df)),
        }
    except Exception as exc:
        msg = f"Exception pendant le téléchargement complet USA Swimming : {exc}"
        print(msg)
        return {
            "success": False,
            "http_status": 500,
            "message": msg,
            "count_results": 0,
        }


def _fetch_single_calendar_month(
    year: int, month: int, columns: list | None
) -> tuple[list[dict], list | None]:
    """Récupère toutes les lignes pour un mois calendaire (avec fallback demi-mois si besoin)."""
    last_day = pd.Timestamp(year, month, 1).days_in_month
    from_iso = f"{year}-{month:02d}-01T00:00:00"
    to_iso = f"{year}-{month:02d}-{last_day:02d}T23:59:59"
    all_records: list[dict] = []

    rows, columns = _fetch_date_range(from_iso, to_iso, columns)
    if rows:
        all_records.extend(rows)
    else:
        mid_day = max(1, last_day // 2)
        ranges = [
            (f"{year}-{month:02d}-01T00:00:00", f"{year}-{month:02d}-{mid_day:02d}T23:59:59"),
            (
                f"{year}-{month:02d}-{mid_day+1:02d}T00:00:00",
                f"{year}-{month:02d}-{last_day:02d}T23:59:59",
            )
            if mid_day + 1 <= last_day
            else None,
        ]
        for r in ranges:
            if r is None:
                continue
            rows_part, columns = _fetch_date_range(r[0], r[1], columns)
            if rows_part:
                all_records.extend(rows_part)

    return (all_records, columns)


def run_one_shot_month_download(year: int, month: int) -> dict:
    """
    Télécharge uniquement un mois (année + mois) et enregistre dans data/raw/usaswimming/<year>/.

    Sert à éviter SafeMode quand on veut un intervalle plus petit qu'une année.
    """
    try:
        if month < 1 or month > 12:
            return {
                "success": False,
                "http_status": 400,
                "message": f"Mois invalide: {month}. Attendu 1-12.",
                "count_results": 0,
            }

        last_day = pd.Timestamp(year, month, 1).days_in_month
        from_iso = f"{year}-{month:02d}-01T00:00:00"
        to_iso = f"{year}-{month:02d}-{last_day:02d}T23:59:59"

        print(f"Téléchargement des données USA Swimming pour {from_iso} → {to_iso}")

        columns: list | None = None
        all_records, columns = _fetch_single_calendar_month(year, month, columns)

        if not all_records:
            return {
                "success": False,
                "http_status": 502,
                "message": f"Aucune donnée récupérée pour {year}-{month:02d}.",
                "count_results": 0,
            }

        df = pd.DataFrame(all_records)
        if "SwimDate" in df.columns:
            df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
            df = df.sort_values(by="SwimDate", ascending=False)

        # Enregistre groupé par Meet (et par année via SwimDate)
        save_data_by_competition(df, append=False)

        return {
            "success": True,
            "http_status": 200,
            "message": f"{len(df)} lignes récupérées pour {year}-{month:02d} et enregistrées.",
            "count_results": int(len(df)),
        }
    except Exception as exc:
        msg = f"Exception pendant le téléchargement mensuel USA Swimming : {exc}"
        print(msg)
        return {
            "success": False,
            "http_status": 500,
            "message": msg,
            "count_results": 0,
        }


def run_one_shot_month_range_download(
    from_year: int, from_month: int, to_year: int, to_month: int
) -> dict:
    """
    Télécharge de (from_year, from_month) à (to_year, to_month) inclus,
    mois par mois (même stratégie SafeMode que le téléchargement mensuel).
    """
    try:
        for m in (from_month, to_month):
            if m < 1 or m > 12:
                return {
                    "success": False,
                    "http_status": 400,
                    "message": f"Mois invalide: {m}. Attendu 1-12.",
                    "count_results": 0,
                }
        start = pd.Period(f"{from_year}-{from_month:02d}", freq="M")
        end = pd.Period(f"{to_year}-{to_month:02d}", freq="M")
        if start > end:
            return {
                "success": False,
                "http_status": 400,
                "message": (
                    f"Date de début après la fin : {from_year}-{from_month:02d} > {to_year}-{to_month:02d}."
                ),
                "count_results": 0,
            }

        print(
            f"Téléchargement USA Swimming du mois {from_year}-{from_month:02d} "
            f"au mois {to_year}-{to_month:02d} (inclus)..."
        )
        all_records: list[dict] = []
        columns: list | None = None
        for period in pd.period_range(start, end, freq="M"):
            y, mo = period.year, period.month
            print(f"  {y}-{mo:02d}...", end=" ", flush=True)
            chunk, columns = _fetch_single_calendar_month(y, mo, columns)
            all_records.extend(chunk)
            print(f"{len(chunk)} lignes")
            time.sleep(DELAY_BETWEEN_REQUESTS_S)

        if not all_records:
            return {
                "success": False,
                "http_status": 502,
                "message": (
                    f"Aucune donnée pour la plage {from_year}-{from_month:02d} → "
                    f"{to_year}-{to_month:02d}."
                ),
                "count_results": 0,
            }

        df = pd.DataFrame(all_records)
        if "SwimDate" in df.columns:
            df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
            df = df.sort_values(by="SwimDate", ascending=False)

        save_data_by_competition(df, append=False)

        return {
            "success": True,
            "http_status": 200,
            "message": (
                f"{len(df)} lignes pour {from_year}-{from_month:02d} → {to_year}-{to_month:02d} "
                "enregistrées."
            ),
            "count_results": int(len(df)),
        }
    except Exception as exc:
        msg = f"Exception pendant le téléchargement par plage de mois : {exc}"
        print(msg)
        return {
            "success": False,
            "http_status": 500,
            "message": msg,
            "count_results": 0,
        }


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


def get_all_results_grouped_by_event() -> dict:
    """
    Agrège tous les résultats stockés dans USASWIMMING_DATA_DIR,
    groupés par `Event`.

    Structure retournée :
    {
        "count_events": <nombre d'events distincts>,
        "count_results": <nombre total de lignes>,
        "events": {
            "<Event>": [ { ... ligne brute ... }, ... ],
            ...
        }
    }
    """
    if not os.path.isdir(USASWIMMING_DATA_DIR):
        return {
            "count_events": 0,
            "count_results": 0,
            "events": {},
        }

    events: dict[str, list[dict]] = {}
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

            for rec in records:
                if not isinstance(rec, dict):
                    continue
                event_name = rec.get("Event") or "_unknown"
                events.setdefault(event_name, []).append(rec)
                total_results += 1

    return {
        "count_events": len(events),
        "count_results": total_results,
        "events": events,
    }


def get_all_results_grouped_by_event_as_list() -> list[dict]:
    """
    Variante de `get_all_results_grouped_by_event` qui retourne une liste
    de blocs de la forme :

    [
      {
        "Event": "50 BR LCM",
        "results": [
          { "Name": "...", "Federation": "...", ... },
          ...
        ]
      },
      ...
    ]

    C'est cette structure qui correspond à ta demande :

        "Event": "50 BR LCM",
        {
          "Name": "...",
          ...
        }
    """
    grouped = get_all_results_grouped_by_event()
    events_dict: dict[str, list[dict]] = grouped.get("events", {})
    result: list[dict] = []
    for event_name, records in events_dict.items():
        result.append(
            {
                "Event": event_name,
                "results": records,
            }
        )
    return result


if __name__ == "__main__":
    debug_log(
        f"USASWIMMING_DEBUG={DEBUG} REQUEST_TIMEOUT_S={REQUEST_TIMEOUT_S} PAGE_SIZE={PAGE_SIZE}"
    )
    polling_on = os.getenv("POLLING_ENABLED", "false").lower() in {"1", "true", "yes"}
    if polling_on:
        run_polling_loop()
    else:
        # Utilisation possible :
        #   python3 usaswimming_service.py          -> toutes les années (comportement historique)
        #   python3 usaswimming_service.py 2002     -> uniquement l'année 2002
        #   python3 usaswimming_service.py 2000 2005 -> de 2000 à 2005 inclus
        #   python3 usaswimming_service.py 2024 01 -> uniquement janvier 2024
        #   python3 usaswimming_service.py 2024 01 2024 05 -> janv. à mai 2024 inclus
        if len(sys.argv) == 5:
            try:
                y_start = int(sys.argv[1])
                m_start = int(sys.argv[2])
                y_end = int(sys.argv[3])
                m_end = int(sys.argv[4])
            except ValueError:
                print(
                    "Arguments invalides. Attendu : "
                    "python3 usaswimming_service.py <année_début> <mois_début> <année_fin> <mois_fin> "
                    "(mois 1-12)."
                )
                sys.exit(1)
            print(run_one_shot_month_range_download(y_start, m_start, y_end, m_end))
        else:
            from_arg: int | None = None
            to_arg: int | None = None
            if len(sys.argv) >= 2:
                try:
                    from_arg = int(sys.argv[1])
                except ValueError:
                    print(f"Argument d'année invalide: {sys.argv[1]!r}. Ignoré.")
                    from_arg = None
            if len(sys.argv) >= 3:
                try:
                    to_arg = int(sys.argv[2])
                except ValueError:
                    print(f"Second argument d'année invalide: {sys.argv[2]!r}. Ignoré.")
                    to_arg = from_arg
            if from_arg is not None and to_arg is None:
                to_arg = from_arg

            if from_arg is not None and to_arg is not None:
                # Cas "AAAA MM" : on interprète le 2e argument comme un mois si 1..12
                if 1 <= to_arg <= 12 and len(sys.argv) == 3:
                    month_result = run_one_shot_month_download(from_arg, to_arg)
                    print(month_result)
                else:
                    print(f"Téléchargement des données USA Swimming pour {from_arg} → {to_arg}")
                    run_one_shot_full_download(from_arg, to_arg)
            else:
                run_one_shot_full_download()
