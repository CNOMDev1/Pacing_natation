"""
Fonctions de préparation de données (feature engineering) pour les jeux
`usaswimming` et `extranat`.

Ici, on se concentre sur la création de variables dérivées à partir de
champs déjà nettoyés (distance, style, type de bassin, temps en secondes,
etc.), en laissant le nettoyage de base (trim, valeurs manquantes, formats)
dans `clean_data.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BASE_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

CLEAN_USASWIMMING_DIR = BASE_DATA_DIR / "cleaned_data" / "usaswimming"

CLEAN_EXTRANAT_BASE_DIR = (
    BASE_DATA_DIR / "cleaned_data" / "extranat" / "competitions_per_type"
)
PREP_EXTRANAT_BASE_DIR = (
    BASE_DATA_DIR / "prepared_data" / "extranat" / "competitions_per_type"
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
    Convertit un temps texte de natation en secondes.
    Exemples acceptés :
    - "4:17.23" -> 257.23
    - "56.49"   -> 56.49
    - "56"      -> 56.0
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

    distance: Optional[int] = None
    try:
        distance = int(tokens[0])
    except ValueError:
        distance = None

    course: Optional[str] = None
    if tokens[-1] in COURSE_CODES:
        course = tokens[-1]

    stroke_name: Optional[str] = None
    for t in tokens[1:]:
        if t in STROKE_MAP:
            stroke_name = STROKE_MAP[t]
            break

    return distance, stroke_name, course


# ---------------------------------------------------------------------------
# Préparation pour usaswimming
# ---------------------------------------------------------------------------

def add_usaswimming_features(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ajoute des variables dérivées à un enregistrement usaswimming déjà
    nettoyé (par exemple par `clean_data.clean_record`).

    - Distance, Stroke, Course, PoolLength à partir de Event
    - SwimTimeSeconds à partir de SwimTime (si absent ou incohérent)
    """
    enriched = dict(record)

    event = str(enriched.get("Event", "")).strip()
    swim_time = str(enriched.get("SwimTime", "")).strip()
    swim_time_seconds = enriched.get("SwimTimeSeconds")

    # Variables dérivées à partir de Event
    if event:
        distance, stroke_name, course = parse_event(event)
        if distance is not None:
            enriched["Distance"] = distance
        if stroke_name is not None:
            enriched["Stroke"] = stroke_name
        if course is not None:
            enriched["Course"] = course
            if course == "SCM":
                enriched["PoolLength"] = 25
            elif course == "LCM":
                enriched["PoolLength"] = 50
            elif course == "SCY":
                enriched["PoolLength"] = 22.86

    # Cohérence / création de SwimTimeSeconds
    computed = float("nan")
    if swim_time:
        computed = parse_swim_time_to_seconds(swim_time)

    if swim_time_seconds is not None:
        try:
            original_seconds = float(swim_time_seconds)
        except (TypeError, ValueError):
            original_seconds = float("nan")
    else:
        original_seconds = float("nan")

    chosen_seconds = original_seconds
    if not (isinstance(original_seconds, float) and original_seconds != original_seconds):
        chosen_seconds = original_seconds
    elif not (isinstance(computed, float) and computed != computed):
        chosen_seconds = computed

    if isinstance(chosen_seconds, float) and not (chosen_seconds != chosen_seconds):
        enriched["SwimTimeSeconds"] = round(chosen_seconds, 2)

    return enriched


def add_extranat_features(competition: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ajoute des variables dérivées à un objet compétition Extranat déjà
    nettoyé (structure avec 'pool_size', 'epreuves', 'performances', etc.).

    - pool_length_m à partir de pool_size ("25m" -> 25, "50m" -> 50)
    - temps_seconds pour chaque performance
    - cumul_seconds et split_seconds pour chaque split
    """
    enriched: Dict[str, Any] = dict(competition)

    pool_size = competition.get("pool_size")
    if isinstance(pool_size, str):
        txt = pool_size.strip().lower().replace(" ", "")
        if txt.startswith("25"):
            enriched["pool_length_m"] = 25
        elif txt.startswith("50"):
            enriched["pool_length_m"] = 50

    epreuves = competition.get("epreuves")
    new_epreuves: List[Dict[str, Any]] = []

    if isinstance(epreuves, list):
        for epreuve in epreuves:
            if not isinstance(epreuve, dict):
                continue

            epreuve_copy: Dict[str, Any] = dict(epreuve)
            performances = epreuve.get("performances")
            new_perfs: List[Dict[str, Any]] = []

            if isinstance(performances, list):
                for perf in performances:
                    if not isinstance(perf, dict):
                        continue

                    perf_copy: Dict[str, Any] = dict(perf)
                    temps = perf.get("temps")
                    if isinstance(temps, str) and temps.strip():
                        perf_copy["temps_seconds"] = parse_swim_time_to_seconds(temps)

                    splits = perf.get("splits")
                    new_splits: List[Dict[str, Any]] = []
                    if isinstance(splits, list):
                        for split in splits:
                            if not isinstance(split, dict):
                                continue
                            split_copy: Dict[str, Any] = dict(split)

                            cumul = split.get("cumul")
                            if isinstance(cumul, str) and cumul.strip():
                                split_copy["cumul_seconds"] = parse_swim_time_to_seconds(
                                    cumul
                                )
                            split_time = split.get("split")
                            if isinstance(split_time, str) and split_time.strip():
                                split_copy["split_seconds"] = parse_swim_time_to_seconds(
                                    split_time
                                )

                            new_splits.append(split_copy)

                    if new_splits:
                        perf_copy["splits"] = new_splits

                    new_perfs.append(perf_copy)

            epreuve_copy["performances"] = new_perfs
            new_epreuves.append(epreuve_copy)

    enriched["epreuves"] = new_epreuves
    return enriched


def prepare_usaswimming_directory() -> None:
    """
    Lit les fichiers JSON déjà nettoyés dans
    `data/cleaned_data/usaswimming`, ajoute les features usaswimming
    puis enregistre les fichiers enrichis dans
    `data/prepared_data/usaswimming` avec les mêmes noms.
    """
    if not CLEAN_USASWIMMING_DIR.exists():
        print(f"Dossier introuvable : {CLEAN_USASWIMMING_DIR}")
        return

    json_files = sorted(CLEAN_USASWIMMING_DIR.glob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON dans {CLEAN_USASWIMMING_DIR}")
        return

    print(f"{len(json_files)} fichiers usaswimming nettoyés trouvés dans {CLEAN_USASWIMMING_DIR}")

    for idx, input_path in enumerate(json_files, start=1):
        output_path = PREP_USASWIMMING_DIR / input_path.name
        print(f"[USASW {idx}/{len(json_files)}] Préparation de {input_path.name} -> {output_path}")

        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print(f"  [WARN] {input_path.name} ne contient pas une liste JSON, ignoré.")
            continue

        prepared_records: List[Dict[str, Any]] = []
        for rec in data:
            if not isinstance(rec, dict):
                continue
            prepared_records.append(add_usaswimming_features(rec))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f_out:
            json.dump(prepared_records, f_out, ensure_ascii=False, indent=2)


def prepare_extranat_directory() -> None:
    """
    Lit les fichiers JSON de compétitions déjà nettoyés dans
    `data/cleaned_data/extranat/competitions_per_type/**.json`,
    ajoute les features Extranat et enregistre les fichiers enrichis
    dans `data/prepared_data/extranat/competitions_per_type/**.json`
    en conservant la même arborescence.
    """
    base_dir = CLEAN_EXTRANAT_BASE_DIR
    out_base = PREP_EXTRANAT_BASE_DIR

    if not base_dir.exists():
        print(f"Dossier Extranat nettoyé introuvable : {base_dir}")
        return

    json_files = sorted(base_dir.rglob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON Extranat dans {base_dir}")
        return

    print(f"{len(json_files)} fichiers Extranat nettoyés trouvés dans {base_dir}")

    for idx, input_path in enumerate(json_files, start=1):
        relative = input_path.relative_to(base_dir)
        output_path = out_base / relative
        print(f"[EXTRA {idx}/{len(json_files)}] Préparation de {relative} -> {output_path}")

        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            print(f"  [WARN] {relative} ne contient pas un objet JSON racine, ignoré.")
            continue

        prepared = add_extranat_features(data)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f_out:
            json.dump(prepared, f_out, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    prepare_usaswimming_directory()
    prepare_extranat_directory()


