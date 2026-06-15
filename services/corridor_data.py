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
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

# --- Constantes visuelles (couleurs des nageurs cibles) ---

CORRIDOR_FR_SWIMMER_COLOR = "#ef4444"  # rouge : nageur français / cible principale
CORRIDOR_MA_SWIMMER_COLOR = "#16a34a"  # vert : nageur marocain (overlay)


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


# --- Résolution du nageur cible dans le peloton ---


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
    ].sort_values("Age_swim")
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

    matches = matches.sort_values("Age_swim")
    resolved_name = str(matches.iloc[0]["Name"]).strip()
    return matches, resolved_name, None


# --- Filtrage et fusion des specs nageur ---


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
    genders: set[str] = set()
    for spec in specs:
        df_s, _, _ = resolve_corridor_swimmer_flexible(
            long_df, spec.name, spec.year_of_birth
        )
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
        ax.plot(
            df_plot["Age_swim"],
            df_plot["SwimTimeSeconds"],
            color=spec.color,
            linewidth=2.5,
            marker="o",
            label=spec.label,
            zorder=5,
        )
        last = df_plot.iloc[-1]
        ax.scatter(
            last["Age_swim"],
            last["SwimTimeSeconds"],
            color=spec.color,
            zorder=6,
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
