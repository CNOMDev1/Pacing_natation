from pathlib import Path
import json
from collections import Counter
from typing import Set


def list_distinct_federations() -> None:
    """
    Parcourt tous les fichiers JSON nettoyés sous
    data/cleaned_data/usaswimming et affiche toutes les
    valeurs distinctes de Federation.
    """
    base_dir = Path(__file__).resolve().parents[1] / "data" / "cleaned_data" / "usaswimming"

    if not base_dir.exists():
        raise FileNotFoundError(f"Dossier introuvable : {base_dir}")

    federations: Set[str] = set()
    freq = Counter()
    empty_count = 0

    json_files = sorted(base_dir.rglob("*.json"))
    print(f"{len(json_files)} fichiers trouvés sous {base_dir}")

    for path in json_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARN] Impossible de lire {path}: {e}")
            continue

        if not isinstance(data, list):
            print(f"[WARN] {path} ne contient pas une liste JSON, ignoré.")
            continue

        for rec in data:
            if not isinstance(rec, dict):
                continue
            federation = rec.get("Federation")
            if federation is None or str(federation).strip() == "":
                empty_count += 1
            else:
                fed_clean = str(federation).strip()
                federations.add(fed_clean)
                freq[fed_clean] += 1

    print("\nFederations distinctes non vides (avec nombre d'apparitions):\n")
    for fed in sorted(federations):
        print(f"{fed} {freq[fed]}")

    total_non_empty = sum(freq.values())
    print(f"\nNombre total d'enregistrements avec Federation non vide : {total_non_empty}")
    print(f"Nombre d'enregistrements avec Federation vide ou manquante : {empty_count}")


if __name__ == "__main__":
    list_distinct_federations()

