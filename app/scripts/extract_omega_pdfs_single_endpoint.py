import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests


ENDPOINT_URL = "https://cnom-background-jobs.azurewebsites.net/api/extract"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_source_dir() -> Path:
    return _project_root() / "app" / "data" / "omega" / "pdfs"


def _default_output_root() -> Path:
    return _project_root() / "app" / "data" / "omega_json_endpoint_single"


def _build_output_path(pdf_path: Path, output_root: Path) -> Path:
    parts = pdf_path.parts
    output_dir = output_root

    if "pdfs" in parts:
        idx = parts.index("pdfs")
        if idx + 1 < len(parts):
            maybe_year = parts[idx + 1]
            if maybe_year.isdigit():
                output_dir = output_root / maybe_year

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{pdf_path.stem}.json"


def _extract_one_pdf(pdf_path: Path, functions_key: str, timeout_seconds: int) -> dict[str, Any]:
    headers = {
        "x-functions-key": functions_key,
        "Content-Type": "application/pdf",
    }
    pdf_bytes = pdf_path.read_bytes()
    resp = requests.post(
        ENDPOINT_URL,
        headers=headers,
        data=pdf_bytes,
        timeout=timeout_seconds,
    )
    resp.raise_for_status()
    return resp.json()


def _iter_pdf_batches(source_root: Path, batch_size: int, year_filter: int | None = None) -> list[list[Path]]:
    batches: list[list[Path]] = []
    year_dirs = sorted(
        [d for d in source_root.iterdir() if d.is_dir() and d.name.isdigit()],
        key=lambda d: int(d.name),
    )
    if year_filter is not None:
        year_dirs = [d for d in year_dirs if int(d.name) == year_filter]
    for year_dir in year_dirs:
        year_pdfs = sorted(year_dir.glob("*.pdf"), key=lambda p: p.name)
        for i in range(0, len(year_pdfs), batch_size):
            batches.append(year_pdfs[i : i + batch_size])
    return batches


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrait des PDFs Omega via /api/extract (single) et écrit un JSON par PDF."
    )
    parser.add_argument(
        "year",
        nargs="?",
        type=int,
        help="Année optionnelle à traiter (ex: 2005). Si absente, traite toutes les années.",
    )
    parser.add_argument(
        "--source-dir",
        default=str(_default_source_dir()),
        help="Dossier racine contenant les sous-dossiers d'années (ex: .../omega/pdfs).",
    )
    parser.add_argument(
        "--output-root",
        default=str(_default_output_root()),
        help="Dossier racine de sortie JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre max de PDFs à traiter au total (toutes années confondues).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Taille du lot de traitement (nombre de PDFs par batch).",
    )
    parser.add_argument(
        "--functions-key-env",
        default="OMEGA_EXTRACTION_FUNCTIONS_KEY",
        help="Nom de la variable d'environnement contenant x-functions-key.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="Timeout HTTP (secondes) par PDF.",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        raise FileNotFoundError(f"source-dir introuvable: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"source-dir invalide (pas un dossier): {source_dir}")
    if args.batch_size <= 0:
        raise RuntimeError("--batch-size doit être > 0.")

    functions_key = os.environ.get(args.functions_key_env, "").strip()
    if not functions_key:
        raise RuntimeError(
            f"Clé manquante: définis la variable `{args.functions_key_env}` avec la valeur x-functions-key."
        )
    if functions_key == "TA_CLE_X_FUNCTIONS_KEY":
        raise RuntimeError("Clé placeholder détectée: remplace par la vraie x-functions-key.")

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    batches = _iter_pdf_batches(source_dir, args.batch_size, year_filter=args.year)
    all_pdfs = [pdf for batch in batches for pdf in batch]
    if args.limit is not None:
        all_pdfs = all_pdfs[: args.limit]
    if not all_pdfs:
        raise RuntimeError(f"Aucun PDF trouvé dans: {source_dir} (sous-dossiers d'années attendus).")

    effective_batches: list[list[Path]] = []
    for i in range(0, len(all_pdfs), args.batch_size):
        effective_batches.append(all_pdfs[i : i + args.batch_size])

    ok_count = 0
    fail_count = 0
    total = len(all_pdfs)
    processed = 0

    for batch_idx, batch in enumerate(effective_batches, start=1):
        batch_years = sorted({p.parent.name for p in batch})
        print(
            f"--- Batch {batch_idx}/{len(effective_batches)} | size={len(batch)} | years={','.join(batch_years)} ---"
        )
        for pdf_path in batch:
            processed += 1
            out_path = _build_output_path(pdf_path, output_root)
            try:
                payload = _extract_one_pdf(pdf_path, functions_key, args.timeout_seconds)
                out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                ok_count += 1
                print(f"[OK {processed}/{total}] {pdf_path.name} -> {out_path}")
            except Exception as exc:
                fail_payload = {"source_pdf": str(pdf_path), "error": str(exc)}
                out_path.write_text(json.dumps(fail_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                fail_count += 1
                print(f"[KO {processed}/{total}] {pdf_path.name}: {exc}")

    print(f"Terminé. OK={ok_count} | KO={fail_count} | Total={total}")


if __name__ == "__main__":
    main()

