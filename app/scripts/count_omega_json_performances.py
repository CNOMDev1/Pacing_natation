"""Count performances in data/raw/omega_json_endpoint_single (recursive).

Definition used:
- Each JSON file is expected to contain a key `results` which is a list.
- One "performance" corresponds to one element in that `results` list.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_json_dir() -> Path:
    return _project_root() / "data" / "raw" / "omega_json_endpoint_single"


def _is_json_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() == ".json"


def count_performances(json_path: Path) -> tuple[int, str]:
    """
    Returns: (performance_count, reason)
    - reason can be: 'results', 'error', 'missing_results', 'invalid_json', 'unexpected_shape'
    """
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return 0, "invalid_json"
    except Exception:
        return 0, "invalid_json"

    if isinstance(data, dict):
        if "error" in data:
            return 0, "error"

        results = data.get("results")
        if isinstance(results, list):
            return len(results), "results"

        return 0, "missing_results"

    return 0, "unexpected_shape"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=_default_json_dir(),
        help=f"Root directory containing omega JSONs (default: {_default_json_dir()})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print additional stats (errors, files with results, etc.)",
    )
    args = parser.parse_args()

    root = args.dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    total_performances = 0
    total_json_files = 0
    total_results_files = 0
    total_error_files = 0
    breakdown = {}

    for p in root.rglob("*.json"):
        if not _is_json_file(p):
            continue

        total_json_files += 1
        n, reason = count_performances(p)
        breakdown[reason] = breakdown.get(reason, 0) + 1
        total_performances += n
        if reason == "results":
            total_results_files += 1
        elif reason == "error":
            total_error_files += 1

    if args.verbose:
        print(f"total_json_files={total_json_files}")
        print(f"total_results_files={total_results_files}")
        print(f"total_error_files={total_error_files}")
        print(f"total_performances={total_performances}")
        if breakdown:
            print("breakdown=" + json.dumps(breakdown, ensure_ascii=True, sort_keys=True))
    else:
        # Keep output script-friendly: number only.
        print(total_performances)


if __name__ == "__main__":
    main()

