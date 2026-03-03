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


def parse_swim_time_to_seconds(raw: str) -> float:
    """
    Convert a time string like "4:17.23" or "56.49" to seconds.
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
    """
    Normalise SwimDate en ISO YYYY-MM-DD (sans l'heure).
    Si le parsing échoue, renvoie la chaîne originale stripée.
    """
    raw = raw.strip()
    # Exemple actuel: "2018-11-04T00:00:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    return raw


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
    swim_time = str(rec.get("SwimTime", "")).strip()
    swim_time_seconds = rec.get("SwimTimeSeconds")

    if name:
        cleaned["Name"] = name.title()
    if federation:
        cleaned["Federation"] = federation.title()
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

    if swim_time:
        cleaned["SwimTime"] = swim_time
        computed = parse_swim_time_to_seconds(swim_time)
    else:
        computed = float("nan")

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
    Parcourt tous les fichiers JSON de data/usaswimming
    et écrit les données nettoyées dans data/cleaned_data/usaswimming
    """
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Dossier introuvable: {DATA_DIR}")

    json_files = sorted(DATA_DIR.glob("*.json"))
    print(f"{len(json_files)} fichiers trouvés dans {DATA_DIR}")

    for idx, input_path in enumerate(json_files, start=1):
        relative_name = input_path.name
        output_path = OUTPUT_DIR / relative_name
        print(f"[{idx}/{len(json_files)}] Nettoyage de {relative_name} -> {output_path}")
        clean_file(input_path, output_path)

    print(f"Nettoyage terminé. Fichiers écrits dans {OUTPUT_DIR}")


# =========================
#  Nettoyage EXTRANAT
# =========================

def parse_extranat_time_to_seconds(raw: str) -> float:
    """
    Réutilise la même logique que pour parse_swim_time_to_seconds
    pour convertir des temps Extranat ("02:19.31", "31.39", etc.) en secondes.
    """
    return parse_swim_time_to_seconds(raw)


def clean_extranat_competition(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nettoie la structure d'un fichier compétition Extranat.
    - Trim des chaînes
    - Ajout de pool_length_m dérivé de pool_size ("25m" -> 25, "50m" -> 50)
    - Pour chaque performance, ajout de temps en secondes (temps_seconds)
      et conversion des splits en secondes.
    """
    cleaned: Dict[str, Any] = {}

    # Copie / trim des champs simples
    for key, value in data.items():
        if key == "epreuves":
            # on traite après
            continue
        if isinstance(value, str):
            cleaned[key] = value.strip()
        else:
            cleaned[key] = value

    # pool_size -> pool_length_m
    pool_size = data.get("pool_size")
    if isinstance(pool_size, str):
        txt = pool_size.strip().lower().replace(" ", "")
        if txt.startswith("25"):
            cleaned["pool_length_m"] = 25
        elif txt.startswith("50"):
            cleaned["pool_length_m"] = 50

    # Nettoyage des épreuves et performances
    epreuves = data.get("epreuves")
    cleaned_epreuves: List[Dict[str, Any]] = []

    if isinstance(epreuves, list):
        for epreuve in epreuves:
            if not isinstance(epreuve, dict):
                continue

            epreuve_clean: Dict[str, Any] = {}
            for k, v in epreuve.items():
                if k == "performances":
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
                        if pk in {"splits"}:
                            continue
                        if isinstance(pv, str):
                            perf_clean[pk] = pv.strip()
                        else:
                            perf_clean[pk] = pv

                    # Temps principal
                    temps = perf.get("temps")
                    if isinstance(temps, str) and temps.strip():
                        perf_clean["temps"] = temps.strip()
                        perf_clean["temps_seconds"] = parse_extranat_time_to_seconds(
                            temps
                        )

                    # Infos nageur (on normalise un peu le nom / sexe)
                    nageur = perf.get("nageur")
                    if isinstance(nageur, dict):
                        nageur_clean: Dict[str, Any] = {}
                        name = nageur.get("name")
                        if isinstance(name, str):
                            nageur_clean["name"] = name.strip().title()
                        sexe = nageur.get("sexe")
                        if isinstance(sexe, str):
                            nageur_clean["sexe"] = sexe.strip().upper()
                        for nk in ["annee_naissance", "age", "nationalite"]:
                            if nk in nageur:
                                nageur_clean[nk] = nageur[nk]
                        perf_clean["nageur"] = nageur_clean

                    # Splits
                    splits = perf.get("splits")
                    cleaned_splits: List[Dict[str, Any]] = []
                    if isinstance(splits, list):
                        for split in splits:
                            if not isinstance(split, dict):
                                continue
                            split_clean: Dict[str, Any] = {}
                            for sk, sv in split.items():
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
