#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def count_distinct_meets(base_dir: Path) -> tuple[int, int, int]:
    meets: set[str] = set()
    total_files = 0
    invalid_files = 0

    for json_file in base_dir.rglob("*.json"):
        total_files += 1
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            invalid_files += 1
            continue

        meet_value = data.get("Meet") if isinstance(data, dict) else None
        if isinstance(meet_value, str):
            meet_value = meet_value.strip()
            if meet_value:
                meets.add(meet_value)

    return len(meets), total_files, invalid_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compte le nombre de valeurs distinctes du champ 'Meet' dans des fichiers JSON."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="/Users/nouhailaimaneabbassi/Desktop/Pacing/data/processed/usaswimming",
        help="Dossier racine contenant les fichiers JSON (par défaut: usaswimming).",
    )
    args = parser.parse_args()

    target_dir = Path(args.directory).expanduser().resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        raise SystemExit(f"Dossier invalide: {target_dir}")

    distinct_meets, total_files, invalid_files = count_distinct_meets(target_dir)
    print(f"Dossier analysé : {target_dir}")
    print(f"Fichiers JSON lus : {total_files}")
    print(f"Fichiers ignorés (invalides) : {invalid_files}")
    print(f"Nombre de Meet distincts : {distinct_meets}")


if __name__ == "__main__":
    main()
