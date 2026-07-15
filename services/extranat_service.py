"""Scraping Extranat (ffnatation.fr) : types de compétition, calendrier, résultats détaillés.

Ce module interroge le site Extranat (``ffn.extranat.fr``), parse les tableaux
HTML de résultats (épreuves, splits, MPP) et produit des structures JSON
sauvegardées sous ``data/raw/extranat/``.

Le flux de données :
1. **Types** — ``get_competition_types()`` lit le ``<select id=liste_type>`` et
   extrait les ``idtyp`` (championnats nationaux, internationaux, etc.).
2. **Calendrier** — ``get_competitions_for_url()`` parcourt la pagination et
   collecte les métadonnées de chaque compétition (nom, date, lieu, URL).
3. **Résultats** — deux stratégies de parsing :
   ``get_competition_data()`` (table unique) ou
   ``get_results_for_competitions_url()`` (formulaire par épreuve, plus complet).
4. **Orchestration** — ``get_all_results_by_type()`` / ``main()`` enchaînent types,
   compétitions et résultats ; ``generate_resume()`` produit un bilan d'erreurs.

Point d'entrée CLI : ``python services/extranat_service.py``.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup


# --- Couche HTTP (retries, backoff) ---


from services.extranat_http import http_get_with_retries

# --- Parsing HTML : page résultats (table unique) ---


def get_competition_data(
    url: str,
    debug: bool = False,
    session: Optional[requests.Session] = None,
    retry_forever: bool = True,
) -> List[Dict[str, Any]]:
    """Parse une page de résultats Extranat et renvoie une ligne par performance.

    Localise le tableau principal (plusieurs sélecteurs CSS en cascade), puis
    parcourt ``thead`` / ``tbody`` pour extraire épreuve, date, classement,
    nageur, club, temps, splits et MPP.

    Args:
        url (str): URL de la page résultats d'une compétition.
        debug (bool): Active les logs de parsing et sauvegarde ``debug.html`` si échec.
        session (Optional[requests.Session]): Session HTTP réutilisable.
        retry_forever (bool): Passe le mode retry infini à ``http_get_with_retries``.

    Returns:
        List[Dict[str, Any]]: Performances extraites ; liste vide si aucune table trouvée.
    """
    response = http_get_with_retries(
        url,
        debug=debug,
        max_retries=5,
        session=session,
        retry_forever=retry_forever,
    )

    soup = BeautifulSoup(response.content, 'html.parser')

    # Recherche en cascade : le markup Extranat varie selon les pages
    table = None
    table_div = soup.find('div', class_='relative overflow-x-auto shadow-md sm:rounded-lg print-not-shadow')
    if table_div:
        table = table_div.find('table')

    if not table:
        table = soup.find('table', class_='w-full text-sm text-left text-gray-500')

    if not table:
        # Fallback : repérer une table contenant du texte d'épreuve typique
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
            # L'en-tête thead porte le nom de l'épreuve et la date
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
                        # Colonne MPP (meilleure performance personnelle) via tooltip
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

import json, os
import os
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from services.extranat_parse import extract_results_from_filter_table
from services.extranat_competitions import (
    BASE_URL,
    COMPETITIONS_PATH,
    get_competitions_url_by_idtyp,
    get_competition_types,
    get_competitions_for_url,
)
from services.extranat_results import get_results_for_competitions_url

# --- Configuration Extranat (URLs, chemins de sortie) ---

# Page des compétitions internationales (idtyp=7)
INTERNATIONALS_URL = ("https://ffn.extranat.fr/webffn/competitions.php?idact=nat&idsai=&idreg=&idtyp=7")


# --- Orchestration : collecte multi-types ---


def get_all_results_by_type(
    base_url: str = BASE_URL,
    path: str = COMPETITIONS_PATH,
    delay_between_comps: float = 1.0,
    debug: bool = False,
    only_idtyps: Optional[List[int]] = None,
) -> Dict:
    """Agrège les résultats de toutes les compétitions, groupés par type.

    Pour chaque type, récupère la liste des compétitions puis appelle
    ``get_competition_data`` sur chacune.

    Args:
        base_url (str): URL de base du site Extranat.
        path (str): Chemin relatif de la page des types de compétition.
        delay_between_comps (float): Délai en secondes entre deux compétitions.
        debug (bool): Active les logs détaillés.
        only_idtyps (Optional[List[int]]): Restreint aux idtyp indiqués.

    Returns:
        Dict: Structure ``{"types": [...]}`` avec compétitions et résultats imbriqués.
    """
    types = get_competition_types(base_url=base_url, path=path, debug=debug)

    data: Dict = {"types": []}

    if not types:
        return data

    # Ne traiter que les vrais types (ignorer l'option "Type de compétition" sans idtyp)
    types = [t for t in types if t.get("idtyp") is not None]

    if not types:
        return data

    import time

    if only_idtyps:
        types = [t for t in types if t.get("idtyp") in only_idtyps]

    total_types = len(types)
    for idx, t in enumerate(types, 1):
        label = t.get("label", "")
        url = t.get("url")

        if not url:
            continue

        if debug:
            print(
                f"\n[{idx}/{total_types}] Type: idtyp={t.get('idtyp')} - {label}\n"
            )

        competitions = get_competitions_for_url(url, debug=debug)

        for c_idx, comp in enumerate(competitions, 1):
            comp_url = comp.get("url")
            if not comp_url:
                continue

            if debug:
                print(
                    f"  [{c_idx}/{len(competitions)}] "
                    f"{comp.get('name', 'N/A')}"
                )

            try:
                results = get_competition_data(comp_url, debug=False)
                comp["results"] = results
                comp["results_count"] = len(results)

                if debug:
                    print(f"      → {len(results)} résultat(s)")
            except Exception as e:
                comp["results"] = []
                comp["results_count"] = 0
                comp["error"] = str(e)
                if debug:
                    print(f"      ✗ Erreur lors de la récupération : {e}")

            # Petite pause pour éviter de spammer le site
            if delay_between_comps > 0 and c_idx < len(competitions):
                time.sleep(delay_between_comps)

        t_data = dict(t)
        t_data["competitions"] = competitions
        data["types"].append(t_data)

    return data


def get_all_results_grouped_by_event_by_type(
    base_url: str = BASE_URL,
    path: str = COMPETITIONS_PATH,
    delay_between_comps: float = 1.0,
    debug: bool = False,
    only_idtyps: Optional[List[int]] = None,
) -> Dict:
    """Agrège les résultats groupés par épreuve pour tous les types.

    Variante de ``get_all_results_by_type`` qui utilise
    ``get_results_for_competitions_url`` (formulaire par épreuve) au lieu de
    ``get_competition_data`` (table unique). Structure de retour identique
    mais ``results`` est un dict ``{nom_épreuve: [performances]}``.

    Args:
        base_url (str): URL de base du site Extranat.
        path (str): Chemin relatif de la page des types.
        delay_between_comps (float): Délai en secondes entre deux compétitions.
        debug (bool): Active les logs détaillés.
        only_idtyps (Optional[List[int]]): Restreint aux idtyp indiqués.

    Returns:
        Dict: Structure ``{"types": [...]}`` avec compétitions et résultats imbriqués.
    """
    types = get_competition_types(base_url=base_url, path=path, debug=debug)

    data: Dict = {"types": []}

    if not types:
        return data

    # Ne traiter que les vrais types (ignorer l'option "Type de compétition" sans idtyp)
    types = [t for t in types if t.get("idtyp") is not None]

    if not types:
        return data

    if only_idtyps:
        types = [t for t in types if t.get("idtyp") in only_idtyps]

    total_types = len(types)
    for idx, t in enumerate(types, 1):
        label = t.get("label", "")
        url = t.get("url")

        if not url:
            continue

        if debug:
            print(
                f"\n[{idx}/{total_types}] Type (grouped): idtyp={t.get('idtyp')} - {label}\n"
            )

        try:
            # Réutilise la fonction qui gère le formulaire et les épreuves
            results_for_type = get_results_for_competitions_url(
                url,
                delay_between_comps=delay_between_comps,
                debug=debug,
            )
        except Exception as e:
            if debug:
                print(
                    f"  ✗ Erreur lors de la récupération groupée pour le type "
                    f"idtyp={t.get('idtyp')} - {label} : {e}"
                )
            type_entry = {
                "idtyp": t.get("idtyp"),
                "label": label,
                "url": url,
                "competitions": [],
                "error": str(e),
            }
            data["types"].append(type_entry)
            continue

        competitions = results_for_type.get("competitions", [])

        type_entry = {
            "idtyp": t.get("idtyp"),
            "label": label,
            "url": url,
            "competitions": competitions,
        }
        data["types"].append(type_entry)

    return data


# --- Collecte avancée : formulaire par épreuve + gestion de session ---
# ``get_results_for_competitions_url`` est importé depuis ``services.extranat_results``
# (réexporté ici pour compatibilité des imports existants).


# --- Raccourcis : compétitions internationales (idtyp=7) ---


def get_international_results(
    delay_between_comps: float = 1.0,
    debug: bool = False,
) -> Dict:
    """Raccourci : compétitions internationales (idtyp=7) avec résultats complets.

    Délègue à ``get_results_for_competitions_url`` sur ``INTERNATIONALS_URL``.

    Args:
        delay_between_comps (float): Délai (s) entre deux compétitions.
        debug (bool): Active les logs détaillés.

    Returns:
        Dict: Compétitions et résultats groupés par épreuve.
    """
    return get_results_for_competitions_url(
        INTERNATIONALS_URL,
        delay_between_comps=delay_between_comps,
        debug=debug,
    )


def get_international_competitions_list(
    debug: bool = False,
) -> Dict:
    """Liste les compétitions internationales (idtyp=7) sans résultats détaillés.

    Ne charge que la page calendrier ; utile pour un inventaire rapide.

    Args:
        debug (bool): Active les logs de pagination.

    Returns:
        Dict: ``{"url", "competitions"}`` avec métadonnées uniquement.
    """
    if debug:
        print(
            "Récupération de la liste des compétitions pour "
            '"Compétitions internationales" (idtyp=7)'
        )

    competitions = get_competitions_for_url(INTERNATIONALS_URL, debug=debug)
    return {"url": INTERNATIONALS_URL, "competitions": competitions}


# --- Bilan de collecte et résumés JSON ---


def generate_resume(
    data: Dict,
    output_dir: str,
    idtyp: Optional[int] = None,
    type_name: Optional[str] = None,
) -> Dict:
    """Génère un résumé des erreurs de collecte et sauvegarde les JSON associés.

    Calcule le taux d'erreur par type et globalement, puis écrit un fichier
    ``resume.json`` global et un ``resume_{type}.json`` par type dans
    ``output_dir``.

    Args:
        data (Dict): Données collectées (mode type unique ou multi-types).
        output_dir (str): Dossier de sortie des fichiers résumé.
        idtyp (Optional[int]): ID du type en mode collecte ciblée.
        type_name (Optional[str]): Libellé du type en mode collecte ciblée.

    Returns:
        Dict: Résumé avec ``resume`` (global) et ``par_type`` (détail par idtyp).
    """
    from datetime import datetime
    
    resume: Dict = {
        "resume": {},
        "par_type": []
    }
    
    # Table de correspondance idtyp → libellé affiché dans les résumés
    type_names = {
        1: "Interclubs Avenirs (Rég. & Dép.)",
        2: "Interclubs Jeunes (Rég. & Dép.)",
        3: "Interclubs TC (Rég. & Dép.)",
        4: "Championnats Régionaux",
        5: "Meetings nationaux labellisés",
        6: "Championnats nationaux",
        7: "Compétitions internationales",
        8: "Compétitions interrégionales",
        12: "Régionaux (web confrontation)",
        13: "Animation « A vos plots ! »",
        14: "Coupes Nationales",
        15: "Coupes Régionales",
    }
    
    total_competitions_global = 0
    total_errors_global = 0
    
    # Cas 1 : Mode par type (un seul idtyp)
    if idtyp is not None and "competitions" in data:
        competitions = data.get("competitions", [])
        total_comp = len(competitions)
        errors = [c for c in competitions if "error" in c]
        total_errors = len(errors)
        
        error_percentage = (total_errors / total_comp * 100) if total_comp > 0 else 0.0
        
        # Détails des erreurs
        errors_details = []
        for comp in errors:
            errors_details.append({
                "name": comp.get("name", "N/A"),
                "competition_id": comp.get("competition_id"),
                "error": comp.get("error", "Erreur inconnue")
            })
        
        resume["par_type"].append({
            "idtyp": idtyp,
            "type_name": type_name or type_names.get(idtyp, f"Type idtyp={idtyp}"),
            "filename": f"results_idtyp_{idtyp}.json",
            "total_competitions": total_comp,
            "competitions_with_errors": total_errors,
            "competitions_without_errors": total_comp - total_errors,
            "error_percentage": f"{round(error_percentage, 2)}%",
            "errors": errors_details
        })
        
        total_competitions_global = total_comp
        total_errors_global = total_errors
    
    # Cas 2 : Mode global (tous les types)
    elif "types" in data:
        types_list = data.get("types", [])
        
        for type_data in types_list:
            idtyp_val = type_data.get("idtyp")
            competitions = type_data.get("competitions", [])
            total_comp = len(competitions)
            errors = [c for c in competitions if "error" in c]
            total_errors = len(errors)
            
            error_percentage = (total_errors / total_comp * 100) if total_comp > 0 else 0.0
            
            # Détails des erreurs (limité aux 10 premières pour éviter un fichier trop volumineux)
            errors_details = []
            for comp in errors[:10]:
                errors_details.append({
                    "name": comp.get("name", "N/A"),
                    "competition_id": comp.get("competition_id"),
                    "error": comp.get("error", "Erreur inconnue")
                })
            if len(errors) > 10:
                errors_details.append({
                    "name": f"... et {len(errors) - 10} autre(s) erreur(s)",
                    "competition_id": None,
                    "error": None
                })
            
            resume["par_type"].append({
                "idtyp": idtyp_val,
                "type_name": type_data.get("label", type_names.get(idtyp_val, f"Type idtyp={idtyp_val}")),
                "filename": f"results_idtyp_{idtyp_val}.json" if idtyp_val else "results_by_type.json",
                "total_competitions": total_comp,
                "competitions_with_errors": total_errors,
                "competitions_without_errors": total_comp - total_errors,
                "error_percentage": f"{round(error_percentage, 2)}%",
                "errors": errors_details
            })
            
            total_competitions_global += total_comp
            total_errors_global += total_errors
    
    # Calcul du pourcentage global
    global_error_percentage = (total_errors_global / total_competitions_global * 100) if total_competitions_global > 0 else 0.0
    
    resume["resume"] = {
        "date_generation": datetime.now().isoformat(),
        "total_types": len(resume["par_type"]),
        "total_competitions": total_competitions_global,
        "total_competitions_with_errors": total_errors_global,
        "total_competitions_without_errors": total_competitions_global - total_errors_global,
        "global_error_percentage": f"{round(global_error_percentage, 2)}%"
    }
    
    # Fonction helper pour convertir un nom de type en nom de fichier valide
    def type_name_to_filename(type_name: str) -> str:
        """Convertit un nom de type de compétition en nom de fichier valide."""
        if not type_name:
            return "resume_type_inconnu"
        
        # Convertir en minuscules
        filename = type_name.lower()
        
        # Remplacer les caractères spéciaux et espaces par des underscores
        import re
        filename = re.sub(r'[^\w\s-]', '', filename)  # Supprimer caractères spéciaux
        filename = re.sub(r'[-\s]+', '_', filename)  # Remplacer espaces et tirets par underscore
        filename = filename.strip('_')  # Supprimer underscores en début/fin
        
        # Nettoyer les caractères interdits pour Windows
        forbidden = '\\/:*?"<>|'
        filename = "".join(("_" if ch in forbidden else ch) for ch in filename)
        
        return f"resume_{filename}"
    
    # Sauvegarder un fichier de résumé pour chaque type individuellement
    for type_info in resume["par_type"]:
        idtyp_val = type_info.get("idtyp")
        type_name_val = type_info.get("type_name", "")
        
        if idtyp_val is not None or type_name_val:
            # Créer un résumé individuel pour ce type
            type_resume = {
                "date_generation": datetime.now().isoformat(),
                "idtyp": idtyp_val,
                "type_name": type_name_val,
                "filename": type_info.get("filename"),
                "total_competitions": type_info.get("total_competitions"),
                "competitions_with_errors": type_info.get("competitions_with_errors"),
                "competitions_without_errors": type_info.get("competitions_without_errors"),
                "error_percentage": type_info.get("error_percentage"),
                "errors": type_info.get("errors", [])
            }
            
            # Générer le nom de fichier basé sur le nom du type
            filename_base = type_name_to_filename(type_name_val)
            type_resume_path = os.path.join(output_dir, f"{filename_base}.json")
            with open(type_resume_path, "w", encoding="utf-8") as f:
                json.dump(type_resume, f, ensure_ascii=False, indent=2)
    
    # Sauvegarder aussi le résumé global (tous types confondus)
    resume_path = os.path.join(output_dir, "resume.json")
    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)
    
    return resume
    

# --- Chemins de sortie (data/raw/extranat) ---

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRANAT_DATA_DIR = os.path.join(BASE_DIR, "data", "raw", "extranat")
COMPETITIONS_PER_TYPE_DIR = os.path.join(EXTRANAT_DATA_DIR, "competitions_per_type")
RESUMES_DIR = os.path.join(EXTRANAT_DATA_DIR, "Resumes")
COMPETITIONS_PER_DATES_DIR = os.path.join(EXTRANAT_DATA_DIR, "competitions_per_dates")


# --- Point d'entrée CLI ---


def main():
    """Point d'entrée CLI : scrape types/compétitions selon les arguments.

    Usage typique :
    - ``python services/extranat_service.py`` → tous les types (mode intl)
    - ``python services/extranat_service.py debug`` → logs verbeux
    - ``python services/extranat_service.py intl 7 fast`` → idtyp=7 sans pause
    - ``python services/extranat_service.py 2025`` → compétitions de l'année 2025

    Sauvegarde les résultats dans ``competitions_per_type/`` et les résumés
    dans ``Resumes/``.

    Returns:
        None
    """
    import sys
    from datetime import datetime, date
    import re

    # Créer le dossier pour stocker les fichiers JSON de résultats détaillés
    output_dir = COMPETITIONS_PER_TYPE_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Créer le dossier pour stocker uniquement les résumés
    resumes_dir = RESUMES_DIR
    os.makedirs(resumes_dir, exist_ok=True)

    # Nouveau : dossier pour stocker les résumés par intervalles de dates
    dates_dir = COMPETITIONS_PER_DATES_DIR
    os.makedirs(dates_dir, exist_ok=True)

    debug = False
    # Pas de pause entre compétitions par défaut (0 = rapide). Mettre "slow" en argument pour activer un délai.
    delay_between_comps = 0.0
    only_idtyps: Optional[List[int]] = None

    # Parsing simple des arguments :
    #   debug           → mode verbeux
    #   fast            → pas de pause entre compétitions (delay = 0)
    #   intl/international → par type (idtyp)
    #   2025            → extraire toutes les compétitions dont la date est en 2025
    #   02/02/2025 10/10/2025 → extraire les compétitions entre ces deux dates
    raw_args = sys.argv[1:]

    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Mode "année seule" : python get_data_deeper.py 2025
    # → on extrait toutes les compétitions dont la date est dans l'année 2025
    def _is_year_token(s: str) -> bool:
        """Indique si une chaîne représente une année valide (1970–2030).

        Args:
            s (str): Jeton à tester.

        Returns:
            bool: True si ``s`` est un entier à quatre chiffres dans la plage autorisée.
        """
        if not s.isdigit() or len(s) != 4:
            return False
        y = int(s)
        return 1970 <= y <= 2030

    # Mode "deux dates" : python get_data_deeper.py 02/02/2025 10/10/2025
    def _parse_date_token(s: str) -> Optional[date]:
        """Parse une date au format ``DD/MM/YYYY``.

        Args:
            s (str): Chaîne de date à convertir.

        Returns:
            Optional[date]: Objet ``date`` ou None si le format est invalide.
        """
        if "/" not in s or len(s) != 10:
            return None
        try:
            return datetime.strptime(s, "%d/%m/%Y").date()
        except ValueError:
            return None

    non_option = [a for a in raw_args if a.lower() not in ("debug", "fast", "list")]
    if non_option:
        if len(non_option) == 1 and _is_year_token(non_option[0]):
            year = int(non_option[0])
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
            raw_args = [
                "intl", "1", "2", "3", "4", "5", "6", "7", "8",
                "12", "13", "14", "15",
            ]
            if "debug" in [a.lower() for a in sys.argv[1:]]:
                raw_args.append("debug")
            if "fast" in [a.lower() for a in sys.argv[1:]]:
                raw_args.append("fast")
            print(f"Mode année : extraction des compétitions dont la date est en {year}")
        elif len(non_option) == 2:
            d1 = _parse_date_token(non_option[0])
            d2 = _parse_date_token(non_option[1])
            if d1 is not None and d2 is not None:
                start_date = min(d1, d2)
                end_date = max(d1, d2)
                raw_args = [
                    "intl", "1", "2", "3", "4", "5", "6", "7", "8",
                    "12", "13", "14", "15",
                ]
                if "debug" in [a.lower() for a in sys.argv[1:]]:
                    raw_args.append("debug")
                if "fast" in [a.lower() for a in sys.argv[1:]]:
                    raw_args.append("fast")
                print(f"Mode plage de dates : du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}")

    # Si aucun argument n'est fourni, ou si on ne passe que "debug",
    # on enchaîne automatiquement tous les principaux types de compétitions avec debug
    if (not raw_args) or (len(raw_args) == 1 and raw_args[0].lower() == "debug"):
        raw_args = [
            "intl",
            "1", "2", "3", "4", "5", "6", "7", "8",
            "12", "13", "14", "15",
            "debug",
        ]

    args = [a.lower() for a in raw_args]

    # Parsing éventuel de bornes de dates au format JJ/MM/AAAA (si pas déjà défini par mode année/plage)
    # Exemple : python get_data_deeper.py intl 15 fast debug 10/01/2026 12/01/2026
    if start_date is None and end_date is None:
        parsed_dates = []
        for raw in raw_args:
            if "/" not in raw:
                continue
            try:
                d = datetime.strptime(raw, "%d/%m/%Y").date()
                parsed_dates.append(d)
            except ValueError:
                continue
        if parsed_dates:
            start_date = min(parsed_dates)
            end_date = max(parsed_dates)

    def _parse_competition_date(date_str: str) -> Optional[date]:
        """
        Extrait une date JJ/MM/AAAA d'une chaîne comme
        'Samedi 10/01/2026' ou 'Sa 10/01/26' et la convertit en date.
        Seule la partie JJ/MM/AAAA est utilisée pour la comparaison.
        """
        if not date_str:
            return None
        # Chercher explicitement un motif JJ/MM/AAAA
        m = re.search(r"(\d{2}/\d{2}/\d{4})", date_str)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), "%d/%m/%Y").date()
        except ValueError:
            return None

    if "debug" in args:
        debug = True
    if "fast" in args:
        delay_between_comps = 0.0

    # Mode spécial : compétitions par type (idtyp)
    # Permet maintenant de traiter UN ou PLUSIEURS idtyp avec "intl"
    # ex : python get_data_deeper.py intl 1 fast debug
    #      python get_data_deeper.py intl 1 2 3 fast
    idtyp = None
    if "intl" in args or "international" in args:
        # Chercher tous les nombres dans les arguments (les idtyp)
        id_list: List[int] = []
        for raw_arg in raw_args:
            if raw_arg.isdigit():
                try:
                    id_list.append(int(raw_arg))
                except ValueError:
                    continue

        # Si pas d'idtyp spécifié, utiliser [7] par défaut (Compétitions internationales)
        if not id_list:
            id_list = [7]

        # Noms des types de compétitions (pour l'affichage)
        type_names = {
            1: "Interclubs Avenirs (Rég. & Dép.)",
            2: "Interclubs Jeunes (Rég. & Dép.)",
            3: "Interclubs TC (Rég. & Dép.)",
            4: "Championnats Régionaux",
            5: "Meetings nationaux labellisés",
            6: "Championnats nationaux",
            7: "Compétitions internationales",
            8: "Compétitions interrégionales",
            12: "Régionaux (web confrontation)",
            13: "Animation « A vos plots ! »",
            14: "Coupes Nationales",
            15: "Coupes Régionales",
        }

        # Boucle sur tous les idtyp demandés (1, 2, 3, ... ou 7 par défaut)
        for idtyp in id_list:
            type_name = type_names.get(idtyp, f"Type idtyp={idtyp}")
            
            print("=" * 60)
            print(f"RÉCUPÉRATION DES COMPÉTITIONS : {type_name} (idtyp={idtyp})")
            print("=" * 60)
            
            if debug:
                print(f"Options : delay_between_comps={delay_between_comps}")
            
            # Construire l'URL pour ce type
            url = get_competitions_url_by_idtyp(idtyp)
            
            # Si l'utilisateur veut seulement la liste des compétitions (sans résultats),
            # il peut ajouter "list" dans les arguments
            if "list" in args:
                competitions = get_competitions_for_url(url, debug=debug)
                data = {"url": url, "competitions": competitions}
                filename = os.path.join(output_dir, f"competitions_idtyp_{idtyp}.json")
            
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            
                print("\n" + "=" * 60)
                print(f"RÉSUMÉ (liste des compétitions - {type_name})")
                print("=" * 60)
                print(f"- Compétitions : {len(competitions)}")
                print(f"- Fichier      : {filename}")
                print("=" * 60)
                # On passe au type suivant le cas échéant
                continue
            else:
                # Récupérer les compétitions avec leurs résultats
                data = get_results_for_competitions_url(
                    url,
                    delay_between_comps=delay_between_comps,
                    debug=debug,
                )
            
                competitions = data.get("competitions", [])
            
                # Si des bornes de dates ont été fournies sur la ligne de commande,
                # filtrer les compétitions sur la date affichée dans
                # <div class="text-blue-600 text-xs uppercase hidden md:block">
                # Exemple HTML :
                #   <div class="text-blue-600 text-xs uppercase hidden md:block">
                #       Samedi 10/01/2026
                #   </div>
                if start_date is not None and end_date is not None:
                    filtered_competitions: List[Dict] = []
                    for comp in competitions:
                        comp_date_str = comp.get("date")
                        comp_date = _parse_competition_date(comp_date_str) if comp_date_str else None
                        if comp_date is None:
                            continue
                        if start_date <= comp_date <= end_date:
                            filtered_competitions.append(comp)
            
                    competitions = filtered_competitions
                    data["competitions"] = competitions
            
                total_competitions = len(competitions)
                total_results = sum(c.get("results_count", 0) for c in competitions)
                total_errors = sum(1 for c in competitions if "error" in c)
            
                # Nouveau : créer un dossier par type et un fichier JSON par compétition
                # Exemple demandé : pour idtyp=1 (Interclubs Avenirs (Rég. & Dép.)),
                # créer un dossier "Interclubs Avenirs" dans "competitions_per_type",
                # contenant un fichier JSON par compétition.
                folder_name = type_name.split(" (")[0] if type_name else f"type_{idtyp}"
                type_dir = os.path.join(output_dir, folder_name)
                os.makedirs(type_dir, exist_ok=True)
            
                # Pour éviter d'écraser des fichiers lorsque plusieurs compétitions
                # ont exactement le même nom (même "Phase qualificative ..." sur
                # plusieurs régions ou années), on garde en mémoire les bases déjà
                # utilisées et on ajoute un suffixe (ID ou compteur) en cas de
                # collision.
                used_bases: set[str] = set()
            
                # Nouveau : conserver la liste de tous les fichiers de résultats
                # générés pour ce type (et cette plage de dates éventuelle), afin
                # de pouvoir les référencer dans le fichier de résumé par dates
                # (competitions_per_dates/*.json).
                competitions_files: List[str] = []
            
                for comp in competitions:
                    # Nom brut de la compétition
                    raw_name = comp.get("name", "competition_sans_nom")
            
                    # Adapter le nom comme demandé pour le fichier :
                    # ex. "Interclubs départementaux U11 - TARN"
                    #  → "Interclubs départementaux U11-TARN"
                    name_for_file = raw_name.replace(" - ", "-").strip()
            
                    # Nettoyage pour un nom de fichier Windows :
                    # - supprimer / remplacer les caractères interdits  \ / : * ? " < > |
                    # - éviter de terminer par un point ou un espace
                    forbidden = '\\/:*?"<>|'
                    safe_base = "".join(
                        ("_" if ch in forbidden else ch) for ch in name_for_file
                    ).rstrip(" .")
            
                    if not safe_base:
                        safe_base = "competition_sans_nom"
            
                    # Assurer l'unicité du nom de base dans ce dossier de type :
                    # si une autre compétition a déjà utilisé le même safe_base,
                    # on lui ajoute en priorité l'ID de compétition, sinon un
                    # suffixe numérique.
                    original_base = safe_base
                    if safe_base in used_bases:
                        comp_id = comp.get("competition_id")
                        if comp_id:
                            safe_base = f"{original_base}_ID{comp_id}"
                        else:
                            idx = 2
                            candidate = f"{original_base}_{idx}"
                            while candidate in used_bases:
                                idx += 1
                                candidate = f"{original_base}_{idx}"
                            safe_base = candidate
                    used_bases.add(safe_base)
            
                    # Vérifier si results est un dictionnaire avec des filtres (Dames, Messieurs, Mixtes)
                    results = comp.get("results", {})
                    is_filtered = (
                        isinstance(results, dict)
                        and len(results) > 0
                        and any(
                            key in ["Dames", "Messieurs", "Mixtes"]
                            for key in results.keys()
                        )
                    )
            
                    if is_filtered:
                        # Créer un fichier JSON par filtre
                        for filter_name, filter_results in results.items():
                            # Ignorer les clés spéciales comme "_info" ou "_error"
                            if filter_name.startswith("_"):
                                continue
            
                            # Créer une copie de la compétition sans le champ "results" agrégé
                            comp_filtered = {k: v for k, v in comp.items() if k != "results"}
            
                            # Nouveau format pour les compétitions filtrées :
                            # on stocke les épreuves dans "epreuves" au lieu de "results".
                            if isinstance(filter_results, list):
                                comp_filtered["epreuves"] = filter_results
            
                                # Compter le nombre total de performances
                                total_perfs = 0
                                for epreuve in filter_results:
                                    if isinstance(epreuve, dict):
                                        perfs = epreuve.get("performances", [])
                                        if isinstance(perfs, list):
                                            total_perfs += len(perfs)
                                comp_filtered["results_count"] = total_perfs
                            else:
                                comp_filtered["epreuves"] = []
                                comp_filtered["results_count"] = 0
            
                            comp_filtered["filter"] = filter_name
                            comp_filtered["name"] = f"{safe_base}-{filter_name}"
            
                            comp_filename = f"{safe_base}-{filter_name}.json"
                            comp_path = os.path.join(type_dir, comp_filename)
                            with open(comp_path, "w", encoding="utf-8") as f:
                                json.dump(comp_filtered, f, ensure_ascii=False, indent=2)
                            # Sauvegarder le chemin du fichier de résultats
                            competitions_files.append(comp_path)
                    else:
                        def _normalize_event_fields(results_dict: Dict) -> None:
                            """Complète les champs ``event`` et ``date`` manquants sur chaque performance.

                            Args:
                                results_dict (Dict): Résultats indexés par nom d'épreuve.

                            Returns:
                                None
                            """
                            for event_name, perfs in results_dict.items():
                                if not isinstance(perfs, list):
                                    continue
                                for perf in perfs:
                                    if not isinstance(perf, dict):
                                        continue
                                    if perf.get("event") is None:
                                        perf["event"] = event_name
                                    if perf.get("date") is None and comp.get("date"):
                                        perf["date"] = comp["date"]
            
                        def _results_to_epreuves(
                            results_dict: Dict, default_categorie: Optional[str] = None
                        ) -> List[Dict]:
                            """Convertit un dict plat de résultats en liste d'épreuves structurées.

                            Args:
                                results_dict (Dict): Performances groupées par nom d'épreuve.
                                default_categorie (Optional[str]): Catégorie par défaut (Dames/Messieurs).

                            Returns:
                                List[Dict]: Épreuves avec performances séparées par genre.
                            """
                            epreuves: List[Dict] = []
            
                            def _base_event_name(perfs_list: List[Dict], fallback: str) -> str:
                                """Extrait le nom d'épreuve sans suffixe genre ni tour.

                                Args:
                                    perfs_list (List[Dict]): Performances d'une même épreuve.
                                    fallback (str): Nom de repli si aucun libellé exploitable.

                                Returns:
                                    str: Nom d'épreuve normalisé.
                                """
                                for p in perfs_list:
                                    if not isinstance(p, dict):
                                        continue
                                    ev = p.get("event") or fallback
                                    if not isinstance(ev, str):
                                        continue
                                    text = ev.strip()
                                    if " - " in text:
                                        text = text.split(" - ", 1)[0].strip()
                                    for gender_word in (" Dames", " Messieurs"):
                                        if text.endswith(gender_word):
                                            text = text[: -len(gender_word)].strip()
                                            break
                                    if text:
                                        return text
                                return fallback
                            for event_name, perfs in results_dict.items():
                                if isinstance(event_name, str) and event_name.startswith("_"):
                                    continue
                                if not isinstance(perfs, list):
                                    continue
                                performances_dames: List[Dict] = []
                                performances_messieurs: List[Dict] = []
                                performances_neutres: List[Dict] = []
            
                                for perf in perfs:
                                    if not isinstance(perf, dict):
                                        continue
            
                                    if "classement" in perf and "nageur" in perf:
                                        nageur_info = perf.get("nageur", {}) or {}
                                        if not isinstance(nageur_info, dict):
                                            nageur_info = {}
            
                                        event_label = perf.get("event") or event_name
                                        if nageur_info.get("sexe") is None and isinstance(
                                            event_label, str
                                        ):
                                            if "Dames" in event_label:
                                                nageur_info["sexe"] = "F"
                                            elif "Messieurs" in event_label:
                                                nageur_info["sexe"] = "M"
            
                                        sexe = nageur_info.get("sexe")
                                        perf["nageur"] = nageur_info
            
                                        cat_perf: Optional[str] = None
                                        if sexe == "F":
                                            cat_perf = "Dames"
                                        elif sexe == "M":
                                            cat_perf = "Messieurs"
                                        else:
                                            event_label = perf.get("event") or event_name
                                            if isinstance(event_label, str):
                                                if "Dames" in event_label:
                                                    cat_perf = "Dames"
                                                elif "Messieurs" in event_label:
                                                    cat_perf = "Messieurs"
            
                                        if cat_perf == "Dames":
                                            performances_dames.append(perf)
                                        elif cat_perf == "Messieurs":
                                            performances_messieurs.append(perf)
                                        else:
                                            performances_neutres.append(perf)
                                        continue
            
                                    rank_val = perf.get("rank")
                                    classement: Optional[int] = None
                                    if isinstance(rank_val, int):
                                        classement = rank_val
                                    elif isinstance(rank_val, str):
                                        import re as _re_mod
            
                                        m_rank = _re_mod.search(r"(\d+)", rank_val)
                                        if m_rank:
                                            try:
                                                classement = int(m_rank.group(1))
                                            except ValueError:
                                                classement = None
            
                                    nageur_obj: Dict
                                    if isinstance(perf.get("nageur"), dict):
                                        nageur_obj = perf["nageur"]
                                    else:
                                        swimmer_name = perf.get("swimmer")
                                        event_label2_for_sex = perf.get("event") or event_name
                                        sexe_inferred: Optional[str] = None
                                        if isinstance(event_label2_for_sex, str):
                                            if "Dames" in event_label2_for_sex:
                                                sexe_inferred = "F"
                                            elif "Messieurs" in event_label2_for_sex:
                                                sexe_inferred = "M"
                                        nageur_obj = {
                                            "name": swimmer_name,
                                            "sexe": sexe_inferred,
                                            "annee_naissance": None,
                                            "age": None,
                                            "nationalite": None,
                                        }
            
                                    new_perf: Dict = {
                                        "classement": classement,
                                        "nageur": nageur_obj,
                                        "club": perf.get("club"),
                                        "temps": perf.get("time") or perf.get("temps"),
                                    }
                                    if "points" in perf:
                                        new_perf["points"] = perf["points"]
                                    if "mpp" in perf:
                                        new_perf["mpp"] = perf["mpp"]
                                    if "splits" in perf:
                                        new_perf["splits"] = perf["splits"]
            
                                    cat_perf2: Optional[str] = None
                                    event_label2 = perf.get("event") or event_name
                                    if isinstance(event_label2, str):
                                        if "Dames" in event_label2:
                                            cat_perf2 = "Dames"
                                        elif "Messieurs" in event_label2:
                                            cat_perf2 = "Messieurs"
            
                                    if cat_perf2 == "Dames":
                                        performances_dames.append(new_perf)
                                    elif cat_perf2 == "Messieurs":
                                        performances_messieurs.append(new_perf)
                                    else:
                                        performances_neutres.append(new_perf)
            
                                base_name = _base_event_name(perfs, event_name)
            
                                if performances_dames:
                                    epreuve_d = {
                                        "nom": base_name,
                                        "categorie": "Dames",
                                        "tour": "",
                                        "performances": performances_dames,
                                    }
                                    epreuves.append(epreuve_d)
            
                                if performances_messieurs:
                                    epreuve_m = {
                                        "nom": base_name,
                                        "categorie": "Messieurs",
                                        "tour": "",
                                        "performances": performances_messieurs,
                                    }
                                    epreuves.append(epreuve_m)
            
                                if not performances_dames and not performances_messieurs and performances_neutres:
                                    epreuve_n = {
                                        "nom": base_name,
                                        "categorie": default_categorie or "",
                                        "tour": "",
                                        "performances": performances_neutres,
                                    }
                                    epreuves.append(epreuve_n)
            
                            return epreuves
                        
                        if isinstance(results, dict):
                            _normalize_event_fields(results)
                            comp["epreuves"] = _results_to_epreuves(
                                results, default_categorie=comp.get("filter")
                            )
                            total_perfs = 0
                            for epreuve in comp.get("epreuves", []):
                                perfs = epreuve.get("performances", [])
                                if isinstance(perfs, list):
                                    total_perfs += len(perfs)
                            if total_perfs > 0:
                                comp["results_count"] = total_perfs
            
                        comp.pop("results", None)
                        epreuves_all = comp.get("epreuves", []) or []
                        epreuves_dames = [
                            e for e in epreuves_all if e.get("categorie") == "Dames"
                        ]
                        epreuves_messieurs = [
                            e for e in epreuves_all if e.get("categorie") == "Messieurs"
                        ]
            
                        def _write_gender_file(
                            gender_label: str, epreuves_list: List[Dict]
                        ) -> None:
                            """Écrit un fichier JSON de compétition filtré par genre.

                            Args:
                                gender_label (str): Libellé de filtre (ex. « Dames », « Messieurs »).
                                epreuves_list (List[Dict]): Épreuves à inclure dans le fichier.

                            Returns:
                                None
                            """
                            if not epreuves_list:
                                return
            
                            comp_gender = {
                                k: v
                                for k, v in comp.items()
                                if k not in ("epreuves", "filter", "results_count")
                            }
                            comp_gender["filter"] = gender_label
                            comp_gender["epreuves"] = epreuves_list
            
                            # Recalculer results_count pour ce genre uniquement
                            total_perfs_gender = 0
                            for epreuve in epreuves_list:
                                perfs = epreuve.get("performances", [])
                                if isinstance(perfs, list):
                                    total_perfs_gender += len(perfs)
                            comp_gender["results_count"] = total_perfs_gender
            
                            comp_gender["name"] = f"{safe_base}-{gender_label}"
                            comp_filename = f"{safe_base}-{gender_label}.json"
                            comp_path = os.path.join(type_dir, comp_filename)
                            with open(comp_path, "w", encoding="utf-8") as f:
                                json.dump(comp_gender, f, ensure_ascii=False, indent=2)
                            # Sauvegarder le chemin du fichier de résultats
                            competitions_files.append(comp_path)
            
                        # Écrire les fichiers filtrés par genre (s'il y a des épreuves)
                        _write_gender_file("Dames", epreuves_dames)
                        _write_gender_file("Messieurs", epreuves_messieurs)
            
                # Générer le résumé des erreurs (dans le dossier Resumes)
                resume_data = generate_resume(
                    data,
                    output_dir=resumes_dir,
                    idtyp=idtyp,
                    type_name=type_name
                )
                
                # Générer le nom de fichier de résumé basé sur le type
                def _type_name_to_filename(tn: str) -> str:
                    """Convertit un nom de type de compétition en nom de fichier sûr.

                    Args:
                        tn (str): Nom du type de compétition Extranat.

                    Returns:
                        str: Identifiant de fichier normalisé (minuscules, underscores).
                    """
                    import re
                    if not tn:
                        return "resume_type_inconnu"
                    fn = tn.lower()
                    fn = re.sub(r'[^\w\s-]', '', fn)
                    fn = re.sub(r'[-\s]+', '_', fn)
                    fn = fn.strip('_')
                    forbidden = '\\/:*?"<>|'
                    fn = "".join(("_" if ch in forbidden else ch) for ch in fn)
                    return f"resume_{fn}"
                
                resume_filename = _type_name_to_filename(type_name)
                
                print("\n" + "-" * 60)
                print(f"RÉSUMÉ ({type_name})")
                print("-" * 60)
                print(f"- Compétitions : {total_competitions}")
                print(f"- Résultats    : {total_results}")
                print(f"- Erreurs      : {total_errors}")
                error_pct = resume_data["par_type"][0]["error_percentage"] if resume_data["par_type"] else "0.0%"
                print(f"- Taux d'erreur : {error_pct}")
                print(f"- Dossier type : {type_dir}")
                print(f"- Fichier résumé (type) : {os.path.join(resumes_dir, f'{resume_filename}.json')}")
                print(f"- Fichier résumé (global) : {os.path.join(resumes_dir, 'resume.json')}")
                print("-" * 60)
            
                # Si un intervalle de dates est utilisé, sauvegarder un fichier JSON
                # de résumé équivalent au bloc ci-dessus dans competitions_per_dates.
                if start_date is not None and end_date is not None:
                    start_str = start_date.strftime("%d/%m/%Y")
                    end_str = end_date.strftime("%d/%m/%Y")
                    # Exemple de nom : "Coupes Régionales 10_01_2026 12_01_2026.json"
                    base_label = f"{type_name} {start_str} {end_str}"
                    forbidden = '\\/:*?"<>|'
                    safe_name = "".join(
                        ("_" if ch in forbidden else ch) for ch in base_label
                    ).rstrip(" .")
                    if not safe_name:
                        safe_name = "resume_par_dates"
            
                    summary_payload = {
                        "type_name": type_name,
                        "idtyp": idtyp,
                        "date_debut": start_str,
                        "date_fin": end_str,
                        "total_competitions": total_competitions,
                        "total_results": total_results,
                        "total_errors": total_errors,
                        "error_percentage": error_pct,
                        "dossier_type": type_dir,
                        "fichier_resume_type": os.path.join(resumes_dir, f"{resume_filename}.json"),
                        "fichier_resume_global": os.path.join(resumes_dir, "resume.json"),
                        # Nouveau : liste de tous les fichiers de résultats JSON
                        # générés pour ces compétitions (chemins relatifs).
                        "fichiers_competitions": competitions_files,
                        # Nouveau : inclusion directe des compétitions avec leurs résultats
                        # dans le fichier de résumé par dates.
                        "competitions": competitions,
                    }
            
                    summary_path = os.path.join(dates_dir, f"{safe_name}.json")
                    with open(summary_path, "w", encoding="utf-8") as f:
                        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

        # On ne continue pas le main() après le mode "intl"
        return

    for raw_arg in raw_args:
        if any(ch.isdigit() for ch in raw_arg):
            try:
                parts = [p for p in raw_arg.split(",") if p.strip()]
                id_list = [int(p.strip()) for p in parts]
                only_idtyps = id_list
                break
            except ValueError:
                continue

    if debug:
        print(f"Options : delay_between_comps={delay_between_comps}, only_idtyps={only_idtyps}")

    data = get_all_results_by_type(
        delay_between_comps=delay_between_comps,
        debug=debug,
        only_idtyps=only_idtyps,
    )

    filename = os.path.join(output_dir, "results_by_type.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total_types = len(data.get("types", []))
    total_competitions = sum(
        len(t.get("competitions", [])) for t in data.get("types", [])
    )
    total_results = sum(
        sum(c.get("results_count", 0) for c in t.get("competitions", []))
        for t in data.get("types", [])
    )
    total_errors = sum(
        sum(1 for c in t.get("competitions", []) if "error" in c)
        for t in data.get("types", [])
    )

    # Le résumé des erreurs (dans le dossier Resumes)
    resume_data = generate_resume(data, output_dir=resumes_dir)
    
    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print(f"- Types de compétitions : {total_types}")
    print(f"- Compétitions          : {total_competitions}")
    print(f"- Résultats             : {total_results}")
    print(f"- Erreurs               : {total_errors}")
    global_error_pct = resume_data["resume"]["global_error_percentage"]
    print(f"- Taux d'erreur global  : {global_error_pct}")
    print(f"- Fichier               : {filename}")
    print(f"- Fichier résumé (global) : {os.path.join(resumes_dir, 'resume.json')}")
    print(f"- Fichiers résumé (par type) : {total_types} fichier(s) resume_*.json")

if __name__ == "__main__":
    main()

