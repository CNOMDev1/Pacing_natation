"""Prétraitement FRM Natation : filtre les performances et normalise les noms.

Ce script lit les JSON bruts scrapés depuis les pages HTML marocaines
(``data/raw/frmnatation/html_results/``) et produit des fichiers normalisés
sous ``data/processed/frmnatation/html_results/``.

Le flux de données :
1. **Filtrage** — suppression des performances sans ``SwimTimeSeconds`` valide.
2. **Noms** — normalisation ``NOM MAJUSCULE + Prénom`` (particules EL, AIT, …).
3. **Épreuves** — conversion des codes nage FRM (DOS, PAP, 4N) vers l'anglais
   (BK, FL, IM) et reconstruction du libellé ``Event``.
4. **Catégories** — ajout de ``AgeGroup`` USA Swimming à partir de l'âge.

Point d'entrée CLI : ``python -m app.scripts.frmnatation_preprocessing``.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Chemins source / sortie ---

FRMNATATION_HTML_RESULTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "raw"
    / "frmnatation"
    / "html_results"
)
FRMNATATION_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "frmnatation"
    / "html_results"
)

# --- Tables de correspondance (noms, nages, catégories d'âge) ---

# Particules du nom de famille (en majuscules dans la source FRM)
FAMILY_CONNECTORS = frozenset(
    {"EL", "AL", "BEN", "DE", "VAN", "AIT", "IBN", "LA", "LE", "DU", "DES", "OU", "OUL"}
)
# Particules dans le prénom (casse titre)
GIVEN_PARTICLES = {
    "el": "El",
    "al": "Al",
    "ben": "Ben",
    "de": "De",
    "van": "Van",
    "ibn": "Ibn",
    "la": "La",
    "le": "Le",
    "du": "Du",
    "des": "Des",
    "ou": "Ou",
    "oul": "Oul",
    "ait": "Ait",
}

# Abréviations FRM (français) -> anglais (USA Swimming)
STROKE_FR_TO_EN: Dict[str, str] = {
    "DOS": "BK",
    "PAP": "FL",
    "4N": "IM",
    "BR": "BR",
    "FR": "FR",
}

AGE_GROUP_LABELS: Tuple[str, ...] = (
    "10 & Under",
    "11-12",
    "13-14",
    "15-18",
    "19 & Over",
)


# --- Utilitaires de validation et normalisation ---


def swim_time_seconds_is_null(value: Any) -> bool:
    """Indique si SwimTimeSeconds est absent, null ou NaN.

    Args:
        value (Any): Valeur brute du champ chrono.

    Returns:
        bool: True si la performance doit être exclue.
    """
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _clean_raw_name(name: str) -> str:
    """Espaces et apostrophes normalisés."""
    text = str(name).strip()
    text = text.replace("\u2019", "'").replace("'", "'")
    return re.sub(r"\s+", " ", text)


def _is_family_word(word: str) -> bool:
    """Mot du bloc nom de famille (MAJUSCULES ou particule EL, AIT, …)."""
    w = word.strip()
    if not w:
        return False
    if w in FAMILY_CONNECTORS:
        return True
    core = w.replace("-", "").replace("'", "")
    return core.isupper() and any(c.isalpha() for c in core)


def _title_given_word(word: str) -> str:
    """Met en forme un mot du prénom (Mohamed, El, M'Hammed, …)."""
    low = word.lower()
    if low in GIVEN_PARTICLES:
        return GIVEN_PARTICLES[low]
    if "'" in word:
        return "'".join(_title_given_word(part) for part in word.split("'"))
    if "-" in word:
        return "-".join(_title_given_word(part) for part in word.split("-"))
    if not word:
        return word
    return word[0].upper() + word[1:].lower()


def normalize_frm_name(name: Any) -> Optional[str]:
    """
    Normalise un nom FRM : NOM(S) EN MAJUSCULES + prénom(s) en casse titre.

    Exemples :
      - \"MANA Noura\" -> \"MANA Noura\"
      - \"ASSAL mohamed Farouk\" -> \"ASSAL Mohamed Farouk\"
      - \"AIT EL HAJ Ghita\" -> \"AIT EL HAJ Ghita\"
      - \"BENSALEH Nour El Houda\" -> \"BENSALEH Nour El Houda\"
    """
    if name is None:
        return None
    text = _clean_raw_name(str(name))
    if not text:
        return None

    words = text.split()
    if len(words) < 2:
        return None

    split_at = 0
    while split_at < len(words) - 1 and _is_family_word(words[split_at]):
        split_at += 1
    if split_at == 0:
        split_at = 1

    family_words = words[:split_at]
    given_words = words[split_at:]
    if not given_words:
        return None

    family = " ".join(w.upper() for w in family_words)
    given = " ".join(_title_given_word(w) for w in given_words)
    return f"{family} {given}"


def age_to_age_group(age: Any) -> Optional[str]:
    """Convertit un âge entier en catégorie USA Swimming.

    Args:
        age (Any): Âge en années (entier ou chaîne numérique).

    Returns:
        Optional[str]: Libellé (ex. ``"13-14"``, ``"19 & Over"``) ou None.
    """
    if age is None:
        return None
    if isinstance(age, str) and not age.strip():
        return None
    try:
        years = int(float(age))
    except (TypeError, ValueError):
        return None
    if years < 0:
        return None
    if years <= 10:
        return "10 & Under"
    if years <= 12:
        return "11-12"
    if years <= 14:
        return "13-14"
    if years <= 18:
        return "15-18"
    return "19 & Over"


def normalize_stroke_code(stroke: Any) -> Any:
    """Convertit un code nage FRM (DOS, PAP, 4N, …) en abréviation anglaise."""
    if not isinstance(stroke, str):
        return stroke
    key = stroke.strip().upper()
    if not key:
        return stroke
    return STROKE_FR_TO_EN.get(key, key)


def build_event_label(epreuve: Dict[str, Any]) -> Optional[str]:
    """Reconstruit le libellé Event à partir de Distance, Stroke et Course.

    Args:
        epreuve (Dict[str, Any]): Dictionnaire épreuve partiellement normalisé.

    Returns:
        Optional[str]: Libellé type ``"100 BK LCM"`` ou None si champs manquants.
    """
    distance = epreuve.get("Distance")
    stroke = epreuve.get("Stroke")
    course = epreuve.get("Course")
    if distance is None or stroke is None or course is None:
        return None
    return f"{distance} {stroke} {course}"


def _normalize_epreuve_stroke_and_event(
    epreuve: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Normalise Stroke (anglais) puis met à jour Event en conséquence."""
    out = dict(epreuve)
    changed = False

    raw_stroke = out.get("Stroke")
    new_stroke = normalize_stroke_code(raw_stroke)
    if new_stroke != raw_stroke:
        out["Stroke"] = new_stroke
        changed = True

    new_event = build_event_label(out)
    if new_event is not None and new_event != out.get("Event"):
        out["Event"] = new_event
        changed = True

    return out, changed


def _normalize_swimmer(swimmer: Any) -> Tuple[Any, bool]:
    """Normalise swimmer.Name et swimmer.AgeGroup ; retourne (swimmer, True si modifié)."""
    if not isinstance(swimmer, dict):
        return swimmer, False

    out = dict(swimmer)
    changed = False

    raw = swimmer.get("Name")
    if isinstance(raw, str):
        raw_clean = _clean_raw_name(raw)
        normalized = normalize_frm_name(raw_clean)
        new_name = normalized if normalized else raw_clean
        if new_name != raw:
            out["Name"] = new_name
            changed = True

    age_group = age_to_age_group(out.get("Age"))
    if age_group != out.get("AgeGroup"):
        if age_group is None:
            out.pop("AgeGroup", None)
        else:
            out["AgeGroup"] = age_group
        changed = True

    return out, changed


# --- Prétraitement compétition et batch ---


def preprocess_competition(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], int, int, int]:
    """Nettoie une compétition FRM Natation (filtrage + normalisation).

    Supprime les performances sans chrono, normalise les noms, convertit les
    codes nage et met à jour ``Event``.

    Args:
        data (Dict[str, Any]): JSON brut d'une compétition.

    Returns:
        Tuple[Dict[str, Any], int, int, int]: Données nettoyées, nombre de
            performances avant filtrage, après filtrage, et noms modifiés.
    """
    epreuves = data.get("epreuves")
    if not isinstance(epreuves, list):
        return data, 0, 0, 0

    before = 0
    after = 0
    names_changed = 0
    filtered_epreuves: List[Dict[str, Any]] = []

    for epreuve in epreuves:
        if not isinstance(epreuve, dict):
            continue

        performances = epreuve.get("performances")
        if not isinstance(performances, list):
            filtered_epreuves.append(epreuve)
            continue

        kept: List[Dict[str, Any]] = []
        for perf in performances:
            if not isinstance(perf, dict):
                continue
            before += 1
            if swim_time_seconds_is_null(perf.get("SwimTimeSeconds")):
                continue

            perf_out = dict(perf)
            swimmer, changed = _normalize_swimmer(perf.get("swimmer"))
            if changed:
                names_changed += 1
            perf_out["swimmer"] = swimmer
            kept.append(perf_out)
            after += 1

        if not kept:
            continue

        epreuve_out = dict(epreuve)
        epreuve_out["performances"] = kept
        epreuve_out, _ = _normalize_epreuve_stroke_and_event(epreuve_out)
        filtered_epreuves.append(epreuve_out)

    out = dict(data)
    out["epreuves"] = filtered_epreuves
    return out, before, after, names_changed


def preprocess_html_results_directory(
    input_dir: Path = FRMNATATION_HTML_RESULTS_DIR,
    output_dir: Path = FRMNATATION_OUTPUT_DIR,
) -> None:
    """Parcourt ``html_results/`` et écrit les JSON normalisés.

    Lit chaque ``*.json`` du dossier source, appelle ``preprocess_competition``
    et conserve le même nom de fichier dans ``data/processed/``.

    Args:
        input_dir (Path): Dossier des JSON bruts.
        output_dir (Path): Dossier de sortie.

    Returns:
        None
    """
    if not input_dir.is_dir():
        print(f"Dossier introuvable : {input_dir}")
        return

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans {input_dir}")
        return

    total_before = 0
    total_after = 0
    total_names_changed = 0

    print(f"{len(json_files)} fichiers FRM Natation trouvés dans {input_dir}")

    for idx, input_path in enumerate(json_files, start=1):
        output_path = output_dir / input_path.name
        print(f"[{idx}/{len(json_files)}] {input_path.name}")

        with input_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            print("  [WARN] racine JSON non objet, ignoré.")
            continue

        cleaned, n_before, n_after, n_names = preprocess_competition(raw)
        total_before += n_before
        total_after += n_after
        total_names_changed += n_names

        removed = n_before - n_after
        if removed or n_names:
            parts = []
            if removed:
                parts.append(f"performances {n_before} -> {n_after} ({removed} supprimée(s))")
            if n_names:
                parts.append(f"{n_names} nom(s) normalisé(s)")
            print("  " + ", ".join(parts))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f_out:
            json.dump(cleaned, f_out, ensure_ascii=False, indent=2)

    print(
        f"\nTerminé. {total_before} performances lues, "
        f"{total_after} conservées, {total_before - total_after} supprimées, "
        f"{total_names_changed} noms normalisés."
    )
    print(f"Fichiers écrits dans {output_dir}")


if __name__ == "__main__":
    preprocess_html_results_directory()
