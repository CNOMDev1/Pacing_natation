import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st


st.set_page_config(
    page_title="Pacing – Dashboard",
    layout="wide",
)


@st.cache_data(show_spinner=True)
def load_data() -> pd.DataFrame:
    """
    Charge les données JSON et reconstruit le même DataFrame que dans graphics.ipynb.
    """
    directory = Path(
        "/Users/nouhailaimaneabbassi/Desktop/Pacing/app/data/cleaned_data/extranat/competitions_per_type"
    )

    data = []
    for file in directory.rglob("*.json"):
        with open(file, "r", encoding="utf-8") as f:
            data.append(json.load(f))

    rows = []
    for comp in data:
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

    df["SwimDate"] = pd.to_datetime(df["SwimDate"], errors="coerce")
    df["SwimTimeSeconds"] = pd.to_numeric(df["SwimTimeSeconds"], errors="coerce")
    df["Distance"] = pd.to_numeric(df["Distance"], errors="coerce")

    df["Gender"] = df["swimmer"].apply(
        lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
    )

    return df


def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filtres")

    strokes = sorted([s for s in df["Stroke"].dropna().unique()])
    selected_strokes = st.sidebar.multiselect(
        "Nage (Stroke)", options=strokes, default=strokes[:3] if strokes else None
    )

    courses = sorted([c for c in df["Course"].dropna().unique()])
    selected_courses = st.sidebar.multiselect(
        "Bassin (Course)", options=courses, default=courses
    )

    distances = sorted([int(d) for d in df["Distance"].dropna().unique()])
    selected_distances = st.sidebar.multiselect(
        "Distance (m)", options=distances, default=distances
    )

    min_date, max_date = (
        df["SwimDate"].min(),
        df["SwimDate"].max(),
    )
    if pd.notna(min_date) and pd.notna(max_date):
        start_date, end_date = st.sidebar.date_input(
            "Période",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        mask_date = (df["SwimDate"] >= pd.to_datetime(start_date)) & (
            df["SwimDate"] <= pd.to_datetime(end_date)
        )
    else:
        mask_date = True

    mask = (
        df["Stroke"].isin(selected_strokes) if selected_strokes else True
    ) & (df["Course"].isin(selected_courses) if selected_courses else True) & (
        df["Distance"].isin(selected_distances) if selected_distances else True
    ) & mask_date

    return df[mask].copy()


def plot_swimtime_distribution(df: pd.DataFrame):
    st.subheader("Distribution des temps (SwimTimeSeconds)")
    fig, ax = plt.subplots(figsize=(8, 4))
    sns.histplot(
        df["SwimTimeSeconds"].dropna(),
        bins=50,
        kde=True,
        color="#008080",
        ax=ax,
    )
    ax.set_xlabel("Temps (secondes)")
    ax.set_ylabel("Fréquence")
    st.pyplot(fig)


def plot_histogram_with_mean_median(df: pd.DataFrame):
    st.subheader("Distribution détaillée des temps (< 500 s) avec moyenne/médiane")
    swim_times = df["SwimTimeSeconds"].dropna()
    swim_times = swim_times[swim_times < 500]
    if swim_times.empty:
        st.info("Aucune donnée disponible pour cette sélection.")
        return

    from matplotlib.ticker import MaxNLocator

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(swim_times, bins=50, color="#004080", edgecolor="#004080", alpha=0.7)

    mean_time = np.mean(swim_times)
    median_time = np.median(swim_times)

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

    ax.set_title("Distribution des temps de nage (temps < 500 s)")
    ax.set_xlabel("Temps (secondes)")
    ax.set_ylabel("Nombre de performances")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    st.pyplot(fig)


def plot_boxplot_times(df: pd.DataFrame):
    st.subheader("Boxplot des temps de nage (< 500 s)")
    swim_times = df["SwimTimeSeconds"].dropna()
    swim_times = swim_times[swim_times < 500]
    if swim_times.empty:
        st.info("Aucune donnée disponible pour cette sélection.")
        return

    fig, ax = plt.subplots(figsize=(10, 4))
    sns.boxplot(x=swim_times, color="#008080", ax=ax)

    median = np.median(swim_times)
    q1 = np.percentile(swim_times, 25)
    q3 = np.percentile(swim_times, 75)
    min_val = swim_times.min()
    max_val = swim_times.max()

    ax.text(median + 2, 0.05, f"Médiane: {median:.1f}s", color="red", fontsize=9)
    ax.text(q1 - 40, 0.05, f"Q1: {q1:.1f}s", color="blue", fontsize=9)
    ax.text(q3 + 5, 0.05, f"Q3: {q3:.1f}s", color="blue", fontsize=9)
    ax.text(min_val, 0.05, f"Min: {min_val:.1f}s", color="green", fontsize=9)
    ax.text(max_val - 50, 0.05, f"Max: {max_val:.1f}s", color="green", fontsize=9)

    ax.set_title("Boxplot des temps de natation")
    ax.set_xlabel("Temps (secondes)")
    st.pyplot(fig)

def plot_cumulative_hist(df: pd.DataFrame):
    st.subheader("Histogramme cumulatif des temps de nage (< 500 s)")
    swim_times = df["SwimTimeSeconds"].dropna()
    swim_times = swim_times[swim_times < 500]
    if swim_times.empty:
        st.info("Aucune donnée disponible pour cette sélection.")
        return

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.hist(
        swim_times,
        bins=30,
        cumulative=True,
        color="#008080",
        edgecolor="black",
        alpha=0.7,
    )
    ax.set_title("Histogramme cumulatif des temps de natation")
    ax.set_xlabel("Temps (secondes)")
    ax.set_ylabel("Nombre cumulé de performances")
    ax.set_xticks(np.arange(0, 501, 25))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.grid(axis="x", alpha=0.3)
    st.pyplot(fig)


def plot_swimtime_by_stroke(df: pd.DataFrame):
    st.subheader("Temps par nage (Stroke)")
    fig, ax = plt.subplots(figsize=(8, 4))
    sns.boxplot(
        x="Stroke",
        y="SwimTimeSeconds",
        data=df.dropna(subset=["Stroke", "SwimTimeSeconds"]),
        palette="Set2",
        ax=ax,
    )
    ax.set_xlabel("Nage")
    ax.set_ylabel("Temps (secondes)")
    ax.tick_params(axis="x", rotation=45)
    st.pyplot(fig)


def plot_gender_count(df: pd.DataFrame):
    st.subheader("Répartition des performances par sexe")
    if "Gender" not in df.columns or df["Gender"].dropna().empty:
        st.info("Aucune information de genre disponible.")
        return

    gender_counts = df["Gender"].value_counts()

    # Bar chart
    fig_bar, ax_bar = plt.subplots(figsize=(6, 3))
    palette_colors = {"F": "#F585BD", "M": "#4FA2F6"}
    sns.barplot(
        x=gender_counts.index,
        y=gender_counts.values,
        palette=[palette_colors.get(g, "#999999") for g in gender_counts.index],
        ax=ax_bar,
    )
    ax_bar.set_title("Nombre de performances par sexe")
    ax_bar.set_xlabel("Sexe")
    ax_bar.set_ylabel("Nombre de performances")
    st.pyplot(fig_bar)

    # Pie chart
    fig_pie, ax_pie = plt.subplots(figsize=(6, 4))
    colors = [palette_colors.get(g, "#999999") for g in gender_counts.index]
    ax_pie.pie(
        gender_counts,
        labels=gender_counts.index,
        autopct="%1.1f%%",
        colors=colors,
        startangle=90,
    )
    ax_pie.set_title("Répartition des performances par sexe (pie chart)")
    ax_pie.axis("equal")
    st.pyplot(fig_pie)


def plot_heatmap_distance_stroke(df: pd.DataFrame):
    st.subheader("Temps moyen par distance et type de nage")
    pivot = df.pivot_table(
        values="SwimTimeSeconds",
        index="Distance",
        columns="Stroke",
        aggfunc="mean",
    )
    if pivot.empty:
        st.info("Pas de données suffisantes pour la heatmap.")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    sns.heatmap(pivot, annot=True, fmt=".1f", cmap="coolwarm_r", ax=ax)
    ax.set_title("Moyenne des temps (s) par distance et type de nage")
    ax.set_xlabel("Type de nage")
    ax.set_ylabel("Distance (m)")
    st.pyplot(fig)


def plot_time_over_date(df: pd.DataFrame):
    st.subheader("Évolution des temps dans le temps (échantillon)")
    df_sample = df.dropna(subset=["SwimTimeSeconds", "SwimDate"])
    if df_sample.empty:
        st.info("Aucune donnée datée disponible.")
        return
    df_sample = df_sample.sample(min(5000, len(df_sample)), random_state=42)

    fig, ax = plt.subplots(figsize=(12, 5))
    sns.lineplot(
        x="SwimDate",
        y="SwimTimeSeconds",
        data=df_sample,
        hue="Stroke",
        alpha=0.7,
        ax=ax,
        legend=True,
    )
    ax.set_title(
        "Évolution des temps de nage dans le temps (échantillon de performances)"
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("Temps de nage (s)")
    ax.legend(title="Stroke", bbox_to_anchor=(1.02, 1), loc="upper left")
    st.pyplot(fig)


def plot_top_clubs(df: pd.DataFrame, top_n: int = 20):
    st.subheader(f"Top {top_n} clubs par points")
    club_points = (
        df.groupby("Club")["points"]
        .sum(min_count=1)
        .sort_values(ascending=False)
        .head(top_n)
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.barplot(
        x=club_points.index,
        y=club_points.values,
        color="#8C5CE4",
        ax=ax,
    )
    ax.set_xlabel("Club")
    ax.set_ylabel("Somme des points")
    ax.tick_params(axis="x", rotation=60)
    plt.setp(ax.get_xticklabels(), ha="right")
    st.pyplot(fig)


def plot_mean_time_top10_clubs(df: pd.DataFrame):
    st.subheader("Temps moyen des 10 meilleurs clubs")
    df_time = df[df["SwimTimeSeconds"].notna()]
    if df_time.empty:
        st.info("Aucune performance avec temps disponible.")
        return

    mean_time_club = (
        df_time.groupby("Club")["SwimTimeSeconds"].mean().reset_index()
    )
    mean_time_club = mean_time_club.sort_values("SwimTimeSeconds")
    top10 = mean_time_club.head(10)

    fig, ax = plt.subplots(figsize=(12, 5))
    sns.lineplot(
        data=top10,
        x="Club",
        y="SwimTimeSeconds",
        marker="o",
        color="#8C5CE4",
        ax=ax,
    )
    ax.set_title("Temps moyen des 10 meilleurs clubs")
    ax.set_xlabel("Club")
    ax.set_ylabel("Temps moyen (secondes)")
    ax.tick_params(axis="x", rotation=90)
    ax.grid(True, linestyle="--", alpha=0.5)
    st.pyplot(fig)


def plot_speed_by_distance_stroke(df: pd.DataFrame):
    st.subheader("Vitesse de nage par distance et type de nage")
    df_speed = df[df["Speed"].notna()]
    if df_speed.empty:
        st.info("Aucune donnée de vitesse disponible.")
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.lineplot(
        x="Distance",
        y="Speed",
        hue="Stroke",
        data=df_speed,
        errorbar=None,
        ax=ax,
    )
    if df_speed["Distance"].notna().any():
        max_distance = int(df_speed["Distance"].max())
        ax.set_xticks(np.arange(0, max_distance + 50, 50))
    ax.set_title("Swimming Speed by Distance and Stroke Type")
    ax.set_xlabel("Distance (m)")
    ax.set_ylabel("Speed (m/s)")
    ax.grid(True, linestyle="--", alpha=0.5)
    st.pyplot(fig)


def plot_single_split_speed(df: pd.DataFrame):
    st.subheader("Vitesse par split pour un nageur et un event")

    df_with_splits = df[df["splits"].apply(lambda x: isinstance(x, list) and len(x) > 0)]
    if df_with_splits.empty:
        st.info("Aucune performance avec splits disponibles.")
        return

    # 1) Sélection de l'Event
    events = sorted(df_with_splits["Event"].dropna().unique())
    if not events:
        st.info("Aucun event disponible.")
        return

    selected_event = st.selectbox("Choisir un Event", options=events)
    df_event = df_with_splits[df_with_splits["Event"] == selected_event]
    if df_event.empty:
        st.info("Aucune performance avec splits pour cet event.")
        return

    # 2) Extraire le nom du nageur principal (premier de la liste)
    df_event = df_event.copy()
    df_event["SwimmerName"] = df_event["swimmer"].apply(
        lambda x: x[0].get("Name") if isinstance(x, list) and len(x) > 0 else None
    )

    swimmer_names = sorted(df_event["SwimmerName"].dropna().unique())
    if not swimmer_names:
        st.info("Aucun nageur avec nom disponible pour cet event.")
        return

    selected_swimmer = st.selectbox("Choisir un nageur", options=swimmer_names)

    df_swimmer = df_event[df_event["SwimmerName"] == selected_swimmer]
    if df_swimmer.empty:
        st.info("Aucune performance pour ce nageur dans cet event.")
        return

    # On prend la meilleure performance (temps minimum) pour ce nageur et cet event
    row = df_swimmer.sort_values("SwimTimeSeconds").iloc[0]
    splits = row["splits"]
    split_data = []
    for s in splits:
        if s.get("split_speed") is not None:
            try:
                dist = int(str(s.get("split_distance", "0").replace(" m", "")))
            except ValueError:
                continue
            split_data.append(
                {
                    "split_distance": dist,
                    "split_speed": s["split_speed"],
                }
            )

    if not split_data:
        st.info("Aucun split valide pour cette performance.")
        return

    df_splits = pd.DataFrame(split_data).sort_values("split_distance")
    fig, ax = plt.subplots(figsize=(8, 4))
    sns.lineplot(
        x="split_distance",
        y="split_speed",
        data=df_splits,
        marker="o",
        color="#008080",
        ax=ax,
    )
    ax.set_xticks(
        range(
            50,
            int(df_splits["split_distance"].max()) + 50,
            50,
        )
    )
    ax.set_title("Vitesse par split pour une performance sélectionnée")
    ax.set_xlabel("Split (m)")
    ax.set_ylabel("Vitesse (m/s)")
    ax.grid(True)
    st.pyplot(fig)


def main():
    st.title("Pacing – Analyse des compétitions")
    st.caption("Interface Streamlit basée sur les graphiques de `graphics.ipynb`.")

    df = load_data()

    st.markdown(
        f"**Nombre de performances chargées :** {df['SwimTime'].notna().sum():,}".replace(
            ",", " "
        )
    )

    df_filtered = sidebar_filters(df)

    st.markdown(
        f"**Nombre de lignes après filtres :** {len(df_filtered):,}".replace(",", " ")
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Distribution globale",
            "Sexe & répartition",
            "Nages & distances",
            "Clubs",
            "Vitesse & splits",
        ]
    )

    with tab1:
        plot_swimtime_distribution(df_filtered)
        plot_histogram_with_mean_median(df_filtered)
        plot_boxplot_times(df_filtered)
        plot_cumulative_hist(df_filtered)

    with tab2:
        plot_gender_count(df_filtered)

    with tab3:
        plot_swimtime_by_stroke(df_filtered)
        plot_heatmap_distance_stroke(df_filtered)
        plot_time_over_date(df_filtered)

    with tab4:
        plot_top_clubs(df_filtered)
        plot_mean_time_top10_clubs(df_filtered)

    with tab5:
        plot_speed_by_distance_stroke(df_filtered)
        plot_single_split_speed(df_filtered)


if __name__ == "__main__":
    main()
