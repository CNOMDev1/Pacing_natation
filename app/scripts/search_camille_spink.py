import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USASWIMMING_DIR = PROJECT_ROOT / "app" / "data" / "usaswimming"

SEARCH_TERMS = ["Yannick Agnel"]

TOTAL_CAMILLE_SPINK = 0


def file_contains_terms(path: Path) -> bool:
    global TOTAL_CAMILLE_SPINK

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Erreur de lecture du fichier {path}: {e}")
        return False

    lower_text = text.lower()
    found = False

    for term in SEARCH_TERMS:
        term_lower = term.lower()
        count = lower_text.count(term_lower)
        if count > 0:
            print(f"- Terme '{term}' trouvé {count} fois dans: {path}")
            found = True

            if term == "Camille Spink":
                TOTAL_CAMILLE_SPINK += count

    return found


def main():
    print(f"Recherche des termes {SEARCH_TERMS} dans {USASWIMMING_DIR}")

    matches = 0
    total_files = 0

    for root, dirs, files in os.walk(USASWIMMING_DIR):
        for name in files:
            if not name.lower().endswith(".json"):
                continue

            total_files += 1
            json_path = Path(root) / name

            if file_contains_terms(json_path):
                matches += 1

    print()
    print(f"Fichiers JSON scannés : {total_files}")
    print(f"Fichiers contenant au moins un terme : {matches}")
    print(f"Nombre total d'occurrences de 'Camille Spink' : {TOTAL_CAMILLE_SPINK}")


if __name__ == "__main__":
    main()

