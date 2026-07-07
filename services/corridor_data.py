"""Préparation vectorisée des données pour les graphiques couloir de performance.

Ce module transforme les DataFrames de performances (Extranat, USA Swimming,
FRM Natation) en données « longues » prêtes pour le tracé couloir âge × temps,
calcule les percentiles de référence et résout les nageurs cibles à afficher.

Le flux de données :
1. **Préparation** — ``prepare_corridor_long_df()`` filtre l'épreuve, extrait
   le premier nageur (solo), calcule ``Age_swim`` et met en cache le résultat (LRU).
2. **Couloir de référence** — ``compute_corridor_percentiles_df()`` agrège les
   percentiles par âge via ``groupby.quantile``.
3. **Résolution nageur** — ``resolve_corridor_swimmer*()`` retrouve le nageur
   cible (exact, tokens, fuzzy) dans le peloton.
4. **Tracé** — ``plot_corridor_swimmer_specs()`` et ``build_corridor_chart_plot_kwargs()``
   préparent les courbes nageur FR / overlay MAR pour ``graph_service``.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# --- Palette couloirs (grammaire visuelle) ---
#
# Principes (Munzner 2014 ; Cleveland & McGill 1984) :
# - Teinte (hue) réservée aux nageurs cibles (attribut catégoriel).
# - Peloton de référence : carte divergente autour de la médiane (P50) —
#   bleu sous la médiane, ambre au-dessus ; luminance pour la dégradation
#   interne (P10→P50 / P50→P90 et P25→P50 / P50→P75).
# - Éviter rouge–vert divergent (daltonisme) : bleu–ambre + contraste de luminance.

# Catégoriel : nageurs cibles (teintes distinctes du couloir bleu/ambre)
CORRIDOR_FR_SWIMMER_COLOR = "#dc2626"  # rouge France / cible principale
CORRIDOR_MA_SWIMMER_COLOR = "#059669"  # vert émeraude Maroc (overlay)

# Divergent — sous la médiane (P10–P50, P25–P50) : rampe bleue claire → saturée
CORRIDOR_BELOW_MEDIAN_OUTER_COLOR = "#bfdbfe"
CORRIDOR_BELOW_MEDIAN_INNER_COLOR = "#3b82f6"
CORRIDOR_BELOW_MEDIAN_EDGE_COLOR = "#1d4ed8"

# Divergent — au-dessus de la médiane (P50–P90, P50–P75) : rampe ambre claire → saturée
CORRIDOR_ABOVE_MEDIAN_OUTER_COLOR = "#fde68a"
CORRIDOR_ABOVE_MEDIAN_INNER_COLOR = "#f59e0b"
CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR = "#d97706"

CORRIDOR_BAND_OUTER_ALPHA = 0.40
CORRIDOR_BAND_INNER_ALPHA = 0.55
CORRIDOR_BAND_EDGE_ALPHA = 0.72
# Médiane P50 : point neutre d'une carte divergente (Munzner 2014 §10.3.2 — blanc,
# gris ou noir ; fig. 10.11b : gris achromatique entre deux teintes saturées).
# Ni bleue (sous-médiane) ni ambre (au-dessus), ni teinte catégorielle (nageurs).
CORRIDOR_MEDIAN_COLOR = "#666666"
CORRIDOR_MEDIAN_LINEWIDTH = 3.4
CORRIDOR_REFERENCE_LINE_COLOR = "#64748b"
CORRIDOR_ANNOTATION_COLOR = "#334155"
CORRIDOR_GRID_ALPHA = 0.18
CORRIDOR_CHART_FIGURE_FACECOLOR = "#ffffff"
CORRIDOR_CHART_AXES_FACECOLOR = "#f8fafc"
CORRIDOR_CHART_STYLE_VERSION = 4

# Déciles : 5 bandes bleues (Pmin→P50) + 5 bandes ambre (P50→Pmax), dégradé par luminance
DECILE_BAND_COLORS_BELOW_MEDIAN: Tuple[str, ...] = (
    "#1e3a8a",
    "#2563eb",
    "#3b82f6",
    "#60a5fa",
    "#93c5fd",
)
DECILE_BAND_COLORS_ABOVE_MEDIAN: Tuple[str, ...] = (
    "#fde68a",
    "#fcd34d",
    "#fbbf24",
    "#f59e0b",
    "#d97706",
)
DECILE_BAND_ALPHA = 0.55
DECILE_EDGE_BELOW_COLOR = "#1e40af"
DECILE_EDGE_ABOVE_COLOR = "#b45309"
DECILE_EDGE_ALPHA = 0.65


@dataclass(frozen=True)
class CorridorSwimmerSpec:
    """Nageur à tracer sur un couloir âge (x) / temps en secondes (y).

    Attributes:
        name (str): Nom du nageur tel qu'affiché dans les données source.
        year_of_birth (Optional[int]): Année de naissance pour désambiguïser.
        color (str): Couleur matplotlib de la courbe et des annotations.
        label (str): Libellé de la légende du graphique.
    """

    name: str
    year_of_birth: Optional[int] = None
    color: str = CORRIDOR_FR_SWIMMER_COLOR
    label: str = "Nageur cible"


# --- Cache LRU pour prepare_corridor_long_df ---

# prepare_corridor_long_df est coûteux sur de gros DataFrames Extranat
_PREP_CACHE: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
_PREP_CACHE_MAX = 96  # nombre maximal d'entrées en mémoire


# --- Normalisation des noms ---


def _normalize_gender_code(value: object) -> Optional[str]:
    """Normalise un libellé genre en code interne ``F`` ou ``M``.

    Args:
        value (object): Genre brut (Extranat, USA, libellés français, etc.).

    Returns:
        Optional[str]: ``F``, ``M`` ou None si non reconnu.
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in ("F", "FEMME", "FEMALE", "W"):
        return "F"
    if s in ("M", "H", "HOMME", "MALE", "MAN"):
        return "M"
    return None


def corridor_norm_name(value: object) -> str:
    """Normalise un nom pour la recherche (minuscules, sans accents, espaces unifiés).

    Utilisé par la résolution fuzzy et la déduplication des specs nageur.

    Args:
        value (object): Nom brut (str, None, etc.).

    Returns:
        str: Nom normalisé ASCII, espaces réduits.
    """
    txt = "" if value is None else str(value).strip().lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", txt)


# --- Préparation du DataFrame long (épreuve → lignes exploitables) ---


def _prep_cache_key(
    df: pd.DataFrame,
    nom_event: str,
    *,
    solo_only: bool,
    require_name: bool,
) -> tuple:
    """Construit une clé de cache LRU pour ``prepare_corridor_long_df``.

    Args:
        df (pd.DataFrame): DataFrame source des performances.
        nom_event (str): Libellé de l'épreuve filtrée.
        solo_only (bool): Indique si seules les nages solo sont conservées.
        require_name (bool): Indique si nom et année de naissance sont requis.

    Returns:
        tuple: Clé hashable (événement, flags, taille, somme des chronos).
    """
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
    """Filtre l'épreuve et extrait Name, Gender, Year_of_birth et Age_swim.

    Ne conserve que les performances solo si ``solo_only`` est True (un seul
    nageur dans la liste ``swimmer``). Le résultat est mis en cache LRU.

    Args:
        df (pd.DataFrame): DataFrame source des performances.
        nom_event (str): Libellé exact de l'épreuve à filtrer.
        solo_only (bool): Si True, exclut les relais (plus d'un nageur).
        require_name (bool): Si True, exige nom et année de naissance valides.

    Returns:
        pd.DataFrame: Lignes prêtes pour le couloir ; vide si colonnes manquantes
            ou aucune performance exploitable.
    """
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

    # Le couloir de référence Extranat ne retient que les nages individuelles (pas les relais).
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
    for i, (idx, d) in enumerate(zip(data.index, first_swimmer)):
        row = data.loc[idx]
        if isinstance(d, dict):
            names[i] = d.get("Name") or row.get("Name")
            genders[i] = d.get("Gender") or row.get("Gender")
            yobs[i] = d.get("Year_of_birth") or row.get("Year_of_birth")
            ages[i] = d.get("Age") or row.get("Age")
        else:
            names[i] = row.get("Name")
            genders[i] = row.get("Gender")
            yobs[i] = row.get("Year_of_birth")
            ages[i] = row.get("Age")

    out = data.copy()
    out["Name"] = names
    out["Gender"] = genders
    out["Year_of_birth"] = yobs
    out["Age_json"] = ages

    swim_year = pd.to_datetime(out["SwimDate"], errors="coerce").dt.year
    age_swim = pd.to_numeric(pd.Series(ages, index=out.index), errors="coerce")
    if "Age" in out.columns:
        age_swim = age_swim.fillna(pd.to_numeric(out["Age"], errors="coerce"))
    yob_num = pd.to_numeric(pd.Series(yobs, index=out.index), errors="coerce")
    missing_age = age_swim.isna() & yob_num.notna() & swim_year.notna()
    if missing_age.any():
        # Âge au moment de la nage : année de compétition − année de naissance
        age_swim = age_swim.copy()
        age_swim.loc[missing_age] = swim_year.loc[missing_age] - yob_num.loc[missing_age]
    out["Age_swim"] = pd.to_numeric(age_swim, errors="coerce").astype("Int64")

    valid = out["Gender"].notna() & out["Age_swim"].notna()
    if require_name:
        valid &= out["Name"].notna() & out["Year_of_birth"].notna()
    result = out.loc[valid].copy()

    # Éviction LRU : supprime l'entrée la plus ancienne si le cache déborde
    _PREP_CACHE[cache_key] = result
    _PREP_CACHE.move_to_end(cache_key)
    if len(_PREP_CACHE) > _PREP_CACHE_MAX:
        _PREP_CACHE.popitem(last=False)
    return result


# --- Percentiles du couloir de référence ---

STANDARD_CORRIDOR_PERCENTILES: List[int] = [10, 25, 50, 75, 90]
DECILE_CORRIDOR_PERCENTILES: List[int] = [10, 20, 30, 40, 50, 60, 70, 80, 90]


def compute_corridor_percentiles_df(
    long_df: pd.DataFrame,
    percentiles: list[int],
    *,
    age_min: int,
    age_max: int,
    min_points: int,
) -> Optional[pd.DataFrame]:
    """Calcule les percentiles de temps par âge pour le couloir de référence.

    Utilise ``groupby.quantile`` (vectorisé) plutôt que des boucles par âge.
    Ignore les âges avec moins de ``min_points`` performances.

    Args:
        long_df (pd.DataFrame): Données longues issues de ``prepare_corridor_long_df``.
        percentiles (list[int]): Liste des percentiles demandés (ex. [10, 25, 50, 75, 90]).
        age_min (int): Borne inférieure d'âge (inclusive).
        age_max (int): Borne supérieure d'âge (inclusive).
        min_points (int): Nombre minimal de points par âge pour inclure la tranche.

    Returns:
        Optional[pd.DataFrame]: Colonnes ``p{percentile}`` indexées par ``Age_swim``,
            ou None si données insuffisantes.
    """
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


def compute_corridor_deciles_df(
    long_df: pd.DataFrame,
    *,
    age_min: int,
    age_max: int,
    min_points: int,
) -> Optional[pd.DataFrame]:
    """Calcule les 9 bornes déciles (P10–P90) et min/max par âge pour 10 bandes.

    Chaque bande couvre environ 10 % du peloton :
    D10 (plus rapide) entre min et P10, D9 entre P10 et P20, …, D1 (plus lent)
    entre P90 et max.

    Args:
        long_df (pd.DataFrame): Données longues issues de ``prepare_corridor_long_df``.
        age_min (int): Borne inférieure d'âge (inclusive).
        age_max (int): Borne supérieure d'âge (inclusive).
        min_points (int): Nombre minimal de points par âge.

    Returns:
        Optional[pd.DataFrame]: Colonnes ``pmin``, ``p10``…``p90``, ``pmax`` indexées par
            ``Age_swim``, ou None si données insuffisantes.
    """
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

    wide = compute_corridor_percentiles_df(
        long_df,
        DECILE_CORRIDOR_PERCENTILES,
        age_min=age_min,
        age_max=age_max,
        min_points=min_points,
    )
    if wide is None or wide.empty:
        return None

    mins = sub.groupby("Age_swim", sort=True)["SwimTimeSeconds"].min()
    maxs = sub.groupby("Age_swim", sort=True)["SwimTimeSeconds"].max()
    wide = wide.copy()
    wide["pmin"] = mins.reindex(wide.index)
    wide["pmax"] = maxs.reindex(wide.index)
    required = ["pmin", "pmax"] + [f"p{p}" for p in DECILE_CORRIDOR_PERCENTILES]
    wide = wide.dropna(subset=required)
    if wide.empty:
        return None
    return wide.sort_index()


# --- Résolution du nageur cible dans le peloton ---


def _sort_corridor_swimmer_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Trie les lignes nageur selon la colonne disponible (âge ou split).

    Les données couloir âge×temps disposent de ``Age_swim`` ; les profils de
    pacing normalisés utilisent des lignes split (``split_no``, ``split_distance``).

    Args:
        df (pd.DataFrame): Lignes d'un nageur cible.

    Returns:
        pd.DataFrame: Copie triée ou entrée inchangée si aucune colonne d'ordre.
    """
    if df.empty:
        return df
    if "Age_swim" in df.columns:
        return df.sort_values("Age_swim")
    if "split_no" in df.columns:
        return df.sort_values("split_no")
    if "split_distance" in df.columns:
        return df.sort_values("split_distance")
    return df


def resolve_corridor_swimmer(
    long_df: pd.DataFrame,
    nom_nageur: str,
    year_of_birth: int,
    *,
    fuzzy_min_ratio: float = 0.55,
    fuzzy_max_yob_diff: float = 999.0,
) -> tuple[pd.DataFrame, str, int]:
    """Retourne les performances du nageur cible (triées par âge) et le nom/année résolus.

    Résolution en cascade : correspondance exacte nom+YOB, puis même nom avec YOB
    le plus proche, puis recherche par tokens, puis fuzzy (``difflib``).

    Args:
        long_df (pd.DataFrame): Données longues préparées.
        nom_nageur (str): Nom saisi par l'utilisateur.
        year_of_birth (int): Année de naissance attendue.
        fuzzy_min_ratio (float): Seuil minimal de similarité pour le fuzzy match.
        fuzzy_max_yob_diff (float): Écart maximal d'année de naissance accepté en fuzzy.

    Returns:
        tuple[pd.DataFrame, str, int]: Performances filtrées, nom résolu, YOB résolu.
    """
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

    # Résolution en cascade : exact → même nom / YOB proche → tokens → fuzzy (difflib).
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
                # Fuzzy match limité à 500 noms uniques (coût difflib)
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
    ]
    swimmer_data = _sort_corridor_swimmer_rows(swimmer_data)
    return swimmer_data, resolved_name, resolved_yob


def resolve_corridor_swimmer_flexible(
    long_df: pd.DataFrame,
    nom_nageur: str,
    year_of_birth: Optional[int] = None,
    *,
    fuzzy_min_ratio: float = 0.55,
    fuzzy_max_yob_diff: float = 999.0,
) -> tuple[pd.DataFrame, str, Optional[int]]:
    """Résout un nageur cible avec année de naissance optionnelle.

    Si ``year_of_birth`` est fourni, délègue à ``resolve_corridor_swimmer``.
    Sinon, cherche par nom seul et utilise la YOB la plus fréquente (mode).

    Args:
        long_df (pd.DataFrame): Données longues préparées.
        nom_nageur (str): Nom saisi par l'utilisateur.
        year_of_birth (Optional[int]): Année de naissance si connue.
        fuzzy_min_ratio (float): Seuil minimal de similarité fuzzy.
        fuzzy_max_yob_diff (float): Écart maximal YOB en fuzzy match.

    Returns:
        tuple[pd.DataFrame, str, Optional[int]]: Performances, nom résolu, YOB résolu
            (None si YOB indéterminée).
    """
    if year_of_birth is not None:
        try:
            df_s, name, yob = resolve_corridor_swimmer(
                long_df,
                nom_nageur,
                int(year_of_birth),
                fuzzy_min_ratio=fuzzy_min_ratio,
                fuzzy_max_yob_diff=fuzzy_max_yob_diff,
            )
            return df_s, name, int(yob)
        except (TypeError, ValueError):
            pass

    target_name = str(nom_nageur).strip()
    if not target_name or long_df.empty:
        return pd.DataFrame(), target_name, None

    target_norm = corridor_norm_name(target_name)
    name_norm = long_df["Name"].astype(str).map(corridor_norm_name)
    matches = long_df[name_norm == target_norm].copy()
    if matches.empty:
        unique = (
            long_df[["Name", "Year_of_birth"]]
            .dropna(subset=["Name"])
            .drop_duplicates()
            .copy()
        )
        if not unique.empty:
            unique["__norm"] = unique["Name"].astype(str).map(corridor_norm_name)
            tokens = [t for t in target_norm.split() if t]
            token_mask = unique["__norm"].map(
                lambda n: all(tok in n for tok in tokens) if tokens else False
            )
            by_tokens = unique[token_mask]
            if not by_tokens.empty:
                best = by_tokens.iloc[0]
                resolved_name = str(best["Name"]).strip()
                yob_val = pd.to_numeric(best.get("Year_of_birth"), errors="coerce")
                if pd.notna(yob_val):
                    return resolve_corridor_swimmer_flexible(
                        long_df,
                        resolved_name,
                        int(yob_val),
                        fuzzy_min_ratio=fuzzy_min_ratio,
                        fuzzy_max_yob_diff=fuzzy_max_yob_diff,
                    )
        return pd.DataFrame(), target_name, None

    yob_series = pd.to_numeric(matches["Year_of_birth"], errors="coerce")
    if yob_series.notna().any():
        # Homonymes : année de naissance la plus fréquente dans les correspondances
        best_yob = int(yob_series.mode().iloc[0])
        resolved_name = str(matches.iloc[0]["Name"]).strip()
        df_s, name, yob = resolve_corridor_swimmer(
            long_df,
            resolved_name,
            best_yob,
            fuzzy_min_ratio=fuzzy_min_ratio,
            fuzzy_max_yob_diff=fuzzy_max_yob_diff,
        )
        return df_s, name, int(yob)

    matches = _sort_corridor_swimmer_rows(matches)
    resolved_name = str(matches.iloc[0]["Name"]).strip()
    return matches, resolved_name, None


# --- Filtrage et fusion des specs nageur ---


def corridor_gender_display_label(gender: Optional[str]) -> str:
    """Libellé lisible pour le genre affiché sur les graphiques couloir.

    Args:
        gender (Optional[str]): Code genre (``F``, ``M`` ou autre).

    Returns:
        str: Libellé pour titre/légende, ou chaîne vide si non applicable.
    """
    if gender == "F":
        return "Femmes"
    if gender == "M":
        return "Hommes"
    return ""


def exclude_corridor_swimmer_specs_from_df(
    df: pd.DataFrame,
    specs: Sequence[CorridorSwimmerSpec],
    *,
    name_col: str = "Name",
    yob_col: str = "Year_of_birth",
) -> pd.DataFrame:
    """Retire du peloton de référence les nages des nageurs cibles à comparer.

    Les percentiles du couloir doivent refléter le groupe de référence sans
    inclure les performances des nageurs superposés (évite un biais de comparaison).

    Args:
        df (pd.DataFrame): Données de référence (format long ou splits).
        specs (Sequence[CorridorSwimmerSpec]): Nageurs à exclure du couloir.
        name_col (str): Colonne nom du nageur.
        yob_col (str): Colonne année de naissance.

    Returns:
        pd.DataFrame: Copie filtrée ; entrée inchangée si ``specs`` vide ou df vide.
    """
    if df.empty or not specs or name_col not in df.columns:
        return df
    out = df.copy()
    name_norm = out[name_col].astype(str).map(corridor_norm_name)
    yob = (
        pd.to_numeric(out[yob_col], errors="coerce")
        if yob_col in out.columns
        else pd.Series(np.nan, index=out.index)
    )
    keep = pd.Series(True, index=out.index)
    for spec in specs:
        if not spec.name.strip():
            continue
        target = corridor_norm_name(spec.name)
        match = name_norm == target
        if spec.year_of_birth is not None:
            match = match & (yob == int(spec.year_of_birth))
        keep = keep & ~match
    return out.loc[keep].copy()


def filter_corridor_long_df_gender(
    long_df: pd.DataFrame, gender: Optional[str]
) -> pd.DataFrame:
    """Filtre le DataFrame long sur F ou M.

    Args:
        long_df (pd.DataFrame): Données longues à filtrer.
        gender (Optional[str]): ``"F"``, ``"M"`` ou autre (pas de filtre).

    Returns:
        pd.DataFrame: Sous-ensemble filtré, ou entrée inchangée si filtre absent.
    """
    if long_df.empty or gender not in ("F", "M") or "Gender" not in long_df.columns:
        return long_df
    g = long_df["Gender"].astype(str).str.strip().str.upper()
    return long_df[g == str(gender).upper()].copy()


def dedupe_corridor_swimmer_specs(
    specs: Sequence[CorridorSwimmerSpec],
) -> List[CorridorSwimmerSpec]:
    """Supprime les doublons de specs nageur (nom, année, libellé normalisés).

    Args:
        specs (Sequence[CorridorSwimmerSpec]): Spécifications à dédupliquer.

    Returns:
        List[CorridorSwimmerSpec]: Liste sans doublons, ordre de première occurrence conservé.
    """
    seen: set[tuple] = set()
    out: List[CorridorSwimmerSpec] = []
    for spec in specs:
        key = (
            corridor_norm_name(spec.name),
            spec.year_of_birth,
            corridor_norm_name(spec.label),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(spec)
    return out


def merge_corridor_swimmer_specs_for_plot(
    swimmer_specs: Optional[List[CorridorSwimmerSpec]],
    *,
    nom_nageur: Optional[str] = None,
    year_of_birth: Optional[int] = None,
    nom_label: str = "Nageur cible (France)",
    nom_color: str = CORRIDOR_FR_SWIMMER_COLOR,
    overlay_nageur: Optional[str] = None,
    overlay_year_of_birth: Optional[int] = None,
    overlay_label: str = "Nageur marocain (MAR)",
    overlay_color: str = CORRIDOR_MA_SWIMMER_COLOR,
) -> List[CorridorSwimmerSpec]:
    """Fusionne les specs nageur sans doublon (kwargs UI + paramètres legacy).

    Combine ``swimmer_specs`` existantes avec le nageur principal (France) et
    l'overlay marocain issus des kwargs de l'interface desktop.

    Args:
        swimmer_specs (Optional[List[CorridorSwimmerSpec]]): Specs déjà fournies.
        nom_nageur (Optional[str]): Nageur cible principal (legacy UI).
        year_of_birth (Optional[int]): YOB du nageur principal.
        nom_label (str): Libellé légende du nageur principal.
        nom_color (str): Couleur du nageur principal.
        overlay_nageur (Optional[str]): Nageur marocain à superposer.
        overlay_year_of_birth (Optional[int]): YOB de l'overlay.
        overlay_label (str): Libellé légende de l'overlay.
        overlay_color (str): Couleur de l'overlay.

    Returns:
        List[CorridorSwimmerSpec]: Liste dédupliquée, nageur principal en tête.
    """
    specs: List[CorridorSwimmerSpec] = list(swimmer_specs or [])

    def _has_name(name: str) -> bool:
        """Indique si un nageur normalisé est déjà présent dans ``specs``.

        Args:
            name (str): Nom du nageur à rechercher.

        Returns:
            bool: True si une spec existante porte le même nom normalisé.
        """
        target = corridor_norm_name(name)
        return any(corridor_norm_name(s.name) == target for s in specs)

    if nom_nageur and str(nom_nageur).strip() and not _has_name(str(nom_nageur)):
        specs.insert(
            0,
            CorridorSwimmerSpec(
                name=str(nom_nageur).strip(),
                year_of_birth=year_of_birth,
                color=nom_color,
                label=nom_label,
            ),
        )
    if overlay_nageur and str(overlay_nageur).strip() and not _has_name(
        str(overlay_nageur)
    ):
        yob_ov: Optional[int] = None
        if overlay_year_of_birth is not None:
            try:
                yob_ov = int(overlay_year_of_birth)
            except (TypeError, ValueError):
                yob_ov = None
        specs.append(
            CorridorSwimmerSpec(
                name=str(overlay_nageur).strip(),
                year_of_birth=yob_ov,
                color=overlay_color,
                label=overlay_label,
            )
        )
    return dedupe_corridor_swimmer_specs(specs)


def resolve_corridor_plot_gender(
    long_df: pd.DataFrame,
    gender_filter: Optional[str],
    specs: Sequence[CorridorSwimmerSpec],
) -> Optional[str]:
    """Détermine le sexe pour le couloir de référence et le tracé.

    Si le filtre UI est « Tous », déduit le sexe des nageurs ciblés. Si plusieurs
    sexes sont ciblés, retourne None pour ne pas exclure une nageuse F quand le
    peloton dominant est M.

    Args:
        long_df (pd.DataFrame): Données longues du peloton.
        gender_filter (Optional[str]): Filtre UI (``"F"``, ``"M"`` ou autre).
        specs (Sequence[CorridorSwimmerSpec]): Nageurs à tracer.

    Returns:
        Optional[str]: ``"F"``, ``"M"`` ou None si indéterminé / multi-sexes.
    """
    if gender_filter in ("F", "M"):
        return gender_filter
    if long_df.empty or "Name" not in long_df.columns:
        return None
    genders: set[str] = set()
    for spec in specs:
        if not spec.name.strip():
            continue
        target_norm = corridor_norm_name(spec.name)
        name_norm = long_df["Name"].astype(str).map(corridor_norm_name)
        mask = name_norm == target_norm
        if spec.year_of_birth is not None and "Year_of_birth" in long_df.columns:
            yob = pd.to_numeric(long_df["Year_of_birth"], errors="coerce")
            mask = mask & (yob == int(spec.year_of_birth))
        df_s = long_df.loc[mask]
        if df_s.empty or "Gender" not in df_s.columns:
            continue
        for value in df_s["Gender"].dropna().astype(str).str.strip().str.upper():
            if value in ("F", "M"):
                genders.add(value)
    if len(genders) == 1:
        return genders.pop()
    return None


# --- Combinaison Extranat + données marocaines ---


def prepare_corridor_long_df_combined(
    df_base: pd.DataFrame,
    nom_event: str,
    *,
    df_extra: Optional[pd.DataFrame] = None,
    solo_only: bool = True,
) -> pd.DataFrame:
    """Combine les données longues Extranat et les perfs marocaines pour un événement.

    Le peloton de référence (``df_base``) est filtré en solo uniquement ;
    les données marocaines (``df_extra``) acceptent aussi les relais.

    Args:
        df_base (pd.DataFrame): Performances Extranat / USA Swimming.
        nom_event (str): Libellé de l'épreuve.
        df_extra (Optional[pd.DataFrame]): Overlay FRM Natation (optionnel).
        solo_only (bool): Filtre solo pour ``df_base``.

    Returns:
        pd.DataFrame: Concaténation dédupliquée ; vide si aucune source exploitable.
    """
    parts: List[pd.DataFrame] = []
    base_long = prepare_corridor_long_df(
        df_base, nom_event, solo_only=solo_only, require_name=False
    )
    if not base_long.empty:
        parts.append(base_long)
    if df_extra is not None and not df_extra.empty:
        extra_long = prepare_corridor_long_df(
            df_extra, nom_event, solo_only=False, require_name=False
        )
        if not extra_long.empty:
            parts.append(extra_long)
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)
    subset = ["Name", "Year_of_birth", "SwimDate", "SwimTimeSeconds", "Age_swim"]
    present = [c for c in subset if c in combined.columns]
    if present:
        combined = combined.drop_duplicates(subset=present, keep="first")
    return combined


# --- Bornes d'âge et diagnostics ---


def corridor_age_limits(
    long_df: pd.DataFrame,
    swimmer_frames: Sequence[pd.DataFrame],
    *,
    default_min: int = 14,
    default_max: int = 35,
    padding: int = 1,
) -> tuple[int, int]:
    """Calcule la plage d'âges couvrant le couloir et les nageurs tracés.

    Args:
        long_df (pd.DataFrame): Peloton de référence.
        swimmer_frames (Sequence[pd.DataFrame]): Courbes nageur à inclure.
        default_min (int): Âge minimum par défaut si aucune donnée.
        default_max (int): Âge maximum par défaut si aucune donnée.
        padding (int): Marge (années) ajoutée de chaque côté.

    Returns:
        tuple[int, int]: ``(age_min, age_max)`` bornés par les défauts.
    """
    ages: List[float] = []
    if not long_df.empty and "Age_swim" in long_df.columns:
        ages.extend(
            pd.to_numeric(long_df["Age_swim"], errors="coerce").dropna().tolist()
        )
    for frame in swimmer_frames:
        if frame.empty or "Age_swim" not in frame.columns:
            continue
        ages.extend(pd.to_numeric(frame["Age_swim"], errors="coerce").dropna().tolist())
    if not ages:
        return default_min, default_max
    lo = max(default_min, int(min(ages)) - padding)
    hi = min(default_max, int(max(ages)) + padding)
    if lo > hi:
        return default_min, default_max
    return lo, hi


def corridor_swimmer_missing_hint(
    df: pd.DataFrame,
    nom_event: str,
    name: str,
    year_of_birth: Optional[int] = None,
) -> str:
    """Précise pourquoi un nageur confirmé n'apparaît pas sur le couloir (solo).

    Parcourt les performances brutes pour distinguer relais, chrono invalide
    et nage solo non exploitable.

    Args:
        df (pd.DataFrame): DataFrame source non filtré (avant ``prepare_corridor_long_df``).
        nom_event (str): Libellé de l'épreuve.
        name (str): Nom du nageur recherché.
        year_of_birth (Optional[int]): YOB pour affiner la recherche.

    Returns:
        str: Message d'aide pour l'UI, ou chaîne vide si aucun diagnostic.
    """
    target = str(name).strip()
    if not target or df.empty or "Event" not in df.columns:
        return ""
    scoped = df[df["Event"].astype(str).str.strip() == str(nom_event).strip()]
    if scoped.empty:
        return ""
    has_solo = False
    has_relay = False
    has_invalid_time = False
    for row in scoped.itertuples(index=False):
        swim_seconds = getattr(row, "SwimTimeSeconds", None)
        swimmers_raw = getattr(row, "swimmer", None)
        if not isinstance(swimmers_raw, list):
            continue
        for swimmer in swimmers_raw:
            if not isinstance(swimmer, dict):
                continue
            if str(swimmer.get("Name", "")).strip() != target:
                continue
            if year_of_birth is not None:
                try:
                    if int(swimmer.get("Year_of_birth")) != int(year_of_birth):
                        continue
                except (TypeError, ValueError):
                    continue
            if swim_seconds is None or swim_seconds != swim_seconds:
                # NaN check sans importer math
                has_invalid_time = True
                continue
            if len(swimmers_raw) == 1:
                has_solo = True
            else:
                has_relay = True
    if has_solo:
        return " (nage individuelle présente mais âge ou chrono non exploitable)"
    if has_relay:
        return " (présent uniquement en relais sur cette épreuve, pas en nage solo)"
    if has_invalid_time:
        return " (présent mais sans chrono valide sur cette épreuve)"
    return ""


# --- Couloir percentile (bandes) et profils de pacing normalisés ---


def corridor_swimmer_line_kwargs(spec: CorridorSwimmerSpec) -> Dict[str, Any]:
    """Style matplotlib pour un nageur : teinte + forme redondante (accessibilité).

    Le nageur marocain utilise un trait discontinu et des marqueurs carrés ;
    le nageur français/USA un trait plein et des cercles. La couleur reste
    le canal d'identité principale.

    Args:
        spec (CorridorSwimmerSpec): Nageur à tracer.

    Returns:
        Dict[str, Any]: Arguments ``plot`` / ``scatter`` matplotlib.
    """
    is_moroccan = (
        spec.color == CORRIDOR_MA_SWIMMER_COLOR
        or "maroc" in spec.label.lower()
    )
    if is_moroccan:
        return {
            "color": spec.color,
            "linewidth": 3.2,
            "linestyle": "--",
            "marker": "s",
            "markersize": 8,
            "markeredgecolor": "#1e293b",
            "markeredgewidth": 1.0,
            "zorder": 8,
        }
    return {
        "color": spec.color,
        "linewidth": 3.4,
        "linestyle": "-",
        "marker": "o",
        "markersize": 8,
        "markeredgecolor": "#1e293b",
        "markeredgewidth": 1.0,
        "zorder": 8,
    }


def apply_corridor_chart_theme(fig, ax) -> None:
    """Applique fond et grilles cohérents aux graphiques couloir.

    Args:
        fig: Figure matplotlib.
        ax: Axe principal.

    Returns:
        None
    """
    fig.patch.set_facecolor(CORRIDOR_CHART_FIGURE_FACECOLOR)
    ax.set_facecolor(CORRIDOR_CHART_AXES_FACECOLOR)
    ax.grid(alpha=CORRIDOR_GRID_ALPHA, color="#94a3b8", linestyle="-", linewidth=0.6)


def parse_split_distance_m(value: object) -> Optional[int]:
    """Convertit une distance de split en mètres entiers.

    Args:
        value (object): Distance brute (ex. « 50 m », 100).

    Returns:
        Optional[int]: Distance en mètres ou None si invalide.
    """
    if value is None:
        return None
    try:
        return int(float(str(value).lower().replace("m", "").strip()))
    except (TypeError, ValueError):
        return None


def parse_event_distance_m(event_name: object) -> Optional[int]:
    """Extrait la distance numérique depuis le libellé d'épreuve.

    Args:
        event_name (object): Nom d'épreuve (ex. « 400 NL LCM »).

    Returns:
        Optional[int]: Distance en mètres ou None.
    """
    match = re.search(r"(\d+)", str(event_name))
    return int(match.group(1)) if match else None


def _solo_swimmer_dict(swimmers: object) -> Optional[dict]:
    """Retourne le dict nageur si la performance est une nage solo.

    Args:
        swimmers (object): Colonne ``swimmer`` brute.

    Returns:
        Optional[dict]: Premier nageur ou None.
    """
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None
    first = swimmers[0]
    return first if isinstance(first, dict) else None


def _parse_split_segment_seconds(
    split: dict,
    *,
    prev_distance_m: int,
    distance_m: int,
) -> Optional[float]:
    """Retourne la durée du segment entre ``prev_distance_m`` et ``distance_m``.

    Args:
        split (dict): Dict split Extranat/USA (``split_seconds``, ``split_speed``).
        prev_distance_m (int): Distance cumulée du segment précédent (0 au départ).
        distance_m (int): Distance cumulée de ce passage.

    Returns:
        Optional[float]: Durée du segment en secondes, ou None si indéterminable.
    """
    length_m = distance_m - prev_distance_m
    if length_m <= 0:
        return None
    raw_sec = split.get("split_seconds")
    if raw_sec is not None:
        try:
            seg_sec = float(raw_sec)
            if seg_sec > 0:
                return seg_sec
        except (TypeError, ValueError):
            pass
    raw_speed = split.get("split_speed")
    if raw_speed is not None:
        try:
            speed = float(raw_speed)
            if speed > 0:
                return length_m / speed
        except (TypeError, ValueError):
            pass
    return None


def _segment_speed_mps(length_m: int, segment_seconds: float) -> Optional[float]:
    """Calcule une vitesse de segment en m/s.

    Args:
        length_m (int): Longueur du segment en mètres.
        segment_seconds (float): Durée du segment en secondes.

    Returns:
        Optional[float]: Vitesse en m/s ou None si invalide.
    """
    if length_m <= 0 or segment_seconds <= 0:
        return None
    speed = length_m / segment_seconds
    if 0 < speed < 6:
        return speed
    return None


def _synthetic_split_entries_from_total_time(
    event_distance: Optional[int],
    swim_time_seconds: object,
) -> List[tuple[int, int, float]]:
    """Synthétise un segment unique quand la source ne fournit aucun intermédiaire.

    Pour les épreuves 25 m et 50 m, Extranat ne publie souvent aucun passage
    intermédiaire : la vitesse moyenne sur toute la distance est dérivée du
    temps final lorsque celui-ci est disponible.

    Args:
        event_distance (Optional[int]): Distance d'épreuve en mètres.
        swim_time_seconds (object): Temps total de la nage en secondes.

    Returns:
        List[tuple[int, int, float]]: Un tuple ``(split_no, distance, speed)``
            ou liste vide si la synthèse est impossible.
    """
    if event_distance not in (25, 50):
        return []
    try:
        total_sec = float(swim_time_seconds)
    except (TypeError, ValueError):
        return []
    if total_sec <= 0:
        return []
    speed = _segment_speed_mps(event_distance, total_sec)
    if speed is None:
        return []
    return [(1, event_distance, speed)]


def _split_entries_for_performance(
    splits: list,
    *,
    event_distance: Optional[int],
    swim_time_seconds: object,
) -> List[tuple[int, int, float]]:
    """Construit les segments de vitesse exploitables pour une performance solo.

    Pour le 50 m SCM, Extranat ne fournit souvent qu'un passage à 25 m : le
  second segment (25–50 m) est reconstruit à partir du temps final.

    Args:
        splits (list): Liste de dicts ``splits`` bruts.
        event_distance (Optional[int]): Distance d'épreuve en mètres.
        swim_time_seconds (object): Temps total de la nage (secondes).

    Returns:
        List[tuple[int, int, float]]: Tuples ``(split_no, split_distance, split_speed)``.
    """
    if not isinstance(splits, list) or not splits:
        return []

    parsed: List[tuple[int, dict]] = []
    for split in splits:
        if not isinstance(split, dict):
            continue
        distance = parse_split_distance_m(split.get("split_distance"))
        if distance is None:
            continue
        parsed.append((distance, split))
    if not parsed:
        return []

    parsed.sort(key=lambda item: item[0])
    by_distance: List[tuple[int, float]] = []
    prev_dist = 0
    for distance, split in parsed:
        seg_sec = _parse_split_segment_seconds(
            split, prev_distance_m=prev_dist, distance_m=distance
        )
        if seg_sec is None:
            prev_dist = distance
            continue
        length_m = distance - prev_dist
        speed = _segment_speed_mps(length_m, seg_sec)
        if speed is not None:
            by_distance.append((distance, speed))
        prev_dist = distance

    distances = [d for d, _ in by_distance]
    if event_distance == 50 and 50 not in distances and 25 in distances:
        try:
            total_sec = float(swim_time_seconds)
        except (TypeError, ValueError):
            total_sec = 0.0
        if total_sec > 0:
            split25 = next(split for dist, split in parsed if dist == 25)
            seg1_sec = _parse_split_segment_seconds(
                split25, prev_distance_m=0, distance_m=25
            )
            if seg1_sec is not None and seg1_sec > 0:
                seg2_sec = total_sec - seg1_sec
                speed2 = _segment_speed_mps(25, seg2_sec)
                if speed2 is not None:
                    by_distance.append((50, speed2))

    if not by_distance:
        return []

    unique_distances = sorted({d for d, _ in by_distance})
    dist_to_no = {dist: idx + 1 for idx, dist in enumerate(unique_distances)}
    return [
        (dist_to_no[distance], distance, speed)
        for distance, speed in sorted(by_distance, key=lambda item: item[0])
    ]


def extract_event_split_speed_rows(
    df: pd.DataFrame,
    nom_event: str,
    *,
    require_complete_splits: bool = True,
) -> pd.DataFrame:
    """Extrait les vitesses de split (format long) pour une épreuve solo.

    Chaque ligne correspond à un segment de nage. Les nages relais sont exclues.
    Si ``require_complete_splits`` est True, seules les performances dont le
    dernier split atteint la distance d'épreuve sont conservées. Pour le 50 m,
    un passage unique à 25 m est complété par synthèse du segment 25–50 m
    lorsque le temps final est disponible.

    Args:
        df (pd.DataFrame): Performances source (Extranat, USA, Maroc).
        nom_event (str): Libellé exact de l'épreuve.
        require_complete_splits (bool): Exiger des splits couvrant toute la distance.

    Returns:
        pd.DataFrame: Colonnes ``swim_key``, ``Name``, ``Gender``, ``Year_of_birth``,
            ``split_no``, ``split_distance``, ``split_speed`` ; vide si rien d'exploitable.
    """
    if df.empty or "Event" not in df.columns:
        return pd.DataFrame()

    event_distance = parse_event_distance_m(nom_event)
    rows: List[dict[str, object]] = []
    event_mask = df["Event"].astype(str).str.strip() == str(nom_event).strip()

    for perf_idx, row in df.loc[event_mask].iterrows():
        swimmer = _solo_swimmer_dict(row.get("swimmer"))
        if swimmer is None:
            continue
        splits = row.get("splits")
        split_entries: List[tuple[int, int, float]] = []
        if isinstance(splits, list) and splits:
            split_entries = _split_entries_for_performance(
                splits,
                event_distance=event_distance,
                swim_time_seconds=row.get("SwimTimeSeconds"),
            )
        else:
            split_entries = _synthetic_split_entries_from_total_time(
                event_distance,
                row.get("SwimTimeSeconds"),
            )
        if not split_entries:
            continue
        if require_complete_splits and event_distance is not None:
            last_dist = max(d for _, d, _ in split_entries)
            if last_dist != event_distance:
                continue

        gender = _normalize_gender_code(swimmer.get("Gender"))
        if gender not in ("F", "M"):
            continue

        swim_key = (
            f"{perf_idx}|{swimmer.get('Name')}|{row.get('SwimDate')}|"
            f"{row.get('SwimTimeSeconds')}"
        )
        for split_no, distance, speed in sorted(split_entries, key=lambda t: t[1]):
            rows.append(
                {
                    "swim_key": swim_key,
                    "Name": swimmer.get("Name"),
                    "Gender": gender,
                    "Year_of_birth": swimmer.get("Year_of_birth"),
                    "split_no": split_no,
                    "split_distance": distance,
                    "split_speed": speed,
                }
            )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


_PACING_EVENT_SPLITS_CACHE: "OrderedDict[tuple, bool]" = OrderedDict()
_PACING_EVENT_SPLITS_CACHE_MAX = 256


def event_supports_pacing_profile(
    df: pd.DataFrame,
    nom_event: str,
) -> bool:
    """Indique si une épreuve dispose de splits exploitables pour le profil de pacing.

    Args:
        df (pd.DataFrame): Performances source (Extranat, USA).
        nom_event (str): Libellé exact de l'épreuve (ex. ``100 FR SCM``).

    Returns:
        bool: True si au moins une nage solo avec splits complets est disponible.
    """
    cache_key = (str(nom_event).strip(), len(df))
    cached = _PACING_EVENT_SPLITS_CACHE.get(cache_key)
    if cached is not None:
        _PACING_EVENT_SPLITS_CACHE.move_to_end(cache_key)
        return cached
    supported = not extract_event_split_speed_rows(df, nom_event).empty
    _PACING_EVENT_SPLITS_CACHE[cache_key] = supported
    _PACING_EVENT_SPLITS_CACHE.move_to_end(cache_key)
    if len(_PACING_EVENT_SPLITS_CACHE) > _PACING_EVENT_SPLITS_CACHE_MAX:
        _PACING_EVENT_SPLITS_CACHE.popitem(last=False)
    return supported


def distance_supports_pacing_profile(
    df: pd.DataFrame,
    stroke: str,
    distance: int,
    pools: Sequence[str],
) -> bool:
    """Vérifie si au moins un bassin propose des splits pour une nage et distance.

    Args:
        df (pd.DataFrame): Performances source.
        stroke (str): Code nage (ex. ``FR``).
        distance (int): Distance en mètres.
        pools (Sequence[str]): Bassins candidats (``SCM``, ``LCM``).

    Returns:
        bool: True si l'épreuve est exploitable pour le profil de pacing normalisé.
    """
    stroke_key = str(stroke).strip()
    for pool in pools:
        pool_key = str(pool).strip()
        if not pool_key:
            continue
        nom_event = f"{int(distance)} {stroke_key} {pool_key}"
        if event_supports_pacing_profile(df, nom_event):
            return True
    return False


def add_within_swim_speed_pct(
    split_df: pd.DataFrame,
    *,
    speed_col: str = "split_speed",
    out_col: str = "speed_pct",
) -> pd.DataFrame:
    """Ajoute la vitesse normalisée en % de la vitesse moyenne de chaque nage.

    La normalisation intra-nage permet de comparer la forme du profil de pacing
    indépendamment du niveau absolu (Robertson et al., Skorski et al.).

    Args:
        split_df (pd.DataFrame): Lignes split avec ``swim_key`` et ``speed_col``.
        speed_col (str): Colonne vitesse brute (m/s).
        out_col (str): Nom de la colonne de sortie (%).

    Returns:
        pd.DataFrame: Copie enrichie ; lignes sans moyenne valide exclues.
    """
    if split_df.empty or "swim_key" not in split_df.columns:
        return pd.DataFrame()
    out = split_df.copy()
    out[speed_col] = pd.to_numeric(out[speed_col], errors="coerce")
    means = out.groupby("swim_key")[speed_col].transform("mean")
    valid = means.notna() & (means > 0) & out[speed_col].notna()
    out = out.loc[valid].copy()
    out[out_col] = (out[speed_col] / means.loc[valid]) * 100.0
    return out


def compute_group_percentiles_df(
    values_df: pd.DataFrame,
    group_col: str,
    value_col: str,
    percentiles: Sequence[int],
    *,
    min_points: int = 5,
) -> Optional[pd.DataFrame]:
    """Calcule les percentiles d'une variable numérique par groupe.

    Args:
        values_df (pd.DataFrame): Données longues à agréger.
        group_col (str): Colonne de regroupement (âge, split_no, etc.).
        value_col (str): Colonne numérique (temps, vitesse %, etc.).
        percentiles (Sequence[int]): Percentiles demandés (ex. [10, 25, 50, 75, 90]).
        min_points (int): Effectif minimal par groupe.

    Returns:
        Optional[pd.DataFrame]: Colonnes ``p{percentile}`` indexées par ``group_col``,
            ou None si données insuffisantes.
    """
    if values_df.empty or group_col not in values_df.columns:
        return None
    sub = values_df[
        values_df[group_col].notna() & values_df[value_col].notna()
    ].copy()
    if sub.empty:
        return None
    counts = sub.groupby(group_col)[value_col].transform("count")
    sub = sub.loc[counts >= min_points]
    if sub.empty:
        return None
    qs = [p / 100.0 for p in percentiles]
    wide = (
        sub.groupby(group_col, sort=True)[value_col]
        .quantile(qs)
        .unstack(level=1)
    )
    if wide.empty:
        return None
    wide.columns = [f"p{int(round(c * 100))}" for c in wide.columns]
    return wide.sort_index()


def draw_percentile_corridor_bands(
    ax,
    x_values: Sequence,
    df_percentiles: pd.DataFrame,
    *,
    outer_low: str = "p10",
    outer_high: str = "p90",
    inner_low: str = "p25",
    inner_high: str = "p75",
    median_col: str = "p50",
    below_median_outer_color: str = CORRIDOR_BELOW_MEDIAN_OUTER_COLOR,
    below_median_inner_color: str = CORRIDOR_BELOW_MEDIAN_INNER_COLOR,
    above_median_outer_color: str = CORRIDOR_ABOVE_MEDIAN_OUTER_COLOR,
    above_median_inner_color: str = CORRIDOR_ABOVE_MEDIAN_INNER_COLOR,
    median_color: str = CORRIDOR_MEDIAN_COLOR,
    median_linewidth: float = CORRIDOR_MEDIAN_LINEWIDTH,
    outer_alpha: float = CORRIDOR_BAND_OUTER_ALPHA,
    inner_alpha: float = CORRIDOR_BAND_INNER_ALPHA,
    outer_label_below: str = "Couloir P10–P50 (sous médiane)",
    outer_label_above: str = "Couloir P50–P90 (au-dessus médiane)",
    inner_label_below: str = "_nolegend_",
    inner_label_above: str = "_nolegend_",
    median_label: str = "Médiane du groupe",
    zorder_bands: int = 1,
    zorder_median: int = 3,
) -> None:
    """Trace un couloir percentile divergent autour de la médiane (P50).

    Les domaines P10–P90 et P25–P75 sont scindés en deux moitiés : sous la
    médiane (bleu, dégradé clair→foncé vers P50) et au-dessus (ambre, idem).
    La ligne médiane matérialise le point neutre (carte divergente, Munzner 2014).

    Args:
        ax: Axe matplotlib cible.
        x_values (Sequence): Abscisses alignées sur l'index de ``df_percentiles``.
        df_percentiles (pd.DataFrame): Colonnes ``p10``…``p90`` (ou équivalent).
        outer_low (str): Colonne borne basse externe (ex. ``p10``).
        outer_high (str): Colonne borne haute externe (ex. ``p90``).
        inner_low (str): Colonne borne basse interne (ex. ``p25``).
        inner_high (str): Colonne borne haute interne (ex. ``p75``).
        median_col (str): Colonne médiane (ex. ``p50``).
        below_median_outer_color (str): Couleur bande externe sous la médiane.
        below_median_inner_color (str): Couleur bande interne sous la médiane.
        above_median_outer_color (str): Couleur bande externe au-dessus de la médiane.
        above_median_inner_color (str): Couleur bande interne au-dessus de la médiane.
        median_color (str): Couleur ligne médiane (point neutre divergent).
        median_linewidth (float): Épaisseur de la ligne médiane.
        outer_alpha (float): Transparence bandes externes.
        inner_alpha (float): Transparence bandes internes.
        outer_label_below (str): Libellé légende bande externe sous médiane.
        outer_label_above (str): Libellé légende bande externe au-dessus médiane.
        inner_label_below (str): Libellé légende bande interne sous médiane.
        inner_label_above (str): Libellé légende bande interne au-dessus médiane.
        median_label (str): Libellé légende médiane.
        zorder_bands (int): Plan de dessin des bandes.
        zorder_median (int): Plan de dessin de la médiane.

    Returns:
        None
    """
    if df_percentiles.empty:
        return
    if median_col not in df_percentiles.columns:
        return

    x = list(x_values)
    median = df_percentiles[median_col]

    has_outer = outer_low in df_percentiles.columns and outer_high in df_percentiles.columns
    has_inner = inner_low in df_percentiles.columns and inner_high in df_percentiles.columns

    if has_outer and len(x) > 1:
        ax.fill_between(
            x,
            df_percentiles[outer_low],
            median,
            color=below_median_outer_color,
            alpha=outer_alpha,
            linewidth=0,
            label=outer_label_below,
            zorder=zorder_bands,
        )
        ax.fill_between(
            x,
            median,
            df_percentiles[outer_high],
            color=above_median_outer_color,
            alpha=outer_alpha,
            linewidth=0,
            label=outer_label_above,
            zorder=zorder_bands,
        )
        for edge_col, edge_color in (
            (outer_low, CORRIDOR_BELOW_MEDIAN_EDGE_COLOR),
            (outer_high, CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR),
        ):
            ax.plot(
                x,
                df_percentiles[edge_col],
                color=edge_color,
                alpha=CORRIDOR_BAND_EDGE_ALPHA,
                linewidth=0.8,
                linestyle="-",
                label="_nolegend_",
                zorder=zorder_bands + 1,
            )

    if has_inner and len(x) > 1:
        ax.fill_between(
            x,
            df_percentiles[inner_low],
            median,
            color=below_median_inner_color,
            alpha=inner_alpha,
            linewidth=0,
            label=inner_label_below,
            zorder=zorder_bands + 2,
        )
        ax.fill_between(
            x,
            median,
            df_percentiles[inner_high],
            color=above_median_inner_color,
            alpha=inner_alpha,
            linewidth=0,
            label=inner_label_above,
            zorder=zorder_bands + 2,
        )

    ax.plot(
        x,
        median,
        color=median_color,
        linewidth=median_linewidth,
        linestyle="-",
        solid_capstyle="round",
        label=median_label,
        zorder=zorder_median,
    )
    if len(x) == 1:
        x0 = x[0]
        median_v = float(median.iloc[0])
        if has_outer:
            ax.scatter(
                [x0, x0],
                [
                    float(df_percentiles[outer_low].iloc[0]),
                    float(df_percentiles[outer_high].iloc[0]),
                ],
                color=[
                    CORRIDOR_BELOW_MEDIAN_EDGE_COLOR,
                    CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR,
                ],
                s=45,
                marker="_",
                linewidths=2.2,
                zorder=zorder_median + 1,
                label="_nolegend_",
            )
        if has_inner:
            ax.scatter(
                [x0, x0],
                [
                    float(df_percentiles[inner_low].iloc[0]),
                    float(df_percentiles[inner_high].iloc[0]),
                ],
                color=[
                    below_median_inner_color,
                    above_median_inner_color,
                ],
                s=40,
                marker="o",
                edgecolors="#1e293b",
                linewidths=0.8,
                alpha=0.9,
                zorder=zorder_median + 1,
                label="_nolegend_",
            )
        ax.scatter(
            [x0],
            [median_v],
            color=median_color,
            s=55,
            marker="o",
            edgecolors="#1e293b",
            linewidths=0.8,
            zorder=zorder_median + 2,
            label="_nolegend_",
        )


def draw_decile_corridor_bands(
    ax,
    x_values: Sequence,
    df_deciles: pd.DataFrame,
    *,
    median_color: str = CORRIDOR_MEDIAN_COLOR,
    median_linewidth: float = CORRIDOR_MEDIAN_LINEWIDTH,
    band_alpha: float = DECILE_BAND_ALPHA,
    zorder_bands: int = 1,
    zorder_median: int = 12,
) -> None:
    """Trace un couloir en 10 bandes déciles (≈ 10 % du peloton chacune).

    Les bandes D10–D6 (Pmin→P50) utilisent une rampe bleue ; D5–D1 (P50→Pmax)
    une rampe ambre, avec la médiane P50 comme point de bascule divergent.

    Args:
        ax: Axe matplotlib cible.
        x_values (Sequence): Abscisses alignées sur l'index de ``df_deciles``.
        df_deciles (pd.DataFrame): Colonnes ``pmin``, ``p10``…``p90``, ``pmax``.
        median_color (str): Couleur de la ligne médiane (point neutre divergent).
        median_linewidth (float): Épaisseur de la ligne médiane.
        band_alpha (float): Transparence des bandes déciles.
        zorder_bands (int): Plan de dessin des bandes.
        zorder_median (int): Plan de dessin de la médiane.

    Returns:
        None
    """
    if df_deciles.empty:
        return
    x = list(x_values)
    boundary_cols = ["pmin"] + [f"p{p}" for p in DECILE_CORRIDOR_PERCENTILES] + ["pmax"]
    for col in boundary_cols:
        if col not in df_deciles.columns:
            return

    decile_labels = (
        "D10 (10 % les plus rapides)",
        "D9",
        "D8",
        "D7",
        "D6",
        "D5",
        "D4",
        "D3",
        "D2",
        "D1 (10 % les plus lents)",
    )
    median_split_idx = 5
    for idx in range(10):
        low_col = boundary_cols[idx]
        high_col = boundary_cols[idx + 1]
        if idx < median_split_idx:
            palette = DECILE_BAND_COLORS_BELOW_MEDIAN
            palette_idx = idx
            edge_color = DECILE_EDGE_BELOW_COLOR
        else:
            palette = DECILE_BAND_COLORS_ABOVE_MEDIAN
            palette_idx = idx - median_split_idx
            edge_color = DECILE_EDGE_ABOVE_COLOR
        color = palette[palette_idx] if palette_idx < len(palette) else "#808080"
        if len(x) > 1:
            ax.fill_between(
                x,
                df_deciles[low_col],
                df_deciles[high_col],
                color=color,
                alpha=band_alpha,
                linewidth=0,
                label=decile_labels[idx] if idx in (0, 9) else "_nolegend_",
                zorder=zorder_bands + idx,
            )
            ax.plot(
                x,
                df_deciles[high_col],
                color=edge_color,
                alpha=DECILE_EDGE_ALPHA,
                linewidth=0.55,
                linestyle="-",
                label="_nolegend_",
                zorder=zorder_bands + idx + 1,
            )
        else:
            x0 = x[0]
            y_mid = float(
                (df_deciles[low_col].iloc[0] + df_deciles[high_col].iloc[0]) / 2.0
            )
            ax.scatter(
                [x0],
                [y_mid],
                color=color,
                alpha=0.95,
                s=36,
                marker="s",
                edgecolors=edge_color,
                linewidths=0.7,
                label=decile_labels[idx] if idx in (0, 9) else "_nolegend_",
                zorder=zorder_bands + idx,
            )

    if "p50" in df_deciles.columns:
        ax.plot(
            x,
            df_deciles["p50"],
            color=median_color,
            linewidth=median_linewidth,
            linestyle="-",
            solid_capstyle="round",
            label="Médiane (D5)",
            zorder=zorder_median,
        )


def mean_normalized_profile_for_swimmer(
    split_df: pd.DataFrame,
    name: str,
    year_of_birth: Optional[int] = None,
) -> pd.DataFrame:
    """Moyenne des profils normalisés d'un nageur par numéro de split.

    Args:
        split_df (pd.DataFrame): Splits avec ``speed_pct``, ``Name``, ``split_no``.
        name (str): Nom du nageur.
        year_of_birth (Optional[int]): Année de naissance pour désambiguïser.

    Returns:
        pd.DataFrame: Colonnes ``split_no``, ``split_distance``, ``speed_pct``,
            ``n_swims`` ; vide si nageur introuvable.
    """
    if split_df.empty or "speed_pct" not in split_df.columns:
        return pd.DataFrame()
    target_norm = corridor_norm_name(name)
    name_norm = split_df["Name"].astype(str).map(corridor_norm_name)
    mask = name_norm == target_norm
    if year_of_birth is not None:
        yob = pd.to_numeric(split_df["Year_of_birth"], errors="coerce")
        mask = mask & (yob == int(year_of_birth))
    sub = split_df.loc[mask]
    if sub.empty:
        return pd.DataFrame()
    return (
        sub.groupby(["split_no", "split_distance"], as_index=False)
        .agg(speed_pct=("speed_pct", "mean"), n_swims=("speed_pct", "count"))
        .sort_values("split_no")
    )


def plot_normalized_pacing_profiles_on_ax(
    ax,
    split_df: pd.DataFrame,
    specs: Sequence[CorridorSwimmerSpec],
) -> List[str]:
    """Trace les profils de pacing normalisés (lignes) pour des nageurs cibles.

    Args:
        ax: Axe matplotlib cible.
        split_df (pd.DataFrame): Splits avec ``speed_pct``.
        specs (Sequence[CorridorSwimmerSpec]): Nageurs à superposer.

    Returns:
        List[str]: Messages d'avertissement par nageur introuvable.
    """
    messages: List[str] = []
    for spec in specs:
        if not spec.name.strip():
            continue
        profile = mean_normalized_profile_for_swimmer(
            split_df, spec.name, spec.year_of_birth
        )
        if profile.empty:
            yob_txt = (
                f" ({spec.year_of_birth})" if spec.year_of_birth is not None else ""
            )
            messages.append(
                f"{spec.label} introuvable ou sans splits exploitables "
                f"(splits intermédiaires requis) : {spec.name}{yob_txt}"
            )
            continue
        n_swims = int(profile["n_swims"].max()) if "n_swims" in profile.columns else 1
        legend_label = (
            f"{spec.label} (moy. {n_swims} nages)" if n_swims > 1 else spec.label
        )
        line_kw = corridor_swimmer_line_kwargs(spec)
        ax.plot(
            profile["split_distance"],
            profile["speed_pct"],
            label=legend_label,
            **line_kw,
        )
    return messages


# --- Tracé matplotlib des nageurs cibles ---


def plot_corridor_swimmer_specs(
    ax,
    long_df: pd.DataFrame,
    specs: Sequence[CorridorSwimmerSpec],
    *,
    fuzzy_min_ratio: float = 0.55,
    source_df: Optional[pd.DataFrame] = None,
    nom_event: Optional[str] = None,
) -> List[str]:
    """Trace plusieurs nageurs (âge × temps en secondes) sur un axe matplotlib.

    Pour chaque spec, résout le nageur, trace la courbe et annote le dernier point.
    Collecte les messages d'erreur pour affichage dans l'UI.

    Args:
        ax: Axe matplotlib cible.
        long_df (pd.DataFrame): Données longues du peloton.
        specs (Sequence[CorridorSwimmerSpec]): Nageurs à tracer.
        fuzzy_min_ratio (float): Seuil fuzzy pour la résolution.
        source_df (Optional[pd.DataFrame]): DataFrame brut pour diagnostics.
        nom_event (Optional[str]): Épreuve pour ``corridor_swimmer_missing_hint``.

    Returns:
        List[str]: Messages d'erreur ou d'avertissement par nageur introuvable.
    """
    messages: List[str] = []
    for spec in specs:
        if not spec.name.strip():
            continue
        df_swimmer, resolved_name, resolved_yob = resolve_corridor_swimmer_flexible(
            long_df,
            spec.name,
            spec.year_of_birth,
            fuzzy_min_ratio=fuzzy_min_ratio,
        )
        if df_swimmer.empty or "Age_swim" not in df_swimmer.columns:
            yob_txt = (
                f" ({spec.year_of_birth})"
                if spec.year_of_birth is not None
                else ""
            )
            hint = ""
            if source_df is not None and nom_event:
                hint = corridor_swimmer_missing_hint(
                    source_df,
                    str(nom_event),
                    spec.name,
                    spec.year_of_birth,
                )
            else:
                target_norm = corridor_norm_name(spec.name)
                name_norm = long_df["Name"].astype(str).map(corridor_norm_name)
                if (name_norm == target_norm).any():
                    hint = " (présent mais sans chrono ou âge valide sur cette épreuve)"
            messages.append(
                f"{spec.label} introuvable : {spec.name}{yob_txt}{hint}"
            )
            continue
        ages = pd.to_numeric(df_swimmer["Age_swim"], errors="coerce")
        times = pd.to_numeric(df_swimmer["SwimTimeSeconds"], errors="coerce")
        valid = ages.notna() & times.notna()
        df_plot = df_swimmer.loc[valid].sort_values("Age_swim")
        if df_plot.empty:
            messages.append(
                f"{spec.label} : pas de points âge/temps exploitables pour {spec.name}"
            )
            continue
        line_kw = corridor_swimmer_line_kwargs(spec)
        ax.plot(
            df_plot["Age_swim"],
            df_plot["SwimTimeSeconds"],
            label=spec.label,
            **line_kw,
        )
        last = df_plot.iloc[-1]
        ax.scatter(
            last["Age_swim"],
            last["SwimTimeSeconds"],
            color=spec.color,
            marker=line_kw.get("marker", "o"),
            s=(line_kw.get("markersize", 7) ** 2) * 1.8,
            edgecolors=line_kw.get("markeredgecolor", "white"),
            linewidths=line_kw.get("markeredgewidth", 0.9),
            zorder=line_kw.get("zorder", 7) + 1,
        )
        yob_ann = (
            f" ({int(resolved_yob)})"
            if resolved_yob is not None
            else ""
        )
        ax.annotate(
            f"{resolved_name}{yob_ann}",
            (last["Age_swim"], last["SwimTimeSeconds"]),
            xytext=(8, 0),
            textcoords="offset points",
            color=spec.color,
            fontsize=9,
            fontweight="bold",
        )
    return messages


# --- Construction des kwargs pour graph_service ---


def build_corridor_chart_plot_kwargs(
    *,
    gender_filter: Optional[str] = None,
    primary_name: Optional[str] = None,
    primary_yob: Optional[int] = None,
    primary_df: Optional[pd.DataFrame] = None,
    primary_label: str = "Nageur cible (France)",
    primary_color: str = CORRIDOR_FR_SWIMMER_COLOR,
    overlay_name: Optional[str] = None,
    overlay_yob: Optional[int] = None,
    overlay_df: Optional[pd.DataFrame] = None,
    overlay_label: str = "Nageur marocain (MAR)",
    french_name: Optional[str] = None,
    french_yob: Optional[int] = None,
    moroccan_name: Optional[str] = None,
    moroccan_yob: Optional[int] = None,
    moroccan_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Construit les paramètres communs pour les couloirs âge × temps.

    Unifie les kwargs legacy (``french_name``, ``moroccan_name``) et les noms
    modernes (``primary_name``, ``overlay_name``) en ``swimmer_specs`` et
    ``overlay_df`` pour ``graph_service``.

    Args:
        gender_filter (Optional[str]): Filtre genre UI.
        primary_name (Optional[str]): Nageur cible principal.
        primary_yob (Optional[int]): YOB du nageur principal.
        primary_df (Optional[pd.DataFrame]): Performances du nageur principal.
        primary_label (str): Libellé légende principal.
        primary_color (str): Couleur du nageur principal.
        overlay_name (Optional[str]): Nageur overlay (MAR).
        overlay_yob (Optional[int]): YOB overlay.
        overlay_df (Optional[pd.DataFrame]): Performances overlay.
        overlay_label (str): Libellé légende overlay.
        french_name (Optional[str]): Alias legacy pour ``primary_name``.
        french_yob (Optional[int]): Alias legacy pour ``primary_yob``.
        moroccan_name (Optional[str]): Alias legacy pour ``overlay_name``.
        moroccan_yob (Optional[int]): Alias legacy pour ``overlay_yob``.
        moroccan_df (Optional[pd.DataFrame]): Alias legacy pour ``overlay_df``.

    Returns:
        Dict[str, Any]: Kwargs prêts à passer à la fonction de tracé couloir.
    """
    # Rétrocompatibilité : alias french_* / moroccan_* → primary_* / overlay_*
    if primary_name is None and french_name:
        primary_name = french_name
        primary_yob = french_yob
    if overlay_name is None and moroccan_name:
        overlay_name = moroccan_name
        overlay_yob = moroccan_yob
        overlay_df = moroccan_df

    kwargs: Dict[str, Any] = {}
    if gender_filter in ("F", "M"):
        kwargs["gender_filter"] = gender_filter

    specs: List[CorridorSwimmerSpec] = []
    if (
        isinstance(overlay_name, str)
        and overlay_name.strip()
        and overlay_df is not None
        and not overlay_df.empty
    ):
        specs.append(
            CorridorSwimmerSpec(
                name=overlay_name.strip(),
                year_of_birth=overlay_yob,
                color=CORRIDOR_MA_SWIMMER_COLOR,
                label=overlay_label,
            )
        )
        kwargs["overlay_nageur"] = overlay_name.strip()
        kwargs["overlay_year_of_birth"] = overlay_yob
        kwargs["overlay_df"] = overlay_df

    if isinstance(primary_name, str) and primary_name.strip():
        specs.insert(
            0,
            CorridorSwimmerSpec(
                name=primary_name.strip(),
                year_of_birth=primary_yob,
                color=primary_color,
                label=primary_label,
            ),
        )
        if primary_df is not None and not primary_df.empty:
            if overlay_df is None or overlay_df.empty:
                kwargs["overlay_df"] = primary_df
            else:
                kwargs["overlay_df"] = pd.concat(
                    [primary_df, overlay_df], ignore_index=True
                ).drop_duplicates(
                    subset=[
                        c
                        for c in (
                            "Name",
                            "Year_of_birth",
                            "SwimDate",
                            "SwimTimeSeconds",
                            "Event",
                        )
                        if c in primary_df.columns or c in overlay_df.columns
                    ],
                    keep="first",
                )

    if specs:
        kwargs["swimmer_specs"] = specs
    return kwargs
