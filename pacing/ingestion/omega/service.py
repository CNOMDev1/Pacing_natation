"""Scraping Omega Timing : index des compétitions et PDF « Total Ranking ».

Ce module parcourt le site omegatiming.com année par année, identifie les
compétitions natation et télécharge les PDF « Total Ranking » associés.
Les fichiers sont stockés sous ``data/raw/omega/pdfs/{année}/``.

Le flux de données :
1. **Authentification** — les requêtes HTTP utilisent des cookies Chromium
   sérialisés dans ``cookies_omegatiming.txt`` à la racine du projet.
   Ils sont rafraîchis via Playwright si expirés ou en cas de timeouts répétés.
2. **Index annuel** — pour chaque année, récupération de la page
   ``/sports-timing-live-results/{year}`` et extraction des liens « Swimming ».
3. **Page compétition** — parsing HTML pour trouver les liens PDF « Total Ranking »
   (trois stratégies de sélecteurs CSS selon la structure de la page).
4. **Téléchargement** — écriture des PDF dans le dossier annuel correspondant.

Les années anciennes (< 2010) et 2000 ont des traitements spécifiques
(timeouts courts, variantes d'URL, URLs de compétition directes).
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- Chemins et configuration locale ---

from pacing.config.paths import OMEGA_RAW_DIR, PROJECT_DIR

_PROJECT_ROOT = PROJECT_DIR
_COOKIES_FILE = _PROJECT_ROOT / "cookies_omegatiming.txt"

# Dossier de sortie des PDF Omega (data/raw/omega/pdfs/{année}/)
_DATA_BASE_OMEGA = OMEGA_RAW_DIR

# --- Paramètres de scraping ---

BASE_URL = "https://www.omegatiming.com"
START_YEAR = 2000  # borne inférieure par défaut (CLI et API)
END_YEAR = 2026  # borne supérieure par défaut
REVERSE_ORDER = False  # si True, traite les années de la plus récente à la plus ancienne
DELAY_BETWEEN_YEARS = 2  # pause (s) entre deux compétitions d'une même année
TIMEOUT_OLD_YEARS = 15  # timeout réduit pour les index < 2010 (souvent absents)
# URLs de secours quand la page index annuelle n'est pas accessible
DIRECT_COMPETITION_URLS = {
    2000: [
        "https://www.omegatiming.com/2000/0001000E00-live-results",
    ],
}

# Page récente utilisée par Playwright pour obtenir des cookies valides
COOKIE_FETCH_URL = "https://www.omegatiming.com/2025/2025-tyr-pro-swim-series-03-live-results"


async def _fetch_cookies_async(cookies_file: Path | None = None, url: str = COOKIE_FETCH_URL, headless: bool = False) -> bool:
    """Ouvre une page Omega via Playwright et sérialise les cookies Chromium.

    Les cookies du domaine ``omegatiming.com`` sont concaténés en en-tête
    ``Cookie`` et écrits dans le fichier texte configuré.

    Args:
        cookies_file (Path | None): Chemin de sortie. Par défaut ``_COOKIES_FILE``.
        url (str): Page Omega à charger pour déclencher la pose des cookies.
        headless (bool): Lance Chromium sans interface graphique si True.

    Returns:
        bool: True si l'écriture du fichier a réussi.

    Raises:
        Aucune exception propagée ; les erreurs Playwright remontent à l'appelant.
    """
    path = cookies_file or _COOKIES_FILE
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        if sys.stdout and sys.stdout.isatty():
            print(f"Ouverture de la page {url}", flush=True)
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        cookies = await context.cookies()
        omegatiming_cookies = [
            c for c in cookies if "omegatiming.com" in c.get("domain", "")
        ]
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in omegatiming_cookies)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cookie_header, encoding="utf-8")

        if sys.stdout and sys.stdout.isatty():
            print("Cookies enregistrés dans", path, flush=True)
        await browser.close()
    return True


def load_cookie_header_from_file(path: str | Path) -> str | None:
    """Lit l'en-tête Cookie sérialisé depuis le fichier texte.

    Args:
        path (str | Path): Chemin vers ``cookies_omegatiming.txt``.

    Returns:
        str | None: Contenu du fichier (sans espaces de bord), ou None si absent/vide.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or None
    except FileNotFoundError:
        return None


# En-têtes HTTP mimant un navigateur Chrome ; Cookie injecté ci-dessous si disponible
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "DNT": "1",
}

cookie_header = load_cookie_header_from_file(_COOKIES_FILE)
if cookie_header:
    HEADERS["Cookie"] = cookie_header

# Session partagée entre threads ; SESSION_LOCK protège les accès concurrents
session = requests.Session()
session.headers.update(HEADERS)
SESSION_LOCK = threading.Lock()


def update_cookies(cookies_file: Path | None = None, url: str = COOKIE_FETCH_URL, headless: bool = False) -> bool:
    """Rafraîchit les cookies via Playwright et recharge la session HTTP.

    Appelé automatiquement après des timeouts répétés dans ``fetch_with_retries``.

    Args:
        cookies_file (Path | None): Fichier cookies cible. Par défaut ``_COOKIES_FILE``.
        url (str): Page utilisée pour la collecte Playwright.
        headless (bool): Mode headless pour Chromium.

    Returns:
        bool: True si de nouveaux cookies ont été chargés dans ``session``.
    """
    print(f"\n{'*'*60}", flush=True)
    print("Mise à jour des cookies...", flush=True)
    print(f"{'*'*60}", flush=True)

    try:
        asyncio.run(
            _fetch_cookies_async(
                cookies_file=cookies_file or _COOKIES_FILE,
                url=url,
                headless=headless,
            )
        )
    except Exception as e:
        print(f"Erreur lors de la mise à jour des cookies: {e}", flush=True)
        return False

    new_cookie_header = load_cookie_header_from_file(_COOKIES_FILE)
    if new_cookie_header:
        with SESSION_LOCK:
            session.headers["Cookie"] = new_cookie_header
            HEADERS["Cookie"] = new_cookie_header
        print("Cookies mis à jour dans la session", flush=True)
        return True
    else:
        print("Aucun cookie trouvé dans le fichier après la mise à jour", flush=True)
        return False


# --- Paramètres HTTP (retries, timeouts) ---

MAX_RETRIES = 3
DELAY_BETWEEN_RETRIES = 5  # pause (s) entre deux tentatives GET
TIMEOUT_INDEX = 60  # pages index / compétition (années récentes)
TIMEOUT_PDF = 40  # téléchargement d'un fichier PDF


def check_url_exists(url: str, timeout: int = 5) -> int | None:
    """Vérifie rapidement si une URL Omega répond (requête HEAD).

    Utilisé avant le GET complet pour les années < 2010 afin d'éviter
    d'attendre un timeout long sur des pages inexistantes.

    Args:
        url (str): URL à tester.
        timeout (int): Délai maximum en secondes.

    Returns:
        int | None: Code HTTP (ex. 200, 404) ou None en cas d'erreur réseau.
    """
    try:
        with SESSION_LOCK:
            resp = session.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code
    except Exception:
        return None


def fetch_with_retries(
    url: str,
    description: str,
    timeout: int,
    skip_quick_check: bool = False,
) -> requests.Response | None:
    """Effectue un GET avec retries, gestion du 429 et rafraîchissement des cookies.

    En cas de timeouts répétés, tente une mise à jour des cookies avant le
    dernier essai. Pour l'année 2000, ajoute un en-tête ``Referer`` spécifique.

    Args:
        url (str): URL cible.
        description (str): Libellé affiché dans les logs.
        timeout (int): Délai maximum par tentative (secondes).
        skip_quick_check (bool): Si True, ignore le HEAD préalable pour les vieilles années.

    Returns:
        requests.Response | None: Réponse HTTP 200, ou None si échec définitif.
    """
    # Pré-vérification HEAD pour les index annuels anciens (souvent 404 ou timeout)
    if not skip_quick_check and "/sports-timing-live-results/" in url:
        year_match = url.split("/sports-timing-live-results/")[-1].split("/")[0]
        try:
            year = int(year_match)
            if year < 2010:
                print("Vérification rapide de l'existence de la page...", flush=True)
                status = check_url_exists(url, timeout=5)
                if status is None:
                    print("La page semble inexistante ou inaccessible (timeout rapide)", flush=True)
                    print(f"  Année {year} probablement non disponible sur le site", flush=True)
                    return None
                elif status == 404:
                    print(f"Page non trouvée (404) - Année {year} non disponible", flush=True)
                    return None
                elif status != 200:
                    print(f"Statut HTTP {status} - La page existe mais avec un statut inattendu", flush=True)
        except ValueError:
            pass

    timeout_count = 0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"{description} (essai {attempt}/{MAX_RETRIES})...", flush=True)
            print(f"URL: {url}", flush=True)
            if "/2000/" in url:
                with SESSION_LOCK:
                    session.headers["Referer"] = "https://www.omegatiming.com/"
                print("  Configuration spéciale pour l'année 2000...", flush=True)

            with SESSION_LOCK:
                resp = session.get(url, timeout=timeout, allow_redirects=True)

            print(f"Code de statut HTTP: {resp.status_code} {resp.reason}", flush=True)
            print(f"  Taille de la réponse: {len(resp.content)} octets", flush=True)
            if resp.headers.get("Content-Type"):
                print(f"  Content-Type: {resp.headers.get('Content-Type')}", flush=True)

            if resp.status_code == 404:
                print(f"Page non trouvée (404) pour {url}", flush=True)
                return None
            elif resp.status_code == 429:
                # Respect du Retry-After serveur, sinon backoff progressif
                print("Rate limiting détecté (429 Too Many Requests)", flush=True)
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_time = int(retry_after)
                        print(f"  Le serveur demande d'attendre {wait_time} secondes (Retry-After)", flush=True)
                    except ValueError:
                        wait_time = DELAY_BETWEEN_RETRIES * (attempt + 1)
                else:
                    wait_time = DELAY_BETWEEN_RETRIES * (attempt + 1) * 2
                    print(f"  Pas de Retry-After, attente progressive de {wait_time} secondes", flush=True)
                if attempt < MAX_RETRIES:
                    print(f"  Attente de {wait_time} secondes avant nouvel essai...", flush=True)
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"Échec après {MAX_RETRIES} essais - Rate limiting persistant", flush=True)
                    return None
            elif resp.status_code != 200:
                print(f"Statut HTTP inattendu: {resp.status_code} {resp.reason}", flush=True)
                if attempt < MAX_RETRIES:
                    print(f"Attente de {DELAY_BETWEEN_RETRIES} secondes avant nouvel essai...", flush=True)
                    time.sleep(DELAY_BETWEEN_RETRIES)
                    continue
                return None

            print("Requête réussie (200 OK)", flush=True)
            return resp
        except requests.exceptions.Timeout:
            timeout_count += 1
            print(f"Timeout - Code de statut: N/A (le serveur ne répond pas dans les {timeout}s)", flush=True)
            print(f"  URL: {url}", flush=True)
            # Au 2e timeout, on tente de rafraîchir les cookies avant le dernier essai
            if attempt == 2 and attempt < MAX_RETRIES:
                print("  Mise à jour des cookies avant le dernier essai...", flush=True)
                if update_cookies():
                    print("  Cookies mis à jour, nouvel essai avec les nouveaux cookies...", flush=True)
                else:
                    print("  Échec de la mise à jour des cookies, continuation avec les cookies existants...", flush=True)
        except requests.exceptions.ConnectionError as e:
            print("Erreur de connexion - Code de statut: N/A", flush=True)
            print(f"  Détails: {e}", flush=True)
            print(f"  URL: {url}", flush=True)
        except requests.exceptions.HTTPError as e:
            print(f"Erreur HTTP - Code de statut: {e.response.status_code if hasattr(e, 'response') and e.response else 'N/A'}", flush=True)
            print(f"  Détails: {e}", flush=True)
            print(f"  URL: {url}", flush=True)
        except Exception as e:
            print("Erreur inattendue - Code de statut: N/A", flush=True)
            print(f"  Type: {type(e).__name__}", flush=True)
            print(f"  Détails: {e}", flush=True)
            print(f"  URL: {url}", flush=True)
            break

        if attempt < MAX_RETRIES:
            print(f"Attente de {DELAY_BETWEEN_RETRIES} secondes avant nouvel essai...", flush=True)
            time.sleep(DELAY_BETWEEN_RETRIES)

    if timeout_count >= MAX_RETRIES:
        print("\nTous les essais ont échoué avec des timeouts. Mise à jour des cookies et dernier essai...", flush=True)
        if update_cookies():
            print("Dernier essai avec les cookies mis à jour...", flush=True)
            try:
                with SESSION_LOCK:
                    resp = session.get(url, timeout=timeout, allow_redirects=True)
                if resp.status_code == 200:
                    print("Requête réussie après mise à jour des cookies (200 OK)", flush=True)
                    return resp
                else:
                    print(f"Code de statut HTTP: {resp.status_code} {resp.reason}", flush=True)
            except Exception as e:
                print(f"Échec du dernier essai: {type(e).__name__} - {e}", flush=True)

    print(f"Échec après {MAX_RETRIES} essais pour {description}", flush=True)
    print("  Code de statut final: N/A (aucune réponse du serveur)", flush=True)
    return None


def try_alternative_urls(base_url: str) -> requests.Response | None:
    """Essaie des variantes d'URL pour les archives Omega de l'année 2000.

    Args:
        base_url (str): URL de départ de la page compétition.

    Returns:
        requests.Response | None: Réponse HTTP 200 si une variante fonctionne, sinon None.
    """
    if "/2000/" in base_url:
        path = base_url.split("/2000/")[-1]
        # Plusieurs schémas d'URL coexistent pour les archives 2000
        alternatives = [
            f"https://www.omegatiming.com/2000/{path}",
            f"https://www.omegatiming.com/2000/{path}/",
            f"https://www.omegatiming.com/sports-timing-live-results/2000/{path}",
            base_url,
        ]
    else:
        alternatives = [base_url]

    for alt_url in alternatives:
        print(f"  Essai avec l'URL alternative: {alt_url}", flush=True)
        try:
            with SESSION_LOCK:
                session.headers["Referer"] = "https://www.omegatiming.com/"
                resp = session.head(alt_url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                print(f"  URL alternative fonctionne: {alt_url}", flush=True)
                with SESSION_LOCK:
                    return session.get(alt_url, timeout=TIMEOUT_INDEX)
            elif resp.status_code == 404:
                print("  URL alternative retourne 404", flush=True)
            else:
                print(f"  URL alternative retourne {resp.status_code}", flush=True)
        except Exception as e:
            print(f"  Erreur avec URL alternative: {type(e).__name__}", flush=True)

    return None


def download_total_ranking_pdfs_for_meet(meet_url: str, pdf_dir: str) -> None:
    """Télécharge les PDF « Total Ranking » listés sur la page d'une compétition.

    Parse le HTML de la page meet, extrait les liens PDF pertinents puis les
    enregistre dans ``pdf_dir``. Pour l'année 2000, essaie des URLs alternatives
    si la page principale échoue.

    Args:
        meet_url (str): URL absolue de la page compétition Omega.
        pdf_dir (str): Dossier de destination (ex. ``data/raw/omega/pdfs/2024``).

    Returns:
        None
    """
    print(f"\nRécupération de la page de la compétition : {meet_url}", flush=True)
    year = None
    if "/2000/" in meet_url:
        year = 2000
        # Archives 2000 : serveur lent, timeout allongé et Referer obligatoire
        print(" Année 2000 détectée - utilisation d'un timeout étendu (120s)", flush=True)
        timeout_to_use = 120
        session.headers["Referer"] = "https://www.omegatiming.com/"
        if cookie_header:
            print("  Utilisation des cookies configurés", flush=True)
    else:
        timeout_to_use = TIMEOUT_INDEX

    resp = fetch_with_retries(meet_url, "Récupération de la page de la compétition", timeout=timeout_to_use, skip_quick_check=True)

    if resp is None and year == 2000:
        print("\n Tentative avec des variantes d'URL...", flush=True)
        resp = try_alternative_urls(meet_url)

    if resp is None:
        if year == 2000:
            print("\n Impossible d'accéder à la page de compétition de 2000.", flush=True)
            print("   Diagnostic:", flush=True)
            print("   - Les archives de 2000 ne semblent plus être disponibles", flush=True)
            print("   - L'URL pourrait avoir changé ou être incorrecte", flush=True)
            print("   - Le serveur ne répond pas (timeout)", flush=True)
            print("   - Vérifiez manuellement l'URL dans un navigateur:", flush=True)
            print(f"     {meet_url}", flush=True)
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    # Trois stratégies de parsing : le markup Omega varie selon l'âge de la page
    total_ranking_links = []

    # 1) Liens dans des paragraphes p.three (structure récente)
    for p in soup.select("p.three"):
        a = p.find("a")
        if a:
            link_text = a.get_text(strip=True).upper()
            if "TOTAL RANKING" in link_text:
                href = a.get("href")
                if href and href.endswith(".pdf"):
                    pdf_url = urljoin(BASE_URL, href)
                    total_ranking_links.append(pdf_url)
                    print(f"  Trouvé PDF 'Total Ranking' (p.three) : {pdf_url}", flush=True)

    # 2) Liens dans des cellules div.cell avec libellé dans un span
    if not total_ranking_links:
        for a in soup.select("div.cell a[href$='.pdf']"):
            span = a.find("span")
            if span:
                span_text = span.get_text(strip=True).upper()
                if "TOTAL RANKING" in span_text:
                    href = a.get("href")
                    if href:
                        pdf_url = urljoin(BASE_URL, href)
                        total_ranking_links.append(pdf_url)
                        print(f"   Trouvé PDF 'Total Ranking' (div.cell) : {pdf_url}", flush=True)

    # 3) Recherche générale sur tous les liens <a> (fallback)
    if not total_ranking_links:
        for a in soup.find_all("a", href=True):
            link_text = a.get_text(strip=True).upper()
            href = a.get("href", "")
            if "TOTAL RANKING" in link_text and href.endswith(".pdf"):
                pdf_url = urljoin(BASE_URL, href)
                if pdf_url not in total_ranking_links:
                    total_ranking_links.append(pdf_url)
                    print(f"  Trouvé PDF 'Total Ranking' (recherche générale) : {pdf_url}", flush=True)

    if not total_ranking_links:
        print('Aucun lien PDF avec le texte "Total Ranking" trouvé pour cette compétition.', flush=True)
        print("   Vérification de la structure de la page...", flush=True)
        all_pdf_links = soup.find_all("a", href=True)
        pdf_count = sum(1 for a in all_pdf_links if a.get("href", "").endswith(".pdf"))
        print(f"   Nombre total de liens PDF trouvés sur la page: {pdf_count}", flush=True)
        return

    print(f"\nNombre de PDFs 'Total Ranking' à télécharger : {len(total_ranking_links)}", flush=True)

    for idx, pdf_url in enumerate(total_ranking_links, 1):
        print(f"\n[{idx}/{len(total_ranking_links)}] Téléchargement du PDF 'Total Ranking' : {pdf_url}", flush=True)
        with SESSION_LOCK:
            session.headers["Referer"] = meet_url
        r = fetch_with_retries(pdf_url, f'Téléchargement du PDF "Total Ranking" {idx}/{len(total_ranking_links)}', timeout=TIMEOUT_PDF)
        if r is None:
            print("  Échec du téléchargement pour ce PDF, passage au suivant...", flush=True)
            continue
        filename = os.path.join(pdf_dir, pdf_url.split("/")[-1])
        try:
            with open(filename, "wb") as f:
                f.write(r.content)
            print(f"  Téléchargé : {filename}", flush=True)
        except Exception as e:
            print(f"  Erreur lors de l'écriture du fichier: {e}", flush=True)
        time.sleep(1)


def _scan_pdfs_from_disk():
    """Scanne ``data/raw/omega/pdfs/`` et retourne la liste des PDFs locaux.

    Parcourt chaque sous-dossier annuel et collecte les fichiers ``*.pdf``.

    Returns:
        list[dict]: Dictionnaires ``{"year", "name", "path"}`` triés par année.
    """
    base = _DATA_BASE_OMEGA / "pdfs"
    if not base.exists() or not base.is_dir():
        return []
    out = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        for f in sorted(year_dir.glob("*.pdf")):
            out.append({"year": year_dir.name, "name": f.name, "path": str(f)})
    return out


def get_all_pdfs_response() -> dict:
    """Lance le téléchargement complet puis retourne l'inventaire des PDFs locaux.

    Point d'entrée API : télécharge toutes les années ``START_YEAR`` → ``END_YEAR``,
    puis scanne le disque.

    Returns:
        dict: ``{"count", "message", "pdfs"}`` avec la liste des fichiers trouvés.
    """
    run_download_between_years(START_YEAR, END_YEAR)
    pdfs = _scan_pdfs_from_disk()
    n = len(pdfs)
    return {"count": n, "message": f"{n} PDF(s) trouvé(s)." if n else "Aucun PDF.", "pdfs": pdfs}


def get_pdf_paths_between_years(start_year: int, end_year: int):
    """Liste les PDFs locaux dont le dossier annuel est dans la plage demandée.

    Ne déclenche aucun téléchargement ; lecture disque uniquement.

    Args:
        start_year (int): Borne inférieure (inclusive).
        end_year (int): Borne supérieure (inclusive).

    Returns:
        list[dict]: Dictionnaires ``{"year", "name", "path"}`` pour la plage filtrée.
    """
    base = _DATA_BASE_OMEGA / "pdfs"
    if not base.exists() or not base.is_dir():
        return []
    out = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        try:
            y = int(year_dir.name)
        except ValueError:
            continue
        if start_year <= y <= end_year:
            for f in sorted(year_dir.glob("*.pdf")):
                out.append({"year": year_dir.name, "name": f.name, "path": str(f)})
    return out


def get_pdfs_by_years_response(start_year: int, end_year: int, execute: bool = False) -> dict:
    """Traite la requête « PDFs par années » pour l'endpoint API.

    Si ``execute`` est True, lance ``run_download_between_years`` avant de
    scanner le disque.

    Args:
        start_year (int): Première année de la plage.
        end_year (int): Dernière année de la plage.
        execute (bool): Si True, télécharge les PDFs avant de lister.

    Returns:
        dict: ``{"start_year", "end_year", "count", "message", "pdfs"}``.
    """
    if execute:
        run_download_between_years(start_year, end_year)
    pdfs = get_pdf_paths_between_years(start_year, end_year)
    n = len(pdfs)
    return {
        "start_year": start_year,
        "end_year": end_year,
        "count": n,
        "message": f"{n} PDF(s) entre {start_year} et {end_year}.",
        "pdfs": pdfs,
    }


def _process_year(year: int, base_pdf_dir: str) -> None:
    """Traite le téléchargement pour une année donnée (exécuté par un thread).

    Récupère la page index annuelle, extrait les liens compétitions natation,
    puis appelle ``download_total_ranking_pdfs_for_meet`` pour chacun.
    Pour les années < 2010 sans index, utilise ``DIRECT_COMPETITION_URLS``.

    Args:
        year (int): Année à traiter.
        base_pdf_dir (str): Racine ``data/raw/omega/pdfs`` (sous-dossier créé par année).

    Returns:
        None
    """
    print(f"\n{'*'*60}", flush=True)
    print(f"TRAITEMENT DE L'ANNÉE {year}", flush=True)
    print(f"{'*'*60}\n", flush=True)

    index_url = f"https://www.omegatiming.com/sports-timing-live-results/{year}"
    pdf_dir = os.path.join(base_pdf_dir, str(year))
    os.makedirs(pdf_dir, exist_ok=True)

    print(f"Récupération de la page index: {index_url}", flush=True)
    timeout_to_use = TIMEOUT_OLD_YEARS if year < 2010 else TIMEOUT_INDEX
    resp = fetch_with_retries(index_url, f"Récupération de la page index {year}", timeout=timeout_to_use)

    meet_links = []
    if resp is None:
        if year < 2010:
            print(f"Année {year} : La page index n'est pas accessible.", flush=True)
            if year in DIRECT_COMPETITION_URLS and DIRECT_COMPETITION_URLS[year]:
                meet_links = DIRECT_COMPETITION_URLS[year]
            else:
                return
        else:
            print(f"Impossible de récupérer la page index pour l'année {year}", flush=True)
            return
    else:
        soup = BeautifulSoup(resp.text, "html.parser")
        # Chaque div.row représente une compétition ; on ne garde que la natation
        for row in soup.select("div.row"):
            sport_p = row.select_one("p.sport.swimming")
            if not sport_p:
                continue
            detail_link = row.select_one("h3.detail a[href]")
            if not detail_link:
                continue
            href = detail_link["href"]
            meet_url = urljoin(BASE_URL, href)
            meet_links.append(meet_url)

    print(f"Nombre de compétitions 'Swimming' trouvées pour {year} : {len(meet_links)}", flush=True)
    for meet_url in meet_links:
        print(f"\n=== Compétition {year} : {meet_url} ===", flush=True)
        download_total_ranking_pdfs_for_meet(meet_url, pdf_dir)
        time.sleep(2)


def run_download_between_years(start_year: int, end_year: int) -> None:
    """Lance le téléchargement des PDFs Omega sur une plage d'années.

    Les années sont traitées en parallèle via ``ThreadPoolExecutor`` (jusqu'à
    27 workers). L'ordre peut être inversé si ``REVERSE_ORDER`` est True.

    Args:
        start_year (int): Borne inférieure (inclusive) ; échangée si > end_year.
        end_year (int): Borne supérieure (inclusive).

    Returns:
        None
    """
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    base_pdf_dir = _DATA_BASE_OMEGA / "pdfs"
    base_pdf_dir.mkdir(parents=True, exist_ok=True)
    base_pdf_dir = str(base_pdf_dir)

    years = list(range(start_year, end_year + 1))
    if REVERSE_ORDER:
        years = list(reversed(years))

    # Un thread par année, plafonné à 27 pour limiter la charge sur le serveur Omega
    max_workers = min(27, len(years))
    if max_workers <= 0:
        return

    print(f"\nLancement du téléchargement en parallèle pour les années {years}", flush=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_year, year, base_pdf_dir): year for year in years}
        for future in as_completed(futures):
            year = futures[future]
            try:
                future.result()
                print(f"\n=== Année {year} terminée ===", flush=True)
            except Exception as e:
                print(f"\nErreur lors du traitement de l'année {year}: {type(e).__name__} - {e}", flush=True)


def main():
    """Point d'entrée CLI : télécharge les PDF Total Ranking sur une plage d'années.

    Usage : ``python -m services.omega_service [start_year end_year]``.
    Sans arguments, utilise ``START_YEAR`` et ``END_YEAR``.

    Returns:
        None
    """
    base_pdf_dir = _DATA_BASE_OMEGA / "pdfs"
    base_pdf_dir.mkdir(parents=True, exist_ok=True)
    base_pdf_dir = str(base_pdf_dir)
    start_year = START_YEAR
    end_year = END_YEAR
    if len(sys.argv) >= 3:
        try:
            start_year = int(sys.argv[1])
            end_year = int(sys.argv[2])
            print(f"Plage d'années : {start_year} → {end_year}", flush=True)
        except ValueError:
            print("Arguments ignorés (attendu : start_year end_year). Utilisation de START_YEAR/END_YEAR.", flush=True)

    run_download_between_years(start_year, end_year)


if __name__ == "__main__":
    main()
