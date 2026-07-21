"""Tracé client des payloads couloir / comparaison (Matplotlib).

Consomme uniquement les données structurées de l'API (``bands``, ``points``),
conformément au contrat NiceGUI / iOS.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


# Aligné sur la charte couloirs Pacing (analytics)
_BELOW_OUTER = "#bfdbfe"
_BELOW_INNER = "#3b82f6"
_ABOVE_OUTER = "#fde68a"
_ABOVE_INNER = "#f59e0b"
_MEDIAN = "#666666"
_SWIMMER_A = "#dc2626"
_SWIMMER_B = "#059669"


def _band_x_values(bands: Sequence[Dict[str, Any]]) -> Tuple[List[Any], str]:
    """
    Déduit l'axe X (âge numérique ou catégories USA).

    Args:
        bands (Sequence[Dict[str, Any]]): Bandes percentiles API.

    Returns:
        Tuple[List[Any], str]: Valeurs X et libellé d'axe.
    """
    if not bands:
        return [], "Âge (années)"
    if bands[0].get("age_group") is not None and bands[0].get("age") is None:
        return [str(b.get("age_group") or "") for b in bands], "Catégorie d'âge"
    return [b.get("age") for b in bands], "Âge (années)"


def _percentile_series(
    bands: Sequence[Dict[str, Any]], key: str
) -> List[Optional[float]]:
    """
    Extrait une série de percentiles.

    Args:
        bands (Sequence[Dict[str, Any]]): Bandes API.
        key (str): Clé (``p10``, ``p50``, …).

    Returns:
        List[Optional[float]]: Valeurs (secondes) ou None.
    """
    return [b.get(key) for b in bands]


def _plot_bands(ax: Any, bands: Sequence[Dict[str, Any]], xs: List[Any]) -> None:
    """
    Trace les rubans P10–P90 et la médiane.

    Args:
        ax (Any): Axes Matplotlib.
        bands (Sequence[Dict[str, Any]]): Bandes API.
        xs (List[Any]): Coordonnées X alignées.
    """
    if not bands or not xs:
        return
    p10 = _percentile_series(bands, "p10")
    p25 = _percentile_series(bands, "p25")
    p50 = _percentile_series(bands, "p50")
    p75 = _percentile_series(bands, "p75")
    p90 = _percentile_series(bands, "p90")

    # fill_between exige des x numériques pour l'interpolation ; catégories → indices
    use_categories = xs and isinstance(xs[0], str)
    x_plot: List[Any] = list(range(len(xs))) if use_categories else list(xs)

    def _fill(y_lo: List[Optional[float]], y_hi: List[Optional[float]], color: str, alpha: float) -> None:
        if any(v is None for v in y_lo + y_hi):
            return
        ax.fill_between(x_plot, y_lo, y_hi, color=color, alpha=alpha, linewidth=0)

    _fill(p10, p25, _BELOW_OUTER, 0.40)
    _fill(p25, p50, _BELOW_INNER, 0.55)
    _fill(p50, p75, _ABOVE_INNER, 0.55)
    _fill(p75, p90, _ABOVE_OUTER, 0.40)

    if not any(v is None for v in p50):
        ax.plot(x_plot, p50, color=_MEDIAN, linewidth=2.4, label="Médiane (P50)")

    if use_categories:
        ax.set_xticks(list(range(len(xs))))
        ax.set_xticklabels([str(x) for x in xs], rotation=45, ha="right")


def _plot_swimmer(
    ax: Any,
    swimmer: Optional[Dict[str, Any]],
    *,
    color: str,
    label: Optional[str] = None,
    categorical_xs: Optional[List[str]] = None,
) -> None:
    """
    Superpose la courbe d'un nageur.

    Args:
        ax (Any): Axes Matplotlib.
        swimmer (Optional[Dict[str, Any]]): Payload nageur API.
        color (str): Couleur de la courbe.
        label (Optional[str]): Libellé légende.
        categorical_xs (Optional[List[str]]): Ordre des catégories USA.
    """
    if not swimmer:
        return
    points = swimmer.get("points") or []
    if not points:
        return

    name = swimmer.get("name") or "Nageur"
    yob = swimmer.get("year_of_birth")
    curve_label = label or (f"{name} ({yob})" if yob else name)

    if points[0].get("age_group") is not None and points[0].get("age") is None:
        groups = [str(p.get("age_group") or "") for p in points]
        times = [float(p["time_s"]) for p in points]
        if categorical_xs:
            index = {g: i for i, g in enumerate(categorical_xs)}
            xs = [index[g] for g in groups if g in index]
            ys = [t for g, t in zip(groups, times) if g in index]
        else:
            xs = list(range(len(groups)))
            ys = times
            ax.set_xticks(xs)
            ax.set_xticklabels(groups, rotation=45, ha="right")
        ax.plot(xs, ys, color=color, marker="o", linewidth=2.0, label=curve_label)
    else:
        xs = [p.get("age") for p in points if p.get("age") is not None]
        ys = [float(p["time_s"]) for p in points if p.get("age") is not None]
        if xs and ys:
            ax.plot(xs, ys, color=color, marker="o", linewidth=2.0, label=curve_label)


def build_corridor_figure(
    payload: Dict[str, Any],
    *,
    title: Optional[str] = None,
) -> Figure:
    """
    Construit une figure couloir à partir d'un payload ``/couloir``.

    Args:
        payload (Dict[str, Any]): Réponse API couloir.
        title (Optional[str]): Titre override.

    Returns:
        Figure: Figure Matplotlib prête à afficher.
    """
    bands = list(payload.get("bands") or [])
    meta = payload.get("meta") or {}
    xs, xlabel = _band_x_values(bands)
    categorical = bool(xs) and isinstance(xs[0], str)

    fig, ax = plt.subplots(figsize=(10, 5.5), layout="constrained")
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f8fafc")

    _plot_bands(ax, bands, xs)
    _plot_swimmer(
        ax,
        payload.get("swimmer"),
        color=_SWIMMER_A,
        categorical_xs=xs if categorical else None,
    )

    event = meta.get("event") or ""
    country = meta.get("country") or ""
    ax.set_title(title or f"Couloir de performance — {event} ({country})")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Temps (s)")
    ax.invert_yaxis()
    ax.grid(True, alpha=0.18)
    ax.legend(loc="best", frameon=False)
    return fig


def build_compare_figure(
    payload: Dict[str, Any],
    *,
    title: Optional[str] = None,
) -> Figure:
    """
    Construit une figure de comparaison à partir de ``/comparaison``.

    Args:
        payload (Dict[str, Any]): Réponse API comparaison.
        title (Optional[str]): Titre override.

    Returns:
        Figure: Figure Matplotlib.
    """
    bands = list(payload.get("bands") or [])
    meta = payload.get("meta") or {}
    xs, xlabel = _band_x_values(bands)
    categorical = bool(xs) and isinstance(xs[0], str)

    fig, ax = plt.subplots(figsize=(10, 5.5), layout="constrained")
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#f8fafc")

    _plot_bands(ax, bands, xs)
    cat = xs if categorical else None
    _plot_swimmer(ax, payload.get("swimmer_a"), color=_SWIMMER_A, label=None, categorical_xs=cat)
    _plot_swimmer(ax, payload.get("swimmer_b"), color=_SWIMMER_B, label=None, categorical_xs=cat)

    event = meta.get("event") or ""
    country = meta.get("country") or ""
    ax.set_title(title or f"Comparaison — {event} (réf. {country})")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Temps (s)")
    ax.invert_yaxis()
    ax.grid(True, alpha=0.18)
    ax.legend(loc="best", frameon=False)
    return fig
