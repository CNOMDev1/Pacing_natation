import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parents[1]
EXTRANAT_OUTPUT_BASE_DIR = (
    BASE_DIR / "data" / "cleaned_data" / "extranat" / "competitions_per_type"
)

JSONDict = Dict[str, Any]


def find_line_numbers_for_null_speed(
    file_path: Path, markers: List[Tuple[Optional[str], Optional[int]]]
) -> List[Tuple[Optional[str], Optional[int], Optional[int]]]:
    """
    Pour chaque performance avec Speed null, essaie de retrouver une ligne
    représentative dans le JSON, en se basant surtout sur SwimTime (et Rank si dispo),
    en privilégiant un bloc qui ne contient pas de champ "Speed".
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return [(swim_time, rank, None) for swim_time, rank in markers]

    lines = text.splitlines()
    results: List[Tuple[Optional[str], Optional[int], Optional[int]]] = []

    search_start = 0

    for swim_time, rank in markers:
        line_no: Optional[int] = None

        # On essaie d'abord avec SwimTime si disponible
        if isinstance(swim_time, str) and swim_time.strip():
            pattern_time = f'"SwimTime": "{swim_time}"'
            idx = search_start
            while idx < len(lines):
                line = lines[idx]
                if pattern_time in line:
                    has_speed = False
                    rank_ok = rank is None

                    # Fenêtre autour de la performance
                    start_win = max(0, idx - 5)
                    end_win = min(len(lines), idx + 20)
                    for j in range(start_win, end_win):
                        l2 = lines[j]
                        if '"Speed"' in l2:
                            has_speed = True
                        if rank is not None and f'"Rank": {rank}' in l2:
                            rank_ok = True

                    # On considère que c'est une perf "Speed null" si pas de Speed
                    # trouvé dans la fenêtre, et (Rank correspond si fourni).
                    if not has_speed and rank_ok:
                        line_no = idx + 1
                        search_start = end_win
                        break

                idx += 1

        # Si on n'a rien trouvé, on essaie éventuellement par Rank seul
        if line_no is None and rank is not None:
            pattern_rank = f'"Rank": {rank}'
            for idx in range(search_start, len(lines)):
                if pattern_rank in lines[idx]:
                    line_no = idx + 1
                    search_start = idx + 1
                    break

        results.append((swim_time, rank, line_no))

    return results


def count_null_speed() -> None:
    """
    Compte le nombre de performances dont le champ Speed est null
    (absent ou à None) dans l'ensemble des fichiers Extranat nettoyés.
    """
    if not EXTRANAT_OUTPUT_BASE_DIR.exists():
        print(f"Dossier introuvable : {EXTRANAT_OUTPUT_BASE_DIR}")
        return

    json_files = sorted(EXTRANAT_OUTPUT_BASE_DIR.rglob("*.json"))
    if not json_files:
        print(f"Aucun fichier JSON trouvé dans {EXTRANAT_OUTPUT_BASE_DIR}")
        return

    total_perfs = 0
    null_speed = 0
    per_file_markers: Dict[str, List[Tuple[Optional[str], Optional[int]]]] = {}

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

            perfs = epreuve.get("performances")
            if not isinstance(perfs, list):
                continue

            for perf in perfs:
                if not isinstance(perf, dict):
                    continue
                total_perfs += 1
                speed = perf.get("Speed", None)
                if speed is None:
                    null_speed += 1
                    rel_path = str(path.relative_to(EXTRANAT_OUTPUT_BASE_DIR))
                    swim_time = perf.get("SwimTime") if isinstance(perf.get("SwimTime"), str) else None
                    rank = perf.get("Rank") if isinstance(perf.get("Rank"), int) else None
                    per_file_markers.setdefault(rel_path, []).append((swim_time, rank))

    print(f"Total performances: {total_perfs}")
    print(f"Performances avec Speed null (absent ou None): {null_speed}")
    if total_perfs:
        pct = null_speed * 100.0 / total_perfs
        print(f"Pourcentage Speed null: {pct:.2f}%")

    if per_file_markers:
        print(
            f"\nFichiers contenant au moins une performance avec Speed null ({len(per_file_markers)} fichiers) :"
        )
        for rel_path, markers in sorted(per_file_markers.items(), key=lambda x: -len(x[1])):
            print(f"  - {rel_path}: {len(markers)} performance(s) avec Speed null")

            detailed = find_line_numbers_for_null_speed(
                EXTRANAT_OUTPUT_BASE_DIR / rel_path, markers
            )
            for swim_time, rank, line_no in detailed:
                time_txt = f"SwimTime={swim_time}" if swim_time is not None else "SwimTime=<inconnu>"
                rank_txt = f", Rank={rank}" if rank is not None else ""
                line_txt = f" (ligne {line_no})" if line_no is not None else ""
                print(f"      * {time_txt}{rank_txt}{line_txt}")


if __name__ == "__main__":
    count_null_speed()

