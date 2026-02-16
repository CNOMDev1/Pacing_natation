"""
Service Omega: logique de récupération des données et PDFs depuis omegatiming.com.
Inclut la mise à jour des cookies .
"""
import asyncio, os, sys, time
import requests
from pathlib import Path
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Racine du projet (Pacing/) pour le fichier cookies
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_COOKIES_FILE = _PROJECT_ROOT / "cookies_omegatiming.txt"

# Dossier de data Omega 
_DATA_BASE_OMEGA = Path(__file__).resolve().parent.parent / "data" / "omega"

BASE_URL = "https://www.omegatiming.com"
START_YEAR = 2000
END_YEAR = 2026
REVERSE_ORDER = False
TEST_PDF_URL = ""
DELAY_BETWEEN_YEARS = 2
TIMEOUT_OLD_YEARS = 15
DIRECT_COMPETITION_URLS = {
    2000: [
        "https://www.omegatiming.com/2000/0001000E00-live-results",
    ],
}

# URL utilisée pour récupérer les cookies 
COOKIE_FETCH_URL = "https://www.omegatiming.com/2025/2025-tyr-pro-swim-series-03-live-results"


async def _fetch_cookies_async(cookies_file: Path | None = None, url: str = COOKIE_FETCH_URL, headless: bool = False) -> bool:
    """
    Met à jour le fichier cookies_omegatiming.txt
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
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or None
    except FileNotFoundError:
        return None


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

session = requests.Session()
session.headers.update(HEADERS)


def update_cookies(cookies_file: Path | None = None, url: str = COOKIE_FETCH_URL, headless: bool = False) -> bool:
    """Met à jour les cookies et recharge la session."""
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
        session.headers["Cookie"] = new_cookie_header
        HEADERS["Cookie"] = new_cookie_header
        print("Cookies mis à jour dans la session", flush=True)
        return True
    else:
        print("Aucun cookie trouvé dans le fichier après la mise à jour", flush=True)
        return False


MAX_RETRIES = 3
DELAY_BETWEEN_RETRIES = 5
TIMEOUT_INDEX = 60
TIMEOUT_PDF = 40

def check_url_exists(url, timeout=5):
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code
    except Exception:
        return None


def fetch_with_retries(url, description, timeout, skip_quick_check=False):
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
                session.headers["Referer"] = "https://www.omegatiming.com/"
                print("  Configuration spéciale pour l'année 2000...", flush=True)

            resp = session.get(url, timeout=timeout, allow_redirects=True)

            print(f"Code de statut HTTP: {resp.status_code} {resp.reason}", flush=True)
            print(f"  Taille de la réponse: {len(resp.content)} octets", flush=True)
            if resp.headers.get("Content-Type"):
                print(f"  Content-Type: {resp.headers.get('Content-Type')}", flush=True)

            if resp.status_code == 404:
                print(f"Page non trouvée (404) pour {url}", flush=True)
                return None
            elif resp.status_code == 429:
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
    if "/2000/" in base_url:
        path = base_url.split("/2000/")[-1]
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
            session.headers["Referer"] = "https://www.omegatiming.com/"
            resp = session.head(alt_url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                print(f"  URL alternative fonctionne: {alt_url}", flush=True)
                return session.get(alt_url, timeout=TIMEOUT_INDEX)
            elif resp.status_code == 404:
                print("  URL alternative retourne 404", flush=True)
            else:
                print(f"  URL alternative retourne {resp.status_code}", flush=True)
        except Exception as e:
            print(f"  Erreur avec URL alternative: {type(e).__name__}", flush=True)

    return None


def download_total_ranking_pdfs_for_meet(meet_url: str, pdf_dir: str) -> None:
    print(f"\nRécupération de la page de la compétition : {meet_url}", flush=True)
    year = None
    if "/2000/" in meet_url:
        year = 2000
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
    total_ranking_links = []

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
    """Scan app/data/omega/pdfs/ et retourne la liste des PDFs (year, name, path)."""
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
    """
    Scrape le site Omega (omegatiming.com) pour toutes les années 
    Retourne count, message et liste des PDFs (year, name, path).
    """
    run_download_between_years(START_YEAR, END_YEAR)
    pdfs = _scan_pdfs_from_disk()
    n = len(pdfs)
    return {"count": n, "message": f"{n} PDF(s) trouvé(s)." if n else "Aucun PDF.", "pdfs": pdfs}


def get_pdf_paths_between_years(start_year: int, end_year: int):
    """
    Retourne les PDFs dont le dossier (année) est entre start_year et end_year (inclus).
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
    """
    Traite la requête "PDFs par années" : lance le téléchargement, puis retourne
    la liste des PDFs et le dict de réponse (pour GET /omega/pdfs/by-years).
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


def run_download_between_years(start_year: int, end_year: int) -> None:
    """
    Lance le téléchargement des PDFs Omega pour les années [start_year, end_year] (inclus).
    """
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    base_pdf_dir = _DATA_BASE_OMEGA / "pdfs"
    base_pdf_dir.mkdir(parents=True, exist_ok=True)
    base_pdf_dir = str(base_pdf_dir)

    years = list(range(start_year, end_year + 1))
    if REVERSE_ORDER:
        years = list(reversed(years))

    for year in years:
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
                    continue
            else:
                print(f"Impossible de récupérer la page index pour l'année {year}", flush=True)
                continue
        else:
            soup = BeautifulSoup(resp.text, "html.parser")
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
        if year < end_year:
            print(f"\nPause de {DELAY_BETWEEN_YEARS} secondes avant l'année suivante...\n", flush=True)
            time.sleep(DELAY_BETWEEN_YEARS)


def main():
    base_pdf_dir = _DATA_BASE_OMEGA / "pdfs"
    base_pdf_dir.mkdir(parents=True, exist_ok=True)
    base_pdf_dir = str(base_pdf_dir)

    if TEST_PDF_URL:
        print("Mode test: téléchargement direct d'un seul PDF.", flush=True)
        r = fetch_with_retries(TEST_PDF_URL, "Test téléchargement PDF direct", timeout=TIMEOUT_PDF)
        if r is None:
            return
        filename = os.path.join(base_pdf_dir, TEST_PDF_URL.split("/")[-1])
        try:
            with open(filename, "wb") as f:
                f.write(r.content)
            print(f"Téléchargé : {filename}", flush=True)
        except Exception as e:
            print(f"Erreur lors de l'écriture du fichier: {e}", flush=True)
        return

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
