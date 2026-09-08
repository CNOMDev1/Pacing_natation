"""Stockage des performances saisies depuis l'app iPad / macOS."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pacing.config.paths import PROCESSED_DIR

MANUAL_PERFORMANCES_DIR = PROCESSED_DIR / "manual_performances"


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    return cleaned.strip("_") or "nageur"


def parse_time_to_seconds(raw: str) -> float:
    """
    Accepte ``63.31``, ``1:03.31`` ou ``1:03,31``.

    Raises:
        ValueError: Si le temps est invalide.
    """
    text = str(raw).strip().replace(",", ".")
    if not text:
        raise ValueError("le temps est obligatoire")
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError("temps invalide (utilisez m:ss.cc ou secondes)")
        minutes = float(parts[0])
        seconds = float(parts[1])
        value = minutes * 60.0 + seconds
    else:
        value = float(text)
    if value <= 0 or value > 3600:
        raise ValueError("temps hors plage")
    return round(value, 2)


def _swimmer_file(name: str, year_of_birth: Optional[int], country: str) -> Any:
    yob_part = str(year_of_birth) if year_of_birth else "na"
    return MANUAL_PERFORMANCES_DIR / f"{_slug(name)}_{yob_part}_{country}.json"


def _age_from_yob_and_date(year_of_birth: Optional[int], meet_date: Optional[str]) -> Optional[float]:
    if year_of_birth is None or not meet_date:
        return None
    try:
        when = datetime.fromisoformat(str(meet_date)[:10])
    except ValueError:
        return None
    return float(when.year - int(year_of_birth))


def save_manual_swimmer(
    *,
    name: str,
    year_of_birth: Optional[int],
    gender: Optional[str],
    country: str,
    club: Optional[str] = None,
    stroke: str,
    distance: int,
    pool: str,
    time_s: Optional[float] = None,
    time_text: Optional[str] = None,
    meet_date: Optional[str] = None,
    age: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Ajoute une performance dans ``data/processed/manual_performances``.

    Un fichier par nageur (nom + année + pays) ; les courses s'ajoutent.
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
    stroke_s = str(stroke).strip().upper()
    pool_s = str(pool).strip().upper()
    if stroke_s not in {"FR", "BK", "BR", "FL", "IM"}:
        raise ValueError("nage invalide")
    if pool_s not in {"LCM", "SCM", "SCY"}:
        raise ValueError("bassin invalide")
    distance_i = int(distance)
    if distance_i <= 0:
        raise ValueError("distance invalide")

    if time_s is not None:
        time_value = float(time_s)
    elif time_text:
        time_value = parse_time_to_seconds(time_text)
    else:
        raise ValueError("le temps est obligatoire")

    age_value = age if age is not None else _age_from_yob_and_date(year_of_birth, meet_date)
    if age_value is None:
        raise ValueError("indiquer l'âge à la course, ou l'année de naissance et la date")

    MANUAL_PERFORMANCES_DIR.mkdir(parents=True, exist_ok=True)
    path = _swimmer_file(name_s, year_of_birth, country_s)
    now = datetime.now(timezone.utc).isoformat()
    label = f"{name_s} ({year_of_birth})" if year_of_birth else name_s

    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
    else:
        payload = {}

    performances = payload.get("performances")
    if not isinstance(performances, list):
        performances = []

    performances.append(
        {
            "stroke": stroke_s,
            "distance": distance_i,
            "pool": pool_s,
            "time_s": time_value,
            "age": age_value,
            "meet_date": meet_date,
        }
    )

    payload.update(
        {
            "name": name_s,
            "year_of_birth": year_of_birth,
            "gender": gender_s,
            "country": country_s,
            "club": club.strip() if isinstance(club, str) and club.strip() else payload.get("club"),
            "label": label,
            "source": "ios",
            "updated_at": now,
            "performances": performances,
        }
    )
    payload.setdefault("created_at", now)
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
    if not MANUAL_PERFORMANCES_DIR.is_dir():
        return []
    q = query.strip().casefold()
    country_s = country.strip().upper() if country else None
    gender_s = gender.strip().upper() if gender else "ALL"
    hits: List[Dict[str, Any]] = []
    for path in sorted(MANUAL_PERFORMANCES_DIR.glob("*.json")):
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


def list_manual_points(
    *,
    name: str,
    year_of_birth: Optional[int],
    country: Optional[str],
    stroke: str,
    distance: int,
    pool: str,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Points âge × temps d'un nageur manuel pour une épreuve."""
    name_s = str(name).strip()
    if not name_s or not MANUAL_PERFORMANCES_DIR.is_dir():
        return None, []
    country_s = country.strip().upper() if country else None
    stroke_s = str(stroke).strip().upper()
    pool_s = str(pool).strip().upper()
    distance_i = int(distance)
    identity: Optional[Dict[str, Any]] = None
    points: List[Dict[str, Any]] = []
    q = name_s.casefold()
    for path in MANUAL_PERFORMANCES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        row_name = str(data.get("name") or "").strip()
        if row_name.casefold() != q:
            continue
        yob = data.get("year_of_birth")
        try:
            yob_i = int(yob) if yob is not None else None
        except (TypeError, ValueError):
            yob_i = None
        if year_of_birth is not None and yob_i is not None and yob_i != int(year_of_birth):
            continue
        row_country = str(data.get("country") or "").upper()
        if country_s and row_country and row_country != country_s:
            continue
        identity = {
            "name": row_name,
            "year_of_birth": yob_i if yob_i is not None else year_of_birth,
            "gender": data.get("gender"),
            "country": row_country or country_s,
        }
        for perf in data.get("performances") or []:
            if not isinstance(perf, dict):
                continue
            if str(perf.get("stroke") or "").upper() != stroke_s:
                continue
            try:
                if int(perf.get("distance")) != distance_i:
                    continue
            except (TypeError, ValueError):
                continue
            if str(perf.get("pool") or "").upper() != pool_s:
                continue
            try:
                age_v = float(perf.get("age"))
                time_v = float(perf.get("time_s"))
            except (TypeError, ValueError):
                continue
            points.append({"age": age_v, "time_s": time_v})
        break
    points.sort(key=lambda p: p["age"])
    return identity, points
