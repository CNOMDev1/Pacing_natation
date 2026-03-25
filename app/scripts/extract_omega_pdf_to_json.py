import argparse
import json
import re
from pathlib import Path
from typing import Any

import fitz  # pymupdf


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _extract_key_value_pairs(lines: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            pairs[key] = value
    return pairs


def _detect_table_lines(page: fitz.Page, y_tolerance: float = 2.5) -> list[dict[str, Any]]:
    """
    Detecte des lignes de tableau en regroupant les mots proches verticalement.
    """
    words = page.get_text("words")
    if not words:
        return []

    # words: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
    sorted_words = sorted(words, key=lambda word: (word[1], word[0]))
    grouped_rows: list[dict[str, Any]] = []

    for word in sorted_words:
        x0, y0, x1, y1, text = word[:5]
        if not str(text).strip():
            continue

        assigned = False
        for row in grouped_rows:
            if abs(row["y"] - y0) <= y_tolerance:
                row["words"].append(
                    {"text": str(text), "x0": float(x0), "x1": float(x1), "y0": float(y0), "y1": float(y1)}
                )
                row["ys"].append(float(y0))
                row["y"] = sum(row["ys"]) / len(row["ys"])
                assigned = True
                break

        if not assigned:
            grouped_rows.append(
                {
                    "y": float(y0),
                    "ys": [float(y0)],
                    "words": [{"text": str(text), "x0": float(x0), "x1": float(x1), "y0": float(y0), "y1": float(y1)}],
                }
            )

    rank_pattern = re.compile(r"^\d+\.$")

    def _extract_rank_from_words(row_words: list[dict[str, Any]]) -> str | None:
        if not row_words:
            return None

        # Cherche l'indice n'importe ou dans la ligne.
        for i, cell in enumerate(row_words):
            text = str(cell["text"])
            if rank_pattern.match(text):
                return text
            # Cas frequent en PDF: "1" et "." extraits comme deux cellules distinctes.
            if i + 1 < len(row_words) and text.isdigit() and row_words[i + 1]["text"] == ".":
                return f"{text}."
        return None

    table_lines: list[dict[str, Any]] = []
    for row_index, row in enumerate(grouped_rows, start=1):
        row_words = sorted(row["words"], key=lambda item: item["x0"])
        line_text = " ".join(item["text"] for item in row_words).strip()
        if not line_text:
            continue
        rank = _extract_rank_from_words(row_words)
        if not rank:
            continue
        table_lines.append(
            {
                "row_index": row_index,
                "rank_index": rank,
                "y": round(row["y"], 2),
                "text": line_text,
                "columns": [item["text"] for item in row_words],
                "cells": row_words,
            }
        )

    return table_lines


def extract_pdf_data(pdf_path: Path) -> dict[str, Any]:
    with fitz.open(pdf_path) as document:
        metadata = _normalize_metadata(document.metadata or {})
        pages: list[dict[str, Any]] = []

        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            pages.append(
                {
                    "page_number": page_index,
                    "text": text,
                    "lines": lines,
                    "detected_fields": _extract_key_value_pairs(lines),
                    "detected_table_lines": _detect_table_lines(page),
                }
            )

        return {
            "source_pdf": str(pdf_path),
            "pdf_name": pdf_path.name,
            "page_count": len(document),
            "metadata": metadata,
            "pages": pages,
        }


def _build_output_path(pdf_path: Path, output_root: Path) -> Path:
    parts = pdf_path.parts
    output_dir = output_root

    if "pdfs" in parts:
        pdfs_index = parts.index("pdfs")
        if pdfs_index + 1 < len(parts):
            potential_year = parts[pdfs_index + 1]
            if potential_year.isdigit():
                output_dir = output_root / potential_year

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{pdf_path.stem}.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lit un PDF Omega avec pymupdf et enregistre les informations en JSON."
    )
    parser.add_argument(
        "--pdf",
        default="/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/omega/pdfs/2000/0001000D000A000000FFFFFFFFFFFF01.pdf",
        help="Chemin du fichier PDF Omega a lire.",
    )
    parser.add_argument(
        "--output-root",
        default="/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/omega_json",
        help="Dossier racine de sortie pour les fichiers JSON.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    output_root = Path(args.output_root)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF introuvable: {pdf_path}")

    extracted_data = extract_pdf_data(pdf_path)
    output_path = _build_output_path(pdf_path, output_root)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(extracted_data, file, ensure_ascii=False, indent=2)

    print(f"JSON genere: {output_path}")


if __name__ == "__main__":
    main()
