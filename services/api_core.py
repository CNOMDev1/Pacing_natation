"""Cœur API Pacing : réponses JSON structurées pour FastAPI / NiceGUI.

Délègue le chargement à ``PacingAppService`` et les calculs couloir à
``corridor_data`` (sans matplotlib).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pacing.analytics.corridor_data import (
    STANDARD_CORRIDOR_PERCENTILES,
    compute_corridor_percentiles_df,
    corridor_age_limits,
    filter_corridor_long_df_gender,
    prepare_corridor_long_df,
    resolve_corridor_swimmer_flexible,
)
from pacing.application.scope import event_combinations
from pacing.domain.normalize import normalize_gender_code, normalize_text
from services.app_service import (
    COUNTRY_FRANCE,
    COUNTRY_MOROCCO,
    COUNTRY_USA,
    PacingAppService,
    USA_CORRIDOR_MIN_POINTS,
)

# Codes API stables → libellés UI / loaders
_COUNTRY_BY_CODE: Dict[str, str] = {
    "FR": COUNTRY_FRANCE,
    "MA": COUNTRY_MOROCCO,
    "US": COUNTRY_USA,
}
_CODE_BY_COUNTRY: Dict[str, str] = {v: k for k, v in _COUNTRY_BY_CODE.items()}

_STROKE_LABELS: Dict[str, str] = {
    "FR": "Nage libre",
    "BK": "Dos",
    "BR": "Brasse",
    "FL": "Papillon",
    "IM": "4 nages",
}

_LABEL_YOB_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<yob>\d{4})\)\s*$")

_USA_AGEGROUP_ORDER: Tuple[str, ...] = (
    "10 & Under",
    "11-12",
    "13-14",
    "15-18",
    "19 & Over",
    "Not Applicable",
)


@lru_cache(maxsize=1)
def get_app_service() -> PacingAppService:
    """
    Retourne une instance unique de la façade métier.

    Returns:
        PacingAppService: Façade partagée (loaders + caches).
    """
    return PacingAppService()


def resolve_country_code(country: str) -> str:
    """
    Normalise un code ou libellé pays vers ``FR`` / ``MA`` / ``US``.

    Args:
        country (str): Code (``FR``) ou libellé (``France``).

    Returns:
        str: Code pays normalisé.

    Raises:
        ValueError: Si le pays est inconnu.
    """
    raw = str(country).strip()
    upper = raw.upper()
    if upper in _COUNTRY_BY_CODE:
        return upper
    for label, code in _CODE_BY_COUNTRY.items():
        if normalize_text(label) == normalize_text(raw):
            return code
    raise ValueError(f"Pays inconnu: {country!r} (attendu FR, MA, US)")


def list_countries() -> Dict[str, Any]:
    """
    Liste les pays supportés par l'API.

    Returns:
        Dict[str, Any]: Payload ``countries``.
    """
    return {
        "countries": [
            {"code": "FR", "label": "France"},
            {"code": "US", "label": "États-Unis"},
            {"code": "MA", "label": "Maroc"},
        ]
    }


def _nav_df_for_code(code: str) -> pd.DataFrame:
    """
    Charge le DataFrame de navigation pour un code pays.

    Args:
        code (str): ``FR``, ``MA`` ou ``US``.

    Returns:
        pd.DataFrame: Performances navigables (vide pour US hors couloir event).
    """
    app = get_app_service()
    if code == "US":
        return pd.DataFrame()
    if code == "MA":
        return app.get_frmnatation_df()
    return app.load_extranat()


def _event_label(distance: int, stroke: str, pool: str) -> str:
    """
    Construit le libellé d'épreuve unifié.

    Args:
        distance (int): Distance en mètres.
        stroke (str): Code nage.
        pool (str): Code bassin.

    Returns:
        str: Ex. ``100 FR LCM``.
    """
    return f"{int(distance)} {str(stroke).strip()} {str(pool).strip()}"


def _parse_swimmer_label(label: str) -> Tuple[str, Optional[int]]:
    """
    Découpe un libellé ``Nom (YYYY)`` éventuel.

    Args:
        label (str): Libellé UI ou nom brut.

    Returns:
        Tuple[str, Optional[int]]: Nom et année de naissance optionnelle.
    """
    text = str(label).strip()
    match = _LABEL_YOB_RE.match(text)
    if not match:
        return text, None
    return match.group("name").strip(), int(match.group("yob"))


def search_swimmers(
    *,
    q: str,
    country: str,
    stroke: Optional[str] = None,
    distance: Optional[int] = None,
    pool: Optional[str] = None,
    event: Optional[str] = None,
    gender: str = "all",
    limit: int = 30,
) -> Dict[str, Any]:
    """
    Recherche des nageurs (autocomplete) dans le scope demandé.

    Args:
        q (str): Préfixe / sous-chaîne de recherche.
        country (str): Code ou libellé pays.
        stroke (Optional[str]): Code nage.
        distance (Optional[int]): Distance (m).
        pool (Optional[str]): Bassin.
        event (Optional[str]): Libellé épreuve exact.
        gender (str): ``F``, ``M`` ou ``all``.
        limit (int): Nombre max de résultats.

    Returns:
        Dict[str, Any]: Payload conforme au contrat ``/swimmers/search``.

    Raises:
        ValueError: Si le pays est invalide.
    """
    code = resolve_country_code(country)
    query = str(q).strip()
    limit_n = max(1, min(int(limit), 100))
    gender_key = normalize_gender_code(gender) or "all"
    if gender_key not in ("F", "M", "all"):
        gender_key = "all"

    app = get_app_service()
    results: List[Dict[str, Any]] = []

    if code == "MA":
        labels = app.morocco_swimmer_labels(
            stroke=stroke,
            distance=distance,
            pool=pool,
            event=event,
            gender=gender_key,
        )
        q_norm = normalize_text(query)
        for label in labels:
            if q_norm and q_norm not in normalize_text(label):
                continue
            name, yob = _parse_swimmer_label(label)
            results.append(
                {
                    "label": label,
                    "name": name,
                    "year_of_birth": yob,
                    "gender": None,
                    "country": code,
                }
            )
            if len(results) >= limit_n:
                break
    elif code == "US":
        usa_event = event or (
            _event_label(distance, stroke, pool)
            if stroke and distance is not None and pool
            else None
        )
        if not usa_event:
            return {
                "status": "empty",
                "query": query,
                "count": 0,
                "results": [],
                "message": "Pour US, fournir event ou stroke+distance+pool",
            }
        names = app.usa_swimmer_names(usa_event, gender=gender_key)
        q_norm = normalize_text(query)
        for name in names:
            if q_norm and q_norm not in normalize_text(name):
                continue
            results.append(
                {
                    "label": name,
                    "name": name,
                    "year_of_birth": None,
                    "gender": None,
                    "country": code,
                }
            )
            if len(results) >= limit_n:
                break
    else:
        df = _nav_df_for_code("FR")
        if df.empty:
            return {"status": "empty", "query": query, "count": 0, "results": []}
        scoped = df
        if event:
            scoped = scoped[scoped["Event"].astype(str).str.strip() == str(event).strip()]
        elif stroke and distance is not None and pool:
            nom = _event_label(distance, stroke, pool)
            scoped = scoped[
                (scoped["Stroke"].astype(str).str.strip() == str(stroke).strip())
                & (pd.to_numeric(scoped["Distance"], errors="coerce") == int(distance))
                & (scoped["Course"].astype(str).str.strip() == str(pool).strip())
            ]
            if "Event" in scoped.columns:
                scoped = scoped[scoped["Event"].astype(str).str.strip() == nom]
        if gender_key in ("F", "M") and "Gender" not in scoped.columns:
            # Genre souvent dans swimmer[] — on ne filtre pas strictement ici
            pass
        q_norm = normalize_text(query)
        seen: set[Tuple[str, Optional[int]]] = set()
        for _, row in scoped.iterrows():
            swimmers = row.get("swimmer")
            if not isinstance(swimmers, list) or not swimmers:
                continue
            first = swimmers[0]
            if not isinstance(first, dict):
                continue
            name = first.get("Name")
            if not name:
                continue
            name_s = str(name).strip()
            yob_raw = first.get("Year_of_birth")
            try:
                yob = int(yob_raw) if yob_raw is not None and str(yob_raw).strip() else None
            except (TypeError, ValueError):
                yob = None
            g = first.get("Gender")
            g_code = normalize_gender_code(g) if g is not None else None
            if gender_key in ("F", "M") and g_code is not None and g_code != gender_key:
                continue
            label = f"{name_s} ({yob})" if yob is not None else name_s
            if q_norm and q_norm not in normalize_text(label):
                continue
            key = (name_s, yob)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "label": label,
                    "name": name_s,
                    "year_of_birth": yob,
                    "gender": g_code,
                    "country": code,
                }
            )
            if len(results) >= limit_n:
                break
        results.sort(key=lambda r: normalize_text(r["label"]))

    return {
        "status": "ok" if results else "empty",
        "query": query,
        "count": len(results),
        "results": results,
    }


def build_corridor_payload(
    *,
    country: str,
    stroke: str,
    distance: int,
    pool: str,
    gender: str = "all",
    swimmer_name: Optional[str] = None,
    swimmer_yob: Optional[int] = None,
    swimmer_country: Optional[str] = None,
    corridor_type: str = "age_global",
) -> Dict[str, Any]:
    """
    Calcule le payload JSON d'un couloir de performance (FR / MA / US).

    Args:
        country (str): Pays du **peloton** (percentiles).
        stroke (str): Code nage.
        distance (int): Distance (m).
        pool (str): Bassin.
        gender (str): Filtre genre.
        swimmer_name (Optional[str]): Nageur cible (``age_target``).
        swimmer_yob (Optional[int]): Année de naissance.
        swimmer_country (Optional[str]): Pays source du nageur
            (défaut = ``country``).
        corridor_type (str): ``age_global`` ou ``age_target``.

    Returns:
        Dict[str, Any]: Payload conforme au contrat ``/corridors/performance``.

    Raises:
        ValueError: Si un code pays est invalide.
    """
    code = resolve_country_code(country)

    swimmer_code: Optional[str] = None
    if swimmer_country is not None and str(swimmer_country).strip():
        swimmer_code = resolve_country_code(swimmer_country)
    elif swimmer_name and str(swimmer_name).strip():
        swimmer_code = code

    event = _event_label(distance, stroke, pool)
    gender_key = normalize_gender_code(gender)
    gender_filter = gender_key if gender_key in ("F", "M") else None

    want_swimmer = bool(swimmer_name and str(swimmer_name).strip()) or (
        corridor_type == "age_target"
    )

    if code == "US":
        df_usa = get_app_service().get_usa_corridor_df(event)
        bands, row_count = _build_usa_agegroup_bands(
            df_usa, event=event, gender_filter=gender_filter
        )
        effective_type = (
            "usa_agegroup_target" if want_swimmer else "usa_agegroup"
        )
        meta = {
            "country": code,
            "corridor_type": effective_type,
            "event": event,
            "stroke": str(stroke).strip(),
            "distance": int(distance),
            "pool": str(pool).strip(),
            "gender": gender_filter or "all",
            "swimmer_country": swimmer_code,
            "units": {
                "age_group": "label",
                "time": "seconds",
                "distance": "m",
            },
            "row_count": row_count,
        }
        if row_count == 0 and not bands:
            return {
                "status": "empty",
                "meta": meta,
                "bands": [],
                "swimmer": None,
                "image_base64": None,
            }

        swimmer_payload: Optional[Dict[str, Any]] = None
        if want_swimmer and swimmer_name and str(swimmer_name).strip():
            swimmer_payload = _resolve_swimmer_on_usa_corridor(
                code=swimmer_code or code,
                swimmer_name=str(swimmer_name),
                swimmer_yob=swimmer_yob,
                event=event,
                gender_filter=gender_filter,
                df_usa=df_usa,
            )
            if not swimmer_payload["points"]:
                return {
                    "status": "not_found",
                    "meta": meta,
                    "bands": bands,
                    "swimmer": swimmer_payload,
                    "image_base64": None,
                    "missing": ["swimmer"],
                }

        return {
            "status": "ok" if bands else "empty",
            "meta": meta,
            "bands": bands,
            "swimmer": swimmer_payload,
            "image_base64": None,
        }

    # --- FR / MA (âge en années) ---
    if swimmer_code == "US" and want_swimmer:
        raise ValueError(
            "Nageur US uniquement supporté quand country=US (peloton USA)"
        )

    df = _nav_df_for_code(code)
    long_df = prepare_corridor_long_df(df, event, solo_only=True, require_name=False)
    if gender_filter:
        long_df = filter_corridor_long_df_gender(long_df, gender_filter)

    meta = {
        "country": code,
        "corridor_type": corridor_type,
        "event": event,
        "stroke": str(stroke).strip(),
        "distance": int(distance),
        "pool": str(pool).strip(),
        "gender": gender_filter or "all",
        "swimmer_country": swimmer_code,
        "units": {"age": "years", "time": "seconds", "distance": "m"},
        "row_count": int(len(long_df)),
    }

    if long_df.empty:
        return {
            "status": "empty",
            "meta": meta,
            "bands": [],
            "swimmer": None,
            "image_base64": None,
        }

    bands = _build_bands_from_long_df(long_df)

    swimmer_payload = None
    if want_swimmer and swimmer_name and str(swimmer_name).strip():
        meta["corridor_type"] = "age_target"
        if swimmer_code == code:
            long_swimmer = long_df
        else:
            assert swimmer_code is not None
            df_sw = _nav_df_for_code(swimmer_code)
            long_swimmer = prepare_corridor_long_df(
                df_sw, event, solo_only=True, require_name=False
            )
            if gender_filter:
                long_swimmer = filter_corridor_long_df_gender(
                    long_swimmer, gender_filter
                )
        swimmer_payload = _resolve_swimmer_curve(
            long_swimmer,
            swimmer_name=str(swimmer_name),
            swimmer_yob=swimmer_yob,
            country_code=swimmer_code or code,
            gender_filter=gender_filter,
        )
        if not swimmer_payload["points"]:
            return {
                "status": "not_found",
                "meta": meta,
                "bands": bands,
                "swimmer": swimmer_payload,
                "image_base64": None,
                "missing": ["swimmer"],
            }

    return {
        "status": "ok" if bands else "empty",
        "meta": meta,
        "bands": bands,
        "swimmer": swimmer_payload,
        "image_base64": None,
    }



def _build_bands_from_long_df(long_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Agrège les bandes percentiles âge × temps depuis un DataFrame long.

    Args:
        long_df (pd.DataFrame): Peloton long (Age_swim, SwimTimeSeconds).

    Returns:
        List[Dict[str, Any]]: Bandes ``age``, ``n``, ``p10``…``p90``.
    """
    if long_df.empty:
        return []
    age_min, age_max = corridor_age_limits(long_df, [])
    bands_df = compute_corridor_percentiles_df(
        long_df,
        STANDARD_CORRIDOR_PERCENTILES,
        age_min=age_min,
        age_max=age_max,
        min_points=5,
    )
    bands: List[Dict[str, Any]] = []
    if bands_df is None or bands_df.empty:
        return bands
    counts = (
        long_df.groupby("Age_swim")["SwimTimeSeconds"].count()
        if "Age_swim" in long_df.columns
        else pd.Series(dtype=int)
    )
    for age, row in bands_df.iterrows():
        age_i = int(age)
        entry: Dict[str, Any] = {"age": age_i, "n": int(counts.get(age, 0))}
        for col in bands_df.columns:
            val = row[col]
            if pd.notna(val):
                entry[str(col)] = round(float(val), 3)
        bands.append(entry)
    return bands


def _resolve_swimmer_curve(
    long_df: pd.DataFrame,
    *,
    swimmer_name: str,
    swimmer_yob: Optional[int],
    country_code: str,
    gender_filter: Optional[str],
) -> Dict[str, Any]:
    """
    Résout un nageur et construit sa courbe âge × temps.

    Args:
        long_df (pd.DataFrame): Peloton / source pour la résolution.
        swimmer_name (str): Nom ou libellé ``Nom (YOB)``.
        swimmer_yob (Optional[int]): Année de naissance explicite.
        country_code (str): Code pays du nageur.
        gender_filter (Optional[str]): Genre du contexte.

    Returns:
        Dict[str, Any]: Payload nageur (name, year_of_birth, country, points).
    """
    name, yob_from_label = _parse_swimmer_label(str(swimmer_name))
    yob = swimmer_yob if swimmer_yob is not None else yob_from_label
    df_s, resolved_name, resolved_yob = resolve_corridor_swimmer_flexible(
        long_df, name, yob
    )
    points: List[Dict[str, Any]] = []
    if not df_s.empty and "Age_swim" in df_s.columns:
        ages = pd.to_numeric(df_s["Age_swim"], errors="coerce")
        times = pd.to_numeric(df_s["SwimTimeSeconds"], errors="coerce")
        valid = ages.notna() & times.notna()
        plot = df_s.loc[valid].sort_values("Age_swim")
        for _, prow in plot.iterrows():
            points.append(
                {
                    "age": float(prow["Age_swim"]),
                    "time_s": round(float(prow["SwimTimeSeconds"]), 3),
                }
            )
    return {
        "name": resolved_name or name,
        "year_of_birth": resolved_yob if resolved_yob is not None else yob,
        "country": country_code,
        "gender": gender_filter,
        "points": points,
    }


def _build_usa_agegroup_bands(
    df_usa: pd.DataFrame,
    *,
    event: str,
    gender_filter: Optional[str],
    min_points: int = USA_CORRIDOR_MIN_POINTS,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Calcule les bandes percentiles USA par ``AgeGroup``.

    Args:
        df_usa (pd.DataFrame): Performances USA (Event, SwimTimeSeconds, AgeGroup).
        event (str): Libellé d'épreuve.
        gender_filter (Optional[str]): ``F`` / ``M`` ou None.
        min_points (int): Effectif minimal par catégorie.

    Returns:
        Tuple[List[Dict[str, Any]], int]: Bandes et nombre de lignes utilisées.
    """
    required = {"Event", "SwimTimeSeconds", "AgeGroup"}
    if df_usa.empty or not required.issubset(df_usa.columns):
        return [], 0
    data = df_usa.loc[:, [c for c in df_usa.columns if c in (
        "Event", "SwimTimeSeconds", "AgeGroup", "Gender", "Name", "Year_of_birth"
    )]].copy()
    data["AgeGroup"] = data["AgeGroup"].fillna("").astype(str).str.strip()
    data = data[
        (data["Event"].astype(str).str.strip() == str(event).strip())
        & data["SwimTimeSeconds"].notna()
        & (data["AgeGroup"] != "")
    ]
    if gender_filter and "Gender" in data.columns:
        g = data["Gender"].astype(str).str.strip().str.upper()
        data = data[g == gender_filter]
    if data.empty:
        return [], 0

    grouped = data.groupby("AgeGroup")["SwimTimeSeconds"]
    counts = grouped.count()
    bands: List[Dict[str, Any]] = []
    present = set(counts.index.astype(str))
    ordered = [g for g in _USA_AGEGROUP_ORDER if g in present] + sorted(
        present - set(_USA_AGEGROUP_ORDER)
    )
    for ag in ordered:
        n = int(counts.get(ag, 0))
        if n < min_points:
            continue
        values = pd.to_numeric(grouped.get_group(ag), errors="coerce").dropna()
        if values.empty:
            continue
        entry: Dict[str, Any] = {"age_group": str(ag), "n": n}
        for p in STANDARD_CORRIDOR_PERCENTILES:
            entry[f"p{p}"] = round(float(np.percentile(values, p)), 3)
        bands.append(entry)
    return bands, int(len(data))


def _resolve_usa_style_swimmer_curve(
    df: pd.DataFrame,
    *,
    swimmer_name: str,
    swimmer_yob: Optional[int],
    country_code: str,
    event: str,
    gender_filter: Optional[str],
) -> Dict[str, Any]:
    """
    Résout un nageur sur un couloir USA (points par ``AgeGroup``).

    Args:
        df (pd.DataFrame): Source (USA ou overlay MA format USA).
        swimmer_name (str): Nom du nageur.
        swimmer_yob (Optional[int]): Année de naissance.
        country_code (str): Code pays du nageur.
        event (str): Épreuve.
        gender_filter (Optional[str]): Filtre genre.

    Returns:
        Dict[str, Any]: Payload nageur avec ``points`` ``age_group`` × ``time_s``.
    """
    name, yob_from_label = _parse_swimmer_label(str(swimmer_name))
    yob = swimmer_yob if swimmer_yob is not None else yob_from_label
    empty = {
        "name": name,
        "year_of_birth": yob,
        "country": country_code,
        "gender": gender_filter,
        "points": [],
    }
    if df.empty or "Name" not in df.columns or "SwimTimeSeconds" not in df.columns:
        return empty

    data = df.copy()
    if "Event" in data.columns:
        data = data[data["Event"].astype(str).str.strip() == str(event).strip()]
    if gender_filter and "Gender" in data.columns:
        g = data["Gender"].astype(str).str.strip().str.upper()
        data = data[g == gender_filter]
    data = data[data["SwimTimeSeconds"].notna()]
    if data.empty:
        return empty

    name_mask = data["Name"].astype(str).str.strip() == name.strip()
    if yob is not None and "Year_of_birth" in data.columns:
        yob_series = pd.to_numeric(data["Year_of_birth"], errors="coerce")
        name_mask = name_mask & (yob_series == int(yob))
    swimmer_data = data.loc[name_mask].copy()
    if swimmer_data.empty:
        return empty

    if "AgeGroup" not in swimmer_data.columns:
        return empty
    swimmer_data["AgeGroup"] = (
        swimmer_data["AgeGroup"].fillna("").astype(str).str.strip()
    )
    swimmer_data = swimmer_data[swimmer_data["AgeGroup"] != ""]
    if swimmer_data.empty:
        return empty

    curve = swimmer_data.groupby("AgeGroup")["SwimTimeSeconds"].mean()
    present = set(curve.index.astype(str))
    ordered = [g for g in _USA_AGEGROUP_ORDER if g in present] + sorted(
        present - set(_USA_AGEGROUP_ORDER)
    )
    points: List[Dict[str, Any]] = []
    for ag in ordered:
        if ag not in curve.index:
            continue
        points.append(
            {
                "age_group": str(ag),
                "time_s": round(float(curve.loc[ag]), 3),
            }
        )
    resolved_yob = yob
    if resolved_yob is None and "Year_of_birth" in swimmer_data.columns:
        yobs = pd.to_numeric(swimmer_data["Year_of_birth"], errors="coerce").dropna()
        if not yobs.empty:
            resolved_yob = int(yobs.mode().iloc[0])
    return {
        "name": str(swimmer_data.iloc[0]["Name"]).strip(),
        "year_of_birth": resolved_yob,
        "country": country_code,
        "gender": gender_filter,
        "points": points,
    }


def _age_to_usa_agegroup(age: float) -> str:
    """
    Mappe un âge numérique vers une catégorie USA Swimming approximative.

    Args:
        age (float): Âge en années.

    Returns:
        str: Libellé AgeGroup.
    """
    if age <= 10:
        return "10 & Under"
    if age <= 12:
        return "11-12"
    if age <= 14:
        return "13-14"
    if age <= 18:
        return "15-18"
    return "19 & Over"


def _resolve_swimmer_on_usa_corridor(
    *,
    code: str,
    swimmer_name: str,
    swimmer_yob: Optional[int],
    event: str,
    gender_filter: Optional[str],
    df_usa: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Résout un nageur (US / MA / FR) pour un couloir USA AgeGroup.

    Args:
        code (str): Pays source du nageur.
        swimmer_name (str): Nom.
        swimmer_yob (Optional[int]): YOB.
        event (str): Épreuve.
        gender_filter (Optional[str]): Genre.
        df_usa (pd.DataFrame): Peloton USA.

    Returns:
        Dict[str, Any]: Courbe nageur (points AgeGroup).
    """
    app = get_app_service()
    if code == "US":
        return _resolve_usa_style_swimmer_curve(
            df_usa,
            swimmer_name=swimmer_name,
            swimmer_yob=swimmer_yob,
            country_code=code,
            event=event,
            gender_filter=gender_filter,
        )
    if code == "MA":
        _, yob_int, rows = app.moroccan_corridor_overlay_bundle(
            ma_name=swimmer_name,
            ma_yob=swimmer_yob,
            nom_event=event,
            usa_mode=True,
        )
        return _resolve_usa_style_swimmer_curve(
            rows,
            swimmer_name=swimmer_name,
            swimmer_yob=yob_int if yob_int is not None else swimmer_yob,
            country_code=code,
            event=event,
            gender_filter=gender_filter,
        )
    # FR → Age_swim puis mapping vers AgeGroup
    df_fr = _nav_df_for_code("FR")
    long_fr = prepare_corridor_long_df(
        df_fr, event, solo_only=True, require_name=False
    )
    if gender_filter:
        long_fr = filter_corridor_long_df_gender(long_fr, gender_filter)
    curve = _resolve_swimmer_curve(
        long_fr,
        swimmer_name=swimmer_name,
        swimmer_yob=swimmer_yob,
        country_code=code,
        gender_filter=gender_filter,
    )
    if not curve["points"]:
        return curve
    by_group: Dict[str, List[float]] = {}
    for pt in curve["points"]:
        ag = _age_to_usa_agegroup(float(pt["age"]))
        by_group.setdefault(ag, []).append(float(pt["time_s"]))
    points = [
        {"age_group": ag, "time_s": round(float(np.mean(vals)), 3)}
        for ag, vals in by_group.items()
    ]
    present = {p["age_group"] for p in points}
    ordered = [g for g in _USA_AGEGROUP_ORDER if g in present] + sorted(
        present - set(_USA_AGEGROUP_ORDER)
    )
    points_sorted = sorted(points, key=lambda p: ordered.index(p["age_group"]))
    curve["points"] = points_sorted
    return curve


def build_compare_payload(
    *,
    country: str,
    stroke: str,
    distance: int,
    pool: str,
    swimmer_a_name: str,
    swimmer_b_name: str,
    gender: str = "all",
    swimmer_a_yob: Optional[int] = None,
    swimmer_b_yob: Optional[int] = None,
    swimmer_a_country: Optional[str] = None,
    swimmer_b_country: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare deux nageurs sur le même couloir de référence.

    Le peloton (bandes) vient de ``country`` (FR/MA par âge, US par AgeGroup).
    Chaque nageur peut provenir d'un autre pays.

    Args:
        country (str): Pays du couloir de référence.
        stroke (str): Code nage.
        distance (int): Distance (m).
        pool (str): Bassin.
        swimmer_a_name (str): Premier nageur.
        swimmer_b_name (str): Second nageur (overlay).
        gender (str): Filtre genre du couloir.
        swimmer_a_yob (Optional[int]): YOB A.
        swimmer_b_yob (Optional[int]): YOB B.
        swimmer_a_country (Optional[str]): Pays source A (défaut = ``country``).
        swimmer_b_country (Optional[str]): Pays source B (défaut = ``country``).

    Returns:
        Dict[str, Any]: Payload ``bands``, ``swimmer_a``, ``swimmer_b``.

    Raises:
        ValueError: Si un code pays est invalide.
    """
    ref_code = resolve_country_code(country)
    code_a = resolve_country_code(swimmer_a_country or ref_code)
    code_b = resolve_country_code(swimmer_b_country or ref_code)

    event = _event_label(distance, stroke, pool)
    gender_key = normalize_gender_code(gender)
    gender_filter = gender_key if gender_key in ("F", "M") else None

    if ref_code == "US":
        df_usa = get_app_service().get_usa_corridor_df(event)
        bands, row_count = _build_usa_agegroup_bands(
            df_usa, event=event, gender_filter=gender_filter
        )
        meta = {
            "country": ref_code,
            "corridor_type": "usa_agegroup",
            "event": event,
            "stroke": str(stroke).strip(),
            "distance": int(distance),
            "pool": str(pool).strip(),
            "gender": gender_filter or "all",
            "units": {
                "age_group": "label",
                "time": "seconds",
                "distance": "m",
            },
            "row_count": row_count,
        }
        swimmer_a = _resolve_swimmer_on_usa_corridor(
            code=code_a,
            swimmer_name=swimmer_a_name,
            swimmer_yob=swimmer_a_yob,
            event=event,
            gender_filter=gender_filter,
            df_usa=df_usa,
        )
        swimmer_b = _resolve_swimmer_on_usa_corridor(
            code=code_b,
            swimmer_name=swimmer_b_name,
            swimmer_yob=swimmer_b_yob,
            event=event,
            gender_filter=gender_filter,
            df_usa=df_usa,
        )
    else:
        df_ref = _nav_df_for_code(ref_code)
        long_ref = prepare_corridor_long_df(
            df_ref, event, solo_only=True, require_name=False
        )
        if gender_filter:
            long_ref = filter_corridor_long_df_gender(long_ref, gender_filter)

        meta = {
            "country": ref_code,
            "corridor_type": "age_target",
            "event": event,
            "stroke": str(stroke).strip(),
            "distance": int(distance),
            "pool": str(pool).strip(),
            "gender": gender_filter or "all",
            "units": {"age": "years", "time": "seconds", "distance": "m"},
            "row_count": int(len(long_ref)),
        }
        bands = _build_bands_from_long_df(long_ref)

        def _long_for_swimmer(code: str) -> pd.DataFrame:
            if code == "US":
                return pd.DataFrame()
            if code == ref_code:
                return long_ref
            df = _nav_df_for_code(code)
            long_df = prepare_corridor_long_df(
                df, event, solo_only=True, require_name=False
            )
            if gender_filter:
                long_df = filter_corridor_long_df_gender(long_df, gender_filter)
            return long_df

        if code_a == "US" or code_b == "US":
            raise ValueError(
                "Nageur US uniquement supporté quand country=US (peloton USA)"
            )

        swimmer_a = _resolve_swimmer_curve(
            _long_for_swimmer(code_a),
            swimmer_name=swimmer_a_name,
            swimmer_yob=swimmer_a_yob,
            country_code=code_a,
            gender_filter=gender_filter,
        )
        swimmer_b = _resolve_swimmer_curve(
            _long_for_swimmer(code_b),
            swimmer_name=swimmer_b_name,
            swimmer_yob=swimmer_b_yob,
            country_code=code_b,
            gender_filter=gender_filter,
        )

    missing: List[str] = []
    if not swimmer_a["points"]:
        missing.append("swimmer_a")
    if not swimmer_b["points"]:
        missing.append("swimmer_b")

    if missing:
        return {
            "status": "not_found",
            "meta": meta,
            "bands": bands,
            "swimmer_a": swimmer_a,
            "swimmer_b": swimmer_b,
            "missing": missing,
            "image_base64": None,
        }

    if not bands:
        return {
            "status": "empty",
            "meta": meta,
            "bands": [],
            "swimmer_a": swimmer_a,
            "swimmer_b": swimmer_b,
            "image_base64": None,
        }

    return {
        "status": "ok",
        "meta": meta,
        "bands": bands,
        "swimmer_a": swimmer_a,
        "swimmer_b": swimmer_b,
        "image_base64": None,
    }


def list_event_combos(country: str) -> Dict[str, Any]:
    """
    Liste les combinaisons nage → distance → bassins (prototype référentiel).

    Args:
        country (str): Code ou libellé pays.

    Returns:
        Dict[str, Any]: Arbre ``strokes`` avec distances et pools.

    Raises:
        ValueError: Pays invalide ou US non supporté ici.
    """
    code = resolve_country_code(country)
    if code == "US":
        events = get_app_service().list_usa_events()
        return {"country": code, "events": events[:200], "strokes": []}
    df = _nav_df_for_code(code)
    combos = event_combinations(df)
    strokes = []
    for stroke, dist_map in sorted(combos.items()):
        distances = []
        for dist, pools in sorted(dist_map.items()):
            distances.append(
                {
                    "distance": int(dist),
                    "unit": "m",
                    "pools": [{"code": p, "label": p} for p in pools],
                }
            )
        strokes.append(
            {
                "code": stroke,
                "label": _STROKE_LABELS.get(stroke, stroke),
                "distances": distances,
            }
        )
    return {"country": code, "strokes": strokes}
