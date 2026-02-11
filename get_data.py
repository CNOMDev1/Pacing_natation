import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import time
import re


# Effectue une requête GET HTTP avec relances automatiques 
def http_get_with_retries(url: str, headers: Optional[dict] = None, max_retries: int = 3, base_delay: float = 1.0, debug: bool = False, session: Optional[requests.Session] = None, retry_forever: bool = False):
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

# Récupère les données de compétition (résultats de natation) depuis l'URL fournie 
def get_competition_data(url: str, debug: bool = False, session: Optional[requests.Session] = None, retry_forever: bool = True) -> List[Dict]:
    response = http_get_with_retries(
        url,
        debug=debug,
        max_retries=5,
        session=session,
        retry_forever=retry_forever,
    )

    soup = BeautifulSoup(response.content, 'html.parser')

    table = None
    table_div = soup.find('div', class_='relative overflow-x-auto shadow-md sm:rounded-lg print-not-shadow')
    if table_div:
        table = table_div.find('table')

    if not table:
        table = soup.find('table', class_='w-full text-sm text-left text-gray-500')

    if not table:
        all_tables = soup.find_all('table')
        for t in all_tables:
            if '100 Nage Libre' in t.get_text() or 'Brasse' in t.get_text():
                table = t
                break

    if not table:
        divs = soup.find_all('div')
        for div in divs:
            if '100 Nage Libre' in div.get_text() or 'Brasse' in div.get_text():
                table = div.find('table')
                if table:
                    break

    if not table:
        print("Table non trouvée - Débogage:")
        print(f"Taille du HTML: {len(response.content)} bytes")
        with open('debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("HTML sauvegardé dans 'debug.html' pour inspection")
        all_tables = soup.find_all('table')
        print(f"Nombre total de tables trouvées: {len(all_tables)}")
        return []

    if debug:
        print("Table trouvée! Recherche des données...")

    results = []
    current_event = None
    current_date = None
    all_rows = table.find_all('tr')
    all_elements = table.find_all(['thead', 'tbody'])

    if debug:
        print(f"Nombre total de lignes (tr) trouvées: {len(all_rows)}")
        print(f"Nombre d'éléments thead/tbody trouvés: {len(all_elements)}")

    if not all_elements:
        rows = table.find_all('tr')
        if debug:
            print(f"Nombre de lignes trouvées: {len(rows)}")
            for i, row in enumerate(rows[:5]):
                cells = row.find_all(['td', 'th'])
                if len(cells) > 0:
                    text_content = ' '.join([cell.get_text(strip=True) for cell in cells[:3]])
                    print(f"Ligne {i+1}: {text_content[:100]}...")

    for idx, element in enumerate(all_elements):
        if element.name == 'thead':
            header_row = element.find('tr')
            if header_row:
                header_cell = header_row.find('td')
                if header_cell:
                    flex_div = header_cell.find('div', class_='flex flex-wrap items-center justify-between')
                    if not flex_div:
                        flex_div = header_cell.find('div')

                    if flex_div:
                        divs = flex_div.find_all('div', recursive=False)
                        if len(divs) >= 2:
                            current_event = divs[0].get_text(strip=True)
                            current_date = divs[1].get_text(strip=True)
                            if debug:
                                print(f"Épreuve trouvée: {current_event} - Date: {current_date}")
                        elif len(divs) == 1:
                            text = divs[0].get_text(strip=True)
                            parts = text.split(' - ')
                            if len(parts) >= 2:
                                current_event = parts[0].strip()
                                date_parts = parts[-1].split()
                                if len(date_parts) >= 4:
                                    current_date = ' '.join(date_parts[-4:])
                                if debug:
                                    print(f"Épreuve trouvée (parsing): {current_event} - Date: {current_date}")

        elif element.name == 'tbody':
            rows = element.find_all('tr')
            if debug:
                print(f"  Nombre de lignes dans ce tbody: {len(rows)}")
            for row_idx, row in enumerate(rows):
                row_text = row.get_text(strip=True)
                if not row_text:
                    continue

                cells = row.find_all('td')
                if len(cells) >= 4:
                    rank_cell = cells[0]
                    rank = rank_cell.get_text(strip=True)

                    swimmer_cell = cells[1]
                    swimmer_link = swimmer_cell.find('a')
                    swimmer_name = swimmer_link.get_text(strip=True) if swimmer_link else swimmer_cell.get_text(strip=True)

                    club_cell = cells[2]
                    club_link = club_cell.find('a')
                    club_name = club_link.get_text(strip=True) if club_link else club_cell.get_text(strip=True)

                    time_cell = cells[3]
                    time = time_cell.get_text(strip=True)

                    splits = []
                    split_links = time_cell.find_all('a', class_='text-blue-600')
                    for split_link in split_links:
                        split_time = split_link.get_text(strip=True)
                        if split_time:
                            split_info = {'time': split_time}
                            if split_link.get('title'):
                                split_info['distance'] = split_link.get('title')
                            elif split_link.get('data-distance'):
                                split_info['distance'] = split_link.get('data-distance')
                            elif split_link.get('data-tippy-content'):
                                tippy_content = split_link.get('data-tippy-content', '')
                                if 'm' in tippy_content.lower():
                                    distance_match = re.search(r'(\d+)\s*m', tippy_content, re.IGNORECASE)
                                    if distance_match:
                                        split_info['distance'] = distance_match.group(1) + 'm'
                            splits.append(split_info)

                    if not splits:
                        split_links = row.find_all('a', class_='text-blue-600')
                        for split_link in split_links:
                            split_time = split_link.get_text(strip=True)
                            if split_time:
                                split_info = {'time': split_time}
                                if split_link.get('title'):
                                    split_info['distance'] = split_link.get('title')
                                elif split_link.get('data-distance'):
                                    split_info['distance'] = split_link.get('data-distance')
                                elif split_link.get('data-tippy-content'):
                                    tippy_content = split_link.get('data-tippy-content', '')
                                    distance_match = re.search(r'(\d+)\s*m', tippy_content, re.IGNORECASE)
                                    if distance_match:
                                        split_info['distance'] = distance_match.group(1) + 'm'
                                splits.append(split_info)

                    mpp_info = ""
                    if len(cells) >= 7:
                        mpp_cell = cells[6]
                        mpp_button = mpp_cell.find('button')
                        if mpp_button and mpp_button.get('data-tippy-content'):
                            mpp_info = mpp_button.get('data-tippy-content', '')
                            mpp_info = mpp_info.replace('&lt;b&gt;', '').replace('&lt;/b&gt;', '')

                    if rank and swimmer_name and time:
                        result = {
                            'event': current_event,
                            'date': current_date,
                            'rank': rank,
                            'swimmer': swimmer_name,
                            'club': club_name,
                            'time': time,
                            'mpp': mpp_info
                        }
                        if splits:
                            result['splits'] = splits
                        results.append(result)
                    elif debug:
                        print(f"Ligne ignorée - Rank: '{rank}', Swimmer: '{swimmer_name}', Time: '{time}'")

    if len(results) == 0:
        if debug:
            print("\nTentative avec approche alternative: parcourir toutes les lignes...")
        current_event = None
        current_date = None

        for row in all_rows:
            cells = row.find_all(['td', 'th'])

            if len(cells) == 1 and ('Nage Libre' in row.get_text() or 'Brasse' in row.get_text()):
                text = row.get_text(strip=True)
                if ' - ' in text:
                    parts = text.split(' - ')
                    if len(parts) >= 2:
                        current_event = parts[0].strip()
                        date_text = ' - '.join(parts[1:])
                        days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
                        for day in days:
                            if day in date_text:
                                day_index = date_text.find(day)
                                date_parts = date_text[day_index:].split()
                                if len(date_parts) >= 4:
                                    current_date = ' '.join(date_parts[:4])
                                break
                        if not current_date:
                            current_date = date_text.strip()
                        if debug:
                            print(f"Épreuve détectée (alt): {current_event} - Date: {current_date}")

            elif len(cells) >= 4:
                rank = cells[0].get_text(strip=True)
                swimmer_cell = cells[1]
                swimmer_link = swimmer_cell.find('a')
                swimmer_name = swimmer_link.get_text(strip=True) if swimmer_link else swimmer_cell.get_text(strip=True)

                club_cell = cells[2] if len(cells) > 2 else None
                club_name = ""
                if club_cell:
                    club_link = club_cell.find('a')
                    club_name = club_link.get_text(strip=True) if club_link else club_cell.get_text(strip=True)

                time_cell = cells[3] if len(cells) > 3 else None
                time = time_cell.get_text(strip=True) if time_cell else ""

                splits = []
                if time_cell:
                    split_links = time_cell.find_all('a', class_='text-blue-600')
                    for split_link in split_links:
                        split_time = split_link.get_text(strip=True)
                        if split_time:
                            split_info = {'time': split_time}
                            if split_link.get('title'):
                                split_info['distance'] = split_link.get('title')
                            elif split_link.get('data-distance'):
                                split_info['distance'] = split_link.get('data-distance')
                            elif split_link.get('data-tippy-content'):
                                tippy_content = split_link.get('data-tippy-content', '')
                                distance_match = re.search(r'(\d+)\s*m', tippy_content, re.IGNORECASE)
                                if distance_match:
                                    split_info['distance'] = distance_match.group(1) + 'm'
                                splits.append(split_info)

                if not splits and time_cell:
                    split_links = row.find_all('a', class_='text-blue-600')
                    for split_link in split_links:
                        split_time = split_link.get_text(strip=True)
                        if split_time:
                            split_info = {'time': split_time}
                            if split_link.get('title'):
                                split_info['distance'] = split_link.get('title')
                            elif split_link.get('data-distance'):
                                split_info['distance'] = split_link.get('data-distance')
                            elif split_link.get('data-tippy-content'):
                                tippy_content = split_link.get('data-tippy-content', '')
                                distance_match = re.search(r'(\d+)\s*m', tippy_content, re.IGNORECASE)
                                if distance_match:
                                    split_info['distance'] = distance_match.group(1) + 'm'
                                splits.append(split_info)

                mpp_info = ""
                if len(cells) >= 7:
                    mpp_cell = cells[6]
                    mpp_button = mpp_cell.find('button')
                    if mpp_button and mpp_button.get('data-tippy-content'):
                        mpp_info = mpp_button.get('data-tippy-content', '')
                        mpp_info = mpp_info.replace('&lt;b&gt;', '').replace('&lt;/b&gt;', '').replace('<b>', '').replace('</b>', '')

                if rank and rank.replace('.', '').isdigit() and swimmer_name and time:
                    result = {
                        'event': current_event,
                        'date': current_date,
                        'rank': rank,
                        'swimmer': swimmer_name,
                        'club': club_name,
                        'time': time,
                        'mpp': mpp_info
                    }
                    if splits:
                        result['splits'] = splits
                    results.append(result)
                    if debug:
                        print(f"Résultat trouvé (alt): {swimmer_name} - {time}")

    if debug:
        print(f"Total de résultats extraits: {len(results)}")
    return results
