"""Count Omega PDF files under data/raw/omega/pdfs (recursive).

Usage:
  python3 count_omega_pdf_files.py
  python3 count_omega_pdf_files.py 2013

When `end_year` is provided, only PDFs located in folders named as years
(`.../pdfs/<year>/...`) with `year <= end_year` are counted.
"""

import argparse
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_pdfs_dir() -> Path:
    return _project_root() / "data" / "raw" / "omega" / "pdfs"


def count_pdfs(root: Path, end_year: int | None = None) -> int:
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    n = 0
    for p in root.rglob("*.pdf"):
        if not p.is_file():
            continue

        if end_year is not None:
            # Expected structure: <root>/<YYYY>/.../file.pdf
            rel = p.relative_to(root)
            year_str = rel.parts[0] if rel.parts else ""
            try:
                year = int(year_str)
            except ValueError:
                continue
            if year > end_year:
                continue

        n += 1
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=_default_pdfs_dir(),
        help=f"Root directory (default: {_default_pdfs_dir()})",
    )
    parser.add_argument(
        "end_year",
        type=int,
        nargs="?",
        default=None,
        help="Optional upper bound year (count PDFs only in folders <= end_year).",
    )
    args = parser.parse_args()
    root = args.dir.resolve()
    n = count_pdfs(root, end_year=args.end_year)
    print(n)


if __name__ == "__main__":
    main()
