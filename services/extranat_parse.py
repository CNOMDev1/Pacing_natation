"""Parsing HTML des pages « filtre » Extranat (résultats par épreuve).

Extrait de ``extranat_service`` pour isoler le parsing pur des tables HTML
(épreuves, nageurs, temps, splits, MPP) sans dépendance réseau.
"""
from __future__ import annotations

import html as html_module
import re as re_module
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


def extract_results_from_filter_table(soup: BeautifulSoup, debug: bool = False) -> List[Dict]:
    """Parse les tables HTML « filtre » en épreuves et performances.

    Extrait nom d'épreuve, catégorie, tour, classement, nageur, club, temps,
    splits et points MPP depuis le HTML BeautifulSoup fourni.

    Args:
        soup (BeautifulSoup): Document HTML de la page résultats filtrée.
        debug (bool): Active les logs de parsing détaillés.

    Returns:
        List[Dict]: Liste d'épreuves, chacune contenant une liste ``performances``.
    """
    epreuves: List[Dict] = []
    current_epreuve: Optional[Dict] = None
    last_performance: Optional[Dict] = None
    tables = soup.find_all("table")

    def parse_event_header(header_text: str) -> Dict:
        """Découpe l'en-tête d'une épreuve en nom, catégorie et tour.

        Args:
            header_text (str): Texte brut de l'en-tête de table.

        Returns:
            Dict: Clés ``nom``, ``categorie`` (Dames/Messieurs) et ``tour``.
        """
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
        """Parse un texte nageur Extranat en structure normalisée.

        Exemple d'entrée : ``"TARTAGLIONE Jade (2014/11 ans)FRA"``.

        Args:
            swimmer_text (str): Texte brut de la cellule nageur.
            categorie (str): Catégorie d'épreuve (``Dames`` / ``Messieurs``).

        Returns:
            Dict: Clés ``name``, ``sexe``, ``annee_naissance``, ``age``,
                ``nationalite``.
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
        # (plus les méta-données), pas de "nom" / "prenom" séparés.
        nageur: Dict = {
            "name": txt,  # valeur par défaut : texte complet brut
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
        # On parcourt TOUTES les lignes dans l'ordre, pour pouvoir
        # détecter les en-têtes d'épreuves (td colspan="8" ...).
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
                # Vérifier si c'est une cellule informative (région, etc.) à ignorer
                # Ces cellules ont souvent des classes comme "text-gray-500", "italic", etc.
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

                # Ignorer les cellules qui contiennent uniquement des informations de région
                # Format typique : "(CAF - GRAND-EST / METZ)" ou similaire
                if header_text:
                    # Vérifier si le texte commence et se termine par des parenthèses
                    # et ne contient pas de nom d'épreuve typique
                    text_trimmed = header_text.strip()
                    is_region_info = (
                        (text_trimmed.startswith("(") and text_trimmed.endswith(")")) or
                        (text_trimmed.startswith("(") and "/" in text_trimmed) or
                        ("CAF" in text_trimmed and "/" in text_trimmed)
                    )

                    # Vérifier si c'est un vrai nom d'épreuve (contient des chiffres et des mots d'épreuve)
                    is_real_event = any(
                        keyword in text_trimmed.upper()
                        for keyword in [
                            "NAGE LIBRE", "DOS", "BRASSE", "PAPILLON",
                            "4 NAGES", "RELAIS", "MÉDAILLE", "FINAL", "SÉRIE"
                        ]
                    ) or any(char.isdigit() for char in text_trimmed)

                    # Ignorer si c'est une cellule informative ET que ce n'est pas un vrai nom d'épreuve
                    if (is_info_cell or is_region_info) and not is_real_event:
                        continue  # Ignorer cette cellule, ce n'est pas une épreuve

                    header_info = parse_event_header(header_text)
                    current_epreuve = {
                        "nom": header_info["nom"],
                        "categorie": header_info["categorie"],
                        "tour": header_info["tour"],
                        "performances": [],
                    }
                    epreuves.append(current_epreuve)
                    last_performance = None  # Réinitialiser lors du changement d'épreuve
                continue

            # Lignes de résultats : au moins 4 cellules (rank, swimmer, club, time)
            if len(cells) < 4:
                continue

            # Si aucune épreuve courante n'a encore été détectée, on ignore
            # (normalement, les résultats suivent toujours un en-tête).
            if current_epreuve is None:
                continue

            # Classement (1ère colonne)
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
                    # Nettoyer le HTML
                    mpp_info = (
                        mpp_info.replace("&lt;b&gt;", "")
                        .replace("&lt;/b&gt;", "")
                        .replace("<b>", "")
                        .replace("</b>", "")
                    )

            # Extraire les temps de passage (splits) : priorité au tableau dans
            # data-tippy-content du bouton tippy-button (table avec distance, cumul, split).
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
            # Fallback : ancienne logique sur les liens <a class="text-blue-600">
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

            # Si cette ligne n'a pas de classement ET qu'il y a une performance précédente
            # ET que la colonne de classement est réellement vide, on ajoute ce nageur
            # à la liste des nageurs de la performance précédente.
            # Si la colonne contient une valeur non vide (par ex. '---', 'DNS', etc.),
            # on considère que c'est une nouvelle performance indépendante.
            if (not has_ranking) and (not rank) and last_performance is not None and swimmer_name:
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
                continue  # Passer à la ligne suivante sans créer de nouvelle performance

            # Sinon, créer une nouvelle performance normalement
            if swimmer_name and (time or has_ranking):
                # Points numériques si possible
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
                last_performance = perf  # Garder une référence pour les lignes suivantes sans classement

    return epreuves
