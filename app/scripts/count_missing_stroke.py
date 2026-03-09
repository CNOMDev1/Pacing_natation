import json
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
EXTRANAT_OUTPUT_BASE_DIR = (
    BASE_DIR / "data" / "cleaned_data" / "extranat" / "competitions_per_type"
)

JSONDict = Dict[str, Any]


def count_epreuves_without_stroke() -> None:
    """
    Compte le nombre d'épreuves (epreuves) qui n'ont pas de propriété Stroke
    ou dont Stroke est vide, sur l'ensemble des fichiers Extranat nettoyés.
    """
    if not EXTRANAT_OUTPUT_BASE_DIR.exists():
        print(f"Dossier introuvable : {EXTRANAT_OUTPUT_BASE_DIR}")
        return

    json_files = sorted(EXTRANAT_OUTPUT_BASE_DIR.rglob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans {EXTRANAT_OUTPUT_BASE_DIR}")
        return

    total_epreuves = 0
    missing_stroke = 0
    per_file_events: Dict[str, List[str]] = {}

    for path in json_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[WARN] Impossible de lire {path}: {exc}")
            continue

        if not isinstance(data, dict):
            continue

        epreuves = data.get("epreuves")
        if not isinstance(epreuves, list):
            continue

        for epreuve in epreuves:
            if not isinstance(epreuve, dict):
                continue

            total_epreuves += 1
            stroke = epreuve.get("Stroke")
            if stroke is None or (isinstance(stroke, str) and not stroke.strip()):
                missing_stroke += 1
                rel_path = str(path.relative_to(EXTRANAT_OUTPUT_BASE_DIR))
                event_val = epreuve.get("Event")
                if isinstance(event_val, str) and event_val.strip():
                    event_str = event_val.strip()
                else:
                    event_str = "<Event manquant>"
                per_file_events.setdefault(rel_path, []).append(event_str)

    print(f"Total epreuves: {total_epreuves}")
    print(f"Epreuves sans propriété Stroke: {missing_stroke}")
    if total_epreuves:
        pct = missing_stroke * 100.0 / total_epreuves
        print(f"Pourcentage sans Stroke: {pct:.2f}%")

    if per_file_events:
        print(
            f"\nFichiers contenant au moins une epreuve sans Stroke ({len(per_file_events)} fichiers) :"
        )
        for rel_path, events in sorted(per_file_events.items(), key=lambda x: -len(x[1])):
            print(f"  - {rel_path}: {len(events)} epreuve(s) sans Stroke")
            for ev in events:
                print(f"      * Event: {ev}")

            distinct_events = sorted(set(events))
            print("      Events distincts sans Stroke:")
            for ev in distinct_events:
                print(f"        - {ev}")


if __name__ == "__main__":
    count_epreuves_without_stroke()

