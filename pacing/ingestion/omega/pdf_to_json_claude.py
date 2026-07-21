"""Extraction des PDF Omega Timing vers JSON structuré via l'API Claude.

Ce script parcourt les PDF « Total Ranking » stockés sous
``data/raw/omega/pdfs/{année}/`` et produit des fichiers JSON au format
``data/omega_json_endpoint_single/{année}/{nom}.json``.

Par défaut, seules les années 2014 à 2026 sont traitées (les années 2000 à
2013 sont ignorées car déjà présentes dans ``omega_json_endpoint_single``).

Point d'entrée CLI :

    python -m app.scripts.omega_pdf_to_json_claude

Configuration :

    Renseigner ``app/scripts/.env`` (ou exporter les variables d'environnement).

    ANTHROPIC_API_KEY (obligatoire) : clé API Anthropic.
    CLAUDE_MODEL (optionnel) : modèle Claude (défaut ``claude-sonnet-4-20250514``).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from anthropic import APIConnectionError, APIStatusError, RateLimitError
from dotenv import load_dotenv

# --- Chemins et paramètres par défaut ---

from pacing.config.paths import OMEGA_RAW_DIR, PROJECT_DIR

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = PROJECT_DIR
load_dotenv(_SCRIPT_DIR / ".env")
# Compat : ancien emplacement app/scripts/.env
load_dotenv(PROJECT_DIR / "app" / "scripts" / ".env")

PDF_BASE_DIR = OMEGA_RAW_DIR / "pdfs"
JSON_BASE_DIR = PROJECT_DIR / "data" / "omega_json_endpoint_single"

DEFAULT_START_YEAR = 2014
DEFAULT_END_YEAR = 2026
SKIP_YEARS_BEFORE = 2014

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")
DEFAULT_MAX_TOKENS = 16_000
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_MAX_RETRIES = 5

REQUIRED_TOP_LEVEL_KEYS = {"competition", "event", "records", "results"}

EXTRACTION_PROMPT = """Tu es un extracteur de données sportives. Analyse ce PDF de résultats de natation Omega Timing (« Total Ranking ») et renvoie UNIQUEMENT un objet JSON valide, sans texte avant ni après, sans balises markdown.

Structure exacte attendue :

{
  "competition": {
    "name": "NOM DE LA COMPÉTITION",
    "location": "Ville",
    "dates": "dates telles qu'affichées"
  },
  "event": {
    "number": 101,
    "distance": "400m",
    "stroke": "Medley",
    "gender": "Women",
    "round": "Finals"
  },
  "records": [
    {
      "type": "WR",
      "time": "4:34.79",
      "holder": "NOM Prénom",
      "country": "CHN",
      "date": "13-10-97",
      "location": "VILLE"
    }
  ],
  "results": [
    {
      "final": "A",
      "rank": 1,
      "name": "NOM Prénom",
      "nationality": "FRA",
      "yearOfBirth": 1998,
      "reactionTime": 0.83,
      "splits": [
        {"distance": "50m", "time": "30.42"},
        {"distance": "100m", "time": "1:04.78"}
      ],
      "finalTime": "4:44.20"
    }
  ]
}

Règles strictes :
- Conserver les temps tels qu'affichés (ex. "1:04.78", "30.42").
- ``records`` : tableau vide [] si aucun record n'est indiqué.
- ``final`` : lettre de la finale ("A", "B", etc.) ou null si non applicable.
- ``yearOfBirth`` : entier ; utiliser 0 si inconnu.
- ``reactionTime`` : nombre décimal ; utiliser 0 si absent.
- Inclure tous les nageurs listés dans le PDF avec leurs splits intermédiaires.
- ``event.number`` : numéro d'épreuve entier si visible, sinon 0.
- Ne pas inventer de données absentes du PDF.
"""


@dataclass
class ExtractionStats:
    """Compteurs agrégés pour une exécution du script.

    Attributes:
        processed (int): Nombre de PDF traités avec succès.
        skipped (int): Nombre de fichiers déjà valides ignorés.
        failed (int): Nombre d'échecs.
    """

    processed: int = 0
    skipped: int = 0
    failed: int = 0


def is_valid_extraction_payload(data: Any) -> bool:
    """Vérifie qu'un objet JSON correspond au schéma minimal attendu.

    Args:
        data (Any): Objet décodé depuis le JSON de sortie.

    Returns:
        bool: True si l'objet contient les clés requises et une liste ``results``.
    """
    if not isinstance(data, dict):
        return False
    if not REQUIRED_TOP_LEVEL_KEYS.issubset(data.keys()):
        return False
    if "error" in data:
        return False
    if not isinstance(data.get("results"), list):
        return False
    if not isinstance(data.get("competition"), dict):
        return False
    if not isinstance(data.get("event"), dict):
        return False
    if not isinstance(data.get("records"), list):
        return False
    return True


def load_existing_json(json_path: Path) -> dict[str, Any] | None:
    """Charge un JSON existant s'il est lisible.

    Args:
        json_path (Path): Chemin du fichier JSON.

    Returns:
        dict[str, Any] | None: Contenu décodé, ou None si absent ou illisible.
    """
    if not json_path.is_file():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def should_skip_pdf(pdf_path: Path, json_path: Path, force: bool) -> bool:
    """Détermine si un PDF peut être ignoré car déjà extrait.

    Args:
        pdf_path (Path): Chemin du PDF source.
        json_path (Path): Chemin du JSON cible.
        force (bool): Si True, ne jamais ignorer.

    Returns:
        bool: True si le traitement peut être sauté.
    """
    if force:
        return False
    existing = load_existing_json(json_path)
    return existing is not None and is_valid_extraction_payload(existing)


def encode_pdf_base64(pdf_path: Path) -> str:
    """Encode un PDF en base64 pour l'API Claude.

    Args:
        pdf_path (Path): Chemin du fichier PDF.

    Returns:
        str: Contenu encodé en base64 (UTF-8).

    Raises:
        OSError: Si la lecture du fichier échoue.
    """
    return base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")


def extract_json_from_response_text(text: str) -> dict[str, Any]:
    """Parse le texte de réponse Claude en objet JSON.

    Args:
        text (str): Texte brut renvoyé par le modèle.

    Returns:
        dict[str, Any]: Objet JSON extrait.

    Raises:
        ValueError: Si aucun JSON valide n'est trouvé.
    """
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Aucun objet JSON détecté dans la réponse Claude.")
        cleaned = cleaned[start : end + 1]

    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("La réponse Claude n'est pas un objet JSON.")
    return payload


def call_claude_for_pdf(
    client: anthropic.Anthropic,
    pdf_path: Path,
    *,
    model: str,
    max_tokens: int,
    max_retries: int,
) -> dict[str, Any]:
    """Envoie un PDF à Claude et récupère le JSON structuré.

    Args:
        client (anthropic.Anthropic): Client API Anthropic initialisé.
        pdf_path (Path): Chemin du PDF à analyser.
        model (str): Identifiant du modèle Claude.
        max_tokens (int): Limite de tokens en sortie.
        max_retries (int): Nombre maximal de tentatives en cas d'erreur transitoire.

    Returns:
        dict[str, Any]: Données extraites validées minimalement.

    Raises:
        ValueError: Si la réponse n'est pas un JSON valide au format attendu.
        APIStatusError: Si l'API échoue après toutes les tentatives.
        APIConnectionError: Si la connexion échoue après toutes les tentatives.
    """
    pdf_b64 = encode_pdf_base64(pdf_path)
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": EXTRACTION_PROMPT,
                            },
                        ],
                    }
                ],
            )
            text_blocks = [
                block.text
                for block in message.content
                if hasattr(block, "text") and block.text
            ]
            if not text_blocks:
                raise ValueError("Réponse Claude vide.")
            payload = extract_json_from_response_text("\n".join(text_blocks))
            if not is_valid_extraction_payload(payload):
                raise ValueError("JSON extrait incomplet ou invalide.")
            return payload
        except (RateLimitError, APIConnectionError, APIStatusError) as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            wait_seconds = min(60.0, 2.0 ** attempt)
            print(
                f"  Tentative {attempt}/{max_retries} échouée ({type(exc).__name__}), "
                f"nouvelle tentative dans {wait_seconds:.0f}s...",
                flush=True,
            )
            time.sleep(wait_seconds)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= max_retries:
                raise ValueError(
                    f"Échec parsing JSON après {max_retries} tentatives: {exc}"
                ) from exc
            time.sleep(1.0)

    raise RuntimeError(f"Extraction impossible: {last_error}")


def write_json_output(json_path: Path, payload: dict[str, Any]) -> None:
    """Écrit le JSON extrait sur disque avec indentation.

    Args:
        json_path (Path): Chemin de sortie.
        payload (dict[str, Any]): Données à sérialiser.

    Returns:
        None
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_error_output(json_path: Path, pdf_path: Path, error_message: str) -> None:
    """Enregistre un fichier JSON d'erreur pour faciliter la reprise.

    Args:
        json_path (Path): Chemin de sortie.
        pdf_path (Path): PDF source concerné.
        error_message (str): Message d'erreur lisible.

    Returns:
        None
    """
    payload = {
        "source_pdf": str(pdf_path),
        "error": error_message,
    }
    write_json_output(json_path, payload)


def iter_pdfs_for_years(start_year: int, end_year: int) -> list[tuple[int, Path]]:
    """Liste les PDF à traiter pour une plage d'années.

    Args:
        start_year (int): Première année incluse.
        end_year (int): Dernière année incluse.

    Returns:
        list[tuple[int, Path]]: Couples (année, chemin PDF) triés par année puis nom.
    """
    if start_year > end_year:
        start_year, end_year = end_year, start_year

    items: list[tuple[int, Path]] = []
    for year in range(start_year, end_year + 1):
        if year < SKIP_YEARS_BEFORE:
            continue
        year_dir = PDF_BASE_DIR / str(year)
        if not year_dir.is_dir():
            print(f"Année {year} : dossier absent ({year_dir}), ignorée.", flush=True)
            continue
        for pdf_path in sorted(year_dir.glob("*.pdf")):
            items.append((year, pdf_path))
    return items


def process_pdf(
    client: anthropic.Anthropic,
    year: int,
    pdf_path: Path,
    *,
    model: str,
    max_tokens: int,
    max_retries: int,
    force: bool,
    write_errors: bool,
) -> str:
    """Traite un PDF unique et écrit le JSON associé.

    Args:
        client (anthropic.Anthropic): Client API Anthropic.
        year (int): Année de la compétition.
        pdf_path (Path): Chemin du PDF source.
        model (str): Modèle Claude.
        max_tokens (int): Limite de tokens en sortie.
        max_retries (int): Tentatives max sur erreurs transitoires.
        force (bool): Réécrire même si un JSON valide existe déjà.
        write_errors (bool): Écrire un JSON d'erreur en cas d'échec.

    Returns:
        str: ``"processed"``, ``"skipped"`` ou ``"failed"``.
    """
    json_path = JSON_BASE_DIR / str(year) / f"{pdf_path.stem}.json"
    if should_skip_pdf(pdf_path, json_path, force):
        return "skipped"

    try:
        payload = call_claude_for_pdf(
            client,
            pdf_path,
            model=model,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        write_json_output(json_path, payload)
        return "processed"
    except Exception as exc:
        print(f"  ERREUR {pdf_path.name}: {exc}", flush=True)
        if write_errors:
            write_error_output(json_path, pdf_path, str(exc))
        return "failed"


def run_extraction(
    *,
    start_year: int,
    end_year: int,
    model: str,
    max_tokens: int,
    delay_seconds: float,
    max_retries: int,
    force: bool,
    write_errors: bool,
    limit: int | None,
) -> ExtractionStats:
    """Lance l'extraction sur toute la plage d'années configurée.

    Args:
        start_year (int): Première année incluse.
        end_year (int): Dernière année incluse.
        model (str): Modèle Claude.
        max_tokens (int): Limite de tokens en sortie.
        delay_seconds (float): Pause entre deux appels API.
        max_retries (int): Tentatives max par PDF.
        force (bool): Réécrire les JSON existants valides.
        write_errors (bool): Persister les erreurs en JSON.
        limit (int | None): Nombre max de PDF à traiter (debug).

    Returns:
        ExtractionStats: Statistiques finales.

    Raises:
        RuntimeError: Si ``ANTHROPIC_API_KEY`` est absente.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Variable ANTHROPIC_API_KEY manquante. "
            "Renseignez-la dans app/scripts/.env ou exportez-la dans le terminal."
        )

    client = anthropic.Anthropic(api_key=api_key)
    pdfs = iter_pdfs_for_years(start_year, end_year)
    if limit is not None:
        pdfs = pdfs[:limit]

    stats = ExtractionStats()
    total = len(pdfs)
    print(
        f"Extraction Omega PDF → JSON | années {start_year}-{end_year} | "
        f"{total} PDF | modèle {model}",
        flush=True,
    )

    for index, (year, pdf_path) in enumerate(pdfs, start=1):
        print(f"[{index}/{total}] {year}/{pdf_path.name}", flush=True)
        status = process_pdf(
            client,
            year,
            pdf_path,
            model=model,
            max_tokens=max_tokens,
            max_retries=max_retries,
            force=force,
            write_errors=write_errors,
        )
        if status == "processed":
            stats.processed += 1
        elif status == "skipped":
            stats.skipped += 1
        else:
            stats.failed += 1

        if status == "processed" and delay_seconds > 0 and index < total:
            time.sleep(delay_seconds)

    return stats


def build_arg_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments CLI.

    Returns:
        argparse.ArgumentParser: Parseur configuré.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Extrait les résultats des PDF Omega Timing (2014-2026) vers JSON "
            "via l'API Claude."
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"Première année à traiter (défaut: {DEFAULT_START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        help=f"Dernière année à traiter (défaut: {DEFAULT_END_YEAR}).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Modèle Claude (défaut: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Tokens max en sortie (défaut: {DEFAULT_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Pause en secondes entre deux PDF (défaut: {DEFAULT_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Tentatives max par PDF (défaut: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Réécrire les JSON déjà valides.",
    )
    parser.add_argument(
        "--no-error-files",
        action="store_true",
        help="Ne pas écrire de fichiers JSON en cas d'erreur.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limiter le nombre de PDF traités (utile pour les tests).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée CLI du script d'extraction Omega.

    Args:
        argv (list[str] | None): Arguments de ligne de commande (``None`` = ``sys.argv``).

    Returns:
        int: Code de sortie (0 succès, 1 erreur).
    """
    args = build_arg_parser().parse_args(argv)
    try:
        stats = run_extraction(
            start_year=args.start_year,
            end_year=args.end_year,
            model=args.model,
            max_tokens=args.max_tokens,
            delay_seconds=args.delay,
            max_retries=args.max_retries,
            force=args.force,
            write_errors=not args.no_error_files,
            limit=args.limit,
        )
    except RuntimeError as exc:
        print(f"Erreur: {exc}", file=sys.stderr, flush=True)
        return 1

    print(
        f"\nTerminé — traités: {stats.processed}, ignorés: {stats.skipped}, "
        f"échecs: {stats.failed}",
        flush=True,
    )
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
