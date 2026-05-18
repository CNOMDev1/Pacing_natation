"""Convertit les JSON USA Swimming (par annee) en fichiers Parquet."""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from services.usaswimming_competitions_data_loader import (
    DEFAULT_USASWIMMING_COMPETITIONS_DIR,
    UsaswimmingCompetitionsDataLoader,
)


def _parse_years(values: list[str] | None) -> list[str] | None:
    """Normalisation la liste d'années en CLI pour correspondre aux noms des dossiers"""
    if not values:
        return None
    return [str(year) for year in values]


def build_parser() -> argparse.ArgumentParser:
    """Construction du parser CLI"""
    parser = argparse.ArgumentParser(
        description=(
            "Convertir les fichiers JSON USA Swimming en format Parquet"
        )
    )
    parser.add_argument(
        "--years",
        nargs="+", # Une ou plusieurs valeurs
        metavar="YEAR", # Nom affiché dans l’aide (--help)
        help="Annees a convertir (ex: 2023 2024)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_dir = DEFAULT_USASWIMMING_COMPETITIONS_DIR.resolve()

    if not source_dir.exists():
        print(f"Dossier source introuvable: {source_dir}", file=sys.stderr) # Message d’erreur sur stderr (sortie d’erreur)
        return 1

    loader = UsaswimmingCompetitionsDataLoader(base_dir=source_dir)
    parquet_dir = loader.parquet_dir.resolve()

    available_years = loader.available_years(years=_parse_years(args.years))
    if not available_years:
        print(f"Aucun dossier annuel trouve dans {source_dir}", file=sys.stderr)
        return 1

    print(f"Source JSON : {source_dir}")
    print(f"Sortie Parquet : {parquet_dir}")
    print(f"Annees a traiter : {', '.join(available_years)}")

    try:
        written_files = loader.build_parquet_cache(
            years=_parse_years(args.years),
            progress_callback=print, # afficher la progression dans le terminal pendant la conversion.
        )
    except ImportError as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        print("Installez pyarrow: pip install pyarrow", file=sys.stderr)
        return 1

    if not written_files:
        print("Aucun fichier Parquet produit.")
        return 1

    print(f"\nTermine: {len(written_files)} fichier(s) Parquet disponible(s).")
    for parquet_file in written_files:
        print(f"  - {parquet_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
