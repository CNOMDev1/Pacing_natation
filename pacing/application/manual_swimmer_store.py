"""Stockage des nageurs saisis depuis l'app iPad / macOS."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pacing.config.paths import PROCESSED_DIR

MANUAL_SWIMMERS_DIR = PROCESSED_DIR / "manual_swimmers"


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    return cleaned.strip("_") or "nageur"


def save_manual_swimmer(
    *,
    name: str,
    year_of_birth: Optional[int],
    gender: Optional[str],
    country: str,
    club: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Écrit un JSON nageur dans ``data/processed/manual_swimmers``.

    Returns:
        dict: ``status``, ``path``, ``swimmer``.
    """
    name_s = str(name).strip()
    if not name_s:
        raise ValueError("le nom du nageur ne peut pas être vide")
    country_s = str(country).strip().upper()
    if country_s not in {"FR", "MA", "US"}:
        raise ValueError("pays invalide")
    gender_s = str(gender).strip().upper() if gender else None
    if gender_s in {"", "ALL"}:
        gender_s = None
    if gender_s not in {None, "F", "M"}:
        raise ValueError("genre invalide")

    MANUAL_SWIMMERS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    yob_part = str(year_of_birth) if year_of_birth else "na"
    filename = f"{_slug(name_s)}_{yob_part}_{country_s}_{stamp}.json"
    path = MANUAL_SWIMMERS_DIR / filename

    label = f"{name_s} ({year_of_birth})" if year_of_birth else name_s
    payload = {
        "name": name_s,
        "year_of_birth": year_of_birth,
        "gender": gender_s,
        "country": country_s,
        "club": club.strip() if isinstance(club, str) and club.strip() else None,
        "label": label,
        "source": "ios",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "path": str(path),
        "swimmer": {
            "label": label,
            "name": name_s,
            "year_of_birth": year_of_birth,
            "gender": gender_s,
            "country": country_s,
        },
    }


def list_manual_swimmers(
    *,
    query: str = "",
    country: Optional[str] = None,
    gender: str = "all",
) -> List[Dict[str, Any]]:
    """Lit les nageurs manuels (filtre nom / pays / genre)."""
    if not MANUAL_SWIMMERS_DIR.is_dir():
        return []
    q = query.strip().casefold()
    country_s = country.strip().upper() if country else None
    gender_s = gender.strip().upper() if gender else "ALL"
    hits: List[Dict[str, Any]] = []
    for path in sorted(MANUAL_SWIMMERS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or "").strip()
        if not name:
            continue
        row_country = str(data.get("country") or "").upper()
        if country_s and row_country != country_s:
            continue
        row_gender = data.get("gender")
        row_gender_s = str(row_gender).upper() if row_gender else None
        if gender_s in {"F", "M"} and row_gender_s not in {None, gender_s}:
            continue
        yob = data.get("year_of_birth")
        try:
            yob_i = int(yob) if yob is not None else None
        except (TypeError, ValueError):
            yob_i = None
        label = str(data.get("label") or "").strip() or (
            f"{name} ({yob_i})" if yob_i else name
        )
        if q and q not in name.casefold() and q not in label.casefold():
            continue
        hits.append(
            {
                "label": label,
                "name": name,
                "year_of_birth": yob_i,
                "gender": row_gender_s,
                "country": row_country or "FR",
            }
        )
    return hits
