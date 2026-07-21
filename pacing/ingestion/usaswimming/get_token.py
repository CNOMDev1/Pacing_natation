"""Récupération du token Bearer pour l'API USA Swimming Data Hub.

Ce script utilise Playwright pour ouvrir le dashboard Data Hub, intercepter
l'en-tête ``Authorization: Bearer …`` des requêtes XHR et le sauvegarder dans
``services/bearer_token.txt`` (consommé par ``usaswimming_service.py``).

Le flux :
1. **Première exécution** — connexion manuelle dans Chromium, sauvegarde de
   ``services/state.json`` (cookies / session).
2. **Exécutions suivantes** — rechargement headless avec ``state.json``,
   écoute réseau et écriture du token.
3. **Fallback** — si la capture headless échoue, nouvelle tentative en mode
   visible pour le débogage.
"""
from playwright.sync_api import sync_playwright
import time, os, sys

# --- Chemins de sortie (secrets sous services/) ---

from pacing.config.paths import BEARER_TOKEN_PATH, USASWIMMING_STATE_PATH

STATE_FILE = str(USASWIMMING_STATE_PATH)
TOKEN_OUT = str(BEARER_TOKEN_PATH)

DATA_HUB_URL = "https://data.usaswimming.org"
WAIT_FOR = 20  # secondes d'attente pour que le dashboard fasse ses requêtes API


def _capture_token_on_page(page, wait_seconds=WAIT_FOR, extra_wait=10):
    """Attache un listener réseau, recharge la page et capture le Bearer token.

    Args:
        page: Page Playwright déjà authentifiée.
        wait_seconds (int): Délai initial après reload.
        extra_wait (int): Délai supplémentaire si aucun token intercepté.

    Returns:
        str | None: En-tête complet ``Bearer …`` ou None.
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


def run_headed_save_state_and_capture_token(user_data_dir=None):
    """Ouvre un navigateur visible pour connexion manuelle puis capture le token.

    Mode interactif : l'utilisateur se connecte, appuie sur Entrée, le script
    sauvegarde ``state.json`` et intercepte le Bearer dans la même session.

    Args:
        user_data_dir (str | None): Profil Chromium persistant. Par défaut
            ``playwright_tmp_profile``.

    Returns:
        None
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


def capture_token_with_storage_state(headless=True):
    """Capture le token en réutilisant un ``state.json`` existant.

    Lance Chromium avec la session sauvegardée, écoute les requêtes réseau et
    écrit le Bearer dans ``bearer_token.txt``.

    Args:
        headless (bool): Si True, navigateur invisible.

    Returns:
        None

    Raises:
        FileNotFoundError: Si ``state.json`` est absent.
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
    """Point d'entrée CLI : capture ou renouvelle le Bearer token USA Swimming.

    Si ``state.json`` est absent, lance le mode interactif. Sinon, tente la
    capture headless avec fallback visible en cas d'erreur.

    Returns:
        None
    """
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
