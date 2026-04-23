import json
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import seaborn as sns
import streamlit as st
import streamlit.components.v1 as components
from matplotlib.colors import to_hex

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.graph_service import ServiceGraphe

EXTRANAT_OUTPUT_BASE_DIR = (
    BASE_DIR / "data" / "processed" / "extranat" / "competitions_per_type"
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

    df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")

    df["Gender"] = df["swimmer"].apply(
        lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
    )

    return df


def _pool_label_from_length(value: object) -> str | None:
    text = str(value).strip()
    if text in {"50", "50.0", "LCM"}:
        return "LCM"
    if text in {"25", "25.0", "SCM"}:
        return "SCM"
    return None


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _primary_swimmer_name(swimmers: object) -> str | None:
    if not isinstance(swimmers, list) or len(swimmers) == 0:
        return None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None
    return first.get("Name")


def _primary_swimmer_name_and_yob(swimmers: object) -> tuple[str | None, int | None]:
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None, None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None, None
    name = first.get("Name")
    yob = first.get("Year_of_birth")
    yob_int: int | None = None
    try:
        if yob is not None and yob == yob:
            yob_int = int(yob)
    except (TypeError, ValueError):
        yob_int = None
    return name, yob_int


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
        button[data-testid="stMainMenuButton"] {
            display: none !important;
        }
        [data-testid="stMainMenuPopover"] {
            display: none !important;
        }

        button[data-testid="stSidebarCollapseButton"] {
            position: fixed !important;
            left: 56px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10000 !important;
        }

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

        button[data-testid="stExpandSidebarButton"] {
            position: fixed !important;
            left: 56px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10001 !important;
        }

        span.st-emotion-cache-wssdyx button[data-testid="stBaseButton-header"] {
            position: fixed !important;
            left: 64px !important;
            bottom: 12px !important;
            top: auto !important;
            right: auto !important;
            z-index: 10000 !important;
        }

        div[data-testid="stAppDeployButton"] {
            display: none !important;
        }

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

        .block-container {
            padding-top: 0 !important;
        }
        [data-testid="stAppViewContainer"] .main .block-container {
            padding-top: 0 !important;
        }

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
    svc = ServiceGraphe()

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

    def show(fig, title: str, empty: str = "Aucune donnée exploitable pour ce graphique.") -> None:
        if fig is None:
            st.warning(empty)
            return
        st.pyplot(fig, use_container_width=True)
        _render_titles_below_chart(total_rows, title)

    if selected_graph in {
        "Histogramme simple",
        "Histogramme + densité",
        "Histogramme cumulatif",
    }:
        if df_filtered.empty:
            st.warning("Aucune donnée pour les filtres sélectionnés.")
            return
        chart_title = "Distribution des temps de nage"
        if selected_graph == "Histogramme simple":
            show(svc.plot_histogramme_simple(df_filtered), chart_title)
        elif selected_graph == "Histogramme + densité":
            show(svc.plot_histogramme_densite(df_filtered), chart_title)
        else:
            show(svc.plot_histogramme_cumulatif(df_filtered), chart_title)

    elif selected_graph == "Nombre de performances par épreuve (LCM)":
        chart_title = f"Nombre de performances par épreuve ({selected_pool})"
        show(
            svc.plot_nombre_performances_par_epreuve(
                df_scope, course_type=str(selected_pool)
            ),
            chart_title,
            "Aucune donnée disponible pour calculer ce graphique.",
        )

    elif selected_graph == "Nombre de performances par épreuve (LCM + SCM)":
        chart_title = "Nombre de performances par épreuve (LCM + SCM)"
        show(
            svc.plot_nombre_performances_par_epreuve_lcm_scm(df_scope),
            chart_title,
            "Aucune donnée disponible pour calculer ce graphique.",
        )

    elif selected_graph == "Comptage par sexe (global)":
        chart_title = "Nombre de performances par sexe – global"
        show(svc.plot_nombre_performances_par_sexe(df_filtered), chart_title)

    elif selected_graph == "Camembert par sexe (global)":
        chart_title = "Répartition des performances par sexe – global"
        show(svc.plot_camembert_sexe_global(df_filtered), chart_title)

    elif selected_graph == "Camembert par sexe (épreuve)":
        chart_title = "Répartition des performances par sexe – filtres actuels"
        if df_filtered.empty:
            st.warning("Aucune donnée pour les filtres sélectionnés.")
            return
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        fig = svc.plot_camembert_sexe_par_event(df_filtered, nom_event=nom_event)
        show(fig, chart_title, "Données ou sexe manquant pour cette épreuve.")

    elif selected_graph == "Distribution des temps par type de nage (boxplot)":
        try:
            distance_label = str(int(float(selected_distance)))
        except (TypeError, ValueError):
            distance_label = str(selected_distance)
        chart_title = f"Distribution des temps par type de nage pour la distance {distance_label} m"
        show(
            svc.plot_boxplot_temps_par_nage(df_scope),
            chart_title,
            "Aucune donnée pour cette distance.",
        )

    elif selected_graph == "Top 10 clubs par participation (épreuve)":
        chart_title = "Top 10 des clubs par nombre de participations – filtres actuels"
        show(svc.plot_top10_clubs(df_scope), chart_title)

    elif selected_graph == "Temps médian des 10 meilleurs clubs":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Temps médian des 10 meilleurs clubs - {nom_event}"
        fig, _meta = svc.plot_temps_median_top10_clubs_par_event(df_scope, nom_event=nom_event)
        show(fig, chart_title, "Aucune information de club ou de temps disponible.")

    elif selected_graph == "Line Plot of Swim Times by Stroke Type Over Time for a Sample of 5000":
        chart_title = "Évolution des temps de nage dans le temps (à partir de 2000)"
        show(
            svc.plot_evolution_temps_nage(df, start_year=2000, sample_size=5000),
            chart_title,
            "Aucune information de date ou de temps disponible à partir de 2000.",
        )

    elif selected_graph == "Swimming Speed by Distance and Stroke Type":
        chart_title = "Swimming Speed by Distance and Stroke Type"
        show(
            svc.plot_swimming_speed_by_distance_and_stroke(df_scope),
            chart_title,
            "Aucune donnée de vitesse disponible.",
        )

    elif selected_graph == "Max Speed per Split Distance and Stroke":
        chart_title = "Max Speed per Split Distance and Stroke"
        fig, _dfm = svc.plot_vitesse_max_par_split_et_nage(df_scope)
        show(fig, chart_title, "Aucun split exploitable pour les filtres sélectionnés.")

    elif selected_graph == "Split speed - F vs M + nageurs cibles":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"{nom_event} - split_speed - F vs M + nageurs cibles"
        target_colors: dict[str, str] = {}
        if selected_target_swimmers:
            pal = sns.color_palette("Dark2", n_colors=len(selected_target_swimmers))
            target_colors = {
                n: to_hex(c) for n, c in zip(selected_target_swimmers, pal)
            }
        fig, _a, _b, _meta = svc.plot_split_speed_analysis_by_gender_with_targets(
            df_scope,
            nom_event=nom_event,
            swimmer_targets=list(selected_target_swimmers),
            target_colors=target_colors,
        )
        show(fig, chart_title, "Aucune donnée split_speed avec sexe F/M.")

    elif selected_graph == "Heatmap vitesse moyenne (distance x nage)":
        chart_title = "Synthèse des vitesses – heatmap comparative"
        if not selected_heatmap_swimmer:
            st.warning("Sélectionne un nageur cible.")
            return
        fig, meta = svc.plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres(
            df_scope,
            nageur_cible=selected_heatmap_swimmer,
        )
        msg = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(
            fig,
            chart_title,
            msg or "Aucune donnée exploitable pour cette heatmap.",
        )

    elif selected_graph == "Couloir de performance (âge) - nageur cible":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Couloir de performance - {nom_event}"
        if not selected_corridor_swimmer_name or selected_corridor_swimmer_yob is None:
            st.warning("Sélectionne un nageur cible valide dans la sidebar.")
            return
        fig, meta = svc.plot_performance_corridor_plot_time(
            df_scope,
            nom_event=nom_event,
            nom_nageur=selected_corridor_swimmer_name,
            year_of_birth=selected_corridor_swimmer_yob,
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucune donnée exploitable pour ce couloir de performance.")

    elif (
        selected_graph
        == "Lineplot of Speed ​​per split for a precise Swimmer and Event"
    ):
        if not selected_precise_split_swimmer:
            st.warning("Sélectionne un nageur (solo) pour ce graphique.")
            return
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = (
            f"Vitesse par split pour {selected_precise_split_swimmer} - {nom_event}"
        )
        fig, _splits, _g = svc.plot_vitesse_par_split_pour_nageur_event(
            df_scope,
            nom_nageur=selected_precise_split_swimmer,
            nom_event=nom_event,
        )
        show(fig, chart_title, "Aucun split_speed valide pour ce nageur.")

    elif (
        selected_graph
        == "Lineplot of split speed for the best swimmer for a specific event"
    ):
        if selected_split_year_start is None or selected_split_year_end is None:
            st.warning("Sélectionne une plage d'années.")
            return
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = (
            f"Vitesse par split (meilleur nageur) - {nom_event} "
            f"({selected_split_year_start}-{selected_split_year_end})"
        )
        fig, _spl, meta = svc.plot_vitesse_par_split_meilleur_nageur_event_periode(
            df_scope,
            nom_event=nom_event,
            annee_debut=int(selected_split_year_start),
            annee_fin=int(selected_split_year_end),
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucune donnée dans la plage d'années pour cette épreuve.")

    elif (
        selected_graph
        == "Lineplot of split speed for the best swimmers for a specific event (women vs men)"
    ):
        if selected_split_year_start is None or selected_split_year_end is None:
            st.warning("Sélectionne une plage d'années.")
            return
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = (
            f"Vitesse par split pour les meilleurs nageurs - "
            f"{nom_event} ({selected_split_year_start}-{selected_split_year_end})"
        )
        fig, _spl, meta = svc.plot_vitesse_par_split_top_nageurs_hf_event_periode(
            df_scope,
            nom_event=nom_event,
            annee_debut=int(selected_split_year_start),
            annee_fin=int(selected_split_year_end),
            top_n=1,
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucun split valide pour les meilleurs nageurs F/M.")

    elif (
        selected_graph
        == "Line plot of Split Speed Progression of Top 10 Swimmers in a given Event (Women vs Men)"
    ):
        if selected_split_year_start is None or selected_split_year_end is None:
            st.warning("Sélectionne une plage d'années.")
            return
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = (
            f"Vitesse par split - Top 10 nageurs uniques - "
            f"{nom_event} ({selected_split_year_start}-{selected_split_year_end})"
        )
        fig, _a, _b, meta = svc.plot_vitesse_par_split_top_nageurs_uniques_event_periode(
            df_scope,
            nom_event=nom_event,
            annee_debut=int(selected_split_year_start),
            annee_fin=int(selected_split_year_end),
            top_n=10,
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Impossible de déterminer le Top 10.")

    elif selected_graph == "Temps médian vs meilleur nageur":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Temps médian vs meilleur nageur - Event {nom_event}"
        fig, _a, _b, meta = svc.plot_temps_median_vs_meilleur_nageur_par_split_event(
            df_scope, nom_event=nom_event
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucune donnée solo ou splits exploitables.")

    elif selected_graph == "Temps médian vs Top 10 nageurs":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Temps médian vs Top 10 nageurs - Event {nom_event}"
        fig, _a, _b, meta = svc.plot_temps_median_vs_top10_nageurs_par_split_event(
            df_scope, nom_event=nom_event
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucune donnée solo ou splits exploitables.")

    elif selected_graph == "Vitesse médiane par split selon le genre":
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = f"Vitesse médiane par split selon le genre - {nom_event}"
        fig, _med, meta = svc.plot_vitesse_mediane_par_split_selon_genre_top_n_event(
            df_scope, nom_event=nom_event, top_n=10
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucune vitesse de split exploitable avec genre F/M.")

    elif (
        selected_graph
        == "Split Speed vs Distance (Relay Events) with Mean Trend Line"
    ):
        nom_event = f"{selected_distance} {selected_stroke} {selected_pool}"
        chart_title = (
            f"{nom_event} — relais uniquement — split_speed en fonction de la distance"
        )
        fig, _p, _m, _md, meta = svc.plot_relais_split_speed_par_distance(
            df_scope, nom_event=nom_event
        )
        err = str(meta.get("message", "")) if isinstance(meta, dict) else ""
        show(fig, chart_title, err or "Aucune performance relais ou splits exploitables.")

    else:
        st.info(
            "Ce graphique n'est pas encore branché dans cette app Streamlit. "
            "La catégorie est prête, mais l'implémentation reste à faire."
        )


if __name__ == "__main__":
    main()
