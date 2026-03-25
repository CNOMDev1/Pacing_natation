import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "usaswimming"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "cleaned_data" / "usaswimming"

COURSE_CODES = {"LCM", "SCM", "SCY"}


def compute_status_from_swim_time(swim_time: Any) -> str:
    """Détermine le statut à partir de la valeur de SwimTime."""
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
    """Convertit une fédération/pays en code pays 3 lettres."""
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
    """
    À partir d'un nom éventuellement enrichi,
    renvoie (nom_nettoyé, année_naissance, nationalité).
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


def parse_swim_time_to_seconds(raw: str) -> float:
    """
    Convert a time to seconds.
    Returns float("nan") if format is not recognized.
    """
    raw = raw.strip()
    mm_ss = re.match(r"^(\d+):(\d{1,2}\.\d+)$", raw)
    if mm_ss:
        minutes = int(mm_ss.group(1))
        seconds = float(mm_ss.group(2))
        return minutes * 60 + seconds

    ss = re.match(r"^(\d+\.\d+)$", raw)
    if ss:
        return float(ss.group(1))

    plain = re.match(r"^(\d+)$", raw)
    if plain:
        return float(plain.group(1))

    return float("nan")


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


def parse_event(raw_event: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    À partir d'un Event comme "1500 FR LCM" ou "100 BK SCM",
    extrait (distance_en_m, stroke_code, course_code).
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


def clean_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Nettoie un enregistrement USA Swimming."""
    cleaned: Dict[str, Any] = {}

    name = str(rec.get("Name", "")).strip()
    year_of_birth_raw = rec.get("Year_of_birth")
    nationality_raw = rec.get("Nationality")
    federation = str(rec.get("Federation", "")).strip()
    event = str(rec.get("Event", "")).strip()
    gender = str(rec.get("Gender", "")).strip()
    meet = str(rec.get("Meet", "")).strip()
    swim_date = str(rec.get("SwimDate", "")).strip()
    swim_time_raw = rec.get("SwimTime", "")
    swim_time = str(swim_time_raw).strip()
    swim_time_seconds = rec.get("SwimTimeSeconds")

    base_name, inferred_year, inferred_nat = parse_name_year_nationality(name)
    if base_name:
        name = base_name

    if name:
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
        elif "Year_of_birth" in rec:
            cleaned["Year_of_birth"] = None
    elif "Year_of_birth" in rec:
        cleaned["Year_of_birth"] = None

    nat_value = nationality_raw or inferred_nat
    if isinstance(nat_value, str) and nat_value.strip():
        cleaned["Nationality"] = nat_value.strip().upper()
    elif "Nationality" in rec:
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


def clean_file(input_path: Path, output_path: Path) -> None:
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Le fichier {input_path} ne contient pas une liste JSON.")

    cleaned_records: List[Dict[str, Any]] = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        cleaned = clean_record(rec)

        if not cleaned.get("Name") or not cleaned.get("Event") or not cleaned.get("SwimTimeSeconds"):
            continue

        cleaned_records.append(cleaned)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(cleaned_records, f, ensure_ascii=False, indent=2)


def clean_usaswimming_directory() -> None:
    """
    Parcourt tous les fichiers JSON sous data/usaswimming et écrit les données
    nettoyées dans data/cleaned_data/usaswimming en conservant
    la même arborescence.
    """
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Dossier introuvable: {DATA_DIR}")

    json_files = sorted(DATA_DIR.rglob("*.json"))
    print(f"{len(json_files)} fichiers trouvés dans {DATA_DIR} (tous sous-dossiers confondus)")

    for idx, input_path in enumerate(json_files, start=1):
        relative = input_path.relative_to(DATA_DIR)
        output_path = OUTPUT_DIR / relative
        print(f"[{idx}/{len(json_files)}] Nettoyage de {relative} -> {output_path}")
        clean_file(input_path, output_path)

    print(f"Nettoyage terminé. Fichiers écrits dans {OUTPUT_DIR}")


if __name__ == "__main__":
    clean_usaswimming_directory()
