import json
from pathlib import Path
from typing import Any, Dict


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compute_results_count(data: Dict[str, Any]) -> int:
    """
    Calcule le nombre de résultats pour une compétition.

    - Si la clé 'results_count' est présente, on l'utilise.
    - Sinon, on compte la taille des tableaux 'performances'
      dans chaque entrée de 'epreuves'.
    """
    results_count = data.get("results_count")
    if isinstance(results_count, int):
        return results_count

    return compute_results_from_performances(data)


def compute_results_from_performances(data: Dict[str, Any]) -> int:
    """Compte les résultats en parcourant les tableaux 'performances'."""
    total = 0
    for epreuve in data.get("epreuves", []):
        performances = epreuve.get("performances", [])
        if isinstance(performances, list):
            total += len(performances)
    return total


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    competitions_dir = base_dir / "competitions_per_type"

    if not competitions_dir.exists():
        raise SystemExit(f"Dossier 'competitions_per_type' introuvable : {competitions_dir}")

    total_competitions = 0
    total_results = 0

    # stats par type de compétition (nom du sous-dossier direct)
    stats_by_type: Dict[str, Dict[str, int]] = {}

    print("=== Résultats par compétition ===")

    # On parcourt récursivement tous les fichiers JSON
    for json_path in sorted(competitions_dir.rglob("*.json")):
        try:
            data = load_json(json_path)
        except Exception as exc:  # pragma: no cover - garde-fou
            print(f"Impossible de lire '{json_path}': {exc}")
            continue

        # Détermination du type de compétition : premier sous-dossier sous 'competitions_per_type'
        try:
            relative = json_path.relative_to(competitions_dir)
            comp_type = relative.parts[0] if len(relative.parts) > 1 else "Racine"
        except ValueError:
            comp_type = "Inconnu"

        # Infos compétition
        name = data.get("name", json_path.stem)
        results = compute_results_count(data)

        print(f"- [{comp_type}] {name} : {results} résultats")

        # Agrégation globale
        total_competitions += 1
        total_results += results

        # Agrégation par type
        type_stats = stats_by_type.setdefault(
            comp_type, {"competitions": 0, "results": 0}
        )
        type_stats["competitions"] += 1
        type_stats["results"] += results

    print("\n=== Récapitulatif par type de compétition ===")
    for comp_type in sorted(stats_by_type):
        type_stats = stats_by_type[comp_type]
        print(
            f"- {comp_type} : "
            f"{type_stats['competitions']} compétitions, "
            f"{type_stats['results']} résultats"
        )

    print("\n=== Statistiques globales sur 'competitions_per_type' ===")
    print(f"Nombre total de compétitions : {total_competitions}")
    print(f"Nombre total de résultats    : {total_results}")


if __name__ == "__main__":
    main()

