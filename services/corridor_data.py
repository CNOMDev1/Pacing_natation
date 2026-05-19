"""Préparation vectorisée des données pour les graphiques couloir de performance."""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd

_PREP_CACHE: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
_PREP_CACHE_MAX = 96


def corridor_norm_name(value: object) -> str:
    txt = "" if value is None else str(value).strip().lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", txt)


def _prep_cache_key(
    df: pd.DataFrame,
    nom_event: str,
    *,
    solo_only: bool,
    require_name: bool,
) -> tuple:
    swim_sum = 0.0
    if len(df) and "SwimTimeSeconds" in df.columns:
        swim_sum = float(pd.to_numeric(df["SwimTimeSeconds"], errors="coerce").sum())
    return (str(nom_event), bool(solo_only), bool(require_name), len(df), swim_sum)


def prepare_corridor_long_df(
    df: pd.DataFrame,
    nom_event: str,
    *,
    solo_only: bool = True,
    require_name: bool = False,
) -> pd.DataFrame:
    """Filtre l'épreuve et extrait Name/Gender/Year_of_birth/Age_swim."""
    cache_key = _prep_cache_key(df, nom_event, solo_only=solo_only, require_name=require_name)
    cached = _PREP_CACHE.get(cache_key)
    if cached is not None:
        _PREP_CACHE.move_to_end(cache_key)
        return cached

    required_cols = ["swimmer", "SwimDate", "Event", "SwimTimeSeconds"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        return pd.DataFrame()

    event_mask = df["Event"].astype(str) == str(nom_event)
    time_mask = df["SwimTimeSeconds"].notna()
    data = df.loc[event_mask & time_mask, required_cols]
    if data.empty:
        return pd.DataFrame()

    swimmers = data["swimmer"].to_numpy()
    n = len(swimmers)
    is_solo = np.zeros(n, dtype=bool)
    first_swimmer: list[object] = [None] * n
    for i, sw in enumerate(swimmers):
        ok = isinstance(sw, list) and len(sw) == 1
        is_solo[i] = ok
        first_swimmer[i] = sw[0] if ok else None

    if solo_only:
        keep = is_solo
        if not keep.any():
            return pd.DataFrame()
        data = data.loc[keep].copy()
        first_swimmer = [first_swimmer[i] for i in range(n) if keep[i]]
    else:
        data = data.copy()
        first_swimmer = []
        for i, sw in enumerate(swimmers):
            if isinstance(sw, list) and len(sw) >= 1:
                first_swimmer.append(sw[0])
            else:
                first_swimmer.append(None)

    m = len(data)
    names = np.empty(m, dtype=object)
    genders = np.empty(m, dtype=object)
    yobs = np.empty(m, dtype=object)
    ages = np.empty(m, dtype=object)
    for i, d in enumerate(first_swimmer):
        if isinstance(d, dict):
            names[i] = d.get("Name")
            genders[i] = d.get("Gender")
            yobs[i] = d.get("Year_of_birth")
            ages[i] = d.get("Age")

    out = data.copy()
    out["Name"] = names
    out["Gender"] = genders
    out["Year_of_birth"] = yobs
    out["Age_json"] = ages

    swim_year = pd.to_datetime(out["SwimDate"], errors="coerce").dt.year
    age_swim = pd.to_numeric(pd.Series(ages, index=out.index), errors="coerce")
    yob_num = pd.to_numeric(pd.Series(yobs, index=out.index), errors="coerce")
    missing_age = age_swim.isna() & yob_num.notna() & swim_year.notna()
    if missing_age.any():
        age_swim = age_swim.copy()
        age_swim.loc[missing_age] = swim_year.loc[missing_age] - yob_num.loc[missing_age]
    out["Age_swim"] = pd.to_numeric(age_swim, errors="coerce").astype("Int64")

    valid = out["Gender"].notna() & out["Age_swim"].notna()
    if require_name:
        valid &= out["Name"].notna() & out["Year_of_birth"].notna()
    result = out.loc[valid].copy()

    _PREP_CACHE[cache_key] = result
    _PREP_CACHE.move_to_end(cache_key)
    if len(_PREP_CACHE) > _PREP_CACHE_MAX:
        _PREP_CACHE.popitem(last=False)
    return result


def compute_corridor_percentiles_df(
    long_df: pd.DataFrame,
    percentiles: list[int],
    *,
    age_min: int,
    age_max: int,
    min_points: int,
) -> Optional[pd.DataFrame]:
    """Percentiles par âge via groupby.quantile (plus rapide que listes + boucles)."""
    if long_df.empty:
        return None
    sub = long_df[
        long_df["Age_swim"].notna()
        & (long_df["Age_swim"] >= age_min)
        & (long_df["Age_swim"] <= age_max)
    ]
    if sub.empty:
        return None
    counts = sub.groupby("Age_swim")["SwimTimeSeconds"].transform("count")
    sub = sub.loc[counts >= min_points]
    if sub.empty:
        return None
    qs = [p / 100.0 for p in percentiles]
    wide = (
        sub.groupby("Age_swim", sort=True)["SwimTimeSeconds"]
        .quantile(qs)
        .unstack(level=1)
    )
    if wide.empty:
        return None
    wide.columns = [f"p{int(round(c * 100))}" for c in wide.columns]
    return wide.sort_index()


def resolve_corridor_swimmer(
    long_df: pd.DataFrame,
    nom_nageur: str,
    year_of_birth: int,
    *,
    fuzzy_min_ratio: float = 0.55,
    fuzzy_max_yob_diff: float = 999.0,
) -> tuple[pd.DataFrame, str, int]:
    """Retourne les performances du nageur cible (triées par âge) et le nom/année résolus."""
    target_name = str(nom_nageur).strip()
    target_norm = corridor_norm_name(target_name)
    yob_target = int(year_of_birth)

    unique = (
        long_df[["Name", "Year_of_birth"]]
        .dropna(subset=["Name", "Year_of_birth"])
        .drop_duplicates()
        .copy()
    )
    if unique.empty:
        return pd.DataFrame(), target_name, yob_target

    unique["__norm"] = unique["Name"].astype(str).map(corridor_norm_name)
    unique["__yob"] = pd.to_numeric(unique["Year_of_birth"], errors="coerce")
    unique = unique.dropna(subset=["__yob"])

    resolved_name = target_name
    resolved_yob = yob_target

    exact = unique[(unique["__norm"] == target_norm) & (unique["__yob"] == yob_target)]
    if exact.empty:
        by_name = unique[unique["__norm"] == target_norm]
        if not by_name.empty:
            best = by_name.iloc[(by_name["__yob"] - yob_target).abs().argmin()]
            resolved_name = str(best["Name"]).strip()
            resolved_yob = int(float(best["__yob"]))
        else:
            tokens = [t for t in target_norm.split(" ") if t]
            if tokens:
                token_mask = unique["__norm"].map(lambda n: all(tok in n for tok in tokens))
                by_tokens = unique[token_mask]
                if not by_tokens.empty:
                    best = by_tokens.iloc[(by_tokens["__yob"] - yob_target).abs().argmin()]
                    resolved_name = str(best["Name"]).strip()
                    resolved_yob = int(float(best["__yob"]))
            if resolved_name == target_name and len(unique) <= 500:
                unique["__ratio"] = unique["__norm"].map(
                    lambda n: difflib.SequenceMatcher(None, target_norm, n).ratio()
                )
                unique["__yob_diff"] = (unique["__yob"] - yob_target).abs()
                fuzzy = unique.sort_values(
                    by=["__ratio", "__yob_diff"], ascending=[False, True]
                )
                if not fuzzy.empty:
                    best = fuzzy.iloc[0]
                    ratio = float(best["__ratio"])
                    yob_diff = float(best["__yob_diff"])
                    if ratio >= fuzzy_min_ratio and yob_diff <= fuzzy_max_yob_diff:
                        resolved_name = str(best["Name"]).strip()
                        resolved_yob = int(float(best["__yob"]))

    resolved_norm = corridor_norm_name(resolved_name)
    name_norm_series = long_df["Name"].astype(str).map(corridor_norm_name)
    yob_series = pd.to_numeric(long_df["Year_of_birth"], errors="coerce")
    swimmer_data = long_df[
        (name_norm_series == resolved_norm) & (yob_series == resolved_yob)
    ].sort_values("Age_swim")
    return swimmer_data, resolved_name, resolved_yob
