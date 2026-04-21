import base64
import datetime as dt
import io
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import flet as ft
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.ticker import MaxNLocator


PROJECT_DIR = Path(__file__).resolve().parent
APP_DIR = PROJECT_DIR / "app"
EXTRANAT_OUTPUT_BASE_DIR = (
    APP_DIR
    / "data"
    / "cleaned_data"
    / "extranat"
    / "competitions_per_type"
)


GRAPH_CATEGORIES: Dict[str, List[str]] = {
    "Distributions de temps": [
        "Histogramme simple",
        "Histogramme + densité",
        "Histogramme cumulatif",
    ],
    "Effectifs et répartition par sexe": [
        "Nombre de performances par épreuve",
        "Nombre de performances par épreuve (LCM + SCM)",
        "Comptage par sexe (global)",
        "Camembert par sexe (global)",
        "Camembert par sexe (épreuve)",
    ],
    "Comparaison des temps par nage": [
        "Distribution des temps par type de nage (boxplot)",
    ],
    "Clubs": [
        "Top 10 clubs par participation (épreuve)",
        "Temps médian des 10 meilleurs clubs",
    ],
    "Chronos dans le temps": [
        "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000",
    ],
    "Vitesse globale": [
        "Swimming Speed by Distance and Stroke Type",
        "Max Speed per Split Distance and Stroke",
    ],
    "Pacing comparatif": [
        "Split speed - F vs M + nageurs cibles",
    ],
    "Synthèse des vitesses par distance et nage": [
        "Heatmap vitesse moyenne (distance x nage)",
    ],
    "Évolution de la vitesse par splits": [
        "Lineplot of Speed ​​per split for a precise Swimmer and Event",
        "Lineplot of split speed for the best swimmer for a specific event",
        "Lineplot of split speed for the best swimmers for a specific event (women vs men)",
        "Line plot of Split Speed Progression of Top 10 Swimmers in a given Event (Women vs Men)",
    ],
    "Comparaisons de pacing par splits (à partir de la médiane)": [
        "Temps médian vs meilleur nageur",
        "Temps médian vs Top 10 nageurs",
        "Vitesse médiane par split selon le genre",
    ],
    "Pacing en relais": [
        "Split Speed vs Distance (Relay Events) with Mean Trend Line",
    ],
    "Couloirs de performance": [
        "Couloir de performance (âge) - nageur cible",
    ],
}

GRAPH_EXPORT_PATH = APP_DIR / "data" / "exports" / "prefetched_graphs.json"
ENABLE_STARTUP_WARMUP = False
EXPORT_IMAGE_BASE64_TO_JSON = True
ENABLE_PERSISTENT_GRAPH_CACHE = True


def build_graph_definitions() -> List[Dict[str, str]]:
    """
    Construit une liste d'objets décrivant chaque graphe UI:
    - name: nom du graphe
    - group: catégorie (groupe)
    - ui_method: nom de la méthode UI associée
    """
    graph_definitions: List[Dict[str, str]] = []
    for group_name, graph_names in GRAPH_CATEGORIES.items():
        for graph_name in graph_names:
            graph_definitions.append(
                {
                    "name": graph_name,
                    "group": group_name,
                    "ui_method": f"render_{_slugify(graph_name)}",
                }
            )
    return graph_definitions


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_split_distance(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).replace(" m", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_time_to_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(text)
    except ValueError:
        return None


def _primary_swimmer_name(swimmers: Any) -> Optional[str]:
    if not isinstance(swimmers, list) or len(swimmers) == 0:
        return None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None
    return first.get("Name")


def _primary_swimmer_name_and_yob(
    swimmers: Any,
) -> Tuple[Optional[str], Optional[int]]:
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


def _build_long_swims(df: pd.DataFrame, solo_only: bool = True) -> pd.DataFrame:
    data = df.copy()

    if solo_only:
        data = data[data["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)]

    data["swimmer_dict"] = data["swimmer"].apply(
        lambda x: x[0] if isinstance(x, list) and len(x) == 1 else None
    )

    data["Name"] = data["swimmer_dict"].apply(
        lambda x: x.get("Name") if isinstance(x, dict) else None
    )
    data["Gender"] = data["swimmer_dict"].apply(
        lambda x: x.get("Gender") if isinstance(x, dict) else None
    )
    data["Year_of_birth"] = data["swimmer_dict"].apply(
        lambda x: x.get("Year_of_birth") if isinstance(x, dict) else None
    )
    data["Age_json"] = data["swimmer_dict"].apply(
        lambda x: x.get("Age") if isinstance(x, dict) else None
    )

    data["SwimYear"] = pd.to_datetime(data["SwimDate"], errors="coerce").dt.year
    data["Age_swim"] = data["Age_json"]

    mask = data["Age_swim"].isna() & data["Year_of_birth"].notna() & data["SwimYear"].notna()
    data.loc[mask, "Age_swim"] = data.loc[mask, "SwimYear"] - data.loc[mask, "Year_of_birth"]

    data["Age_swim"] = pd.to_numeric(data["Age_swim"], errors="coerce").astype("Int64")
    return data


def _extract_split_rows(df_input: pd.DataFrame) -> pd.DataFrame:
    split_rows: List[Dict[str, Any]] = []
    for _, row in df_input.iterrows():
        swimmer_name = _primary_swimmer_name(row.get("swimmer"))
        splits = row.get("splits", [])
        if not isinstance(splits, list):
            continue
        for idx, split in enumerate(splits, start=1):
            if not isinstance(split, dict):
                continue
            dist = _parse_split_distance(split.get("split_distance"))
            speed = _to_float(split.get("split_speed"))
            split_time = _parse_time_to_seconds(split.get("split_time"))
            if dist is None:
                continue
            split_rows.append(
                {
                    "split_no": idx,
                    "split_distance": dist,
                    "split_speed": speed,
                    "split_time_sec": split_time,
                    "Gender": row.get("Gender"),
                    "Stroke": row.get("Stroke"),
                    "Distance": row.get("Distance"),
                    "PoolLength": row.get("PoolLength"),
                    "Event": row.get("Event"),
                    "Rank": _to_float(row.get("Rank")),
                    "SwimTimeSeconds": _to_float(row.get("SwimTimeSeconds")),
                    "Name": swimmer_name,
                }
            )
    return pd.DataFrame(split_rows)


def _pool_label_from_length(value: Any) -> Optional[str]:
    text = str(value).strip()
    if text in {"50", "50.0", "LCM"}:
        return "LCM"
    if text in {"25", "25.0", "SCM"}:
        return "SCM"
    return None


def _pool_display_label(pool_code: Optional[str]) -> str:
    if pool_code == "SCM":
        return "SCM (25 m)"
    if pool_code == "LCM":
        return "LCM (50 m)"
    return str(pool_code) if pool_code is not None else ""


def _normalize_text(value: Any) -> str:
    import unicodedata

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _slugify(text: str) -> str:
    value = _normalize_text(text)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


@lru_cache(maxsize=1)
def load_data() -> pd.DataFrame:
    """Chargement des JSON Extranat avec cache mémoire (équivalent st.cache_data)."""
    rows: List[Dict[str, Any]] = []

    if not EXTRANAT_OUTPUT_BASE_DIR.exists():
        return pd.DataFrame()

    for file in EXTRANAT_OUTPUT_BASE_DIR.rglob("*.json"):
        try:
            with file.open("r", encoding="utf-8") as f:
                comp = json.load(f)
        except Exception:
            continue

        for epreuve in comp.get("epreuves", []):
            for perf in epreuve.get("performances", []):

                swimmers = perf.get("swimmer", [])
                if isinstance(swimmers, dict):
                    swimmers = [swimmers]

                row = {
                    "Meet": comp.get("Meet"),
                    "SwimDate": comp.get("SwimDate"),
                    "Location": comp.get("location"),
                    "Country": comp.get("Country"),
                    "Event": epreuve.get("Event"),
                    "Distance": epreuve.get("Distance"),
                    "Stroke": epreuve.get("Stroke"),
                    "Course": epreuve.get("Course"),
                    "PoolLength": epreuve.get("PoolLength"),
                    "Tour": epreuve.get("tour"),
                    "Rank": perf.get("Rank"),
                    "Club": perf.get("club"),
                    "points": perf.get("points"),
                    "mpp": perf.get("mpp"),
                    "mpp_date": perf.get("mpp_date"),
                    "SwimTime": perf.get("SwimTime"),
                    "SwimTimeSeconds": perf.get("SwimTimeSeconds"),
                    "Status": perf.get("Status"),
                    "Speed": perf.get("Speed"),
                    "swimmer": swimmers,
                    "splits": perf.get("splits", []),
                }
                rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")
    df["Gender"] = df["swimmer"].apply(
        lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
    )
    return df


def _figure_to_base64(fig: plt.Figure) -> str:
    """Convertit une figure matplotlib en chaîne base64 PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _performance_corridor_plot_time(
    df: pd.DataFrame,
    nom_event: str,
    nom_nageur: str,
    year_of_birth: int,
    age_min: int = 14,
    age_max: int = 35,
    solo_only: bool = True,
    min_points: int = 5,
    figsize: Tuple[int, int] = (12, 8),
) -> Optional[plt.Figure]:
    long_df = _build_long_swims(df, solo_only=solo_only)

    long_df = long_df[
        (long_df["Event"] == nom_event)
        & (long_df["SwimTimeSeconds"].notna())
        & (long_df["Name"].notna())
        & (long_df["Gender"].notna())
        & (long_df["Age_swim"].notna())
        & (long_df["Year_of_birth"].notna())
    ].copy()
    if long_df.empty:
        return None

    target_name = nom_nageur.strip().lower()

    swimmer_data = long_df[
        (long_df["Name"].str.strip().str.lower() == target_name)
        & (long_df["Year_of_birth"] == year_of_birth)
    ]
    if swimmer_data.empty:
        return None

    gender = swimmer_data["Gender"].mode().iloc[0]
    long_df = long_df[long_df["Gender"] == gender]

    swimmer_name = swimmer_data.iloc[0]["Name"]
    swimmer_yob = swimmer_data.iloc[0]["Year_of_birth"]

    percentiles = [10, 25, 50, 75, 90]

    grouped = long_df.groupby("Age_swim")["SwimTimeSeconds"].agg(list)
    grouped = grouped.apply(lambda x: x if len(x) >= min_points else np.nan).dropna()

    df_percentiles = pd.DataFrame(
        {f"p{p}": grouped.apply(lambda x: np.percentile(x, p)) for p in percentiles}
    )
    df_percentiles = df_percentiles.loc[
        (df_percentiles.index >= age_min) & (df_percentiles.index <= age_max)
    ]

    df_swimmer = long_df[
        (long_df["Name"] == swimmer_name) & (long_df["Year_of_birth"] == swimmer_yob)
    ].sort_values("Age_swim")

    if df_percentiles.empty or df_swimmer.empty:
        return None

    fig, ax = plt.subplots(figsize=figsize)
    for p in percentiles:
        ax.plot(
            df_percentiles.index,
            df_percentiles[f"p{p}"],
            linestyle="--",
            label=f"{p}%",
        )

    ax.fill_between(
        df_percentiles.index,
        df_percentiles["p25"],
        df_percentiles["p75"],
        alpha=0.2,
        label="Zone 25-75%",
    )

    ax.plot(
        df_swimmer["Age_swim"],
        df_swimmer["SwimTimeSeconds"],
        color="red",
        linewidth=2.5,
        marker="o",
    )

    last = df_swimmer.iloc[-1]
    ax.scatter(last["Age_swim"], last["SwimTimeSeconds"], color="red")
    ax.annotate(
        f"{swimmer_name} ({swimmer_yob})",
        (last["Age_swim"], last["SwimTimeSeconds"]),
        xytext=(8, 0),
        textcoords="offset points",
    )

    ax.invert_yaxis()
    ax.set_xlabel("Âge")
    ax.set_ylabel("Temps (secondes)")
    ax.set_title(f"Couloir de performance - {nom_event}")
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()
    return fig


def _build_df_nav(df: pd.DataFrame) -> pd.DataFrame:
    df_nav = df.copy()
    if "PoolLength" in df_nav.columns:
        df_nav["PoolLabel"] = df_nav["PoolLength"].apply(_pool_label_from_length)
    else:
        # Colonne manquante: on crée un label vide pour éviter les KeyError
        df_nav["PoolLabel"] = None
    return df_nav


def _event_combinations(
    df_nav: pd.DataFrame,
) -> Dict[str, Dict[int, List[str]]]:
    """
    Construit les combinaisons valides Stroke -> Distance -> [PoolLabel]
    à partir des données réellement disponibles.
    """
    combos: Dict[str, Dict[int, set[str]]] = {}
    if df_nav.empty:
        return {}

    df_tmp = df_nav.dropna(subset=["Stroke", "Distance", "PoolLabel"]).copy()
    if df_tmp.empty:
        return {}

    df_tmp["Distance"] = pd.to_numeric(df_tmp["Distance"], errors="coerce")
    df_tmp = df_tmp[df_tmp["Distance"].notna()].copy()
    if df_tmp.empty:
        return {}

    for _, row in df_tmp.iterrows():
        stroke = str(row["Stroke"]).strip()
        if not stroke:
            continue
        distance = int(row["Distance"])
        pool = str(row["PoolLabel"]).strip()
        if not pool:
            continue
        combos.setdefault(stroke, {}).setdefault(distance, set()).add(pool)

    # Conversion en dictionnaire trié et listes de pools ordonnées
    ordered: Dict[str, Dict[int, List[str]]] = {}
    pool_rank = {"SCM": 0, "LCM": 1}
    for stroke in sorted(combos.keys()):
        ordered[stroke] = {}
        for distance in sorted(combos[stroke].keys()):
            pools = sorted(
                combos[stroke][distance],
                key=lambda p: (pool_rank.get(p, 99), p),
            )
            ordered[stroke][distance] = pools
    return ordered


def _build_scope_and_widgets_data(
    df_nav: pd.DataFrame,
    selected_graph: str,
    selected_stroke: Optional[str],
    selected_distance: Optional[int],
    selected_pool: Optional[str],
) -> Tuple[pd.DataFrame, Optional[str], Optional[int], Optional[str]]:
    """
    Reproduit la logique de filtrage principale de la sidebar Streamlit
    mais sans UI (purement data). Les paramètres déjà sélectionnés sont
    utilisés quand ils ne sont pas None, sinon on prend les premières
    valeurs disponibles dans df_nav.
    """
    no_filter_graphs = {
        "Nombre de performances par épreuve (LCM + SCM)",
        "Comptage par sexe (global)",
        "Camembert par sexe (global)",
        "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000",
        "Swimming Speed by Distance and Stroke Type",
        "Max Speed per Split Distance and Stroke",
        "Heatmap vitesse moyenne (distance x nage)",
    }
    pool_only_graphs = {"Nombre de performances par épreuve"}
    no_stroke_graphs = {"Distribution des temps par type de nage (boxplot)"}

    if selected_graph in no_filter_graphs:
        df_scope = df_nav.copy()
        return df_scope, None, None, None

    if selected_graph in pool_only_graphs:
        pool_options = sorted(df_nav["PoolLabel"].dropna().unique().tolist())
        if not pool_options:
            return pd.DataFrame(), None, None, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        df_scope = df_nav[df_nav["PoolLabel"] == selected_pool].copy()
        return df_scope, None, None, selected_pool

    if selected_graph in no_stroke_graphs:
        distance_options = sorted(df_nav["Distance"].dropna().unique().tolist())
        if not distance_options:
            return pd.DataFrame(), None, None, None
        if selected_distance not in distance_options:
            selected_distance = distance_options[0]
        df_distance = df_nav[df_nav["Distance"] == selected_distance].copy()
        pool_options = sorted(df_distance["PoolLabel"].dropna().unique().tolist())
        if not pool_options:
            return pd.DataFrame(), None, selected_distance, None
        if selected_pool not in pool_options:
            selected_pool = pool_options[0]
        df_scope = df_distance[df_distance["PoolLabel"] == selected_pool].copy()
        return df_scope, None, selected_distance, selected_pool

    # Par défaut : Stroke + Distance + Pool
    stroke_options = sorted(df_nav["Stroke"].dropna().unique().tolist())
    if not stroke_options:
        return pd.DataFrame(), None, None, None
    if selected_stroke not in stroke_options:
        selected_stroke = stroke_options[0]

    df_stroke = df_nav[df_nav["Stroke"] == selected_stroke].copy()
    distance_options = sorted(df_stroke["Distance"].dropna().unique().tolist())
    if not distance_options:
        return pd.DataFrame(), selected_stroke, None, None
    if selected_distance not in distance_options:
        selected_distance = distance_options[0]

    df_distance = df_stroke[df_stroke["Distance"] == selected_distance].copy()
    pool_options = sorted(df_distance["PoolLabel"].dropna().unique().tolist())
    if not pool_options:
        return pd.DataFrame(), selected_stroke, selected_distance, None
    if selected_pool not in pool_options:
        selected_pool = pool_options[0]

    df_scope = df_distance[df_distance["PoolLabel"] == selected_pool].copy()
    return df_scope, selected_stroke, selected_distance, selected_pool


def _build_histogram_figure(
    df_filtered: pd.DataFrame, mode: str, event_label: str
) -> Optional[Tuple[plt.Figure, str]]:
    if df_filtered.empty:
        return None
    swim_times = df_filtered[df_filtered["SwimTimeSeconds"] < 500]["SwimTimeSeconds"].dropna()
    if swim_times.empty:
        return None

    fig, ax = plt.subplots(figsize=(12, 8))
    if mode == "Histogramme simple":
        ax.hist(
            swim_times,
            bins=50,
            color="#004080",
            edgecolor="#004080",
            alpha=0.7,
        )
        mean_time = float(np.mean(swim_times))
        median_time = float(np.median(swim_times))
        ax.axvline(
            mean_time,
            color="red",
            linestyle="dashed",
            linewidth=2,
            label=f"Moyenne: {mean_time:.2f}s",
        )
        ax.axvline(
            median_time,
            color="orange",
            linestyle="dashed",
            linewidth=2,
            label=f"Médiane: {median_time:.2f}s",
        )
        ax.legend()
        chart_title = f"Distribution des temps de nage pour {event_label} (temps < 500 s)"
        ax.set_title(chart_title, fontsize=14)
        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre de performances")
        ax.grid(axis="y", alpha=0.3)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=10))
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    elif mode == "Histogramme + densité":
        sns.histplot(
            swim_times,
            bins=30,
            kde=True,
            color="#004080",
            edgecolor="#004080",
            alpha=0.6,
            ax=ax,
        )
        chart_title = f"Distribution des temps de natation pour {event_label} avec densité"
        ax.set_title(chart_title)
        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre de performances")
        ax.set_xticks(np.arange(0, 501, 25))
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        ax.grid(axis="x", alpha=0.3)
    else:
        ax.hist(
            swim_times,
            bins=30,
            cumulative=True,
            color="#008080",
            edgecolor="black",
            alpha=0.7,
        )
        chart_title = f"Histogramme cumulatif des temps de natation pour {event_label}"
        ax.set_title(chart_title)
        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre cumulé de performances")
        ax.set_xticks(np.arange(0, 501, 25))
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    return fig, chart_title


def _build_median_vs_best(
    df_scope: pd.DataFrame, nom_event: str
) -> Optional[Tuple[plt.Figure, str]]:
    df_event = df_scope[
        (df_scope["Event"] == nom_event)
        & (df_scope["SwimTimeSeconds"].notna())
        & df_scope["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
    ].copy()
    if df_event.empty:
        return None

    df_splits = _extract_split_rows(df_event)
    df_splits = df_splits[df_splits["split_time_sec"].notna()].copy()
    if df_splits.empty:
        return None

    median_splits = (
        df_splits.groupby("split_distance", as_index=False)["split_time_sec"]
        .median()
        .sort_values("split_distance")
    )

    best_row = df_event.nsmallest(1, "SwimTimeSeconds").iloc[0]
    best_name = _primary_swimmer_name(best_row.get("swimmer")) or "Nageur inconnu"
    best_gender = best_row.get("Gender")

    best_splits = _extract_split_rows(pd.DataFrame([best_row]))
    best_splits = best_splits[best_splits["split_time_sec"].notna()].copy()
    if best_splits.empty:
        return None
    best_splits = best_splits.sort_values("split_distance")

    fig, ax = plt.subplots(figsize=(12, 7))
    sns.lineplot(
        data=median_splits,
        x="split_distance",
        y="split_time_sec",
        marker="o",
        color="#EA800F",
        label="Temps médian de tous les nageurs",
        ax=ax,
    )

    best_color = "#003E80" if best_gender == "M" else "#FF69B4"
    sns.lineplot(
        data=best_splits,
        x="split_distance",
        y="split_time_sec",
        marker="o",
        color=best_color,
        label=f"Meilleur nageur : {best_name} ({best_gender})",
        ax=ax,
    )

    max_dist = int(
        max(
            median_splits["split_distance"].max(),
            best_splits["split_distance"].max(),
        )
    )
    ax.set_xticks(list(range(50, max_dist + 50, 50)))
    ax.set_xlabel("Distance par split (m)")
    ax.set_ylabel("Temps (s)")
    ax.set_title(f"Temps médian vs meilleur nageur - Event {nom_event}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    return fig, f"Temps médian vs meilleur nageur - Event {nom_event}"


def _build_median_vs_top10(
    df_scope: pd.DataFrame, nom_event: str
) -> Optional[Tuple[plt.Figure, str]]:
    df_event = df_scope[
        (df_scope["Event"] == nom_event)
        & (df_scope["SwimTimeSeconds"].notna())
        & df_scope["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
    ].copy()
    if df_event.empty:
        return None

    df_splits = _extract_split_rows(df_event)
    df_splits = df_splits[df_splits["split_time_sec"].notna()].copy()
    if df_splits.empty:
        return None

    median_splits = (
        df_splits.groupby("split_distance", as_index=False)["split_time_sec"]
        .median()
        .sort_values("split_distance")
    )

    df_top10 = df_event.nsmallest(10, "SwimTimeSeconds").copy()
    top10_splits = _extract_split_rows(df_top10)
    top10_splits = top10_splits[top10_splits["split_time_sec"].notna()].copy()
    if top10_splits.empty:
        return None

    top10_median = (
        top10_splits.groupby("split_distance", as_index=False)["split_time_sec"]
        .median()
        .sort_values("split_distance")
    )

    fig, ax = plt.subplots(figsize=(12, 7))
    sns.lineplot(
        data=median_splits,
        x="split_distance",
        y="split_time_sec",
        marker="o",
        color="#EA800F",
        label="Temps médian de tous les nageurs",
        ax=ax,
    )
    sns.lineplot(
        data=top10_median,
        x="split_distance",
        y="split_time_sec",
        marker="o",
        color="#003E80",
        label="Temps médian des 10 meilleurs nageurs",
        ax=ax,
    )

    max_dist = int(
        max(
            median_splits["split_distance"].max(),
            top10_median["split_distance"].max(),
        )
    )
    ax.set_xticks(list(range(50, max_dist + 50, 50)))
    ax.set_xlabel("Distance par split (m)")
    ax.set_ylabel("Temps (s)")
    ax.set_title(f"Temps médian vs Top 10 nageurs - Event {nom_event}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    return fig, f"Temps médian vs Top 10 nageurs - Event {nom_event}"


def _build_median_speed_by_gender(
    df_scope: pd.DataFrame, nom_event: str
) -> Optional[Tuple[plt.Figure, str]]:
    df_event = df_scope[
        (df_scope["Event"] == nom_event)
        & df_scope["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
    ].copy()
    if df_event.empty:
        return None

    df_splits = _extract_split_rows(df_event)
    df_splits = df_splits[
        df_splits["split_speed"].notna() & df_splits["Gender"].isin(["F", "M"])
    ].copy()
    if df_splits.empty:
        return None

    df_med = (
        df_splits.groupby(["Gender", "split_distance"], as_index=False)["split_speed"]
        .median()
        .sort_values(["Gender", "split_distance"])
    )

    fig, ax = plt.subplots(figsize=(12, 7))
    sns.lineplot(
        data=df_med,
        x="split_distance",
        y="split_speed",
        hue="Gender",
        marker="o",
        palette={"F": "#F585BD", "M": "#0B4F94"},
        linewidth=2.5,
        ax=ax,
    )

    max_dist = int(df_splits["split_distance"].max())
    ax.set_xticks(list(range(50, max_dist + 50, 50)))
    ax.set_xlabel("Distance par splits (m)")
    ax.set_ylabel("Vitesse médiane (m/s)")
    ax.set_title(f"Vitesse médiane par split selon le genre - {nom_event}")
    ax.grid(True, alpha=0.3)
    ax.legend(title="Genre")
    plt.tight_layout()
    return fig, f"Vitesse médiane par split selon le genre - {nom_event}"


def _build_heatmap_speed(
    df_scope: pd.DataFrame, nageur_cible: str
) -> Optional[Tuple[plt.Figure, str]]:
    if not nageur_cible:
        return None

    df_cmp = df_scope.copy().explode("swimmer")
    df_cmp = df_cmp[df_cmp["swimmer"].apply(lambda x: isinstance(x, dict))].copy()
    df_cmp["Nageur"] = df_cmp["swimmer"].apply(lambda x: x.get("Name"))
    df_cmp["Nageur_norm"] = df_cmp["Nageur"].map(_normalize_text)
    df_cmp["Speed"] = pd.to_numeric(df_cmp["Speed"], errors="coerce")
    df_cmp["Distance"] = pd.to_numeric(df_cmp["Distance"], errors="coerce")
    df_cmp["Stroke"] = df_cmp["Stroke"].astype(str).str.strip()
    df_cmp = df_cmp[
        df_cmp["Speed"].notna()
        & df_cmp["Distance"].notna()
        & df_cmp["Stroke"].notna()
        & (df_cmp["Stroke"] != "")
    ].copy()
    if df_cmp.empty:
        return None

    nageur_norm = _normalize_text(nageur_cible)
    df_cmp["Groupe"] = df_cmp["Nageur_norm"].apply(
        lambda name: "Nageur cible" if nageur_norm in name else "Autres nageurs"
    )
    if (df_cmp["Groupe"] == "Nageur cible").sum() == 0:
        return None

    pivot_target = df_cmp[df_cmp["Groupe"] == "Nageur cible"].pivot_table(
        values="Speed", index="Distance", columns="Stroke", aggfunc="mean"
    )
    pivot_others = df_cmp[df_cmp["Groupe"] == "Autres nageurs"].pivot_table(
        values="Speed", index="Distance", columns="Stroke", aggfunc="mean"
    )

    all_idx = sorted(set(pivot_target.index).union(set(pivot_others.index)))
    all_cols = sorted(set(pivot_target.columns).union(set(pivot_others.columns)))
    pivot_target = pivot_target.reindex(index=all_idx, columns=all_cols)
    pivot_others = pivot_others.reindex(index=all_idx, columns=all_cols)

    valid_mins: List[float] = []
    valid_maxs: List[float] = []
    for pivot in (pivot_target, pivot_others):
        if not pivot.empty:
            pivot_min = pivot.min().min(skipna=True)
            pivot_max = pivot.max().max(skipna=True)
            if pd.notna(pivot_min):
                valid_mins.append(float(pivot_min))
            if pd.notna(pivot_max):
                valid_maxs.append(float(pivot_max))
    if not valid_mins or not valid_maxs:
        return None

    vmin = min(valid_mins)
    vmax = max(valid_maxs)

    fig, axes = plt.subplots(1, 2, figsize=(18, 7), sharey=True)

    def draw_heatmap(ax: plt.Axes, piv: pd.DataFrame, title: str, cbar: bool = False) -> None:
        if piv.empty or piv.dropna(how="all").dropna(axis=1, how="all").empty:
            ax.text(
                0.5,
                0.5,
                "Pas de donnees disponibles",
                ha="center",
                va="center",
                fontsize=12,
            )
            ax.set_title(title)
            ax.set_xlabel("Stroke")
            ax.set_ylabel("Distance")
            ax.set_xticks([])
            ax.set_yticks([])
            return

        sns.heatmap(
            piv,
            annot=True,
            fmt=".2f",
            cmap="coolwarm",
            ax=ax,
            cbar=cbar,
            vmin=vmin,
            vmax=vmax,
        )
        ax.set_title(title)
        ax.set_xlabel("Stroke")
        ax.set_ylabel("Distance")

    draw_heatmap(
        axes[0],
        pivot_target,
        f"{nageur_cible} - Vitesse moyenne",
        cbar=False,
    )
    draw_heatmap(
        axes[1],
        pivot_others,
        "Autres nageurs - Vitesse moyenne",
        cbar=True,
    )
    plt.tight_layout()
    return fig, "Heatmap vitesse moyenne (distance x nage)"


class PacingDesktopApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.page.title = "Pacing – Desktop (PyFlet)"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#020617"
        self.page.padding = 0

        self.df: pd.DataFrame = load_data()
        self.total_rows: int = int(self.df.shape[0])
        self.df_nav: pd.DataFrame = _build_df_nav(self.df)

        # Sélections courantes
        self.selected_category: str = list(GRAPH_CATEGORIES.keys())[0]
        self.selected_graph: str = GRAPH_CATEGORIES[self.selected_category][0]
        self.selected_stroke: Optional[str] = None
        self.selected_distance: Optional[int] = None
        self.selected_pool: Optional[str] = None
        self.selected_heatmap_swimmer: Optional[str] = None
        self.selected_corridor_swimmer_name: Optional[str] = None
        self.selected_corridor_swimmer_yob: Optional[int] = None
        self.selected_pacing_swimmers: List[str] = []
        self.selected_chronos_sample_size: int = 5000
        self._last_corridor_filter: Optional[Tuple[Optional[str], Optional[int], Optional[str]]] = None
        self.graph_render_registry: Dict[str, Dict[str, Any]] = {}
        self.chart_image_cache: Dict[str, str] = {}
        self.graph_definitions: List[Dict[str, str]] = build_graph_definitions()

        # Widgets Flet
        self.category_dd: ft.Dropdown
        self.graph_dd: ft.Dropdown
        self.stroke_dd: ft.Dropdown
        self.distance_dd: ft.Dropdown
        self.pool_dd: ft.Dropdown
        self.heatmap_swimmer_dd: ft.Dropdown
        self.corridor_swimmer_dd: ft.Dropdown
        self.pacing_swimmer_dd_1: ft.Dropdown
        self.pacing_swimmer_dd_2: ft.Dropdown
        self.pacing_swimmer_dd_3: ft.Dropdown
        self.chronos_sample_text: ft.Text
        self.chronos_sample_slider: ft.Slider

        self.image = ft.Image(
            src="",
            expand=True,
            fit=ft.BoxFit.CONTAIN,
            border_radius=ft.BorderRadius.all(4),
        )
        self.chart_title_text = ft.Text(
            "",
            size=16,
            weight=ft.FontWeight.BOLD,
            color="#e5e7eb",
            text_align=ft.TextAlign.CENTER,
        )
        self.row_count_text = ft.Text(
            "",
            size=12,
            color="#9ca3af",
            text_align=ft.TextAlign.CENTER,
        )
        self.status_text = ft.Text(
            "",
            size=12,
            color="#f97373",
            text_align=ft.TextAlign.CENTER,
        )
        self.loader = ft.ProgressRing(visible=False, width=32, height=32, color="#22c55e")

        if ENABLE_PERSISTENT_GRAPH_CACHE:
            self._load_graph_registry_json()

        self._build_ui()
        if ENABLE_STARTUP_WARMUP:
            self._warmup_graph_registry()
        self._update_chart()

    def _graph_method_name(self, graph_name: str) -> str:
        return f"render_{_slugify(graph_name)}"

    def _chart_id(self, category: str, graph_name: str) -> str:
        return f"{_slugify(category)}__{_slugify(graph_name)}"

    def _build_render_key(
        self,
        category: str,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Tuple[str, Dict[str, Any], str]:
        options = self._current_render_options(stroke, distance, pool)
        chart_id = self._chart_id(category, graph_name)
        render_key = (
            f"{chart_id}::"
            f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        )
        return chart_id, options, render_key

    def _current_render_options(
        self,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "stroke": stroke,
            "distance": int(distance) if distance is not None else None,
            "pool": pool,
            "heatmap_swimmer": self.selected_heatmap_swimmer,
            "corridor_swimmer_name": self.selected_corridor_swimmer_name,
            "corridor_swimmer_yob": self.selected_corridor_swimmer_yob,
            "pacing_swimmers": self.selected_pacing_swimmers[:3],
            "chronos_sample_size": int(self.selected_chronos_sample_size),
        }

    def _write_graph_registry_json(self) -> None:
        GRAPH_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        renders = list(self.graph_render_registry.values())
        if not EXPORT_IMAGE_BASE64_TO_JSON:
            renders = [
                {k: v for k, v in item.items() if k != "image_base64"}
                for item in renders
            ]
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "total_renders": len(self.graph_render_registry),
            "renders": sorted(
                renders,
                key=lambda item: (item["category"], item["name"], item["rendered_at"]),
            ),
        }
        with GRAPH_EXPORT_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load_graph_registry_json(self) -> None:
        if not GRAPH_EXPORT_PATH.exists():
            return
        try:
            with GRAPH_EXPORT_PATH.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return

        raw_renders = payload.get("renders")
        if not isinstance(raw_renders, list):
            return

        loaded_registry: Dict[str, Dict[str, Any]] = {}
        loaded_cache: Dict[str, str] = {}
        for item in raw_renders:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            name = item.get("name")
            options = item.get("options")
            if not isinstance(category, str) or not isinstance(name, str) or not isinstance(options, dict):
                continue

            chart_id = self._chart_id(category, name)
            render_key = (
                f"{chart_id}::"
                f"{json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
            )
            loaded_registry[render_key] = item
            image_base64 = item.get("image_base64")
            status = item.get("status")
            if status == "ok" and isinstance(image_base64, str) and image_base64:
                loaded_cache[render_key] = image_base64

        self.graph_render_registry = loaded_registry
        self.chart_image_cache = loaded_cache

    def _register_graph_render(
        self,
        *,
        category: str,
        graph_name: str,
        stroke: Optional[str],
        distance: Optional[int],
        pool: Optional[str],
        chart_title: str,
        status: str,
        row_count: int,
        image_base64: Optional[str],
        warmup: bool,
        error: Optional[str] = None,
    ) -> None:
        chart_id, options, render_key = self._build_render_key(
            category,
            graph_name,
            stroke,
            distance,
            pool,
        )
        self.graph_render_registry[render_key] = {
            "id": chart_id,
            "name": graph_name,
            "category": category,
            "method": self._graph_method_name(graph_name),
            "status": status,
            "chart_title": chart_title,
            "row_count": int(row_count),
            "warmup": bool(warmup),
            "error": error,
            "rendered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "options": options,
            "image_base64": image_base64,
        }
        if image_base64:
            self.chart_image_cache[render_key] = image_base64
        self._write_graph_registry_json()

    def _warmup_graph_registry(self) -> None:
        if self.df.empty:
            self._write_graph_registry_json()
            return

        saved_state = (
            self.selected_category,
            self.selected_graph,
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            self.selected_heatmap_swimmer,
            self.selected_corridor_swimmer_name,
            self.selected_corridor_swimmer_yob,
            self.selected_pacing_swimmers[:],
            self.selected_chronos_sample_size,
        )

        for category, graphs in GRAPH_CATEGORIES.items():
            self.selected_category = category
            for graph_name in graphs:
                self.selected_graph = graph_name
                self._refresh_filters_from_data(update_ui=False)
                self._update_chart(update_ui=False, warmup=True)

        (
            self.selected_category,
            self.selected_graph,
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
            self.selected_heatmap_swimmer,
            self.selected_corridor_swimmer_name,
            self.selected_corridor_swimmer_yob,
            self.selected_pacing_swimmers,
            self.selected_chronos_sample_size,
        ) = saved_state
        self._refresh_filters_from_data(update_ui=False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        if self.df.empty:
            self.page.add(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "Aucune donnée trouvée. Vérifie les JSON Extranat.",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color="#f97373",
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                )
            )
            return

        # Sidebar widgets
        dropdown_width = 420
        dropdown_menu_width = 420

        self.category_dd = ft.Dropdown(
            label="Catégorie",
            options=[ft.dropdown.Option(k) for k in GRAPH_CATEGORIES.keys()],
            value=self.selected_category,
            on_select=self._on_category_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.graph_dd = ft.Dropdown(
            label="Graphique",
            options=[ft.dropdown.Option(g) for g in GRAPH_CATEGORIES[self.selected_category]],
            value=self.selected_graph,
            on_select=self._on_graph_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.stroke_dd = ft.Dropdown(
            label="Stroke",
            options=[],
            on_select=self._on_filter_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.distance_dd = ft.Dropdown(
            label="Distance",
            options=[],
            on_select=self._on_filter_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.pool_dd = ft.Dropdown(
            label="Bassin",
            options=[],
            on_select=self._on_filter_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
        )
        self.heatmap_swimmer_dd = ft.Dropdown(
            label="Nageur cible (heatmap)",
            options=[],
            on_select=self._on_heatmap_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.corridor_swimmer_dd = ft.Dropdown(
            label="Nageur cible (couloir de perf.)",
            options=[],
            on_select=self._on_corridor_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.pacing_swimmer_dd_1 = ft.Dropdown(
            label="Nageur cible 1 (pacing)",
            options=[],
            on_select=self._on_pacing_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.pacing_swimmer_dd_2 = ft.Dropdown(
            label="Nageur cible 2 (pacing)",
            options=[],
            on_select=self._on_pacing_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.pacing_swimmer_dd_3 = ft.Dropdown(
            label="Nageur cible 3 (pacing)",
            options=[],
            on_select=self._on_pacing_swimmer_change,
            filled=True,
            menu_height=320,
            width=dropdown_width,
            menu_width=dropdown_menu_width,
            visible=False,
        )
        self.chronos_sample_text = ft.Text(
            "",
            size=12,
            color="#cbd5e1",
            visible=False,
        )
        self.chronos_sample_slider = ft.Slider(
            min=0,
            max=5000,
            value=float(self.selected_chronos_sample_size),
            round=0,
            on_change=self._on_chronos_sample_change,
            label="{value}",
            visible=False,
            width=dropdown_width,
        )

        dark_toggle = ft.IconButton(
            icon=ft.icons.Icons.LIGHT_MODE,
            icon_color="#facc15",
            tooltip="Basculer light/dark mode",
            on_click=self._toggle_theme,
        )

        sidebar = ft.Container(
            bgcolor="#020617",
            padding=16,
            expand=3,
            clip_behavior=ft.ClipBehavior.NONE,
            content=ft.Column(
                controls=[
                    ft.Row(
                        [ft.Text("Navigation", size=20, weight=ft.FontWeight.BOLD), dark_toggle],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=10),
                    self.category_dd,
                    self.graph_dd,
                    ft.Divider(),
                    self.stroke_dd,
                    self.distance_dd,
                    self.pool_dd,
                    self.pacing_swimmer_dd_1,
                    self.pacing_swimmer_dd_2,
                    self.pacing_swimmer_dd_3,
                    self.heatmap_swimmer_dd,
                    self.corridor_swimmer_dd,
                    self.chronos_sample_text,
                    self.chronos_sample_slider,
                    ft.Divider(),
                    ft.Row(
                        [self.loader],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=10,
                expand=False,
            ),
        )

        main_area = ft.Container(
            expand=7,
            padding=16,
            bgcolor="#020617",
            content=ft.Column(
                [
                    ft.Container(
                        content=self.image,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                self.chart_title_text,
                                self.row_count_text,
                                self.status_text,
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        padding=ft.padding.only(top=8),
                    ),
                ],
                expand=True,
                spacing=8,
            ),
        )

        layout = ft.Row(
            controls=[sidebar, main_area],
            expand=True,
        )
        self.page.add(layout)
        self._refresh_filters_from_data()

    # ------------------------------------------------------------------ Events
    def _toggle_theme(self, _: ft.ControlEvent) -> None:
        self.page.theme_mode = (
            ft.ThemeMode.LIGHT if self.page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        )
        self.page.update()

    def _on_category_change(self, e: ft.ControlEvent) -> None:
        self.selected_category = e.control.value
        graphs = GRAPH_CATEGORIES[self.selected_category]
        self.selected_graph = graphs[0]
        self.graph_dd.options = [ft.dropdown.Option(g) for g in graphs]
        self.graph_dd.value = self.selected_graph
        self._refresh_filters_from_data()
        self._update_chart()

    def _on_graph_change(self, e: ft.ControlEvent) -> None:
        self.selected_graph = e.control.value
        self._refresh_filters_from_data()
        self._update_chart()

    def _on_filter_change(self, _: ft.ControlEvent) -> None:
        self.selected_stroke = self.stroke_dd.value
        self.selected_distance = int(self.distance_dd.value) if self.distance_dd.value else None
        self.selected_pool = self.pool_dd.value
        # Recalcule les options dépendantes quand Stroke/Distance changent
        # pour éviter de garder une ancienne liste incohérente.
        self._refresh_filters_from_data()
        self._update_chart()

    def _on_heatmap_swimmer_change(self, e: ft.ControlEvent) -> None:
        self.selected_heatmap_swimmer = e.control.value
        self._update_chart()

    def _on_pacing_swimmer_change(self, e: ft.ControlEvent) -> None:
        selected = [
            self.pacing_swimmer_dd_1.value,
            self.pacing_swimmer_dd_2.value,
            self.pacing_swimmer_dd_3.value,
        ]
        # Nettoyage: ignore vides et doublons, conserve l'ordre
        cleaned: List[str] = []
        for s in selected:
            if s and s not in cleaned:
                cleaned.append(s)
        self.selected_pacing_swimmers = cleaned[:3]
        self._update_chart()

    def _on_chronos_sample_change(self, e: ft.ControlEvent) -> None:
        try:
            self.selected_chronos_sample_size = int(float(e.control.value or 0))
        except (TypeError, ValueError):
            self.selected_chronos_sample_size = 0
        self.chronos_sample_text.value = (
            f"Taille échantillon chronos: {self.selected_chronos_sample_size:,}".replace(
                ",", " "
            )
        )
        self.page.update()
        self._update_chart()

    def _on_corridor_swimmer_change(self, e: ft.ControlEvent) -> None:
        label = e.control.value
        name, yob = self._parse_corridor_swimmer_label(label)
        self.selected_corridor_swimmer_name = name
        self.selected_corridor_swimmer_yob = yob
        self._update_chart()

    def _parse_corridor_swimmer_label(
        self, label: Optional[str]
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Parse le format : "Name (YYYY)".
        Retourne (None, None) si format invalide.
        """
        if not label:
            return None, None
        if "(" in label and label.endswith(")"):
            name, yob_str = label.rsplit("(", 1)
            name = name.strip()
            yob_str = yob_str[:-1]
            try:
                yob = int(yob_str)
            except ValueError:
                yob = None
            return name, yob
        return None, None

    # ------------------------------------------------------------------ Data-driven filters
    @staticmethod
    def _menu_height_for_count(option_count: int) -> int:
        # 56px ~ hauteur visuelle par ligne dans ce thème/material.
        return max(72, min(320, 56 * max(1, option_count)))

    def _refresh_filters_from_data(self, update_ui: bool = True) -> None:
        """Met à jour les listes d'options des filtres en fonction du graphique choisi."""
        df_nav = self.df_nav

        no_filter_graphs = {
            "Nombre de performances par épreuve (LCM + SCM)",
            "Comptage par sexe (global)",
            "Camembert par sexe (global)",
            "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000",
            "Swimming Speed by Distance and Stroke Type",
            "Max Speed per Split Distance and Stroke",
            "Heatmap vitesse moyenne (distance x nage)",
        }
        pool_only_graphs = {"Nombre de performances par épreuve"}
        no_stroke_graphs = {"Distribution des temps par type de nage (boxplot)"}

        # Stroke / distance / pool
        df_scope, stroke, distance, pool = _build_scope_and_widgets_data(
            df_nav,
            self.selected_graph,
            self.selected_stroke,
            self.selected_distance,
            self.selected_pool,
        )

        self.selected_stroke = stroke
        self.selected_distance = distance
        self.selected_pool = pool

        # Combinaisons valides Stroke -> Distance -> Pool (issues des events existants)
        combos = _event_combinations(df_nav)

        # Stroke options
        stroke_vals = list(combos.keys())
        self.stroke_dd.options = [ft.dropdown.Option(s) for s in stroke_vals]
        self.stroke_dd.menu_height = self._menu_height_for_count(len(stroke_vals))
        if self.selected_stroke not in stroke_vals:
            self.selected_stroke = stroke_vals[0] if stroke_vals else None
        self.stroke_dd.value = self.selected_stroke

        # Distance options:
        # - graphes "no stroke": distances globales
        # - sinon: liées au stroke choisi
        if self.selected_graph in no_stroke_graphs:
            dist_vals = sorted(
                pd.to_numeric(df_nav["Distance"], errors="coerce")
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )
        else:
            dist_vals = (
                list(combos.get(self.selected_stroke, {}).keys())
                if self.selected_stroke
                else []
            )
        self.distance_dd.options = [ft.dropdown.Option(str(d)) for d in dist_vals]
        self.distance_dd.menu_height = self._menu_height_for_count(len(dist_vals))
        if self.selected_distance not in dist_vals:
            self.selected_distance = dist_vals[0] if dist_vals else None
        self.distance_dd.value = (
            str(self.selected_distance) if self.selected_distance is not None else None
        )

        # Pool options:
        # - graphe "pool only": options globales (SCM/LCM disponibles)
        # - graphes "no stroke": liées à la distance choisie (tous strokes confondus)
        # - sinon: liées au couple stroke+distance choisi
        if self.selected_graph in pool_only_graphs:
            pool_vals = sorted(df_nav["PoolLabel"].dropna().unique().tolist())
        elif self.selected_graph in no_stroke_graphs:
            if self.selected_distance is not None:
                df_dist = df_nav[
                    pd.to_numeric(df_nav["Distance"], errors="coerce")
                    == self.selected_distance
                ].copy()
                pool_vals = sorted(df_dist["PoolLabel"].dropna().unique().tolist())
            else:
                pool_vals = []
        else:
            pool_vals = (
                combos.get(self.selected_stroke, {}).get(self.selected_distance, [])
                if (self.selected_stroke and self.selected_distance is not None)
                else []
            )
        self.pool_dd.options = [
            ft.dropdown.Option(key=p, text=_pool_display_label(p)) for p in pool_vals
        ]
        self.pool_dd.menu_height = self._menu_height_for_count(len(pool_vals))
        if self.selected_pool not in pool_vals:
            self.selected_pool = pool_vals[0] if pool_vals else None
        self.pool_dd.value = self.selected_pool

        # Affichage conditionnel des filtres principaux selon le graphe
        if self.selected_graph in no_filter_graphs:
            self.stroke_dd.visible = False
            self.distance_dd.visible = False
            self.pool_dd.visible = False
        elif self.selected_graph in pool_only_graphs:
            self.stroke_dd.visible = False
            self.distance_dd.visible = False
            self.pool_dd.visible = True
        elif self.selected_graph in no_stroke_graphs:
            self.stroke_dd.visible = False
            self.distance_dd.visible = True
            self.pool_dd.visible = True
        else:
            self.stroke_dd.visible = True
            self.distance_dd.visible = True
            self.pool_dd.visible = True

        # Options spécifiques pour heatmap
        if self.selected_graph == "Heatmap vitesse moyenne (distance x nage)":
            self.heatmap_swimmer_dd.visible = True
            swimmer_options = sorted(
                {
                    name
                    for name in df_nav["swimmer"].apply(_primary_swimmer_name).tolist()
                    if name
                },
                key=lambda name: _normalize_text(name),
            )
            self.heatmap_swimmer_dd.options = [
                ft.dropdown.Option(name) for name in swimmer_options
            ]
            self.heatmap_swimmer_dd.menu_height = self._menu_height_for_count(
                len(swimmer_options)
            )
            if swimmer_options and not self.selected_heatmap_swimmer:
                self.selected_heatmap_swimmer = swimmer_options[0]
            self.heatmap_swimmer_dd.value = self.selected_heatmap_swimmer
        else:
            self.heatmap_swimmer_dd.options = []
            self.heatmap_swimmer_dd.value = None
            self.heatmap_swimmer_dd.menu_height = self._menu_height_for_count(1)
            self.heatmap_swimmer_dd.visible = False

        # Options spécifiques pour couloir de performance
        if self.selected_graph == "Couloir de performance (âge) - nageur cible":
            self.corridor_swimmer_dd.visible = True
            current_corridor_filter = (
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
            )
            if self._last_corridor_filter != current_corridor_filter:
                # Force la remise à zéro de la sélection quand les filtres changent
                # pour que la mise à jour de liste soit immédiatement visible.
                self.corridor_swimmer_dd.value = None
                self.selected_corridor_swimmer_name = None
                self.selected_corridor_swimmer_yob = None
                self._last_corridor_filter = current_corridor_filter
            nom_event = (
                f"{self.selected_distance} {self.selected_stroke} {self.selected_pool}"
                if self.selected_distance and self.selected_stroke and self.selected_pool
                else None
            )
            if nom_event:
                df_event = df_scope[df_scope["Event"] == nom_event].copy()
                df_event = df_event[
                    df_event["swimmer"].apply(
                        lambda x: isinstance(x, list) and len(x) == 1
                    )
                ].copy()
                swimmer_pairs = {
                    pair
                    for pair in df_event["swimmer"]
                    .apply(_primary_swimmer_name_and_yob)
                    .tolist()
                    if pair[0] is not None and pair[1] is not None
                }
                swimmer_pairs = sorted(
                    swimmer_pairs, key=lambda t: (str(t[0]).lower(), int(t[1]))
                )
                labels = [f"{name} ({yob})" for name, yob in swimmer_pairs]
                self.corridor_swimmer_dd.options = [
                    ft.dropdown.Option(label) for label in labels
                ]
                self.corridor_swimmer_dd.label = (
                    f"Nageur cible (couloir) — {len(labels)} disponibles"
                )
                self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(
                    len(labels)
                )
                if labels:
                    # Garde la valeur choisie si elle reste valide, sinon fallback.
                    if self.corridor_swimmer_dd.value not in labels:
                        self.corridor_swimmer_dd.value = labels[0]
                    name, yob = self._parse_corridor_swimmer_label(
                        self.corridor_swimmer_dd.value
                    )
                    self.selected_corridor_swimmer_name = name
                    self.selected_corridor_swimmer_yob = yob
            else:
                self.corridor_swimmer_dd.options = []
                self.corridor_swimmer_dd.value = None
                self.corridor_swimmer_dd.label = "Nageur cible (couloir) — 0 disponible"
                self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(1)
                self.selected_corridor_swimmer_name = None
                self.selected_corridor_swimmer_yob = None
        else:
            self.corridor_swimmer_dd.options = []
            self.corridor_swimmer_dd.value = None
            self.corridor_swimmer_dd.label = "Nageur cible (couloir de perf.)"
            self.corridor_swimmer_dd.menu_height = self._menu_height_for_count(1)
            self.corridor_swimmer_dd.visible = False
            self.selected_corridor_swimmer_name = None
            self.selected_corridor_swimmer_yob = None

        # Option spécifique pacing comparatif (nageur cible)
        if self.selected_graph == "Split speed - F vs M + nageurs cibles":
            swimmer_options = sorted(
                {
                    n
                    for n in df_scope["swimmer"].apply(_primary_swimmer_name).tolist()
                    if n
                },
                key=lambda x: _normalize_text(x),
            )
            options = [ft.dropdown.Option(key="", text="(aucun)")] + [
                ft.dropdown.Option(name) for name in swimmer_options
            ]
            for dd in [self.pacing_swimmer_dd_1, self.pacing_swimmer_dd_2, self.pacing_swimmer_dd_3]:
                dd.options = options
                dd.menu_height = self._menu_height_for_count(len(options))
                dd.visible = True

            # Valeurs initiales par défaut: 3 premiers nageurs dispo
            default_vals = swimmer_options[:3]
            while len(default_vals) < 3:
                default_vals.append("")

            current = self.selected_pacing_swimmers[:]
            while len(current) < 3:
                current.append("")
            # Si une valeur n'existe plus, retombe sur défaut
            for i in range(3):
                if current[i] and current[i] not in swimmer_options:
                    current[i] = default_vals[i]
            if not any(current) and swimmer_options:
                current = default_vals

            self.pacing_swimmer_dd_1.value = current[0]
            self.pacing_swimmer_dd_2.value = current[1]
            self.pacing_swimmer_dd_3.value = current[2]

            cleaned: List[str] = []
            for s in current:
                if s and s not in cleaned:
                    cleaned.append(s)
            self.selected_pacing_swimmers = cleaned[:3]
        else:
            for dd in [self.pacing_swimmer_dd_1, self.pacing_swimmer_dd_2, self.pacing_swimmer_dd_3]:
                dd.options = []
                dd.value = None
                dd.menu_height = self._menu_height_for_count(1)
                dd.visible = False
            self.selected_pacing_swimmers = []

        # Option spécifique Chronos dans le temps (taille échantillon)
        if self.selected_graph == "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000":
            df_plot_max = self.df.copy()
            df_plot_max["SwimDate"] = pd.to_datetime(df_plot_max["SwimDate"], errors="coerce")
            df_plot_max = df_plot_max[
                (df_plot_max["SwimDate"].notna())
                & (df_plot_max["SwimTimeSeconds"].notna())
                & (df_plot_max["SwimDate"].dt.year >= 2000)
            ].copy()
            max_count = int(len(df_plot_max))
            if max_count < 0:
                max_count = 0
            if self.selected_chronos_sample_size > max_count:
                self.selected_chronos_sample_size = max_count
            if self.selected_chronos_sample_size < 0:
                self.selected_chronos_sample_size = 0
            self.chronos_sample_slider.min = 0
            self.chronos_sample_slider.max = float(max_count)
            self.chronos_sample_slider.value = float(self.selected_chronos_sample_size)
            self.chronos_sample_text.value = (
                f"Taille échantillon chronos: {self.selected_chronos_sample_size:,} / {max_count:,}".replace(
                    ",", " "
                )
            )
            self.chronos_sample_text.visible = True
            self.chronos_sample_slider.visible = True
        else:
            self.chronos_sample_text.visible = False
            self.chronos_sample_slider.visible = False

        # Catégorie / Graphique
        self.category_dd.menu_height = self._menu_height_for_count(len(self.category_dd.options))
        self.graph_dd.menu_height = self._menu_height_for_count(len(self.graph_dd.options))

        if update_ui:
            self.page.update()

    # ------------------------------------------------------------------ Chart rendering
    def _update_chart(self, update_ui: bool = True, warmup: bool = False) -> None:
        if update_ui:
            self.loader.visible = True
            self.status_text.value = ""
            self.page.update()

        try:
            df_scope, stroke, distance, pool = _build_scope_and_widgets_data(
                self.df_nav,
                self.selected_graph,
                self.selected_stroke,
                self.selected_distance,
                self.selected_pool,
            )
            _, _, render_key = self._build_render_key(
                self.selected_category,
                self.selected_graph,
                stroke,
                distance,
                pool,
            )
            cached = self.graph_render_registry.get(render_key)
            cached_image = self.chart_image_cache.get(render_key)
            if (
                cached is not None
                and cached.get("status") == "ok"
                and cached_image is not None
            ):
                if update_ui:
                    self.image.visible = True
                    self.image.src = cached_image
                    self.chart_title_text.value = str(cached.get("chart_title", self.selected_graph))
                    row_count = int(cached.get("row_count", 0))
                    self.row_count_text.value = (
                        f"Nombre de performances disponibles : {row_count:,}".replace(",", " ")
                    )
                return

            if df_scope.empty:
                if update_ui:
                    self.image.visible = False
                    self.chart_title_text.value = self.selected_graph
                    self.row_count_text.value = "Aucune donnée pour les filtres sélectionnés."
                self._register_graph_render(
                    category=self.selected_category,
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                    chart_title=self.selected_graph,
                    status="empty_scope",
                    row_count=0,
                    image_base64=None,
                    warmup=warmup,
                )
                return

            df_filtered = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
            fig: Optional[plt.Figure] = None
            chart_title = self.selected_graph

            if self.selected_graph in {
                "Histogramme simple",
                "Histogramme + densité",
                "Histogramme cumulatif",
            }:
                event_label = (
                    f"{distance} {stroke} {pool}" if distance and stroke and pool else "Événement"
                )
                res_hist = _build_histogram_figure(
                    df_filtered, self.selected_graph, event_label
                )
                if res_hist:
                    fig, chart_title = res_hist

            elif self.selected_graph == "Nombre de performances par épreuve":
                if pool:
                    chart_title = f"Nombre de performances par épreuve ({pool})"
                df_tmp = df_scope.copy()
                df_tmp["Gender"] = df_tmp["swimmer"].apply(
                    lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
                )
                df_clean = df_tmp.dropna(subset=["Gender", "Event"])
                if pool:
                    df_clean = df_clean[df_clean["Event"].str.contains(pool, na=False)]
                if not df_clean.empty:
                    df_counts = (
                        df_clean.groupby(["Event", "Gender"]).size().unstack(fill_value=0)
                    ).sort_index()
                    events = df_counts.index
                    female_counts = df_counts.get("F", [0] * len(events))
                    male_counts = df_counts.get("M", [0] * len(events))
                    x = np.arange(len(events))
                    width = 0.35
                    fig, ax = plt.subplots(figsize=(16, 6))
                    bars1 = ax.bar(
                        x - width / 2, female_counts, width, label="Femmes", color="#F585BD"
                    )
                    bars2 = ax.bar(
                        x + width / 2, male_counts, width, label="Hommes", color="#4FA2F6"
                    )
                    for bars in [bars1, bars2]:
                        for bar in bars:
                            height = bar.get_height()
                            ax.text(
                                bar.get_x() + bar.get_width() / 2,
                                height + 0.1,
                                f"{int(height)}",
                                ha="center",
                                va="bottom",
                                fontsize=9,
                            )
                    ax.set_title(chart_title, fontsize=16)
                    ax.set_xlabel("Épreuve")
                    ax.set_ylabel("Nombre de performances")
                    ax.set_xticks(x)
                    ax.set_xticklabels(events, rotation=45, ha="right")
                    ax.legend()
                    ax.grid(axis="y", linestyle="--", alpha=0.4)
                    fig.tight_layout()

            elif self.selected_graph == "Nombre de performances par épreuve (LCM + SCM)":
                chart_title = "Nombre de performances par épreuve (LCM + SCM)"
                df_tmp = df_scope.copy()
                df_tmp["Gender"] = df_tmp["swimmer"].apply(
                    lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
                )
                df_tmp["Event_clean"] = (
                    df_tmp["Event"]
                    .str.replace(" LCM", "", regex=False)
                    .str.replace(" SCM", "", regex=False)
                )
                df_clean = df_tmp.dropna(subset=["Gender", "Event_clean"])
                if not df_clean.empty:
                    df_counts = (
                        df_clean.groupby(["Event_clean", "Gender"]).size().unstack(fill_value=0)
                    )
                    df_counts["Total"] = df_counts.sum(axis=1)
                    df_counts = df_counts.sort_values("Total", ascending=False).drop(
                        columns="Total"
                    )
                    events = df_counts.index
                    female_counts = df_counts.get("F", [0] * len(events))
                    male_counts = df_counts.get("M", [0] * len(events))
                    x = np.arange(len(events))
                    width = 0.35
                    fig, ax = plt.subplots(figsize=(16, 6))
                    ax.bar(x - width / 2, female_counts, width, label="Femmes", color="#F585BD")
                    ax.bar(x + width / 2, male_counts, width, label="Hommes", color="#4FA2F6")
                    ax.set_title(chart_title, fontsize=16)
                    ax.set_xlabel("Épreuve")
                    ax.set_ylabel("Nombre de performances")
                    ax.set_xticks(x)
                    ax.set_xticklabels(events, rotation=45, ha="right")
                    ax.legend()
                    ax.grid(axis="y", linestyle="--", alpha=0.4)
                    fig.tight_layout()

            elif self.selected_graph in {"Comptage par sexe (global)", "Comptage par sexe (épreuve)"}:
                chart_title = (
                    "Nombre de performances par sexe – global"
                    if self.selected_graph == "Comptage par sexe (global)"
                    else "Nombre de performances par sexe – filtres actuels"
                )
                df_event = df_filtered.copy()
                if not df_event.empty and not df_event["Gender"].dropna().empty:
                    fig, ax = plt.subplots(figsize=(6, 4))
                    sns.countplot(
                        x="Gender",
                        data=df_event,
                        palette={"F": "#F585BD", "M": "#4FA2F6"},
                        ax=ax,
                    )
                    ax.set_xlabel("Sexe")
                    ax.set_ylabel("Nombre de performances")
                    plt.tight_layout()

            elif self.selected_graph in {"Camembert par sexe (global)", "Camembert par sexe (épreuve)"}:
                chart_title = (
                    "Répartition des performances par sexe – global"
                    if self.selected_graph == "Camembert par sexe (global)"
                    else "Répartition des performances par sexe – filtres actuels"
                )
                gender_counts = df_filtered["Gender"].value_counts()
                if not gender_counts.empty:
                    fig, ax = plt.subplots(figsize=(6, 6))
                    ax.pie(
                        gender_counts,
                        labels=[f"{g} ({n})" for g, n in zip(gender_counts.index, gender_counts)],
                        autopct="%1.1f%%",
                        colors=["#4FA2F6", "#F585BD"],
                        startangle=90,
                    )
                    plt.tight_layout()

            elif self.selected_graph == "Distribution des temps par type de nage (boxplot)":
                if self.selected_distance is not None:
                    chart_title = (
                        f"Distribution des temps par type de nage pour la distance "
                        f"{int(self.selected_distance)} m"
                    )
                df_dist = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
                if not df_dist.empty:
                    df_dist["SwimTimeMinutes"] = df_dist["SwimTimeSeconds"] / 60.0
                    fig, ax = plt.subplots(figsize=(12, 8))
                    sns.boxplot(
                        data=df_dist,
                        x="Stroke",
                        y="SwimTimeMinutes",
                        palette="Set2",
                        ax=ax,
                    )
                    ax.set_xlabel("Type de nage")
                    ax.set_ylabel("Temps (minutes)")
                    ax.set_title(chart_title)
                    plt.tight_layout()

            elif self.selected_graph == "Top 10 clubs par participation (épreuve)":
                chart_title = "Top 10 des clubs par nombre de participations – filtres actuels"
                df_event = df_scope[df_scope["Club"].notna()].copy()
                if not df_event.empty:
                    top_clubs = df_event["Club"].value_counts().nlargest(10)
                    fig, ax = plt.subplots(figsize=(12, 6))
                    sns.barplot(x=top_clubs.index, y=top_clubs.values, color="#8C5CE4", ax=ax)
                    ax.set_title(chart_title)
                    ax.set_xlabel("Club")
                    ax.set_ylabel("Nombre de participations")
                    plt.setp(ax.get_xticklabels(), rotation=90)
                    plt.tight_layout()

            elif self.selected_graph == "Temps médian des 10 meilleurs clubs":
                event_label = f"{distance} {stroke} {pool}" if distance and stroke and pool else ""
                chart_title = f"Temps médian des 10 meilleurs clubs - {event_label}"
                df_clubs = df_scope[
                    df_scope["Club"].notna() & df_scope["SwimTimeSeconds"].notna()
                ].copy()
                if not df_clubs.empty:
                    medians = (
                        df_clubs.groupby("Club")["SwimTimeSeconds"]
                        .median()
                        .sort_values()
                        .head(10)
                    )
                    if not medians.empty:
                        fig, ax = plt.subplots(figsize=(12, 6))
                        ax.plot(
                            medians.index,
                            (medians / 60.0).values,
                            color="#8C5CE4",
                            marker="o",
                            linewidth=2,
                        )
                        ax.set_xlabel("Club")
                        ax.set_ylabel("Temps médian (minutes)")
                        ax.set_title(chart_title)
                        ax.grid(alpha=0.3, linestyle="--")
                        plt.setp(ax.get_xticklabels(), rotation=90)
                        plt.tight_layout()

            elif self.selected_graph == "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000":
                chart_title = "Évolution des temps de nage dans le temps (à partir de 2000)"
                df_plot = self.df.copy()
                df_plot["SwimDate"] = pd.to_datetime(df_plot["SwimDate"], errors="coerce")
                df_plot = df_plot[
                    (df_plot["SwimDate"].notna())
                    & (df_plot["SwimTimeSeconds"].notna())
                    & (df_plot["SwimDate"].dt.year >= 2000)
                ].copy()
                if not df_plot.empty:
                    df_plot["SwimTimeMinutes"] = df_plot["SwimTimeSeconds"] / 60.0
                    sample_size = max(0, min(self.selected_chronos_sample_size, len(df_plot)))
                    if sample_size > 0:
                        df_sample = df_plot.sample(sample_size, random_state=42)
                        fig, ax = plt.subplots(figsize=(20, 6))
                        sns.lineplot(
                            x="SwimDate",
                            y="SwimTimeMinutes",
                            data=df_sample,
                            hue="Stroke",
                            alpha=0.7,
                            ax=ax,
                        )
                        ax.set_title(chart_title)
                        ax.set_xlabel("Année")
                        ax.set_ylabel("Temps de nage (minutes)")
                        ax.legend(title="Stroke")
                        plt.tight_layout()

            elif self.selected_graph == "Swimming Speed by Distance and Stroke Type":
                chart_title = "Swimming Speed by Distance and Stroke Type"
                df_speed = df_scope[df_scope["Speed"].notna()].copy()
                if not df_speed.empty:
                    speed_by_dist = (
                        df_speed.groupby(["Distance", "Stroke"])["Speed"]
                        .mean()
                        .reset_index()
                        .sort_values(["Stroke", "Distance"])
                    )
                    fig, ax = plt.subplots(figsize=(14, 8))
                    sns.lineplot(
                        data=speed_by_dist,
                        x="Distance",
                        y="Speed",
                        hue="Stroke",
                        marker="o",
                        ax=ax,
                    )
                    ax.set_title(chart_title)
                    ax.set_xlabel("Distance (m)")
                    ax.set_ylabel("Vitesse (m/s)")
                    ax.grid(alpha=0.3, linestyle="--")
                    plt.tight_layout()

            elif self.selected_graph == "Max Speed per Split Distance and Stroke":
                chart_title = "Max Speed per Split Distance and Stroke"
                df_splits = _extract_split_rows(df_scope)
                if not df_splits.empty:
                    df_splits = df_splits[df_splits["split_speed"].notna()]
                    if not df_splits.empty:
                        max_split_speed = (
                            df_splits.groupby(["split_distance", "Stroke"])["split_speed"]
                            .max()
                            .reset_index()
                            .sort_values(["Stroke", "split_distance"])
                        )
                        fig, ax = plt.subplots(figsize=(14, 8))
                        sns.scatterplot(
                            data=max_split_speed,
                            x="split_distance",
                            y="split_speed",
                            hue="Stroke",
                            style="Stroke",
                            s=90,
                            ax=ax,
                        )
                        ax.set_title(chart_title)
                        ax.set_xlabel("Split Distance (m)")
                        ax.set_ylabel("Split Speed (m/s)")
                        ax.grid(alpha=0.3, linestyle="--")
                        plt.tight_layout()

            elif self.selected_graph == "Split speed - F vs M + nageurs cibles":
                event_label = f"{distance} {stroke} {pool}" if distance and stroke and pool else ""
                chart_title = f"{event_label} - split_speed - F vs M + nageurs cibles"
                df_splits = _extract_split_rows(df_scope)
                if not df_splits.empty:
                    df_splits = df_splits[
                        df_splits["split_speed"].notna() & df_splits["Gender"].isin(["F", "M"])
                    ].copy()
                    if not df_splits.empty:
                        stats = (
                            df_splits.groupby(["Gender", "split_distance"])["split_speed"]
                            .agg(
                                mean="mean",
                                median="median",
                                q1=lambda x: x.quantile(0.25),
                                q3=lambda x: x.quantile(0.75),
                            )
                            .reset_index()
                        )
                        fig, ax = plt.subplots(figsize=(14, 8))
                        gender_colors = {"F": "#E6C6E8", "M": "#9ADBE8"}
                        for gender in ["F", "M"]:
                            d = stats[stats["Gender"] == gender].sort_values("split_distance")
                            if d.empty:
                                continue
                            color = gender_colors[gender]
                            ax.fill_between(
                                d["split_distance"],
                                d["q1"],
                                d["q3"],
                                color=color,
                                alpha=0.2,
                                label=f"IQR (Q1–Q3) — {gender}",
                            )
                            ax.plot(
                                d["split_distance"], d["median"], marker="s", linestyle="--", color=color,
                                alpha=0.9, label=f"Médiane — {gender}",
                            )
                            ax.plot(
                                d["split_distance"], d["mean"], marker="o", linestyle="-", color=color,
                                alpha=0.9, label=f"Moyenne — {gender}",
                            )
                        selected_target_swimmers = self.selected_pacing_swimmers[:3]
                        if selected_target_swimmers:
                            target_colors = sns.color_palette(
                                "Dark2", n_colors=len(selected_target_swimmers)
                            )
                            for swimmer, color in zip(selected_target_swimmers, target_colors):
                                d_sw = (
                                    df_splits[df_splits["Name"] == swimmer]
                                    .groupby(["Gender", "split_distance"])["split_speed"]
                                    .mean()
                                    .reset_index()
                                    .sort_values("split_distance")
                                )
                                if d_sw.empty:
                                    continue
                                gender = d_sw["Gender"].iloc[0]
                                ax.plot(
                                    d_sw["split_distance"],
                                    d_sw["split_speed"],
                                    marker="D",
                                    linestyle="-",
                                    linewidth=2,
                                    color=color,
                                    label=f"{swimmer} (moyenne, {gender})",
                                )
                        xticks = sorted(df_splits["split_distance"].dropna().unique().tolist())
                        ax.set_xticks(xticks)
                        ax.set_xticklabels([f"{int(x)} m" for x in xticks])
                        ax.set_xlabel("Rang du split")
                        ax.set_ylabel("Vitesse par split")
                        ax.set_title(chart_title, fontweight="bold")
                        ax.grid(alpha=0.3, linestyle="--")
                        ax.legend()
                        plt.tight_layout()

            elif self.selected_graph == "Temps médian vs meilleur nageur":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    res = _build_median_vs_best(df_scope, nom_event)
                    if res:
                        fig, chart_title = res

            elif self.selected_graph == "Temps médian vs Top 10 nageurs":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    res = _build_median_vs_top10(df_scope, nom_event)
                    if res:
                        fig, chart_title = res

            elif self.selected_graph == "Vitesse médiane par split selon le genre":
                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    res = _build_median_speed_by_gender(df_scope, nom_event)
                    if res:
                        fig, chart_title = res

            elif self.selected_graph == "Heatmap vitesse moyenne (distance x nage)":
                res = _build_heatmap_speed(df_scope, self.selected_heatmap_swimmer or "")
                if res:
                    fig, chart_title = res

            elif self.selected_graph == "Couloir de performance (âge) - nageur cible":
                if (
                    distance
                    and stroke
                    and pool
                    and self.selected_corridor_swimmer_name
                    and self.selected_corridor_swimmer_yob is not None
                ):
                    nom_event = f"{distance} {stroke} {pool}"
                    fig = _performance_corridor_plot_time(
                        df_scope,
                        nom_event=nom_event,
                        nom_nageur=self.selected_corridor_swimmer_name,
                        year_of_birth=self.selected_corridor_swimmer_yob,
                    )
                    chart_title = f"Couloir de performance - {nom_event}"

            elif self.selected_graph == "Split Speed vs Distance (Relay Events) with Mean Trend Line":
                def is_relay_swimmers(swimmers: object) -> bool:
                    return (
                        isinstance(swimmers, list)
                        and len(swimmers) > 1
                        and all(isinstance(s, dict) for s in swimmers)
                    )

                if distance and stroke and pool:
                    nom_event = f"{distance} {stroke} {pool}"
                    chart_title = (
                        f"{nom_event} — relais uniquement — split_speed en fonction de la distance"
                    )
                    df_relay = df_scope[
                        (df_scope["Event"] == nom_event)
                        & df_scope["swimmer"].apply(is_relay_swimmers)
                    ].copy()
                    if not df_relay.empty:
                        rows: list[dict] = []
                        for idx, row in df_relay.iterrows():
                            splits = row.get("splits", [])
                            if not isinstance(splits, list):
                                continue
                            for s in splits:
                                if not isinstance(s, dict):
                                    continue
                                dist = _parse_split_distance(s.get("split_distance"))
                                speed = _to_float(s.get("split_speed"))
                                if dist is None or speed is None:
                                    continue
                                rows.append(
                                    {
                                        "perf_idx": idx,
                                        "split_distance_m": dist,
                                        "split_speed": speed,
                                    }
                                )
                        df_pts = pd.DataFrame(rows)
                        if not df_pts.empty:
                            fig, ax = plt.subplots(figsize=(12, 6))
                            ax.scatter(
                                df_pts["split_distance_m"],
                                df_pts["split_speed"],
                                alpha=0.35,
                                s=28,
                                edgecolors="none",
                                label="Splits (relay)",
                            )
                            mean_by_dist = (
                                df_pts.groupby("split_distance_m", as_index=False)["split_speed"]
                                .mean()
                                .sort_values("split_distance_m")
                            )
                            ax.plot(
                                mean_by_dist["split_distance_m"],
                                mean_by_dist["split_speed"],
                                color="#DA7B27",
                                linewidth=2.7,
                                marker="o",
                                label="Moyenne par split_distance_m",
                            )
                            median_by_dist = (
                                df_pts.groupby("split_distance_m", as_index=False)["split_speed"]
                                .median()
                                .sort_values("split_distance_m")
                            )
                            ax.plot(
                                median_by_dist["split_distance_m"],
                                median_by_dist["split_speed"],
                                color="#1F77B4",
                                linewidth=2.4,
                                linestyle="--",
                                marker="s",
                                label="Médiane par split_distance_m",
                            )
                            ax.set_title(chart_title, fontsize=13, fontweight="bold")
                            ax.set_xlabel("Distance du split (m)")
                            ax.set_ylabel("split_speed")
                            ax.grid(alpha=0.25)
                            ax.legend()
                            plt.tight_layout()

            if fig is None:
                if update_ui:
                    self.image.visible = False
                    self.chart_title_text.value = chart_title
                    self.row_count_text.value = (
                        "Graphique non encore implémenté dans la version PyFlet "
                        "ou aucune donnée exploitable pour ces filtres."
                    )
                self._register_graph_render(
                    category=self.selected_category,
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                    chart_title=chart_title,
                    status="no_figure",
                    row_count=len(df_scope),
                    image_base64=None,
                    warmup=warmup,
                )
            else:
                image_base64 = _figure_to_base64(fig)
                if update_ui:
                    self.image.visible = True
                    self.image.src = image_base64
                    self.chart_title_text.value = chart_title
                    self.row_count_text.value = (
                        f"Nombre de performances disponibles : {len(df_scope):,}".replace(
                            ",", " "
                        )
                    )
                self._register_graph_render(
                    category=self.selected_category,
                    graph_name=self.selected_graph,
                    stroke=stroke,
                    distance=distance,
                    pool=pool,
                    chart_title=chart_title,
                    status="ok",
                    row_count=len(df_scope),
                    image_base64=image_base64,
                    warmup=warmup,
                )
                plt.close(fig)

        except Exception as exc:  # type: ignore[bare-except]
            if update_ui:
                self.image.visible = False
                self.chart_title_text.value = self.selected_graph
                self.row_count_text.value = ""
                self.status_text.value = f"Erreur lors de la génération du graphique: {exc}"
            self._register_graph_render(
                category=self.selected_category,
                graph_name=self.selected_graph,
                stroke=self.selected_stroke,
                distance=self.selected_distance,
                pool=self.selected_pool,
                chart_title=self.selected_graph,
                status="error",
                row_count=0,
                image_base64=None,
                warmup=warmup,
                error=str(exc),
            )
        finally:
            if update_ui:
                self.loader.visible = False
                self.page.update()


def main(page: ft.Page) -> None:
    PacingDesktopApp(page)


if __name__ == "__main__":
    ft.run(main)

