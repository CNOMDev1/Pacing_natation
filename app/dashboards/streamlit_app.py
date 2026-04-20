import json
from pathlib import Path
import unicodedata
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st
import streamlit.components.v1 as components


BASE_DIR = Path(__file__).resolve().parents[1]
EXTRANAT_OUTPUT_BASE_DIR = (
    BASE_DIR / "data" / "cleaned_data" / "extranat" / "competitions_per_type"
)

GRAPH_CATEGORIES: dict[str, list[str]] = {
    "Distributions de temps": [
        "Histogramme simple",
        "Histogramme + densité",
        "Histogramme cumulatif",
    ],
    "Effectifs et répartition par sexe": [
        "Nombre de performances par épreuve (LCM)",
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

@st.cache_data(show_spinner=True)
def load_data() -> pd.DataFrame:
    rows: list[dict] = []

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

    # Nettoyage / typage de base
    df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")

    # Colonne Gender calculée une seule fois sur l'ensemble du DataFrame
    df["Gender"] = df["swimmer"].apply(
        lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
    )

    return df


def _to_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_split_distance(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).replace(" m", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_time_to_seconds(value: object) -> float | None:
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


def _extract_split_rows(df_input: pd.DataFrame) -> pd.DataFrame:
    split_rows: list[dict] = []
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


def _primary_swimmer_name(swimmers: object) -> str | None:
    if not isinstance(swimmers, list) or len(swimmers) == 0:
        return None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None
    return first.get("Name")


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _primary_swimmer_name_and_yob(swimmers: object) -> tuple[str | None, int | None]:
    """
    Récupère (Name, Year_of_birth) du premier nageur d'une liste `swimmer`.
    Retourne (None, None) si la structure n'est pas compatible.
    """
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None, None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None, None
    name = first.get("Name")
    yob = first.get("Year_of_birth")
    yob_int: int | None = None
    try:
        if yob is not None and yob == yob:  # avoid NaN
            yob_int = int(yob)
    except (TypeError, ValueError):
        yob_int = None
    return name, yob_int


def _build_long_swims(df: pd.DataFrame, solo_only: bool = True) -> pd.DataFrame:
    """
    Reproduction de build_long_swims() du notebook :
    - garde uniquement les performances solo (swimmer list length == 1)
    - déplie les champs du dictionnaire swimmer
    - calcule Age_swim via Age si dispo, sinon SwimYear - Year_of_birth
    """
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


def _performance_corridor_plot_time(
    df: pd.DataFrame,
    nom_event: str,
    nom_nageur: str,
    year_of_birth: int,
    age_min: int = 14,
    age_max: int = 35,
    solo_only: bool = True,
    min_points: int = 5,
    figsize: tuple[int, int] = (12, 8),
):
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


def _pool_label_from_length(value: object) -> str | None:
    text = str(value).strip()
    if text in {"50", "50.0", "LCM"}:
        return "LCM"
    if text in {"25", "25.0", "SCM"}:
        return "SCM"
    return None


def _render_titles_below_chart(total_rows: int, chart_title: str) -> None:
    if chart_title == "Distribution des temps de nage":
        st.markdown(f"## {chart_title}")
    else:
        st.text(chart_title)
    st.markdown(
        f"Nombre de performances disponibles : **{total_rows:,}**".replace(",", " ")
    )


def _inject_layout_css() -> None:
    st.markdown(
        """
        <style>
        /* Masquer les 3 points et leur menu */
        button[data-testid="stMainMenuButton"] {
            display: none !important;
        }
        [data-testid="stMainMenuPopover"] {
            display: none !important;
        }

        /* Bouton collapse/expand sidebar (double arrow) en bas à gauche */
        button[data-testid="stSidebarCollapseButton"] {
            position: fixed !important;
            left: 56px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10000 !important;
        }

        /* Contrôle sidebar repliée (bouton ">>" / "«") */
        [data-testid="stSidebarCollapsedControl"] {
            position: fixed !important;
            left: 56px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10000 !important;
        }
        [data-testid="stSidebarCollapsedControl"] button {
            position: fixed !important;
            left: 56px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10001 !important;
        }

        /* Bouton expand sidebar (keyboard_double_arrow_right) en bas */
        button[data-testid="stExpandSidebarButton"] {
            position: fixed !important;
            left: 56px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10001 !important;
        }

        /* Bouton Rerun en bas à gauche */
        span.st-emotion-cache-wssdyx button[data-testid="stBaseButton-header"] {
            position: fixed !important;
            left: 64px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10000 !important;
        }

        /* Cacher le bouton Deploy */
        div[data-testid="stAppDeployButton"] {
            display: none !important;
        }

        /* Supprimer la barre horizontale du haut */
        header[data-testid="stHeader"] {
            height: 0 !important;
            min-height: 0 !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        [data-testid="stDecoration"] {
            display: none !important;
        }

        /* Réduire l'espace entre le haut et l'image */
        .block-container {
            padding-top: 0 !important;
        }
        [data-testid="stAppViewContainer"] .main .block-container {
            padding-top: 0 !important;
        }

        /* Graphique dimensionné pour être visible en entier */
        .block-container {
            min-height: 100vh !important;
            padding-bottom: 0 !important;
        }
        div[data-testid="stPyplotChart"] {
            width: 100% !important;
            height: calc(100vh - 3.5rem) !important;
            min-height: calc(100vh - 3.5rem) !important;
            max-height: calc(100vh - 3.5rem) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            margin-bottom: 0 !important;
            box-sizing: border-box !important;
        }
        div[data-testid="stPyplotChart"] > div {
            width: 100% !important;
            height: 100% !important;
            min-height: 100% !important;
            max-height: 100% !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div[data-testid="stPyplotChart"] img,
        div[data-testid="stPyplotChart"] canvas,
        div[data-testid="stPyplotChart"] svg {
            width: 100% !important;
            height: 100% !important;
            object-fit: contain !important;
        }

        /* Icône light mode à la place des 3 points */
        .custom-light-icon {
            position: fixed;
            left: 14px;
            bottom: 14px;
            z-index: 10002;
            width: 34px;
            height: 34px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.12);
            color: #f7c948;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            line-height: 1;
            user-select: none;
            pointer-events: auto;
            cursor: pointer;
            border: 1px solid rgba(255, 255, 255, 0.22);
            text-decoration: none;
        }
        .custom-light-icon.is-dark {
            color: #dfe7ff;
            background: rgba(17, 24, 39, 0.6);
            border: 1px solid rgba(223, 231, 255, 0.35);
        }

        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <button id="light-mode-toggle" class="custom-light-icon" title="Basculer light/dark mode">☀️</button>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (function() {
          const rootDoc = window.parent?.document || document;
          const btn = rootDoc.getElementById("light-mode-toggle");
          if (!btn || btn.dataset.bound === "1") return;
          btn.dataset.bound = "1";

          function applyLightMode() {
            const styleId = "forced-light-mode-style";
            let styleTag = rootDoc.getElementById(styleId);
            if (!styleTag) {
              styleTag = rootDoc.createElement("style");
              styleTag.id = styleId;
              styleTag.textContent = `
                [data-testid="stAppViewContainer"], [data-testid="stSidebar"], .stApp, body {
                  background: #ffffff !important;
                  color: #111111 !important;
                }
                [data-testid="stSidebar"] * {
                  color: #111111 !important;
                }
              `;
              rootDoc.head.appendChild(styleTag);
            }
            btn.textContent = "🌙";
            btn.classList.remove("is-dark");
            btn.title = "Passer en dark mode";
          }

          function removeLightMode() {
            const styleTag = rootDoc.getElementById("forced-light-mode-style");
            if (styleTag) styleTag.remove();
            btn.textContent = "☀️";
            btn.classList.add("is-dark");
            btn.title = "Passer en light mode";
          }

          function getMode() {
            try { return localStorage.getItem("pacing_ui_mode") || "dark"; } catch (e) { return "dark"; }
          }

          function setMode(mode) {
            try { localStorage.setItem("pacing_ui_mode", mode); } catch (e) {}
          }

          function applyMode(mode) {
            if (mode === "light") {
              applyLightMode();
            } else {
              removeLightMode();
            }
          }

          applyMode(getMode());

          btn.addEventListener("click", function(e) {
            e.preventDefault();
            const next = getMode() === "light" ? "dark" : "light";
            setMode(next);
            applyMode(next);
          });
        })();
        </script>
        """,
        height=0,
    )


def main() -> None:
    st.set_page_config(
        page_title="Pacing – Visualisations Extranat",
        layout="wide",
    )
    _inject_layout_css()

    df = load_data()
    if df.empty:
        st.error(
            f"Aucune donnée trouvée dans `{EXTRANAT_OUTPUT_BASE_DIR}`.\n\n"
            "Vérifie que les fichiers JSON existent bien."
        )
        return

    total_rows = int(df.shape[0])

    df_nav = df.copy()
    df_nav["PoolLabel"] = df_nav["PoolLength"].apply(_pool_label_from_length)
    selected_target_swimmers: list[str] = []
    selected_corridor_swimmer_name: str | None = None
    selected_corridor_swimmer_yob: int | None = None
    selected_precise_split_swimmer: str | None = None
    selected_split_year_start: int | None = None
    selected_split_year_end: int | None = None
    selected_heatmap_swimmer: str | None = None

    with st.sidebar:
        st.header("Navigation")
        selected_category = st.selectbox(
            "Catégorie",
            options=list(GRAPH_CATEGORIES.keys()),
            index=0,
        )
        selected_graph = st.selectbox(
            "Graphique",
            options=GRAPH_CATEGORIES[selected_category],
            index=0,
        )

        no_filter_graphs = {
            "Nombre de performances par épreuve (LCM + SCM)",
            "Comptage par sexe (global)",
            "Camembert par sexe (global)",
            "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000",
            "Swimming Speed by Distance and Stroke Type",
            "Max Speed per Split Distance and Stroke",
            "Heatmap vitesse moyenne (distance x nage)",
        }
        pool_only_graphs = {"Nombre de performances par épreuve (LCM)"}
        no_stroke_graphs = {"Distribution des temps par type de nage (boxplot)"}
        selected_stroke: str | None = None
        selected_distance: int | None = None

        if selected_graph in no_filter_graphs:
            df_scope = df_nav.copy()
            selected_pool = None
        elif selected_graph in pool_only_graphs:
            pool_options = sorted(df_nav["PoolLabel"].dropna().unique().tolist())
            if not pool_options:
                st.error("Aucune taille bassin disponible.")
                return
            selected_pool = st.selectbox(
                "Taille bassin",
                options=pool_options,
                index=0,
            )
            df_scope = df_nav[df_nav["PoolLabel"] == selected_pool].copy()
        elif selected_graph in no_stroke_graphs:
            distance_options = sorted(df_nav["Distance"].dropna().unique().tolist())
            if not distance_options:
                st.error("Aucune distance disponible.")
                return
            selected_distance = st.selectbox(
                "Distance",
                options=distance_options,
                index=0,
            )

            df_distance = df_nav[df_nav["Distance"] == selected_distance].copy()
            pool_options = sorted(df_distance["PoolLabel"].dropna().unique().tolist())
            if not pool_options:
                st.error("Aucune taille bassin disponible pour cette distance.")
                return
            selected_pool = st.selectbox(
                "Taille bassin",
                options=pool_options,
                index=0,
            )
            df_scope = df_distance[df_distance["PoolLabel"] == selected_pool].copy()
        else:
            stroke_options = sorted(df_nav["Stroke"].dropna().unique().tolist())
            if not stroke_options:
                st.error("Aucune valeur disponible pour le filtre Stroke.")
                return
            selected_stroke = st.selectbox(
                "Stroke",
                options=stroke_options,
                index=0,
            )

            df_stroke = df_nav[df_nav["Stroke"] == selected_stroke].copy()
            distance_options = sorted(df_stroke["Distance"].dropna().unique().tolist())
            if not distance_options:
                st.error("Aucune distance disponible pour ce stroke.")
                return
            selected_distance = st.selectbox(
                "Distance",
                options=distance_options,
                index=0,
            )

            df_distance = df_stroke[df_stroke["Distance"] == selected_distance].copy()
            pool_options = sorted(df_distance["PoolLabel"].dropna().unique().tolist())
            if not pool_options:
                st.error("Aucune taille bassin disponible pour ce stroke/distance.")
                return
            selected_pool = st.selectbox(
                "Taille bassin",
                options=pool_options,
                index=0,
            )
            df_scope = df_distance[df_distance["PoolLabel"] == selected_pool].copy()

        if selected_graph == "Couloir de performance (âge) - nageur cible":
            # Nom d'épreuve attendu dans df["Event"], ex: "50 FL LCM"
            nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
            df_event = df_scope[df_scope["Event"] == nom_event].copy()
            df_event = df_event[
                df_event["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
            ].copy()

            swimmer_pairs = {
                pair
                for pair in df_event["swimmer"].apply(_primary_swimmer_name_and_yob).tolist()
                if pair[0] is not None and pair[1] is not None
            }
            swimmer_pairs = sorted(swimmer_pairs, key=lambda t: (str(t[0]).lower(), int(t[1])))
            if not swimmer_pairs:
                st.warning("Aucun nageur cible (solo) trouvable pour cette épreuve.")
                return

            label_to_pair = {
                f"{name} ({yob})": (name, yob) for name, yob in swimmer_pairs
            }
            labels = sorted(label_to_pair.keys())
            chosen_label = st.selectbox(
                "Nageur cible",
                options=labels,
                index=0,
            )
            selected_corridor_swimmer_name, selected_corridor_swimmer_yob = label_to_pair[
                chosen_label
            ]

        if selected_graph == "Heatmap vitesse moyenne (distance x nage)":
            swimmer_options = sorted(
                {
                    name
                    for name in df_nav["swimmer"].apply(_primary_swimmer_name).tolist()
                    if name
                },
                key=lambda name: _normalize_text(name),
            )
            if not swimmer_options:
                st.warning("Aucun nageur exploitable pour cette heatmap.")
                return

            default_index = 0
            normalized_options = [_normalize_text(name) for name in swimmer_options]
            if "marchand leon" in normalized_options:
                default_index = normalized_options.index("marchand leon")

            selected_heatmap_swimmer = st.selectbox(
                "Nageur cible",
                options=swimmer_options,
                index=default_index,
            )

        if selected_graph == "Split speed - F vs M + nageurs cibles":
            swimmer_options = sorted(
                df_scope["swimmer"]
                .apply(_primary_swimmer_name)
                .dropna()
                .unique()
                .tolist()
            )
            selected_target_swimmers = st.multiselect(
                "Nageurs cibles",
                options=swimmer_options,
                default=swimmer_options[:3],
            )

        # Graphs "splits vitesse" (précis / best / top 10) : widgets dédiés
        if selected_graph == (
            "Lineplot of Speed ​​per split for a precise Swimmer and Event"
        ):
            nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
            df_event = df_scope[df_scope["Event"] == nom_event].copy()
            df_event = df_event[
                df_event["swimmer"].apply(
                    lambda x: isinstance(x, list) and len(x) == 1
                )
            ].copy()

            swimmer_options = sorted(
                df_event["swimmer"].apply(_primary_swimmer_name).dropna().unique().tolist()
            )
            if not swimmer_options:
                st.warning("Aucun nageur (solo) disponible avec splits pour cette épreuve.")
                return
            selected_precise_split_swimmer = st.selectbox(
                "Nageur",
                options=swimmer_options,
                index=0,
            )

        elif selected_graph in {
            "Lineplot of split speed for the best swimmer for a specific event",
            "Lineplot of split speed for the best swimmers for a specific event (women vs men)",
            "Line plot of Split Speed Progression of Top 10 Swimmers in a given Event (Women vs Men)",
        }:
            default_year_start, default_year_end = 2018, 2022
            if (
                selected_graph
                in {
                    "Lineplot of split speed for the best swimmer for a specific event",
                    "Lineplot of split speed for the best swimmers for a specific event (women vs men)",
                }
            ):
                default_year_start, default_year_end = 2022, 2026

            selected_split_year_start = st.number_input(
                "Année début",
                min_value=1900,
                max_value=2100,
                value=default_year_start,
                step=1,
            )
            selected_split_year_end = st.number_input(
                "Année fin",
                min_value=1900,
                max_value=2100,
                value=default_year_end,
                step=1,
            )

    if selected_graph in no_filter_graphs:
        st.sidebar.caption(
            f"Lignes disponibles (global) : {len(df_scope):,}".replace(",", " ")
        )
    else:
        st.sidebar.caption(
            f"Lignes disponibles avec ces filtres : {len(df_scope):,}".replace(",", " ")
        )

    df_filtered = df_scope.copy()
    df_filtered = df_filtered[df_filtered["SwimTimeSeconds"].notna()]
    chart_title = selected_graph

    if selected_graph in {
        "Histogramme simple",
        "Histogramme + densité",
        "Histogramme cumulatif",
    }:
        if df_filtered.empty:
            st.warning("Aucune donnée pour les filtres sélectionnés.")
            return

        swim_times = df_filtered["SwimTimeSeconds"].dropna()

        chart_title = "Distribution des temps de nage"

        fig, ax = plt.subplots(figsize=(12, 8))

        if selected_graph == "Histogramme simple":
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

        elif selected_graph == "Histogramme + densité":
            sns.histplot(
                swim_times,
                bins=30,
                kde=True,
                color="#004080",
                edgecolor="#004080",
                alpha=0.6,
                ax=ax,
            )

        else:
            ax.hist(
                swim_times,
                bins=30,
                cumulative=True,
                color="#008080",
                edgecolor="black",
                alpha=0.7,
            )

        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre de performances")
        ax.grid(axis="y", alpha=0.3)

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Nombre de performances par épreuve (LCM)":
        chart_title = f"Nombre de performances par épreuve ({selected_pool})"

        df_tmp = df_scope.copy()

        df_tmp["Gender"] = df_tmp["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )

        df_clean = df_tmp.dropna(subset=["Gender", "Event"])
        df_clean = df_clean[df_clean["Event"].str.contains(selected_pool, na=False)]

        if df_clean.empty:
            st.warning("Aucune donnée disponible pour calculer ce graphique.")
            return

        df_counts = (
            df_clean.groupby(["Event", "Gender"]).size().unstack(fill_value=0)
        )

        df_counts = df_counts.sort_index()

        events = df_counts.index
        female_counts = df_counts.get("F", [0] * len(events))
        male_counts = df_counts.get("M", [0] * len(events))

        x = np.arange(len(events))
        width = 0.35

        fig, ax = plt.subplots(figsize=(16, 6))

        bars1 = ax.bar(
            x - width / 2,
            female_counts,
            width,
            label="Femmes",
            color="#F585BD",
        )
        bars2 = ax.bar(
            x + width / 2,
            male_counts,
            width,
            label="Hommes",
            color="#4FA2F6",
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
                    fontsize=10,
                )

        ax.set_title(f"Nombre de performances par épreuve ({selected_pool})", fontsize=16)
        ax.set_xlabel("Épreuve")
        ax.set_ylabel("Nombre de performances")
        ax.set_xticks(x)
        ax.set_xticklabels(events, rotation=45, ha="right")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)

        fig.tight_layout()
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Nombre de performances par épreuve (LCM + SCM)":
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

        if df_clean.empty:
            st.warning("Aucune donnée disponible pour calculer ce graphique.")
            return

        df_counts = (
            df_clean.groupby(["Event_clean", "Gender"])
            .size()
            .unstack(fill_value=0)
        )

        df_counts["Total"] = df_counts.sum(axis=1)
        df_counts = df_counts.sort_values("Total", ascending=False).drop(
            columns="Total"
        )

        total_performances = df_counts.sum().sum()

        events = df_counts.index
        female_counts = df_counts.get("F", [0] * len(events))
        male_counts = df_counts.get("M", [0] * len(events))

        x = np.arange(len(events))
        width = 0.35

        fig, ax = plt.subplots(figsize=(16, 6))

        bars1 = ax.bar(
            x - width / 2,
            female_counts,
            width,
            label="Femmes",
            color="#F585BD",
        )
        bars2 = ax.bar(
            x + width / 2,
            male_counts,
            width,
            label="Hommes",
            color="#4FA2F6",
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
                    fontsize=10,
                )

        ax.set_title(
            "Nombre de performances par épreuve (LCM + SCM)", fontsize=16
        )
        ax.set_xlabel("Épreuve")
        ax.set_ylabel("Nombre de performances")
        ax.set_xticks(x)
        ax.set_xticklabels(events, rotation=45, ha="right")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)

        ax.text(
            0.5,
            1.08,
            f"Total des performances : {int(total_performances)}",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            fontweight="bold",
            color="#333333",
        )

        fig.tight_layout()
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Comptage par sexe (global)":
        chart_title = "Nombre de performances par sexe – global"

        gender_counts = df_filtered["Gender"].value_counts()
        if gender_counts.empty:
            st.warning("Aucune information de sexe disponible.")
            return

        fig, ax = plt.subplots(figsize=(6, 4))

        palette_colors = {"F": "#F585BD", "M": "#4FA2F6"}
        sns.countplot(
            x="Gender",
            data=df_filtered,
            palette=palette_colors,
            ax=ax,
        )

        ax.set_xlabel("Sexe")
        ax.set_ylabel("Nombre de performances")

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Comptage par sexe (épreuve)":
        chart_title = "Nombre de performances par sexe – filtres actuels"
        df_event = df_filtered.copy()
        if df_event.empty:
            st.warning(
                "Aucune donnée pour les filtres sélectionnés."
            )
            return

        gender_counts = df_event["Gender"].value_counts()

        if gender_counts.empty:
            st.warning(
                "Données disponibles pour cette épreuve, mais aucune information "
                "de sexe n'est renseignée dans les fichiers pour ces lignes."
            )
            return

        fig, ax = plt.subplots(figsize=(6, 4))

        palette_colors = {"F": "#F585BD", "M": "#4FA2F6"}
        sns.countplot(
            x="Gender",
            data=df_event,
            palette=palette_colors,
            ax=ax,
        )

        ax.set_xlabel("Sexe")
        ax.set_ylabel("Nombre de performances")

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Camembert par sexe (global)":
        chart_title = "Répartition des performances par sexe – global"

        gender_counts = df_filtered["Gender"].value_counts()
        if gender_counts.empty:
            st.warning("Aucune information de sexe disponible.")
            return

        fig, ax = plt.subplots(figsize=(6, 6))
        colors = ["#4FA2F6", "#F585BD"]

        ax.pie(
            gender_counts,
            labels=[
                f"{g} ({n})" for g, n in zip(gender_counts.index, gender_counts)
            ],
            autopct="%1.1f%%",
            colors=colors,
            startangle=90,
        )

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Camembert par sexe (épreuve)":
        chart_title = "Répartition des performances par sexe – filtres actuels"
        df_event = df_filtered.copy()
        if df_event.empty:
            st.warning(
                "Aucune donnée pour les filtres sélectionnés."
            )
            return

        gender_counts = df_event["Gender"].value_counts()

        if gender_counts.empty:
            st.warning(
                "Données disponibles pour cette épreuve, mais aucune information "
                "de sexe n'est renseignée dans les fichiers pour ces lignes."
            )
            return

        fig, ax = plt.subplots(figsize=(6, 6))
        colors = ["#4FA2F6", "#F585BD"]

        ax.pie(
            gender_counts,
            labels=[
                f"{g} ({n})" for g, n in zip(gender_counts.index, gender_counts)
            ],
            autopct="%1.1f%%",
            colors=colors,
            startangle=90,
        )

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Distribution des temps par type de nage (boxplot)":
        distance_label = (
            f"{int(selected_distance)}" if isinstance(selected_distance, (int, float, np.integer)) else str(selected_distance)
        )
        chart_title = f"Distribution des temps par type de nage pour la distance {distance_label} m"

        df_dist = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
        if df_dist.empty:
            st.warning("Aucune donnée pour cette distance.")
            return

        df_dist["SwimTimeMinutes"] = df_dist["SwimTimeSeconds"] / 60.0
        stroke_order = ["BK", "BR", "FL", "FR", "MD"]
        available_order = [s for s in stroke_order if s in df_dist["Stroke"].dropna().unique().tolist()]

        fig, ax = plt.subplots(figsize=(12, 8))
        sns.boxplot(
            data=df_dist,
            x="Stroke",
            y="SwimTimeMinutes",
            order=available_order if available_order else None,
            palette="Set2",
            ax=ax,
        )
        ax.set_xlabel("Type de nage")
        ax.set_ylabel("Temps (minutes)")
        ax.set_title(chart_title)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Top 10 clubs par participation (épreuve)":
        chart_title = "Top 10 des clubs par nombre de participations – filtres actuels"
        df_event = df_scope.copy()
        df_event = df_event[df_event["Club"].notna()]
        if df_event.empty:
            st.warning("Aucune information de club disponible pour les filtres actuels.")
            return

        top_clubs = df_event["Club"].value_counts().nlargest(10)

        fig, ax = plt.subplots(figsize=(12, 6))
        sns.barplot(x=top_clubs.index, y=top_clubs.values, color="#8C5CE4", ax=ax)

        ax.set_title(
            "Top 10 des clubs par nombre de participations - filtres actuels"
        )
        ax.set_xlabel("Club")
        ax.set_ylabel("Nombre de participations")
        plt.setp(ax.get_xticklabels(), rotation=90)

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Temps médian des 10 meilleurs clubs":
        event_label = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Temps médian des 10 meilleurs clubs - {event_label}"

        df_clubs = df_scope[
            df_scope["Club"].notna() & df_scope["SwimTimeSeconds"].notna()
        ].copy()
        if df_clubs.empty:
            st.warning("Aucune information de club ou de temps disponible.")
            return

        medians = (
            df_clubs.groupby("Club")["SwimTimeSeconds"]
            .median()
            .sort_values()
            .head(10)
        )

        if medians.empty:
            st.warning("Aucun club exploitable pour ce calcul.")
            return

        medians_minutes = medians / 60.0
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(
            medians_minutes.index,
            medians_minutes.values,
            color="#8C5CE4",
            marker="o",
            linewidth=2,
        )
        ax.set_xlabel("Club")
        ax.set_ylabel("Temps médian (minutes)")
        ax.set_title(chart_title)
        ax.grid(alpha=0.3, linestyle="--")
        plt.setp(ax.get_xticklabels(), rotation=90)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000":
        chart_title = "Évolution des temps de nage dans le temps (à partir de 2000)"

        df_plot = df.copy()
        df_plot["SwimDate"] = pd.to_datetime(df_plot["SwimDate"], errors="coerce")
        df_plot = df_plot[
            (df_plot["SwimDate"].notna())
            & (df_plot["SwimTimeSeconds"].notna())
            & (df_plot["SwimDate"].dt.year >= 2000)
        ].copy()

        if df_plot.empty:
            st.warning("Aucune information de date ou de temps disponible à partir de 2000.")
            return

        df_plot["SwimTimeMinutes"] = df_plot["SwimTimeSeconds"] / 60.0
        df_sample = df_plot.sample(min(5000, len(df_plot)), random_state=42)

        fig, ax = plt.subplots(figsize=(20, 6))
        sns.lineplot(
            x="SwimDate",
            y="SwimTimeMinutes",
            data=df_sample,
            hue="Stroke",
            alpha=0.7,
            ax=ax,
        )
        ax.set_title("Évolution des temps de nage dans le temps (à partir de 2000)")
        ax.set_xlabel("Année")
        ax.set_ylabel("Temps de nage (minutes)")
        ax.legend(title="Stroke")
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Moyenne des temps par distance et type de nage":
        chart_title = "Moyenne des temps par distance et type de nage"

        df_tmp = df_scope[df_scope["SwimTimeSeconds"].notna()].copy()
        if df_tmp.empty:
            st.warning("Aucune donnée de temps disponible.")
            return

        pivot = (
            df_tmp.groupby(["Distance", "Stroke"])["SwimTimeSeconds"]
            .mean()
            .reset_index()
        )

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(
            data=pivot,
            x="Distance",
            y="SwimTimeSeconds",
            hue="Stroke",
            ax=ax,
        )
        ax.set_xlabel("Distance (m)")
        ax.set_ylabel("Temps moyen (secondes)")
        ax.set_title("Moyenne des temps (en secondes) par distance et type de nage")
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Top 10 nageurs pour une épreuve":
        chart_title = "Top 10 nageurs – filtres actuels"
        df_event = df_scope.copy()
        df_event = df_event[df_event["SwimTimeSeconds"].notna()]
        if df_event.empty:
            st.warning("Aucune donnée pour les filtres actuels.")
            return

        # Extraire le nom du nageur principal de la liste swimmer
        def get_name(swimmers: list | None) -> str | None:
            if isinstance(swimmers, list) and swimmers:
                first = swimmers[0]
                if isinstance(first, dict):
                    return first.get("Name")
            return None

        df_event["SwimmerName"] = df_event["swimmer"].apply(get_name)
        df_event = df_event[df_event["SwimmerName"].notna()]

        best_times = (
            df_event.groupby("SwimmerName")["SwimTimeSeconds"]
            .min()
            .sort_values()
            .head(10)[::-1]
        )

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(best_times.index, best_times.values, color="#4FA2F6")
        ax.set_xlabel("Meilleur temps (secondes)")
        ax.set_ylabel("Nageur")
        ax.set_title("Top 10 nageurs - filtres actuels")
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Swimming Speed by Distance and Stroke Type":
        chart_title = "Swimming Speed by Distance and Stroke Type"

        df_speed = df_scope[df_scope["Speed"].notna()].copy()
        if df_speed.empty:
            st.warning("Aucune donnée de vitesse disponible.")
            return

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
        ax.set_title("Swimming Speed by Distance and Stroke Type")
        ax.set_xlabel("Distance (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(alpha=0.3, linestyle="--")
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Max Speed per Split Distance and Stroke":
        chart_title = "Max Speed per Split Distance and Stroke"

        df_splits = _extract_split_rows(df_scope)
        if df_splits.empty:
            st.warning("Aucun split exploitable pour les filtres sélectionnés.")
            return
        df_splits = df_splits[df_splits["split_speed"].notna()]
        if df_splits.empty:
            st.warning("Aucune vitesse de split disponible.")
            return

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
        ax.set_title("Max Speed per Split Distance and Stroke")
        ax.set_xlabel("Split Distance (m)")
        ax.set_ylabel("Split Speed (m/s)")
        ax.grid(alpha=0.3, linestyle="--")
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Split speed - F vs M + nageurs cibles":
        event_label = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"{event_label} - split_speed - F vs M + nageurs cibles"
        df_splits = _extract_split_rows(df_scope)
        if df_splits.empty:
            st.warning("Aucun split exploitable pour les filtres sélectionnés.")
            return
        df_splits = df_splits[
            df_splits["split_speed"].notna() & df_splits["Gender"].isin(["F", "M"])
        ].copy()
        if df_splits.empty:
            st.warning("Aucune donnée split_speed avec sexe F/M.")
            return

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
            d = stats[stats["Gender"] == gender]
            if d.empty:
                continue
            color = gender_colors[gender]
            d = d.sort_values("split_distance")
            ax.fill_between(
                d["split_distance"],
                d["q1"],
                d["q3"],
                color=color,
                alpha=0.2,
                label=f"IQR (Q1–Q3) — {gender}",
            )
            ax.plot(
                d["split_distance"],
                d["median"],
                marker="s",
                linestyle="--",
                color=color,
                alpha=0.9,
                label=f"Médiane — {gender}",
            )
            ax.plot(
                d["split_distance"],
                d["mean"],
                marker="o",
                linestyle="-",
                color=color,
                alpha=0.9,
                label=f"Moyenne — {gender}",
            )

        if selected_target_swimmers:
            target_colors = sns.color_palette("Dark2", n_colors=len(selected_target_swimmers))
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
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Couloir de performance (âge) - nageur cible":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Couloir de performance - {nom_event}"

        if not selected_corridor_swimmer_name or selected_corridor_swimmer_yob is None:
            st.warning("Sélectionne un nageur cible valide dans la sidebar.")
            return

        fig = _performance_corridor_plot_time(
            df_scope,
            nom_event=nom_event,
            nom_nageur=selected_corridor_swimmer_name,
            year_of_birth=selected_corridor_swimmer_yob,
        )
        if fig is None:
            st.warning("Aucune donnée exploitable pour ce couloir de performance.")
            return

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Heatmap vitesse moyenne (distance x nage)":
        chart_title = "Synthèse des vitesses – heatmap comparative"
        if not selected_heatmap_swimmer:
            st.warning("Sélectionne un nageur cible.")
            return

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
            st.warning("Aucune donnée de vitesse disponible.")
            return

        nageur_norm = _normalize_text(selected_heatmap_swimmer)
        df_cmp["Groupe"] = df_cmp["Nageur_norm"].apply(
            lambda name: "Nageur cible" if nageur_norm in name else "Autres nageurs"
        )

        if (df_cmp["Groupe"] == "Nageur cible").sum() == 0:
            st.warning("Aucune ligne trouvée pour le nageur cible sélectionné.")
            return

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

        valid_mins = []
        valid_maxs = []
        for pivot in (pivot_target, pivot_others):
            if not pivot.empty:
                pivot_min = pivot.min().min(skipna=True)
                pivot_max = pivot.max().max(skipna=True)
                if pd.notna(pivot_min):
                    valid_mins.append(float(pivot_min))
                if pd.notna(pivot_max):
                    valid_maxs.append(float(pivot_max))
        if not valid_mins or not valid_maxs:
            st.warning("Aucune combinaison distance/nage disponible.")
            return

        vmin = min(valid_mins)
        vmax = max(valid_maxs)

        fig, axes = plt.subplots(1, 2, figsize=(18, 7), sharey=True)

        def draw_heatmap(
            ax: plt.Axes, piv: pd.DataFrame, title: str, cbar: bool = False
        ) -> None:
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
            f"{selected_heatmap_swimmer} - Vitesse moyenne",
            cbar=False,
        )
        draw_heatmap(
            axes[1],
            pivot_others,
            "Autres nageurs - Vitesse moyenne",
            cbar=True,
        )
        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif (
        selected_graph
        == "Lineplot of Speed ​​per split for a precise Swimmer and Event"
    ):
        if not selected_precise_split_swimmer:
            st.warning("Sélectionne un nageur (solo) pour ce graphique.")
            return

        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        df_event = df_scope[df_scope["Event"] == nom_event].copy()
        df_event = df_event[
            df_event["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        if df_event.empty:
            st.warning("Aucune donnée solo pour cette épreuve.")
            return

        df_event["SwimmerName"] = df_event["swimmer"].apply(_primary_swimmer_name)
        df_event = df_event[df_event["SwimmerName"] == selected_precise_split_swimmer]
        if df_event.empty:
            st.warning("Aucun split exploitable pour ce nageur.")
            return

        df_event_with_splits = _extract_split_rows(df_event)
        if df_event_with_splits.empty or "split_speed" not in df_event_with_splits.columns:
            st.warning("Le nageur sélectionné ne possède pas de splits exploitables.")
            return
        df_event_with_splits = df_event_with_splits[
            df_event_with_splits["split_speed"].notna()
        ].copy()
        if df_event_with_splits.empty:
            st.warning("Le nageur sélectionné ne possède pas de splits exploitables.")
            return

        best_swim_time = df_event_with_splits["SwimTimeSeconds"].dropna().min()
        if pd.notna(best_swim_time):
            df_event_with_splits = df_event_with_splits[
                df_event_with_splits["SwimTimeSeconds"] == best_swim_time
            ].copy()

        gender = (
            df_event_with_splits["Gender"].dropna().iloc[0]
            if not df_event_with_splits["Gender"].dropna().empty
            else None
        )
        color_line = (
            "#003E80" if gender == "M" else "#FF69B4" if gender == "F" else "#008080"
        )

        df_splits = (
            df_event_with_splits.groupby("split_distance", as_index=False)["split_speed"]
            .mean()
            .sort_values("split_distance")
        )
        if df_splits.empty:
            st.warning("Aucun split_speed valide pour ce nageur.")
            return

        chart_title = f"Vitesse par split pour {selected_precise_split_swimmer} - {nom_event}"
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(
            data=df_splits,
            x="split_distance",
            y="split_speed",
            marker="o",
            color=color_line,
            ci=None,
            ax=ax,
        )
        ax.set_title(chart_title)
        ax.set_xlabel("Split (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True, alpha=0.3)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif (
        selected_graph
        == "Lineplot of split speed for the best swimmer for a specific event"
    ):
        if selected_split_year_start is None or selected_split_year_end is None:
            st.warning("Sélectionne une plage d'années.")
            return

        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        df_event = df_scope[df_scope["Event"] == nom_event].copy()
        df_event = df_event[
            df_event["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        df_event = df_event[df_event["SwimTimeSeconds"].notna()].copy()
        df_event["year"] = pd.to_datetime(df_event["SwimDate"], errors="coerce").dt.year
        df_event = df_event[
            df_event["year"].between(selected_split_year_start, selected_split_year_end)
        ].copy()

        if df_event.empty:
            st.warning("Aucune donnée dans la plage d'années pour cette épreuve.")
            return

        df_event["swimmer_name"] = df_event["swimmer"].apply(_primary_swimmer_name)
        best_row = df_event.nsmallest(1, "SwimTimeSeconds").iloc[0]
        best_name = best_row.get("swimmer_name")
        best_gender = best_row.get("Gender")

        split_data = []
        for s in best_row.get("splits", []) or []:
            if not isinstance(s, dict):
                continue
            dist = _parse_split_distance(s.get("split_distance"))
            speed = _to_float(s.get("split_speed"))
            if dist is None or speed is None:
                continue
            split_data.append({"split_distance": dist, "split_speed": speed})

        df_splits = pd.DataFrame(split_data).sort_values("split_distance")
        if df_splits.empty:
            st.warning("Aucun split_speed valide pour le meilleur nageur.")
            return

        event_year = f"{selected_split_year_start}-{selected_split_year_end}"
        chart_title = (
            f"Vitesse par split pour {best_name} ({best_gender}) - "
            f"{nom_event} ({event_year})"
        )
        color_line = (
            "#003E80" if best_gender == "M" else "#FF69B4" if best_gender == "F" else "#008080"
        )

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(
            df_splits["split_distance"],
            df_splits["split_speed"],
            marker="o",
            linewidth=1.8,
            color=color_line,
        )
        ax.set_xticks(
            list(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        )
        ax.set_title(chart_title)
        ax.set_xlabel("Distance par splits (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True, alpha=0.3)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif (
        selected_graph
        == "Lineplot of split speed for the best swimmers for a specific event (women vs men)"
    ):
        if selected_split_year_start is None or selected_split_year_end is None:
            st.warning("Sélectionne une plage d'années.")
            return

        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        df_event = df_scope[df_scope["Event"] == nom_event].copy()
        df_event = df_event[
            df_event["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        df_event = df_event[df_event["SwimTimeSeconds"].notna()].copy()
        df_event["year"] = pd.to_datetime(df_event["SwimDate"], errors="coerce").dt.year
        df_event = df_event[
            df_event["year"].between(selected_split_year_start, selected_split_year_end)
        ].copy()

        if df_event.empty:
            st.warning("Aucune donnée dans la plage d'années pour cette épreuve.")
            return

        df_event["swimmer_name"] = df_event["swimmer"].apply(_primary_swimmer_name)
        df_event = df_event[
            df_event["Gender"].isin(["F", "M"]) & df_event["swimmer_name"].notna()
        ].copy()
        if df_event.empty:
            st.warning("Aucune donnée F/M exploitable pour cette épreuve.")
            return

        event_year = f"{selected_split_year_start}-{selected_split_year_end}"
        fig, ax = plt.subplots(figsize=(10, 6))
        plotted_any = False
        gender_colors = {"M": "#003E80", "F": "#FF69B4"}

        for gender in ["M", "F"]:
            df_gender = df_event[df_event["Gender"] == gender].copy()
            if df_gender.empty:
                continue

            best_row = df_gender.nsmallest(1, "SwimTimeSeconds").iloc[0]
            swimmer_name = best_row["swimmer_name"]

            split_data = []
            for s in best_row.get("splits", []) or []:
                if not isinstance(s, dict):
                    continue
                dist = _parse_split_distance(s.get("split_distance"))
                speed = _to_float(s.get("split_speed"))
                if dist is None or speed is None:
                    continue
                split_data.append({"split_distance": dist, "split_speed": speed})

            df_splits = pd.DataFrame(split_data).sort_values("split_distance")
            if df_splits.empty:
                continue

            ax.plot(
                df_splits["split_distance"],
                df_splits["split_speed"],
                marker="o" if gender == "M" else "x",
                color=gender_colors[gender],
                linewidth=1.8,
                label=f"{swimmer_name} ({gender})",
            )
            if gender == "F":
                ax.plot(
                    df_splits["split_distance"].iloc[-1],
                    df_splits["split_speed"].iloc[-1],
                    marker="*",
                    markersize=10,
                    color=gender_colors[gender],
                )
            if gender == "M":
                ax.plot(
                    df_splits["split_distance"].iloc[-1],
                    df_splits["split_speed"].iloc[-1],
                    marker="*",
                    markersize=10,
                    color=gender_colors[gender],
                )
            plotted_any = True

        if not plotted_any:
            st.warning("Aucun split_speed valide pour les meilleurs nageurs F/M.")
            return

        chart_title = (
            f"Vitesse par split pour les meilleurs nageurs - "
            f"{nom_event} ({event_year})"
        )
        ax.set_title(chart_title)
        ax.set_xlabel("Distance par splits (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True, alpha=0.3)
        ax.legend(title="Nageur (Genre)", bbox_to_anchor=(1.02, 1), loc="upper left")
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif (
        selected_graph
        == "Line plot of Split Speed Progression of Top 10 Swimmers in a given Event (Women vs Men)"
    ):
        if selected_split_year_start is None or selected_split_year_end is None:
            st.warning("Sélectionne une plage d'années.")
            return

        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        df_event = df_scope[df_scope["Event"] == nom_event].copy()
        df_event = df_event[
            df_event["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        df_event = df_event[df_event["SwimTimeSeconds"].notna()].copy()
        df_event["year"] = pd.to_datetime(df_event["SwimDate"], errors="coerce").dt.year
        df_event = df_event[
            df_event["year"].between(selected_split_year_start, selected_split_year_end)
        ].copy()

        if df_event.empty:
            st.warning("Aucune donnée dans la plage d'années pour cette épreuve.")
            return

        df_event["SwimmerName"] = df_event["swimmer"].apply(_primary_swimmer_name)
        df_event = df_event[df_event["SwimmerName"].notna()].copy()

        top10_swimmers = (
            df_event.groupby(["SwimmerName", "Gender"])["SwimTimeSeconds"]
            .min()
            .sort_values()
            .head(10)
            .reset_index()
        )

        if top10_swimmers.empty:
            st.warning("Impossible de déterminer le Top 10.")
            return

        fig, ax = plt.subplots(figsize=(12, 6))
        for _, r in top10_swimmers.iterrows():
            name = r["SwimmerName"]
            gender = r["Gender"]
            row_best = df_event[
                (df_event["SwimmerName"] == name) & (df_event["Gender"] == gender)
            ].nsmallest(1, "SwimTimeSeconds").iloc[0]

            split_data = []
            for s in row_best.get("splits", []) or []:
                if not isinstance(s, dict):
                    continue
                dist = _parse_split_distance(s.get("split_distance"))
                speed = _to_float(s.get("split_speed"))
                if dist is None or speed is None:
                    continue
                split_data.append({"split_distance": dist, "split_speed": speed})

            df_splits = pd.DataFrame(split_data).sort_values("split_distance")
            if df_splits.empty:
                continue

            label = f"{name} ({gender})"
            line_color = "#003E80" if gender == "M" else "#FF69B4" if gender == "F" else None
            ax.plot(
                df_splits["split_distance"],
                df_splits["split_speed"],
                marker="o",
                linewidth=1.8,
                label=label,
                color=line_color,
            )

        event_year = f"{selected_split_year_start}-{selected_split_year_end}"
        chart_title = f"Vitesse par split - Top 10 nageurs uniques - {nom_event} ({event_year})"
        ax.set_title(chart_title)
        ax.set_xlabel("Distance par splits (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True, alpha=0.25)
        plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left", borderaxespad=0)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)

    elif selected_graph == "Vitesse moyenne par split":
        chart_title = "Évolution de la vitesse par splits"
        df_splits = _extract_split_rows(df_scope)
        if df_splits.empty:
            st.warning("Aucun split exploitable pour les filtres sélectionnés.")
            return
        df_splits = df_splits[df_splits["split_speed"].notna()]
        if df_splits.empty:
            st.warning("Aucune vitesse de split disponible.")
            return
        agg = (
            df_splits.groupby("split_distance")["split_speed"]
            .mean()
            .reset_index()
            .sort_values("split_distance")
        )
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(
            data=agg, x="split_distance", y="split_speed", marker="o", ax=ax
        )
        ax.set_xlabel("Distance split (m)")
        ax.set_ylabel("Vitesse moyenne (m/s)")
        ax.set_title("Vitesse moyenne par split")
        ax.grid(alpha=0.3)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Temps médian vs meilleur nageur":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Temps médian vs meilleur nageur - Event {nom_event}"

        df_event = df_scope[
            (df_scope["Event"] == nom_event)
            & (df_scope["SwimTimeSeconds"].notna())
            & df_scope["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        if df_event.empty:
            st.warning("Aucune donnée solo exploitable pour cette épreuve.")
            return

        df_splits = _extract_split_rows(df_event)
        df_splits = df_splits[df_splits["split_time_sec"].notna()].copy()
        if df_splits.empty:
            st.warning("Aucun split_time exploitable pour cette épreuve.")
            return

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
            st.warning("Aucun split exploitable pour le meilleur nageur.")
            return
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
        ax.set_title(chart_title)
        ax.grid(True, alpha=0.3)
        ax.legend()
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Temps médian vs Top 10 nageurs":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Temps médian vs Top 10 nageurs - Event {nom_event}"

        df_event = df_scope[
            (df_scope["Event"] == nom_event)
            & (df_scope["SwimTimeSeconds"].notna())
            & df_scope["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        if df_event.empty:
            st.warning("Aucune donnée solo exploitable pour cette épreuve.")
            return

        df_splits = _extract_split_rows(df_event)
        df_splits = df_splits[df_splits["split_time_sec"].notna()].copy()
        if df_splits.empty:
            st.warning("Aucun split_time exploitable pour cette épreuve.")
            return

        median_splits = (
            df_splits.groupby("split_distance", as_index=False)["split_time_sec"]
            .median()
            .sort_values("split_distance")
        )

        df_top10 = df_event.nsmallest(10, "SwimTimeSeconds").copy()
        top10_splits = _extract_split_rows(df_top10)
        top10_splits = top10_splits[top10_splits["split_time_sec"].notna()].copy()
        if top10_splits.empty:
            st.warning("Aucun split exploitable pour le Top 10.")
            return

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
        ax.set_title(chart_title)
        ax.grid(True, alpha=0.3)
        ax.legend()
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Vitesse médiane par split selon le genre":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Vitesse médiane par split selon le genre - {nom_event}"

        df_event = df_scope[
            (df_scope["Event"] == nom_event)
            & df_scope["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1)
        ].copy()
        if df_event.empty:
            st.warning("Aucune donnée solo exploitable pour cette épreuve.")
            return

        df_splits = _extract_split_rows(df_event)
        df_splits = df_splits[
            df_splits["split_speed"].notna() & df_splits["Gender"].isin(["F", "M"])
        ].copy()
        if df_splits.empty:
            st.warning("Aucune vitesse de split exploitable avec genre F/M.")
            return

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
        ax.set_title(chart_title)
        ax.grid(True, alpha=0.3)
        ax.legend(title="Genre")
        plt.tight_layout()
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif (
        selected_graph
        == "Split Speed vs Distance (Relay Events) with Mean Trend Line"
    ):
        def parse_dist(x: object) -> int | None:
            try:
                return int(str(x).replace(" m", "").strip())
            except Exception:
                return None

        def is_relay_swimmers(swimmers: object) -> bool:
            return (
                isinstance(swimmers, list)
                and len(swimmers) > 1
                and all(isinstance(s, dict) for s in swimmers)
            )

        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = (
            f"{nom_event} — relais uniquement — split_speed en fonction de la distance"
        )

        df_relay = df_scope[
            (df_scope["Event"] == nom_event)
            & df_scope["swimmer"].apply(is_relay_swimmers)
        ].copy()

        if df_relay.empty:
            st.warning("Aucune performance relais pour cet événement.")
            return

        rows: list[dict] = []
        for idx, row in df_relay.iterrows():
            splits = row.get("splits", [])
            if not isinstance(splits, list):
                continue
            for s in splits:
                if not isinstance(s, dict):
                    continue
                dist = parse_dist(s.get("split_distance"))
                speed = s.get("split_speed")
                if dist is None or speed is None:
                    continue
                try:
                    speed_f = float(speed)
                except (TypeError, ValueError):
                    continue
                rows.append(
                    {
                        "perf_idx": idx,
                        "split_distance_m": dist,
                        "split_speed": speed_f,
                    }
                )

        df_pts = pd.DataFrame(rows)
        if df_pts.empty:
            st.warning("Aucun split relay exploitable (splits vides ou split_speed manquant).")
            return

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

        ax.set_title(
            f"{nom_event} — relais uniquement — split_speed en fonction de la distance",
            fontsize=13,
            fontweight="bold",
        )
        ax.set_xlabel("Distance du split (m)")
        ax.set_ylabel("split_speed")
        ax.grid(alpha=0.25)
        ax.legend()
        plt.tight_layout()

        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    elif selected_graph == "Couloirs de performance (rang vs temps)":
        chart_title = "Couloirs de performance – rang vs temps"
        df_lane = df_scope[
            df_scope["Rank"].notna() & df_scope["SwimTimeSeconds"].notna()
        ].copy()
        if df_lane.empty:
            st.warning("Aucune donnée de rang/temps disponible.")
            return
        df_lane["Rank"] = pd.to_numeric(df_lane["Rank"], errors="coerce")
        df_lane = df_lane[df_lane["Rank"].notna()]
        if df_lane.empty:
            st.warning("Aucun rang numérique exploitable.")
            return
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.scatterplot(
            data=df_lane,
            x="Rank",
            y="SwimTimeSeconds",
            hue="Stroke",
            alpha=0.35,
            s=30,
            ax=ax,
        )
        ax.set_xlabel("Rang")
        ax.set_ylabel("Temps (secondes)")
        ax.set_title("Relation rang / temps")
        ax.grid(alpha=0.3)
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, chart_title)
    else:
        st.info(
            "Ce graphique n'est pas encore branché dans cette app Streamlit. "
            "La catégorie est prête, mais l'implémentation reste à faire."
        )


if __name__ == "__main__":
    main()

