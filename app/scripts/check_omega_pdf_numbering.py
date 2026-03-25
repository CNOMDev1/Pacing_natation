import argparse
import re
from pathlib import Path

import fitz  # pymupdf


REQUIRED_MARKERS = ("1.", "2.", "3.", "4.", "5.")


def _extract_pdf_text(pdf_path: Path) -> str:
    with fitz.open(pdf_path) as document:
        return "\n".join(page.get_text("text") for page in document)


def _missing_markers(text: str) -> list[str]:
    missing: list[str] = []
    for marker in REQUIRED_MARKERS:
        # On cherche le marqueur comme numero de liste (ex: "1.")
        pattern = rf"(?<!\d){re.escape(marker)}(?!\d)"
        if not re.search(pattern, text):
            missing.append(marker)
    return missing


def check_pdfs(root_dir: Path) -> tuple[int, int]:
    pdf_files = sorted(root_dir.rglob("*.pdf"))
    if not pdf_files:
        print(f"Aucun PDF trouve dans: {root_dir}")
        return 0, 0

    print(f"{len(pdf_files)} PDF detectes dans {root_dir}\n")
    valid_count = 0

    for pdf_path in pdf_files:
        text = _extract_pdf_text(pdf_path)
        missing = _missing_markers(text)

        if missing:
            print(f"[KO] {pdf_path}")
            print(f"     Manquants: {', '.join(missing)}")
        else:
            print(f"[OK] {pdf_path}")
            valid_count += 1

    return valid_count, len(pdf_files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifie que chaque PDF contient les marqueurs 1., 2., 3., 4., 5."
    )
    parser.add_argument(
        "--root-dir",
        default="/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/omega/pdfs",
        help="Dossier racine contenant les fichiers PDF a verifier.",
    )
    args = parser.parse_args()

    root_dir = Path(args.root_dir)
    if not root_dir.exists():
        raise FileNotFoundError(f"Dossier introuvable: {root_dir}")
    if not root_dir.is_dir():
        raise NotADirectoryError(f"Chemin invalide (pas un dossier): {root_dir}")

    valid_count, total_count = check_pdfs(root_dir)
    print("\n--- Resume ---")
    print(f"PDF conformes : {valid_count}")
    print(f"PDF non conformes : {total_count - valid_count}")
    print(f"Total : {total_count}")


if __name__ == "__main__":
    main()
