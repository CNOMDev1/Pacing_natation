import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USASWIMMING_DIR = PROJECT_ROOT / "app" / "data" / "usaswimming"

def main():
    total_results = 0
    per_dir_counts = {}

    for root, dirs, files in os.walk(USASWIMMING_DIR):
        root_path = Path(root)
        # clé: chemin relatif à USASWIMMING_DIR ("" pour la racine)
        rel = root_path.relative_to(USASWIMMING_DIR)
        key = "." if str(rel) == "." else str(rel)

        json_count = 0

        for name in files:
            if not name.lower().endswith(".json"):
                continue

            json_count += 1
            json_path = root_path / name
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    total_results += len(data)
            except Exception as e:
                print(f"Erreur lecture {json_path}: {e}")

        if json_count > 0:
            per_dir_counts[key] = per_dir_counts.get(key, 0) + json_count

    total_json_files = sum(per_dir_counts.values())
    print(f"Nombre total de fichiers JSON: {total_json_files}")
    print(f"Nombre total de résultats dans tous les JSON: {total_results}")
    print("\nNombre de fichiers JSON par dossier (relatif à data/usaswimming):")
    for folder in sorted(per_dir_counts):
        print(f"{folder} {per_dir_counts[folder]}")

if __name__ == "__main__":
    main()