"""Compte le nombre d'éléments dans le champ `results`."""

import json
import os
from pathlib import Path


def count_results_in_file(json_path: Path) -> int:
    """
    Retourne un nombre d'éléments de résultats pour un fichier de compétition.
    Stratégie (dans l'ordre) :
    - si `results` est une liste, retourne len(results)
    - sinon si `results_count` est un entier, retourne cette valeur
    - sinon si `epreuves` est une liste, somme len(epreuve["performances"])
      pour chaque épreuve où `performances` est une liste
    - sinon 0
    """
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Erreur lors de la lecture de {json_path}: {e}")
        return 0

    results = data.get("results")
    if isinstance(results, list):
        return len(results)

    results_count = data.get("results_count")
    if isinstance(results_count, int):
        return results_count

    epreuves = data.get("epreuves")
    if isinstance(epreuves, list):
        total = 0
        for epreuve in epreuves:
            if not isinstance(epreuve, dict):
                continue
            performances = epreuve.get("performances")
            if isinstance(performances, list):
                total += len(performances)
        return total

    return 0


def main() -> None:
    base_dir = (
        Path(__file__)
        .resolve()
        .parent  
        .parent  
        / "data"
        / "extranat"
        / "competitions_per_type"
    )

    if not base_dir.exists() or not base_dir.is_dir():
        print(f"Le dossier '{base_dir}' n'existe pas ou n'est pas un dossier.")
        return

    subdirs = sorted(d for d in base_dir.iterdir() if d.is_dir())
    if not subdirs:
        print(f"Aucun sous-dossier dans '{base_dir}'.")
        return

    total_global_results = 0

    for subdir in subdirs:
        print(f"\n=== {subdir.name} ===")
        json_files = sorted(
            p for p in subdir.iterdir() if p.is_file() and p.suffix.lower() == ".json"
        )
        if not json_files:
            print("  (aucun fichier JSON)")
            continue

        subdir_total = 0
        for json_file in json_files:
            count = count_results_in_file(json_file)
            subdir_total += count
            total_global_results += count
            print(f"  {json_file.name:70s} : {count:5d} résultat(s)")

        print(f"  {'TOTAL SOUS-DOSSIER':70s} : {subdir_total:5d} résultat(s)")

    print("\n" + "-" * 80)
    print(f"{'TOTAL GLOBAL RESULTS':70s} : {total_global_results:5d} résultat(s)")


if __name__ == "__main__":
    main()

