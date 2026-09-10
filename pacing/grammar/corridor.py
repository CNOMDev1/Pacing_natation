"""Recette du couloir de performance : la définition unique du graphique.

Ce module répond une seule fois à la question « qu'est-ce qu'un couloir de
performance ? » — quelles variables, quelle transformation, quelles bandes,
quelles échelles, quelle légende. Avant lui, la réponse était réécrite en
instructions de dessin dans ``pacing/ui/web/charts.py``, dans
``pacing/rendering/corridor_plots.py`` et dans ``CorridorChartView.swift``.

Deux portes d'entrée, une seule recette :

- ``corridor_spec_from_payload`` / ``compare_spec_from_payload`` partent du
  payload de l'API (NiceGUI, DearPyGUI, iOS).
- ``percentile_corridor_spec`` part d'un DataFrame de percentiles déjà agrégé
  (Flet, via ``pacing.rendering.corridor_plots``).

Les deux délèguent la construction des géométries à ``corridor_band_layers``,
qui est donc le seul endroit du projet où la structure du couloir est décrite.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from pacing.analytics.corridor_data import (
    CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR,
    CORRIDOR_ABOVE_MEDIAN_INNER_COLOR,
    CORRIDOR_ABOVE_MEDIAN_OUTER_COLOR,
    CORRIDOR_ANNOTATION_COLOR,
    CORRIDOR_BAND_EDGE_ALPHA,
    CORRIDOR_BAND_INNER_ALPHA,
    CORRIDOR_BAND_OUTER_ALPHA,
    CORRIDOR_BELOW_MEDIAN_EDGE_COLOR,
    CORRIDOR_BELOW_MEDIAN_INNER_COLOR,
    CORRIDOR_BELOW_MEDIAN_OUTER_COLOR,
    CORRIDOR_CHART_AXES_FACECOLOR,
    CORRIDOR_CHART_FIGURE_FACECOLOR,
    CORRIDOR_FR_SWIMMER_COLOR,
    CORRIDOR_GRID_ALPHA,
    CORRIDOR_MA_SWIMMER_COLOR,
    CORRIDOR_MEDIAN_COLOR,
    CORRIDOR_MEDIAN_LINEWIDTH,
)
from pacing.grammar.spec import (
    Area,
    ChartSpec,
    DataTable,
    Geom,
    LegendEntry,
    Line,
    Point,
    Scale,
    Theme,
)

#: Charte visuelle Pacing, dérivée des constantes d'``analytics.corridor_data``.
#: Aucun moteur ne redéfinit ces valeurs : ils les lisent ici.
PACING_THEME = Theme(
    figure_facecolor=CORRIDOR_CHART_FIGURE_FACECOLOR,
    axes_facecolor=CORRIDOR_CHART_AXES_FACECOLOR,
    grid_color="#94a3b8",
    grid_alpha=CORRIDOR_GRID_ALPHA,
    grid_linewidth=0.6,
    annotation_color=CORRIDOR_ANNOTATION_COLOR,
    marker_edge_color="#1e293b",
)

#: Transformation statistique déclarée par la recette (calculée en amont).
CORRIDOR_STAT = "percentiles(10, 25, 50, 75, 90) group_by=x"

#: Motif de pointillés du second nageur (encodage redondant à la couleur).
SWIMMER_DASH_PATTERN: Tuple[float, ...] = (5.0, 3.0)

_NO_LEGEND = "_nolegend_"

_BANDS = "bands"


def _label(value: Optional[str]) -> Optional[str]:
    """Normalise un libellé de légende matplotlib en libellé de recette.

    Args:
        value (Optional[str]): Libellé, éventuellement ``"_nolegend_"``.

    Returns:
        Optional[str]: ``None`` si l'entrée doit rester hors légende.
    """
    if value is None or value == _NO_LEGEND:
        return None
    return value


def corridor_band_layers(
    rows: Sequence[Dict[str, Any]],
    *,
    source: str = _BANDS,
    outer_low: str = "p10",
    outer_high: str = "p90",
    inner_low: str = "p25",
    inner_high: str = "p75",
    median_col: str = "p50",
    outer_label_below: Optional[str] = "Couloir P10–P50 (sous médiane)",
    outer_label_above: Optional[str] = "Couloir P50–P90 (au-dessus médiane)",
    inner_label_below: Optional[str] = None,
    inner_label_above: Optional[str] = None,
    median_label: Optional[str] = "Médiane du groupe",
    zorder_bands: int = 1,
    zorder_median: int = 3,
) -> Tuple[Geom, ...]:
    """Construit les géométries du couloir : la structure canonique du graphique.

    Le couloir est une carte divergente autour de la médiane (Munzner 2014) :
    deux aires externes P10→P50 et P50→P90 en teinte claire, deux aires
    internes P25→P50 et P50→P75 en teinte saturée par-dessus, des liserés sur
    les bornes externes, et la médiane comme point neutre achromatique.

    Lorsque les données ne contiennent qu'une seule abscisse, aucune aire n'est
    traçable : la recette bascule sur des repères ponctuels.

    Args:
        rows (Sequence[Dict[str, Any]]): Enregistrements de la table de bandes.
        source (str): Nom de la table dans ``ChartSpec.data``.
        outer_low (str): Champ de la borne basse externe.
        outer_high (str): Champ de la borne haute externe.
        inner_low (str): Champ de la borne basse interne.
        inner_high (str): Champ de la borne haute interne.
        median_col (str): Champ de la médiane.
        outer_label_below (Optional[str]): Légende de l'aire externe basse.
        outer_label_above (Optional[str]): Légende de l'aire externe haute.
        inner_label_below (Optional[str]): Légende de l'aire interne basse.
        inner_label_above (Optional[str]): Légende de l'aire interne haute.
        median_label (Optional[str]): Légende de la médiane.
        zorder_bands (int): Plan de dessin de base des aires.
        zorder_median (int): Plan de dessin de la médiane.

    Returns:
        Tuple[Geom, ...]: Géométries dans l'ordre de dessin.
    """
    if not rows:
        return ()

    present = {key for row in rows for key, value in row.items() if value is not None}
    if median_col not in present:
        return ()

    has_outer = outer_low in present and outer_high in present
    has_inner = inner_low in present and inner_high in present
    multi_x = len({row.get("x") for row in rows}) > 1

    layers: List[Geom] = []

    if has_outer and multi_x:
        layers.append(
            Area(
                source=source,
                ymin=outer_low,
                ymax=median_col,
                fill=CORRIDOR_BELOW_MEDIAN_OUTER_COLOR,
                alpha=CORRIDOR_BAND_OUTER_ALPHA,
                label=_label(outer_label_below),
                zorder=zorder_bands,
            )
        )
        layers.append(
            Area(
                source=source,
                ymin=median_col,
                ymax=outer_high,
                fill=CORRIDOR_ABOVE_MEDIAN_OUTER_COLOR,
                alpha=CORRIDOR_BAND_OUTER_ALPHA,
                label=_label(outer_label_above),
                zorder=zorder_bands,
            )
        )
        for edge_field, edge_color in (
            (outer_low, CORRIDOR_BELOW_MEDIAN_EDGE_COLOR),
            (outer_high, CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR),
        ):
            layers.append(
                Line(
                    source=source,
                    y=edge_field,
                    color=edge_color,
                    width=0.8,
                    alpha=CORRIDOR_BAND_EDGE_ALPHA,
                    label=None,
                    zorder=zorder_bands + 1,
                )
            )

    if has_inner and multi_x:
        layers.append(
            Area(
                source=source,
                ymin=inner_low,
                ymax=median_col,
                fill=CORRIDOR_BELOW_MEDIAN_INNER_COLOR,
                alpha=CORRIDOR_BAND_INNER_ALPHA,
                label=_label(inner_label_below),
                zorder=zorder_bands + 2,
            )
        )
        layers.append(
            Area(
                source=source,
                ymin=median_col,
                ymax=inner_high,
                fill=CORRIDOR_ABOVE_MEDIAN_INNER_COLOR,
                alpha=CORRIDOR_BAND_INNER_ALPHA,
                label=_label(inner_label_above),
                zorder=zorder_bands + 2,
            )
        )

    layers.append(
        Line(
            source=source,
            y=median_col,
            color=CORRIDOR_MEDIAN_COLOR,
            width=CORRIDOR_MEDIAN_LINEWIDTH,
            label=_label(median_label),
            zorder=zorder_median,
        )
    )

    if not multi_x:
        if has_outer:
            layers.append(
                Point(
                    source=source,
                    y=outer_low,
                    color=CORRIDOR_BELOW_MEDIAN_EDGE_COLOR,
                    size=45.0,
                    marker="tick",
                    zorder=zorder_median + 1,
                )
            )
            layers.append(
                Point(
                    source=source,
                    y=outer_high,
                    color=CORRIDOR_ABOVE_MEDIAN_EDGE_COLOR,
                    size=45.0,
                    marker="tick",
                    zorder=zorder_median + 1,
                )
            )
        if has_inner:
            layers.append(
                Point(
                    source=source,
                    y=inner_low,
                    color=CORRIDOR_BELOW_MEDIAN_INNER_COLOR,
                    size=40.0,
                    marker="circle",
                    alpha=0.9,
                    zorder=zorder_median + 1,
                )
            )
            layers.append(
                Point(
                    source=source,
                    y=inner_high,
                    color=CORRIDOR_ABOVE_MEDIAN_INNER_COLOR,
                    size=40.0,
                    marker="circle",
                    alpha=0.9,
                    zorder=zorder_median + 1,
                )
            )
        layers.append(
            Point(
                source=source,
                y=median_col,
                color=CORRIDOR_MEDIAN_COLOR,
                size=55.0,
                marker="circle",
                zorder=zorder_median + 2,
            )
        )

    return tuple(layers)


def swimmer_layers(
    source: str,
    label: str,
    color: str,
    *,
    y: str = "time_s",
    dashed: Optional[bool] = None,
) -> Tuple[Geom, ...]:
    """Construit les géométries d'une courbe nageur.

    Le style encode l'identité deux fois — teinte *et* forme — pour rester
    lisible en cas de déficience de la vision des couleurs : le second nageur
    (overlay marocain) reçoit un trait discontinu et des marqueurs carrés.

    Args:
        source (str): Nom de la table du nageur dans ``ChartSpec.data``.
        label (str): Libellé de légende.
        color (str): Couleur de la courbe.
        y (str): Champ porté par l'axe Y.
        dashed (Optional[bool]): Force le style discontinu ; déduit de la
            couleur et du libellé si ``None``.

    Returns:
        Tuple[Geom, ...]: Géométries de la courbe nageur.
    """
    if dashed is None:
        dashed = color == CORRIDOR_MA_SWIMMER_COLOR or "maroc" in label.lower()
    return (
        Line(
            source=source,
            y=y,
            color=color,
            width=3.2 if dashed else 3.4,
            dash=SWIMMER_DASH_PATTERN if dashed else (),
            marker="square" if dashed else "circle",
            marker_size=8.0,
            label=label,
            zorder=8,
        ),
    )


def _band_axis(bands: Sequence[Dict[str, Any]]) -> Tuple[Scale, List[str]]:
    """Déduit l'échelle X : âge numérique (FR/MA) ou catégories d'âge (US).

    Args:
        bands (Sequence[Dict[str, Any]]): Bandes du payload API.

    Returns:
        Tuple[Scale, List[str]]: Échelle X et catégories dans l'ordre.
    """
    categorical = bool(bands) and (
        bands[0].get("age_group") is not None and bands[0].get("age") is None
    )
    if categorical:
        categories = [str(band.get("age_group") or "") for band in bands]
        return (
            Scale(
                label="Catégorie d'âge",
                kind="categorical",
                categories=tuple(categories),
            ),
            categories,
        )
    return Scale(label="Âge (années)", unit="années", tick_format="integer"), []


_TIME_SCALE = Scale(
    label="Temps (s)",
    unit="s",
    reverse=True,
    tick_format="seconds",
)


def _band_rows(
    bands: Sequence[Dict[str, Any]], categories: Sequence[str]
) -> DataTable:
    """Normalise les bandes du payload en table à abscisse numérique.

    Args:
        bands (Sequence[Dict[str, Any]]): Bandes du payload API.
        categories (Sequence[str]): Catégories d'âge, vide si axe numérique.

    Returns:
        DataTable: Enregistrements portant ``x`` et les percentiles.
    """
    rows: List[Dict[str, Any]] = []
    for index, band in enumerate(bands):
        if categories:
            x: Optional[float] = float(index)
        else:
            age = band.get("age")
            x = None if age is None else float(age)
        if x is None:
            continue
        row: Dict[str, Any] = {"x": x}
        if categories:
            row["x_label"] = str(band.get("age_group") or "")
        for key in ("p10", "p25", "p50", "p75", "p90"):
            row[key] = band.get(key)
        rows.append(row)
    return tuple(rows)


def _swimmer_rows(
    swimmer: Optional[Dict[str, Any]], categories: Sequence[str]
) -> DataTable:
    """Normalise les points d'un nageur en table à abscisse numérique.

    Args:
        swimmer (Optional[Dict[str, Any]]): Payload nageur de l'API.
        categories (Sequence[str]): Catégories d'âge, vide si axe numérique.

    Returns:
        DataTable: Enregistrements portant ``x`` et ``time_s``.
    """
    if not swimmer:
        return ()
    index_by_category = {name: position for position, name in enumerate(categories)}
    rows: List[Dict[str, Any]] = []
    for point in swimmer.get("points") or []:
        time_s = point.get("time_s")
        if time_s is None:
            continue
        if categories:
            group = str(point.get("age_group") or "")
            if group not in index_by_category:
                continue
            x: float = float(index_by_category[group])
        else:
            age = point.get("age")
            if age is None:
                continue
            x = float(age)
        rows.append({"x": x, "time_s": float(time_s)})
    rows.sort(key=lambda row: row["x"])
    return tuple(rows)


def _swimmer_label(swimmer: Dict[str, Any], fallback: str = "Nageur") -> str:
    """Compose le libellé de légende d'un nageur.

    Args:
        swimmer (Dict[str, Any]): Payload nageur de l'API.
        fallback (str): Nom de repli si absent.

    Returns:
        str: Libellé « Nom (année de naissance) ».
    """
    name = str(swimmer.get("name") or fallback)
    yob = swimmer.get("year_of_birth")
    return f"{name} ({yob})" if yob else name


def _corridor_title(
    meta: Dict[str, Any], prefix: str, *, country_prefix: str = ""
) -> str:
    """Compose le titre d'un couloir à partir du contexte de la requête.

    Args:
        meta (Dict[str, Any]): Bloc ``meta`` du payload API.
        prefix (str): Préfixe du titre.
        country_prefix (str): Mention précédant le pays (``"réf. "`` en
            comparaison, où le pays désigne le peloton de référence).

    Returns:
        str: Titre affiché.
    """
    event = str(meta.get("event") or "").strip()
    country = str(meta.get("country") or "").strip()
    if event and country:
        return f"{prefix} — {event} ({country_prefix}{country})"
    if event:
        return f"{prefix} — {event}"
    return prefix


def _band_legend(layers: Sequence[Geom]) -> Tuple[LegendEntry, ...]:
    """Dérive la légende des géométries porteuses d'un libellé.

    Args:
        layers (Sequence[Geom]): Géométries de la recette.

    Returns:
        Tuple[LegendEntry, ...]: Entrées de légende, dans l'ordre de dessin.
    """
    entries: List[LegendEntry] = []
    for layer in layers:
        label = getattr(layer, "label", None)
        if not label:
            continue
        if isinstance(layer, Area):
            entries.append(LegendEntry(label=label, color=layer.fill, kind="swatch"))
        elif isinstance(layer, Line):
            entries.append(
                LegendEntry(
                    label=label, color=layer.color, kind="line", dash=layer.dash
                )
            )
        elif isinstance(layer, Point):
            entries.append(LegendEntry(label=label, color=layer.color, kind="swatch"))
    return tuple(entries)


def corridor_spec_from_payload(
    payload: Dict[str, Any],
    *,
    title: Optional[str] = None,
) -> ChartSpec:
    """Construit la recette d'un couloir à partir du payload ``GET /couloir``.

    Args:
        payload (Dict[str, Any]): Réponse API couloir (``bands``, ``swimmer``).
        title (Optional[str]): Titre de remplacement.

    Returns:
        ChartSpec: Recette prête à être rendue par n'importe quel moteur.
    """
    bands = list(payload.get("bands") or [])
    meta = dict(payload.get("meta") or {})
    x_scale, categories = _band_axis(bands)
    band_rows = _band_rows(bands, categories)

    layers: List[Geom] = list(
        corridor_band_layers(
            band_rows,
            outer_label_below="Couloir P10–P50 (sous médiane)",
            outer_label_above="Couloir P50–P90 (au-dessus médiane)",
            inner_label_below="Cœur P25–P50",
            inner_label_above="Cœur P50–P75",
            median_label="Médiane (P50)",
        )
    )

    data: Dict[str, DataTable] = {_BANDS: band_rows}
    swimmer = payload.get("swimmer")
    if swimmer:
        rows = _swimmer_rows(swimmer, categories)
        if rows:
            data["swimmer"] = rows
            layers.extend(
                swimmer_layers(
                    "swimmer",
                    _swimmer_label(swimmer),
                    CORRIDOR_FR_SWIMMER_COLOR,
                    dashed=False,
                )
            )

    return ChartSpec(
        kind="corridor",
        title=title or _corridor_title(meta, "Couloir de performance"),
        data=data,
        mapping={"x": "age_group" if categories else "age", "y": "time_s"},
        stat=CORRIDOR_STAT,
        x=x_scale,
        y=_TIME_SCALE,
        layers=tuple(layers),
        theme=PACING_THEME,
        legend=_band_legend(layers),
        meta=meta,
    )


def compare_spec_from_payload(
    payload: Dict[str, Any],
    *,
    title: Optional[str] = None,
) -> ChartSpec:
    """Construit la recette d'une comparaison à partir de ``GET /comparaison``.

    Même couloir de référence que ``corridor_spec_from_payload``, avec deux
    courbes nageurs distinguées par la teinte *et* par la forme du trait.

    Args:
        payload (Dict[str, Any]): Réponse API comparaison.
        title (Optional[str]): Titre de remplacement.

    Returns:
        ChartSpec: Recette prête à être rendue par n'importe quel moteur.
    """
    bands = list(payload.get("bands") or [])
    meta = dict(payload.get("meta") or {})
    x_scale, categories = _band_axis(bands)
    band_rows = _band_rows(bands, categories)

    layers: List[Geom] = list(
        corridor_band_layers(
            band_rows,
            outer_label_below="Couloir P10–P50 (sous médiane)",
            outer_label_above="Couloir P50–P90 (au-dessus médiane)",
            inner_label_below="Cœur P25–P50",
            inner_label_above="Cœur P50–P75",
            median_label="Médiane (P50)",
        )
    )

    data: Dict[str, DataTable] = {_BANDS: band_rows}
    for key, color, dashed, fallback in (
        ("swimmer_a", CORRIDOR_FR_SWIMMER_COLOR, False, "Nageur A"),
        ("swimmer_b", CORRIDOR_MA_SWIMMER_COLOR, True, "Nageur B"),
    ):
        swimmer = payload.get(key)
        if not swimmer:
            continue
        rows = _swimmer_rows(swimmer, categories)
        if not rows:
            continue
        data[key] = rows
        layers.extend(
            swimmer_layers(
                key,
                _swimmer_label(swimmer, fallback),
                color,
                dashed=dashed,
            )
        )

    return ChartSpec(
        kind="compare",
        title=title or _corridor_title(meta, "Comparaison", country_prefix="réf. "),
        data=data,
        mapping={"x": "age_group" if categories else "age", "y": "time_s"},
        stat=CORRIDOR_STAT,
        x=x_scale,
        y=_TIME_SCALE,
        layers=tuple(layers),
        theme=PACING_THEME,
        legend=_band_legend(layers),
        meta=meta,
    )


def percentile_corridor_spec(
    x_values: Sequence[Any],
    df_percentiles: Any,
    *,
    outer_low: str = "p10",
    outer_high: str = "p90",
    inner_low: str = "p25",
    inner_high: str = "p75",
    median_col: str = "p50",
    outer_label_below: Optional[str] = "Couloir P10–P50 (sous médiane)",
    outer_label_above: Optional[str] = "Couloir P50–P90 (au-dessus médiane)",
    inner_label_below: Optional[str] = _NO_LEGEND,
    inner_label_above: Optional[str] = _NO_LEGEND,
    median_label: Optional[str] = "Médiane du groupe",
    zorder_bands: int = 1,
    zorder_median: int = 3,
    title: str = "",
    x_label: str = "",
    y_label: str = "Temps (s)",
    y_reverse: bool = False,
) -> ChartSpec:
    """Construit la recette d'un couloir à partir d'un DataFrame de percentiles.

    Porte d'entrée du chemin Flet, qui agrège ses percentiles en pandas au lieu
    de passer par l'API. Les géométries produites sont celles de
    ``corridor_band_layers`` : la structure du couloir reste définie une seule
    fois, quelle que soit la provenance des données.

    Args:
        x_values (Sequence[Any]): Abscisses alignées sur ``df_percentiles``.
        df_percentiles (Any): DataFrame de colonnes ``p10``…``p90``.
        outer_low (str): Colonne borne basse externe.
        outer_high (str): Colonne borne haute externe.
        inner_low (str): Colonne borne basse interne.
        inner_high (str): Colonne borne haute interne.
        median_col (str): Colonne médiane.
        outer_label_below (Optional[str]): Légende aire externe basse.
        outer_label_above (Optional[str]): Légende aire externe haute.
        inner_label_below (Optional[str]): Légende aire interne basse.
        inner_label_above (Optional[str]): Légende aire interne haute.
        median_label (Optional[str]): Légende médiane.
        zorder_bands (int): Plan de dessin de base des aires.
        zorder_median (int): Plan de dessin de la médiane.
        title (str): Titre du graphique.
        x_label (str): Libellé d'axe X.
        y_label (str): Libellé d'axe Y.
        y_reverse (bool): Petites valeurs en haut.

    Returns:
        ChartSpec: Recette du couloir.
    """
    columns = [
        name
        for name in (outer_low, inner_low, median_col, inner_high, outer_high)
        if name in getattr(df_percentiles, "columns", [])
    ]
    rows: List[Dict[str, Any]] = []
    for position, x in enumerate(list(x_values)):
        try:
            x_numeric = float(x)
        except (TypeError, ValueError):
            x_numeric = float(position)
        row: Dict[str, Any] = {"x": x_numeric}
        for name in columns:
            value = df_percentiles[name].iloc[position]
            row[name] = None if value is None else float(value)
        rows.append(row)

    band_rows: DataTable = tuple(rows)
    layers = corridor_band_layers(
        band_rows,
        outer_low=outer_low,
        outer_high=outer_high,
        inner_low=inner_low,
        inner_high=inner_high,
        median_col=median_col,
        outer_label_below=outer_label_below,
        outer_label_above=outer_label_above,
        inner_label_below=inner_label_below,
        inner_label_above=inner_label_above,
        median_label=median_label,
        zorder_bands=zorder_bands,
        zorder_median=zorder_median,
    )

    return ChartSpec(
        kind="corridor",
        title=title,
        data={_BANDS: band_rows},
        mapping={"x": "x", "y": median_col},
        stat=CORRIDOR_STAT,
        x=Scale(label=x_label),
        y=Scale(label=y_label, unit="s", reverse=y_reverse, tick_format="seconds"),
        layers=layers,
        theme=PACING_THEME,
        legend=_band_legend(layers),
    )
