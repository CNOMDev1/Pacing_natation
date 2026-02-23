import requests
import json
import re
import pandas as pd
import time
import os
import sys
from playwright.sync_api import sync_playwright

# Permet d'importer app quand le script est lancé directement (ex: python3 usaswimming_service.py)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.models.usaswimming_models import NageurRecord

# URL de l'API
url = "https://usaswimming.sisense.com/api/datasources/USA%20Swimming%20Times%20Elasticube/jaql?trc=sdk-ui-1.11.0"

BASE_DIR = os.path.dirname(__file__)
TOKEN_FILE = os.path.join(BASE_DIR, "bearer_token.txt")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
DATA_HUB_URL = "https://data.usaswimming.org"
WAIT_FOR = 20  # secondes d'attente pour que le dashboard fasse ses requêtes


def run_headed_and_save_state(user_data_dir=None):
    """
    Ouvre un navigateur en mode persistant/headed pour te permettre de te connecter,
    puis sauvegarde le storage_state dans STATE_FILE.
    """
    print("Mode interactive: ouverture du navigateur pour te connecter manuellement...")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir or "playwright_tmp_profile",
            headless=False,
            channel="chrome",
            args=["--start-maximized"]
        )
        page = context.new_page()
        page.goto(DATA_HUB_URL)
        print(f"Connecte-toi sur {DATA_HUB_URL} puis appuie sur Entrée ici quand c'est fait...")
        input("Après connexion, appuie Entrée pour continuer et sauvegarder le state...")
        context.storage_state(path=STATE_FILE)
        print(f"[OK] state sauvegardé dans {STATE_FILE}")
        context.close()


def capture_token_with_storage_state(headless=True):
    """
    Lance un navigateur headless (ou non) en réutilisant STATE_FILE, écoute les requêtes
    et récupère le header Authorization: Bearer ...
    """
    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError(f"{STATE_FILE} introuvable. Lance d'abord le script en mode interactif pour te connecter.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chrome")
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()

        found = {"token": None}

        def on_request(request):
            hdrs = request.headers
            auth = hdrs.get("authorization") or hdrs.get("Authorization")
            if auth and auth.startswith("Bearer "):
                print("Bearer token trouvé :", auth)
                found["token"] = auth
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(auth)

        page.on("request", on_request)
        page.goto(DATA_HUB_URL)
        print(f"Attente {WAIT_FOR} secondes pour laisser le dashboard charger et envoyer les requêtes...")
        time.sleep(WAIT_FOR)

        if not found["token"]:
            print("Token non trouvé dans le délai initial, attente supplémentaire de 10s...")
            time.sleep(10)

        context.close()
        browser.close()

        if not found["token"]:
            print("Aucun token trouvé — vérifie que ton state.json est valide et que le compte a les droits pour accéder au Data Hub.")
        else:
            print(f"[OK] Token sauvegardé dans {TOKEN_FILE}")
        # Mise à jour de state.json avec l'état actuel de la session (cookies, etc.)
        try:
            context.storage_state(path=STATE_FILE)
            print(f"[OK] state sauvegardé dans {STATE_FILE}", flush=True)
        except Exception as e:
            print(f"Impossible de sauver state: {e}", flush=True)


def load_bearer_token() -> str:
    """Charge le token Bearer; génère le token via Playwright si le fichier est absent.

    - Cherche le fichier TOKEN_FILE dans le même dossier que ce script
    - Si absent et state.json absent: ouvre le navigateur pour connexion manuelle, puis il faut relancer
    - Si absent et state.json présent: capture le token en headless
    - Retourne le token (préfixé par 'Bearer ' si nécessaire)
    """
    if not os.path.exists(TOKEN_FILE):
        if not os.path.exists(STATE_FILE):
            print(f"{STATE_FILE} non trouvé.")
            run_headed_and_save_state(user_data_dir=None)
            print("Capture du token en cours...")
            try:
                capture_token_with_storage_state(headless=True)
            except Exception as e:
                print("Erreur lors de la capture headless:", e)
                print("Tentative en mode visible...")
                capture_token_with_storage_state(headless=False)
        else:
            try:
                capture_token_with_storage_state(headless=True)
            except Exception as e:
                print("Erreur lors de la capture headless:", e)
                print("Tentative de fallback en mode non-headless pour debug...")
                capture_token_with_storage_state(headless=False)

    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} introuvable après capture du token."
        )

    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    return raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"


def refresh_bearer_token_and_state():
    """
    En cas de token expiré (401) : supprime bearer_token.txt, relance la capture
    via state.json et met à jour bearer_token.txt et state.json.
    Retourne True si un nouveau token a été capturé, False sinon.
    """
    if os.path.exists(TOKEN_FILE):
        try:
            os.remove(TOKEN_FILE)
        except OSError:
            pass
    if not os.path.exists(STATE_FILE):
        print(f"[refresh] {STATE_FILE} introuvable, impossible de mettre à jour le token.", flush=True)
        return False
    print("[refresh] Mise à jour du token et du state en cours...", flush=True)
    try:
        capture_token_with_storage_state(headless=True)
    except Exception as e:
        print(f"[refresh] Erreur capture headless: {e}", flush=True)
        try:
            capture_token_with_storage_state(headless=False)
        except Exception as e2:
            print(f"[refresh] Erreur capture visible: {e2}", flush=True)
            return False
    return os.path.exists(TOKEN_FILE)


def get_headers():
    """Headers pour les requêtes API, avec le token Bearer à jour."""
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "fr,fr-FR;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "authorization": load_bearer_token(),
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://data.usaswimming.org",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
    }


# Compatibilité : headers chargés au premier import (pour scripts qui l'utilisent directement)
headers = get_headers()

# Plage de dates pour récupérer toutes les années (toutes les données disponibles)
DATE_FROM = "1900-01-01T00:00:00"
DATE_TO = "2099-12-31T23:59:59"

# Construit le payload JSON pour les requêtes API avec pagination et filtres de dates
def make_payload(offset, from_iso: str | None = None, to_iso: str | None = None):
    from_value = from_iso or DATE_FROM
    to_value = to_iso or DATE_TO
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
        "count": 10000,
        "offset": offset
    }


def _row_to_record(row, columns):
    """Convertit une ligne DataFrame en dict JSON-sérialisable (dates ISO, NaN → null)."""
    d = {}
    for k in columns:
        v = row[k]
        if pd.isna(v):
            d[k] = None
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        else:
            d[k] = v
    return d


def _meet_to_safe_filename(meet_name: str, used: set) -> str:
    """Génère un nom de fichier sûr à partir du nom de compétition (Meet)."""
    s = re.sub(r'[<>:"/\\|?*\x00]', "_", str(meet_name).strip())
    s = re.sub(r"\s+", "_", s).strip("_")[:100] or "unnamed"
    base = s
    filename = f"{s}.json"
    c = 1
    while filename in used:
        filename = f"{base}_{c}.json"
        c += 1
    used.add(filename)
    return filename


# Télécharge toutes les données, toutes années (1900–2099), et les sauvegarde par compétition
# Retourne {"success": True} ou {"success": False, "http_status": int, "message": str}
def run_one_shot_full_download():
    all_rows = []
    columns = None
    offset = 0
    last_error = None
    print("Téléchargement en cours (complet)...", flush=True)
    request_headers = get_headers()
    while True:
        payload = make_payload(offset)
        response = requests.post(url, headers=request_headers, json=payload)
        if response.status_code == 401:
            print(f"Erreur HTTP 401 (token invalide). Tentative de mise à jour de bearer_token.txt et state.json...", flush=True)
            if refresh_bearer_token_and_state():
                request_headers = get_headers()
                print("Nouveau token chargé, nouvelle tentative...", flush=True)
                response = requests.post(url, headers=request_headers, json=payload)
            else:
                print(response.text, flush=True)
                last_error = {"http_status": 401, "message": response.text.strip() or "Invalid token."}
                break
        if response.status_code != 200:
            print(f"Erreur HTTP {response.status_code}", flush=True)
            print(response.text, flush=True)
            last_error = {"http_status": response.status_code, "message": response.text.strip() or f"Erreur HTTP {response.status_code}"}
            break
        data = response.json()
        if "values" not in data:
            print("Aucune clé 'values' dans la réponse.", flush=True)
            print(json.dumps(data, indent=2), flush=True)
            last_error = {"http_status": 502, "message": "Réponse API invalide (pas de 'values')."}
            break
        if columns is None:
            columns = data["headers"]
        rows = [[cell["data"] for cell in row] for row in data["values"]]
        if not rows:
            print("Fin des données atteinte.", flush=True)
            break
        all_rows.extend(rows)
        print(f"Page récupérée : {len(rows)} lignes (offset {offset})", flush=True)
        offset += len(rows)
        time.sleep(0.5)
    if not all_rows:
        print("Aucune donnée récupérée.", flush=True)
        if last_error:
            return {"success": False, "http_status": last_error["http_status"], "message": last_error["message"]}
        return {"success": False, "http_status": 503, "message": "Aucune donnée récupérée."}
    df = pd.DataFrame(all_rows, columns=columns)
    df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
    df = df.sort_values(by="SwimDate", ascending=False)
    print(f"\nTotal de lignes récupérées : {len(df)}", flush=True)
    print(df.head(20), flush=True)

    # Dossier de sortie : un fichier JSON par compétition (Meet)
    out_dir = os.path.join(BASE_DIR, "..", "data", "usaswimming")
    os.makedirs(out_dir, exist_ok=True)
    indent = 2 if os.getenv("JSON_INDENT", "1").lower() in ("1", "true", "yes") else None
    used_filenames = set()
    index = []

    for meet_name, group in df.groupby("Meet", sort=False):
        raw_records = [_row_to_record(row, df.columns) for _, row in group.iterrows()]
        records = [
            NageurRecord(**r).model_dump(mode="json") for r in raw_records
        ]
        filename = _meet_to_safe_filename(meet_name, used_filenames)
        json_path = os.path.join(out_dir, filename)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=indent, allow_nan=False)
        index.append({"meet": meet_name, "file": filename, "count": len(records)})

    # Fichier index : liste des compétitions et leurs fichiers
    index_path = os.path.join(out_dir, "_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2, allow_nan=False)

    # Affichage du nombre de données collectées
    total_donnees = len(df)
    nb_competitions = len(index)
    print(f"\n--- Données collectées ---", flush=True)
    print(f"Nombre total de résultats : {total_donnees}", flush=True)
    print(f"Nombre de compétitions     : {nb_competitions}", flush=True)
    print(f"Données enregistrées dans '{out_dir}/' ({nb_competitions} fichiers + _index.json).", flush=True)
    return {"success": True}


def get_all_results():
    """
    Charge tous les résultats USA Swimming depuis le dossier data/usaswimming.
    Retourne l'index des compétitions et, pour chacune, la liste des résultats.
    """
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "usaswimming")
    index_path = os.path.join(out_dir, "_index.json")
    if not os.path.exists(index_path):
        return {"count_competitions": 0, "count_results": 0, "index": [], "competitions": []}
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    competitions = []
    total_results = 0
    for item in index:
        filepath = os.path.join(out_dir, item["file"])
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                records = json.load(f)
            competitions.append({
                "meet": item["meet"],
                "file": item["file"],
                "count": len(records),
                "results": records,
            })
            total_results += len(records)
        else:
            competitions.append({
                "meet": item["meet"],
                "file": item["file"],
                "count": 0,
                "results": [],
            })
    return {
        "count_competitions": len(competitions),
        "count_results": total_results,
        "index": index,
        "competitions": competitions,
    }


if __name__ == "__main__":
    run_one_shot_full_download()
