"""Prétraitement USA Swimming : nettoyage et regroupement par compétition.

Ce script lit les listes de performances brutes (``data/raw/usaswimming/``),
nettoie chaque enregistrement et regroupe les résultats au format Extranat
(compétition → épreuves → performances) sous ``data/processed/usaswimming/``.

Le flux de données :
1. **Nettoyage ligne** — ``clean_record()`` valide le nom, normalise dates,
   chronos, genre, pays et calcule ``SwimTimeSeconds`` / ``Speed``.
2. **Regroupement** — ``clean_file()`` agrège par ``(Event, Session)`` en
   épreuves avec liste de performances.
3. **Batch** — ``clean_usaswimming_directory()`` parcourt récursivement
   tous les JSON bruts en conservant l'arborescence.

Point d'entrée CLI : ``python -m app.scripts.usaswimming_preprocessing``.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from pydantic import ValidationError

from pacing.config.paths import USASWIMMING_PROCESSED_DIR, USASWIMMING_RAW_DIR
from pacing.domain.models_usaswimming import NageurRecord, NageursList

DATA_DIR = USASWIMMING_RAW_DIR
OUTPUT_DIR = USASWIMMING_PROCESSED_DIR

COURSE_CODES = {"LCM", "SCM", "SCY"}

# Lettres, espaces, tiret, apostrophe, point (ex. O'Brien, Jean-Pierre, Jr.)
_VALID_SWIMMER_NAME_PATTERN = re.compile(r"^[A-Za-zÀ-ÿ\s\-'.]+$")


# --- Statut, pays et parsing des noms ---


def compute_status_from_swim_time(swim_time: Any) -> str:
    """Détermine le statut à partir de la valeur de SwimTime.

    Args:
        swim_time (Any): Temps brut (chaîne, None, code DNS/DSQ/DNF).

    Returns:
        str: ``"OK"``, ``"DNS"``, ``"DSQ"``, ``"DNF"`` ou ``"NaN"``.
    """
    if swim_time is None:
        return "NaN"

    s = str(swim_time).strip()
    if not s or s.upper() == "NONE":
        return "NaN"

    code = s.upper()
    if code in {"DNS", "DSQ", "DNF"}:
        return code

    return "OK"


COUNTRY_MAP: Dict[str, str] = {
    "United States": "USA",
    "United States Of America": "USA",
    "Usa": "USA",
    "Germany": "GER",
    "France": "FRA",
    "Brazil": "BRA",
    "Canada": "CAN",
    "Spain": "ESP",
    "Italy": "ITA",
    "Great Britain": "GBR",
    "United Kingdom": "GBR",
    "Russia": "RUS",
    "China": "CHN",
    "Japan": "JPN",
    "Australia": "AUS",
    "Netherlands": "NED",
    "Sweden": "SWE",
    "Norway": "NOR",
    "Denmark": "DEN",
    "Hungary": "HUN",
    "Poland": "POL",
    "South Africa": "RSA",
}


def normalize_country(raw: str) -> str:
    """Convertit une fédération ou un pays en code ISO 3 lettres.

    Args:
        raw (str): Libellé pays ou code existant.

    Returns:
        str: Code normalisé (ex. ``"USA"``, ``"FRA"``).
    """
    txt = raw.strip()
    if not txt:
        return txt

    upper = txt.upper()
    if len(upper) == 3 and upper.isalpha():
        return upper

    return COUNTRY_MAP.get(txt, txt)


def parse_name_year_nationality(
    raw_name: str,
) -> Tuple[str, Optional[int], Optional[str]]:
    """Extrait nom, année de naissance et nationalité d'un libellé enrichi.

    Gère les formats du type ``"Dupont Jean (2008/16 ans)FRA"``.

    Args:
        raw_name (str): Nom brut tel que fourni par la source.

    Returns:
        Tuple[str, Optional[int], Optional[str]]: Nom nettoyé, YOB, nationalité.
    """
    txt = raw_name.strip()
    if not txt:
        return txt, None, None

    m = re.match(
        r"^(?P<name>.+?)\s*\((?P<year>\d{4})[^)]*\)\s*(?P<nat>[A-Za-z]{3})?$",
        txt,
        flags=re.IGNORECASE,
    )
    if not m:
        return txt, None, None

    base_name = m.group("name").strip()
    year_str = m.group("year")
    nat_str = m.group("nat")

    year_val: Optional[int] = None
    if year_str:
        try:
            year_val = int(year_str)
        except ValueError:
            year_val = None

    nat_val: Optional[str] = None
    if nat_str:
        nat_val = nat_str.strip().upper()

    return base_name, year_val, nat_val


def is_valid_swimmer_name(name: Optional[str]) -> bool:
    """Vérifie que le nom ne contient ni chiffre ni caractère spécial.

    Args:
        name (Optional[str]): Nom du nageur.

    Returns:
        bool: True si le nom respecte le motif autorisé.
    """
    if name is None:
        return False
    value = str(name).strip()
    if not value:
        return False
    return bool(_VALID_SWIMMER_NAME_PATTERN.match(value))


def parse_swim_time_to_seconds(raw: str) -> float:
    """Convertit un temps affiché en secondes décimales.

    Accepte ``HH:MM:SS``, ``MM:SS.ss``, ``SS.ss`` ou entiers.

    Args:
        raw (str): Chaîne de temps brute.

    Returns:
        float: Secondes, ou ``float("nan")`` si format non reconnu.
    """
    raw = raw.strip()
    hh_mm_ss = re.match(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$", raw)
    if hh_mm_ss:
        hours = int(hh_mm_ss.group(1))
        minutes = int(hh_mm_ss.group(2))
        seconds = float(hh_mm_ss.group(3))
        if 0 <= minutes < 60 and 0 <= seconds < 60:
            return hours * 3600 + minutes * 60 + seconds
        return float("nan")

    mm_ss = re.match(r"^(\d+):(\d{1,2}(?:\.\d+)?)$", raw)
    if mm_ss:
        minutes = int(mm_ss.group(1))
        seconds = float(mm_ss.group(2))
        if 0 <= seconds < 60:
            return minutes * 60 + seconds
        return float("nan")

    ss = re.match(r"^(\d+\.\d+)$", raw)
    if ss:
        return float(ss.group(1))

    plain = re.match(r"^(\d+)$", raw)
    if plain:
        return float(plain.group(1))

    return float("nan")


def sanitize_swim_time(raw: Any) -> str:
    """Nettoie SwimTime en ne conservant que chiffres, ``:`` et ``.``.

    Args:
        raw (Any): Valeur brute du temps.

    Returns:
        str: Temps sanitisé, ou chaîne vide si absent.
    """
    if raw is None:
        return ""

    value = str(raw).strip()
    if not value:
        return ""

    # Decimal comma -> decimal point.
    value = value.replace(",", ".")

    # Keep only allowed characters.
    value = re.sub(r"[^0-9:.]", "", value)

    # Remove repeated separators that can appear in noisy source values.
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r":{2,}", ":", value)

    # Remove leading/trailing separators.
    value = value.strip(":.")
    return value


def normalize_date(raw: str) -> str:
    """Normalise SwimDate en ISO YYYY-MM-DD."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    return raw


# --- Parsing épreuve et nettoyage enregistrement ---


def parse_event(raw_event: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Extrait distance, code nage et bassin depuis un libellé Event.

    Args:
        raw_event (str): Libellé type ``"100 BK LCM"``.

    Returns:
        Tuple[Optional[int], Optional[str], Optional[str]]: Distance, Stroke, Course.
    """
    if not raw_event:
        return None, None, None

    tokens = raw_event.upper().split()
    if not tokens:
        return None, None, None

    distance: Optional[int] = None
    try:
        distance = int(tokens[0])
    except ValueError:
        distance = None

    course: Optional[str] = None
    if tokens[-1] in COURSE_CODES:
        course = tokens[-1]

    stroke_code: Optional[str] = None
    stroke_codes = {"FR", "BK", "BR", "FL", "MD", "IM"}
    for t in tokens[1:]:
        if t in stroke_codes:
            stroke_code = t
            break

    return distance, stroke_code, course


def clean_record(rec: NageurRecord) -> Optional[Dict[str, Any]]:
    """Nettoie un enregistrement USA Swimming (une performance).

    Valide le nom, normalise genre/chrono/pays et dérive Distance, Stroke,
    Course et Speed. Retourne None si le nom est invalide.

    Args:
        rec (NageurRecord): Ligne validée du JSON source.

    Returns:
        Optional[Dict[str, Any]]: Performance nettoyée ou None si rejetée.
    """
    cleaned: Dict[str, Any] = {}

    name = str(rec.Name or "").strip()
    year_of_birth_raw = rec.resolved_year_of_birth()
    nationality_raw = rec.Nationality
    federation = str(rec.Federation or "").strip()
    event = str(rec.Event or "").strip()
    gender = str(rec.Gender or "").strip()
    meet = str(rec.Meet or "").strip()
    swim_date_raw = rec.SwimDate
    swim_date = (
        swim_date_raw.strftime("%Y-%m-%d")
        if isinstance(swim_date_raw, datetime)
        else str(swim_date_raw or "").strip()
    )
    swim_time_raw = rec.SwimTime
    swim_time = sanitize_swim_time(swim_time_raw)
    swim_time_seconds = rec.SwimTimeSeconds
    session_raw = rec.Session
    agegroup_raw = rec.AgeGroup
    time_standard_raw = rec.TimeStandard
    rank_raw = rec.Rank if rec.Rank is not None else rec.Place

    session = str(session_raw).strip() if session_raw is not None else None
    age_group = str(agegroup_raw).strip() if agegroup_raw is not None else None
    time_standard = str(time_standard_raw).strip() if time_standard_raw is not None else None

    rank: Any = None
    if rank_raw is not None:
        rank_str = str(rank_raw).strip()
        if rank_str and rank_str.upper().replace("\\", "") not in {"N/A", "NA", "NONE"}:
            try:
                rank = int(float(rank_str))
            except ValueError:
                rank = rank_raw

    base_name, inferred_year, inferred_nat = parse_name_year_nationality(name)
    if base_name:
        name = base_name

    if not is_valid_swimmer_name(name):
        return None

    cleaned["Name"] = name.title()

    yob_value = year_of_birth_raw
    if yob_value is None or (isinstance(yob_value, str) and not yob_value.strip()):
        yob_value = inferred_year

    if yob_value is not None:
        try:
            yob_int = int(yob_value)
        except (TypeError, ValueError):
            yob_int = None
        if yob_int is not None:
            cleaned["Year_of_birth"] = yob_int
        elif rec.Year_of_birth is not None or rec.DateOfBirth is not None:
            cleaned["Year_of_birth"] = None
    elif rec.Year_of_birth is not None or rec.DateOfBirth is not None:
        cleaned["Year_of_birth"] = None

    nat_value = nationality_raw or inferred_nat
    if isinstance(nat_value, str) and nat_value.strip():
        cleaned["Nationality"] = nat_value.strip().upper()
    else:
        cleaned["Nationality"] = None

    if federation:
        cleaned["Country"] = normalize_country(federation)
    if event:
        norm_event = event.upper()
        cleaned["Event"] = norm_event

        distance, stroke_name, course = parse_event(norm_event)
        if distance is not None:
            cleaned["Distance"] = distance
        if stroke_name is not None:
            cleaned["Stroke"] = stroke_name
        if course is not None:
            cleaned["Course"] = course
            if course == "SCM":
                cleaned["PoolLength"] = 25
            elif course == "LCM":
                cleaned["PoolLength"] = 50
            elif course == "SCY":
                cleaned["PoolLength"] = 22.86

    if meet:
        cleaned["Meet"] = meet.strip()

    if session:
        cleaned["Session"] = session
    if age_group:
        cleaned["AgeGroup"] = age_group
    if time_standard:
        cleaned["TimeStandard"] = time_standard
    if rank is not None:
        cleaned["Rank"] = rank

    club = rec.resolved_club()
    if club:
        cleaned["Club"] = club.strip()

    g = gender.lower()
    if g in {"f", "female", "femme", "girl", "women"}:
        cleaned["Gender"] = "F"
    elif g in {"m", "male", "homme", "boy", "men"}:
        cleaned["Gender"] = "M"
    elif gender:
        cleaned["Gender"] = gender

    if swim_date:
        cleaned["SwimDate"] = normalize_date(swim_date)

    status = compute_status_from_swim_time(swim_time_raw)
    if status == "OK" and swim_time:
        cleaned["SwimTime"] = swim_time
        computed = parse_swim_time_to_seconds(swim_time)
    else:
        cleaned["SwimTime"] = "NaN"
        computed = float("nan")

    if status == "OK":
        if swim_time_seconds is not None:
            try:
                original_seconds = float(swim_time_seconds)
            except (TypeError, ValueError):
                original_seconds = float("nan")
        else:
            original_seconds = float("nan")

        chosen_seconds = original_seconds
        # NaN check : préfère SwimTimeSeconds source, sinon valeur recalculée
        if not (isinstance(original_seconds, float) and not (original_seconds != original_seconds)):
            chosen_seconds = original_seconds
        elif not (isinstance(computed, float) and computed != computed):
            chosen_seconds = computed

        if isinstance(chosen_seconds, float) and not (chosen_seconds != chosen_seconds):
            cleaned["SwimTimeSeconds"] = round(chosen_seconds, 2)
    else:
        cleaned["SwimTimeSeconds"] = None

    cleaned["Status"] = status

    distance_val = cleaned.get("Distance")
    time_seconds_val = cleaned.get("SwimTimeSeconds")
    if (
        isinstance(distance_val, (int, float))
        and isinstance(time_seconds_val, (int, float))
        and time_seconds_val > 0
    ):
        cleaned["Speed"] = round(distance_val / time_seconds_val, 4)

    return cleaned


def _age_at_performance(swim_date_iso: Optional[str], year_of_birth: Any) -> Optional[int]:
    if not swim_date_iso or year_of_birth is None:
        return None
    if not isinstance(year_of_birth, int):
        return None
    try:
        swim_year = int(str(swim_date_iso).split("-")[0])
    except Exception:
        return None
    return swim_year - year_of_birth


# --- Regroupement fichier et batch ---


def clean_file(input_path: Path, output_path: Path) -> None:
    """Nettoie un fichier JSON liste et le regroupe au format compétition Extranat.

    Args:
        input_path (Path): Fichier JSON brut (liste de performances).
        output_path (Path): Fichier JSON de sortie (objet compétition).

    Returns:
        None

    Raises:
        ValidationError: Si le JSON ne respecte pas le schéma ``NageursList``.
        ValueError: Si la racine JSON n'est pas une liste.
    """
    try:
        records = NageursList.from_json_file(input_path)
    except ValueError as exc:
        raise ValueError(f"Le fichier {input_path} ne contient pas une liste JSON.") from exc

    cleaned_performances: List[Dict[str, Any]] = []
    for rec in records.root:
        try:
            cleaned = clean_record(rec)
        except Exception:
            cleaned = {"_raw": rec.model_dump()}
        if cleaned is None:
            continue
        cleaned_performances.append(cleaned)

    if not cleaned_performances:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        competition = {"SwimDate": None, "Meet": None, "location": None, "Country": None, "epreuves": []}
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(competition, f, ensure_ascii=False, indent=2)
        return

    meet = cleaned_performances[0].get("Meet")
    swim_date = cleaned_performances[0].get("SwimDate")
    country = next((p.get("Country") for p in cleaned_performances if p.get("Country")), None)

    # Group by (Event, Session) -> correspond au couple (Event + tour) côté Extranat.
    grouped: dict[tuple[str, Optional[str]], list[Dict[str, Any]]] = defaultdict(list)
    for p in cleaned_performances:
        grouped[(p.get("Event"), p.get("Session"))].append(p)

    epreuves: List[Dict[str, Any]] = []
    for (event, session), perfs in grouped.items():
        first = perfs[0]
        epreuve = {
            "Event": event,
            "Distance": first.get("Distance"),
            "Stroke": first.get("Stroke"),
            "Course": first.get("Course"),
            "PoolLength": first.get("PoolLength"),
            # Mapping : côté USA, `Session` correspond au "tour" (Final / Prelim / Unknown, etc.)
            "tour": session,
            "performances": [],
        }

        def _rank_key(p: Dict[str, Any]) -> Any:
            r = p.get("Rank")
            if r is None:
                return 10**12
            return r

        for perf in sorted(perfs, key=_rank_key):
            perf_name = perf.get("Name")
            if not is_valid_swimmer_name(perf_name):
                continue

            swimmer = {
                "Name": perf_name,
                "Gender": perf.get("Gender"),
                "Year_of_birth": perf.get("Year_of_birth"),
                "Age_at_Performance": _age_at_performance(perf.get("SwimDate"), perf.get("Year_of_birth")),
                "Nationality": perf.get("Nationality"),
            }

            epreuve["performances"].append(
                {
                    "Rank": perf.get("Rank"),
                    "club": perf.get("Club"),
                    "SwimTime": perf.get("SwimTime"),
                    "SwimTimeSeconds": perf.get("SwimTimeSeconds"),
                    "Status": perf.get("Status"),
                    "Speed": perf.get("Speed"),
                    "TimeStandard": perf.get("TimeStandard"),
                    "AgeGroup": perf.get("AgeGroup"),
                    "Session": perf.get("Session"),
                    "swimmer": swimmer,
                }
            )

        epreuves.append(epreuve)

    competition = {
        "SwimDate": swim_date,
        "Meet": meet,
        "location": None,
        "Country": country,
        "epreuves": epreuves,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(competition, f, ensure_ascii=False, indent=2)


def clean_usaswimming_directory() -> None:
    """Parcourt ``data/raw/usaswimming`` et écrit les JSON normalisés.

    Conserve l'arborescence des sous-dossiers (un fichier par compétition/année).

    Returns:
        None

    Raises:
        FileNotFoundError: Si le dossier source est absent.
    """
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Dossier introuvable: {DATA_DIR}")

    json_files = sorted(DATA_DIR.rglob("*.json"))
    print(f"{len(json_files)} fichiers trouvés dans {DATA_DIR} (tous sous-dossiers confondus)")

    for idx, input_path in enumerate(json_files, start=1):
        relative = input_path.relative_to(DATA_DIR)
        output_path = OUTPUT_DIR / relative
        print(f"[{idx}/{len(json_files)}] Nettoyage de {relative} -> {output_path}")
        try:
            clean_file(input_path, output_path)
        except ValidationError as exc:
            print(f"  [WARN] {relative} JSON invalide, ignoré: {exc}")
        except ValueError as exc:
            print(f"  [WARN] {relative} ignoré: {exc}")

    print(f"Nettoyage terminé. Fichiers écrits dans {OUTPUT_DIR}")


if __name__ == "__main__":
    clean_usaswimming_directory()
