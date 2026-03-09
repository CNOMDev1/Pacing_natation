from collections import Counter
from pathlib import Path


def count_countries(path: Path) -> None:
    """
    Lit un fichier texte où chaque ligne commence par un pays,
    puis compte le nombre d'occurrences par pays.
    """
    counts = Counter()

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # On coupe d'abord sur tabulation, sinon sur espaces
            if "\t" in line:
                country = line.split("\t", 1)[0].strip()
            else:
                parts = line.split()
                if not parts:
                    continue
                country = parts[0].strip()

            counts[country] += 1

    # Tri par nombre d'occurrences décroissant, puis par nom de pays
    for country, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        # Affichage sous la forme "Zimbabwe 33"
        print(f"{country} {n}")


if __name__ == "__main__":
    # Adapte ce chemin si tu veux analyser un autre fichier
    path = Path(
        "/Users/nouhailaimaneabbassi/.cursor/projects/Users-nouhailaimaneabbassi-Desktop-Pacing/terminals/1.txt"
    )
    count_countries(path)

