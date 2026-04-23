from __future__ import annotations
from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


@dataclass(frozen=True)
class GraphSpec:
    """dataclass pour la description des graphes """
    key: str
    name: str
    category: str
    method_name: str


class ServiceGraphe:
    """Service central pour construire les graphes."""
    def plot_histogramme_simple(self, df: pd.DataFrame, swim_col: str = "SwimTimeSeconds") -> plt.Figure:
        values = pd.to_numeric(df.get(swim_col), errors="coerce").dropna()
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.hist(values, bins=50, color="#004080", edgecolor="#004080", alpha=0.7)
        if not values.empty:
            ax.axvline(float(np.mean(values)), color="red", linestyle="dashed", linewidth=2, label="Moyenne")
            ax.axvline(float(np.median(values)), color="orange", linestyle="dashed", linewidth=2, label="Mediane")
            ax.legend()
        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre de performances")
        ax.set_title("Histogramme simple des temps de nage")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        return fig

    def plot_camembert_sexe_global(self, df: pd.DataFrame, gender_col: str = "Gender") -> plt.Figure:
        local_df = df.copy()
        if gender_col not in local_df.columns:
            local_df[gender_col] = local_df.get("swimmer", pd.Series(dtype=object)).apply(
                lambda x: x[0].get("Gender") if isinstance(x, list) and len(x) > 0 and isinstance(x[0], dict) else None
            )

        counts = local_df.get(gender_col, pd.Series(dtype=str)).dropna().value_counts()
        fig, ax = plt.subplots(figsize=(6, 6))
        if counts.empty:
            ax.text(0.5, 0.5, "Aucune donnée de sexe disponible", ha="center", va="center")
            ax.set_axis_off()
            ax.set_title("Camembert par sexe (global)")
            fig.tight_layout()
            return fig

        ax.pie(
            counts,
            labels=[f"{g} ({n})" for g, n in zip(counts.index, counts)],
            autopct="%1.1f%%",
            colors=["#4FA2F6", "#F585BD"],
            startangle=90,
        )
        ax.set_title("Camembert par sexe (global)")
        fig.tight_layout()
        return fig

    def plot_histogramme_densite(self, df: pd.DataFrame, swim_col: str = "SwimTimeSeconds") -> plt.Figure:
        values = pd.to_numeric(df.get(swim_col), errors="coerce")
        values = values[(values.notna()) & (values < 500)]
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.histplot(
            values,
            bins=30,
            kde=True,
            color="#004080",
            edgecolor="#004080",
            alpha=0.6,
            ax=ax,
        )
        ax.set_title("Distribution des temps de natation avec densite")
        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre de performances")
        ax.set_xticks(np.arange(0, 501, 25))
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        return fig

    def plot_histogramme_cumulatif(self, df: pd.DataFrame, swim_col: str = "SwimTimeSeconds") -> plt.Figure:
        values = pd.to_numeric(df.get(swim_col), errors="coerce")
        values = values[(values.notna()) & (values < 500)]
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.hist(
            values,
            bins=30,
            cumulative=True,
            color="#008080",
            edgecolor="black",
            alpha=0.7,
        )
        ax.set_title("Histogramme cumulatif des temps de natation")
        ax.set_xlabel("Temps (secondes)")
        ax.set_ylabel("Nombre cumule de performances")
        ax.set_xticks(np.arange(0, 501, 25))
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        return fig

    def plot_boxplot_temps_par_nage(
        self,
        df: pd.DataFrame,
        stroke_col: str = "Stroke",
        swim_col: str = "SwimTimeSeconds",
    ) -> plt.Figure:
        local_df = df.copy()
        local_df[swim_col] = pd.to_numeric(local_df.get(swim_col), errors="coerce")
        local_df = local_df.dropna(subset=[stroke_col, swim_col])
        local_df["SwimTimeMinutes"] = local_df[swim_col] / 60.0
        fig, ax = plt.subplots(figsize=(12, 8))
        sns.boxplot(data=local_df, x=stroke_col, y="SwimTimeMinutes", palette="Set2", ax=ax)
        ax.set_xlabel("Type de nage")
        ax.set_ylabel("Temps (minutes)")
        ax.set_title("Distribution des temps par type de nage (boxplot)")
        fig.tight_layout()
        return fig

    def plot_top10_clubs(self, df: pd.DataFrame, club_col: str = "Club") -> plt.Figure:
        counts = df.get(club_col, pd.Series(dtype=str)).dropna().value_counts().nlargest(10)
        fig, ax = plt.subplots(figsize=(12, 6))
        sns.barplot(x=counts.index, y=counts.values, color="#8C5CE4", ax=ax)
        ax.set_title("Top 10 clubs par participation")
        ax.set_xlabel("Club")
        ax.set_ylabel("Nombre de participations")
        plt.setp(ax.get_xticklabels(), rotation=90)
        fig.tight_layout()
        return fig

    def plot_heatmap_vitesse_moyenne(
        self,
        df: pd.DataFrame,
        distance_col: str = "Distance",
        stroke_col: str = "Stroke",
        speed_col: str = "Speed",
    ) -> plt.Figure:
        local_df = df.copy()
        local_df[distance_col] = pd.to_numeric(local_df.get(distance_col), errors="coerce")
        local_df[speed_col] = pd.to_numeric(local_df.get(speed_col), errors="coerce")
        local_df = local_df.dropna(subset=[distance_col, stroke_col, speed_col])
        pivot = local_df.pivot_table(values=speed_col, index=distance_col, columns=stroke_col, aggfunc="mean")
        fig, ax = plt.subplots(figsize=(12, 7))
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="coolwarm", ax=ax)
        ax.set_title("Heatmap vitesse moyenne (distance x nage)")
        ax.set_xlabel("Stroke")
        ax.set_ylabel("Distance")
        fig.tight_layout()
        return fig

    def plot_swimming_speed_by_distance_and_stroke(
        self,
        df: pd.DataFrame,
        speed_col: str = "Speed",
        distance_col: str = "Distance",
        stroke_col: str = "Stroke",
    ) -> Optional[plt.Figure]:
        """Vitesse moyenne (colonne Speed) par distance et type de nage — courbes."""
        local_df = df.copy()
        local_df[speed_col] = pd.to_numeric(local_df.get(speed_col), errors="coerce")
        local_df[distance_col] = pd.to_numeric(local_df.get(distance_col), errors="coerce")
        local_df = local_df.dropna(subset=[speed_col, distance_col, stroke_col])
        if local_df.empty:
            return None
        speed_by_dist = (
            local_df.groupby([distance_col, stroke_col], as_index=False)[speed_col]
            .mean()
            .sort_values([stroke_col, distance_col])
        )
        fig, ax = plt.subplots(figsize=(14, 8))
        sns.lineplot(
            data=speed_by_dist,
            x=distance_col,
            y=speed_col,
            hue=stroke_col,
            marker="o",
            ax=ax,
        )
        ax.set_title("Swimming Speed by Distance and Stroke Type")
        ax.set_xlabel("Distance (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(alpha=0.3, linestyle="--")
        fig.tight_layout()
        return fig

    def plot_vitesse_max_par_split_et_nage(
        self,
        df: pd.DataFrame,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        local_df = df.loc[
            df["Speed"].notna(),
            ["Stroke", "Distance", "Speed", "swimmer", "splits"],
        ].copy()

        def clean_swimmer(value: object) -> Optional[str]:
            if isinstance(value, dict):
                return value.get("Name")
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                return value[0].get("Name")
            return None

        local_df["Swimmer"] = local_df["swimmer"].map(clean_swimmer)
        local_df = local_df.dropna(subset=["Swimmer"])

        split_rows: list[dict[str, object]] = []
        has_splits = local_df["splits"].apply(lambda x: isinstance(x, list) and len(x) > 0)
        for _, row in local_df.loc[has_splits].iterrows():
            swimmer_name = row["Swimmer"]
            stroke = row["Stroke"]
            for split in row["splits"]:
                if not isinstance(split, dict):
                    continue
                split_distance = split.get("split_distance")
                split_speed = split.get("split_speed")
                if split_distance is None or split_speed is None:
                    continue
                try:
                    distance = int(str(split_distance).replace(" m", ""))
                    speed = float(split_speed)
                except (TypeError, ValueError):
                    continue
                if 0 < speed < 5:
                    split_rows.append(
                        {
                            "Stroke": stroke,
                            "SplitDistance": distance,
                            "SplitSpeed": speed,
                            "Swimmer": swimmer_name,
                        }
                    )

        df_splits = pd.DataFrame(split_rows)
        if df_splits.empty:
            return None, pd.DataFrame()

        df_splits_max = df_splits.loc[
            df_splits.groupby(["Stroke", "SplitDistance"])["SplitSpeed"].idxmax()
        ].reset_index(drop=True)

        fig, ax = plt.subplots(figsize=(12, 6))
        sns.set_style("whitegrid")
        sns.scatterplot(
            data=df_splits_max,
            x="SplitDistance",
            y="SplitSpeed",
            hue="Stroke",
            style="Stroke",
            s=150,
            ax=ax,
        )

        max_split = int(df_splits_max["SplitDistance"].max())
        ax.set_xticks(np.arange(0, max_split + 50, 50))
        ax.set_title("Max Speed per Split Distance and Stroke", fontsize=16)
        ax.set_xlabel("Split Distance (m)")
        ax.set_ylabel("Split Speed (m/s)")
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(title="Stroke", bbox_to_anchor=(1.05, 1), loc="upper left")
        fig.tight_layout()
        return fig, df_splits_max

    def plot_vitesse_moyenne_mediane_par_split_et_nage(
        self,
        df: pd.DataFrame,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        local_df = df.loc[
            df["Speed"].notna(),
            ["Stroke", "Distance", "Speed", "swimmer", "splits"],
        ].copy()

        split_rows: list[dict[str, object]] = []
        has_splits = local_df["splits"].apply(lambda x: isinstance(x, list) and len(x) > 0)
        for _, row in local_df.loc[has_splits].iterrows():
            stroke = row["Stroke"]
            for split in row["splits"]:
                if not isinstance(split, dict):
                    continue
                split_distance = split.get("split_distance")
                split_speed = split.get("split_speed")
                if split_distance is None or split_speed is None:
                    continue
                try:
                    distance = int(str(split_distance).replace(" m", "").strip())
                    speed = float(split_speed)
                except (TypeError, ValueError):
                    continue
                if 0 < speed < 5:
                    split_rows.append(
                        {
                            "Stroke": stroke,
                            "SplitDistance": distance,
                            "SplitSpeed": speed,
                        }
                    )

        df_splits = pd.DataFrame(split_rows)
        if df_splits.empty:
            return None, pd.DataFrame()

        df_stats = (
            df_splits.groupby(["Stroke", "SplitDistance"], as_index=False)
            .agg(
                MeanSpeed=("SplitSpeed", "mean"),
                MedianSpeed=("SplitSpeed", "median"),
                N=("SplitSpeed", "size"),
            )
        )

        df_plot = df_stats.melt(
            id_vars=["Stroke", "SplitDistance", "N"],
            value_vars=["MeanSpeed", "MedianSpeed"],
            var_name="Stat",
            value_name="SpeedValue",
        )
        df_plot["Stat"] = df_plot["Stat"].map(
            {
                "MeanSpeed": "Moyenne",
                "MedianSpeed": "Mediane",
            }
        )

        fig, ax = plt.subplots(figsize=(13, 7))
        sns.set_style("whitegrid")
        sns.scatterplot(
            data=df_plot,
            x="SplitDistance",
            y="SpeedValue",
            hue="Stroke",
            style="Stat",
            s=150,
            ax=ax,
        )

        max_split = int(df_plot["SplitDistance"].max())
        ax.set_xticks(np.arange(0, max_split + 50, 50))
        ax.set_title("Vitesse moyenne et mediane par split et stroke", fontsize=16)
        ax.set_xlabel("Split Distance (m)")
        ax.set_ylabel("Speed (m/s)")
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend(title="Stroke / Stat", bbox_to_anchor=(1.05, 1), loc="upper left")
        fig.tight_layout()
        return fig, df_plot

    def filter_performances_with_valid_splits_for_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[int], pd.DataFrame]:
        def parse_event_distance(event_name: object) -> Optional[int]:
            match = re.search(r"(\d+)", str(event_name))
            return int(match.group(1)) if match else None

        def parse_split_distance(value: object) -> Optional[int]:
            try:
                return int(float(str(value).lower().replace("m", "").strip()))
            except (TypeError, ValueError):
                return None

        def get_last_split_distance(splits: object) -> Optional[int]:
            if not isinstance(splits, list) or len(splits) == 0:
                return None
            for split in reversed(splits):
                if not isinstance(split, dict):
                    continue
                distance = parse_split_distance(split.get("split_distance"))
                if distance is not None:
                    return distance
            return None

        def has_valid_splits(splits: object) -> bool:
            if not isinstance(splits, list) or len(splits) == 0:
                return False
            return any(isinstance(split, dict) and split.get("split_seconds") is not None for split in splits)

        event_distance = parse_event_distance(nom_event)
        df_splits_event = df[
            (df["Event"].astype(str).str.strip() == nom_event)
            & (df["splits"].apply(has_valid_splits))
            & (df["splits"].apply(lambda splits: get_last_split_distance(splits) == event_distance))
        ].copy()
        return event_distance, df_splits_event

    def plot_nombre_performances_par_epreuve(
        self,
        df: pd.DataFrame,
        course_type: str = "LCM",
    ) -> plt.Figure:
        local_df = df.copy()
        local_df["Gender"] = local_df["swimmer"].apply(
            lambda x: x[0].get("Gender") if isinstance(x, list) and len(x) > 0 else None
        )
        local_df["swimmer_name"] = local_df["swimmer"].apply(
            lambda x: x[0].get("Name") if isinstance(x, list) and len(x) > 0 else None
        )
        local_df = local_df.dropna(subset=["Gender", "Event", "swimmer_name"])
        local_df = local_df[local_df["Event"].str.contains(course_type, na=False)]

        df_counts = (
            local_df
            .groupby(["Event", "Gender"])["swimmer_name"]
            .count()
            .unstack(fill_value=0)
            .sort_index()
        )
        events = df_counts.index
        female_counts = df_counts["F"] if "F" in df_counts else pd.Series(0, index=events)
        male_counts = df_counts["M"] if "M" in df_counts else pd.Series(0, index=events)

        x = np.arange(len(events))
        width = 0.35
        fig, ax = plt.subplots(figsize=(16, 6))
        bars1 = ax.bar(x - width / 2, female_counts, width, label="Female", color="#F585BD")
        bars2 = ax.bar(x + width / 2, male_counts, width, label="Male", color="#4FA2F6")

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

        ax.set_title(f"Nombre de performances par epreuve ({course_type})", fontsize=16, fontweight="bold")
        ax.set_xlabel("Epreuve")
        ax.set_ylabel("Nombre de performances")
        ax.set_xticks(x)
        ax.set_xticklabels(events, rotation=45)
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        fig.tight_layout()
        return fig

    def plot_nombre_performances_par_epreuve_lcm_scm(self, df: pd.DataFrame) -> plt.Figure:
        local_df = df.copy()
        local_df["Gender"] = local_df["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )
        local_df["Event_clean"] = (
            local_df["Event"]
            .str.replace(" LCM", "", regex=False)
            .str.replace(" SCM", "", regex=False)
        )
        local_df = local_df.dropna(subset=["Gender", "Event_clean"])

        df_counts = local_df.groupby(["Event_clean", "Gender"]).size().unstack(fill_value=0)
        df_counts["Total"] = df_counts.sum(axis=1)
        df_counts = df_counts.sort_values("Total", ascending=False).drop(columns="Total")

        total_performances = int(df_counts.sum().sum())
        events = df_counts.index
        female_counts = df_counts["F"] if "F" in df_counts else pd.Series(0, index=events)
        male_counts = df_counts["M"] if "M" in df_counts else pd.Series(0, index=events)

        x = np.arange(len(events))
        width = 0.35
        fig, ax = plt.subplots(figsize=(16, 6))
        bars1 = ax.bar(x - width / 2, female_counts, width, label="Female", color="#F585BD")
        bars2 = ax.bar(x + width / 2, male_counts, width, label="Male", color="#4FA2F6")

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

        ax.set_title("Number of Performances per Event (LCM + SCM)", fontsize=16, fontweight="bold")
        ax.text(
            0.5,
            1.08,
            f"Total Performances: {total_performances}",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            fontweight="bold",
            color="#333333",
        )
        ax.set_xlabel("Event")
        ax.set_ylabel("Number of Performances")
        ax.set_xticks(x)
        ax.set_xticklabels(events, rotation=45)
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        fig.tight_layout()
        return fig

    def plot_nombre_performances_par_sexe(self, df: pd.DataFrame) -> plt.Figure:
        local_df = df.copy()
        local_df["Gender"] = local_df["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )

        fig, ax = plt.subplots(figsize=(6, 4))
        palette_colors = {"F": "#F585BD", "M": "#4FA2F6"}
        sns.countplot(x="Gender", data=local_df, palette=palette_colors, ax=ax)

        ax.set_title("Nombre de performances par sexe")
        ax.set_xlabel("Sexe")
        ax.set_ylabel("Nombre de performances")
        fig.tight_layout()
        return fig

    def plot_camembert_sexe_par_event(self, df: pd.DataFrame, nom_event: str) -> Optional[plt.Figure]:
        df_event = df.loc[df["Event"] == nom_event].copy()
        df_event["Gender"] = df_event["swimmer"].apply(
            lambda x: x[0]["Gender"] if isinstance(x, list) and len(x) > 0 else None
        )

        gender_counts = df_event["Gender"].value_counts()
        if gender_counts.empty:
            return None

        fig, ax = plt.subplots(figsize=(6, 6))
        ax.pie(
            gender_counts,
            labels=[f"{g} ({n})" for g, n in zip(gender_counts.index, gender_counts)],
            autopct="%1.1f%%",
            colors=["#4FA2F6", "#F585BD"],
            startangle=90,
        )
        ax.set_title(f"Répartition des performances par sexe pour {nom_event}")
        fig.tight_layout()
        return fig

    def plot_temps_median_top10_clubs_par_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        df_time = df[(df["Event"] == nom_event) & (df["SwimTimeSeconds"].notna())].copy()
        if df_time.empty:
            return None, pd.DataFrame()

        df_time["SwimTimeMinutes"] = df_time["SwimTimeSeconds"] / 60
        median_time_club = (
            df_time.groupby("Club", dropna=False)["SwimTimeMinutes"]
            .median()
            .reset_index()
            .sort_values("SwimTimeMinutes")
        )
        top10_clubs = median_time_club.head(10)

        fig, ax = plt.subplots(figsize=(12, 6))
        sns.lineplot(
            data=top10_clubs,
            x="Club",
            y="SwimTimeMinutes",
            marker="o",
            color="#8C5CE4",
            ax=ax,
        )
        ax.set_title(f"Temps médian des 10 meilleurs clubs - {nom_event}")
        ax.set_xlabel("Club")
        ax.set_ylabel("Temps médian (minutes)")
        plt.setp(ax.get_xticklabels(), rotation=90)
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.tight_layout()
        return fig, top10_clubs

    def plot_evolution_temps_nage(
        self,
        df: pd.DataFrame,
        start_year: int = 2000,
        sample_size: int = 5000,
    ) -> Optional[plt.Figure]:
        local_df = df.copy()
        local_df["SwimDate"] = pd.to_datetime(local_df["SwimDate"], errors="coerce")

        df_plot = local_df[
            (local_df["SwimDate"].notna())
            & (local_df["SwimTimeSeconds"].notna())
            & (local_df["SwimDate"].dt.year >= start_year)
        ].copy()

        if df_plot.empty:
            return None

        df_plot["SwimTimeMinutes"] = df_plot["SwimTimeSeconds"] / 60
        df_sample = df_plot.sample(min(sample_size, len(df_plot)), random_state=42)

        fig, ax = plt.subplots(figsize=(20, 6))
        sns.lineplot(
            x="SwimDate",
            y="SwimTimeMinutes",
            data=df_sample,
            hue="Stroke",
            alpha=0.7,
            ax=ax,
        )
        ax.set_title(f"Évolution des temps de nage dans le temps (à partir de {start_year})")
        ax.set_xlabel("Année")
        ax.set_ylabel("Temps de nage (minutes)")
        ax.legend(title="Stroke")
        fig.tight_layout()
        return fig

    def plot_top10_nageurs_meilleur_temps_par_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame]:
        subset = df[
            (df["Event"] == nom_event)
            & (df["SwimTimeSeconds"].notna())
            & (df["SwimTimeSeconds"] > 0)
        ].copy()

        if subset.empty:
            return None, pd.DataFrame()

        subset["SwimmerName"] = subset["swimmer"].apply(
            lambda x: x[0]["Name"] if isinstance(x, list) and len(x) > 0 else "Unknown"
        )

        best_times = subset.groupby("SwimmerName", as_index=False)["SwimTimeSeconds"].min()
        top10 = best_times.nsmallest(10, "SwimTimeSeconds")

        def format_time(sec: float) -> str:
            minutes = int(sec // 60)
            seconds = sec % 60
            return f"{minutes}:{seconds:05.2f} min"

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(
            x="SwimTimeSeconds",
            y="SwimmerName",
            data=top10,
            palette="coolwarm_r",
            orient="h",
            errorbar=None,
            ax=ax,
        )

        ax.set_title(f"Top 10 nageurs (meilleur temps) - {nom_event}")
        ax.set_ylabel("Nageur")
        ax.set_xlabel("")
        ax.set_xticks([])
        ax.spines["bottom"].set_visible(False)

        for i, v in enumerate(top10["SwimTimeSeconds"]):
            ax.text(v + 0.5, i, format_time(v), va="center")

        fig.tight_layout()
        return fig, top10

    def plot_split_speed_analysis_by_gender_with_targets(
        self,
        df: pd.DataFrame,
        nom_event: str,
        swimmer_targets: list[str],
        target_colors: Optional[dict[str, str]] = None,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        target_colors = target_colors or {}
        style_by_gender = {
            "F": {"fill": "#F9D9D7", "median": "#F5D7F9", "mean": "#F5D7F9"},
            "M": {"fill": "#82C9D1", "median": "#AAEEF6", "mean": "#AAEEF6"},
        }
        fill_alpha = 0.22
        line_width_med = 2.8
        line_width_mean = 3.2
        marker_size = 7

        def parse_dist(value: object) -> Optional[int]:
            try:
                return int(float(str(value).lower().replace("m", "").strip()))
            except (TypeError, ValueError):
                return None

        def parse_event_distance(event_name: str) -> Optional[int]:
            try:
                return int(str(event_name).strip().split()[0])
            except (TypeError, ValueError, IndexError):
                return None

        def normalize_name(value: object) -> str:
            if pd.notna(value):
                return str(value).strip().lower()
            return ""

        def to_float(value: object) -> Optional[float]:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def has_valid_split_speed(splits: object) -> bool:
            if not isinstance(splits, list) or len(splits) == 0:
                return False
            for split in splits:
                if not isinstance(split, dict):
                    continue
                distance = parse_dist(split.get("split_distance"))
                speed = to_float(split.get("split_speed"))
                if distance is not None and speed is not None:
                    return True
            return False

        def get_last_split_distance(splits: object) -> Optional[int]:
            if not isinstance(splits, list) or len(splits) == 0:
                return None
            for split in reversed(splits):
                if not isinstance(split, dict):
                    continue
                distance = parse_dist(split.get("split_distance"))
                if distance is not None:
                    return distance
            return None

        target_set_norm = {normalize_name(name) for name in swimmer_targets}
        event_distance = parse_event_distance(nom_event)
        applied_last_filter = False

        df_event = df[
            (df["Event"].astype(str).str.strip() == nom_event)
            & df["splits"].apply(has_valid_split_speed)
        ].copy()

        if event_distance is not None:
            df_event_last = df_event[
                df_event["splits"].apply(lambda splits: get_last_split_distance(splits) == event_distance)
            ].copy()
            if len(df_event_last) > 0:
                df_event = df_event_last
                applied_last_filter = True

        split_rows: list[dict[str, object]] = []
        target_rows: list[dict[str, object]] = []
        for _, row in df_event.iterrows():
            swimmers = row.get("swimmer", [])
            splits = row.get("splits", [])

            swimmer0 = {}
            if isinstance(swimmers, list) and len(swimmers) > 0 and isinstance(swimmers[0], dict):
                swimmer0 = swimmers[0]

            gender = swimmer0.get("Gender")
            name = swimmer0.get("Name")
            if gender not in ["F", "M"]:
                continue

            is_target = normalize_name(name) in target_set_norm
            for split in splits if isinstance(splits, list) else []:
                if not isinstance(split, dict):
                    continue
                distance = parse_dist(split.get("split_distance"))
                speed = to_float(split.get("split_speed"))
                if distance is None or speed is None:
                    continue
                split_no = max(1, int(round(distance / 50)))
                split_rows.append(
                    {
                        "Gender": gender,
                        "split_no": split_no,
                        "split_distance": distance,
                        "split_speed": speed,
                    }
                )
                if is_target:
                    target_rows.append(
                        {
                            "Name": name,
                            "Gender": gender,
                            "split_no": split_no,
                            "split_distance": distance,
                            "split_speed": speed,
                        }
                    )

        df_splits = pd.DataFrame(split_rows)
        if df_splits.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "event_distance": event_distance,
                "applied_last_filter": applied_last_filter,
                "performances_count": len(df_event),
                "split_values_count": 0,
            }

        stats = (
            df_splits.groupby(["Gender", "split_no"])["split_speed"]
            .agg(
                mean="mean",
                median="median",
                q1=lambda x: x.quantile(0.25),
                q3=lambda x: x.quantile(0.75),
                n="count",
            )
            .reset_index()
            .sort_values(["Gender", "split_no"])
        )
        stats["split_distance_theorique"] = stats["split_no"] * 50

        df_target = pd.DataFrame(target_rows)
        if not df_target.empty:
            target_stats = (
                df_target.groupby(["Name", "Gender", "split_no"])["split_speed"]
                .agg(target_mean="mean", target_n="count")
                .reset_index()
                .sort_values(["Name", "split_no"])
            )
            target_stats["split_distance_theorique"] = target_stats["split_no"] * 50
        else:
            target_stats = pd.DataFrame()

        fig, ax = plt.subplots(figsize=(13, 7))
        for gender in ["F", "M"]:
            data_gender = stats[stats["Gender"] == gender].sort_values("split_no")
            if data_gender.empty:
                continue
            style = style_by_gender[gender]
            ax.fill_between(
                data_gender["split_no"],
                data_gender["q1"],
                data_gender["q3"],
                color=style["fill"],
                alpha=fill_alpha,
                linewidth=0,
                label=f"IQR (Q1-Q3) - {gender}",
            )
            ax.plot(
                data_gender["split_no"],
                data_gender["median"],
                color=style["median"],
                linewidth=line_width_med,
                linestyle="--",
                marker="s",
                markersize=marker_size,
                markeredgecolor="white",
                markeredgewidth=0.8,
                label=f"Mediane - {gender}",
                zorder=5,
            )
            ax.plot(
                data_gender["split_no"],
                data_gender["mean"],
                color=style["mean"],
                linewidth=line_width_mean,
                linestyle="-",
                marker="o",
                markersize=marker_size,
                markeredgecolor="white",
                markeredgewidth=0.8,
                label=f"Moyenne - {gender}",
                zorder=6,
            )

        if not target_stats.empty:
            for swimmer in swimmer_targets:
                data_sw = target_stats[
                    target_stats["Name"].apply(normalize_name) == normalize_name(swimmer)
                ].sort_values("split_no")
                if data_sw.empty:
                    continue
                gender = data_sw.iloc[0]["Gender"]
                color_sw = target_colors.get(swimmer, "#222222")
                ax.plot(
                    data_sw["split_no"],
                    data_sw["target_mean"],
                    color=color_sw,
                    linewidth=3.2,
                    linestyle="-",
                    marker="D",
                    markersize=8,
                    markeredgecolor="white",
                    markeredgewidth=0.9,
                    label=f"{swimmer} (moyenne, {gender})",
                    zorder=7,
                )

        ticks = sorted(df_splits["split_no"].dropna().astype(int).unique().tolist())
        labels = [f"{tick * 50} m" for tick in ticks]
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        ax.set_title(f"{nom_event} - split_speed - F vs M + nageurs cibles", fontsize=14, fontweight="bold")
        ax.set_xlabel("Rang du split", fontsize=12)
        ax.set_ylabel("Vitesse par split", fontsize=12)
        ax.grid(alpha=0.25)
        ax.legend(ncol=2, frameon=False, fontsize=9)
        fig.tight_layout()

        return fig, stats, target_stats, {
            "event_distance": event_distance,
            "applied_last_filter": applied_last_filter,
            "performances_count": len(df_event),
            "split_values_count": len(df_splits),
        }

    def plot_vitesse_par_split_pour_nageur_event(
        self,
        df: pd.DataFrame,
        nom_nageur: str,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, Optional[str]]:
        split_data: list[dict[str, object]] = []
        gender_nageur: Optional[str] = None

        for _, row in df.iterrows():
            swimmers = row.get("swimmer", [])
            if row.get("Event") != nom_event or not isinstance(swimmers, list) or len(swimmers) != 1:
                continue
            swimmer = swimmers[0]
            if not isinstance(swimmer, dict) or swimmer.get("Name") != nom_nageur:
                continue

            gender_nageur = swimmer.get("Gender")
            for split in row.get("splits", []):
                if not isinstance(split, dict) or split.get("split_speed") is None:
                    continue
                try:
                    distance = int(str(split.get("split_distance")).replace(" m", ""))
                    speed = float(split.get("split_speed"))
                except (TypeError, ValueError):
                    continue
                split_data.append({"split_distance": distance, "split_speed": speed})

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), gender_nageur

        df_splits = df_splits.sort_values("split_distance")
        if gender_nageur == "M":
            color_line = "#003E80"
        elif gender_nageur == "F":
            color_line = "#FF69B4"
        else:
            color_line = "#008080"

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            data=df_splits,
            marker="o",
            color=color_line,
            errorbar=None,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        plt.setp(ax.get_xticklabels(), rotation=45)
        ax.set_title(f"Vitesse par split pour {nom_nageur} - {nom_event}")
        ax.set_xlabel("Split (m)")
        ax.set_ylabel("Vitesse (m/s)")
        ax.grid(True)
        fig.tight_layout()
        return fig, df_splits, gender_nageur

    def plot_vitesse_par_split_meilleur_nageur_event_periode(
        self,
        df: pd.DataFrame,
        nom_event: str,
        annee_debut: int,
        annee_fin: int,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
        df_work = df.copy()
        df_work.columns = df_work.columns.map(lambda x: str(x).strip())

        event_col = next((c for c in df_work.columns if c.lower() == "event"), None)
        swimtime_col = next((c for c in df_work.columns if c.lower() == "swimtimeseconds"), None)
        swimmer_col = next((c for c in df_work.columns if c.lower() == "swimmer"), None)
        if event_col is None or swimtime_col is None or swimmer_col is None:
            return None, pd.DataFrame(), {
                "message": "Colonnes indispensables manquantes (Event/SwimTimeSeconds/swimmer).",
            }

        year_candidates = [c for c in df_work.columns if "year" in c.lower()]
        date_candidates = [c for c in df_work.columns if "date" in c.lower()]

        chosen_year_col = None
        for pref in ["swimyear", "year", "meetyear", "competitionyear"]:
            chosen_year_col = next((c for c in year_candidates if c.lower() == pref), None)
            if chosen_year_col is not None:
                break
        if chosen_year_col is None and len(year_candidates) > 0:
            chosen_year_col = year_candidates[0]

        if chosen_year_col is not None:
            df_work["year"] = pd.to_numeric(df_work[chosen_year_col], errors="coerce")
        else:
            chosen_date_col = None
            for pref in ["swimdate", "date", "mpp_date", "meetdate", "competitiondate"]:
                chosen_date_col = next((c for c in date_candidates if c.lower() == pref), None)
                if chosen_date_col is not None:
                    break
            if chosen_date_col is None and len(date_candidates) > 0:
                chosen_date_col = date_candidates[0]
            if chosen_date_col is None:
                return None, pd.DataFrame(), {"message": "Aucune colonne annee/date disponible."}
            df_work["year"] = pd.to_datetime(df_work[chosen_date_col], errors="coerce").dt.year

        df_event = df_work[
            (df_work[event_col] == nom_event)
            & (df_work[swimtime_col].notna())
            & (df_work[swimmer_col].apply(lambda x: isinstance(x, list) and len(x) == 1))
            & (df_work["year"].between(annee_debut, annee_fin))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), {
                "message": f"Aucune performance pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        df_event["swimmer_name"] = df_event[swimmer_col].apply(
            lambda x: x[0].get("Name") if isinstance(x, list) and len(x) == 1 and isinstance(x[0], dict) else None
        )
        df_event["swimmer_gender"] = df_event[swimmer_col].apply(
            lambda x: x[0].get("Gender") if isinstance(x, list) and len(x) == 1 and isinstance(x[0], dict) else None
        )

        best_row = df_event.nsmallest(1, swimtime_col).iloc[0]
        best_name = best_row["swimmer_name"]
        best_gender = best_row["swimmer_gender"]
        best_time = float(best_row[swimtime_col])
        best_year = best_row["year"]
        meet_col = next((c for c in df_event.columns if c.lower() == "meet"), None)
        best_meet = best_row[meet_col] if meet_col is not None else "Meet non disponible"

        split_data: list[dict[str, object]] = []
        best_splits = best_row.get("splits", [])
        if isinstance(best_splits, list):
            for split in best_splits:
                if not isinstance(split, dict):
                    continue
                if split.get("split_speed") is None or split.get("split_distance") is None:
                    continue
                try:
                    distance = int(str(split["split_distance"]).replace(" m", "").strip())
                    speed = float(split["split_speed"])
                except (TypeError, ValueError):
                    continue
                split_data.append({"split_distance": distance, "split_speed": speed})

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), {
                "message": (
                    f"Aucun split valide trouve pour le meilleur nageur de l'event {nom_event} "
                    f"({annee_debut}-{annee_fin})."
                ),
                "best_name": best_name,
                "best_gender": best_gender,
                "best_time": best_time,
                "best_year": best_year,
                "best_meet": best_meet,
            }

        df_splits = df_splits.sort_values("split_distance")
        color = "#003E80" if best_gender == "M" else "#FF69B4"
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            data=df_splits,
            marker="o",
            color=color,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(
            f"Vitesse par split pour {best_name} ({best_gender}) - {nom_event} ({annee_debut}-{annee_fin})",
            fontsize=16,
        )
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse (m/s)", fontsize=14)
        ax.grid(True)
        fig.tight_layout()
        return fig, df_splits, {
            "best_name": best_name,
            "best_gender": best_gender,
            "best_time": best_time,
            "best_year": best_year,
            "best_meet": best_meet,
            "message": "ok",
        }

    def plot_vitesse_par_split_top_nageurs_hf_event_periode(
        self,
        df: pd.DataFrame,
        nom_event: str,
        annee_debut: int,
        annee_fin: int,
        top_n: int = 1,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
        df_work = df.copy()
        df_work.columns = df_work.columns.map(lambda x: str(x).strip())

        if "SwimnjkYear" in df_work.columns:
            df_work["year"] = pd.to_numeric(df_work["SwimYear"], errors="coerce")
        elif "Year" in df_work.columns:
            df_work["year"] = pd.to_numeric(df_work["Year"], errors="coerce")
        elif "SwimDate" in df_work.columns:
            df_work["year"] = pd.to_datetime(df_work["SwimDate"], errors="coerce").dt.year
        elif "Date" in df_work.columns:
            df_work["year"] = pd.to_datetime(df_work["Date"], errors="coerce").dt.year
        elif "mpp_date" in df_work.columns:
            df_work["year"] = pd.to_datetime(df_work["mpp_date"], errors="coerce").dt.year
        else:
            return None, pd.DataFrame(), {"message": "Aucune colonne annee/date trouvee."}

        df_event = df_work[
            (df_work["Event"] == nom_event)
            & (df_work["SwimTimeSeconds"].notna())
            & (df_work["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1))
            & (df_work["year"].between(annee_debut, annee_fin))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), {
                "message": f"Aucune performance pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        df_event["swimmer_name"] = df_event["swimmer"].apply(lambda x: x[0]["Name"])
        df_event["swimmer_gender"] = df_event["swimmer"].apply(lambda x: x[0]["Gender"])

        df_top_men = df_event[df_event["swimmer_gender"] == "M"].nsmallest(top_n, "SwimTimeSeconds")
        df_top_women = df_event[df_event["swimmer_gender"] == "F"].nsmallest(top_n, "SwimTimeSeconds")
        df_top_all = pd.concat([df_top_men, df_top_women], ignore_index=True)

        split_data: list[dict[str, object]] = []
        for _, row in df_top_all.iterrows():
            swimmer_name = row["swimmer_name"]
            gender = row["swimmer_gender"]
            splits = row["splits"]
            if not isinstance(splits, list):
                continue
            for split in splits:
                if not isinstance(split, dict):
                    continue
                if split.get("split_speed") is None or split.get("split_distance") is None:
                    continue
                try:
                    distance = int(str(split["split_distance"]).replace(" m", "").strip())
                    speed = float(split["split_speed"])
                except (TypeError, ValueError):
                    continue
                split_data.append(
                    {
                        "swimmer": swimmer_name,
                        "gender": gender,
                        "split_distance": distance,
                        "split_speed": speed,
                    }
                )

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), {"message": "Aucun split valide trouve pour les top nageurs."}

        df_splits["swimmer_label"] = df_splits["swimmer"] + " (" + df_splits["gender"] + ")"
        palette_colors = {"M": "#003E80", "F": "#FF69B4"}
        labels_gender = df_splits[["swimmer_label", "gender"]].drop_duplicates()
        palette_for_plot = {
            row["swimmer_label"]: palette_colors.get(row["gender"], "#777777")
            for _, row in labels_gender.iterrows()
        }

        fig, ax = plt.subplots(figsize=(14, 8))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            hue="swimmer_label",
            style="swimmer_label",
            data=df_splits,
            markers=True,
            dashes=False,
            palette=palette_for_plot,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(
            f"Vitesse par split pour les meilleurs nageurs - {nom_event} ({annee_debut}-{annee_fin})",
            fontsize=16,
        )
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse (m/s)", fontsize=14)
        ax.grid(True)
        ax.legend(title="Nageur (Genre)", bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=12)

        if not df_top_men.empty:
            best_male = df_top_men.nsmallest(1, "SwimTimeSeconds")["swimmer_name"].iloc[0]
            swimmer_data = df_splits[df_splits["swimmer"] == best_male]
            if not swimmer_data.empty:
                label = f"{best_male} ({swimmer_data['gender'].iloc[0]})"
                ax.scatter(
                    swimmer_data["split_distance"].iloc[-1],
                    swimmer_data["split_speed"].iloc[-1],
                    s=150,
                    color=palette_for_plot[label],
                    marker="*",
                    zorder=5,
                )

        if not df_top_women.empty:
            best_female = df_top_women.nsmallest(1, "SwimTimeSeconds")["swimmer_name"].iloc[0]
            swimmer_data = df_splits[df_splits["swimmer"] == best_female]
            if not swimmer_data.empty:
                label = f"{best_female} ({swimmer_data['gender'].iloc[0]})"
                ax.scatter(
                    swimmer_data["split_distance"].iloc[-1],
                    swimmer_data["split_speed"].iloc[-1],
                    s=150,
                    color=palette_for_plot[label],
                    marker="*",
                    zorder=5,
                )

        fig.tight_layout()
        return fig, df_splits, {
            "message": "ok",
            "top_men_count": len(df_top_men),
            "top_women_count": len(df_top_women),
        }

    def plot_vitesse_par_split_top_nageurs_uniques_event_periode(
        self,
        df: pd.DataFrame,
        nom_event: str,
        annee_debut: int,
        annee_fin: int,
        top_n: int = 10,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        df_work = df.copy()
        df_work.columns = df_work.columns.map(lambda x: str(x).strip())

        year_col = None
        if "SwimYear" in df_work.columns:
            year_col = "SwimYear"
        elif "Year" in df_work.columns:
            year_col = "Year"
        else:
            year_candidates = [c for c in df_work.columns if "year" in c.lower()]
            if year_candidates:
                year_col = year_candidates[0]

        if year_col is not None:
            df_work["year"] = pd.to_numeric(df_work[year_col], errors="coerce")
        else:
            date_col = None
            for c in ["SwimDate", "Date", "mpp_date", "MeetDate", "CompetitionDate", "competition_date"]:
                if c in df_work.columns:
                    date_col = c
                    break
            if date_col is None:
                date_candidates = [c for c in df_work.columns if "date" in c.lower()]
                if date_candidates:
                    date_col = date_candidates[0]
            if date_col is None:
                return None, pd.DataFrame(), pd.DataFrame(), {"message": "Aucune colonne pour l'annee trouvee."}
            df_work["year"] = pd.to_datetime(df_work[date_col], errors="coerce").dt.year

        df_event = df_work[
            (df_work["Event"] == nom_event)
            & (df_work["SwimTimeSeconds"].notna())
            & (df_work["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1))
            & (df_work["year"].between(annee_debut, annee_fin))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": f"Aucune performance pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        df_event["swimmer_name"] = df_event["swimmer"].apply(lambda x: x[0].get("Name"))
        df_event["swimmer_gender"] = df_event["swimmer"].apply(lambda x: x[0].get("Gender"))

        df_best_per_swimmer = (
            df_event.sort_values("SwimTimeSeconds", ascending=True).drop_duplicates(subset=["swimmer_name"], keep="first")
        )
        df_top_all = df_best_per_swimmer.nsmallest(top_n, "SwimTimeSeconds").copy()
        if df_top_all.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {
                "message": f"Aucun nageur unique trouve pour {nom_event} entre {annee_debut} et {annee_fin}.",
            }

        split_data: list[dict[str, object]] = []
        for _, row in df_top_all.iterrows():
            swimmer_name = row["swimmer_name"]
            gender = row["swimmer_gender"]
            splits = row["splits"]
            if not isinstance(splits, list):
                continue
            for split in splits:
                if not isinstance(split, dict):
                    continue
                if split.get("split_speed") is None or split.get("split_distance") is None:
                    continue
                try:
                    distance = int(str(split["split_distance"]).replace(" m", "").strip())
                    speed = float(split["split_speed"])
                except (TypeError, ValueError):
                    continue
                split_data.append(
                    {
                        "swimmer": swimmer_name,
                        "gender": gender,
                        "split_distance": distance,
                        "split_speed": speed,
                    }
                )

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {"message": "Aucun split valide trouve pour les top nageurs."}

        df_splits["swimmer_label"] = df_splits["swimmer"] + " (" + df_splits["gender"].fillna("?") + ")"
        palette_colors = {"M": "#003E80", "F": "#FF69B4"}
        labels_gender = df_splits[["swimmer_label", "gender"]].drop_duplicates()
        palette_for_plot = {
            row["swimmer_label"]: palette_colors.get(row["gender"], "#777777")
            for _, row in labels_gender.iterrows()
        }

        fig, ax = plt.subplots(figsize=(14, 8))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            hue="swimmer_label",
            style="swimmer_label",
            data=df_splits,
            markers=True,
            dashes=False,
            palette=palette_for_plot,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(f"Vitesse par split - Top {top_n} nageurs uniques ({nom_event}, {annee_debut}-{annee_fin})", fontsize=16)
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse (m/s)", fontsize=14)
        ax.grid(True)
        ax.legend(title="Nageur (Genre)", bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=11)
        fig.tight_layout()

        return fig, df_splits, df_top_all, {"message": "ok"}

    def plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres(
        self,
        df: pd.DataFrame,
        nageur_cible: str,
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        def norm_txt(value: object) -> str:
            if pd.isna(value):
                return ""
            text = str(value).strip().lower()
            text = unicodedata.normalize("NFD", text)
            text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
            text = " ".join(text.split())
            return text

        df_cmp = df.copy()
        df_cmp = df_cmp.explode("swimmer")
        df_cmp = df_cmp[df_cmp["swimmer"].apply(lambda x: isinstance(x, dict))].copy()

        df_cmp["Nageur"] = df_cmp["swimmer"].apply(lambda x: x.get("Name"))
        df_cmp["Speed"] = pd.to_numeric(df_cmp["Speed"], errors="coerce")
        df_cmp["Distance"] = pd.to_numeric(df_cmp["Distance"], errors="coerce")
        df_cmp["Stroke"] = df_cmp["Stroke"].astype(str).str.strip()

        df_cmp["Nageur_norm"] = df_cmp["Nageur"].map(norm_txt)
        nageur_norm = norm_txt(nageur_cible)
        df_cmp = df_cmp[
            df_cmp["Speed"].notna()
            & df_cmp["Distance"].notna()
            & df_cmp["Stroke"].notna()
            & (df_cmp["Stroke"].str.strip() != "")
        ].copy()
        df_cmp["Groupe"] = df_cmp["Nageur_norm"].apply(
            lambda n: "Nageur cible" if nageur_norm in n else "Autres nageurs"
        )

        nb_target = int((df_cmp["Groupe"] == "Nageur cible").sum())
        if nb_target == 0:
            return None, {
                "message": f"Aucune ligne trouvée pour le nageur '{nageur_cible}'.",
                "examples": df_cmp["Nageur"].dropna().value_counts().head(30),
            }

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

        vmin = min(pivot_target.min().min(skipna=True), pivot_others.min().min(skipna=True))
        vmax = max(pivot_target.max().max(skipna=True), pivot_others.max().max(skipna=True))

        def draw_heatmap(ax: plt.Axes, pivot: pd.DataFrame, title: str, cbar: bool = False) -> None:
            empty = pivot.empty or pivot.dropna(how="all").dropna(axis=1, how="all").empty
            if empty:
                ax.text(0.5, 0.5, "Pas de donnees disponibles", ha="center", va="center", fontsize=12)
                ax.set_title(title)
                ax.set_xlabel("Stroke")
                ax.set_ylabel("Distance")
                ax.set_xticks([])
                ax.set_yticks([])
                return
            sns.heatmap(
                pivot,
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

        fig, axes = plt.subplots(1, 2, figsize=(18, 7), sharey=True)
        draw_heatmap(axes[0], pivot_target, f"{nageur_cible} - Vitesse moyenne", cbar=False)
        draw_heatmap(axes[1], pivot_others, "Autres nageurs - Vitesse moyenne", cbar=True)
        fig.tight_layout()
        return fig, {"message": "ok", "target_count": nb_target}

    def plot_temps_median_vs_meilleur_nageur_par_split_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        df_event = df[
            (df["Event"] == nom_event)
            & (df["SwimTimeSeconds"].notna())
            & (df["swimmer"].apply(len) == 1)
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {"message": f"Aucune performance pour l'event {nom_event}."}

        split_data: list[dict[str, object]] = []
        for _, row in df_event.iterrows():
            splits = row["splits"]
            if not splits:
                continue
            for split in splits:
                if not isinstance(split, dict) or split.get("split_seconds") is None:
                    continue
                try:
                    distance = int(str(split.get("split_distance")).replace(" m", ""))
                    split_seconds = float(split.get("split_seconds"))
                except (TypeError, ValueError):
                    continue
                split_data.append({"split_distance": distance, "split_seconds": split_seconds})

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {"message": "Aucun split valide disponible pour la mediane."}

        df_median_splits = df_splits.groupby("split_distance", as_index=False)["split_seconds"].median()

        df_best = df_event.nsmallest(1, "SwimTimeSeconds").iloc[0]
        best_name = df_best["swimmer"][0]["Name"]
        best_gender = df_best["swimmer"][0]["Gender"]
        best_splits = df_best["splits"]

        split_best_data: list[dict[str, object]] = []
        for split in best_splits:
            if not isinstance(split, dict) or split.get("split_seconds") is None:
                continue
            try:
                distance = int(str(split.get("split_distance")).replace(" m", ""))
                split_seconds = float(split.get("split_seconds"))
            except (TypeError, ValueError):
                continue
            split_best_data.append({"split_distance": distance, "split_seconds": split_seconds})
        df_best_splits = pd.DataFrame(split_best_data)
        if df_best_splits.empty:
            return None, df_median_splits, pd.DataFrame(), {"message": "Aucun split valide pour le meilleur nageur."}

        fig, ax = plt.subplots(figsize=(12, 7))
        sns.lineplot(
            x="split_distance",
            y="split_seconds",
            data=df_median_splits,
            marker="o",
            color="#EA800F",
            label="Temps median de tous les nageurs",
            ax=ax,
        )
        color_best = "#003E80" if best_gender == "M" else "#FF69B4"
        sns.lineplot(
            x="split_distance",
            y="split_seconds",
            data=df_best_splits,
            marker="o",
            color=color_best,
            label=f"Meilleur nageur : {best_name} ({best_gender})",
            ax=ax,
        )
        max_dist = max(df_median_splits["split_distance"].max(), df_best_splits["split_distance"].max())
        ax.set_xticks(range(50, int(max_dist) + 50, 50))
        ax.set_title(f"Temps median vs meilleur nageur - Event {nom_event}", fontsize=16)
        ax.set_xlabel("Distance par split (m)", fontsize=14)
        ax.set_ylabel("Temps (s)", fontsize=14)
        ax.grid(True)
        ax.legend(fontsize=12)
        fig.tight_layout()
        return fig, df_median_splits, df_best_splits, {"message": "ok", "best_name": best_name, "best_gender": best_gender}

    def plot_temps_median_vs_top10_nageurs_par_split_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, dict[str, object]]:
        df_event = df[
            (df["Event"] == nom_event)
            & (df["SwimTimeSeconds"].notna())
            & (df["swimmer"].apply(len) == 1)
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {"message": f"Aucune performance pour l'event {nom_event}."}

        split_data: list[dict[str, object]] = []
        for _, row in df_event.iterrows():
            for split in row.get("splits", []) or []:
                if not isinstance(split, dict) or split.get("split_seconds") is None:
                    continue
                try:
                    distance = int(str(split.get("split_distance")).replace(" m", ""))
                    split_seconds = float(split.get("split_seconds"))
                except (TypeError, ValueError):
                    continue
                split_data.append({"split_distance": distance, "split_seconds": split_seconds})

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), pd.DataFrame(), {"message": "Aucun split valide pour l'ensemble des nageurs."}
        df_median_splits = df_splits.groupby("split_distance", as_index=False)["split_seconds"].median()

        df_top10 = df_event.nsmallest(10, "SwimTimeSeconds")
        top10_split_data: list[dict[str, object]] = []
        for _, row in df_top10.iterrows():
            for split in row.get("splits", []) or []:
                if not isinstance(split, dict) or split.get("split_seconds") is None:
                    continue
                try:
                    distance = int(str(split.get("split_distance")).replace(" m", ""))
                    split_seconds = float(split.get("split_seconds"))
                except (TypeError, ValueError):
                    continue
                top10_split_data.append({"split_distance": distance, "split_seconds": split_seconds})

        df_top10_splits = pd.DataFrame(top10_split_data)
        if df_top10_splits.empty:
            return None, df_median_splits, pd.DataFrame(), {"message": "Aucun split valide pour le top 10."}
        df_top10_median = df_top10_splits.groupby("split_distance", as_index=False)["split_seconds"].median()

        fig, ax = plt.subplots(figsize=(12, 7))
        sns.lineplot(
            x="split_distance",
            y="split_seconds",
            data=df_median_splits,
            marker="o",
            color="#EA800F",
            label="Temps median de tous les nageurs",
            ax=ax,
        )
        sns.lineplot(
            x="split_distance",
            y="split_seconds",
            data=df_top10_median,
            marker="o",
            color="#003E80",
            label="Temps median des 10 meilleurs nageurs",
            ax=ax,
        )
        max_dist = max(df_median_splits["split_distance"].max(), df_top10_median["split_distance"].max())
        ax.set_xticks(range(50, int(max_dist) + 50, 50))
        ax.set_title(f"Temps median vs Top 10 nageurs - Event {nom_event}", fontsize=16)
        ax.set_xlabel("Distance par split (m)", fontsize=14)
        ax.set_ylabel("Temps (s)", fontsize=14)
        ax.grid(True)
        ax.legend(fontsize=12)
        fig.tight_layout()
        return fig, df_median_splits, df_top10_median, {"message": "ok", "top10_count": len(df_top10)}

    def plot_vitesse_mediane_par_split_selon_genre_top_n_event(
        self,
        df: pd.DataFrame,
        nom_event: str,
        top_n: int = 10,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, dict[str, object]]:
        df_event = df[
            (df["Event"] == nom_event)
            & (df["SwimTimeSeconds"].notna())
            & (df["swimmer"].apply(lambda x: isinstance(x, list) and len(x) == 1))
        ].copy()
        if df_event.empty:
            return None, pd.DataFrame(), {"message": f"Aucune performance pour l'event {nom_event}."}

        df_event["swimmer_name"] = df_event["swimmer"].apply(lambda x: x[0]["Name"])
        df_event["swimmer_gender"] = df_event["swimmer"].apply(lambda x: x[0]["Gender"])
        df_top_men = df_event[df_event["swimmer_gender"] == "M"].nsmallest(top_n, "SwimTimeSeconds")
        df_top_women = df_event[df_event["swimmer_gender"] == "F"].nsmallest(top_n, "SwimTimeSeconds")
        df_top_all = pd.concat([df_top_men, df_top_women], ignore_index=True)

        split_data: list[dict[str, object]] = []
        for _, row in df_top_all.iterrows():
            gender = row["swimmer_gender"]
            for split in row.get("splits", []) or []:
                if not isinstance(split, dict):
                    continue
                try:
                    distance = int(str(split.get("split_distance")).replace(" m", "").strip())
                    split_speed = float(split.get("split_speed"))
                except (TypeError, ValueError):
                    continue
                split_data.append(
                    {
                        "gender": gender,
                        "split_distance": distance,
                        "split_speed": split_speed,
                    }
                )

        df_splits = pd.DataFrame(split_data)
        if df_splits.empty:
            return None, pd.DataFrame(), {"message": "Aucune donnée de split exploitable."}

        df_med = (
            df_splits.groupby(["gender", "split_distance"])["split_speed"]
            .median()
            .reset_index()
        )

        fig, ax = plt.subplots(figsize=(12, 7))
        sns.lineplot(
            x="split_distance",
            y="split_speed",
            hue="gender",
            data=df_med,
            marker="o",
            palette={"M": "#003E80", "F": "#FF69B4"},
            linewidth=2.5,
            ax=ax,
        )
        ax.set_xticks(range(50, int(df_splits["split_distance"].max()) + 50, 50))
        ax.set_title(f"Vitesse mediane par split selon le genre - {nom_event}", fontsize=16)
        ax.set_xlabel("Distance par splits (m)", fontsize=14)
        ax.set_ylabel("Vitesse mediane (m/s)", fontsize=14)
        ax.grid(True)
        ax.legend(title="Genre", fontsize=12)
        fig.tight_layout()
        return fig, df_med, {"message": "ok", "top_men_count": len(df_top_men), "top_women_count": len(df_top_women)}

    def plot_relais_split_speed_par_distance(
        self,
        df: pd.DataFrame,
        nom_event: str,
    ) -> tuple[Optional[plt.Figure], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
        def parse_dist(value: object) -> Optional[int]:
            try:
                return int(str(value).replace(" m", "").strip())
            except (TypeError, ValueError):
                return None

        def is_relay_swimmers(swimmers: object) -> bool:
            return isinstance(swimmers, list) and len(swimmers) > 1 and all(isinstance(s, dict) for s in swimmers)

        df_relay = df[
            (df["Event"] == nom_event) & df["swimmer"].apply(is_relay_swimmers)
        ].copy()

        rows: list[dict[str, object]] = []
        for idx, row in df_relay.iterrows():
            splits = row.get("splits", [])
            if not isinstance(splits, list):
                continue
            for split in splits:
                if not isinstance(split, dict):
                    continue
                dist = parse_dist(split.get("split_distance"))
                speed = split.get("split_speed")
                if dist is None or speed is None:
                    continue
                try:
                    speed = float(speed)
                except (TypeError, ValueError):
                    continue
                rows.append(
                    {
                        "perf_idx": idx,
                        "split_distance_m": dist,
                        "split_speed": speed,
                        "nb_swimmers": len(row["swimmer"]),
                    }
                )

        df_pts = pd.DataFrame(rows)
        if df_pts.empty:
            return None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {
                "message": "Aucun point relai pour cet event (ou splits vides / split_speed manquant).",
                "relay_perf_count": len(df_relay),
            }

        mean_by_dist = (
            df_pts.groupby("split_distance_m", as_index=False)["split_speed"]
            .mean()
            .sort_values("split_distance_m")
        )
        median_by_dist = (
            df_pts.groupby("split_distance_m", as_index=False)["split_speed"]
            .median()
            .sort_values("split_distance_m")
        )

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.scatter(
            df_pts["split_distance_m"],
            df_pts["split_speed"],
            alpha=0.35,
            s=28,
            edgecolors="none",
        )
        ax.plot(
            mean_by_dist["split_distance_m"],
            mean_by_dist["split_speed"],
            color="#DA7B27",
            linewidth=2.7,
            marker="o",
            label="Moyenne par split_distance_m",
        )
        ax.plot(
            median_by_dist["split_distance_m"],
            median_by_dist["split_speed"],
            color="#1F77B4",
            linewidth=2.4,
            linestyle="--",
            marker="s",
            label="Mediane par split_distance_m",
        )
        ax.set_title(f"{nom_event} - relais uniquement - split_speed en fonction de la distance", fontsize=13, fontweight="bold")
        ax.set_xlabel("Distance du split (m)")
        ax.set_ylabel("split_speed")
        ax.grid(alpha=0.25)
        ax.legend()
        fig.tight_layout()
        return fig, df_pts, mean_by_dist, median_by_dist, {
            "message": "ok",
            "relay_perf_count": len(df_relay),
            "points_count": len(df_pts),
        }

    def plot_performance_corridor_plot_time(
        self,
        df: pd.DataFrame,
        nom_event: str,
        nom_nageur: str,
        year_of_birth: int,
        age_min: int = 14,
        age_max: int = 35,
        solo_only: bool = True,
        min_points: int = 5,
        figsize: tuple[int, int] = (12, 8),
    ) -> tuple[Optional[plt.Figure], dict[str, object]]:
        data = df.copy()
        if solo_only:
            data = data[
                data["swimmer"].apply(
                    lambda x: isinstance(x, list) and len(x) == 1
                )
            ].copy()

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
        data["SwimYear"] = pd.to_datetime(data.get("SwimDate"), errors="coerce").dt.year
        data["Age_swim"] = data["Age_json"]

        mask = (
            data["Age_swim"].isna()
            & data["Year_of_birth"].notna()
            & data["SwimYear"].notna()
        )
        data.loc[mask, "Age_swim"] = data.loc[mask, "SwimYear"] - data.loc[mask, "Year_of_birth"]
        data["Age_swim"] = pd.to_numeric(data["Age_swim"], errors="coerce").astype("Int64")

        long_df = data[
            (data["Event"] == nom_event)
            & (data["SwimTimeSeconds"].notna())
            & (data["Name"].notna())
            & (data["Gender"].notna())
            & (data["Age_swim"].notna())
            & (data["Year_of_birth"].notna())
        ].copy()
        if long_df.empty:
            return None, {"message": f"Aucune donnee pour {nom_event}"}

        target_name = str(nom_nageur).strip().lower()
        swimmer_data = long_df[
            (long_df["Name"].astype(str).str.strip().str.lower() == target_name)
            & (long_df["Year_of_birth"] == year_of_birth)
        ].copy()
        if swimmer_data.empty:
            return None, {
                "message": f"Nageur introuvable : {nom_nageur} ({year_of_birth})",
                "examples": long_df["Name"].dropna().drop_duplicates().head(10).tolist(),
            }

        gender = swimmer_data["Gender"].mode().iloc[0]
        long_df = long_df[long_df["Gender"] == gender].copy()
        swimmer_name = swimmer_data.iloc[0]["Name"]
        swimmer_yob = swimmer_data.iloc[0]["Year_of_birth"]

        grouped = long_df.groupby("Age_swim")["SwimTimeSeconds"].agg(list)
        grouped = grouped.apply(lambda x: x if len(x) >= min_points else np.nan).dropna()
        if grouped.empty:
            return None, {
                "message": "Pas assez de points pour calculer les percentiles.",
                "gender": gender,
            }

        percentiles = [10, 25, 50, 75, 90]
        df_percentiles = pd.DataFrame(
            {f"p{p}": grouped.apply(lambda x: np.percentile(x, p)) for p in percentiles}
        )
        df_percentiles = df_percentiles.loc[
            (df_percentiles.index >= age_min)
            & (df_percentiles.index <= age_max)
        ]
        if df_percentiles.empty:
            return None, {
                "message": "Aucune tranche d'age disponible sur la plage demandee.",
                "gender": gender,
            }

        df_swimmer = long_df[
            (long_df["Name"] == swimmer_name)
            & (long_df["Year_of_birth"] == swimmer_yob)
        ].sort_values("Age_swim")
        if df_swimmer.empty:
            return None, {"message": "Aucune performance du nageur cible apres filtrage."}

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
        ax.set_xlabel("Age")
        ax.set_ylabel("Temps (secondes)")
        ax.set_title(f"Couloir de performance - {nom_event}")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()

        return fig, {
            "message": "ok",
            "gender": gender,
            "swimmer_name": swimmer_name,
            "year_of_birth": swimmer_yob,
            "points_swimmer": int(len(df_swimmer)),
            "ages_available": [int(x) for x in df_percentiles.index.tolist()],
        }

    def build_figure(self, spec: GraphSpec, df: pd.DataFrame, **kwargs: Any) -> Any:
        method: Callable[..., Any] = getattr(self, spec.method_name)
        return method(df, **kwargs)


Graphe1 = GraphSpec(
    key="histogramme_simple",
    name="Histogramme simple",
    category="Distributions de temps",
    method_name="plot_histogramme_simple",
)
Graphe2 = GraphSpec(
    key="camembert_sexe_global",
    name="Camembert par sexe (global)",
    category="Effectifs et repartition par sexe",
    method_name="plot_camembert_sexe_global",
)
Graphe3 = GraphSpec(
    key="boxplot_temps_par_nage",
    name="Distribution des temps par type de nage (boxplot)",
    category="Comparaison des temps par nage",
    method_name="plot_boxplot_temps_par_nage",
)
Graphe4 = GraphSpec(
    key="top10_clubs",
    name="Top 10 clubs par participation",
    category="Clubs",
    method_name="plot_top10_clubs",
)
Graphe5 = GraphSpec(
    key="heatmap_vitesse_moyenne",
    name="Heatmap vitesse moyenne (distance x nage)",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_heatmap_vitesse_moyenne",
)
Graphe6 = GraphSpec(
    key="histogramme_densite",
    name="Histogramme + densite",
    category="Distributions de temps",
    method_name="plot_histogramme_densite",
)
Graphe7 = GraphSpec(
    key="histogramme_cumulatif",
    name="Histogramme cumulatif",
    category="Distributions de temps",
    method_name="plot_histogramme_cumulatif",
)
Graphe8 = GraphSpec(
    key="nombre_performances_par_epreuve",
    name="Nombre de performances par epreuve",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_epreuve",
)
Graphe9 = GraphSpec(
    key="nombre_performances_par_epreuve_lcm_scm",
    name="Nombre de performances par epreuve (LCM + SCM)",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_epreuve_lcm_scm",
)
Graphe10 = GraphSpec(
    key="nombre_performances_par_sexe",
    name="Nombre de performances par sexe",
    category="Effectifs et repartition par sexe",
    method_name="plot_nombre_performances_par_sexe",
)
Graphe11 = GraphSpec(
    key="temps_median_top10_clubs_par_event",
    name="Temps médian top 10 clubs par event",
    category="Clubs",
    method_name="plot_temps_median_top10_clubs_par_event",
)
Graphe12 = GraphSpec(
    key="evolution_temps_nage",
    name="Évolution des temps de nage",
    category="Distributions de temps",
    method_name="plot_evolution_temps_nage",
)
Graphe13 = GraphSpec(
    key="top10_nageurs_meilleur_temps_par_event",
    name="Top 10 nageurs meilleur temps par event",
    category="Classements par epreuve",
    method_name="plot_top10_nageurs_meilleur_temps_par_event",
)
Graphe14 = GraphSpec(
    key="camembert_sexe_par_event",
    name="Camembert par sexe (par event)",
    category="Effectifs et repartition par sexe",
    method_name="plot_camembert_sexe_par_event",
)
Graphe15 = GraphSpec(
    key="vitesse_max_par_split_et_nage",
    name="Vitesse max par split et nage",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_vitesse_max_par_split_et_nage",
)
Graphe16 = GraphSpec(
    key="vitesse_moyenne_mediane_par_split_et_nage",
    name="Vitesse moyenne et mediane par split et nage",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_vitesse_moyenne_mediane_par_split_et_nage",
)
Graphe17 = GraphSpec(
    key="split_speed_analysis_by_gender_with_targets",
    name="Analyse split_speed par genre avec nageurs cibles",
    category="Synthese des vitesses par distance et nage",
    method_name="plot_split_speed_analysis_by_gender_with_targets",
)
Graphe18 = GraphSpec(
    key="vitesse_par_split_pour_nageur_event",
    name="Vitesse par split pour un nageur et un event",
    category="Analyse individuelle par epreuve",
    method_name="plot_vitesse_par_split_pour_nageur_event",
)
Graphe19 = GraphSpec(
    key="vitesse_par_split_meilleur_nageur_event_periode",
    name="Vitesse par split du meilleur nageur par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_meilleur_nageur_event_periode",
)
Graphe20 = GraphSpec(
    key="vitesse_par_split_top_nageurs_hf_event_periode",
    name="Vitesse par split des top nageurs H/F par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_top_nageurs_hf_event_periode",
)
Graphe21 = GraphSpec(
    key="vitesse_par_split_top_nageurs_uniques_event_periode",
    name="Vitesse par split des top nageurs uniques par event et periode",
    category="Classements par epreuve",
    method_name="plot_vitesse_par_split_top_nageurs_uniques_event_periode",
)
Graphe22 = GraphSpec(
    key="comparaison_vitesse_moyenne_heatmap_nageur_vs_autres",
    name="Comparaison heatmap vitesse moyenne nageur vs autres",
    category="Analyse individuelle par epreuve",
    method_name="plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres",
)
Graphe23 = GraphSpec(
    key="temps_median_vs_meilleur_nageur_par_split_event",
    name="Temps median vs meilleur nageur par split et event",
    category="Analyse individuelle par epreuve",
    method_name="plot_temps_median_vs_meilleur_nageur_par_split_event",
)
Graphe24 = GraphSpec(
    key="temps_median_vs_top10_nageurs_par_split_event",
    name="Temps median vs top10 nageurs par split et event",
    category="Analyse individuelle par epreuve",
    method_name="plot_temps_median_vs_top10_nageurs_par_split_event",
)
Graphe25 = GraphSpec(
    key="vitesse_mediane_par_split_selon_genre_top_n_event",
    name="Vitesse mediane par split selon genre top-n event",
    category="Classements par epreuve",
    method_name="plot_vitesse_mediane_par_split_selon_genre_top_n_event",
)
Graphe26 = GraphSpec(
    key="relais_split_speed_par_distance",
    name="Vitesse split relais par distance",
    category="Analyse individuelle par epreuve",
    method_name="plot_relais_split_speed_par_distance",
)
Graphe27 = GraphSpec(
    key="performance_corridor_plot_time",
    name="Couloir de performance sur SwimTime",
    category="Analyse individuelle par epreuve",
    method_name="plot_performance_corridor_plot_time",
)

GRAPHES_NOTEBOOK: List[GraphSpec] = [Graphe1, Graphe2, Graphe3, Graphe4, Graphe5, Graphe6, Graphe7, Graphe8, Graphe9, Graphe10, Graphe11, Graphe12, Graphe13, Graphe14, Graphe15, Graphe16, Graphe17, Graphe18, Graphe19, Graphe20, Graphe21, Graphe22, Graphe23, Graphe24, Graphe25, Graphe26, Graphe27]
GRAPHES_PAR_KEY: Dict[str, GraphSpec] = {g.key: g for g in GRAPHES_NOTEBOOK}

# Catégorie JSON pour les entrées préchargées depuis GRAPHES_NOTEBOOK (hors menus Flet).
SERVICE_NOTEBOOK_JSON_CATEGORY = "_service_notebook"


def _nb_first_event_label(df_nav: pd.DataFrame) -> Optional[str]:
    need = ("Stroke", "Distance", "PoolLabel")
    if df_nav.empty or not all(c in df_nav.columns for c in need):
        return None
    sub = df_nav.dropna(subset=list(need))
    if sub.empty:
        return None
    r = sub.iloc[0]
    try:
        d = int(float(r["Distance"]))
    except (TypeError, ValueError):
        return None
    st = str(r["Stroke"]).strip()
    pl = str(r["PoolLabel"]).strip()
    if not st or not pl:
        return None
    return f"{d} {st} {pl}"


def _nb_first_pool_label(df_nav: pd.DataFrame) -> Optional[str]:
    if "PoolLabel" not in df_nav.columns or df_nav.empty:
        return None
    pools = df_nav["PoolLabel"].dropna().astype(str).str.strip()
    if pools.empty:
        return None
    return str(pools.iloc[0])


def _nb_first_swimmer_name(df_nav: pd.DataFrame) -> Optional[str]:
    if "swimmer" not in df_nav.columns:
        return None
    for swimmers in df_nav["swimmer"].tolist():
        if isinstance(swimmers, list) and swimmers and isinstance(swimmers[0], dict):
            n = swimmers[0].get("Name")
            if n:
                return str(n).strip()
    return None


def _nb_year_bounds(df_nav: pd.DataFrame) -> Tuple[int, int]:
    if "SwimDate" not in df_nav.columns or df_nav.empty:
        return 2000, 2024
    years = pd.to_datetime(df_nav["SwimDate"], errors="coerce").dt.year.dropna()
    if years.empty:
        return 2000, 2024
    ymin, ymax = int(years.min()), int(years.max())
    if ymin > ymax:
        return 2000, 2024
    return ymin, ymax


def _nb_first_solo_name_yob_for_event(
    df_nav: pd.DataFrame, nom_event: str
) -> Tuple[Optional[str], Optional[int]]:
    if df_nav.empty or "Event" not in df_nav.columns:
        return None, None
    df_e = df_nav[df_nav["Event"].astype(str).str.strip() == str(nom_event).strip()]
    for _, row in df_e.iterrows():
        sw = row.get("swimmer")
        if not isinstance(sw, list) or len(sw) != 1 or not isinstance(sw[0], dict):
            continue
        d0 = sw[0]
        name = d0.get("Name")
        yob = d0.get("Year_of_birth")
        if not name:
            continue
        try:
            if yob is not None and yob == yob:
                yob_i = int(yob)
            else:
                yob_i = None
        except (TypeError, ValueError):
            yob_i = None
        if yob_i is None:
            continue
        return str(name).strip(), yob_i
    return None, None


def notebook_prefetch_kwargs_for_spec(
    spec: GraphSpec, df: pd.DataFrame, df_nav: pd.DataFrame
) -> Optional[Dict[str, Any]]:
    """
    Kwargs passés à ``ServiceGraphe.build_figure`` pour un préchargement automatique.
    Retourne ``None`` si les données minimales (ex. ``nom_event``) manquent.
    """
    nom = _nb_first_event_label(df_nav)
    swimmer = _nb_first_swimmer_name(df_nav)
    y0, y1 = _nb_year_bounds(df_nav)
    pool = _nb_first_pool_label(df_nav)

    m = spec.method_name
    if m in (
        "plot_histogramme_simple",
        "plot_histogramme_densite",
        "plot_histogramme_cumulatif",
        "plot_camembert_sexe_global",
        "plot_boxplot_temps_par_nage",
        "plot_top10_clubs",
        "plot_heatmap_vitesse_moyenne",
        "plot_nombre_performances_par_epreuve_lcm_scm",
        "plot_nombre_performances_par_sexe",
        "plot_vitesse_max_par_split_et_nage",
        "plot_vitesse_moyenne_mediane_par_split_et_nage",
    ):
        return {}
    if m == "plot_nombre_performances_par_epreuve":
        if not pool:
            return None
        return {"course_type": pool}
    if m in ("plot_temps_median_top10_clubs_par_event", "plot_top10_nageurs_meilleur_temps_par_event"):
        if not nom:
            return None
        return {"nom_event": nom}
    if m == "plot_evolution_temps_nage":
        return {"start_year": 2000, "sample_size": min(5000, max(1, len(df)))}
    if m == "plot_camembert_sexe_par_event":
        if not nom:
            return None
        return {"nom_event": nom}
    if m == "plot_split_speed_analysis_by_gender_with_targets":
        if not nom:
            return None
        targets: List[str] = []
        if swimmer:
            targets = [swimmer]
        return {
            "nom_event": nom,
            "swimmer_targets": targets,
            "target_colors": {},
        }
    if m == "plot_vitesse_par_split_pour_nageur_event":
        if not nom or not swimmer:
            return None
        return {"nom_nageur": swimmer, "nom_event": nom}
    if m == "plot_vitesse_par_split_meilleur_nageur_event_periode":
        if not nom:
            return None
        return {"nom_event": nom, "annee_debut": y0, "annee_fin": y1}
    if m == "plot_vitesse_par_split_top_nageurs_hf_event_periode":
        if not nom:
            return None
        return {"nom_event": nom, "annee_debut": y0, "annee_fin": y1, "top_n": 1}
    if m == "plot_vitesse_par_split_top_nageurs_uniques_event_periode":
        if not nom:
            return None
        return {"nom_event": nom, "annee_debut": y0, "annee_fin": y1, "top_n": 10}
    if m == "plot_comparaison_vitesse_moyenne_heatmap_nageur_vs_autres":
        if not swimmer:
            return None
        return {"nageur_cible": swimmer}
    if m in (
        "plot_temps_median_vs_meilleur_nageur_par_split_event",
        "plot_temps_median_vs_top10_nageurs_par_split_event",
        "plot_vitesse_mediane_par_split_selon_genre_top_n_event",
        "plot_relais_split_speed_par_distance",
    ):
        if not nom:
            return None
        if m == "plot_vitesse_mediane_par_split_selon_genre_top_n_event":
            return {"nom_event": nom, "top_n": 10}
        return {"nom_event": nom}
    if m == "plot_performance_corridor_plot_time":
        if not nom:
            return None
        name, yob = _nb_first_solo_name_yob_for_event(df_nav, nom)
        if not name or yob is None:
            return None
        return {"nom_event": nom, "nom_nageur": name, "year_of_birth": int(yob)}
    return {}


def unwrap_matplotlib_figure(result: Any) -> Optional[plt.Figure]:
    if result is None:
        return None
    if isinstance(result, plt.Figure):
        return result
    if isinstance(result, tuple) and result and isinstance(result[0], plt.Figure):
        return result[0]
    return None

