"""Pretraitement FRM Natation : filtre les performances et normalise les noms.

Ce script lit les JSON bruts marocains depuis deux dossiers sous
``data/raw/frmnatation/`` :

1. ``html_results/`` --- JSON deja proches du schema unifie (HTML externe).
2. ``json_from_pdfs_llamaextract/`` --- JSON tabulaires extraits de PDF via
   LlamaExtract (``source_file``, ``tables[]``).

Les fichiers normalises sont ecrits sous ``data/processed/frmnatation/html_results/``
(schema unifie consomme par ``FrmnatationHtmlResultsDataLoader``).

Le flux de donnees :
1. **Conversion** --- les payloads LlamaExtract sont transformes en schema unifie.
2. **Filtrage** --- suppression des performances sans ``SwimTimeSeconds`` valide.
3. **Noms** --- normalisation ``NOM MAJUSCULE + Prenom`` (particules EL, AIT, ...).
4. **Epreuves** --- conversion des codes nage FRM (DOS, PAP, 4N) vers l'anglais
   (BK, FL, IM) et reconstruction du libelle ``Event``.
5. **Categories** --- ajout de ``AgeGroup`` USA Swimming a partir de l'age.

Point d'entree CLI : ``python -m pacing.ingestion.frmnatation.preprocessing``.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from pacing.config.paths import FRMNATATION_PROCESSED_DIR, FRMNATATION_RAW_DIR
from pacing.domain.models_frmn import FrmCompetition, FrmNageur

FRMNATATION_HTML_RESULTS_DIR = FRMNATATION_RAW_DIR / "html_results"
FRMNATATION_LLAMAEXTRACT_DIR = FRMNATATION_RAW_DIR / "json_from_pdfs_llamaextract"
FRMNATATION_OUTPUT_DIR = FRMNATATION_PROCESSED_DIR

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


def sanitize_epreuve_event(epreuve: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Nettoie ``Event`` : libelle canonique ou ``None`` si epreuve inconnue.

    Ne conserve un ``Event`` non nul que s'il peut etre reconstruit depuis
    ``Distance``, ``Stroke`` et ``Course``. Supprime toute autre valeur
    (ex. ``PDF_TABLE_001`` ou libelle orphelin).

    Args:
        epreuve (Dict[str, Any]): Dictionnaire epreuve apres normalisation nage.

    Returns:
        Tuple[Dict[str, Any], bool]: Epreuve mise a jour et indicateur de changement.
    """
    out = dict(epreuve)
    changed = False
    canonical = build_event_label(out)
    current = out.get("Event")

    if canonical is not None:
        if current != canonical:
            out["Event"] = canonical
            changed = True
    elif current is not None:
        out["Event"] = None
        changed = True

    return out, changed


def _normalize_epreuve_stroke_and_event(
    epreuve: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Normalise Stroke (anglais) puis nettoie ``Event`` en consequence."""
    out = dict(epreuve)
    changed = False

    raw_stroke = out.get("Stroke")
    new_stroke = normalize_stroke_code(raw_stroke)
    if new_stroke != raw_stroke:
        out["Stroke"] = new_stroke
        changed = True

    out, event_changed = sanitize_epreuve_event(out)
    changed = changed or event_changed

    return out, changed


def _normalize_frm_nageur(swimmer: FrmNageur) -> Tuple[Dict[str, Any], bool]:
    """Normalise un nageur FRM typé ; retourne (dict, True si modifié)."""
    out = swimmer.model_dump()
    changed = False

    raw = swimmer.Name
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


def _normalize_swimmer(swimmer: Any) -> Tuple[Any, bool]:
    """Normalise swimmer.Name et swimmer.AgeGroup ; retourne (swimmer, True si modifié)."""
    if isinstance(swimmer, FrmNageur):
        return _normalize_frm_nageur(swimmer)

    if isinstance(swimmer, list):
        normalized: List[Dict[str, Any]] = []
        changed = False
        for item in swimmer:
            if isinstance(item, FrmNageur):
                nageur_out, item_changed = _normalize_frm_nageur(item)
            elif isinstance(item, dict):
                nageur_out, item_changed = _normalize_swimmer(item)
            else:
                continue
            normalized.append(nageur_out)
            changed = changed or item_changed
        if not normalized:
            return swimmer, False
        return normalized if len(normalized) > 1 else normalized[0], changed

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


def parse_swim_time_to_seconds(raw: Any) -> Optional[float]:
    """Convertit un temps affiche FRM en secondes decimales.

    Accepte ``HH:MM:SS``, ``MM:SS.ss``, ``SS.ss`` ou entiers.

    Args:
        raw (Any): Chaine ou nombre brut (ex. ``35.97``, ``1:02.15``).

    Returns:
        Optional[float]: Secondes arrondies a 2 decimales, ou None si invalide.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None

    hh_mm_ss = re.match(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$", text)
    if hh_mm_ss:
        hours = int(hh_mm_ss.group(1))
        minutes = int(hh_mm_ss.group(2))
        seconds = float(hh_mm_ss.group(3))
        if 0 <= minutes < 60 and 0 <= seconds < 60:
            return round(hours * 3600 + minutes * 60 + seconds, 2)
        return None

    mm_ss = re.match(r"^(\d+):(\d{1,2}(?:\.\d+)?)$", text)
    if mm_ss:
        minutes = int(mm_ss.group(1))
        seconds = float(mm_ss.group(2))
        if 0 <= seconds < 60:
            return round(minutes * 60 + seconds, 2)
        return None

    ss = re.match(r"^(\d+\.\d+)$", text)
    if ss:
        return round(float(ss.group(1)), 2)

    plain = re.match(r"^(\d+)$", text)
    if plain:
        return round(float(plain.group(1)), 2)

    return None


def parse_llama_rank(raw: Any) -> Optional[int]:
    """Extrait un classement entier depuis une cellule LlamaExtract.

    Args:
        raw (Any): Valeur brute (ex. ``\"1.\"``, ``\"12\"``).

    Returns:
        Optional[int]: Rang ou None si non parseable.
    """
    if raw is None:
        return None
    text = str(raw).strip().rstrip(".")
    if not text or not text.isdigit():
        return None
    return int(text)


def parse_year_of_birth(raw: Any) -> Optional[int]:
    """Convertit une annee de naissance LlamaExtract en entier.

    Args:
        raw (Any): Valeur brute (ex. ``\"2003\"``).

    Returns:
        Optional[int]: Annee ou None.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.isdigit():
        return None
    year = int(text)
    if 1900 <= year <= 2100:
        return year
    return None


def is_llamaextract_competition(data: Dict[str, Any]) -> bool:
    """Indique si un JSON brut provient de LlamaExtract (PDF).

    Args:
        data (Dict[str, Any]): Objet JSON racine.

    Returns:
        bool: True si les cles ``source_file`` et ``tables`` sont presentes.
    """
    return isinstance(data.get("tables"), list) and "source_file" in data


def meet_name_from_llama_source(source_file: Any) -> str:
    """Derive le nom de competition depuis le PDF source LlamaExtract.

    Args:
        source_file (Any): Nom de fichier PDF (ex. ``\"Meeting X_0.pdf\"``).

    Returns:
        str: Libelle Meet sans extension ni suffixe ``_0``.
    """
    name = Path(str(source_file or "competition_sans_nom")).stem
    if name.endswith("_0"):
        name = name[:-2]
    return name.strip() or "competition_sans_nom"


def _llama_row_to_performance(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convertit une ligne tabulaire LlamaExtract en performance unifiee.

    Args:
        row (Dict[str, Any]): Ligne avec colonnes FR (Place, Nom et prenom, ...).

    Returns:
        Optional[Dict[str, Any]]: Performance normalisee, ou None si chrono absent.
    """
    swim_time_raw = row.get("Temps")
    swim_time = str(swim_time_raw).strip() if swim_time_raw is not None else ""
    swim_time_seconds = parse_swim_time_to_seconds(swim_time)
    if swim_time_seconds is None:
        return None

    raw_name = row.get("Nom et prénom") or row.get("Nom et prenom")
    name = str(raw_name).strip() if raw_name is not None else ""
    if not name:
        return None

    yob = parse_year_of_birth(row.get("Naissance"))
    nationality = row.get("Nation")
    nat_str = str(nationality).strip().upper() if nationality is not None else None

    swimmer: Dict[str, Any] = {
        "Name": name,
        "Gender": None,
        "Year_of_birth": yob,
        "Age": None,
        "Nationality": nat_str or None,
    }

    club_raw = row.get("Club")
    club = str(club_raw).strip() if club_raw is not None else None

    return {
        "Rank": parse_llama_rank(row.get("Place")),
        "club": club,
        "SwimTime": swim_time,
        "SwimTimeSeconds": swim_time_seconds,
        "Status": "OK",
        "Speed": None,
        "swimmer": swimmer,
        "splits": [],
    }


def llamaextract_table_to_epreuve(table: Dict[str, Any], table_index: int) -> Optional[Dict[str, Any]]:
    """Convertit une table LlamaExtract en epreuve au schema unifie.

    Les PDF extraits ne contiennent en general pas la distance ni la nage :
    ``Event`` reste ``None`` ; la categorie d'age PDF (``category``) est
    conservee dans ``tour``.

    Args:
        table (Dict[str, Any]): Table avec ``category``, ``headers``, ``rows``.
        table_index (int): Index zero-based de la table dans le fichier source.

    Returns:
        Optional[Dict[str, Any]]: Epreuve avec performances, ou None si vide.
    """
    rows = table.get("rows")
    if not isinstance(rows, list):
        return None

    performances: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        perf = _llama_row_to_performance(row)
        if perf is not None:
            performances.append(perf)

    if not performances:
        return None

    category = str(table.get("category") or "").strip()
    tour = category if category else f"Table {table_index + 1}"

    return {
        "Event": None,
        "Distance": None,
        "Stroke": None,
        "Course": "LCM",
        "PoolLength": 50,
        "tour": tour,
        "performances": performances,
    }


def llamaextract_to_competition(data: Dict[str, Any]) -> Dict[str, Any]:
    """Transforme un JSON LlamaExtract en competition au schema unifie Pacing.

    Args:
        data (Dict[str, Any]): Payload brut ``{source_file, tables[]}``.

    Returns:
        Dict[str, Any]: Competition avec ``Meet``, ``epreuves`` et metadonnees.
    """
    tables = data.get("tables") or []
    epreuves: List[Dict[str, Any]] = []
    if isinstance(tables, list):
        for idx, table in enumerate(tables):
            if not isinstance(table, dict):
                continue
            epreuve = llamaextract_table_to_epreuve(table, idx)
            if epreuve is not None:
                epreuves.append(epreuve)

    return {
        "Meet": meet_name_from_llama_source(data.get("source_file")),
        "SwimDate": None,
        "SwimYear": None,
        "location": None,
        "Country": "MAR",
        "source_format": "llamaextract_pdf",
        "source_file": data.get("source_file"),
        "epreuves": epreuves,
    }


def load_competition_from_raw(raw: Dict[str, Any]) -> FrmCompetition:
    """Charge une competition brute (HTML ou LlamaExtract) au schema unifie.

    Args:
        raw (Dict[str, Any]): JSON brut lu depuis le disque.

    Returns:
        FrmCompetition: Structure competition validee pour ``preprocess_competition``.
    """
    if is_llamaextract_competition(raw):
        return FrmCompetition.model_validate(llamaextract_to_competition(raw))
    return FrmCompetition.model_validate(raw)


def load_competition_from_path(input_path: Path, *, label: str) -> FrmCompetition:
    """Charge une competition FRM depuis un fichier JSON.

    Args:
        input_path (Path): Chemin du fichier source.
        label (str): ``html_results`` ou ``llamaextract``.

    Returns:
        FrmCompetition: Instance validee.

    Raises:
        ValidationError: Si le JSON ne respecte pas le schema.
        OSError: Si le fichier est illisible.
    """
    if label == "html_results":
        return FrmCompetition.from_json_file(input_path)

    with input_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{input_path.name} ne contient pas un objet JSON racine.")
    return load_competition_from_raw(raw)


# --- Pretraitement competition et batch ---


def preprocess_competition(
    data: FrmCompetition,
) -> Tuple[Dict[str, Any], int, int, int]:
    """Nettoie une compétition FRM Natation (filtrage + normalisation).

    Supprime les performances sans chrono, normalise les noms, convertit les
    codes nage et met à jour ``Event``.

    Args:
        data (FrmCompetition): Compétition FRM validée.

    Returns:
        Tuple[Dict[str, Any], int, int, int]: Données nettoyées, nombre de
            performances avant filtrage, après filtrage, et noms modifiés.
    """
    before = 0
    after = 0
    names_changed = 0
    filtered_epreuves: List[Dict[str, Any]] = []

    for epreuve in data.epreuves:
        kept: List[Dict[str, Any]] = []
        for perf in epreuve.performances:
            before += 1
            if swim_time_seconds_is_null(perf.SwimTimeSeconds):
                continue

            perf_out = perf.model_dump()
            swimmer, changed = _normalize_swimmer(perf.swimmer)
            if changed:
                names_changed += 1
            perf_out["swimmer"] = swimmer
            kept.append(perf_out)
            after += 1

        if not kept:
            continue

        epreuve_out = epreuve.model_dump()
        epreuve_out["performances"] = kept
        epreuve_out, _ = _normalize_epreuve_stroke_and_event(epreuve_out)
        filtered_epreuves.append(epreuve_out)

    out = data.model_dump()
    out["epreuves"] = filtered_epreuves
    return out, before, after, names_changed


def _preprocess_json_directory(
    input_dir: Path,
    output_dir: Path,
    *,
    label: str,
) -> Tuple[int, int, int]:
    """Parcourt un dossier de JSON bruts et ecrit les versions normalisees.

    Args:
        input_dir (Path): Dossier source (``*.json`` a la racine).
        output_dir (Path): Dossier de sortie processed.
        label (str): Libelle affiche dans les logs (ex. ``html_results``).

    Returns:
        Tuple[int, int, int]: Total performances avant filtrage, apres filtrage,
            et nombre de noms normalises.
    """
    if not input_dir.is_dir():
        print(f"[{label}] Dossier introuvable : {input_dir}")
        return 0, 0, 0

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        print(f"[{label}] Aucun fichier JSON trouve dans {input_dir}")
        return 0, 0, 0

    total_before = 0
    total_after = 0
    total_names_changed = 0

    print(f"[{label}] {len(json_files)} fichiers trouves dans {input_dir}")

    for idx, input_path in enumerate(json_files, start=1):
        output_path = output_dir / input_path.name
        print(f"[{label}] [{idx}/{len(json_files)}] {input_path.name}")

        try:
            competition = load_competition_from_path(input_path, label=label)
        except ValidationError as exc:
            print(f"  [WARN] JSON invalide, ignore: {exc}")
            continue
        except (OSError, ValueError) as exc:
            print(f"  [WARN] illisible ou format incorrect, ignore: {exc}")
            continue

        cleaned, n_before, n_after, n_names = preprocess_competition(competition)
        total_before += n_before
        total_after += n_after
        total_names_changed += n_names

        removed = n_before - n_after
        if removed or n_names:
            parts = []
            if removed:
                parts.append(f"performances {n_before} -> {n_after} ({removed} supprimee(s))")
            if n_names:
                parts.append(f"{n_names} nom(s) normalise(s)")
            print("  " + ", ".join(parts))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f_out:
            json.dump(cleaned, f_out, ensure_ascii=False, indent=2)

    return total_before, total_after, total_names_changed


def preprocess_html_results_directory(
    input_dir: Path = FRMNATATION_HTML_RESULTS_DIR,
    output_dir: Path = FRMNATATION_OUTPUT_DIR,
) -> None:
    """Parcourt ``html_results/`` et ecrit les JSON normalises.

    Lit chaque ``*.json`` du dossier source, appelle ``preprocess_competition``
    et conserve le meme nom de fichier dans ``data/processed/``.

    Args:
        input_dir (Path): Dossier des JSON bruts HTML.
        output_dir (Path): Dossier de sortie.

    Returns:
        None
    """
    before, after, names = _preprocess_json_directory(
        input_dir,
        output_dir,
        label="html_results",
    )
    if before or after or names:
        print(
            f"\n[html_results] Termine. {before} performances lues, "
            f"{after} conservees, {before - after} supprimees, "
            f"{names} noms normalises."
        )
        print(f"[html_results] Fichiers ecrits dans {output_dir}")


def preprocess_llamaextract_directory(
    input_dir: Path = FRMNATATION_LLAMAEXTRACT_DIR,
    output_dir: Path = FRMNATATION_OUTPUT_DIR,
) -> None:
    """Parcourt ``json_from_pdfs_llamaextract/`` et ecrit les JSON normalises.

    Convertit d'abord chaque payload LlamaExtract vers le schema unifie, puis
    applique le meme filtrage et normalisation que ``html_results/``.

    Args:
        input_dir (Path): Dossier des JSON bruts LlamaExtract.
        output_dir (Path): Dossier de sortie (``processed/html_results/``).

    Returns:
        None
    """
    before, after, names = _preprocess_json_directory(
        input_dir,
        output_dir,
        label="llamaextract",
    )
    if before or after or names:
        print(
            f"\n[llamaextract] Termine. {before} performances lues, "
            f"{after} conservees, {before - after} supprimees, "
            f"{names} noms normalises."
        )
        print(f"[llamaextract] Fichiers ecrits dans {output_dir}")


def preprocess_all_frmnatation_directories(
    html_input_dir: Path = FRMNATATION_HTML_RESULTS_DIR,
    llama_input_dir: Path = FRMNATATION_LLAMAEXTRACT_DIR,
    output_dir: Path = FRMNATATION_OUTPUT_DIR,
) -> None:
    """Execute le pretraitement HTML puis LlamaExtract vers ``processed/``.

    Args:
        html_input_dir (Path): Dossier ``data/raw/.../html_results``.
        llama_input_dir (Path): Dossier ``data/raw/.../json_from_pdfs_llamaextract``.
        output_dir (Path): Dossier de sortie partage.

    Returns:
        None
    """
    preprocess_html_results_directory(input_dir=html_input_dir, output_dir=output_dir)
    preprocess_llamaextract_directory(input_dir=llama_input_dir, output_dir=output_dir)


if __name__ == "__main__":
    preprocess_all_frmnatation_directories()
