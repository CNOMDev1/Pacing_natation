"""Export du schéma OpenAPI de l'API Pacing vers un fichier versionné.

Le contrat d'échange consommé par NiceGUI, DearPyGUI et iOS doit être
vérifiable sans lancer le serveur. Ce module écrit ``docs/openapi.json``
depuis l'application FastAPI elle-même : le fichier ne peut donc pas
divergerdu code, contrairement à une description rédigée à la main.

Usage ::

    python -m pacing.api.export_openapi              # écrit docs/openapi.json
    python -m pacing.api.export_openapi --check      # vérifie sans écrire
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from pacing.api.main import app
from pacing.config.paths import PROJECT_DIR

#: Emplacement versionné du contrat OpenAPI.
OPENAPI_PATH: Path = PROJECT_DIR / "docs" / "openapi.json"


def build_openapi() -> Dict[str, Any]:
    """Construit le schéma OpenAPI de l'application.

    Returns:
        Dict[str, Any]: Schéma OpenAPI complet.
    """
    return app.openapi()


def render_openapi() -> str:
    """Sérialise le schéma OpenAPI en JSON stable.

    Les clés sont triées et l'indentation est fixe pour que deux exports
    successifs sans changement de code produisent un fichier identique,
    donc un diff git vide.

    Returns:
        str: JSON indenté, terminé par un retour à la ligne.
    """
    return json.dumps(build_openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def export(path: Path = OPENAPI_PATH) -> Path:
    """Écrit le schéma OpenAPI sur disque.

    Args:
        path (Path): Fichier cible.

    Returns:
        Path: Chemin écrit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_openapi(), encoding="utf-8")
    return path


def check(path: Path = OPENAPI_PATH) -> bool:
    """Vérifie que le fichier sur disque correspond au code.

    Args:
        path (Path): Fichier à comparer.

    Returns:
        bool: ``True`` si le fichier est à jour.
    """
    if not path.exists():
        return False
    return path.read_text(encoding="utf-8") == render_openapi()


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI.

    Args:
        argv (list[str] | None): Arguments (``sys.argv[1:]`` par défaut).

    Returns:
        int: Code de sortie (0 = succès).
    """
    parser = argparse.ArgumentParser(description="Export du contrat OpenAPI Pacing.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="vérifie que docs/openapi.json est à jour, sans l'écrire",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OPENAPI_PATH,
        help="fichier de sortie (défaut : docs/openapi.json)",
    )
    args = parser.parse_args(argv)

    if args.check:
        if check(args.output):
            print(f"OK : {args.output} est à jour.")
            return 0
        print(
            f"OBSOLÈTE : {args.output} ne correspond plus au code. "
            "Relancez : python -m pacing.api.export_openapi",
            file=sys.stderr,
        )
        return 1

    written = export(args.output)
    schema = build_openapi()
    print(f"Écrit : {written} ({len(schema.get('paths', {}))} chemins)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
