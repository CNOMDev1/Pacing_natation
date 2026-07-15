"""Scraping de l'API Sisense USA Swimming (chronos historiques).

Ce module interroge l'API JAQL Sisense (``USA Swimming Times Elasticube``),
paginate par fenêtres de dates et persiste les réponses brutes sous
``data/raw/usaswimming/{year}/{meet}.json``.

Le flux de données :
1. **Authentification** — ``load_bearer_token()`` lit ``bearer_token.txt`` ou
   exécute ``get_token_usaswimming.py`` si le fichier est absent.
2. **Téléchargement** — ``run_one_shot_full_download()`` (ou variantes mensuelles)
   récupère les performances par plages annuelles, avec fallback semestriel /
   mensuel en cas de ``SafeModeException``.
3. **Persistance** — ``save_data_by_competition()`` regroupe par année et par
   compétition (``Meet``), avec déduplication optionnelle à l'ajout.
4. **Polling** — ``run_polling_loop()`` surveille les nouvelles nages et met à
   jour les JSON existants via ``_latest_swimdate.txt``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Optional

import pandas as pd
import requests

USASWIMMING_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw", "usaswimming")
)

# Endpoint JAQL Sisense — même datasource que usaswimming_2024_olympic_trials_service.py.
url = "https://usaswimming.sisense.com/api/datasources/USA%20Swimming%20Times%20Elasticube/jaql?trc=sdk-ui-1.11.0"

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "bearer_token.txt")
DEBUG = os.getenv("USASWIMMING_DEBUG", "true").lower() in {"1", "true", "yes"}
REQUEST_TIMEOUT_S = float(os.getenv("USASWIMMING_REQUEST_TIMEOUT", "120"))


def debug_log(message: str) -> None:
    """Affiche un message de debug si ``USASWIMMING_DEBUG`` est activé.

    Args:
        message (str): Texte à journaliser.

    Returns:
        None
    """
    if DEBUG:
        print(f"[DEBUG] {message}")


def load_bearer_token() -> str:
    """Charge le token Bearer depuis ``bearer_token.txt``.

    Si le fichier est absent, exécute ``get_token_usaswimming.py`` avec
    l'interpréteur courant puis relit le token généré.

    Args:
        None

    Returns:
        str: Token préfixé par ``Bearer `` si nécessaire.

    Raises:
        FileNotFoundError: Si le fichier token et le script de génération sont absents.
        RuntimeError: Si l'exécution de ``get_token_usaswimming.py`` échoue.
    """
    if not os.path.exists(TOKEN_FILE):
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "scripts", "get_token_usaswimming.py")
        )
        if not os.path.exists(script_path):
            raise FileNotFoundError(
                f"{TOKEN_FILE} introuvable et {script_path} également manquant."
            )
        # Génération automatique : le script d'auth écrit bearer_token.txt à côté de ce module.
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

# En-têtes HTTP Sisense : le token est rechargé au démarrage du module.
headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "fr,fr-FR;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "authorization": load_bearer_token(),
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://data.usaswimming.org",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
}

# Pagination et temporisation : valeurs conservatrices pour limiter les SafeModeException.
PAGE_SIZE = int(os.getenv("USASWIMMING_PAGE_SIZE", "2000"))
DELAY_BETWEEN_REQUESTS_S = float(os.getenv("USASWIMMING_DELAY_REQUESTS", "0.5"))
DELAY_BETWEEN_PERIODS_S = float(os.getenv("USASWIMMING_DELAY_PERIODS", "2.0"))
# SafeMode : le serveur Sisense coupe la requête après ~30 s — on attend avant de réessayer.
SAFEMODE_RETRY_DELAY_S = float(os.getenv("USASWIMMING_SAFEMODE_RETRY_DELAY", "35"))
SAFEMODE_MAX_RETRIES = int(os.getenv("USASWIMMING_SAFEMODE_MAX_RETRIES", "2"))

def make_payload(
    offset: int,
    from_iso: str | None = None,
    to_iso: str | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    """Construit le payload JAQL Sisense avec pagination et filtre de dates.

    Args:
        offset (int): Décalage de pagination (lignes déjà récupérées).
        from_iso (str | None): Borne basse du filtre ``SwimDate`` (ISO 8601).
        to_iso (str | None): Borne haute du filtre ``SwimDate`` (ISO 8601).
        count (int | None): Taille de page ; ``PAGE_SIZE`` si ``None``.

    Returns:
        dict[str, Any]: Corps JSON prêt pour ``requests.post``.
    """
    from_value = from_iso or "1900-01-01T00:00:00"
    to_value = to_iso or "2025-12-31T23:59:59"
    page_size = count if count is not None else PAGE_SIZE
    return {
        "metadata": [
            # Place officielle — dimension [UsasSwimTime.FinishPosition] du cube Sisense.
            {
                "jaql": {
                    "title": "Place",
                    "dim": "[UsasSwimTime.FinishPosition]",
                    "datatype": "numeric",
                    "sort": "asc",
                }
            },
            {"jaql": {"title": "Name", "dim": "[UsasSwimTime.FullName]", "datatype": "text"}},
            # Federation absente : OrgUnit.TeamName n'existe pas dans ce cube Elasticube.
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
            {"jaql": {"title": "SwimTime", "dim": "[UsasSwimTime.SwimTimeFormatted]", "datatype": "text"}},
            {"jaql": {"title": "SwimTimeSeconds", "dim": "[UsasSwimTime.SwimTimeSeconds]", "datatype": "numeric"}}
        ],
        "datasource": "USA Swimming Times Elasticube",
        "by": "ComposeSDK",
        "queryGuid": f"page-{offset}",
        "count": page_size,
        "offset": offset
    }


def fetch_min_swim_date_from_api() -> int | None:
    """Interroge l'API pour obtenir l'année de la nage la plus ancienne.

    Envoie une requête d'une seule ligne triée par ``SwimDate`` croissant.

    Args:
        None

    Returns:
        int | None: Année de la première nage, ou ``None`` si l'API ne répond pas.
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


# Pointeur de reprise pour le polling : dernière SwimDate traitée.
LATEST_SWIMDATE_FILE = os.path.join(USASWIMMING_DATA_DIR, "_latest_swimdate.txt")


def _read_latest_swimdate() -> pd.Timestamp | None:
    """Lit la dernière date de nage enregistrée pour le polling.

    Args:
        None

    Returns:
        pd.Timestamp | None: Timestamp lu depuis ``_latest_swimdate.txt``, ou ``None``.
    """
    if not os.path.exists(LATEST_SWIMDATE_FILE):
        return None
    try:
        with open(LATEST_SWIMDATE_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        return pd.to_datetime(raw, errors="coerce")
    except Exception:
        return None


def _write_latest_swimdate(ts: pd.Timestamp) -> None:
    """Persiste la dernière date de nage traitée par le polling.

    Args:
        ts (pd.Timestamp): Date maximale à enregistrer.

    Returns:
        None
    """
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
    """Convertit une réponse Sisense JAQL ``{headers, values}`` en lignes dict.

    Chaque cellule est un objet ``{data, text}`` ; on mappe sur le header
    correspondant et on dérive ``Rank`` depuis ``Place`` si absent.

    Args:
        data (dict): Réponse JSON brute de l'API Sisense.

    Returns:
        list[dict]: Enregistrements aplatis prêts pour un DataFrame.
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

        # Rank dérivé de Place pour homogénéiser avec les autres modules du projet.
        if "Place" in rec and "Rank" not in rec:
            try:
                rec["Rank"] = int(rec["Place"])
            except Exception:
                rec["Rank"] = rec["Place"]

        records.append(rec)

    return records


def _sanitize_meet_filename(meet_name: str, max_length: int = 120) -> str:
    """Retourne un nom de fichier sûr à partir du nom de compétition.

    Args:
        meet_name (str): Libellé ``Meet`` tel que renvoyé par l'API.
        max_length (int): Longueur maximale du nom de fichier (hors extension).

    Returns:
        str: Identifiant fichier sans caractères interdits.
    """
    if pd.isna(meet_name) or meet_name == "":
        return "_unknown"
    s = re.sub(r'[<>:"/\\|?*]', "", str(meet_name).strip())
    s = re.sub(r"\s+", "_", s)
    s = s[:max_length].rstrip("_") or "_unknown"
    return s or "_unknown"


def save_data_by_competition(df: pd.DataFrame, append: bool = False) -> None:
    """Enregistre les performances groupées par année puis par compétition.

    Structure cible : ``data/raw/usaswimming/{year}/{meet}.json``.
    En mode ``append=True``, fusionne avec le fichier existant et déduplique
    sur ``KEY_COLUMNS``.

    Args:
        df (pd.DataFrame): Performances à persister.
        append (bool): Si ``True``, fusionne et déduplique ; sinon écrase.

    Returns:
        None
    """
    if df.empty:
        return
    df = df.copy()
    if "SwimDate" in df.columns:
        df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
        df["_year"] = df["SwimDate"].dt.year
    else:
        # Sans SwimDate : regroupement dans un dossier d'année indéterminée.
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
        # Validation schéma Pydantic avant écriture (best-effort)
        try:
            from app.models.usaswimming_models import NageursList

            NageursList.model_validate(combined.to_dict(orient="records"))
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] validation Pydantic USA {fname}: {exc}")
        combined.to_json(path, orient="records", date_format="iso", force_ascii=False, indent=2)
    print(f"Données enregistrées par année et compétition dans {USASWIMMING_DATA_DIR}")


def fetch_since(from_ts: pd.Timestamp) -> pd.DataFrame:
    """Récupère toutes les nages depuis une date jusqu'à maintenant.

    Paginate l'API Sisense jusqu'à épuisement des résultats pour la plage
    ``[from_ts, maintenant]``.

    Args:
        from_ts (pd.Timestamp): Date/heure de début inclusive pour ``SwimDate``.

    Returns:
        pd.DataFrame: Performances paginées, vide si aucune donnée.
    """
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
    """Détecte une réponse SafeMode (serveur Sisense en surcharge).

    Args:
        data (dict): Corps JSON de la réponse API.

    Returns:
        bool: ``True`` si une SafeModeException est signalée.
    """
    err = data.get("error")
    details = data.get("details", "")

    # error/details peuvent être non-str : conversion explicite avant la recherche.
    err_str = str(err) if err is not None else ""
    details_str = str(details) if details is not None else ""

    return (
        "SafeMode" in err_str
        or "SafeMode" in details_str
        or "Safe-Mode" in details_str
    )


def _fetch_date_range(from_iso: str, to_iso: str, columns_ref: list | None) -> tuple[list, list | None]:
    """Récupère toutes les pages pour une plage de dates.

    En cas de SafeMode, attend ``SAFEMODE_RETRY_DELAY_S`` puis réessaie jusqu'à
    ``SAFEMODE_MAX_RETRIES``. Sur les plages larges (≥ 180 jours), abandonne
    rapidement pour laisser l'appelant subdiviser la fenêtre.

    Args:
        from_iso (str): Borne basse ISO 8601 du filtre ``SwimDate``.
        to_iso (str): Borne haute ISO 8601 du filtre ``SwimDate``.
        columns_ref (list | None): En-têtes déjà connus d'une page précédente.

    Returns:
        tuple[list, list | None]: ``(lignes, colonnes)`` ; liste vide si échec.
    """
    all_records: list[dict] = []
    columns = columns_ref
    offset = 0
    retries_left = SAFEMODE_MAX_RETRIES
    # Durée de la plage : sert à court-circuiter les retries sur les fenêtres annuelles.
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
                # Plage large : on force le fallback semestriel/mensuel sans attendre 35 s.
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
        retries_left = SAFEMODE_MAX_RETRIES
        if columns is None:
            columns = data["headers"]
        records = _parse_sisense_values(data)
        if not records:
            break
        all_records.extend(records)
        offset += len(records)
        time.sleep(DELAY_BETWEEN_REQUESTS_S)
    return (all_records, columns)


def run_one_shot_full_download(from_year: int | None = None, to_year: int | None = None) -> dict:
    """Télécharge l'historique complet par tranches annuelles (fallback semestriel / mensuel).

    Détecte l'année minimale via l'API si non fournie, puis parcourt chaque année
    avec subdivision progressive en cas de SafeMode.

    Args:
        from_year (int | None): Première année incluse. Défaut : env ou détection API.
        to_year (int | None): Dernière année incluse. Défaut : année courante.

    Returns:
        dict: Statut HTTP ``{success, http_status, message, count_results}``.
    """
    try:
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

            # Stratégie 1 : année entière (moins de requêtes si le serveur tient la charge).
            rows, columns = _fetch_date_range(from_iso, to_iso, columns)
            if rows:
                all_records.extend(rows)
                print(f"{len(rows)} lignes (année complète)")
            else:
                print("0 lignes sur l'année, tentative par semestre...")
                # Stratégie 2 : deux semestres si l'année complète déclenche SafeMode.
                for start_month, end_month in [(1, 6), (7, 12)]:
                    from_iso = f"{year}-{start_month:02d}-01T00:00:00"
                    last_day = pd.Timestamp(year, end_month, 1).days_in_month
                    to_iso = f"{year}-{end_month:02d}-{last_day:02d}T23:59:59"
                    rows_sem, columns = _fetch_date_range(from_iso, to_iso, columns)
                    if rows_sem:
                        all_records.extend(rows_sem)
                        print(f"    S{start_month}-S{end_month}: {len(rows_sem)} lignes")

            # Stratégie 3 : mois par mois — fenêtres minimales pour contourner SafeMode.
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
    """Récupère toutes les lignes d'un mois calendaire.

    Si le mois entier échoue, subdivise en deux demi-mois.

    Args:
        year (int): Année cible.
        month (int): Mois calendaire (1–12).
        columns (list | None): En-têtes déjà connus d'une page précédente.

    Returns:
        tuple[list[dict], list | None]: ``(lignes, colonnes)``.
    """
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
    """Télécharge et enregistre les performances d'un seul mois.

    Utile pour des plages courtes sans déclencher SafeMode sur une année entière.

    Args:
        year (int): Année cible.
        month (int): Mois calendaire (1–12).

    Returns:
        dict: Statut HTTP ``{success, http_status, message, count_results}``.
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
    """Télécharge une plage de mois consécutifs, mois par mois.

    Applique la même stratégie SafeMode que ``run_one_shot_month_download``.

    Args:
        from_year (int): Année de début.
        from_month (int): Mois de début (1–12).
        to_year (int): Année de fin.
        to_month (int): Mois de fin (1–12).

    Returns:
        dict: Statut HTTP ``{success, http_status, message, count_results}``.
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


def run_polling_loop() -> None:
    """Surveille en continu les nouvelles nages et les ajoute aux JSON existants.

    Reprend après ``_latest_swimdate.txt`` (ou ``POLL_SINCE_DAYS`` si absent).
    L'intervalle entre deux passages est contrôlé par ``POLL_INTERVAL_SECONDS``.

    Args:
        None

    Returns:
        None
    """
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
    """Agrège les métadonnées de tous les JSON stockés sous ``USASWIMMING_DATA_DIR``.

    Args:
        None

    Returns:
        dict: ``{count_competitions, count_results, competitions}`` où chaque
            entrée de ``competitions`` décrit un fichier ``{year, file, meet, count_results}``.
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
            # Fichiers d'état (_latest_swimdate.txt, etc.) : préfixe "_" ignoré.
            if fname.startswith("_"):
                continue

            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
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
    """Agrège toutes les performances groupées par épreuve (``Event``).

    Args:
        None

    Returns:
        dict: ``{count_events, count_results, events}`` où ``events`` mappe
            chaque libellé d'épreuve vers la liste des lignes brutes.
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
            # Fichiers d'état (_latest_swimdate.txt, etc.) : préfixe "_" ignoré.
            if fname.startswith("_"):
                continue

            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
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
    """Retourne les performances groupées par épreuve sous forme de liste.

    Chaque élément est un bloc ``{"Event": "<libellé>", "results": [...]}``.

    Args:
        None

    Returns:
        list[dict]: Liste de blocs épreuve / performances.
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
        # CLI : python3 usaswimming_service.py [année_début] [année_fin|mois]
        #   sans args          -> téléchargement complet
        #   2002               -> année 2002 seule
        #   2000 2005          -> plage annuelle inclusive
        #   2024 01            -> janvier 2024
        #   2024 01 2024 05    -> janvier à mai 2024
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
                # Deux arguments avec 2e valeur 1–12 : interprétation année + mois.
                if 1 <= to_arg <= 12 and len(sys.argv) == 3:
                    month_result = run_one_shot_month_download(from_arg, to_arg)
                    print(month_result)
                else:
                    print(f"Téléchargement des données USA Swimming pour {from_arg} → {to_arg}")
                    run_one_shot_full_download(from_arg, to_arg)
            else:
                run_one_shot_full_download()
