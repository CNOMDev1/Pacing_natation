import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USASWIMMING_DIR = PROJECT_ROOT / "app" / "data" / "usaswimming"
FUSION_DIR = PROJECT_ROOT / "app" / "data" / "fusion_usaswimming"
OUTPUT_FILE = FUSION_DIR / "merged_usaswimming.json"


def merge_json_files() -> None:
    all_records = []

    # S'assurer que le dossier de sortie existe
    FUSION_DIR.mkdir(parents=True, exist_ok=True)

    for root, _, files in os.walk(USASWIMMING_DIR):
        for name in files:
            if not name.lower().endswith(".json"):
                continue

            # Exclure l'index et le fichier de sortie lui-même
            if name == "_index.json" or name == OUTPUT_FILE.name:
                continue

            path = Path(root) / name

            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Impossible de lire {path}: {e}")
                continue

            # Chaque fichier semble contenir une liste d'objets
            if isinstance(data, list):
                all_records.extend(data)
            else:
                all_records.append(data)

    try:
        with OUTPUT_FILE.open("w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)
        print(f"{len(all_records)} enregistrements écrits dans {OUTPUT_FILE}")
    except Exception as e:
        print(f"Erreur d'écriture du fichier de sortie {OUTPUT_FILE}: {e}")


def main() -> None:
    print(f"Fusion de tous les JSON de {USASWIMMING_DIR} (sauf '_index.json') dans {OUTPUT_FILE}")
    merge_json_files()


if __name__ == "__main__":
    main()

