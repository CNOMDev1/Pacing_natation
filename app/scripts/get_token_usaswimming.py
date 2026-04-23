# get_token_usaswimming.py — Récupération du token Bearer pour l'API USA Swimming Data Hub
from playwright.sync_api import sync_playwright
import time, os, sys

# Fichiers token/state dans services/ (utilisés par usaswimming_service.py)
_SCRIPT_DIR = os.path.dirname(__file__)
_SERVICES_DIR = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "services"))
STATE_FILE = os.path.join(_SERVICES_DIR, "state.json")
TOKEN_OUT = os.path.join(_SERVICES_DIR, "bearer_token.txt")

DATA_HUB_URL = "https://data.usaswimming.org"
WAIT_FOR = 20  # secondes d'attente pour que le dashboard fasse ses requêtes

def _capture_token_on_page(page, wait_seconds=WAIT_FOR, extra_wait=10):
    """
    Attache un listener sur la page pour capturer le Bearer token, recharge la page
    pour déclencher les requêtes API, attend et retourne le token (ou None).
    """
    found = {"token": None}

    def on_request(request):
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            found["token"] = auth

    page.on("request", on_request)
    page.reload(wait_until="networkidle")
    print(f"Attente {wait_seconds}s pour laisser le dashboard envoyer les requêtes...")
    time.sleep(wait_seconds)
    if not found["token"]:
        print(f"Token non trouvé, attente supplémentaire de {extra_wait}s...")
        time.sleep(extra_wait)
    return found["token"]


# Une seule exécution : connexion manuelle, sauvegarde du state puis capture du token
def run_headed_save_state_and_capture_token(user_data_dir=None):
    """
    Ouvre un navigateur pour te connecter manuellement, sauvegarde le state,
    puis capture le token dans la même session (sans relancer le script).
    """
    print("Mode interactif : ouverture du navigateur pour te connecter...")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir or "playwright_tmp_profile",
            headless=False,
            channel="chrome",
            args=["--start-maximized"],
        )
        page = context.new_page()
        page.goto(DATA_HUB_URL)
        print(f"Connecte-toi sur {DATA_HUB_URL} puis appuie sur Entrée quand c'est fait...")
        input("Après connexion, appuie Entrée pour sauvegarder le state et capturer le token...")
        context.storage_state(path=STATE_FILE)
        print(f"[OK] State sauvegardé dans {STATE_FILE}")
        print("Capture du token en cours...")
        token = _capture_token_on_page(page)
        context.close()
        if token:
            with open(TOKEN_OUT, "w", encoding="utf-8") as f:
                f.write(token)
            print(f"[OK] Token sauvegardé dans {TOKEN_OUT}")
        else:
            print("Aucun token Bearer capturé — le dashboard n'a peut-être pas envoyé de requête API.")


# Capture du token en réutilisant un state.json existant
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
                with open(TOKEN_OUT, "w", encoding="utf-8") as f:
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
            print(f"[OK] Token sauvegardé dans {TOKEN_OUT}")

def main():
    if not os.path.exists(STATE_FILE):
        print(f"{STATE_FILE} non trouvé — une seule exécution : connexion puis sauvegarde state + token.")
        run_headed_save_state_and_capture_token(user_data_dir=None)
        return

    try:
        capture_token_with_storage_state(headless=True)
    except Exception as e:
        print("Erreur lors de la capture headless:", e)
        print("Tentative de fallback en mode non-headless pour debug...")
        capture_token_with_storage_state(headless=False)

if __name__ == "__main__":
    main()
