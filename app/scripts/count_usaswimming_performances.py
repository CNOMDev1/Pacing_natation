
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_data_dir() -> Path:
    return _project_root() / "data" / "raw" / "usaswimming"


def _infer_year(path: Path) -> int | None:
    # Expected: data/raw/usaswimming/<year>/<meet>.json
    try:
        parent = path.parent.name
        return int(parent) if parent.isdigit() else None
    except Exception:
        return None


def _count_performances_in_file(path: Path) -> int:
    """
    Fast path:
    Count lines starting with exactly `  {` (2 spaces + `{`).
    This matches the formatting produced by `DataFrame.to_json(... indent=2)`.
    """
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("  {"):
                count += 1

    if count > 0:
        return count

    # Fallback (handles edge cases like compact JSON, or empty arrays encoded oddly).
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        # Common keys if someone changes the format upstream.
        for key in ("performances", "records", "results", "data", "values"):
            v = data.get(key)
            if isinstance(v, list):
                return len(v)
    return 0


def _iter_json_files(data_dir: Path, pattern: str) -> Iterable[Path]:
    # Keep it simple and deterministic: recursive search.
    yield from (p for p in data_dir.rglob(pattern) if p.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_default_data_dir(),
        help=f"Root directory containing year subfolders (default: {_default_data_dir()})",
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

    by_year: dict[int, int] = defaultdict(int)
    files_per_year: dict[int, int] = defaultdict(int)
    total = 0

    if args.workers <= 1:
        for path in json_files:
            n = _count_performances_in_file(path)
            total += n
            year = _infer_year(path)
            if year is not None:
                by_year[year] += n
                files_per_year[year] += 1
        print(f"Total performances: {total:,}")
        print(f"JSON files counted: {len(json_files):,}")
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(_count_performances_in_file, p): p for p in json_files}
            for fut in as_completed(futures):
                path = futures[fut]
                n = fut.result()
                total += n
                year = _infer_year(path)
                if year is not None:
                    by_year[year] += n
                    files_per_year[year] += 1
        print(f"Total performances: {total:,}")
        print(f"JSON files counted: {len(json_files):,}")

    # Per-year breakdown (sorted for readability)
    if by_year:
        print("\nPerformances par année:")
        for year in sorted(by_year.keys()):
            print(f"- {year}: {by_year[year]:,} ({files_per_year[year]} fichiers)")


if __name__ == "__main__":
    main()

