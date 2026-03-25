import argparse
import json
import re
from pathlib import Path
from typing import Any

import fitz  # pymupdf


RANK_PATTERN = re.compile(r"^\d+\.$")
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}\.\d{2}$|^\d{1,2}\.\d{2}$")


def _group_words_into_rows(words: list[tuple], y_tolerance: float = 2.5) -> list[dict[str, Any]]:
    sorted_words = sorted(words, key=lambda word: (word[1], word[0]))
    rows: list[dict[str, Any]] = []

    for item in sorted_words:
        x0, y0, x1, y1, text = item[:5]
        text = str(text).strip()
        if not text:
            continue

        assigned = False
        for row in rows:
            if abs(row["y"] - float(y0)) <= y_tolerance:
                row["words"].append(
                    {"text": text, "x0": float(x0), "x1": float(x1), "y0": float(y0), "y1": float(y1)}
                )
                row["ys"].append(float(y0))
                row["y"] = sum(row["ys"]) / len(row["ys"])
                assigned = True
                break

        if not assigned:
            rows.append(
                {
                    "y": float(y0),
                    "ys": [float(y0)],
                    "words": [{"text": text, "x0": float(x0), "x1": float(x1), "y0": float(y0), "y1": float(y1)}],
                }
            )

    for row in rows:
        row["words"] = sorted(row["words"], key=lambda w: w["x0"])

    return rows


def _extract_data_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data_rows: list[dict[str, Any]] = []

    for row in rows:
        row_words = row["words"]
        if not row_words:
            continue

        rank_found = False
        for i, cell in enumerate(row_words):
            if RANK_PATTERN.match(cell["text"]):
                rank_found = True
                break
            # Cas PDF frequent: "1" et "." separes
            if i + 1 < len(row_words) and cell["text"].isdigit() and row_words[i + 1]["text"] == ".":
                rank_found = True
                break

        if not rank_found:
            continue

        numeric_like_cells = 0
        for cell in row_words:
            value = cell["text"]
            if value.isdigit() or TIME_PATTERN.match(value):
                numeric_like_cells += 1

        if numeric_like_cells >= 4:
            data_rows.append(row)

    return data_rows


def _cluster_x_positions(x_values: list[float], tolerance: float = 14.0) -> list[dict[str, Any]]:
    if not x_values:
        return []

    x_values = sorted(x_values)
    clusters: list[list[float]] = [[x_values[0]]]

    for x in x_values[1:]:
        if abs(x - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    result: list[dict[str, Any]] = []
    for cluster in clusters:
        center = sum(cluster) / len(cluster)
        result.append(
            {
                "x_center": round(center, 2),
                "x_min": round(min(cluster), 2),
                "x_max": round(max(cluster), 2),
                "samples": len(cluster),
            }
        )
    return result


def _guess_header_labels(page_words: list[tuple], first_data_y: float, columns: list[dict[str, Any]]) -> list[str]:
    if not columns:
        return []

    labels = [""] * len(columns)
    header_band_top = max(0.0, first_data_y - 90.0)
    header_band_bottom = first_data_y - 2.0

    candidates: list[dict[str, Any]] = []
    for item in page_words:
        x0, y0, x1, y1, text = item[:5]
        text = str(text).strip()
        if not text:
            continue
        if y0 < header_band_top or y0 > header_band_bottom:
            continue
        if len(text) == 1 and not text.isdigit():
            continue
        candidates.append({"text": text, "x_center": float(x0 + x1) / 2.0, "y0": float(y0)})

    for candidate in sorted(candidates, key=lambda c: c["y0"], reverse=True):
        nearest_idx = min(
            range(len(columns)),
            key=lambda i: abs(columns[i]["x_center"] - candidate["x_center"]),
        )
        if not labels[nearest_idx]:
            labels[nearest_idx] = candidate["text"]

    return labels


def detect_columns(pdf_path: Path, page_number: int = 1) -> dict[str, Any]:
    with fitz.open(pdf_path) as document:
        if page_number < 1 or page_number > len(document):
            raise ValueError(f"Page invalide: {page_number} (1-{len(document)})")

        page = document[page_number - 1]
        words = page.get_text("words")
        rows = _group_words_into_rows(words)
        data_rows = _extract_data_rows(rows)

        if not data_rows:
            return {
                "source_pdf": str(pdf_path),
                "page_number": page_number,
                "columns": [],
                "message": "Aucune ligne de donnees detectee.",
            }

        x_values: list[float] = []
        for row in data_rows:
            for cell in row["words"]:
                x_values.append(float(cell["x0"]))

        columns = _cluster_x_positions(x_values)
        first_data_y = min(row["y"] for row in data_rows)
        labels = _guess_header_labels(words, first_data_y, columns)

        for i, column in enumerate(columns):
            column["header_guess"] = labels[i] if i < len(labels) else ""

        return {
            "source_pdf": str(pdf_path),
            "page_number": page_number,
            "rows_detected": len(data_rows),
            "columns": columns,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detecte les colonnes d'une table dans un PDF Omega (via positions x)."
    )
    parser.add_argument(
        "--pdf",
        default="/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/omega/pdfs/2000/0001000D000A000000FFFFFFFFFFFF01.pdf",
        help="Chemin du PDF a analyser.",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="Numero de page (base 1).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Affiche le resultat complet en JSON.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF introuvable: {pdf_path}")

    result = detect_columns(pdf_path, page_number=args.page)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"PDF: {result['source_pdf']}")
    print(f"Page: {result['page_number']}")
    if "message" in result:
        print(result["message"])
        return

    print(f"Lignes de donnees detectees: {result['rows_detected']}")
    print("Colonnes detectees:")
    for index, column in enumerate(result["columns"], start=1):
        guess = column.get("header_guess", "")
        guess_part = f" | header~ {guess}" if guess else ""
        print(
            f"  {index:02d}. x={column['x_center']:.2f} "
            f"(min={column['x_min']:.2f}, max={column['x_max']:.2f}, n={column['samples']}){guess_part}"
        )


if __name__ == "__main__":
    main()
