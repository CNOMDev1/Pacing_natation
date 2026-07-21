"""Collecte avancée des résultats Extranat (formulaire par épreuve).

Extrait de ``extranat_service`` : scrape chaque compétition via le formulaire
``<form name="choix">`` / selects d'épreuves, avec renouvellement de session
HTTP pour limiter les 403.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from services.extranat_competitions import BASE_URL, get_competitions_for_url
from services.extranat_http import http_get_with_retries
from services.extranat_parse import extract_results_from_filter_table


def get_results_for_competitions_url(
    url: str,
    delay_between_comps: float = 1.0,
    debug: bool = False,
    max_competitions_before_pause: int = 50,
    rest_delay: float = 30.0,
) -> Dict:
    """Récupère toutes les compétitions d'une URL et leurs résultats par épreuve.

    Pour chaque compétition, parse le formulaire ``<form name="choix">`` et
    scrape chaque URL d'épreuve. Recrée la session HTTP périodiquement pour
    éviter les blocages 403 après un grand nombre de requêtes.

    Args:
        url (str): URL de la page liste (ex. internationales idtyp=7).
        delay_between_comps (float): Délai (s) entre deux compétitions.
        debug (bool): Active les logs détaillés.
        max_competitions_before_pause (int): Seuil de compétitions avant pause session.
        rest_delay (float): Pause (s) avant recréation de session.

    Returns:
        Dict: ``{"url", "competitions"}`` avec résultats groupés par épreuve.
    """
    import time
    import requests

    def get_competition_results_grouped_by_event(
        comp_url: str,
        debug: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Pour une URL de compétition donnée, récupère la liste de toutes les
        épreuves disponibles dans le formulaire <form name="choix"> (Épreuves
        Dames, Messieurs, Relais, etc.), puis scrape chaque URL d'épreuve
        (50 Nage Libre, 50 Dos, ...) et classe les résultats par nom d'épreuve.

        Retourne un dict du type :
        {
          "50 Nage Libre": [ {...}, {...}, ... ],
          "50 Dos": [...],
          ...
        }
        """
        from urllib.parse import urljoin

        from services.extranat_service import get_competition_data

        grouped_results: Dict[str, List[Dict]] = {}

        # Partager le compteur de requêtes avec la fonction englobante
        nonlocal requests_since_session

        # 1) Charger la page principale de la compétition (avec le formulaire)
        if debug:
            print(f"    [grouped] Chargement page principale : {comp_url}")

        resp = http_get_with_retries(
            comp_url,
            debug=debug,
            max_retries=5,
            session=session,
            # Important : pas de retry infini ici. Si cette compétition
            # retourne 403 en continu (bloquée côté serveur), on laisse
            # http_get_with_retries lever une erreur après quelques essais,
            # puis le code appelant marquera la compétition en erreur et
            # passera à la suivante.
            retry_forever=False,
        )
        # Une requête "logique" supplémentaire
        requests_since_session += 1
        soup = BeautifulSoup(resp.content, "html.parser")

        # 1.a) TENTER D'ABORD de lire directement les <select> d'épreuves dans le bloc
        #      <div class="mb-3"> qui contient "Épreuves Dames/Messieurs" et "Relais ...".
        #      Cela permet de couvrir les compétitions où il n'y a pas de liens idsex=
        #      mais uniquement ces selects.
        def _scrape_events_from_selects(
            select_elements, gender_label: str
        ) -> List[Dict]:
            """Parcourt les ``<select>`` d'épreuves et récupère chaque page résultats.

            Args:
                select_elements: Éléments BeautifulSoup ``<select>`` à parcourir.
                gender_label (str): Libellé de genre pour les logs (ex. « Dames »).

            Returns:
                List[Dict]: Épreuves extraites via ``extract_results_from_filter_table``.
            """
            all_epreuves: List[Dict] = []
            nonlocal requests_since_session
            from urllib.parse import urljoin as _urljoin_local

            for sel in select_elements:
                for opt in sel.find_all("option"):
                    value = opt.get("value", "").strip()
                    label_opt = opt.get_text(strip=True)

                    # Ignorer option vide / titre
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
                            # Aucune performance trouvée : créer tout de même l'épreuve vide
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
                        # En cas d'erreur, on ajoute quand même l'épreuve (vide) pour ne pas la perdre
                        all_epreuves.append(
                            {
                                "nom": label_opt,
                                "categorie": gender_label,
                                "tour": "",
                                "performances": [],
                            }
                        )

            return all_epreuves

        # Chercher tous les <select> et regrouper ceux qui concernent Dames/Messieurs
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

            # Si on a effectivement récupéré quelque chose, on peut retourner tout de suite
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
                # Une requête "logique" supplémentaire
                requests_since_session += 1
                if simple_results:
                    grouped_results["default"] = simple_results
                else:
                    # Aucun résultat trouvé même avec le fallback
                    grouped_results["_info"] = "Formulaire non trouvé et aucun résultat sur la page principale"
            except Exception as e:
                if debug:
                    print(f"    [grouped] Erreur lors du fallback : {e}")
                grouped_results["_error"] = f"Formulaire non trouvé et erreur lors du scraping : {str(e)}"
            return grouped_results

        # 2) Vérifier s'il y a des filtres (Dames, Messieurs) dans le formulaire
        filter_links = form.find_all("a", href=True)
        filter_links_valid = []
        for link in filter_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            # Chercher les liens de filtre (Dames, Messieurs) qui contiennent idsex=
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

                                # Ignorer options vides / titres / vues alternatives
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
                                        # On a trouvé des résultats pour cette épreuve :
                                        # on les ajoute tels quels.
                                        all_epreuves_for_filter.extend(epreuves_event)
                                    else:
                                        # Aucun résultat trouvé sur la page, mais on veut
                                        # quand même que l'épreuve existe dans le JSON
                                        # (avec une liste de performances vide) pour ne
                                        # pas "perdre" l'épreuve présente dans le <select>.
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
                            # Fallback : table directe (cas où il n'y aurait pas d'épreuves
                            # accessibles via le formulaire pour ce filtre).
                            filter_results = extract_results_from_filter_table(
                                filter_soup, debug=debug
                            )
                            grouped_results[filter_label] = filter_results
                    else:
                        # Aucun formulaire trouvé sur la page filtrée :
                        # fallback direct sur la table.
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

                # Ignorer les options vides ou purement descriptives
                if not value or not label:
                    continue
                # Exemples de labels à ignorer :
                #   - "Épreuves Dames", "Relais Messieurs", etc. (titres de groupes)
                #   - "Affichage par séries" (vue alternative qu'on ne souhaite pas scraper)
                if (
                    "Épreuves" in label
                    or "Relais" in label
                    or "Affichage par séries" in label
                ):
                    continue

                events_found += 1
                event_name = label  # ex : "50 Nage Libre"
                event_url = urljoin(BASE_URL, value)

                if debug:
                    print(f"    [grouped] Épreuve détectée : '{event_name}' → {event_url}")

                try:
                    # Pas de retry infini ici non plus : si une épreuve
                    # est inaccessible, on passe à la suivante.
                    event_results = get_competition_data(
                        event_url,
                        debug=False,
                        session=session,
                        retry_forever=False,
                    )
                    # Une requête "logique" supplémentaire
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

        # Si aucun événement valide n'a été trouvé, ajouter une info
        if events_found == 0 and len(grouped_results) == 0:
            grouped_results["_info"] = f"Formulaire trouvé avec {len(selects)} select(s) mais aucune épreuve valide détectée"

        return grouped_results

    if debug:
        print(f"Récupération des compétitions (URL directe) : {url}")

    competitions = get_competitions_for_url(url, debug=debug)

    competitions_since_pause = 0
    # Compteur approximatif de "requêtes logiques" (pages de résultats)
    # effectuées avec la session courante : 1 pour la page principale
    # d'une compétition, 1 pour chaque épreuve/option du formulaire.
    requests_since_session = 0
    consecutive_403_count = 0
    recent_success_count = 0  # Compteur de succès récents
    competitions_since_new_session = 0  # Compteur depuis la dernière création de session

    def create_new_session():
        """Helper pour créer une nouvelle session avec des headers réalistes"""
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
                    """Compte le nombre total de performances dans un dict groupé par épreuve.

                    Args:
                        grouped_dict (Dict): Résultats groupés (listes plates ou épreuves).

                    Returns:
                        int: Nombre total de lignes de performance.
                    """
                    total = 0
                    for key, value in grouped_dict.items():
                        # Ignorer les clés spéciales éventuelles (_info, _error, etc.)
                        if isinstance(key, str) and key.startswith("_"):
                            continue
                        if not isinstance(value, list):
                            continue
                        if not value:
                            continue
                        # Cas des pages filtrées : value est une liste d'épreuves,
                        # chaque épreuve ayant une liste "performances".
                        if isinstance(value[0], dict) and "performances" in value[0]:
                            for epreuve in value:
                                if isinstance(epreuve, dict):
                                    perfs = epreuve.get("performances", [])
                                    if isinstance(perfs, list):
                                        total += len(perfs)
                        else:
                            # Cas historique : liste "plate" de résultats
                            total += len(value)
                    return total

                comp["results_count"] = _count_grouped_results(grouped)
                consecutive_403_count = 0  # Réinitialiser le compteur si succès
                recent_success_count = min(recent_success_count + 1, 10)  # Max 10, pour tracker les succès récents

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

            # Compter cette compétition (même si erreur, on a fait une requête)
            competitions_since_pause += 1
            competitions_since_new_session += 1

            # Si les 3 premières compétitions après une nouvelle session échouent toutes avec 403,
            # ce sont probablement des compétitions bloquées en permanence, pas un problème de session
            if competitions_since_new_session <= 3 and is_403:
                if debug and competitions_since_new_session == 3:
                    print(
                        f"      ⚠ Les 3 premières compétitions après la nouvelle session ont échoué avec 403. "
                        f"Ce sont probablement des compétitions bloquées en permanence."
                    )
                # Ne pas compter ces 403 comme des erreurs de rate-limiting
                # On continue normalement sans créer une autre session

            # Si trop de 403 consécutifs ET qu'on a eu des succès récents (rate-limiting probable),
            # créer une nouvelle session. Si on n'a pas eu de succès récents, ce sont probablement
            # des compétitions bloquées en permanence, donc pas besoin de créer une nouvelle session.
            # ET on ne crée pas de session si on vient juste d'en créer une (competitions_since_new_session <= 5)
            if consecutive_403_count >= 5 and recent_success_count > 0 and competitions_since_new_session > 5:
                if debug:
                    print(
                        f"      ⚠ {consecutive_403_count} erreurs 403 consécutives détectées "
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
                continue  # Passer à la compétition suivante sans pause supplémentaire
            elif consecutive_403_count >= 5 and recent_success_count == 0:
                if debug:
                    print(
                        f"      ⚠ {consecutive_403_count} erreurs 403 consécutives détectées "
                        f"(aucun succès récent). Ces compétitions semblent bloquées en permanence. "
                        f"On continue sans créer de nouvelle session..."
                    )
                # Ne pas créer de nouvelle session, juste réinitialiser le compteur pour éviter les messages répétés
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
