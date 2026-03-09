import json
import re
from pathlib import Path
from collections import Counter
from typing import Any, Dict

# Chemin de base donné dans ta question
BASE_DIR = Path(
    "/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/cleaned_data/extranat/competitions_per_type"
)


def strip_age_from_tour(raw: str) -> str:
    """
    Nettoie une valeur de 'tour' pour supprimer les âges,
    par ex. "Barrage Finales : 15-18 ans" -> "Barrage Finales".
    """
    text = str(raw).strip()
    if not text:
        return text

    # Supprime " : 15-18 ans", " : 17 ans et plus", " : 16 ans et moins", etc.
    text_no_age = re.sub(
        r"\s*:?\s*\d+\s*(?:-\s*\d+)?\s*ans(?:\s+(?:et\s+plus|et\s+moins))?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text_no_age

def iter_tour_fields(obj: Any, current_path: str = ""):
    """
    Générateur qui parcourt récursivement un objet JSON
    et renvoie (json_path, valeur) pour chaque clé 'tour'.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{current_path}.{k}" if current_path else k
            if k == "tour":
                yield new_path, v
            # Continuer la recherche en profondeur
            yield from iter_tour_fields(v, new_path)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_path = f"{current_path}[{idx}]"
            yield from iter_tour_fields(item, new_path)


def main():
    if not BASE_DIR.exists():
        print(f"Dossier introuvable : {BASE_DIR}")
        return

    json_files = sorted(BASE_DIR.rglob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans {BASE_DIR}")
        return

    tour_counter = Counter()

    for fpath in json_files:
        try:
            with fpath.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ERREUR] Impossible de lire {fpath}: {e}")
            continue

        for json_path, value in iter_tour_fields(data):
            cleaned_value = strip_age_from_tour(value)
            print(f"Fichier: {fpath}")
            print(f"Chemin JSON: {json_path}")
            print(f"tour = {cleaned_value!r}")
            print("-" * 80)
            tour_counter[str(cleaned_value)] += 1

    print("\n=== RÉSUMÉ DES VALEURS DE 'tour' ===")
    for val, count in tour_counter.most_common():
        print(f"{val!r}: {count} occurrence(s)")


if __name__ == "__main__":
    main()