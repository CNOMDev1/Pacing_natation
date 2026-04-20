#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

VALID_AGE_GROUPS = {
    "10 & Under",
    "11-12",
    "13-14",
    "15-18",
    "19 & Over",
    "Not Applicable",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_data_dir() -> Path:
    return _project_root() / "app" / "data" / "usaswimming"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.strip().split())


def _process_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "files_scanned": 1,
        "invalid_json_files": 0,
        "non_list_json_files": 0,
        "performances_total": 0,
        "agegroup_valid": 0,
        "agegroup_different": 0,
        "invalid_values_counter": Counter(),
    }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        result["invalid_json_files"] = 1
        return result

    if not isinstance(data, list):
        result["non_list_json_files"] = 1
        return result

    for row in data:
        if not isinstance(row, dict):
            continue

        result["performances_total"] += 1
        age_group = _normalize_text(row.get("AgeGroup"))

        if age_group in VALID_AGE_GROUPS:
            result["agegroup_valid"] += 1
        else:
            result["agegroup_different"] += 1
            label = age_group if age_group else "<EMPTY_OR_MISSING>"
            result["invalid_values_counter"][label] += 1

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compte les performances avec AgeGroup valide et celles dont AgeGroup "
            "est différent de la liste autorisée."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_default_data_dir(),
        help=f"Dossier racine des JSON (défaut: {_default_data_dir()})",
    )
    parser.add_argument(
        "--pattern",
        default="*.json",
        help="Pattern des fichiers recherché récursivement (défaut: *.json).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Limite optionnelle pour debug (0 = pas de limite).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Nombre de threads (défaut: 8).",
    )
    parser.add_argument(
        "--show-top-invalid",
        type=int,
        default=10,
        help="Nombre de valeurs AgeGroup invalides à afficher (défaut: 10).",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Dossier introuvable: {data_dir}")

    files = [p for p in data_dir.rglob(args.pattern) if p.is_file()]
    if args.max_files > 0:
        files = files[: args.max_files]

    files_scanned = 0
    invalid_json_files = 0
    non_list_json_files = 0
    performances_total = 0
    agegroup_valid = 0
    agegroup_different = 0
    invalid_values_counter: Counter[str] = Counter()

    if args.workers <= 1:
        for path in files:
            result = _process_file(path)
            files_scanned += result["files_scanned"]
            invalid_json_files += result["invalid_json_files"]
            non_list_json_files += result["non_list_json_files"]
            performances_total += result["performances_total"]
            agegroup_valid += result["agegroup_valid"]
            agegroup_different += result["agegroup_different"]
            invalid_values_counter.update(result["invalid_values_counter"])
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_process_file, path): path for path in files}
            for fut in as_completed(futures):
                result = fut.result()
                files_scanned += result["files_scanned"]
                invalid_json_files += result["invalid_json_files"]
                non_list_json_files += result["non_list_json_files"]
                performances_total += result["performances_total"]
                agegroup_valid += result["agegroup_valid"]
                agegroup_different += result["agegroup_different"]
                invalid_values_counter.update(result["invalid_values_counter"])

    print(f"Data directory: {data_dir}")
    print(f"JSON files found: {len(files):,}")
    print(f"Files scanned: {files_scanned:,}")
    print(f"Invalid JSON files: {invalid_json_files:,}")
    print(f"Non-list JSON files: {non_list_json_files:,}")
    print(f"Total performances scanned: {performances_total:,}")
    print(f"Performances with valid AgeGroup: {agegroup_valid:,}")
    print(
        "Performances with AgeGroup different from "
        f"{sorted(VALID_AGE_GROUPS)}: {agegroup_different:,}"
    )

    if args.show_top_invalid > 0 and invalid_values_counter:
        print(f"\nTop {args.show_top_invalid} invalid AgeGroup values:")
        for value, count in invalid_values_counter.most_common(args.show_top_invalid):
            print(f"- {value}: {count:,}")


if __name__ == "__main__":
    main()
