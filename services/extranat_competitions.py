"""Listing Extranat : types de compétition et calendrier paginé.

Extrait de ``extranat_service`` pour isoler la découverte des compétitions
(``idtyp``, pagination, métadonnées) sans scraping des résultats détaillés.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from services.extranat_http import http_get_with_retries

# --- Configuration Extranat (URLs) ---

BASE_URL = "https://ffn.extranat.fr/webffn/"
COMPETITIONS_PATH = "competitions.php?idact=nat"


def get_competitions_url_by_idtyp(idtyp: int) -> str:
    """Construit l'URL Extranat pour un type de compétition (``idtyp``).

    Args:
        idtyp (int): Identifiant du type (1=interclubs, 7=internationales, etc.).

    Returns:
        str: URL complète de la page liste des compétitions filtrée.
    """
    return f"{BASE_URL}competitions.php?idact=nat&idsai=&idreg=&idtyp={idtyp}"


def get_competition_types(
    base_url: str = BASE_URL,
    path: str = COMPETITIONS_PATH,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """Parse le ``<select id=liste_type>`` et renvoie les types de compétition.

    Chaque entrée contient ``idtyp``, libellé, valeur brute et URL complète.

    Args:
        base_url (str): URL de base du site Extranat.
        path (str): Chemin relatif de la page des types.
        debug (bool): Active les logs de parsing.

    Returns:
        List[Dict[str, Any]]: Types trouvés ; liste vide si le select est absent ou 403.
    """
    url = f"{base_url}{path}"

    if debug:
        print(f"Récupération des types de compétitions depuis : {url}")

    try:
        resp = http_get_with_retries(url, debug=debug)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(
                " x 403 Forbidden sur la page des compétitions "
            )
            print(
                "  Réessaie plus tard, ou avec moins de scripts en parallèle "
            )
            return []
        raise
    soup = BeautifulSoup(resp.content, "html.parser")

    select = soup.find("select", id="liste_type")
    if not select:
        select = soup.find("select", {"name": "idtyp"})

    if not select:
        if debug:
            print("Select #liste_type introuvable")
        return []

    types: List[Dict] = []

    for opt in select.find_all("option"):
        value = opt.get("value", "").strip()
        label = opt.get_text(strip=True)

        full_url = value
        if value and not value.startswith("http"):
            full_url = f"{base_url}{value}"

        idtyp: Optional[int] = None
        if "idtyp=" in value:
            # Extraire l'idtyp depuis la query string de l'option
            try:
                part = value.split("idtyp=", 1)[1]
                id_str = part.split("&")[0]
                idtyp = int(id_str)
            except (ValueError, IndexError):
                idtyp = None

        types.append(
            {
                "idtyp": idtyp,
                "label": label,
                "value": value,
                "url": full_url,
            }
        )

    if debug:
        print(f"{len(types)} type(s) de compétition trouvé(s)")
        for t in types:
            print(f"  - idtyp={t['idtyp']}, label='{t['label']}', url='{t['url']}'")

    return types


# --- Calendrier : liste paginée des compétitions ---


def get_competitions_for_url(
    url: str,
    debug: bool = False,
) -> List[Dict]:
    """Récupère la liste paginée des compétitions pour une URL Extranat.

    Suit les liens de pagination partageant le même filtre (idtyp, idsai, idreg)
    et parse chaque bloc compétition (nom, date, lieu, URL, bassin, etc.).

    Args:
        url (str): URL de la page liste des compétitions.
        debug (bool): Active les logs détaillés de pagination et parsing.

    Returns:
        List[Dict]: Métadonnées de chaque compétition trouvée.
    """
    competitions: List[Dict] = []

    if debug:
        print(f"Récupération des compétitions (avec pagination) depuis : {url}")

    from urllib.parse import urljoin, urlparse, parse_qs

    start_url = url
    parsed_start = urlparse(start_url)
    start_qs = parse_qs(parsed_start.query)

    def _same_filter(list_url: str) -> bool:
        """Vérifie qu'une URL de liste partage le même filtre que l'URL de départ.

        Args:
            list_url (str): URL candidate de pagination.

        Returns:
            bool: True si idtyp (et idsai/idreg le cas échéant) correspondent.
        """
        p = urlparse(list_url)
        if "competitions.php" not in p.path:
            return False
        qs = parse_qs(p.query)

        if start_qs.get("idtyp") != qs.get("idtyp"):
            return False
        for key in ("idsai", "idreg"):
            if key in start_qs and start_qs.get(key) != qs.get(key):
                return False
        return True

    visited: set[str] = set()
    to_visit: List[str] = [start_url]

    while to_visit:
        current_url = to_visit.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        if debug:
            print(f"  → Page liste : {current_url}")

        resp = http_get_with_retries(current_url, debug=debug)
        soup = BeautifulSoup(resp.content, "html.parser")

        competition_divs = soup.find_all("div", class_="border-b pb-2 mt-4")

        if debug:
            print(f"    → {len(competition_divs)} bloc(s) de compétition trouvé(s) sur cette page")

        for comp_div in competition_divs:
            comp_info: Dict = {}

            date_elements = comp_div.find_all("div", class_="text-blue-600")
            if date_elements:
                date_long = comp_div.find(
                    "div",
                    class_="text-blue-600 text-xs uppercase hidden md:block",
                )
                if date_long:
                    comp_info["date"] = date_long.get_text(strip=True)
                else:
                    comp_info["date"] = date_elements[0].get_text(strip=True)

            title_link = comp_div.find("a", href=True)
            if title_link:
                comp_info["name"] = title_link.get_text(strip=True)
                href = title_link.get("href")
                if href:
                    if "idcpt=" in href:
                        idcpt = href.split("idcpt=")[1].split("&")[0]
                        comp_info["competition_id"] = idcpt
                        comp_info["url"] = urljoin(BASE_URL, href)
                    else:
                        comp_info["url"] = urljoin(BASE_URL, href)

            location_span = comp_div.find(
                "span",
                class_=["uppercase", "text-green-700", "font-bold"],
            )
            if not location_span:
                location_span = comp_div.find(
                    "span", class_="uppercase text-green-700 font-bold"
                )
            if location_span:
                comp_info["location"] = location_span.get_text(strip=True)

            title_original = comp_div.find("div", class_="text-xs text-orange-600")
            if title_original:
                text = title_original.get_text(strip=True)
                if text.startswith("Titre original :"):
                    comp_info["original_title"] = (
                        text.replace("Titre original :", "").strip()
                    )

            type_divs = comp_div.find_all("div", class_="text-xs text-orange-600")
            for type_div in type_divs:
                text = type_div.get_text(strip=True)
                if text.startswith("Type de compétition :"):
                    comp_info["competition_type"] = (
                        text.replace("Type de compétition :", "").strip()
                    )

            bassin_img = comp_div.find("img", alt="taille bassin")
            if bassin_img:
                src = bassin_img.get("src", "")
                if "25m" in src:
                    comp_info["pool_size"] = "25m"
                elif "50m" in src:
                    comp_info["pool_size"] = "50m"

            level_div = comp_div.find("div", class_="text-red-700 font-light")
            if level_div:
                comp_info["level"] = level_div.get_text(strip=True)

            extract_span = comp_div.find("span", class_="md:block hidden")
            if extract_span and "extrait" in extract_span.get_text(strip=True).lower():
                comp_info["is_extract"] = True

            new_comp_img = comp_div.find("img", alt="nouvelle compétition")
            if new_comp_img:
                comp_info["is_new"] = True

            if "competition_id" in comp_info or "url" in comp_info:
                competitions.append(comp_info)
                if debug:
                    print(
                        f"      Compétition : {comp_info.get('name', 'N/A')} "
                        f"(ID: {comp_info.get('competition_id', 'N/A')})"
                    )

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "competitions.php" not in href:
                continue
            if "resultats.php" in href:
                continue
            full_url = urljoin(BASE_URL, href)
            if not _same_filter(full_url):
                continue
            if full_url not in visited and full_url not in to_visit:
                if debug:
                    print(f"    → Page de liste supplémentaire détectée : {full_url}")
                to_visit.append(full_url)

    return competitions
