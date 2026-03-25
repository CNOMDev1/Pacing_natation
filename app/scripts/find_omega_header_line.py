import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # pymupdf


DISTANCE_PATTERN = re.compile(r"^\d{2,4}m$", re.IGNORECASE)


@dataclass
class HeaderMatch:
    page_number: int
    row_text: str


def normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def group_words_into_rows(words: list[tuple], y_tolerance: float = 2.5) -> list[list[str]]:
    rows: list[dict[str, float | list[tuple[float, str]]]] = []
    sorted_words = sorted(words, key=lambda w: (float(w[1]), float(w[0])))

    for item in sorted_words:
        x0, y0, _, _, text = item[:5]
        token = str(text).strip()
        if not token:
            continue

        assigned = False
        for row in rows:
            if abs(float(row["y"]) - float(y0)) <= y_tolerance:
                row["cells"].append((float(x0), token))
                row["ys"].append(float(y0))
                row["y"] = sum(row["ys"]) / len(row["ys"])
                assigned = True
                break

        if not assigned:
            rows.append(
                {
                    "y": float(y0),
                    "ys": [float(y0)],
                    "cells": [(float(x0), token)],
                }
            )

    rendered_rows: list[list[str]] = []
    for row in rows:
        cells = sorted(row["cells"], key=lambda c: c[0])
        rendered_rows.append([str(token) for _, token in cells])
    return rendered_rows


def is_target_header_row(tokens: list[str]) -> bool:
    normalized_tokens = [normalize_token(token) for token in tokens if normalize_token(token)]
    if not normalized_tokens:
        return False

    has_rank = "rank" in normalized_tokens
    has_nat = "nat" in normalized_tokens
    has_name = "name" in normalized_tokens or any("name firstname" in token for token in normalized_tokens)
    has_firstname = "firstname" in normalized_tokens or any("name firstname" in token for token in normalized_tokens)
    distance_count = sum(1 for token in normalized_tokens if DISTANCE_PATTERN.match(token))

    # On cherche une ligne d'entete du type:
    # Rank | Name | Firstname | Nat | ... | 25m | 50m | 100m | 400m
    return has_rank and has_nat and has_name and has_firstname and distance_count >= 2


def detect_pdf_matches(pdf_path: Path) -> list[HeaderMatch]:
    matches: list[HeaderMatch] = []
    with fitz.open(pdf_path) as document:
        for page_index, page in enumerate(document, start=1):
            words = page.get_text("words")
            if not words:
                continue

            rows = group_words_into_rows(words)
            for row in rows:
                if is_target_header_row(row):
                    row_text = " ".join(row)
                    matches.append(HeaderMatch(page_number=page_index, row_text=row_text))
                    break
    return matches


def scan_pdf_tree(root_dir: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for pdf_path in sorted(root_dir.rglob("*.pdf")):
        matches = detect_pdf_matches(pdf_path)
        if not matches:
            continue

        results.append(
            {
                "pdf_path": str(pdf_path),
                "matches": [{"page_number": m.page_number, "row_text": m.row_text} for m in matches],
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detecte les PDF Omega contenant une ligne d'entete de type 'Rank Name Firstname Nat ... 25m ...'."
    )
    parser.add_argument(
        "--root",
        default="/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/omega/pdfs",
        help="Dossier racine contenant les PDF.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Chemin de sortie JSON (optionnel) pour enregistrer les resultats.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Affiche le total scanne, les non-correspondants et la liste des fichiers.",
    )
    args = parser.parse_args()

    root_dir = Path(args.root)
    if not root_dir.exists():
        raise FileNotFoundError(f"Dossier introuvable: {root_dir}")

    total_pdfs = sum(1 for _ in root_dir.rglob("*.pdf"))
    results = scan_pdf_tree(root_dir)
    matching_count = len(results)
    non_matching_count = total_pdfs - matching_count

    print(matching_count)

    if args.verbose:
        print(f"PDF scannes: {total_pdfs}")
        print(f"PDF ne contenant pas la ligne: {non_matching_count}")
        for item in results:
            first_match = item["matches"][0]
            print(f"- {item['pdf_path']} (page {first_match['page_number']})")

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.verbose:
            print(f"\nResultats JSON ecrits dans: {output_path}")


if __name__ == "__main__":
    main()
