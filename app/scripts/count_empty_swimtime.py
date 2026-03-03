import argparse
import json
import re
from pathlib import Path
from typing import Any, List, Tuple


def count_swimtime_extranat(data: dict) -> Tuple[int, int]:
    empty = 0
    non_empty = 0

    epreuves = data.get("epreuves", [])

    for epreuve in epreuves:
        performances = epreuve.get("performances", [])

        for perf in performances:
            swim_time = perf.get("SwimTime")
            if (
                swim_time is None
                or swim_time == ""
                or (isinstance(swim_time, str) and swim_time.strip() in {"", "DNF", "DNS", "DSQ"})
            ):
                empty += 1
            else:
                non_empty += 1

    return empty, non_empty


def count_swimtime_extranat_file(file_path: Path) -> Tuple[int, int]:
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Impossible de lire/parcer le fichier {file_path}: {e}")
        return 0, 0

    return count_swimtime_extranat(data)


EMPTY_SWIMTIME_VALUES = {"", "DNF", "DNS", "DSQ"}
SWIMTIME_VALUE_RE = re.compile(r'"SwimTime"\s*:\s*"(?P<val>[^"]*)"')
SWIMTIME_NULL_RE = re.compile(r'"SwimTime"\s*:\s*null\b')


def find_empty_swimtime_lines(file_path: Path) -> List[Tuple[int, str]]:
    """
    Retourne la liste (ligne, valeur) où SwimTime est vide
    (au sens de EMPTY_SWIMTIME_VALUES ou null).
    """
    lines: List[Tuple[int, str]] = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                m_val = SWIMTIME_VALUE_RE.search(line)
                if m_val:
                    val = m_val.group("val").strip()
                    if val in EMPTY_SWIMTIME_VALUES:
                        lines.append((lineno, val))
                    continue

                if SWIMTIME_NULL_RE.search(line):
                    lines.append((lineno, "null"))
    except Exception as e:
        print(f"Impossible de lire {file_path} pour récupérer les lignes: {e}")

    return lines

def count_swimtime_in_obj(obj: Any) -> Tuple[int, int]:
    empty = 0
    non_empty = 0

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "SwimTime":
                if (
                    value is None
                    or value == ""
                    or (isinstance(value, str) and value.strip() in {"", "DNF", "DNS", "DSQ"})
                ):
                    empty += 1
                else:
                    non_empty += 1

            e, ne = count_swimtime_in_obj(value)
            empty += e
            non_empty += ne

    elif isinstance(obj, list):
        for item in obj:
            e, ne = count_swimtime_in_obj(item)
            empty += e
            non_empty += ne

    return empty, non_empty


def count_swimtime_usa_file(file_path: Path) -> Tuple[int, int]:
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Impossible de lire/parcer le fichier {file_path}: {e}")
        return 0, 0

    return count_swimtime_in_obj(data)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compter les SwimTime vides / non vides "
        "dans les fichiers JSON Extranat et USA Swimming."
    )
    parser.add_argument(
        "--file",
        type=str,
        help=(
            "Chemin vers un fichier JSON précis à analyser "
            "(par exemple un fichier Extranat)."
        ),
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[1]

    extranat_dir = (
        base_dir
        / "data"
        / "cleaned_data"
        / "extranat"
        / "competitions_per_type"
    )

    usaswimming_dir = (
        base_dir
        / "data"
        / "cleaned_data"
        / "usaswimming"
    )

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Fichier introuvable: {file_path}")
            return

        print(f"Analyse du fichier: {file_path}")

        if "extranat" in file_path.parts:
            empty, non_empty = count_swimtime_extranat_file(file_path)
        else:
            empty, non_empty = count_swimtime_usa_file(file_path)

        total = empty + non_empty
        percentage = (empty / total * 100) if total > 0 else 0

        print(f"\nSwimTime vides: {empty}")
        print(f"SwimTime non vides: {non_empty}")
        print(f"{percentage:.2f}% de SwimTime manquants")
        return

    total_empty_global = 0
    total_non_empty_global = 0

    results = []
    extranat_empty_files: List[Tuple[Path, int, List[Tuple[int, str]]]] = []
    usa_empty_files: List[Tuple[Path, int, List[Tuple[int, str]]]] = []

    #  EXTRANAT 
    if extranat_dir.exists():
        print(f"\n Parcours Extranat : {extranat_dir}")

        dir_empty = 0
        dir_non_empty = 0

        for path in extranat_dir.rglob("*.json"):
            file_empty, file_non_empty = count_swimtime_extranat_file(path)

            if file_empty > 0 or file_non_empty > 0:
                print(
                    f"{path.name}: "
                    f"{file_empty} vides, "
                    f"{file_non_empty} non vides"
                )

            if file_empty > 0:
                line_numbers = find_empty_swimtime_lines(path)
                extranat_empty_files.append((path, file_empty, line_numbers))

            dir_empty += file_empty
            dir_non_empty += file_non_empty

        results.append(("Extranat", dir_empty, dir_non_empty))
        total_empty_global += dir_empty
        total_non_empty_global += dir_non_empty

    else:
        print(f"Dossier Extranat introuvable: {extranat_dir}")

    #  USA SWIMMING 
    if usaswimming_dir.exists():
        print(f"\n Parcours USA Swimming : {usaswimming_dir}")

        dir_empty = 0
        dir_non_empty = 0

        for path in usaswimming_dir.rglob("*.json"):
            file_empty, file_non_empty = count_swimtime_usa_file(path)

            if file_empty > 0 or file_non_empty > 0:
                print(
                    f"{path.name}: "
                    f"{file_empty} vides, "
                    f"{file_non_empty} non vides"
                )

            if file_empty > 0:
                line_numbers = find_empty_swimtime_lines(path)
                usa_empty_files.append((path, file_empty, line_numbers))

            dir_empty += file_empty
            dir_non_empty += file_non_empty

        results.append(("USA Swimming", dir_empty, dir_non_empty))
        total_empty_global += dir_empty
        total_non_empty_global += dir_non_empty

    else:
        print(f"Dossier USA Swimming introuvable: {usaswimming_dir}")

    #  RÉCAP 
    print("\n================ RÉCAPITULATIF ================")

    for label, dir_empty, dir_non_empty in results:
        total = dir_empty + dir_non_empty
        percentage = (dir_empty / total * 100) if total > 0 else 0

        print(
            f"\n{label} :"
            f"\n  ➤ {dir_empty} SwimTime vides"
            f"\n  ➤ {dir_non_empty} SwimTime non vides"
            f"\n  ➤ {percentage:.2f}% de SwimTime manquants"
        )

    total_all = total_empty_global + total_non_empty_global
    global_percentage = (
        total_empty_global / total_all * 100
        if total_all > 0 else 0
    )

    print("\n================ FICHIERS AVEC SwimTime VIDES ================")

    if extranat_empty_files:
        print("\nExtranat :")
        for path, cnt, line_infos in extranat_empty_files:
            if line_infos:
                lines_str = ", ".join(
                    f"{lineno} (valeur='{val}')"
                    for lineno, val in line_infos
                )
                print(
                    f"  - {path}: {cnt} SwimTime vides "
                    f"(lignes / valeurs: {lines_str})"
                )
            else:
                print(f"  - {path}: {cnt} SwimTime vides")
    else:
        print("\nExtranat : aucun fichier avec SwimTime vide.")

    if usa_empty_files:
        print("\nUSA Swimming :")
        for path, cnt, line_infos in usa_empty_files:
            if line_infos:
                lines_str = ", ".join(
                    f"{lineno} (valeur='{val}')"
                    for lineno, val in line_infos
                )
                print(
                    f"  - {path}: {cnt} SwimTime vides "
                    f"(lignes / valeurs: {lines_str})"
                )
            else:
                print(f"  - {path}: {cnt} SwimTime vides")
    else:
        print("\nUSA Swimming : aucun fichier avec SwimTime vide.")

    print("\n================ TOTAL GLOBAL ================")
    print(f"{total_empty_global} SwimTime vides")
    print(f"{total_non_empty_global} SwimTime non vides")
    print(f"{global_percentage:.2f}% de SwimTime manquants")


if __name__ == "__main__":
    main()