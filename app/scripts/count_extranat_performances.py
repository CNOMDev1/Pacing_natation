from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable


YEAR_REGEX = re.compile(r"(19|20)\d{2}")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_data_dir() -> Path:
    return _project_root() / "app" / "data" / "extranat"


def _iter_json_files(data_dir: Path, pattern: str) -> Iterable[Path]:
    yield from (p for p in data_dir.rglob(pattern) if p.is_file())


def _extract_year_from_data(data: object) -> int | None:
    if not isinstance(data, dict):
        return None

    date_value = data.get("date")
    if isinstance(date_value, str):
        matches = YEAR_REGEX.findall(date_value)
        # YEAR_REGEX has a group, so finditer is safer for full match.
        if not matches:
            for m in re.finditer(r"(?:19|20)\d{2}", date_value):
                return int(m.group(0))
        else:
            for m in re.finditer(r"(?:19|20)\d{2}", date_value):
                return int(m.group(0))

    return None


def _count_performances_in_object(data: object) -> int:
    if isinstance(data, dict):
        total = 0
        for key, value in data.items():
            if key == "performances" and isinstance(value, list):
                total += len(value)
                continue
            total += _count_performances_in_object(value)
        return total

    if isinstance(data, list):
        return sum(_count_performances_in_object(item) for item in data)

    return 0


def _count_file(path: Path) -> tuple[int, int | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    performances = _count_performances_in_object(data)
    year = _extract_year_from_data(data)
    return performances, year


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count performances in Extranat JSON files."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_default_data_dir(),
        help=f"Root directory containing Extranat JSON files (default: {_default_data_dir()})",
    )
    parser.add_argument(
        "--pattern",
        default="*.json",
        help="File glob pattern relative to data-dir (default: *.json)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads (default: 1). Use >1 to speed up IO.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional limit for debugging (0 = no limit).",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Not a directory: {data_dir}")

    json_files = list(_iter_json_files(data_dir, args.pattern))
    if args.max_files and args.max_files > 0:
        json_files = json_files[: args.max_files]

    total = 0
    by_year: dict[int, int] = defaultdict(int)
    files_per_year: dict[int, int] = defaultdict(int)
    unknown_year_files = 0

    if args.workers <= 1:
        for path in json_files:
            n, year = _count_file(path)
            total += n
            if year is None:
                unknown_year_files += 1
            else:
                by_year[year] += n
                files_per_year[year] += 1
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_count_file, p): p for p in json_files}
            for fut in as_completed(futures):
                n, year = fut.result()
                total += n
                if year is None:
                    unknown_year_files += 1
                else:
                    by_year[year] += n
                    files_per_year[year] += 1

    print(f"Total performances: {total:,}")
    print(f"JSON files counted: {len(json_files):,}")
    print(f"JSON files without year: {unknown_year_files:,}")

    if by_year:
        print("\nPerformances par année:")
        for year in sorted(by_year):
            print(f"- {year}: {by_year[year]:,} ({files_per_year[year]} fichiers)")


if __name__ == "__main__":
    main()
