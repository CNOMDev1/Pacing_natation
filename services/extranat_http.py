"""Client HTTP Extranat (retries / backoff).

Extrait de ``extranat_service`` pour isoler la couche réseau.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

def http_get_with_retries(
    url: str,
    headers: Optional[dict[str, str]] = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
    debug: bool = False,
    session: Optional[requests.Session] = None,
    retry_forever: bool = False,
) -> requests.Response:
    """Effectue un GET avec backoff exponentiel sur erreurs réseau et HTTP.

    Réessaie automatiquement sur 403, 429 et 5xx. Le délai est plus agressif
    pour les 403 (protection anti-bot Extranat). Mode ``retry_forever`` pour
    les pages critiques où l'abandon n'est pas acceptable.

    Args:
        url (str): URL cible.
        headers (Optional[dict[str, str]]): En-têtes HTTP ; défaut navigateur Chrome.
        max_retries (int): Nombre maximal de tentatives si ``retry_forever=False``.
        base_delay (float): Délai de base (s) pour le backoff exponentiel.
        debug (bool): Affiche les tentatives et statuts HTTP.
        session (Optional[requests.Session]): Session réutilisable (cookies, keep-alive).
        retry_forever (bool): Si True, boucle indéfiniment jusqu'à succès.

    Returns:
        requests.Response: Réponse HTTP avec statut < 400.

    Raises:
        requests.HTTPError: Si le statut reste en erreur après épuisement des retries.
        RuntimeError: Si toutes les tentatives échouent sans réponse HTTP.
    """
    if headers is None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    last_exc: Optional[Exception] = None
    attempt = 0
    max_delay = 300.0

    while True:
        attempt += 1
        try:
            if session is not None:
                resp = session.get(url, headers=headers, timeout=20)
            else:
                resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code < 400:
                return resp

            if resp.status_code not in (403, 429) and not (500 <= resp.status_code < 600):
                if not retry_forever:
                    resp.raise_for_status()
                else:
                    if debug:
                        print(
                            f"[http_get_with_retries] {url} → statut {resp.status_code} "
                            f"(erreur permanente, mais retry_forever=True), tentative {attempt}"
                        )

            if debug:
                if retry_forever:
                    print(
                        f"[http_get_with_retries] {url} → statut {resp.status_code}, "
                        f"tentative {attempt} (retry forever...)"
                    )
                else:
                    print(
                        f"[http_get_with_retries] {url} → statut {resp.status_code}, "
                        f"tentative {attempt}/{max_retries}"
                    )

            last_exc = requests.HTTPError(
                f"Status {resp.status_code} for URL {url}", response=resp
            )

        except requests.RequestException as exc:
            last_exc = exc
            if debug:
                if retry_forever:
                    print(
                        f"[http_get_with_retries] Exception sur {url} : {exc} "
                        f"(tentative {attempt}, retry forever...)"
                    )
                else:
                    print(
                        f"[http_get_with_retries] Exception sur {url} : {exc} "
                        f"(tentative {attempt}/{max_retries})"
                    )

        if not retry_forever and attempt >= max_retries:
            break

        if isinstance(last_exc, requests.HTTPError) and getattr(last_exc, "response", None) is not None:
            # 403 Extranat : backoff plus long (souvent rate-limit / anti-bot)
            if last_exc.response.status_code == 403:
                delay = min(5.0 * (3 ** (attempt - 1)), max_delay)
            else:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
        else:
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)

        time.sleep(delay)

    if isinstance(last_exc, requests.HTTPError) and getattr(last_exc, "response", None) is not None:
        raise last_exc
    else:
        raise last_exc if last_exc is not None else RuntimeError(
            f"Echec de la requête GET vers {url} après {max_retries} tentatives"
        )


