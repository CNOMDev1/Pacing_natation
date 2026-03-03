"""
Compte le nombre de valeurs vides ou nulles dans les fichiers JSON
du dossier `app/data/usaswimming`.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Tuple


def is_empty_value(value: Any) -> bool:
    """Retourne True si la valeur est considérée comme vide."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def analyse_file(json_path: Path) -> Tuple[int, Counter[str]]:
    """
    Analyse un fichier JSON de usaswimming.

    Retourne :
    - nombre d'enregistrements (éléments de la liste)
    - Counter des valeurs vides par champ
    """
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Erreur lors de la lecture de {json_path}: {e}")
        return 0, Counter()

    if not isinstance(data, list):
        print(f"  [WARN] {json_path.name} ne contient pas une liste JSON, ignoré.")
        return 0, Counter()

    missing_counts: Counter[str] = Counter()
    record_count = 0

    for rec in data:
        if not isinstance(rec, dict):
            continue
        record_count += 1

        for key, value in rec.items():
            if is_empty_value(value):
                missing_counts[key] += 1

    return record_count, missing_counts


def main() -> None:
    base_dir = (
        Path(__file__)
        .resolve()
        .parent  # scripts
        .parent  # app
        / "data"
        / "usaswimming"
    )

    if not base_dir.exists() or not base_dir.is_dir():
        print(f"Le dossier '{base_dir}' n'existe pas ou n'est pas un dossier.")
        return

    json_files = sorted(p for p in base_dir.iterdir() if p.is_file() and p.suffix.lower() == ".json")
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans '{base_dir}'.")
        return

    print(f"{len(json_files)} fichiers JSON trouvés dans {base_dir}\n")

    global_records = 0
    global_missing: Counter[str] = Counter()

    for json_file in json_files:
        record_count, missing_counts = analyse_file(json_file)
        global_records += record_count
        global_missing.update(missing_counts)

        if record_count == 0:
            print(f"{json_file.name:60s} : 0 enregistrement, ignoré")
            continue

        total_missing = sum(missing_counts.values())
        print(f"{json_file.name:60s} : {record_count:5d} enreg. | {total_missing:5d} valeurs vides")

    print("\n" + "-" * 80)
    print(f"TOTAL ENREGISTREMENTS (tous fichiers) : {global_records}")
    print("VALEURS VIDES / NULL PAR CHAMP (global) :")

    if global_records == 0:
        print("  Aucun enregistrement trouvé.")
        return

    # Tri des champs par nombre décroissant de valeurs manquantes
    for field, count in global_missing.most_common():
        pourcentage = (count / global_records) * 100
        print(f"  {field:25s} : {count:7d} manquantes ({pourcentage:6.2f} % des enregistrements)")


if __name__ == "__main__":
    main()

