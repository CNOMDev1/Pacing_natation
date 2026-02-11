import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_error_percentage(value: str) -> float:
    """
    Convertit une chaîne du style '2.7%' en float 2.7.
    Si la valeur est déjà un nombre, on la renvoie telle quelle.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            value = value[:-1].strip()
        try:
            return float(value.replace(",", "."))
        except ValueError:
            pass
    raise ValueError(f"Impossible de parser error_percentage: {value!r}")


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    resumes_dir = base_dir / "Resumes"

    if not resumes_dir.exists():
        raise SystemExit(f"Dossier 'Resumes' introuvable: {resumes_dir}")

    # On prend tous les fichiers 'resume_*.json' sauf le résumé global 'resume.json'
    resume_files: List[Path] = [
        p for p in resumes_dir.glob("resume_*.json") if p.name != "resume.json"
    ]

    if not resume_files:
        raise SystemExit("Aucun fichier 'resume_*.json' trouvé dans le dossier 'Resumes'.")

    values: List[Tuple[str, float]] = []

    for path in sorted(resume_files):
        try:
            data: Dict[str, Any] = load_json(path)
        except Exception as exc:
            print(f"Impossible de lire '{path}': {exc}")
            continue

        raw = data.get("error_percentage")
        if raw is None:
            # certains fichiers peuvent ne pas avoir de clé error_percentage
            print(f"Avertissement: pas de 'error_percentage' dans '{path.name}'")
            continue

        try:
            pct = parse_error_percentage(raw)
        except ValueError as exc:
            print(f"Avertissement: {exc} dans '{path.name}'")
            continue

        values.append((path.name, pct))

    if not values:
        raise SystemExit("Aucune valeur 'error_percentage' valide trouvée.")

    print("=== error_percentage par fichier de 'Resumes' ===")
    for name, pct in values:
        print(f"- {name}: {pct:.4f} %")

    avg = sum(p for _, p in values) / len(values)
    print("\n=== Moyenne globale ===")
    print(f"Erreur moyenne sur {len(values)} fichiers: {avg:.4f} %")


if __name__ == "__main__":
    main()

