"""Count pages for Omega PDFs (recursive).

Parcourt récursivement le dossier `data/raw/omega/pdfs` et calcule:
- le nombre de pages de chaque PDF
- le total de pages (somme)
- le nombre de PDFs valides et le nombre d'erreurs

Usage:
  python3 count_omega_pdf_pages.py
  python3 count_omega_pdf_pages.py --dir /path/to/pdfs
  python3 count_omega_pdf_pages.py --out pages.csv
  python3 count_omega_pdf_pages.py 2013  # compte jusqu'à l'année (inclus)
  python3 count_omega_pdf_pages.py --year 2013  # compte uniquement l'année
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_pdfs_dir() -> Path:
    return _project_root() / "data" / "raw" / "omega" / "pdfs"


def _parse_year_from_path(p: Path, pdfs_root: Path) -> Optional[int]:
    """
    Essaye d'inférer une année à partir du chemin relatif.
    Cas attendu: <root>/<YYYY>/.../file.pdf
    """
    try:
        rel = p.relative_to(pdfs_root)
    except ValueError:
        return None

    if not rel.parts:
        return None
    first = rel.parts[0]
    try:
        return int(first)
    except ValueError:
        return None


def _count_pages_one_pdf(pdf_path: Path) -> int:
    # PyMuPDF fournit une méthode robuste pour extraire le nombre de pages.
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Dépendance manquante: installe `pymupdf` (PyMuPDF) pour lire les PDFs."
        ) from exc

    doc = fitz.open(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=_default_pdfs_dir(),
        help=f"Root directory containing PDFs (default: {_default_pdfs_dir()})",
    )
    parser.add_argument(
        "end_year",
        type=int,
        nargs="?",
        default=None,
        help="Optionnel: ne compter que les PDFs situés dans des dossiers d'années <= end_year (ex: 2013).",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Optionnel: ne compter que les PDFs dont le premier dossier relatif est exactement l'année (ex: 2013).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optionnel: écrire un CSV (colonnes: pdf_path,pages,status,error).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Réduit l'affichage: pas de ligne par PDF.",
    )
    args = parser.parse_args()

    root = args.dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    rows: list[dict[str, str]] = []

    pdf_count = 0
    valid_count = 0
    error_count = 0
    total_pages = 0

    for pdf_path in sorted(root.rglob("*.pdf")):
        if not pdf_path.is_file():
            continue

        if args.year is not None:
            inferred_year = _parse_year_from_path(pdf_path, root)
            if inferred_year != args.year:
                continue
        elif args.end_year is not None:
            # Le comportement demandé: compter "jusqu'à" une date (<= end_year).
            inferred_year = _parse_year_from_path(pdf_path, root)
            if inferred_year is None:
                continue
            if inferred_year > args.end_year:
                continue

        pdf_count += 1
        try:
            pages = _count_pages_one_pdf(pdf_path)
            valid_count += 1
            total_pages += pages
            if not args.quiet:
                print(f"[OK] {pdf_path} -> {pages} pages")
            rows.append(
                {
                    "pdf_path": str(pdf_path),
                    "pages": str(pages),
                    "status": "ok",
                    "error": "",
                }
            )
        except Exception as exc:
            error_count += 1
            if not args.quiet:
                print(f"[KO] {pdf_path} -> {exc}")
            rows.append(
                {
                    "pdf_path": str(pdf_path),
                    "pages": "",
                    "status": "error",
                    "error": str(exc),
                }
            )

    avg_pages = (total_pages / valid_count) if valid_count else 0.0

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["pdf_path", "pages", "status", "error"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    # Output en fin de script: pratique pour récupérer un résumé.
    print(
        "Terminé. "
        f"pdfs_found={pdf_count} | valid={valid_count} | errors={error_count} | "
        f"total_pages={total_pages} | avg_pages={avg_pages:.2f}"
    )


if __name__ == "__main__":
    main()

