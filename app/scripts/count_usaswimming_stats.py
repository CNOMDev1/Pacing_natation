"""
Compte le nombre de fichiers JSON et le nombre total de résultats
dans app/data/usaswimming.
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USASWIMMING_DIR = PROJECT_ROOT / "app" / "data" / "usaswimming"


def count_usaswimming_stats() -> tuple[int, int]:
    """
    Parcourt app/data/usaswimming et retourne (nb_fichiers_json, nb_resultats).
    Exclut _index.json. Chaque élément d'une liste JSON compte pour 1 résultat.
    """
    if not USASWIMMING_DIR.exists():
        return 0, 0

    nb_files = 0
    nb_results = 0

    for path in sorted(USASWIMMING_DIR.rglob("*.json")):
        if path.name == "_index.json":
            continue

        nb_files += 1
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if isinstance(data, list):
            nb_results += len(data)
        else:
            nb_results += 1

    return nb_files, nb_results


def main() -> None:
    print(f"Dossier : {USASWIMMING_DIR}")
    if not USASWIMMING_DIR.exists():
        print("Le dossier n'existe pas.")
        return

    nb_files, nb_results = count_usaswimming_stats()
    print(f"Nombre de fichiers JSON (hors _index.json) : {nb_files}")
    print(f"Nombre total de résultats : {nb_results}")


if __name__ == "__main__":
    main()
