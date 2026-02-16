"""
Comptage des PDFs Omega par année (app/data/omega/pdfs).
À exécuter : python -m app.scripts.count_omega_pdfs_by_year
"""
import os
from pathlib import Path


def count_pdfs_in_directory(directory_path: Path) -> int:
    """Compte le nombre de fichiers PDF dans un répertoire (non récursif)."""
    try:
        return sum(
            1 for f in os.listdir(directory_path)
            if f.lower().endswith(".pdf")
        )
    except (PermissionError, OSError):
        return 0


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent / "data" / "omega" / "pdfs"
    if not base_dir.exists() or not base_dir.is_dir():
        print(f"Le dossier '{base_dir}' n'existe pas ou n'est pas un dossier.")
        return
    subdirs = sorted(d for d in base_dir.iterdir() if d.is_dir())
    if not subdirs:
        print(f"Aucun sous-dossier dans '{base_dir}'.")
        return
    total = 0
    for subdir in subdirs:
        count = count_pdfs_in_directory(subdir)
        print(f"  {subdir.name:20s} : {count:5d} PDF(s)")
        total += count
    print("-" * 40)
    print(f"  {'TOTAL':20s} : {total:5d} PDF(s)")


if __name__ == "__main__":
    main()
