import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[1]
EXTRANAT_OUTPUT_BASE_DIR = (
    BASE_DIR / "data" / "cleaned_data" / "extranat" / "competitions_per_type"
)


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


def main() -> None:
    st.set_page_config(
        page_title="Pacing – Visualisations Extranat",
        layout="wide",
    )

    st.title("Pacing – Visualisations Extranat")

    df = load_data()
    if df.empty:
        st.error(
            f"Aucune donnée trouvée dans `{EXTRANAT_OUTPUT_BASE_DIR}`.\n\n"
            "Vérifie que les fichiers JSON existent bien."
        )
        return

    st.markdown(
        f"Nombre de performances disponibles : **{df.shape[0]:,}**".replace(",", " ")
    )

    with st.sidebar:
        st.header("Filtres")

        all_events = sorted(df["Event"].dropna().unique().tolist())
        nom_event = st.selectbox(
            "Épreuve (Event)",
            options=["<Toutes>"] + all_events,
            index=0,
        )

        graphique = st.selectbox(
            "Type de graphique",
            [
                "Histogramme simple",
                "Histogramme + densité",
                "Histogramme cumulatif",
                "Comptage par sexe (global)",
                "Comptage par sexe (épreuve)",
                "Camembert par sexe (global)",
                "Camembert par sexe (épreuve)",
                "Nombre de nageurs uniques par épreuve (LCM)",
                "Nombre de performances par épreuve (LCM + SCM)",
                "Temps moyen par type de nage (distance choisie)",
                "Top 10 clubs par participation",
                "Top 10 clubs par participation (épreuve)",
                "Temps moyen des 10 meilleurs clubs",
                "Évolution des temps dans le temps",
                "Moyenne des temps par distance et type de nage",
                "Top 10 nageurs pour une épreuve",
                "Vitesse moyenne par distance et type de nage",
            ],
        )

    df_filtered = df.copy()
    df_filtered = df_filtered[df_filtered["SwimTimeSeconds"].notna()]

    if nom_event != "<Toutes>":
        df_filtered = df_filtered[df_filtered["Event"] == nom_event]

    if graphique in {
        "Histogramme simple",
        "Histogramme + densité",
        "Histogramme cumulatif",
    }:
        if df_filtered.empty:
            st.warning("Aucune donnée pour les filtres sélectionnés.")
            return

        swim_times = df_filtered["SwimTimeSeconds"].dropna()

        st.subheader(
            "Distribution des temps de nage"
            + (f" – {nom_event}" if nom_event != "<Toutes>" else "")
        )

        fig, ax = plt.subplots(figsize=(12, 8))

        if graphique == "Histogramme simple":
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

        elif graphique == "Histogramme + densité":
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

        st.pyplot(fig)

    elif graphique == "Nombre de nageurs uniques par épreuve (LCM)":
        st.subheader("Nombre de nageurs uniques par épreuve (LCM)")

        df_tmp = df.copy()

        df_tmp["Gender"] = df_tmp["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )
        df_tmp["swimmer_name"] = df_tmp["swimmer"].apply(
            lambda x: x[0]["Name"] if isinstance(x, list) and len(x) > 0 else None
        )

        df_clean = df_tmp.dropna(subset=["Gender", "Event", "swimmer_name"])
        df_clean = df_clean[df_clean["Event"].str.contains("LCM", na=False)]

        if df_clean.empty:
            st.warning("Aucune donnée disponible pour calculer ce graphique.")
            return

        df_counts = (
            df_clean.groupby(["Event", "Gender"])["swimmer_name"]
            .nunique()
            .unstack(fill_value=0)
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

        ax.set_title("Nombre de nageurs uniques par épreuve (LCM)", fontsize=16)
        ax.set_xlabel("Épreuve")
        ax.set_ylabel("Nombre de nageurs uniques")
        ax.set_xticks(x)
        ax.set_xticklabels(events, rotation=45, ha="right")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)

        fig.tight_layout()
        st.pyplot(fig)

    elif graphique == "Nombre de performances par épreuve (LCM + SCM)":
        st.subheader("Nombre de performances par épreuve (LCM + SCM)")

        df_tmp = df.copy()

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
        st.pyplot(fig)

    elif graphique == "Comptage par sexe (global)":
        st.subheader("Nombre de performances par sexe – global")

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

        st.pyplot(fig)

    elif graphique == "Comptage par sexe (épreuve)":
        if nom_event == "<Toutes>":
            st.info("Sélectionne une épreuve précise pour ce graphique.")
            return

        st.subheader(f"Nombre de performances par sexe – {nom_event}")

        df_event = df_filtered[df_filtered["Event"] == nom_event].copy()
        if df_event.empty:
            st.warning(
                "Aucune donnée pour cette épreuve avec les filtres actuels "
                "(vérifie notamment le temps maximum)."
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

        st.pyplot(fig)

    elif graphique == "Camembert par sexe (global)":
        st.subheader("Répartition des performances par sexe – global")

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

        st.pyplot(fig)

    elif graphique == "Camembert par sexe (épreuve)":
        if nom_event == "<Toutes>":
            st.info("Sélectionne une épreuve précise pour ce graphique.")
            return

        st.subheader(f"Répartition des performances par sexe – {nom_event}")

        df_event = df_filtered[df_filtered["Event"] == nom_event].copy()
        if df_event.empty:
            st.warning(
                "Aucune donnée pour cette épreuve avec les filtres actuels "
                "(vérifie notamment le temps maximum)."
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

        st.pyplot(fig)

    elif graphique == "Temps moyen par type de nage (distance choisie)":
        st.subheader("Temps moyen par type de nage pour une distance")

        distances = sorted(df["Distance"].dropna().unique().tolist())
        if not distances:
            st.warning("Aucune distance disponible.")
            return

        distance_choisie = st.selectbox(
            "Distance (m)",
            options=distances,
            index=0,
        )

        df_dist = df[df["Distance"] == distance_choisie].copy()
        df_dist = df_dist[df_dist["SwimTimeSeconds"].notna()]

        if df_dist.empty:
            st.warning("Aucune donnée pour cette distance.")
            return

        moyennes = (
            df_dist.groupby("Stroke")["SwimTimeSeconds"].mean().sort_values()
        )

        fig, ax = plt.subplots(figsize=(8, 5))
        sns.barplot(
            x=moyennes.index,
            y=moyennes.values,
            palette="viridis",
            ax=ax,
        )
        ax.set_xlabel("Type de nage")
        ax.set_ylabel("Temps moyen (secondes)")
        ax.set_title(
            f"Temps moyen par type de nage pour la distance {distance_choisie} m"
        )
        st.pyplot(fig)

    elif graphique == "Top 10 clubs par participation":
        st.subheader("Top 10 des clubs par nombre de participations")

        df_clubs = df[df["Club"].notna()].copy()
        if df_clubs.empty:
            st.warning("Aucune information de club disponible.")
            return

        counts = df_clubs["Club"].value_counts().head(10)[::-1]

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(counts.index, counts.values, color="#4FA2F6")
        ax.set_xlabel("Nombre de participations")
        ax.set_ylabel("Club")
        ax.set_title("Top 10 des clubs par nombre de participation")
        st.pyplot(fig)

    elif graphique == "Top 10 clubs par participation (épreuve)":
        if nom_event == "<Toutes>":
            st.info("Sélectionne une épreuve précise pour ce graphique.")
            return

        st.subheader(f"Top 10 des clubs par nombre de participations – {nom_event}")

        df_event = df[df["Event"] == nom_event].copy()
        df_event = df_event[df_event["Club"].notna()]
        if df_event.empty:
            st.warning("Aucune information de club disponible pour cette épreuve.")
            return

        top_clubs = df_event["Club"].value_counts().nlargest(10)

        fig, ax = plt.subplots(figsize=(12, 6))
        sns.barplot(x=top_clubs.index, y=top_clubs.values, color="#8C5CE4", ax=ax)

        ax.set_title(
            f"Top 10 des clubs par nombre de participations - {nom_event}"
        )
        ax.set_xlabel("Club")
        ax.set_ylabel("Nombre de participations")
        plt.setp(ax.get_xticklabels(), rotation=90)

        st.pyplot(fig)

    elif graphique == "Temps moyen des 10 meilleurs clubs":
        st.subheader("Temps moyen des 10 meilleurs clubs")

        df_clubs = df[
            df["Club"].notna() & df["SwimTimeSeconds"].notna()
        ].copy()
        if df_clubs.empty:
            st.warning("Aucune information de club ou de temps disponible.")
            return

        moyennes = (
            df_clubs.groupby("Club")["SwimTimeSeconds"]
            .mean()
            .sort_values()
            .head(10)[::-1]
        )

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(moyennes.index, moyennes.values, color="#008080")
        ax.set_xlabel("Temps moyen (secondes)")
        ax.set_ylabel("Club")
        ax.set_title("Temps moyen des 10 meilleurs clubs")
        st.pyplot(fig)

    elif graphique == "Évolution des temps dans le temps":
        st.subheader(
            "Évolution des temps de nage dans le temps (échantillon de 5000 performances)"
        )

        df_time = df[["SwimDate", "SwimTimeSeconds"]].dropna().copy()
        if df_time.empty:
            st.warning("Aucune information de date ou de temps disponible.")
            return

        df_time["SwimDate"] = pd.to_datetime(df_time["SwimDate"], errors="coerce")
        df_time = df_time.dropna(subset=["SwimDate"])

        if len(df_time) > 5000:
            df_time = df_time.sample(5000, random_state=42)

        df_time = df_time.sort_values("SwimDate")

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.scatter(df_time["SwimDate"], df_time["SwimTimeSeconds"], s=5, alpha=0.4)
        ax.set_xlabel("Date")
        ax.set_ylabel("Temps (secondes)")
        ax.set_title(
            "Évolution des temps de nage dans le temps (échantillon de 5000 performances)"
        )
        plt.xticks(rotation=45)
        st.pyplot(fig)

    elif graphique == "Moyenne des temps par distance et type de nage":
        st.subheader("Moyenne des temps par distance et type de nage")

        df_tmp = df[df["SwimTimeSeconds"].notna()].copy()
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
        st.pyplot(fig)

    elif graphique == "Top 10 nageurs pour une épreuve":
        if nom_event == "<Toutes>":
            st.info("Sélectionne une épreuve précise pour ce graphique.")
            return

        st.subheader(f"Top 10 nageurs – {nom_event}")

        df_event = df[df["Event"] == nom_event].copy()
        df_event = df_event[df_event["SwimTimeSeconds"].notna()]
        if df_event.empty:
            st.warning("Aucune donnée pour cette épreuve.")
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
        ax.set_title(f"Top 10 nageurs - {nom_event}")
        st.pyplot(fig)

    elif graphique == "Vitesse moyenne par distance et type de nage":
        st.subheader("Vitesse moyenne par distance et type de nage")

        df_speed = df[df["Speed"].notna()].copy()
        if df_speed.empty:
            st.warning("Aucune donnée de vitesse disponible.")
            return

        pivot = (
            df_speed.groupby(["Distance", "Stroke"])["Speed"]
            .mean()
            .reset_index()
        )

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(
            data=pivot,
            x="Distance",
            y="Speed",
            hue="Stroke",
            ax=ax,
        )
        ax.set_xlabel("Distance (m)")
        ax.set_ylabel("Vitesse moyenne (m/s)")
        ax.set_title("Vitesse moyenne selon distance et type de nage")
        st.pyplot(fig)


if __name__ == "__main__":
    main()

