import html as html_module
import json, os
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import re as re_module
from get_data import (http_get_with_retries, get_competition_data)
import time, requests
from urllib.parse import urljoin
import sys
from datetime import datetime, date
import re

BASE_URL = "https://ffn.extranat.fr/webffn/"
COMPETITIONS_PATH = "competitions.php?idact=nat"
INTERNATIONALS_URL = ("https://ffn.extranat.fr/webffn/competitions.php?idact=nat&idsai=&idreg=&idtyp=7")


# Construction de l'URL de la page des compétitions FFN pour un type donné (idtyp).
def get_competitions_url_by_idtyp(idtyp: int) -> str:
    return f"{BASE_URL}competitions.php?idact=nat&idsai=&idreg=&idtyp={idtyp}"


# Récupèration de la liste des types de compétition depuis la page FFN 
def get_competition_types(base_url: str = BASE_URL, path: str = COMPETITIONS_PATH, debug: bool = False) -> List[Dict]:
    url = f"{base_url}{path}"
    if debug:
        print(f"Récupération des types de compétitions depuis : {url}")
    try:
        resp = http_get_with_retries(url, debug=debug)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(" x 403 Forbidden sur la page des compétitions ")
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


# Récupèration de la liste des compétitions pour une URL donnée
def get_competitions_for_url(url: str, debug: bool = False) -> List[Dict]:
    competitions: List[Dict] = []
    if debug:
        print(f"Récupération des compétitions (avec pagination) depuis : {url}")

    from urllib.parse import urljoin, urlparse, parse_qs
    start_url = url
    parsed_start = urlparse(start_url)
    start_qs = parse_qs(parsed_start.query)

    def _same_filter(list_url: str) -> bool:
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


# Pour chaque type de compétition, récupère les compétitions puis les résultats de chaque compétition (via get_competition_data) 
def get_all_results_by_type(base_url: str = BASE_URL, path: str = COMPETITIONS_PATH, delay_between_comps: float = 1.0, debug: bool = False, only_idtyps: Optional[List[int]] = None) -> Dict:
    types = get_competition_types(base_url=base_url, path=path, debug=debug)
    data: Dict = {"types": []}

    if not types:
        return data

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


# Parse le HTML (soup) des pages « filtre » : extrait les épreuves et leurs performances (nom épreuve, catégorie, nageurs, temps, splits, etc.) depuis les tables.
def extract_results_from_filter_table(soup: BeautifulSoup, debug: bool = False) -> List[Dict]:
    epreuves: List[Dict] = []
    current_epreuve: Optional[Dict] = None
    last_performance: Optional[Dict] = None  
    tables = soup.find_all("table")

    def parse_event_header(header_text: str) -> Dict:
        text = " ".join(header_text.split())
        nom = text
        categorie = ""
        tour = ""

        if " - " in text:
            left, right = text.split(" - ", 1)
            tour = right.strip()
        else:
            left = text

        m_gender = re_module.search(r"\b(Dames|Messieurs)\b", left)
        if m_gender:
            categorie = m_gender.group(1)
            nom = left[: m_gender.start()].strip()
        else:
            parts = left.rsplit(" ", 1)
            if len(parts) == 2:
                nom_part, cat_part = parts
                nom = nom_part.strip()
                categorie = cat_part.strip()
            else:
                nom = left.strip()

        return {"nom": nom, "categorie": categorie, "tour": tour}

    def parse_swimmer(swimmer_text: str, categorie: str) -> Dict:
        """
        Parse un texte du type :
          "TARTAGLIONE Jade (2014/11 ans)FRA"
        en structure nageur.
        """
        txt = " ".join(swimmer_text.split())
        pattern = (
            r"^(?P<nom>[A-ZÉÈÊÀÂÄÔÖÛÜÎÏÇ' \-]+)\s+"
            r"(?P<prenom>.+?)\s*"
            r"\((?P<annee>\d{4})/(?P<age>\d+)\s*ans\)"
            r"(?P<nationalite>[A-Z]{3})?$"
        )
        m = re_module.match(pattern, txt)
        sexe = None
        if categorie == "Dames":
            sexe = "F"
        elif categorie == "Messieurs":
            sexe = "M"

        # On ne garde dans la sortie finale qu'une propriété "name"
        nageur: Dict = {
            "name": txt,  
            "sexe": sexe,
            "annee_naissance": None,
            "age": None,
            "nationalite": None,
        }

        if m:
            nom = m.group("nom").strip()
            prenom = m.group("prenom").strip()
            nageur["name"] = f"{nom} {prenom}".strip()
            try:
                nageur["annee_naissance"] = int(m.group("annee"))
            except (TypeError, ValueError):
                nageur["annee_naissance"] = None
            try:
                nageur["age"] = int(m.group("age"))
            except (TypeError, ValueError):
                nageur["age"] = None
            nat = m.group("nationalite")
            nageur["nationalite"] = nat.strip() if nat else None

        return nageur

    for table in tables:
        # On parcourt TOUTES les lignes dans l'ordre, pour pouvoir détecter les en-têtes d'épreuves 
        rows = table.find_all("tr")

        for row in rows:
            cells = row.find_all("td")
            if not cells:
                continue

            # Détection d'un en-tête d'épreuve
            header_cell = None
            if len(cells) == 1:
                header_cell = cells[0]
            else:
                # Chercher une cellule avec un colspan élevé (>= 6, souvent 8)
                for c in cells:
                    try:
                        colspan = int(c.get("colspan", "1"))
                    except ValueError:
                        colspan = 1
                    if colspan >= 6:
                        header_cell = c
                        break

            if header_cell is not None:
                cell_classes = header_cell.get("class", [])
                is_info_cell = any(
                    cls in ["text-gray-500", "italic", "text-xs"] 
                    for cls in cell_classes
                )
                
                divs = header_cell.find_all("div")
                if divs:
                    header_text = divs[0].get_text(strip=True)
                else:
                    header_text = header_cell.get_text(strip=True)

                if header_text:
                    text_trimmed = header_text.strip()
                    is_region_info = (
                        (text_trimmed.startswith("(") and text_trimmed.endswith(")")) or
                        (text_trimmed.startswith("(") and "/" in text_trimmed) or
                        ("CAF" in text_trimmed and "/" in text_trimmed)
                    )
                    
                    is_real_event = any(
                        keyword in text_trimmed.upper() 
                        for keyword in [
                            "NAGE LIBRE", "DOS", "BRASSE", "PAPILLON", 
                            "4 NAGES", "RELAIS", "MÉDAILLE", "FINAL", "SÉRIE"
                        ]
                    ) or any(char.isdigit() for char in text_trimmed)
                    
                    if (is_info_cell or is_region_info) and not is_real_event:
                        continue  
                    
                    header_info = parse_event_header(header_text)
                    current_epreuve = {
                        "nom": header_info["nom"],
                        "categorie": header_info["categorie"],
                        "tour": header_info["tour"],
                        "performances": [],
                    }
                    epreuves.append(current_epreuve)
                    last_performance = None  
                continue

            if len(cells) < 4:
                continue

            if current_epreuve is None:
                continue

            rank_cell = cells[0]
            rank = rank_cell.get_text(strip=True)
            
            # Vérifier si cette ligne a un classement valide
            has_ranking = False
            classement: Optional[int] = None
            if rank:
                m_rank = re_module.search(r"(\d+)", rank)
                if m_rank:
                    try:
                        classement = int(m_rank.group(1))
                        has_ranking = True
                    except ValueError:
                        pass

            # Nageur (2ème colonne)
            swimmer_cell = cells[1]
            swimmer_link = swimmer_cell.find("a")
            swimmer_name = (
                swimmer_link.get_text(strip=True)
                if swimmer_link
                else swimmer_cell.get_text(strip=True)
            )
            swimmer_name = " ".join(swimmer_name.split())

            # Club (3ème colonne)
            club_cell = cells[2]
            club_link = club_cell.find("a")
            club_name = (
                club_link.get_text(strip=True)
                if club_link
                else club_cell.get_text(strip=True)
            )

            # Temps (4ème colonne)
            time_cell = cells[3]
            time = time_cell.get_text(strip=True)

            # Points (6ème colonne si disponible)
            points = ""
            if len(cells) >= 6:
                points_cell = cells[5]
                points = points_cell.get_text(strip=True)

            # MPP (7ème colonne si disponible)
            mpp_info = ""
            if len(cells) >= 7:
                mpp_cell = cells[6]
                mpp_button = mpp_cell.find("button")
                if mpp_button and mpp_button.get("data-tippy-content"):
                    mpp_info = mpp_button.get("data-tippy-content", "")
                    # Nettoyage du HTML
                    mpp_info = (
                        mpp_info.replace("&lt;b&gt;", "")
                        .replace("&lt;/b&gt;", "")
                        .replace("<b>", "")
                        .replace("</b>", "")
                    )

            # Extraire les temps de passage (splits) 
            splits: List[Dict] = []
            tippy_button = time_cell.find("button", class_="tippy-button")
            if tippy_button:
                tippy_content = tippy_button.get("data-tippy-content", "")
                if tippy_content and "styleNoBorderNoBottom" in tippy_content:
                    try:
                        # Décoder le HTML échappé (ex: &lt; → <)
                        decoded = html_module.unescape(tippy_content)
                        tip_soup = BeautifulSoup(decoded, "html.parser")
                        table = tip_soup.find("table", id="styleNoBorderNoBottom")
                        if table:
                            for tr in table.find_all("tr"):
                                tds = tr.find_all("td")
                                if len(tds) >= 4:
                                    # td[0]: "50 m : " (text-lime-600), td[1]: cumul (green),
                                    # td[2]: (00:36.87) (red), td[3]: [00:36.87] (purple)
                                    dist_text = tds[0].get_text(strip=True).rstrip(" :").strip()
                                    cumul = tds[1].get_text(strip=True)
                                    split_parens = tds[2].get_text(strip=True).strip("()")
                                    split_brackets = tds[3].get_text(strip=True).strip("[]")
                                    splits.append({
                                        "distance": dist_text,
                                        "cumul": cumul,
                                        "split": split_parens or split_brackets,
                                    })
                    except Exception:
                        pass
            if not splits:
                split_links = time_cell.find_all("a", class_="text-blue-600")
                for split_link in split_links:
                    split_time = split_link.get_text(strip=True)
                    if split_time:
                        split_info: Dict = {"time": split_time}
                        if split_link.get("title"):
                            split_info["distance"] = split_link.get("title")
                        elif split_link.get("data-distance"):
                            split_info["distance"] = split_link.get("data-distance")
                        elif split_link.get("data-tippy-content"):
                            tippy_content = split_link.get("data-tippy-content", "")
                            distance_match = re_module.search(
                                r"(\d+)\s*m", tippy_content, re_module.IGNORECASE
                            )
                            if distance_match:
                                split_info["distance"] = distance_match.group(1) + "m"
                        splits.append(split_info)

            # Si cette ligne n'a pas de classement ET qu'il y a une performance précédente,
            # alors on ajoute ce nageur à la liste des nageurs de la performance précédente - Relais -
            if not has_ranking and last_performance is not None and swimmer_name:
                nageur = parse_swimmer(
                    swimmer_name, current_epreuve.get("categorie", "")
                )
                
                # Convertir nageur en liste si ce n'est pas déjà une liste
                if isinstance(last_performance.get("nageur"), dict):
                    last_performance["nageur"] = [last_performance["nageur"]]
                elif not isinstance(last_performance.get("nageur"), list):
                    last_performance["nageur"] = []
                
                # Ajouter le nouveau nageur à la liste
                last_performance["nageur"].append(nageur)
                continue  # pour passer à la ligne suivante sans créer de nouvelle performance

            # Sinon, créer une nouvelle performance normalement
            if swimmer_name and (time or has_ranking):
                points_val: Optional[int] = None
                if points:
                    m_pts = re_module.search(r"(\d+)", points)
                    if m_pts:
                        try:
                            points_val = int(m_pts.group(1))
                        except ValueError:
                            points_val = None

                nageur = parse_swimmer(
                    swimmer_name, current_epreuve.get("categorie", "")
                )

                perf: Dict = {
                    "classement": classement,
                    "nageur": nageur,
                    "club": club_name if club_name else None,
                    "temps": time if time else None,
                }
                if points_val is not None:
                    perf["points"] = points_val
                if mpp_info:
                    perf["mpp"] = mpp_info
                if splits:
                    perf["splits"] = splits

                current_epreuve["performances"].append(perf)
                last_performance = perf  

    return epreuves


# LA récupèration de toutes les compétitions listées sur l'URL (ex. internationales idtyp=7), charge chaque page compétition, récupère les résultats par épreuve et gère les pauses session.
def get_results_for_competitions_url(url: str, delay_between_comps: float = 1.0, debug: bool = False, max_competitions_before_pause: int = 50, rest_delay: float = 30.0) -> Dict:
    def get_competition_results_grouped_by_event(comp_url: str, debug: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Pour une URL de compétition donnée, récupère la liste de toutes les
        épreuves disponibles dans le formulaire <form name="choix"> (Épreuves
        Dames, Messieurs, Relais, etc.), puis scrape chaque URL d'épreuve
        (50 Nage Libre, 50 Dos, ...) et classe les résultats par nom d'épreuve.
        """
        grouped_results: Dict[str, List[Dict]] = {}

        nonlocal requests_since_session

        # 1) Charger la page principale de la compétition (avec le formulaire)
        if debug:
            print(f"    [grouped] Chargement page principale : {comp_url}")

        resp = http_get_with_retries(comp_url, debug=debug, max_retries=5, session=session, retry_forever=False )
        requests_since_session += 1
        soup = BeautifulSoup(resp.content, "html.parser")

        # 1.a) TENTE D'ABORD de lire directement les <select> d'épreuves dans le bloc
        #      <div class="mb-3"> qui contient "Épreuves Dames/Messieurs" et "Relais ...".
        #      Cela permet de couvrir les compétitions où il n'y a pas de liens idsex=
        #      mais uniquement ces selects.
        def _scrape_events_from_selects(
            select_elements, gender_label: str
        ) -> List[Dict]:
            all_epreuves: List[Dict] = []
            nonlocal requests_since_session
            from urllib.parse import urljoin as _urljoin_local

            for sel in select_elements:
                for opt in sel.find_all("option"):
                    value = opt.get("value", "").strip()
                    label_opt = opt.get_text(strip=True)

                    if not value or not label_opt:
                        continue
                    if "Épreuves" in label_opt or "Relais" in label_opt:
                        continue

                    if debug:
                        print(
                            f"        [grouped] ({gender_label}) épreuve '{label_opt}' → {value}"
                        )

                    event_url = _urljoin_local(BASE_URL, value)
                    try:
                        event_resp = http_get_with_retries(
                            event_url,
                            debug=debug,
                            max_retries=5,
                            session=session,
                            retry_forever=False,
                        )
                        requests_since_session += 1
                        event_soup = BeautifulSoup(event_resp.content, "html.parser")
                        epreuves_event = extract_results_from_filter_table(
                            event_soup, debug=debug
                        )
                        if epreuves_event:
                            all_epreuves.extend(epreuves_event)
                        else:
                            all_epreuves.append(
                                {
                                    "nom": label_opt,
                                    "categorie": gender_label,
                                    "tour": "",
                                    "performances": [],
                                }
                            )
                    except Exception as e:
                        if debug:
                            print(
                                f"        ✗ Erreur lors du scraping de l'épreuve '{label_opt}' ({gender_label}) : {e}"
                            )
                        all_epreuves.append(
                            {
                                "nom": label_opt,
                                "categorie": gender_label,
                                "tour": "",
                                "performances": [],
                            }
                        )

            return all_epreuves

        # Cherche tous les <select> et regroupe ceux qui concernent Dames/Messieurs
        all_selects = soup.find_all("select")
        selects_dames = []
        selects_messieurs = []
        for sel in all_selects:
            opts = sel.find_all("option")
            if not opts:
                continue
            first_label = opts[0].get_text(strip=True)
            if "Dames" in first_label:
                selects_dames.append(sel)
            elif "Messieurs" in first_label:
                selects_messieurs.append(sel)

        used_direct_selects = False
        if selects_dames or selects_messieurs:
            if debug:
                print(
                    f"    [grouped] Selects trouvés dans le bloc filtres : "
                    f"{len(selects_dames)} pour Dames, {len(selects_messieurs)} pour Messieurs"
                )
            if selects_dames:
                grouped_results["Dames"] = _scrape_events_from_selects(
                    selects_dames, "Dames"
                )
            if selects_messieurs:
                grouped_results["Messieurs"] = _scrape_events_from_selects(
                    selects_messieurs, "Messieurs"
                )

            if grouped_results:
                return grouped_results

        # 1.b) Si on n'a pas pu utiliser les selects, on retombe sur l'ancien comportement
        form = soup.find("form", attrs={"name": "choix"})
        if not form:
            # Pas de formulaire : fallback, on scrape simplement la page
            if debug:
                print("    [grouped] Formulaire 'choix' non trouvé, fallback simple.")
            try:
                simple_results = get_competition_data(
                    comp_url, debug=debug, session=session, retry_forever=False
                )
                requests_since_session += 1
                if simple_results:
                    grouped_results["default"] = simple_results
                else:
                    grouped_results["_info"] = "Formulaire non trouvé et aucun résultat sur la page principale"
            except Exception as e:
                if debug:
                    print(f"    [grouped] Erreur lors du fallback : {e}")
                grouped_results["_error"] = f"Formulaire non trouvé et erreur lors du scraping : {str(e)}"
            return grouped_results

        # 2) Vérification s'il y a des filtres (Dames, Messieurs) dans le formulaire
        filter_links = form.find_all("a", href=True)
        filter_links_valid = []
        for link in filter_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            # Recherche des liens de filtre (Dames, Messieurs) qui contiennent idsex=
            if "idsex=" in href and text in ["Dames", "Messieurs"]:
                filter_links_valid.append({
                    "label": text,
                    "url": urljoin(BASE_URL, href)
                })
        
        # Si on a trouvé des filtres, scraper les résultats pour chaque filtre
        # en utilisant également le formulaire AU-DESSUS de la section "Filtres"
        # (selects des épreuves / relais) pour parcourir toutes les combinaisons.
        if filter_links_valid:
            if debug:
                print(f"    [grouped] {len(filter_links_valid)} filtre(s) trouvé(s) : {[f['label'] for f in filter_links_valid]}")
            
            for filter_info in filter_links_valid:
                filter_label = filter_info["label"]
                filter_url = filter_info["url"]
                
                if debug:
                    print(f"    [grouped] Scraping filtre '{filter_label}' → {filter_url}")
                
                try:
                    filter_resp = http_get_with_retries(
                        filter_url,
                        debug=debug,
                        max_retries=5,
                        session=session,
                        retry_forever=False,
                    )
                    requests_since_session += 1
                    filter_soup = BeautifulSoup(filter_resp.content, "html.parser")

                    # TENTER D'ABORD de parcourir les <select> d'épreuves visibles
                    # dans la zone de filtres (Épreuves Dames/Messieurs, Relais, etc.),
                    # sans dépendre strictement du <form name="choix">.
                    all_epreuves_for_filter: List[Dict] = []

                    # Sélectionner les <select> pertinents en fonction du filtre courant.
                    selects_candidates = filter_soup.find_all("select")
                    selects_in_filter: List = []
                    for sel in selects_candidates:
                        opts = sel.find_all("option")
                        if not opts:
                            continue
                        first_label = opts[0].get_text(strip=True)
                        # Rendre la détection plus tolérante : on regarde
                        # simplement si le libellé contient "Dames" ou "Messieurs".
                        if filter_label == "Dames" and "Dames" in first_label:
                            selects_in_filter.append(sel)
                        elif filter_label == "Messieurs" and "Messieurs" in first_label:
                            selects_in_filter.append(sel)

                    if debug:
                        print(
                            f"        [grouped] {len(selects_in_filter)} select(s) "
                            f"d'épreuves trouvée(s) pour le filtre '{filter_label}'."
                        )

                        events_for_filter = 0
                        for sel in selects_in_filter:
                            for opt in sel.find_all("option"):
                                value = opt.get("value", "").strip()
                                label_opt = opt.get_text(strip=True)

                                if not value or not label_opt:
                                    continue
                                if (
                                    "Épreuves" in label_opt
                                    or "Relais" in label_opt
                                    or "Affichage par séries" in label_opt
                                ):
                                    continue

                                events_for_filter += 1
                                event_url = urljoin(BASE_URL, value)

                                if debug:
                                    print(
                                        f"        [grouped] Filtre '{filter_label}' → "
                                        f"épreuve '{label_opt}' → {event_url}"
                                    )

                                try:
                                    event_resp = http_get_with_retries(
                                        event_url,
                                        debug=debug,
                                        max_retries=5,
                                        session=session,
                                        retry_forever=False,
                                    )
                                    requests_since_session += 1
                                    event_soup = BeautifulSoup(
                                        event_resp.content, "html.parser"
                                    )
                                    epreuves_event = extract_results_from_filter_table(
                                        event_soup, debug=debug
                                    )
                                    if epreuves_event:
                                        all_epreuves_for_filter.extend(epreuves_event)
                                    else:
                                        all_epreuves_for_filter.append(
                                            {
                                                "nom": label_opt,
                                                "categorie": filter_label,
                                                "tour": "",
                                                "performances": [],
                                            }
                                        )
                                except Exception as e:
                                    if debug:
                                        print(
                                            f"        ✗ Erreur lors du scraping de "
                                            f"l'épreuve '{label_opt}' pour le filtre "
                                            f"'{filter_label}' : {e}"
                                        )

                        # Si on a effectivement trouvé des épreuves via le formulaire,
                        # on les utilise comme résultat principal pour ce filtre.
                        if events_for_filter > 0 and all_epreuves_for_filter:
                            grouped_results[filter_label] = all_epreuves_for_filter
                        else:
                            filter_results = extract_results_from_filter_table(
                                filter_soup, debug=debug
                            )
                            grouped_results[filter_label] = filter_results
                    else:
                        # Aucun formulaire trouvé sur la page filtrée :
                        filter_results = extract_results_from_filter_table(
                            filter_soup, debug=debug
                        )
                    grouped_results[filter_label] = filter_results
                    
                    if debug:
                        nb = len(grouped_results.get(filter_label, []))
                        print(f"        → {nb} résultat(s) (épreuves) pour '{filter_label}'")
                except Exception as e:
                    if debug:
                        print(f"        ✗ Erreur lors du scraping du filtre '{filter_label}' : {e}")
                    grouped_results[filter_label] = []
            
            # Si on a trouvé des filtres, on retourne les résultats groupés par filtre
            if len(grouped_results) > 0:
                return grouped_results

        # 3) Sinon, récupérer toutes les selects d'épreuves dans le formulaire (ancien comportement)
        selects = form.find_all("select")
        if debug:
            print(f"    [grouped] {len(selects)} select(s) trouvée(s) dans le formulaire.")

        events_found = 0
        for select in selects:
            for opt in select.find_all("option"):
                value = opt.get("value", "").strip()
                label = opt.get_text(strip=True)

                if not value or not label:
                    continue
                if (
                    "Épreuves" in label
                    or "Relais" in label
                    or "Affichage par séries" in label
                ):
                    continue

                events_found += 1
                event_name = label  
                event_url = urljoin(BASE_URL, value)

                if debug:
                    print(f"    [grouped] Épreuve détectée : '{event_name}' → {event_url}")

                try:
                    
                    event_results = get_competition_data(
                        event_url,
                        debug=False,
                        session=session,
                        retry_forever=False,
                    )
                    requests_since_session += 1
                    grouped_results[event_name] = event_results
                    if debug:
                        print(
                            f"        → {len(event_results)} résultat(s) pour '{event_name}'"
                        )
                except Exception as e:
                    if debug:
                        print(
                            f"        ✗ Erreur lors du scraping de '{event_name}' ({event_url}) : {e}"
                        )
                    grouped_results[event_name] = []

        if events_found == 0 and len(grouped_results) == 0:
            grouped_results["_info"] = f"Formulaire trouvé avec {len(selects)} select(s) mais aucune épreuve valide détectée"

        return grouped_results

    if debug:
        print(f"Récupération des compétitions (URL directe) : {url}")

    competitions = get_competitions_for_url(url, debug=debug)

    competitions_since_pause = 0
    requests_since_session = 0
    consecutive_403_count = 0
    recent_success_count = 0  
    competitions_since_new_session = 0 

    def create_new_session():
        """ pour créer une nouvelle session avec des headers réalistes"""
        import random
        new_session = requests.Session()
        chrome_version = f"Chrome/{random.randint(120, 130)}.0.{random.randint(1000, 9999)}.{random.randint(100, 999)}"
        new_session.headers.update({
            "User-Agent": (
                f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"{chrome_version} Safari/537.36"
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
        })
        return new_session

    # Créer une session HTTP initiale avec des headers réalistes
    session = create_new_session()
    # Seuil de requêtes "logiques" avant de renouveler la session
    max_requests_before_new_session = 50

    try:
        for idx, comp in enumerate(competitions, 1):
            comp_url = comp.get("url")
            if not comp_url:
                continue

            if debug:
                print(f"  [{idx}/{len(competitions)}] {comp.get('name', 'N/A')}")

            is_403 = False
            try:
                # Récupérer les résultats groupés par épreuve (50 NL, 50 Dos, ...)
                grouped = get_competition_results_grouped_by_event(
                    comp_url, debug=debug, session=session
                )
                comp["results"] = grouped
                # Compter le nombre total de lignes de résultats
                def _count_grouped_results(grouped_dict: Dict) -> int:
                    total = 0
                    for key, value in grouped_dict.items():
                        if isinstance(key, str) and key.startswith("_"):
                            continue
                        if not isinstance(value, list):
                            continue
                        if not value:
                            continue
                        if isinstance(value[0], dict) and "performances" in value[0]:
                            for epreuve in value:
                                if isinstance(epreuve, dict):
                                    perfs = epreuve.get("performances", [])
                                    if isinstance(perfs, list):
                                        total += len(perfs)
                        else:
                            total += len(value)
                    return total

                comp["results_count"] = _count_grouped_results(grouped)
                consecutive_403_count = 0  # Réinitialiser le compteur si succès
                recent_success_count = min(recent_success_count + 1, 10)  

                if debug:
                    total_grouped = comp.get("results_count", 0)
                    print(f"      → {total_grouped} résultat(s) (toutes épreuves confondues)")
            except Exception as e:
                comp["results"] = []
                comp["results_count"] = 0
                comp["error"] = str(e)
                # Vérifier si c'est un 403
                if "403" in str(e) or "Status 403" in str(e):
                    is_403 = True
                    consecutive_403_count += 1
                    # Décrémenter le compteur de succès récents (mais pas en dessous de 0)
                    recent_success_count = max(recent_success_count - 1, 0)
                else:
                    consecutive_403_count = 0  # Réinitialiser si ce n'est pas un 403
                if debug:
                    print(f"      ✗ Erreur lors de la récupération : {e}")

            competitions_since_pause += 1
            competitions_since_new_session += 1

            # Si les 3 premières compétitions après une nouvelle session échouent toutes avec 403,
            # ce sont probablement des compétitions bloquées en permanence, pas un problème de session
            if competitions_since_new_session <= 3 and is_403:
                if debug and competitions_since_new_session == 3:
                    print(
                        f"      x Les 3 premières compétitions après la nouvelle session ont échoué avec 403. "
                        f"Ce sont probablement des compétitions bloquées en permanence."
                    )
            if consecutive_403_count >= 5 and recent_success_count > 0 and competitions_since_new_session > 5:
                if debug:
                    print(
                        f"      x {consecutive_403_count} erreurs 403 consécutives détectées "
                        f"(après {recent_success_count} succès récents). "
                        f"Création d'une nouvelle session (rate-limiting probable)..."
                    )
                session.close()
                if rest_delay > 0:
                    time.sleep(rest_delay * 2)  # Pause double pour laisser le serveur se reposer
                session = create_new_session()
                consecutive_403_count = 0
                competitions_since_pause = 0
                competitions_since_new_session = 0  # Réinitialiser le compteur depuis la nouvelle session
                recent_success_count = 0  # Réinitialiser aussi le compteur de succès
                continue 
            elif consecutive_403_count >= 5 and recent_success_count == 0:
                if debug:
                    print(
                        f"      x {consecutive_403_count} erreurs 403 consécutives détectées "
                        f"(aucun succès récent). Ces compétitions semblent bloquées en permanence. "
                        f"On continue sans créer de nouvelle session..."
                    )
                consecutive_403_count = 0

            # Pause courte éventuelle entre compétitions (optionnelle)
            if delay_between_comps > 0 and idx < len(competitions):
                time.sleep(delay_between_comps)

            # Créer une nouvelle session après chaque batch de compétitions
            if max_competitions_before_pause > 0 and competitions_since_pause >= max_competitions_before_pause:
                if debug:
                    print(
                        f"      Création d'une nouvelle session HTTP après {competitions_since_pause} compétition(s) "
                        f"({competitions_since_pause} requêtes HTTP)..."
                    )
                # Fermer l'ancienne session
                session.close()
                # Pause avant de créer la nouvelle session pour laisser le serveur se reposer
                if rest_delay > 0:
                    if debug:
                        print(f"      Pause de {rest_delay}s avant la nouvelle session...")
                    time.sleep(rest_delay)
                # Créer une nouvelle session
                session = create_new_session()
                competitions_since_pause = 0
                competitions_since_new_session = 0  # Réinitialiser le compteur depuis la nouvelle session
                consecutive_403_count = 0  # Réinitialiser aussi le compteur de 403
                recent_success_count = 0  # Réinitialiser le compteur de succès

            # Créer une nouvelle session après un certain nombre de requêtes logiques
            if (
                max_requests_before_new_session > 0
                and requests_since_session >= max_requests_before_new_session
            ):
                if debug:
                    print(
                        f"      Création d'une nouvelle session HTTP après "
                        f"{requests_since_session} requête(s) de résultats..."
                    )
                session.close()
                if rest_delay > 0:
                    if debug:
                        print(f"      Pause de {rest_delay}s avant la nouvelle session (requêtes)...")
                    time.sleep(rest_delay)
                session = create_new_session()
                requests_since_session = 0
    finally:
        # Fermer la session à la fin
        session.close()

    return {"url": url, "competitions": competitions}


# Raccourci : récupère les compétitions « Compétitions internationales » (idtyp=7) et leurs résultats.
def get_international_results(delay_between_comps: float = 1.0,debug: bool = False) -> Dict:
    return get_results_for_competitions_url(
        INTERNATIONALS_URL,
        delay_between_comps=delay_between_comps,
        debug=debug,
    )


# Récupère uniquement la liste des compétitions internationales (idtyp=7), sans résultats détaillés.
def get_international_competitions_list(debug: bool = False) -> Dict:
    if debug:
        print(
            "Récupération de la liste des compétitions pour "
            '"Compétitions internationales" (idtyp=7)'
        )
    competitions = get_competitions_for_url(INTERNATIONALS_URL, debug=debug)
    return {"url": INTERNATIONALS_URL, "competitions": competitions}


# Génère un résumé des erreurs de collecte (par type et global)
def generate_resume(
    data: Dict,
    output_dir: str = "competitions_per_type",
    idtyp: Optional[int] = None,
    type_name: Optional[str] = None,
) -> Dict:
    resume: Dict = {
        "resume": {},
        "par_type": []
    }
    
    # Noms des types de compétitions
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
        if not type_name:
            return "resume_type_inconnu"
        
        filename = type_name.lower()
        
        filename = re.sub(r'[^\w\s-]', '', filename)  # Supprimer caractères spéciaux
        filename = re.sub(r'[-\s]+', '_', filename)  # Remplacer espaces et tirets par underscore
        filename = filename.strip('_')  # Supprimer underscores en début/fin
        
        # Nettoyer les caractères interdits 
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
    
    # Sauvegarder aussi le résumé global 
    resume_path = os.path.join(output_dir, "resume.json")
    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=2)
    
    return resume


# Point d'entrée CLI : scrape types/compétitions selon les arguments (debug, fast, intl, dates),
# sauvegarde les résultats et résumés dans les dossiers configurés.
def main():
    output_dir = "competitions_per_type"
    os.makedirs(output_dir, exist_ok=True)

    resumes_dir = "Resumes"
    os.makedirs(resumes_dir, exist_ok=True)

    dates_dir = "competitions_per_dates"
    os.makedirs(dates_dir, exist_ok=True)

    debug = False
    delay_between_comps = 0.0
    only_idtyps: Optional[List[int]] = None
    raw_args = sys.argv[1:]

    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Mode "année seule" : python get_data_deeper.py 2025
    # → on extrait toutes les compétitions dont la date est dans l'année 2025
    def _is_year_token(s: str) -> bool:
        if not s.isdigit() or len(s) != 4:
            return False
        y = int(s)
        return 1970 <= y <= 2030

    # Mode "deux dates" : python get_data_deeper.py 02/02/2025 10/10/2025
    def _parse_date_token(s: str) -> Optional[date]:
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

    if not raw_args:
        raw_args = [
            "intl",
            "1", "2", "3", "4", "5", "6", "7", "8",
            "12", "13", "14", "15",
            "debug",
        ]

    args = [a.lower() for a in raw_args]

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

        if not id_list:
            id_list = [7]

        # Noms des types de compétitions 
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

        for idtyp in id_list:
            type_name = type_names.get(idtyp, f"Type idtyp={idtyp}")
            
            print("*" * 60)
            print(f"RÉCUPÉRATION DES COMPÉTITIONS : {type_name} (idtyp={idtyp})")
            print("*" * 60)
            
            if debug:
                print(f"Options : delay_between_comps={delay_between_comps}")
            
            url = get_competitions_url_by_idtyp(idtyp)
            
            # Pour avoir la liste des compétitions (sans résultats), ajouter "list" dans les arguments
            if "list" in args:
                competitions = get_competitions_for_url(url, debug=debug)
                data = {"url": url, "competitions": competitions}
                filename = os.path.join(output_dir, f"competitions_idtyp_{idtyp}.json")
            
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            
                print("\n" + "*" * 60)
                print(f"RÉSUMÉ (liste des compétitions - {type_name})")
                print("*" * 60)
                print(f"- Compétitions : {len(competitions)}")
                print(f"- Fichier      : {filename}")
                print("*" * 60)
                continue
            else:
                data = get_results_for_competitions_url(
                    url,
                    delay_between_comps=delay_between_comps,
                    debug=debug,
                )
            
                competitions = data.get("competitions", [])
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
            
                folder_name = type_name.split(" (")[0] if type_name else f"type_{idtyp}"
                type_dir = os.path.join(output_dir, folder_name)
                os.makedirs(type_dir, exist_ok=True)
            
                # Pour éviter d'écraser des fichiers lorsque plusieurs compétitions
                # ont exactement le même nom, on garde en mémoire les bases déjà
                # utilisées et on ajoute un suffixe (ID ou compteur) en cas de
                # collision.
                used_bases: set[str] = set()
            
                competitions_files: List[str] = []
            
                for comp in competitions:
                    raw_name = comp.get("name", "competition_sans_nom")
            
                    name_for_file = raw_name.replace(" - ", "-").strip()
                    forbidden = '\\/:*?"<>|'
                    safe_base = "".join(
                        ("_" if ch in forbidden else ch) for ch in name_for_file
                    ).rstrip(" .")
            
                    if not safe_base:
                        safe_base = "competition_sans_nom"
            
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
                            if filter_name.startswith("_"):
                                continue
            
                            comp_filtered = {k: v for k, v in comp.items() if k != "results"}
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
                            competitions_files.append(comp_path)
                    else:
                        def _normalize_event_fields(results_dict: Dict):
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
                            epreuves: List[Dict] = []
            
                            def _base_event_name(perfs_list: List[Dict], fallback: str) -> str:
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
                            if not epreuves_list:
                                return
            
                            comp_gender = {
                                k: v
                                for k, v in comp.items()
                                if k not in ("epreuves", "filter", "results_count")
                            }
                            comp_gender["filter"] = gender_label
                            comp_gender["epreuves"] = epreuves_list
            
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
                            competitions_files.append(comp_path)
        
                        _write_gender_file("Dames", epreuves_dames)
                        _write_gender_file("Messieurs", epreuves_messieurs)
            
                # Générer le résumé des erreurs (dans le dossier Resumes)
                resume_data = generate_resume(
                    data,
                    output_dir=resumes_dir,
                    idtyp=idtyp,
                    type_name=type_name
                )
                
                def _type_name_to_filename(tn: str) -> str:
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
                
                print("\n" + "*" * 60)
                print(f"RÉSUMÉ ({type_name})")
                print("*" * 60)
                print(f"- Compétitions : {total_competitions}")
                print(f"- Résultats    : {total_results}")
                print(f"- Erreurs      : {total_errors}")
                error_pct = resume_data["par_type"][0]["error_percentage"] if resume_data["par_type"] else "0.0%"
                print(f"- Taux d'erreur : {error_pct}")
                print(f"- Dossier type : {type_dir}")
                print(f"- Fichier résumé (type) : {os.path.join(resumes_dir, f'{resume_filename}.json')}")
                print(f"- Fichier résumé (global) : {os.path.join(resumes_dir, 'resume.json')}")
                print("*" * 60)
            
                if start_date is not None and end_date is not None:
                    start_str = start_date.strftime("%d/%m/%Y")
                    end_str = end_date.strftime("%d/%m/%Y")
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
                        "fichiers_competitions": competitions_files,
                        "competitions": competitions,
                    }
            
                    summary_path = os.path.join(dates_dir, f"{safe_name}.json")
                    with open(summary_path, "w", encoding="utf-8") as f:
                        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

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
    
    print("\n" + "*" * 60)
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

