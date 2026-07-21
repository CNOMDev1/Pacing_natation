"""Résolution des filtres de scope pour les graphiques Pacing.

Logique métier pure (sans Flet) partagée par la façade application et les helpers UI.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from services.graph_catalog import (
    SCOPE_GENDER_FILTER_GRAPHS,
    SCOPE_NO_FILTER_GRAPHS,
    SCOPE_NO_STROKE_GRAPHS,
    SCOPE_POOL_ONLY_GRAPHS,
    SCOPE_POOL_STROKE_GRAPHS,
    SCOPE_STROKE_ONLY_GRAPHS,
)


def event_combinations(
    df_nav: pd.DataFrame,
) -> Dict[str, Dict[int, List[str]]]:
    """
    Construit les combinaisons valides Stroke -> Distance -> [Course].

    Args:
        df_nav (pd.DataFrame): DataFrame de navigation.

    Returns:
        Dict[str, Dict[int, List[str]]]: Combinaisons stroke/distance/bassins.
    """
    combos: Dict[str, Dict[int, set[str]]] = {}
    if df_nav.empty:
        return {}

    cols = ["Stroke", "Distance", "Course"]
    if not all(c in df_nav.columns for c in cols):
        return {}

    df_tmp = df_nav[cols].dropna(subset=cols)
    if df_tmp.empty:
        return {}

    d_num = pd.to_numeric(df_tmp["Distance"], errors="coerce")
    df_tmp = df_tmp.assign(Distance=d_num)
    df_tmp = df_tmp[df_tmp["Distance"].notna()]
    if df_tmp.empty:
        return {}

    uniq = df_tmp.drop_duplicates(subset=cols)
    strokes = uniq["Stroke"].astype(str).str.strip()
    pools = uniq["Course"].astype(str).str.strip()
    dists = uniq["Distance"]
    for stroke, distance, pool in zip(strokes, dists, pools):
        if not stroke or not pool:
            continue
        try:
            dist_i = int(distance)
        except (TypeError, ValueError):
            continue
        combos.setdefault(stroke, {}).setdefault(dist_i, set()).add(pool)

    ordered: Dict[str, Dict[int, List[str]]] = {}
    pool_rank = {"SCM": 0, "LCM": 1}
    for stroke in sorted(combos.keys()):
        ordered[stroke] = {}
        for distance in sorted(combos[stroke].keys()):
            pools_sorted = sorted(
                combos[stroke][distance],
                key=lambda p: (pool_rank.get(p), p),
            )
            ordered[stroke][distance] = pools_sorted
    return ordered


def resolve_scope_filters(
    df_nav: pd.DataFrame,
    selected_graph: str,
    selected_stroke: Optional[str],
    selected_distance: Optional[int],
    selected_pool: Optional[str],
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Résout et valide les filtres stroke / distance / bassin pour un graphique.

    Args:
        df_nav (pd.DataFrame): DataFrame de navigation complet.
        selected_graph (str): Nom du graphique actif.
        selected_stroke (Optional[str]): Nage sélectionnée.
        selected_distance (Optional[int]): Distance sélectionnée.
        selected_pool (Optional[str]): Bassin sélectionné (LCM/SCM).

    Returns:
        Tuple[Optional[str], Optional[int], Optional[str]]: Filtres effectifs.
    """
    if selected_graph in SCOPE_NO_FILTER_GRAPHS:
        return None, None, None

    if selected_graph in SCOPE_POOL_ONLY_GRAPHS:
        pool_options = sorted(df_nav["Course"].dropna().unique().tolist())
        if not pool_options:
            return None, None, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        return None, None, selected_pool

    if selected_graph in SCOPE_POOL_STROKE_GRAPHS:
        stroke_options = sorted(df_nav["Stroke"].dropna().unique().tolist())
        if not stroke_options:
            return None, None, None
        if selected_stroke not in stroke_options:
            selected_stroke = stroke_options[0]
        stroke_mask = df_nav["Stroke"] == selected_stroke
        pool_options = sorted(df_nav.loc[stroke_mask, "Course"].dropna().unique().tolist())
        if not pool_options:
            return selected_stroke, None, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        return selected_stroke, None, selected_pool

    if selected_graph in SCOPE_STROKE_ONLY_GRAPHS:
        stroke_options = sorted(df_nav["Stroke"].dropna().unique().tolist())
        if not stroke_options:
            return None, None, None
        if selected_stroke not in stroke_options:
            selected_stroke = stroke_options[0]
        return selected_stroke, None, None

    if selected_graph in SCOPE_NO_STROKE_GRAPHS:
        distance_options = sorted(df_nav["Distance"].dropna().unique().tolist())
        if not distance_options:
            return None, None, None
        if selected_distance not in distance_options:
            selected_distance = distance_options[0]
        pool_options = sorted(
            df_nav.loc[
                df_nav["Distance"] == selected_distance,
                "Course",
            ]
            .dropna()
            .unique()
            .tolist()
        )
        if not pool_options:
            return None, selected_distance, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        return None, selected_distance, selected_pool

    stroke_options = sorted(df_nav["Stroke"].dropna().unique().tolist())
    if not stroke_options:
        return None, None, None
    if selected_stroke not in stroke_options:
        selected_stroke = stroke_options[0]

    stroke_mask = df_nav["Stroke"] == selected_stroke
    distance_options = sorted(df_nav.loc[stroke_mask, "Distance"].dropna().unique().tolist())
    if not distance_options:
        return selected_stroke, None, None
    if selected_distance not in distance_options:
        selected_distance = distance_options[0]

    dist_mask = stroke_mask & (df_nav["Distance"] == selected_distance)
    pool_options = sorted(df_nav.loc[dist_mask, "Course"].dropna().unique().tolist())
    if not pool_options:
        return selected_stroke, selected_distance, None
    if selected_pool not in pool_options:
        selected_pool = pool_options[0]

    return selected_stroke, selected_distance, selected_pool


def materialize_df_scope(
    df_nav: pd.DataFrame,
    selected_graph: str,
    stroke: Optional[str],
    distance: Optional[int],
    pool: Optional[str],
) -> pd.DataFrame:
    """
    Construit le DataFrame filtré (df_scope) depuis les filtres résolus.

    Args:
        df_nav (pd.DataFrame): DataFrame de navigation.
        selected_graph (str): Nom du graphique.
        stroke (Optional[str]): Filtre nage.
        distance (Optional[int]): Filtre distance.
        pool (Optional[str]): Filtre bassin.

    Returns:
        pd.DataFrame: Sous-ensemble filtré ; vide si filtres incomplets.
    """
    if selected_graph in SCOPE_NO_FILTER_GRAPHS:
        return df_nav.copy()

    if selected_graph in SCOPE_GENDER_FILTER_GRAPHS:
        if pool is None:
            return df_nav.copy()
        pool_key = str(pool).strip()
        return df_nav[df_nav["Course"].astype(str).str.strip() == pool_key].copy()

    if selected_graph in SCOPE_POOL_ONLY_GRAPHS:
        if pool is None:
            return pd.DataFrame()
        return df_nav[df_nav["Course"] == pool].copy()

    if selected_graph in SCOPE_POOL_STROKE_GRAPHS:
        if stroke is None or pool is None:
            return pd.DataFrame()
        stroke_key = str(stroke).strip()
        pool_key = str(pool).strip()
        mask = (
            (df_nav["Stroke"].astype(str).str.strip() == stroke_key)
            & (df_nav["Course"].astype(str).str.strip() == pool_key)
        )
        return df_nav.loc[mask].copy()

    if selected_graph in SCOPE_STROKE_ONLY_GRAPHS:
        if stroke is None:
            return pd.DataFrame()
        stroke_key = str(stroke).strip()
        return df_nav[df_nav["Stroke"].astype(str).str.strip() == stroke_key].copy()

    if selected_graph in SCOPE_NO_STROKE_GRAPHS:
        if distance is None or pool is None:
            return pd.DataFrame()
        df_distance = df_nav[df_nav["Distance"] == distance].copy()
        return df_distance[df_distance["Course"] == pool].copy()

    if stroke is None or distance is None or pool is None:
        return pd.DataFrame()
    dist_num = int(distance)
    stroke_key = str(stroke).strip()
    pool_key = str(pool).strip()
    mask = (
        (df_nav["Stroke"].astype(str).str.strip() == stroke_key)
        & (pd.to_numeric(df_nav["Distance"], errors="coerce") == dist_num)
        & (df_nav["Course"].astype(str).str.strip() == pool_key)
    )
    scoped = df_nav.loc[mask].copy()
    if "Event" in scoped.columns:
        nom_event = f"{dist_num} {stroke_key} {pool_key}"
        scoped = scoped[scoped["Event"].astype(str).str.strip() == nom_event].copy()
    return scoped
