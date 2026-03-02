import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USASWIMMING_DIR = PROJECT_ROOT / "app" / "data" / "usaswimming"

def main():
    json_count = 0
    total_results = 0

    for root, dirs, files in os.walk(USASWIMMING_DIR):
        for name in files:
            lower = name.lower()

            if lower.endswith(".json"):
                json_count += 1
                json_path = Path(root) / name
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        total_results += len(data)
                    else:
                        pass
                except Exception as e:
                    print(f"Erreur lecture {json_path}: {e}")

    print(f"Nombre de fichiers JSON dans {USASWIMMING_DIR}: {json_count}")
    print(f"Nombre total de résultats dans tous les JSON: {total_results}")

if __name__ == "__main__":
    main()