"""Grammaire de graphiques Pacing : vocabulaire déclaratif.

Ce module ne dessine rien et n'importe aucune bibliothèque de rendu. Il définit
les objets qui *décrivent* un graphique — données, mapping variable → canal
visuel, transformations, géométries, échelles, thème, légende — de sorte qu'une
même recette puisse être rendue par Matplotlib (Flet, NiceGUI, DearPyGUI) ou
par Swift Charts (iOS).

Le partage entre plateformes passe par ``ChartSpec.to_dict()`` : la recette est
sérialisable en JSON, donc transmissible par l'API à un moteur non-Python.

Répartition des responsabilités :

- La **recette** (ce module et ``pacing.grammar.corridor``) décide *quoi* est
  tracé : quelle variable sur quel axe, quelles bandes, quelles couleurs,
  quelles unités, quel sens d'axe.
- Le **moteur** (``pacing.grammar.render_matplotlib``, ``CorridorChartView``)
  décide *comment* : ``fill_between`` ou ``AreaMark``, PNG base64 ou texture
  GPU. Il n'a aucune latitude sur l'apparence.

Convention d'abscisse : chaque table de données expose une clé ``x`` numérique.
Pour un axe catégoriel (catégories d'âge USA), ``x`` est l'indice de la
catégorie dans ``Scale.categories``. Les deux moteurs ont besoin de cette
normalisation (``fill_between`` exige des X numériques, Swift Charts aussi),
elle appartient donc à la recette et non aux moteurs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

DataTable = Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class Theme:
    """Charte visuelle commune à tous les graphiques Pacing.

    Attributes:
        figure_facecolor (str): Couleur de fond de la figure.
        axes_facecolor (str): Couleur de fond de la zone de tracé.
        grid_color (str): Couleur des lignes de grille.
        grid_alpha (float): Opacité de la grille.
        grid_linewidth (float): Épaisseur des lignes de grille.
        annotation_color (str): Couleur des textes d'annotation.
        marker_edge_color (str): Couleur du liseré des marqueurs.
    """

    figure_facecolor: str
    axes_facecolor: str
    grid_color: str
    grid_alpha: float
    grid_linewidth: float
    annotation_color: str
    marker_edge_color: str

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise le thème.

        Returns:
            Dict[str, Any]: Thème en dictionnaire JSON-compatible.
        """
        return {
            "figure_facecolor": self.figure_facecolor,
            "axes_facecolor": self.axes_facecolor,
            "grid_color": self.grid_color,
            "grid_alpha": self.grid_alpha,
            "grid_linewidth": self.grid_linewidth,
            "annotation_color": self.annotation_color,
            "marker_edge_color": self.marker_edge_color,
        }


@dataclass(frozen=True)
class Scale:
    """Échelle d'un canal visuel : domaine, unité, sens et libellé.

    Attributes:
        label (str): Libellé d'axe affiché.
        unit (Optional[str]): Unité physique (``"s"`` pour des secondes).
        kind (str): ``"linear"`` ou ``"categorical"``.
        reverse (bool): Si vrai, les petites valeurs sont en haut (temps :
            le meilleur chrono domine). Chaque moteur applique ce sens avec sa
            propre technique.
        categories (Tuple[str, ...]): Libellés de ticks pour ``"categorical"``,
            indexés par la valeur ``x`` des données.
        tick_format (Optional[str]): Format des étiquettes (``"seconds"``,
            ``"mm:ss.cc"``, ``"integer"``).
    """

    label: str
    unit: Optional[str] = None
    kind: str = "linear"
    reverse: bool = False
    categories: Tuple[str, ...] = ()
    tick_format: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise l'échelle.

        Returns:
            Dict[str, Any]: Échelle en dictionnaire JSON-compatible.
        """
        return {
            "label": self.label,
            "unit": self.unit,
            "kind": self.kind,
            "reverse": self.reverse,
            "categories": list(self.categories),
            "tick_format": self.tick_format,
        }


@dataclass(frozen=True)
class Area:
    """Géométrie « aire » : ruban entre deux bornes verticales.

    Attributes:
        source (str): Nom de la table de données dans ``ChartSpec.data``.
        ymin (str): Champ de la borne basse.
        ymax (str): Champ de la borne haute.
        fill (str): Couleur de remplissage.
        alpha (float): Opacité du remplissage.
        label (Optional[str]): Libellé de légende ; ``None`` = hors légende.
        zorder (int): Plan de dessin (croissant = au-dessus).
    """

    source: str
    ymin: str
    ymax: str
    fill: str
    alpha: float = 1.0
    label: Optional[str] = None
    zorder: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie.

        Returns:
            Dict[str, Any]: Géométrie en dictionnaire JSON-compatible.
        """
        return {
            "geom": "area",
            "source": self.source,
            "ymin": self.ymin,
            "ymax": self.ymax,
            "fill": self.fill,
            "alpha": self.alpha,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Line:
    """Géométrie « ligne » : courbe reliant les points d'une table.

    Attributes:
        source (str): Nom de la table de données dans ``ChartSpec.data``.
        y (str): Champ porté par l'axe Y.
        color (str): Couleur du trait.
        width (float): Épaisseur du trait.
        dash (Tuple[float, ...]): Motif de pointillés ; vide = trait plein.
        alpha (float): Opacité du trait.
        marker (Optional[str]): Marqueur aux points (``"circle"``,
            ``"square"``) ; ``None`` = aucun.
        marker_size (float): Taille du marqueur.
        label (Optional[str]): Libellé de légende ; ``None`` = hors légende.
        zorder (int): Plan de dessin.
    """

    source: str
    y: str
    color: str
    width: float = 2.0
    dash: Tuple[float, ...] = ()
    alpha: float = 1.0
    marker: Optional[str] = None
    marker_size: float = 0.0
    label: Optional[str] = None
    zorder: int = 3

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie.

        Returns:
            Dict[str, Any]: Géométrie en dictionnaire JSON-compatible.
        """
        return {
            "geom": "line",
            "source": self.source,
            "y": self.y,
            "color": self.color,
            "width": self.width,
            "dash": list(self.dash),
            "alpha": self.alpha,
            "marker": self.marker,
            "marker_size": self.marker_size,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Point:
    """Géométrie « points » : marqueurs isolés, sans trait de liaison.

    Sert notamment de repli lorsqu'une seule abscisse est disponible : un
    couloir d'un seul âge n'a pas d'aire, seulement des repères.

    Attributes:
        source (str): Nom de la table de données dans ``ChartSpec.data``.
        y (str): Champ porté par l'axe Y.
        color (str): Couleur du marqueur.
        size (float): Taille du marqueur.
        marker (str): Forme (``"circle"``, ``"square"``, ``"tick"``).
        alpha (float): Opacité.
        label (Optional[str]): Libellé de légende ; ``None`` = hors légende.
        zorder (int): Plan de dessin.
    """

    source: str
    y: str
    color: str
    size: float = 40.0
    marker: str = "circle"
    alpha: float = 1.0
    label: Optional[str] = None
    zorder: int = 5

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie.

        Returns:
            Dict[str, Any]: Géométrie en dictionnaire JSON-compatible.
        """
        return {
            "geom": "point",
            "source": self.source,
            "y": self.y,
            "color": self.color,
            "size": self.size,
            "marker": self.marker,
            "alpha": self.alpha,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Bar:
    """Géométrie « barres » : longueur = grandeur, position = catégorie.

    Attributes:
        source (str): Table de données (``x`` = indice de catégorie, ``y`` =
            valeur).
        y (str): Champ de la longueur.
        fill (str): Couleur de remplissage.
        orientation (str): ``"vertical"`` ou ``"horizontal"``.
        width (float): Largeur (ou hauteur) d'une barre, en unités d'axe.
        alpha (float): Opacité.
        label (Optional[str]): Libellé de légende.
        zorder (int): Plan de dessin.
        value_labels (bool): Annoter chaque barre avec sa valeur.
        label_field (Optional[str]): Champ texte d'annotation ; ``None`` =
            formater ``y``.
    """

    source: str
    y: str
    fill: str
    orientation: str = "vertical"
    width: float = 0.8
    alpha: float = 0.92
    label: Optional[str] = None
    zorder: int = 3
    value_labels: bool = False
    label_field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie."""
        return {
            "geom": "bar",
            "source": self.source,
            "y": self.y,
            "fill": self.fill,
            "orientation": self.orientation,
            "width": self.width,
            "alpha": self.alpha,
            "label": self.label,
            "zorder": self.zorder,
            "value_labels": self.value_labels,
            "label_field": self.label_field,
        }


@dataclass(frozen=True)
class Histogram:
    """Géométrie « histogramme » : barres de classes déjà calculées en amont.

    La transformation (bins adaptatifs) n'est pas le rôle du moteur : la table
    expose le centre de classe ``x`` et l'effectif ``y``.

    Attributes:
        source (str): Table des classes.
        y (str): Effectif (ou densité) de la classe.
        fill (str): Couleur.
        width (float): Largeur de classe en unités d'abscisse.
        alpha (float): Opacité.
        label (Optional[str]): Libellé de légende.
        zorder (int): Plan de dessin.
    """

    source: str
    y: str
    fill: str
    width: float = 1.0
    alpha: float = 0.78
    label: Optional[str] = None
    zorder: int = 2

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie."""
        return {
            "geom": "histogram",
            "source": self.source,
            "y": self.y,
            "fill": self.fill,
            "width": self.width,
            "alpha": self.alpha,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Boxplot:
    """Géométrie « boîte à moustaches » : quartiles calculés en amont.

    Chaque ligne de la table porte ``x``, ``q1``, ``median``, ``q3``,
    ``whislo``, ``whishi``. Les points aberrants sont une géométrie ``Point``
    séparée.

    Attributes:
        source (str): Table des statistiques par catégorie.
        fill (str): Couleur de remplissage des boîtes.
        median_color (str): Couleur du trait de médiane.
        edge_color (str): Couleur des contours.
        width (float): Largeur des boîtes.
        label (Optional[str]): Libellé de légende.
        zorder (int): Plan de dessin.
    """

    source: str
    fill: str = "#ffffff"
    median_color: str = "#374151"
    edge_color: str = "#475569"
    width: float = 0.52
    label: Optional[str] = None
    zorder: int = 3

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie."""
        return {
            "geom": "boxplot",
            "source": self.source,
            "fill": self.fill,
            "median_color": self.median_color,
            "edge_color": self.edge_color,
            "width": self.width,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Heatmap:
    """Géométrie « heatmap » : tuiles ``x`` × ``y`` colorées par ``value``.

    Attributes:
        source (str): Table (une ligne par cellule).
        value (str): Champ numérique encodé par la couleur.
        cmap (str): Nom de colormap Matplotlib.
        annot (Optional[str]): Champ texte d'annotation de cellule.
        vmin (Optional[float]): Borne basse de l'échelle.
        vmax (Optional[float]): Borne haute de l'échelle.
        center (Optional[float]): Centre pour une carte divergente.
        x_field (str): Champ d'indice de colonne (défaut ``x``).
        y_field (str): Champ d'indice de ligne (défaut ``y``).
        zorder (int): Plan de dessin.
        colorbar (bool): Afficher l'échelle de couleur.
        colorbar_label (Optional[str]): Libellé de l'échelle.
    """

    source: str
    value: str = "value"
    cmap: str = "viridis"
    annot: Optional[str] = None
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    center: Optional[float] = None
    x_field: str = "x"
    y_field: str = "y"
    zorder: int = 1
    colorbar: bool = False
    colorbar_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie."""
        return {
            "geom": "heatmap",
            "source": self.source,
            "value": self.value,
            "cmap": self.cmap,
            "annot": self.annot,
            "vmin": self.vmin,
            "vmax": self.vmax,
            "center": self.center,
            "x_field": self.x_field,
            "y_field": self.y_field,
            "zorder": self.zorder,
            "colorbar": self.colorbar,
            "colorbar_label": self.colorbar_label,
        }


@dataclass(frozen=True)
class Rule:
    """Ligne de référence constante (moyenne, médiane, 100 %).

    Attributes:
        axis (str): ``"x"`` (verticale) ou ``"y"`` (horizontale).
        value (float): Position.
        color (str): Couleur.
        width (float): Épaisseur.
        dash (Tuple[float, ...]): Motif de pointillés.
        alpha (float): Opacité.
        label (Optional[str]): Libellé de légende.
        zorder (int): Plan de dessin.
    """

    axis: str
    value: float
    color: str
    width: float = 1.4
    dash: Tuple[float, ...] = ()
    alpha: float = 1.0
    label: Optional[str] = None
    zorder: int = 6

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie."""
        return {
            "geom": "rule",
            "source": "",
            "axis": self.axis,
            "value": self.value,
            "color": self.color,
            "width": self.width,
            "dash": list(self.dash),
            "alpha": self.alpha,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Span:
    """Bande de référence (IQR, intervalle) le long d'un axe.

    Attributes:
        axis (str): ``"x"`` (axvspan) ou ``"y"`` (axhspan).
        start (float): Borne basse.
        end (float): Borne haute.
        fill (str): Couleur.
        alpha (float): Opacité.
        label (Optional[str]): Libellé de légende.
        zorder (int): Plan de dessin.
    """

    axis: str
    start: float
    end: float
    fill: str
    alpha: float = 0.15
    label: Optional[str] = None
    zorder: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la géométrie."""
        return {
            "geom": "span",
            "source": "",
            "axis": self.axis,
            "start": self.start,
            "end": self.end,
            "fill": self.fill,
            "alpha": self.alpha,
            "label": self.label,
            "zorder": self.zorder,
        }


@dataclass(frozen=True)
class Annotation:
    """Texte d'annotation (limites d'interprétation, stats, message vide).

    Attributes:
        text (str): Contenu.
        loc (str): ``"footnote"`` (figure), ``"center"`` (message vide),
            ``"axes"`` (coordonnées 0–1) ou ``"data"``.
        x (Optional[float]): Abscisse (data ou axes).
        y (Optional[float]): Ordonnée.
        color (Optional[str]): Couleur ; ``None`` = thème.
        size (float): Taille de police.
    """

    text: str
    loc: str = "footnote"
    x: Optional[float] = None
    y: Optional[float] = None
    color: Optional[str] = None
    size: float = 8.5

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise l'annotation."""
        return {
            "text": self.text,
            "loc": self.loc,
            "x": self.x,
            "y": self.y,
            "color": self.color,
            "size": self.size,
        }


@dataclass(frozen=True)
class Facet:
    """Disposition en petits multiples.

    Attributes:
        ncol (int): Nombre de colonnes.
        sharex (bool): Partager l'axe X.
        sharey (bool): Partager l'axe Y.
    """

    ncol: int = 2
    sharex: bool = True
    sharey: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la facette."""
        return {
            "ncol": self.ncol,
            "sharex": self.sharex,
            "sharey": self.sharey,
        }


Geom = Any  # Area | Line | Point | Bar | Histogram | Boxplot | Heatmap | Rule | Span


@dataclass(frozen=True)
class LegendEntry:
    """Entrée de légende déclarée par la recette.

    La légende fait partie de la recette et non du moteur : Matplotlib la
    dérive des libellés de géométries, Swift Charts en construit une vue
    maison, mais l'ordre et les libellés doivent être identiques.

    Attributes:
        label (str): Texte affiché.
        color (str): Couleur du témoin.
        kind (str): ``"swatch"`` (aplat) ou ``"line"`` (trait).
        dash (Tuple[float, ...]): Motif de pointillés pour ``"line"``.
    """

    label: str
    color: str
    kind: str = "swatch"
    dash: Tuple[float, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise l'entrée de légende.

        Returns:
            Dict[str, Any]: Entrée en dictionnaire JSON-compatible.
        """
        return {
            "label": self.label,
            "color": self.color,
            "kind": self.kind,
            "dash": list(self.dash),
        }


@dataclass(frozen=True)
class ChartSpec:
    """Recette complète d'un graphique, indépendante de tout moteur de rendu.

    Attributes:
        kind (str): Famille de graphique (``"corridor"``, ``"compare"``).
        title (str): Titre affiché.
        data (Dict[str, DataTable]): Tables nommées ; chaque enregistrement
            porte une clé ``x`` numérique.
        mapping (Dict[str, str]): Variable source par canal visuel, à des fins
            de documentation et de traçabilité (``{"x": "age", "y": "time_s"}``).
        stat (Optional[str]): Transformation statistique appliquée en amont
            (``"percentiles(10,25,50,75,90) by age"``), à titre déclaratif.
        x (Scale): Échelle horizontale.
        y (Scale): Échelle verticale.
        layers (Tuple[Geom, ...]): Géométries, dans l'ordre de dessin.
        theme (Theme): Charte visuelle.
        legend (Tuple[LegendEntry, ...]): Légende déclarée.
        annotations (Tuple[Annotation, ...]): Textes (limites, notes, vide).
        panels (Tuple[ChartSpec, ...]): Petits multiples ; si non vide, chaque
            panneau est une recette complète (F6, F10).
        facet (Optional[Facet]): Disposition des ``panels``.
        figsize (Optional[Tuple[float, float]]): Taille en pouces, si le moteur
            Matplotlib doit s'écarter du défaut.
        meta (Dict[str, Any]): Contexte libre (épreuve, pays, effectif).
    """

    kind: str
    title: str
    data: Dict[str, DataTable]
    mapping: Dict[str, str]
    x: Scale
    y: Scale
    layers: Tuple[Geom, ...]
    theme: Theme
    stat: Optional[str] = None
    legend: Tuple[LegendEntry, ...] = ()
    annotations: Tuple[Annotation, ...] = ()
    panels: Tuple["ChartSpec", ...] = ()
    facet: Optional[Facet] = None
    figsize: Optional[Tuple[float, float]] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def table(self, name: str) -> DataTable:
        """Retourne une table de données par nom.

        Args:
            name (str): Nom de la table.

        Returns:
            DataTable: Enregistrements, vide si la table est absente.
        """
        return self.data.get(name, ())

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise la recette entière pour transport JSON.

        C'est ce dictionnaire que l'API transmet à iOS : le graphique y est
        décrit, pas dessiné.

        Returns:
            Dict[str, Any]: Recette en dictionnaire JSON-compatible.
        """
        return {
            "kind": self.kind,
            "title": self.title,
            "stat": self.stat,
            "mapping": dict(self.mapping),
            "x": self.x.to_dict(),
            "y": self.y.to_dict(),
            "theme": self.theme.to_dict(),
            "layers": [layer.to_dict() for layer in self.layers],
            "legend": [entry.to_dict() for entry in self.legend],
            "annotations": [note.to_dict() for note in self.annotations],
            "panels": [panel.to_dict() for panel in self.panels],
            "facet": None if self.facet is None else self.facet.to_dict(),
            "figsize": None if self.figsize is None else list(self.figsize),
            "data": {
                name: [dict(row) for row in rows] for name, rows in self.data.items()
            },
            "meta": dict(self.meta),
        }


def numeric_series(
    rows: Sequence[Dict[str, Any]], *fields: str
) -> Tuple[List[float], ...]:
    """Extrait des séries numériques alignées, en écartant les lignes trouées.

    Une aire ou une ligne n'a de sens que sur les abscisses où *tous* les
    champs requis sont renseignés ; cette fonction assure cet alignement pour
    n'importe quel moteur.

    Args:
        rows (Sequence[Dict[str, Any]]): Enregistrements d'une table.
        *fields (str): Champs à extraire, ``"x"`` inclus si nécessaire.

    Returns:
        Tuple[List[float], ...]: Une liste par champ, de même longueur.
    """
    out: Tuple[List[float], ...] = tuple([] for _ in fields)
    for row in rows:
        values: List[float] = []
        for name in fields:
            value = row.get(name)
            if value is None:
                break
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                break
        else:
            for bucket, value in zip(out, values):
                bucket.append(value)
    return out
