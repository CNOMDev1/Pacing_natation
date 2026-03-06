from pathlib import Path

BASE_DIR = Path(
    "/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/cleaned_data/extranat/competitions_per_type"
)

TARGET = "(temps des séries + temps des finales)= temps cumulés"


def main():
    if not BASE_DIR.exists():
        print(f"Dossier introuvable : {BASE_DIR}")
        return

    json_files = sorted(BASE_DIR.rglob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans {BASE_DIR}")
        return

    print(f"Recherche de {TARGET!r} dans {len(json_files)} fichiers...\n")
    found_any = False

    for fpath in json_files:
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[ERREUR] Impossible de lire {fpath}: {e}")
            continue

        if TARGET in text:
            found_any = True
            print(f"- {fpath}")

    if not found_any:
        print("Aucun fichier ne contient cette chaîne.")


if __name__ == "__main__":
    main()