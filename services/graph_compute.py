"""Cœur métier des graphiques Pacing (préparation et agrégations).

Ce module calcule DataFrames, statistiques et clés de sélection sans importer
matplotlib. Le rendu vit dans ``services.rendering.chart_plots`` ; l'orchestration
reste dans ``services.graph_service.ServiceGraphe``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from services.corridor_data import (
    CORRIDOR_FR_SWIMMER_COLOR,
    CORRIDOR_MA_SWIMMER_COLOR,
    CorridorSwimmerSpec,
    corridor_norm_name,
    parse_event_distance_m,
)
from services.stroke_labels import (
    format_event_label,
    localize_event_string,
    relabel_stroke_column,
    stroke_code_to_label,
    stroke_label_to_code,
)

CORRIDOR_OVERLAY_SWIMMER_COLOR = CORRIDOR_MA_SWIMMER_COLOR

CORRIDOR_OVERLAY_SWIMMER_LABEL = "Nageur marocain (MAR)"

_GENDER_LABEL_FEMALE = "Féminin"

_GENDER_LABEL_MALE = "Masculin"

_STROKE_SORT_ORDER: Dict[str, int] = {
    "FR": 0,
    "BK": 1,
    "BR": 2,
    "FL": 3,
    "IM": 4,
    "MD": 5,
}

def _stroke_label_sort_key(label: str) -> Tuple[int, str]:
    """Construit une clé de tri pour un libellé français de nage.

    Args:
        label (str): Libellé affiché (ex. ``Nage libre``).

    Returns:
        Tuple[int, str]: Rang natation standard puis libellé brut.
    """
    code = stroke_label_to_code(label)
    return (_STROKE_SORT_ORDER.get(code, 99), str(label))

def _ordered_stroke_labels(labels: List[str]) -> List[str]:
    """Trie les libellés de nage selon l'ordre compétition (FR, dos, brasse…).

    Args:
        labels (List[str]): Libellés français présents dans les données.

    Returns:
        List[str]: Libellés uniques triés.
    """
    unique = {str(label).strip() for label in labels if str(label).strip()}
    return sorted(unique, key=_stroke_label_sort_key)

_HEATMAP_STANDARD_DISTANCES: Tuple[int, ...] = (
    25,
    50,
    100,
    200,
    400,
    500,
    800,
    1000,
    1200,
    1500,
)

def _split_segment_tick_labels(
    split_nos: List[int],
    distance_by_no: Dict[int, int],
) -> List[str]:
    """Construit les libellés de segments pour l'axe des splits.

    Chaque segment est affiché sous la forme « début–fin m » (ex. ``0–50 m``),
    conformément à l'analyse par lap times (Robertson et al., 2009).

    Args:
        split_nos (List[int]): Numéros de split ordonnés.
        distance_by_no (Dict[int, int]): Distance cumulée de fin de segment par split.

    Returns:
        List[str]: Libellés prêts pour ``ax.set_xticklabels``.
    """
    labels: List[str] = []
    prev_end = 0
    for split_no in sorted(int(sn) for sn in split_nos):
        end_dist = int(distance_by_no.get(split_no, split_no * 50))
        labels.append(f"{prev_end}–{end_dist} m")
        prev_end = end_dist
    return labels

def _solo_swim_key_from_row(perf_idx: object, row: pd.Series) -> Optional[str]:
    """Calcule la clé ``swim_key`` alignée sur ``extract_event_split_speed_rows``.

    Args:
        perf_idx (object): Index de la performance dans le DataFrame source.
        row (pd.Series): Ligne performance (nage solo).

    Returns:
        Optional[str]: Clé unique ou ``None`` si nageur invalide.
    """
    swimmers = row.get("swimmer")
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None
    swimmer = swimmers[0]
    if not isinstance(swimmer, dict):
        return None
    name = swimmer.get("Name")
    if not isinstance(name, str) or not name.strip():
        return None
    return (
        f"{perf_idx}|{name}|{row.get('SwimDate')}|"
        f"{row.get('SwimTimeSeconds')}"
    )

def _resolve_fastest_solo_swim_for_event(
    df: pd.DataFrame,
    nom_event: str,
) -> Optional[Tuple[str, str, str, float]]:
    """Identifie la performance solo la plus rapide pour une épreuve.

    Args:
        df (pd.DataFrame): Performances source.
        nom_event (str): Libellé exact de l'épreuve.

    Returns:
        Optional[Tuple[str, str, str, float]]: ``(swim_key, nom, genre, temps)`` ;
            ``None`` si aucune performance exploitable.
    """
    if df.empty or "Event" not in df.columns:
        return None
    event_mask = df["Event"].astype(str).str.strip() == str(nom_event).strip()
    candidates = df.loc[
        event_mask
        & df["SwimTimeSeconds"].notna()
        & df["swimmer"].apply(lambda swimmers: isinstance(swimmers, list) and len(swimmers) == 1)
    ].copy()
    if candidates.empty:
        return None
    best_row = candidates.nsmallest(1, "SwimTimeSeconds").iloc[0]
    perf_idx = best_row.name
    swim_key = _solo_swim_key_from_row(perf_idx, best_row)
    if not swim_key:
        return None
    swimmer = best_row["swimmer"][0]
    name = str(swimmer.get("Name", "")).strip()
    gender = str(swimmer.get("Gender", "")).strip().upper()
    if gender not in ("F", "M"):
        gender = "M" if gender.startswith("M") else "F" if gender.startswith("F") else "?"
    swim_time = float(best_row["SwimTimeSeconds"])
    return swim_key, name, gender, swim_time

def _top_n_swim_keys_for_event(
    df: pd.DataFrame,
    nom_event: str,
    *,
    top_n: int = 10,
) -> List[str]:
    """Retourne les clés ``swim_key`` des ``top_n`` performances les plus rapides.

    Args:
        df (pd.DataFrame): Performances source.
        nom_event (str): Libellé exact de l'épreuve.
        top_n (int): Nombre de performances à retenir.

    Returns:
        List[str]: Clés uniques, dans l'ordre des temps croissants.
    """
    if df.empty or "Event" not in df.columns or top_n <= 0:
        return []
    event_mask = df["Event"].astype(str).str.strip() == str(nom_event).strip()
    candidates = df.loc[
        event_mask
        & df["SwimTimeSeconds"].notna()
        & df["swimmer"].apply(lambda swimmers: isinstance(swimmers, list) and len(swimmers) == 1)
    ].copy()
    if candidates.empty:
        return []
    keys: List[str] = []
    for perf_idx, row in candidates.nsmallest(int(top_n), "SwimTimeSeconds").iterrows():
        swim_key = _solo_swim_key_from_row(perf_idx, row)
        if swim_key and swim_key not in keys:
            keys.append(swim_key)
    return keys

def _top_n_swim_keys_for_event_by_gender(
    df: pd.DataFrame,
    nom_event: str,
    *,
    top_n: int = 10,
) -> Dict[str, List[str]]:
    """Retourne les ``top_n`` clés ``swim_key`` les plus rapides par genre.

    Args:
        df (pd.DataFrame): Performances source.
        nom_event (str): Libellé exact de l'épreuve.
        top_n (int): Nombre de performances à retenir par genre (F/M).

    Returns:
        Dict[str, List[str]]: Clés par genre, temps croissants.
    """
    out: Dict[str, List[str]] = {"F": [], "M": []}
    if df.empty or "Event" not in df.columns or top_n <= 0:
        return out
    event_mask = df["Event"].astype(str).str.strip() == str(nom_event).strip()
    for gender in ("F", "M"):
        candidates = df.loc[
            event_mask
            & df["SwimTimeSeconds"].notna()
            & df["swimmer"].apply(
                lambda swimmers, g=gender: (
                    isinstance(swimmers, list)
                    and len(swimmers) == 1
                    and isinstance(swimmers[0], dict)
                    and str(swimmers[0].get("Gender", "")).strip().upper().startswith(g)
                )
            )
        ].copy()
        keys: List[str] = []
        for perf_idx, row in candidates.nsmallest(int(top_n), "SwimTimeSeconds").iterrows():
            swim_key = _solo_swim_key_from_row(perf_idx, row)
            if swim_key and swim_key not in keys:
                keys.append(swim_key)
        out[gender] = keys
    return out

def _is_relay_swimmers(swimmers: object) -> bool:
    """Indique si la cellule ``swimmer`` représente une performance relais.

    Args:
        swimmers (object): Valeur de la colonne ``swimmer``.

    Returns:
        bool: ``True`` si la liste contient au moins deux nageurs dict.
    """
    return (
        isinstance(swimmers, list)
        and len(swimmers) > 1
        and all(isinstance(item, dict) for item in swimmers)
    )

def _extract_relay_split_speed_rows(
    df: pd.DataFrame,
    nom_event: str,
) -> pd.DataFrame:
    """Extrait les vitesses de split (format long) pour les relais d'une épreuve.

    Chaque ligne correspond à un segment de relais avec un ``split_no`` ordinal
    (1 = premier passage, etc.) pour un alignement visuel cohérent avec les
    graphiques solo.

    Args:
        df (pd.DataFrame): Performances source (Extranat).
        nom_event (str): Libellé exact de l'épreuve.

    Returns:
        pd.DataFrame: Colonnes ``relay_key``, ``split_no``, ``split_distance``,
            ``split_speed``, ``nb_swimmers`` ; vide si aucun relais exploitable.
    """
    if df.empty or "Event" not in df.columns:
        return pd.DataFrame()
    event_mask = df["Event"].astype(str).str.strip() == str(nom_event).strip()
    rows: List[dict[str, object]] = []
    for perf_idx, row in df.loc[event_mask].iterrows():
        swimmers = row.get("swimmer")
        if not _is_relay_swimmers(swimmers):
            continue
        splits = row.get("splits")
        if not isinstance(splits, list):
            continue
        entries: List[Tuple[int, float]] = []
        for split in splits:
            if not isinstance(split, dict):
                continue
            dist = _parse_split_distance_m(split.get("split_distance"))
            speed_raw = split.get("split_speed")
            if dist is None or speed_raw is None:
                continue
            try:
                speed = float(speed_raw)
            except (TypeError, ValueError):
                continue
            if speed <= 0:
                continue
            entries.append((dist, speed))
        if not entries:
            continue
        entries.sort(key=lambda item: item[0])
        relay_key = f"{perf_idx}|{row.get('SwimDate')}|{len(swimmers)}"
        for split_no, (distance, speed) in enumerate(entries, start=1):
            rows.append(
                {
                    "relay_key": relay_key,
                    "split_no": split_no,
                    "split_distance": distance,
                    "split_speed": speed,
                    "nb_swimmers": len(swimmers),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)

def _prepare_speed_heatmap_long_df(df: pd.DataFrame) -> pd.DataFrame:
    """Prépare un tableau long vitesse × distance × nage pour les heatmaps.

    Ne conserve que les nages solo avec une vitesse et une distance valides.
    Les codes nage sont convertis en libellés français pour l'affichage.

    Args:
        df (pd.DataFrame): Performances source (Extranat).

    Returns:
        pd.DataFrame: Colonnes ``Name``, ``Name_norm``, ``Distance``, ``Stroke``,
            ``Speed`` ; vide si aucune ligne exploitable.
    """
    if df.empty:
        return pd.DataFrame()

    if "SwimmerName" in df.columns:
        work = df.loc[
            df["SwimmerName"].notna(),
            ["SwimmerName", "Distance", "Stroke", "Speed"],
        ].copy()
        work["Speed"] = pd.to_numeric(work["Speed"], errors="coerce")
        work["Distance"] = pd.to_numeric(work["Distance"], errors="coerce")
        work = work.loc[
            work["Speed"].notna()
            & work["Distance"].notna()
            & (work["Speed"] > 0)
        ].copy()
        if work.empty:
            return pd.DataFrame()
        work["Distance"] = work["Distance"].astype(int)
        work = work.loc[work["Distance"].isin(_HEATMAP_STANDARD_DISTANCES)].copy()
        work["Stroke"] = (
            work["Stroke"].astype(str).str.strip().map(stroke_code_to_label)
        )
        work = work.loc[
            work["Stroke"].notna() & (work["Stroke"].astype(str).str.strip() != "")
        ].copy()
        if work.empty:
            return pd.DataFrame()
        work["Name"] = work["SwimmerName"].astype(str).str.strip()
        work["Name_norm"] = work["Name"].map(corridor_norm_name)
        return work[["Name", "Name_norm", "Distance", "Stroke", "Speed"]].copy()

    rows: List[dict[str, object]] = []
    for swimmers_raw, distance_raw, stroke_raw, speed_raw in df[
        ["swimmer", "Distance", "Stroke", "Speed"]
    ].itertuples(index=False, name=None):
        speed = pd.to_numeric(speed_raw, errors="coerce")
        distance = pd.to_numeric(distance_raw, errors="coerce")
        if pd.isna(speed) or pd.isna(distance) or float(speed) <= 0:
            continue
        dist_int = int(float(distance))
        if dist_int not in _HEATMAP_STANDARD_DISTANCES:
            continue

        swimmers: List[dict]
        if isinstance(swimmers_raw, list):
            swimmers = [s for s in swimmers_raw if isinstance(s, dict)]
        elif isinstance(swimmers_raw, dict):
            swimmers = [swimmers_raw]
        else:
            swimmers = []
        if len(swimmers) != 1:
            continue

        name = swimmers[0].get("Name")
        if not isinstance(name, str) or not name.strip():
            continue
        stroke_label = stroke_code_to_label(str(stroke_raw).strip())
        if not stroke_label:
            continue

        rows.append(
            {
                "Name": name.strip(),
                "Name_norm": corridor_norm_name(name),
                "Distance": dist_int,
                "Stroke": stroke_label,
                "Speed": float(speed),
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)

def _speed_heatmap_pivot_tables(
    long_df: pd.DataFrame,
    *,
    mask: pd.Series,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Construit les pivots médiane et effectif pour une heatmap vitesse.

    Args:
        long_df (pd.DataFrame): Données longues préparées par
            ``_prepare_speed_heatmap_long_df``.
        mask (pd.Series): Masque booléen sur ``long_df`` (groupe cible ou peloton).

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: Pivot vitesse médiane et pivot effectifs
            (distance × nage), réindexés sur la grille standard.
    """
    subset = long_df.loc[mask].copy()
    if subset.empty:
        empty_index = list(_HEATMAP_STANDARD_DISTANCES)
        return (
            pd.DataFrame(index=empty_index),
            pd.DataFrame(index=empty_index),
        )

    speed_pivot = subset.pivot_table(
        values="Speed",
        index="Distance",
        columns="Stroke",
        aggfunc="median",
    )
    count_pivot = subset.pivot_table(
        values="Speed",
        index="Distance",
        columns="Stroke",
        aggfunc="count",
    )
    stroke_cols = _ordered_stroke_labels(
        list(set(speed_pivot.columns.tolist()) | set(count_pivot.columns.tolist()))
    )
    speed_pivot = speed_pivot.reindex(
        index=list(_HEATMAP_STANDARD_DISTANCES),
        columns=stroke_cols,
    )
    count_pivot = count_pivot.reindex(
        index=list(_HEATMAP_STANDARD_DISTANCES),
        columns=stroke_cols,
    )
    return speed_pivot, count_pivot

def _canonical_heatmap_stroke_columns(
    pivot_target: pd.DataFrame,
    pivot_others: pd.DataFrame,
) -> List[str]:
    """Retourne l'ordre canonique des colonnes nage pour les trois panneaux.

    Args:
        pivot_target (pd.DataFrame): Pivot nageur cible.
        pivot_others (pd.DataFrame): Pivot peloton.

    Returns:
        List[str]: Libellés de nage triés (FR, dos, brasse…).
    """
    labels = list(pivot_target.columns) + list(pivot_others.columns)
    return _ordered_stroke_labels(labels)

def _reindex_heatmap_grid(
    pivot: pd.DataFrame,
    counts: pd.DataFrame,
    *,
    stroke_cols: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Réindexe un pivot sur la grille distance × nage standard.

    Args:
        pivot (pd.DataFrame): Table pivot vitesse.
        counts (pd.DataFrame): Table pivot effectifs.
        stroke_cols (List[str]): Ordre fixe des colonnes nage.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: Pivot vitesse et effectifs alignés.
    """
    distances = list(_HEATMAP_STANDARD_DISTANCES)
    speed_out = pivot.reindex(index=distances, columns=stroke_cols)
    count_out = counts.reindex(index=distances, columns=stroke_cols).fillna(0)
    return speed_out, count_out

def _filter_stroke_swim_time_outliers(
    df: pd.DataFrame,
    stroke_col: str,
    swim_col: str,
) -> pd.DataFrame:
    """Exclut les temps extrêmes par nage selon la règle IQR.

    Réduit l'impact des valeurs aberrantes ou d'épreuves très longues mélangées
    avant l'agrégation annuelle (Tufte : honnêteté et lisibilité des tendances).

    Args:
        df (pd.DataFrame): Performances avec nage et temps en secondes.
        stroke_col (str): Colonne du type de nage.
        swim_col (str): Colonne des temps en secondes.

    Returns:
        pd.DataFrame: Sous-ensemble filtré, ou copie d'origine si filtre vide.
    """
    if df.empty:
        return df.copy()
    filtered_parts: List[pd.DataFrame] = []
    for _, group in df.groupby(stroke_col):
        values = pd.to_numeric(group[swim_col], errors="coerce").dropna()
        if values.empty:
            continue
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = float(q3 - q1)
        if iqr <= 0:
            filtered_parts.append(group.copy())
            continue
        low = max(0.0, float(q1 - 1.5 * iqr))
        high = float(q3 + 1.5 * iqr)
        mask = (pd.to_numeric(group[swim_col], errors="coerce") >= low) & (
            pd.to_numeric(group[swim_col], errors="coerce") <= high
        )
        kept = group.loc[mask].copy()
        filtered_parts.append(kept if not kept.empty else group.copy())
    if not filtered_parts:
        return df.copy()
    return pd.concat(filtered_parts, ignore_index=True)

def _compute_yearly_stroke_median_times(
    df: pd.DataFrame,
    stroke_col: str,
    swim_col: str,
    year_col: str,
) -> pd.DataFrame:
    """Calcule la médiane annuelle des temps par type de nage.

    Args:
        df (pd.DataFrame): Performances échantillonnées avec année et nage.
        stroke_col (str): Colonne du type de nage (libellés français).
        swim_col (str): Colonne des temps en secondes.
        year_col (str): Colonne de l'année civile.

    Returns:
        pd.DataFrame: Colonnes ``year``, ``stroke_col``, ``median_seconds``, ``n``.
    """
    if df.empty:
        return pd.DataFrame(columns=[year_col, stroke_col, "median_seconds", "n"])

    cleaned = _filter_stroke_swim_time_outliers(df, stroke_col, swim_col)
    yearly_parts: List[pd.DataFrame] = []
    for stroke_label, group in cleaned.groupby(stroke_col):
        yearly = (
            group.groupby(year_col, as_index=False)
            .agg(
                median_seconds=(swim_col, "median"),
                n=(swim_col, "size"),
            )
            .sort_values(year_col)
        )
        if yearly.empty:
            continue
        yearly[stroke_col] = stroke_label
        yearly_parts.append(yearly)

    if not yearly_parts:
        return pd.DataFrame(columns=[year_col, stroke_col, "median_seconds", "n"])
    return pd.concat(yearly_parts, ignore_index=True)

_CHRONOS_YEARLY_MIN_PERFORMANCES = 5

_CHRONOS_ROLLING_WINDOW_YEARS = 3

_SPEED_DISTANCE_MIN_AGE_YEARS = 17

_SPEED_DISTANCE_MIN_GROUP_N = 25

_SPEED_DISTANCE_MAX_MPS = 2.8

_SPEED_DISTANCE_MIN_MPS = 0.45

def _resolve_speed_distance_min_group_n(raw_count: int) -> int:
    """Adapte l'effectif minimal par point à la taille du périmètre.

    Args:
        raw_count (int): Nombre de performances dans le périmètre filtré.

    Returns:
        int: Seuil minimal par couple distance × nage.
    """
    if raw_count >= 200:
        return _SPEED_DISTANCE_MIN_GROUP_N
    if raw_count >= 80:
        return 12
    if raw_count >= 30:
        return 6
    return max(2, raw_count // 4)

def _swimmer_field_from_cell(swimmer: object, field: str) -> Optional[Any]:
    """Extrait un champ d'un nageur depuis une cellule ``swimmer`` hétérogène.

    Args:
        swimmer (object): Dict, liste de dicts ou valeur brute.
        field (str): Nom du champ (ex. ``Gender``, ``Year_of_birth``).

    Returns:
        Optional[Any]: Valeur du champ ou None si introuvable.
    """
    if isinstance(swimmer, dict):
        return swimmer.get(field)
    if isinstance(swimmer, list) and swimmer and isinstance(swimmer[0], dict):
        return swimmer[0].get(field)
    return None

def _prepare_speed_distance_stroke_stats(
    df: pd.DataFrame,
    *,
    distance_col: str = "Distance",
    stroke_col: str = "Stroke",
    swim_col: str = "SwimTimeSeconds",
    gender_filter: Optional[str] = None,
    min_age_years: int = _SPEED_DISTANCE_MIN_AGE_YEARS,
    min_group_n: int = _SPEED_DISTANCE_MIN_GROUP_N,
) -> pd.DataFrame:
    """Prépare les vitesses médianes par distance et nage avec nettoyage méthodologique.

    Filtre les performances valides (statut OK, âge minimal, cohérence épreuve /
    distance), recalcule la vitesse (distance / temps), puis agrège la médiane
    après exclusion IQR par couple distance × nage.

    Args:
        df (pd.DataFrame): Performances brutes.
        distance_col (str): Colonne distance en mètres.
        stroke_col (str): Colonne type de nage.
        swim_col (str): Colonne temps en secondes.
        gender_filter (Optional[str]): ``F``, ``M`` ou None pour tous.
        min_age_years (int): Âge minimal à la date de performance.
        min_group_n (int): Effectif minimal par couple distance × nage.

    Returns:
        pd.DataFrame: Colonnes distance, nage, ``median_speed``, ``n``.
    """
    if df.empty:
        return pd.DataFrame(
            columns=[distance_col, stroke_col, "median_speed", "n"]
        )

    effective_min_group_n = _resolve_speed_distance_min_group_n(len(df))
    if min_group_n != _SPEED_DISTANCE_MIN_GROUP_N:
        effective_min_group_n = max(2, int(min_group_n))

    local_df = df.copy()
    local_df[distance_col] = pd.to_numeric(local_df.get(distance_col), errors="coerce")
    local_df[swim_col] = pd.to_numeric(local_df.get(swim_col), errors="coerce")
    local_df = local_df.dropna(subset=[distance_col, swim_col, stroke_col])
    local_df = local_df.loc[
        (local_df[distance_col] > 0)
        & (local_df[swim_col] > 0)
    ].copy()

    if "Status" in local_df.columns:
        local_df = local_df.loc[
            local_df["Status"].astype(str).str.upper().eq("OK")
        ].copy()

    if "Event" in local_df.columns:
        event_distances = local_df["Event"].astype(str).map(parse_event_distance_m)
        known_event_distance = event_distances.notna()
        local_df = local_df.loc[
            ~known_event_distance
            | (event_distances == local_df[distance_col])
        ].copy()

    local_df["SwimDate"] = pd.to_datetime(local_df.get("SwimDate"), errors="coerce")
    local_df["swim_year"] = local_df["SwimDate"].dt.year
    local_df["year_of_birth"] = local_df.get("swimmer", pd.Series(dtype=object)).map(
        lambda cell: _swimmer_field_from_cell(cell, "Year_of_birth")
    )
    local_df["year_of_birth"] = pd.to_numeric(local_df["year_of_birth"], errors="coerce")
    local_df["age_at_swim"] = local_df["swim_year"] - local_df["year_of_birth"]
    aged_df = local_df.loc[local_df["age_at_swim"] >= min_age_years].copy()
    if len(aged_df) >= max(effective_min_group_n * 2, 8):
        local_df = aged_df

    if gender_filter in ("F", "M"):
        local_df["Gender"] = local_df.get("swimmer", pd.Series(dtype=object)).map(
            lambda cell: _swimmer_field_from_cell(cell, "Gender")
        )
        local_df["Gender"] = local_df["Gender"].astype(str).str.upper().str[:1]
        local_df = local_df.loc[local_df["Gender"] == gender_filter].copy()

    local_df["speed_calc"] = local_df[distance_col] / local_df[swim_col]
    local_df = local_df.loc[
        (local_df["speed_calc"] >= _SPEED_DISTANCE_MIN_MPS)
        & (local_df["speed_calc"] <= _SPEED_DISTANCE_MAX_MPS)
    ].copy()
    local_df = relabel_stroke_column(local_df, stroke_col)

    if local_df.empty:
        return pd.DataFrame(
            columns=[distance_col, stroke_col, "median_speed", "n"]
        )

    aggregated_rows: List[Dict[str, Any]] = []
    for (distance_value, stroke_label), group in local_df.groupby(
        [distance_col, stroke_col]
    ):
        speeds = pd.to_numeric(group["speed_calc"], errors="coerce").dropna()
        if len(speeds) < effective_min_group_n:
            continue
        q1, q3 = speeds.quantile([0.25, 0.75])
        iqr = float(q3 - q1)
        if iqr > 0 and len(speeds) >= 6:
            low = float(q1 - 1.5 * iqr)
            high = float(q3 + 1.5 * iqr)
            speeds = speeds[(speeds >= low) & (speeds <= high)]
        if len(speeds) < max(2, effective_min_group_n // 2):
            continue
        aggregated_rows.append(
            {
                distance_col: float(distance_value),
                stroke_col: str(stroke_label),
                "median_speed": float(speeds.median()),
                "n": int(len(speeds)),
            }
        )

    if not aggregated_rows:
        return pd.DataFrame(
            columns=[distance_col, stroke_col, "median_speed", "n"]
        )
    return pd.DataFrame(aggregated_rows).sort_values([stroke_col, distance_col])

def _smooth_centered_rolling(values: List[float], window: int) -> List[float]:
    """Applique une moyenne mobile centrée pour lisser une série annuelle.

    Args:
        values (List[float]): Valeurs ordonnées chronologiquement.
        window (int): Largeur de la fenêtre (années).

    Returns:
        List[float]: Série lissée de même longueur.
    """
    if not values:
        return []
    if window <= 1 or len(values) < 2:
        return [float(value) for value in values]
    series = pd.Series([float(value) for value in values])
    smoothed = series.rolling(window=window, center=True, min_periods=1).mean()
    return [float(value) for value in smoothed.tolist()]

def _filter_yearly_stats_by_min_count(
    yearly_stats: pd.DataFrame,
    *,
    year_col: str,
    min_performances: int,
) -> pd.DataFrame:
    """Exclut les années avec trop peu de performances (biais de composition).

    Args:
        yearly_stats (pd.DataFrame): Agrégats annuels avec colonne ``n``.
        year_col (str): Colonne de l'année (conservée pour cohérence d'API).
        min_performances (int): Seuil minimal d'effectif annuel.

    Returns:
        pd.DataFrame: Sous-ensemble des années suffisamment représentées.
    """
    if yearly_stats.empty or "n" not in yearly_stats.columns:
        return yearly_stats.copy()
    if min_performances <= 1:
        return yearly_stats.copy()
    return yearly_stats.loc[yearly_stats["n"] >= min_performances].copy()

_SPLIT_SPEED_MIN_MPS = 0.45

_SPLIT_SPEED_MAX_MPS = 3.0

def _parse_split_distance_m(value: object) -> Optional[int]:
    """Convertit une distance de split en mètres entiers.

    Args:
        value (object): Valeur brute (ex. ``100``, ``\"100 m\"``).

    Returns:
        Optional[int]: Distance en mètres ou None si invalide.
    """
    if value is None:
        return None
    try:
        text = str(value).strip().lower().replace("m", "").strip()
        distance = int(float(text))
    except (TypeError, ValueError):
        return None
    if distance <= 0:
        return None
    return distance

def _parse_split_speed_mps(value: object) -> Optional[float]:
    """Convertit une vitesse de split en m/s.

    Args:
        value (object): Valeur brute numérique ou chaîne.

    Returns:
        Optional[float]: Vitesse en m/s ou None si invalide.
    """
    if value is None:
        return None
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(speed) or speed <= 0:
        return None
    return speed

def _extract_all_split_speed_rows(
    df: pd.DataFrame,
    *,
    stroke_col: str = "Stroke",
    min_speed_mps: float = _SPLIT_SPEED_MIN_MPS,
    max_speed_mps: float = _SPLIT_SPEED_MAX_MPS,
) -> pd.DataFrame:
    """Extrait toutes les vitesses de splits exploitables du périmètre.

    Parcourt les performances solo avec splits, filtre les vitesses plausibles
    et relabel les nages en français.

    Args:
        df (pd.DataFrame): Performances source (colonnes ``splits``, ``swimmer``…).
        stroke_col (str): Colonne du type de nage.
        min_speed_mps (float): Vitesse minimale conservée (m/s).
        max_speed_mps (float): Vitesse maximale conservée (m/s).

    Returns:
        pd.DataFrame: Colonnes ``Stroke``, ``SplitDistance``, ``SplitSpeed``,
            ``Swimmer`` ; vide si aucun split valide.
    """
    if df.empty or "splits" not in df.columns:
        return pd.DataFrame(
            columns=[stroke_col, "SplitDistance", "SplitSpeed", "Swimmer"]
        )

    local_df = df.copy()
    if "Status" in local_df.columns:
        local_df = local_df.loc[
            local_df["Status"].astype(str).str.upper().eq("OK")
        ].copy()

    split_rows: List[Dict[str, object]] = []
    has_splits = local_df["splits"].apply(
        lambda cell: isinstance(cell, list) and len(cell) > 0
    )
    for _, row in local_df.loc[has_splits].iterrows():
        swimmer_name = _swimmer_field_from_cell(row.get("swimmer"), "Name")
        if not swimmer_name:
            continue
        stroke = row.get(stroke_col)
        if stroke is None or (isinstance(stroke, float) and np.isnan(stroke)):
            continue
        for split in row["splits"]:
            if not isinstance(split, dict):
                continue
            distance = _parse_split_distance_m(split.get("split_distance"))
            speed = _parse_split_speed_mps(split.get("split_speed"))
            if distance is None or speed is None:
                continue
            if speed < min_speed_mps or speed > max_speed_mps:
                continue
            split_rows.append(
                {
                    stroke_col: str(stroke),
                    "SplitDistance": distance,
                    "SplitSpeed": speed,
                    "Swimmer": str(swimmer_name),
                }
            )

    if not split_rows:
        return pd.DataFrame(
            columns=[stroke_col, "SplitDistance", "SplitSpeed", "Swimmer"]
        )
    result = pd.DataFrame(split_rows)
    return relabel_stroke_column(result, stroke_col)

def _prepare_max_split_speed_by_stroke(
    df_splits: pd.DataFrame,
    *,
    stroke_col: str = "Stroke",
    distance_col: str = "SplitDistance",
    speed_col: str = "SplitSpeed",
) -> pd.DataFrame:
    """Retient la vitesse maximale observée par couple nage × distance de split.

    Args:
        df_splits (pd.DataFrame): Splits extraits (une ligne par passage).
        stroke_col (str): Colonne du type de nage.
        distance_col (str): Colonne distance cumulée du split (m).
        speed_col (str): Colonne vitesse du segment (m/s).

    Returns:
        pd.DataFrame: Un enregistrement par couple nage × distance (record de
            vitesse) avec colonnes ``Swimmer`` et ``n`` (effectif source).
    """
    required = (stroke_col, distance_col, speed_col)
    if df_splits.empty or any(col not in df_splits.columns for col in required):
        return pd.DataFrame(
            columns=[stroke_col, distance_col, speed_col, "Swimmer", "n"]
        )

    grouped_keys = [stroke_col, distance_col]
    counts = (
        df_splits.groupby(grouped_keys)[speed_col]
        .size()
        .reset_index(name="n")
    )
    idx = df_splits.groupby(grouped_keys)[speed_col].idxmax()
    peaks = df_splits.loc[idx, [stroke_col, distance_col, speed_col, "Swimmer"]].copy()
    peaks = peaks.merge(counts, on=grouped_keys, how="left")
    return peaks.sort_values(grouped_keys).reset_index(drop=True)

def _event_display_sort_key(event: str) -> Tuple[int, int, str]:
    """Construit une clé de tri natation (nage, distance, libellé).

    Args:
        event (str): Libellé d'épreuve (ex. ``100 FR SCM``).

    Returns:
        Tuple[int, int, str]: Tri par nage, distance croissante puis libellé brut.
    """
    text = str(event).strip()
    parts = text.split()
    stroke = parts[1].upper() if len(parts) > 1 else ""
    stroke_rank = _STROKE_SORT_ORDER.get(stroke, 99)
    distance = parse_event_distance_m(text) or 9999
    return (stroke_rank, distance, text)

def _drop_zero_count_events(df_counts: pd.DataFrame) -> pd.DataFrame:
    """Exclut les épreuves sans aucune performance enregistrée.

    Args:
        df_counts (pd.DataFrame): Effectifs par épreuve et genre.

    Returns:
        pd.DataFrame: Sous-ensemble sans lignes à effectif total nul.
    """
    if df_counts.empty:
        return df_counts
    totals = df_counts.sum(axis=1)
    return df_counts.loc[totals > 0].copy()

def _sort_event_counts_df(
    df_counts: pd.DataFrame,
    *,
    by_total: bool = False,
) -> pd.DataFrame:
    """Trie les effectifs F/M par épreuve selon l'ordre natation ou l'effectif.

    Args:
        df_counts (pd.DataFrame): Colonnes de genre indexées par épreuve.
        by_total (bool): Si True, tri décroissant par effectif total.

    Returns:
        pd.DataFrame: Copie triée des effectifs par épreuve.
    """
    out = df_counts.copy()
    if out.empty:
        return out
    if by_total:
        totals = out.sum(axis=1)
        return out.loc[totals.sort_values(ascending=False).index]
    order = sorted(out.index, key=lambda event: _event_display_sort_key(str(event)))
    return out.loc[order]

def _gender_label_for_code(code: str) -> str:
    """Convertit un code genre interne en libellé français d'affichage.

    Args:
        code (str): Code genre (``F`` ou ``M``).

    Returns:
        str: Libellé français ou la valeur d'origine si inconnue.
    """
    if code == "F":
        return _GENDER_LABEL_FEMALE
    if code == "M":
        return _GENDER_LABEL_MALE
    return str(code)

def _adaptive_histogram_bin_count(
    n_perf: int,
    data_min: float,
    data_max: float,
    iqr: float,
) -> int:
    """Calcule un nombre de classes d'histogramme adapté à l'échantillon.

    Petits échantillons : peu de bacs pour éviter un rendu en bâtons isolés.
    Grands échantillons : règle de Freedman-Diaconis, plafonnée pour la lisibilité.

    Args:
        n_perf (int): Nombre de performances valides.
        data_min (float): Temps minimum observé (secondes).
        data_max (float): Temps maximum observé (secondes).
        iqr (float): Écart interquartile (Q3 - Q1).

    Returns:
        int: Nombre de classes à utiliser pour l'histogramme.
    """
    if n_perf <= 40:
        return max(6, min(10, int(np.ceil(np.sqrt(n_perf))) + 2))
    if n_perf > 1 and iqr > 0:
        bin_width = 2.0 * iqr / np.cbrt(n_perf)
        if bin_width > 0:
            nbins = int(np.ceil((data_max - data_min) / bin_width))
        else:
            nbins = 16
        return max(10, min(40, nbins))
    return max(8, min(24, int(np.sqrt(n_perf)) + 2))

def _corridor_swimmer_specs_from_kwargs(
    kwargs: Dict[str, Any],
) -> List[CorridorSwimmerSpec]:
    """Extrait ou construit la liste de specs nageur depuis les kwargs du couloir.
    
    Args:
        kwargs (Dict[str, Any]): Arguments de tracé (swimmer_specs ou overlay_nageur).
    
    Returns:
        List[CorridorSwimmerSpec]: Spécifications prêtes pour le tracé matplotlib.
    """
    raw = kwargs.get("swimmer_specs")
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, CorridorSwimmerSpec)]
    specs: List[CorridorSwimmerSpec] = []
    overlay_name = kwargs.get("overlay_nageur")
    if isinstance(overlay_name, str) and overlay_name.strip():
        overlay_yob = kwargs.get("overlay_year_of_birth")
        yob_int: Optional[int] = None
        if overlay_yob is not None:
            try:
                yob_int = int(overlay_yob)
            except (TypeError, ValueError):
                yob_int = None
        specs.append(
            CorridorSwimmerSpec(
                name=overlay_name.strip(),
                year_of_birth=yob_int,
                color=CORRIDOR_MA_SWIMMER_COLOR,
                label=CORRIDOR_OVERLAY_SWIMMER_LABEL,
            )
        )
    return specs
