from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_data_dir() -> Path:
    return _project_root() / "data" / "raw" / "usaswimming"


def _default_output_path() -> Path:
    return _project_root() / "data" / "processed" / "usaswimming_summary.json"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.strip().split())


def _normalize_name(value: Any) -> str:
    return _normalize_text(value).casefold()


def _infer_year_from_path(path: Path) -> int | None:
    parent = path.parent.name
    return int(parent) if parent.isdigit() else None


def _extract_swimdate_iso(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    # Common shape: 1991-08-10T00:00:00.000
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        if len(v) >= 10:
            prefix = v[:10]
            try:
                return datetime.strptime(prefix, "%Y-%m-%d").date().isoformat()
            except ValueError:
                return None
    return None


def _process_file(path: Path) -> dict[str, Any]:
    year = _infer_year_from_path(path)
    result: dict[str, Any] = {
        "year": year,
        "invalid_json_file": 0,
        "non_list_json_file": 0,
        "performances_total": 0,
        "missing_name_property": 0,
        "empty_name_value": 0,
        "swimmers_distinct": set(),
        "meets_distinct": set(),
        "events_distinct": set(),
        "genders_distinct": set(),
        "sessions_distinct": set(),
        "agegroups_distinct": set(),
        "date_min": None,
        "date_max": None,
        "top_swimmer_counter": Counter(),
        "file_rows": 0,
    }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        result["invalid_json_file"] = 1
        return result

    if not isinstance(data, list):
        result["non_list_json_file"] = 1
        return result

    for row in data:
        if not isinstance(row, dict):
            continue

        result["file_rows"] += 1
        result["performances_total"] += 1

        name_present = "Name" in row
        raw_name = row.get("Name") if name_present else None
        name_norm = _normalize_name(raw_name)

        if not name_present:
            result["missing_name_property"] += 1
        elif not name_norm:
            result["empty_name_value"] += 1
        else:
            result["swimmers_distinct"].add(name_norm)
            result["top_swimmer_counter"][name_norm] += 1

        meet = _normalize_text(row.get("Meet"))
        if meet:
            result["meets_distinct"].add(meet)

        event = _normalize_text(row.get("Event"))
        if event:
            result["events_distinct"].add(event)

        gender = _normalize_text(row.get("Gender"))
        if gender:
            result["genders_distinct"].add(gender)

        session = _normalize_text(row.get("Session"))
        if session:
            result["sessions_distinct"].add(session)

        agegroup = _normalize_text(row.get("AgeGroup"))
        if agegroup:
            result["agegroups_distinct"].add(agegroup)

        swimdate = _extract_swimdate_iso(row.get("SwimDate"))
        if swimdate:
            if result["date_min"] is None or swimdate < result["date_min"]:
                result["date_min"] = swimdate
            if result["date_max"] is None or swimdate > result["date_max"]:
                result["date_max"] = swimdate

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a JSON summary for app/data/usaswimming."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_default_data_dir(),
        help=f"Root directory containing USA Swimming JSON files (default: {_default_data_dir()})",
    )
    parser.add_argument(
        "--pattern",
        default="*.json",
        help="File glob pattern to search recursively (default: *.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output_path(),
        help=f"Output JSON path (default: {_default_output_path()})",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional limit for debugging (0 = no limit).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of worker threads (default: 8).",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Not a directory: {data_dir}")

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files = [p for p in data_dir.rglob(args.pattern) if p.is_file()]
    if args.max_files > 0:
        files = files[: args.max_files]

    performances_total = 0
    swimmers_with_duplication = 0
    swimmers_distinct: set[str] = set()

    missing_name_property = 0
    empty_name_value = 0
    invalid_json_files = 0
    non_list_json_files = 0

    meets_distinct: set[str] = set()
    events_distinct: set[str] = set()
    genders_distinct: set[str] = set()
    sessions_distinct: set[str] = set()
    agegroups_distinct: set[str] = set()

    files_per_year: Counter[int] = Counter()
    performances_per_year: Counter[int] = Counter()

    date_min: str | None = None
    date_max: str | None = None

    top_swimmer_counter: Counter[str] = Counter()
    max_rows_in_one_file = 0
    min_rows_in_one_file: int | None = None

    if args.workers <= 1:
        for path in files:
            result = _process_file(path)
            year = result["year"]
            if year is not None:
                files_per_year[year] += 1
                performances_per_year[year] += result["performances_total"]

            invalid_json_files += result["invalid_json_file"]
            non_list_json_files += result["non_list_json_file"]
            performances_total += result["performances_total"]
            swimmers_with_duplication += result["performances_total"]
            missing_name_property += result["missing_name_property"]
            empty_name_value += result["empty_name_value"]

            swimmers_distinct.update(result["swimmers_distinct"])
            meets_distinct.update(result["meets_distinct"])
            events_distinct.update(result["events_distinct"])
            genders_distinct.update(result["genders_distinct"])
            sessions_distinct.update(result["sessions_distinct"])
            agegroups_distinct.update(result["agegroups_distinct"])
            top_swimmer_counter.update(result["top_swimmer_counter"])

            result_date_min = result["date_min"]
            result_date_max = result["date_max"]
            if result_date_min and (date_min is None or result_date_min < date_min):
                date_min = result_date_min
            if result_date_max and (date_max is None or result_date_max > date_max):
                date_max = result_date_max

            file_rows = result["file_rows"]
            max_rows_in_one_file = max(max_rows_in_one_file, file_rows)
            if min_rows_in_one_file is None:
                min_rows_in_one_file = file_rows
            else:
                min_rows_in_one_file = min(min_rows_in_one_file, file_rows)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_process_file, path): path for path in files}
            for fut in as_completed(futures):
                result = fut.result()
                year = result["year"]
                if year is not None:
                    files_per_year[year] += 1
                    performances_per_year[year] += result["performances_total"]

                invalid_json_files += result["invalid_json_file"]
                non_list_json_files += result["non_list_json_file"]
                performances_total += result["performances_total"]
                swimmers_with_duplication += result["performances_total"]
                missing_name_property += result["missing_name_property"]
                empty_name_value += result["empty_name_value"]

                swimmers_distinct.update(result["swimmers_distinct"])
                meets_distinct.update(result["meets_distinct"])
                events_distinct.update(result["events_distinct"])
                genders_distinct.update(result["genders_distinct"])
                sessions_distinct.update(result["sessions_distinct"])
                agegroups_distinct.update(result["agegroups_distinct"])
                top_swimmer_counter.update(result["top_swimmer_counter"])

                result_date_min = result["date_min"]
                result_date_max = result["date_max"]
                if result_date_min and (date_min is None or result_date_min < date_min):
                    date_min = result_date_min
                if result_date_max and (date_max is None or result_date_max > date_max):
                    date_max = result_date_max

                file_rows = result["file_rows"]
                max_rows_in_one_file = max(max_rows_in_one_file, file_rows)
                if min_rows_in_one_file is None:
                    min_rows_in_one_file = file_rows
                else:
                    min_rows_in_one_file = min(min_rows_in_one_file, file_rows)

    average_rows = (performances_total / len(files)) if files else 0.0

    top_swimmers = [
        {"name_normalized": name, "performances": count}
        for name, count in top_swimmer_counter.most_common(20)
    ]

    summary: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "data_dir": str(data_dir),
            "pattern": args.pattern,
            "files_scanned": len(files),
            "invalid_json_files": invalid_json_files,
            "non_list_json_files": non_list_json_files,
        },
        "totals": {
            "performances_total": performances_total,
            "swimmers_total_with_duplication": swimmers_with_duplication,
            "swimmers_distinct": len(swimmers_distinct),
            "performances_missing_name_property": missing_name_property,
            "performances_empty_name_value": empty_name_value,
        },
        "dataset_dimensions": {
            "distinct_meets": len(meets_distinct),
            "distinct_events": len(events_distinct),
            "distinct_genders": len(genders_distinct),
            "distinct_sessions": len(sessions_distinct),
            "distinct_age_groups": len(agegroups_distinct),
            "date_min": date_min,
            "date_max": date_max,
        },
        "file_stats": {
            "max_rows_in_one_file": max_rows_in_one_file,
            "min_rows_in_one_file": min_rows_in_one_file if min_rows_in_one_file is not None else 0,
            "average_rows_per_file": round(average_rows, 4),
        },
        "by_year": {
            str(year): {
                "files": files_per_year[year],
                "performances": performances_per_year[year],
            }
            for year in sorted(set(files_per_year.keys()) | set(performances_per_year.keys()))
        },
        "top_swimmers_by_performance_count": top_swimmers,
    }

    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Summary file created: {output_path}")
    print(f"JSON files scanned: {len(files):,}")
    print(f"Total performances: {performances_total:,}")
    print(f"Swimmers total with duplication: {swimmers_with_duplication:,}")
    print(f"Swimmers distinct: {len(swimmers_distinct):,}")


if __name__ == "__main__":
    main()
