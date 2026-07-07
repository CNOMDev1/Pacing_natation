"""Utilitaires partagés par l'interface desktop Flet (données, filtres, graphiques).

Ce module centralise le chargement du DataFrame Extranat, la résolution des
filtres par type de graphique (stroke / distance / bassin) et la conversion
matplotlib → PNG base64 pour l'affichage dans Flet.

Le flux côté UI :
1. **Chargement** — ``load_data()`` lit les JSON traités via
   ``ExtranatCompetitionsDataLoader`` (cache LRU).
2. **Navigation** — ``_event_combinations()`` et ``_resolve_scope_filters()``
   construisent les combinaisons valides selon ``SCOPE_*`` de ``graph_service``.
3. **Scope** — ``_materialize_df_scope()`` produit le DataFrame filtré pour
   un graphique donné.
4. **Rendu** — ``_figure_to_base64()`` sérialise les figures pour le cache
   ``prefetched_graphs.json``.
"""
import base64
import io
import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd

from project_path import PROJECT_DIR
from services.extranat_competitions_data_loader import ExtranatCompetitionsDataLoader
from services.graph_service import (
    SCOPE_GENDER_FILTER_GRAPHS,
    SCOPE_NO_FILTER_GRAPHS,
    SCOPE_NO_STROKE_GRAPHS,
    SCOPE_POOL_ONLY_GRAPHS,
    SCOPE_POOL_STROKE_GRAPHS,
    SCOPE_STROKE_ONLY_GRAPHS,
)

# --- Chemins et constantes d'affichage ---

EXTRANAT_OUTPUT_BASE_DIR = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "extranat"
    / "competitions_per_type"
)
CHART_PNG_DPI = 96
CORRIDOR_CHART_PNG_DPI = 72

CORRIDOR_PREFERRED_STROKES: Tuple[str, ...] = ("FR", "BK", "BR", "FL", "IM", "MD")
CORRIDOR_PREFERRED_DISTANCES: Tuple[int, ...] = (100, 200, 50, 400, 1500, 25)


def _pick_preferred_corridor_stroke(stroke_vals: List[str]) -> Optional[str]:
    """Choisit une nage par défaut lisible pour les couloirs de performance.

    Args:
        stroke_vals (List[str]): Codes nage disponibles pour l'épreuve filtrée.

    Returns:
        Optional[str]: Code nage préféré ou premier disponible.
    """
    if not stroke_vals:
        return None
    stroke_set = {str(s) for s in stroke_vals}
    for code in CORRIDOR_PREFERRED_STROKES:
        if code in stroke_set:
            return code
    return str(stroke_vals[0])


def _pick_preferred_corridor_distance(dist_vals: List[int]) -> Optional[int]:
    """Choisit une distance par défaut adaptée aux couloirs (évite le 25 m isolé).

    Args:
        dist_vals (List[int]): Distances disponibles pour la nage et le bassin.

    Returns:
        Optional[int]: Distance préférée ou première disponible.
    """
    if not dist_vals:
        return None
    dist_set = {int(d) for d in dist_vals}
    for distance in CORRIDOR_PREFERRED_DISTANCES:
        if distance in dist_set:
            return distance
    return int(sorted(dist_set)[0])


# --- Extraction nageur depuis la colonne swimmer ---


def _primary_swimmer_name(swimmers: Any) -> Optional[str]:
    """Retourne le nom du premier nageur si ``swimmer`` est une liste non vide.

    Args:
        swimmers (Any): Valeur de la colonne ``swimmer``.

    Returns:
        Optional[str]: Nom du nageur ou None.
    """
    if not isinstance(swimmers, list) or len(swimmers) == 0:
        return None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None
    return first.get("Name")


def _primary_swimmer_name_and_yob(
    swimmers: Any,
) -> Tuple[Optional[str], Optional[int]]:
    """Retourne nom et année de naissance du nageur solo (liste à un seul élément).

    Args:
        swimmers (Any): Valeur de la colonne ``swimmer``.

    Returns:
        Tuple[Optional[str], Optional[int]]: Nom et YOB, ou (None, None) si relais.
    """
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None, None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None, None
    name = first.get("Name")
    yob = first.get("Year_of_birth")
    yob_int: Optional[int] = None
    try:
        if yob is not None and yob == yob:
            yob_int = int(yob)
    except (TypeError, ValueError):
        yob_int = None
    return name, yob_int


def _normalize_text(value: Any) -> str:
    """Normalise un texte pour comparaison (minuscules, sans accents).

    Args:
        value (Any): Chaîne ou valeur pandas.

    Returns:
        str: Texte normalisé ASCII.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _slugify(text: str) -> str:
    """Convertit un libellé en identifiant URL/fichier (kebab-case).

    Args:
        text (str): Texte source.

    Returns:
        str: Slug sans caractères spéciaux.
    """
    value = _normalize_text(text)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


@lru_cache(maxsize=1)
def load_data() -> pd.DataFrame:
    """Charge le DataFrame Extranat traité (mis en cache après le premier appel).

    Returns:
        pd.DataFrame: Performances aplaties depuis ``competitions_per_type``.
    """
    return ExtranatCompetitionsDataLoader(EXTRANAT_OUTPUT_BASE_DIR).load()


def _figure_to_base64(fig: plt.Figure, *, dpi: Optional[int] = None) -> str:
    """Convertit une figure matplotlib en data-URI PNG base64.

    Args:
        fig (plt.Figure): Figure à exporter.
        dpi (Optional[int]): Résolution ; défaut ``CHART_PNG_DPI``.

    Returns:
        str: URI ``data:image/png;base64,…``.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=int(dpi or CHART_PNG_DPI))
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _event_combinations(
    df_nav: pd.DataFrame,
) -> Dict[str, Dict[int, List[str]]]:
    """Construit les combinaisons valides Stroke -> Distance -> [Course]."""
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
            pools = sorted(
                combos[stroke][distance],
                key=lambda p: (pool_rank.get(p), p),
            )
            ordered[stroke][distance] = pools
    return ordered


def _resolve_scope_filters(
    df_nav: pd.DataFrame,
    selected_graph: str,
    selected_stroke: Optional[str],
    selected_distance: Optional[int],
    selected_pool: Optional[str],
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Résout et valide les filtres stroke / distance / bassin pour un graphique.

    Adapte les valeurs sélectionnées selon le scope du graphique
    (``SCOPE_NO_FILTER_GRAPHS``, ``SCOPE_POOL_ONLY_GRAPHS``, etc.).

    Args:
        df_nav (pd.DataFrame): DataFrame de navigation complet.
        selected_graph (str): Nom du graphique actif.
        selected_stroke (Optional[str]): Nage sélectionnée.
        selected_distance (Optional[int]): Distance sélectionnée.
        selected_pool (Optional[str]): Bassin sélectionné (LCM/SCM).

    Returns:
        Tuple[Optional[str], Optional[int], Optional[str]]: Filtres effectifs
            (stroke, distance, pool) ou None si non applicable.
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


def _materialize_df_scope(
    df_nav: pd.DataFrame,
    selected_graph: str,
    stroke: Optional[str],
    distance: Optional[int],
    pool: Optional[str],
) -> pd.DataFrame:
    """Construit le DataFrame filtré (df_scope) depuis les filtres résolus.

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
