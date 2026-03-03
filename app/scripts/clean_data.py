import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "usaswimming"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "cleaned_data" / "usaswimming"

# Dossiers pour Extranat
EXTRANAT_BASE_DIR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "extranat"
    / "competitions_per_type"
)
EXTRANAT_OUTPUT_BASE_DIR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "cleaned_data"
    / "extranat"
    / "competitions_per_type"
)

STROKE_MAP: Dict[str, str] = {
    "FR": "Freestyle",
    "FREE": "Freestyle",
    "BK": "Backstroke",
    "BACK": "Backstroke",
    "BR": "Breaststroke",
    "BREAST": "Breaststroke",
    "FL": "Butterfly",
    "FLY": "Butterfly",
    "BUTTERFLY": "Butterfly",
    "IM": "Individual Medley",
}

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

# Normalisation des pays vers des codes à 3 lettres 
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
    """Convertit une fédération/pays (ex. "Germany") en code pays 3 lettres (ex. "GER")."""
    txt = raw.strip()
    if not txt:
        return txt

    upper = txt.upper()
    if len(upper) == 3 and upper.isalpha():
        return upper

    return COUNTRY_MAP.get(txt, txt)


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

    # Cas Extranat : formats du type "Dimanche 04/02/2024"
    m = re.search(r"(\d{2}/\d{2}/\d{4})", raw)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%d/%m/%Y")
            return dt.date().isoformat()
        except ValueError:
            pass

    return raw


def normalize_extranat_round_date(raw: str) -> str:
    """Normalise une chaîne de type "SériesDimanche 4 Février 2024"
    vers une date ISO YYYY-MM-DD en extrayant le jour, le mois et l'année."""
    text = raw.strip()
    lowered = (
        text.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ä", "a")
        .replace("ô", "o")
        .replace("ö", "o")
        .replace("ù", "u")
        .replace("û", "u")
        .replace("ü", "u")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ç", "c")
    )

    month_map = {
        "janvier": 1,
        "fevrier": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "aout": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "decembre": 12,
    }

    # Cherche un motif "4 fevrier 2024" quelque part dans la chaîne
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", lowered)
    if not m:
        return text

    day_str, month_str, year_str = m.group(1), m.group(2), m.group(3)
    month_num = month_map.get(month_str)
    if not month_num:
        return text

    try:
        dt = datetime(int(year_str), month_num, int(day_str))
        return dt.date().isoformat()
    except ValueError:
        return text


def parse_event(raw_event: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    À partir d'un Event comme "1500 FR LCM" ou "100 BK SCM",
    extrait (distance_en_m, stroke_normalisé, course_code).
    """
    if not raw_event:
        return None, None, None

    tokens = raw_event.upper().split()
    if not tokens:
        return None, None, None

    # Distance = premier token numérique
    distance: Optional[int] = None
    try:
        distance = int(tokens[0])
    except ValueError:
        distance = None

    # Course = dernier token si connu
    course: Optional[str] = None
    if tokens[-1] in COURSE_CODES:
        course = tokens[-1]

    # Stroke = premier token connu dans STROKE_MAP après la distance
    stroke_name: Optional[str] = None
    for t in tokens[1:]:
        if t in STROKE_MAP:
            stroke_name = STROKE_MAP[t]
            break

    return distance, stroke_name, course


def clean_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nettoie un enregistrement de nage :
    - Trim des strings
    - Normalisation du nom, fédération, épreuve, sexe
    - Cohérence SwimTime / SwimTimeSeconds
    - Normalisation de SwimDate
    """
    cleaned: Dict[str, Any] = {}

    name = str(rec.get("Name", "")).strip()
    federation = str(rec.get("Federation", "")).strip()
    event = str(rec.get("Event", "")).strip()
    gender = str(rec.get("Gender", "")).strip()
    meet = str(rec.get("Meet", "")).strip()
    swim_date = str(rec.get("SwimDate", "")).strip()
    swim_time_raw = rec.get("SwimTime", "")
    swim_time = str(swim_time_raw).strip()
    swim_time_seconds = rec.get("SwimTimeSeconds")

    if name:
        cleaned["Name"] = name.title()
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

    # Normalisation du genre
    g = gender.lower()
    if g in {"f", "female", "femme", "girl", "women"}:
        cleaned["Gender"] = "F"
    elif g in {"m", "male", "homme", "boy", "men"}:
        cleaned["Gender"] = "M"
    elif gender:
        cleaned["Gender"] = gender

    if swim_date:
        cleaned["SwimDate"] = normalize_date(swim_date)

    # Statut d'abord pour SwimTime
    status = compute_status_from_swim_time(swim_time_raw)

    if status == "OK" and swim_time:
        cleaned["SwimTime"] = swim_time
        computed = parse_swim_time_to_seconds(swim_time)
    else:
        # Cas DNS / DSQ / DNF / vide -> SwimTime normalisé à "NaN"
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
        # Cas DSQ / DNS / DNF / vide -> secondes null 
        cleaned["SwimTimeSeconds"] = None

    cleaned["Status"] = status

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
    la même arborescence (donc groupées par années).
    """
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Dossier introuvable: {DATA_DIR}")

    # On parcourt récursivement tous les fichiers JSON
    json_files = sorted(DATA_DIR.rglob("*.json"))
    print(f"{len(json_files)} fichiers trouvés dans {DATA_DIR} (tous sous-dossiers confondus)")

    for idx, input_path in enumerate(json_files, start=1):
        relative = input_path.relative_to(DATA_DIR)
        output_path = OUTPUT_DIR / relative
        print(f"[{idx}/{len(json_files)}] Nettoyage de {relative} -> {output_path}")
        clean_file(input_path, output_path)

    print(f"Nettoyage terminé. Fichiers écrits dans {OUTPUT_DIR}")

#  Nettoyage EXTRANAT

def parse_extranat_time_to_seconds(raw: str) -> float:
    """Convertir des temps Extranat en secondes."""
    return parse_swim_time_to_seconds(raw)


def format_extranat_event_name(raw_name: str, pool_length: Optional[int]) -> str:
    """
    Convertit un nom d'épreuve Extranat en format type "200 FR LCM".
    Exemple : "25 Nage Libre" -> "25 FR SCM" (bassin 25m).
    """
    name = raw_name.strip()
    if not name:
        return name

    # Distance = premier entier trouvé dans la chaîne
    m_dist = re.search(r"(\d+)", name)
    if not m_dist:
        return name
    distance = m_dist.group(1)

    # Normalisation simple des styles en français -> abréviations anglaises
    lowered = (
        name.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ä", "a")
        .replace("ô", "o")
        .replace("ö", "o")
        .replace("ù", "u")
        .replace("û", "u")
        .replace("ü", "u")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ç", "c")
    )

    stroke_code: Optional[str] = None
    if "nage libre" in lowered or "nl" in lowered:
        stroke_code = "FR"
    elif "dos" in lowered:
        stroke_code = "BK"
    elif "brasse" in lowered:
        stroke_code = "BR"
    elif "papillon" in lowered:
        stroke_code = "FL"
    elif "4 nages" in lowered or "quatre nages" in lowered:
        stroke_code = "IM"

    # Type de bassin 
    course_code: Optional[str] = None
    if pool_length == 25:
        course_code = "SCM"
    elif pool_length == 50:
        course_code = "LCM"

    if stroke_code and course_code:
        return f"{distance} {stroke_code} {course_code}"
    if stroke_code:
        return f"{distance} {stroke_code}"
    if course_code:
        return f"{distance} {course_code}"
    return name


def clean_extranat_competition(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nettoie la structure d'un fichier compétition Extranat.
    - Trim des chaînes
    - Ajout de pool_length_m dérivé de pool_size ("25m" -> 25, "50m" -> 50)
    - Pour chaque performance, ajout de temps en secondes (temps_seconds)
      et conversion des splits en secondes.
    """
    cleaned: Dict[str, Any] = {}

    for key, value in data.items():
        if key in {"epreuves", "original_title", "level"}:
            continue

        # Renommage du nom de la compétition en Meet
        if key == "name":
            if isinstance(value, str):
                cleaned["Meet"] = value.strip()
            else:
                cleaned["Meet"] = value
            continue

        # Extraction du code pays à partir de "location"
        if key == "location" and isinstance(value, str):
            txt = value.strip()
            cleaned["location"] = txt
            m_loc = re.search(r"\(([^)]+)\)", txt)
            if m_loc:
                country_code = m_loc.group(1).strip()
                cleaned["Country"] = normalize_country(country_code)
            continue

        # On ne conserve pas certains champs (ex: competition_id, url, results_count, filter)
        if key in {"competition_id", "url", "results_count", "filter"}:
            continue

        # Normalisation spécifique de la taille de bassin :
        if key == "pool_size":
            if isinstance(value, str):
                txt = value.strip().lower().replace(" ", "")
                if txt.startswith("25"):
                    cleaned["PoolLength"] = 25
                elif txt.startswith("50"):
                    cleaned["PoolLength"] = 50
            else:
                # Si jamais ce n'est pas une string mais déjà un nombre
                cleaned["PoolLength"] = value
            continue

        # Normalisation spécifique de la date de compétition
        if key.lower() == "date":
            if isinstance(value, str):
                cleaned["SwimDate"] = normalize_date(value)
            else:
                cleaned["SwimDate"] = str(value)
            continue

        if isinstance(value, str):
            cleaned[key] = value.strip()
        else:
            cleaned[key] = value

    # Nettoyage des épreuves et performances
    epreuves = data.get("epreuves")
    cleaned_epreuves: List[Dict[str, Any]] = []

    # On récupère la longueur de bassin déjà normalisée si disponible
    pool_length = cleaned.get("PoolLength")

    if isinstance(epreuves, list):
        for epreuve in epreuves:
            if not isinstance(epreuve, dict):
                continue

            epreuve_clean: Dict[str, Any] = {}
            for k, v in epreuve.items():
                # et on supprime certains champs d'épreuve (ex: categorie, tour)
                if k in {"performances", "categorie", "tour"}:
                    continue

                # Renommage du nom d'épreuve en Event avec formatage "200 FR LCM"
                # et gestion des relais du type "4x200 Nage Libre"
                if k == "nom" and isinstance(v, str):
                    raw_name = v
                    event_str = format_extranat_event_name(raw_name, pool_length)
                    epreuve_clean["Event"] = event_str

                    # Extraction Distance, Stroke, Course à partir de Event
                    distance, stroke_name, course = parse_event(event_str)

                    # Cas spécial relais "4x200" : Distance = 4 * 200 = 800...
                    relay_match = re.search(r"(\d+)\s*x\s*(\d+)", raw_name.replace(" ", ""))
                    if relay_match:
                        legs = int(relay_match.group(1))
                        leg_distance = int(relay_match.group(2))
                        total_distance = legs * leg_distance
                        epreuve_clean["Distance"] = total_distance
                    elif distance is not None:
                        epreuve_clean["Distance"] = distance
                    if stroke_name is not None:
                        epreuve_clean["Stroke"] = stroke_name
                    if course is not None:
                        epreuve_clean["Course"] = course
                        # Cohérence PoolLength si possible
                        if course == "SCM":
                            epreuve_clean["PoolLength"] = 25
                        elif course == "LCM":
                            epreuve_clean["PoolLength"] = 50
                        elif course == "SCY":
                            epreuve_clean["PoolLength"] = 22.86
                    continue

                if isinstance(v, str):
                    epreuve_clean[k] = v.strip()
                else:
                    epreuve_clean[k] = v

            performances = epreuve.get("performances")
            cleaned_perfs: List[Dict[str, Any]] = []
            if isinstance(performances, list):
                for perf in performances:
                    if not isinstance(perf, dict):
                        continue

                    perf_clean: Dict[str, Any] = {}
                    for pk, pv in perf.items():
                        if pk in {"splits", "temps", "nageur"}:
                            continue
                        # Renommage du classement en Rank
                        target_pk = "Rank" if pk == "classement" else pk
                        if isinstance(pv, str):
                            perf_clean[target_pk] = pv.strip()
                        else:
                            perf_clean[target_pk] = pv

                    # Temps principal
                    temps = perf.get("temps")
                    if isinstance(temps, str) and temps.strip():
                        t_txt = temps.strip()
                        status = compute_status_from_swim_time(t_txt)

                        # SwimTime & secondes normalisés suivant le statut
                        if status == "OK":
                            perf_clean["SwimTime"] = t_txt
                            perf_clean["SwimTimeSeconds"] = parse_extranat_time_to_seconds(
                                t_txt
                            )
                        else:
                            perf_clean["SwimTime"] = "NaN"
                            perf_clean["SwimTimeSeconds"] = None

                        perf_clean["Status"] = status
                    else:
                        # Pas de temps renseigné
                        perf_clean["SwimTime"] = "NaN"
                        perf_clean["SwimTimeSeconds"] = None
                        perf_clean["Status"] = compute_status_from_swim_time("")

                    # Infos nageur / nageurs 
                    nageur = perf.get("nageur")
                    swimmers: List[Dict[str, Any]] = []
                    # Cas 1 : un seul nageur (dict)
                    if isinstance(nageur, dict):
                        nageurs_iter = [nageur]
                    # Cas 2 : plusieurs nageurs (liste de dicts)
                    elif isinstance(nageur, list):
                        nageurs_iter = [n for n in nageur if isinstance(n, dict)]
                    else:
                        nageurs_iter = []

                    for n in nageurs_iter:
                        nageur_clean: Dict[str, Any] = {}
                        name = n.get("name")
                        if isinstance(name, str):
                            nageur_clean["Name"] = name.strip().title()
                        sexe = n.get("sexe")
                        if isinstance(sexe, str):
                            nageur_clean["Gender"] = sexe.strip().upper()
                        # Année de naissance
                        if "annee_naissance" in n:
                            nageur_clean["Year_of_birth"] = n["annee_naissance"]
                        # Nationalité
                        if "nationalite" in n:
                            nageur_clean["Nationality"] = n["nationalite"]
                        swimmers.append(nageur_clean)

                    if swimmers:
                        # Si un seul nageur, on garde un objet ; sinon une liste
                        perf_clean["swimmer"] = swimmers[0] if len(swimmers) == 1 else swimmers

                    # Splits
                    splits = perf.get("splits")
                    cleaned_splits: List[Dict[str, Any]] = []
                    if isinstance(splits, list):
                        for split in splits:
                            if not isinstance(split, dict):
                                continue
                            split_clean: Dict[str, Any] = {}
                            for sk, sv in split.items():
                                # Renommage de "distance" en "SplitDistance" pour plus de clarté
                                if sk == "distance":
                                    if isinstance(sv, str):
                                        split_clean["SplitDistance"] = sv.strip()
                                    else:
                                        split_clean["SplitDistance"] = sv
                                    continue

                                if isinstance(sv, str):
                                    split_clean[sk] = sv.strip()
                                else:
                                    split_clean[sk] = sv

                            cumul = split.get("cumul")
                            if isinstance(cumul, str) and cumul.strip():
                                split_clean["cumul_seconds"] = parse_extranat_time_to_seconds(
                                    cumul
                                )
                            split_time = split.get("split")
                            if isinstance(split_time, str) and split_time.strip():
                                split_clean["split_seconds"] = parse_extranat_time_to_seconds(
                                    split_time
                                )

                            cleaned_splits.append(split_clean)

                    if cleaned_splits:
                        perf_clean["splits"] = cleaned_splits

                    cleaned_perfs.append(perf_clean)

            epreuve_clean["performances"] = cleaned_perfs
            cleaned_epreuves.append(epreuve_clean)

    cleaned["epreuves"] = cleaned_epreuves
    return cleaned


def clean_extranat_directory() -> None:
    """
    Parcourt tous les fichiers JSON sous
    data/extranat/competitions_per_type
    et écrit des versions nettoyées sous
    data/clean_data/extranat/competitions_per_type
    en conservant la même arborescence.
    """
    base_dir = EXTRANAT_BASE_DIR
    out_base = EXTRANAT_OUTPUT_BASE_DIR

    if not base_dir.exists() or not base_dir.is_dir():
        print(f"Dossier Extranat introuvable: {base_dir}")
        return

    json_files = sorted(base_dir.rglob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON Extranat trouvé dans {base_dir}")
        return

    print(f"{len(json_files)} fichiers Extranat trouvés dans {base_dir}")

    for idx, input_path in enumerate(json_files, start=1):
        relative = input_path.relative_to(base_dir)
        output_path = out_base / relative
        print(f"[{idx}/{len(json_files)}] Nettoyage Extranat de {relative} -> {output_path}")

        with input_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            print(f"  [WARN] {relative} ne contient pas un objet JSON racine, ignoré.")
            continue

        cleaned = clean_extranat_competition(raw)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f_out:
            json.dump(cleaned, f_out, ensure_ascii=False, indent=2)

    print(f"Nettoyage Extranat terminé. Fichiers écrits dans {out_base}")


if __name__ == "__main__":
    clean_usaswimming_directory()
    clean_extranat_directory()
