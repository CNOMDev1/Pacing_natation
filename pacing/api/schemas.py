"""Modèles Pydantic pour le contrat HTTP de l'API Pacing (/api/v1).

Valident les query params et les payloads JSON exposés à NiceGUI / iOS.
Distincts des modèles d'ingestion (``pacing.domain.models_*``).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CountryCode(str, Enum):
    """Codes pays stables de l'API."""

    FR = "FR"
    MA = "MA"
    US = "US"


class StrokeCode(str, Enum):
    """Codes nage unifiés."""

    FR = "FR"
    BK = "BK"
    BR = "BR"
    FL = "FL"
    IM = "IM"


class PoolCode(str, Enum):
    """Codes bassin."""

    LCM = "LCM"
    SCM = "SCM"
    SCY = "SCY"


class GenderFilter(str, Enum):
    """Filtre genre API."""

    F = "F"
    M = "M"
    ALL = "all"


class CorridorType(str, Enum):
    """Types de couloir exposés par le prototype."""

    AGE_GLOBAL = "age_global"
    AGE_TARGET = "age_target"


class ApiStatus(str, Enum):
    """Statuts métier renvoyés en HTTP 200."""

    OK = "ok"
    EMPTY = "empty"
    NOT_FOUND = "not_found"


# --- Référentiels ---


class CountryItem(BaseModel):
    """Un pays du référentiel.

    Attributes:
        code (CountryCode): Code ISO court API.
        label (str): Libellé affiché.
    """

    code: CountryCode
    label: str = Field(..., min_length=1)


class CountriesResponse(BaseModel):
    """Réponse ``GET /pays``.

    Attributes:
        countries (List[CountryItem]): Liste des pays supportés.
    """

    countries: List[CountryItem]


class PoolItem(BaseModel):
    """Un bassin dans le référentiel épreuves.

    Attributes:
        code (str): Code bassin (LCM, SCM, …).
        label (str): Libellé.
    """

    code: str
    label: str


class DistanceItem(BaseModel):
    """Une distance et ses bassins associés.

    Attributes:
        distance (int): Distance en mètres.
        unit (str): Unité (toujours ``m``).
        pools (List[PoolItem]): Bassins disponibles.
    """

    distance: int = Field(..., gt=0, description="Distance en mètres")
    unit: str = "m"
    pools: List[PoolItem] = Field(default_factory=list)


class StrokeTreeItem(BaseModel):
    """Une nage avec ses distances / bassins.

    Attributes:
        code (str): Code nage.
        label (str): Libellé français.
        distances (List[DistanceItem]): Distances disponibles.
    """

    code: str
    label: str
    distances: List[DistanceItem] = Field(default_factory=list)


class EventsReferentialResponse(BaseModel):
    """Réponse ``GET /referentiels/epreuves``.

    Attributes:
        country (CountryCode): Pays demandé.
        strokes (List[StrokeTreeItem]): Arbre FR/MA.
        events (List[str]): Liste plate d'épreuves (surtout US).
    """

    country: CountryCode
    strokes: List[StrokeTreeItem] = Field(default_factory=list)
    events: List[str] = Field(default_factory=list)


# --- Recherche nageur ---


class SwimmerSearchResult(BaseModel):
    """Un nageur dans les résultats de recherche.

    Attributes:
        label (str): Libellé UI (ex. ``DUPONT Alice (2008)``).
        name (str): Nom.
        year_of_birth (Optional[int]): Année de naissance.
        gender (Optional[str]): ``F`` / ``M`` si connu.
        country (CountryCode): Pays source.
    """

    label: str
    name: str
    year_of_birth: Optional[int] = Field(None, ge=1900, le=2100)
    gender: Optional[str] = None
    country: CountryCode


class SwimmerSearchResponse(BaseModel):
    """Réponse ``GET /nageur/recherche``.

    Attributes:
        status (ApiStatus): ``ok`` ou ``empty``.
        query (str): Texte recherché.
        count (int): Nombre de résultats.
        results (List[SwimmerSearchResult]): Hits.
        message (Optional[str]): Message optionnel (ex. US sans event).
    """

    status: ApiStatus
    query: str
    count: int = Field(..., ge=0)
    results: List[SwimmerSearchResult] = Field(default_factory=list)
    message: Optional[str] = None


# --- Couloir ---


class CorridorUnits(BaseModel):
    """Unités du payload couloir.

    Attributes:
        age (Optional[str]): Unité âge (``years``) pour FR/MA.
        age_group (Optional[str]): Unité catégorie (``label``) pour US.
        time (str): Unité temps (``seconds``).
        distance (str): Unité distance (``m``).
    """

    age: Optional[str] = None
    age_group: Optional[str] = None
    time: str = "seconds"
    distance: str = "m"


class CorridorMeta(BaseModel):
    """Métadonnées du couloir.

    Attributes:
        country (CountryCode): Pays du peloton (percentiles).
        corridor_type (str): Type de couloir.
        event (str): Libellé épreuve.
        stroke (str): Code nage.
        distance (int): Distance (m).
        pool (str): Bassin.
        gender (str): Filtre genre effectif.
        swimmer_country (Optional[CountryCode]): Pays source du nageur cible.
        units (CorridorUnits): Unités.
        row_count (int): Nombre de perfs dans le long DF.
    """

    country: CountryCode
    corridor_type: str
    event: str
    stroke: str
    distance: int = Field(..., gt=0)
    pool: str
    gender: str
    swimmer_country: Optional[CountryCode] = None
    units: CorridorUnits
    row_count: int = Field(..., ge=0)


class CorridorBand(BaseModel):
    """Une bande de percentiles pour un âge ou une catégorie d'âge.

    Temps en **secondes**. FR/MA : ``age`` ; US : ``age_group``.

    Attributes:
        age (Optional[int]): Âge en années (FR/MA).
        age_group (Optional[str]): Catégorie USA Swimming.
        n (int): Effectif.
        p10 / p25 / p50 / p75 / p90 (Optional[float]): Percentiles (s).
    """

    model_config = ConfigDict(extra="allow")

    age: Optional[int] = Field(None, ge=0, le=100)
    age_group: Optional[str] = None
    n: int = Field(0, ge=0)
    p10: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None


class SwimmerPoint(BaseModel):
    """Point âge/catégorie × temps d'un nageur.

    Attributes:
        age (Optional[float]): Âge (années) pour FR/MA.
        age_group (Optional[str]): Catégorie USA pour US / overlay MA→US.
        time_s (float): Temps en secondes.
    """

    age: Optional[float] = Field(None, ge=0)
    age_group: Optional[str] = None
    time_s: float = Field(..., gt=0, description="Temps en secondes")


class CorridorSwimmer(BaseModel):
    """Courbe nageur superposée au couloir.

    Attributes:
        name (str): Nom résolu.
        year_of_birth (Optional[int]): YOB.
        country (Optional[CountryCode]): Pays source du nageur (comparaison).
        gender (Optional[str]): Genre.
        points (List[SwimmerPoint]): Série âge × temps.
    """

    name: str
    year_of_birth: Optional[int] = Field(None, ge=1900, le=2100)
    country: Optional[CountryCode] = None
    gender: Optional[str] = None
    points: List[SwimmerPoint] = Field(default_factory=list)


class CorridorResponse(BaseModel):
    """Réponse ``GET /couloir``.

    Attributes:
        status (ApiStatus): Statut métier.
        meta (CorridorMeta): Contexte de la requête.
        bands (List[CorridorBand]): Bandes percentiles.
        swimmer (Optional[CorridorSwimmer]): Nageur cible si demandé.
        image_base64 (Optional[str]): Image optionnelle (non utilisée en prototype).
        missing (Optional[List[str]]): Ressources manquantes si ``not_found``.
    """

    status: ApiStatus
    meta: CorridorMeta
    bands: List[CorridorBand] = Field(default_factory=list)
    swimmer: Optional[CorridorSwimmer] = None
    image_base64: Optional[str] = None
    missing: Optional[List[str]] = None


class CompareResponse(BaseModel):
    """Réponse ``GET /comparaison`` (deux nageurs sur un couloir).

    Attributes:
        status (ApiStatus): Statut métier.
        meta (CorridorMeta): Contexte (pays = peloton de référence).
        bands (List[CorridorBand]): Bandes du couloir.
        swimmer_a (Optional[CorridorSwimmer]): Premier nageur.
        swimmer_b (Optional[CorridorSwimmer]): Second nageur (overlay).
        image_base64 (Optional[str]): Non utilisé en prototype.
        missing (Optional[List[str]]): ``swimmer_a`` / ``swimmer_b`` si absents.
    """

    status: ApiStatus
    meta: CorridorMeta
    bands: List[CorridorBand] = Field(default_factory=list)
    swimmer_a: Optional[CorridorSwimmer] = None
    swimmer_b: Optional[CorridorSwimmer] = None
    image_base64: Optional[str] = None
    missing: Optional[List[str]] = None


# --- Query params (validation entrée) ---


class SwimmerSearchParams(BaseModel):
    """Query params validés pour ``GET /nageur/recherche``.

    Attributes:
        q (str): Texte de recherche.
        country (CountryCode): Pays.
        stroke (Optional[StrokeCode]): Nage.
        distance (Optional[int]): Distance (m).
        pool (Optional[PoolCode]): Bassin.
        event (Optional[str]): Épreuve exacte.
        gender (GenderFilter): Filtre genre.
        limit (int): Nombre max de résultats.
    """

    q: str = Field(..., min_length=1, max_length=120)
    country: CountryCode = CountryCode.FR
    stroke: Optional[StrokeCode] = None
    distance: Optional[int] = Field(None, gt=0, le=1500)
    pool: Optional[PoolCode] = None
    event: Optional[str] = Field(None, max_length=80)
    gender: GenderFilter = GenderFilter.ALL
    limit: int = Field(30, ge=1, le=100)

    @field_validator("q")
    @classmethod
    def strip_q(cls, value: str) -> str:
        """
        Normalise la requête en retirant les espaces de bord.

        Args:
            value (str): Texte brut.

        Returns:
            str: Texte stripé.

        Raises:
            ValueError: Si vide après strip.
        """
        text = value.strip()
        if not text:
            raise ValueError("q ne peut pas être vide")
        return text


class CorridorParams(BaseModel):
    """Query params validés pour ``GET /couloir``.

    Attributes:
        country (CountryCode): Pays du **peloton** (percentiles).
        stroke (StrokeCode): Nage.
        distance (int): Distance (m).
        pool (PoolCode): Bassin.
        gender (GenderFilter): Genre.
        corridor_type (CorridorType): Type de couloir.
        swimmer_name (Optional[str]): Nageur cible.
        swimmer_yob (Optional[int]): Année de naissance.
        swimmer_country (Optional[CountryCode]): Pays source du nageur
            (défaut = ``country`` si omis).
    """

    country: CountryCode = CountryCode.FR
    stroke: StrokeCode
    distance: int = Field(..., gt=0, le=1500, description="Distance en mètres")
    pool: PoolCode
    gender: GenderFilter = GenderFilter.ALL
    corridor_type: CorridorType = CorridorType.AGE_GLOBAL
    swimmer_name: Optional[str] = Field(None, max_length=120)
    swimmer_yob: Optional[int] = Field(None, ge=1900, le=2100)
    swimmer_country: Optional[CountryCode] = Field(
        None,
        description="Pays du nageur (défaut = country du peloton)",
    )

    @field_validator("swimmer_name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        """
        Strip le nom nageur.

        Args:
            value (Optional[str]): Nom brut.

        Returns:
            Optional[str]: Nom stripé ou None.
        """
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def target_requires_swimmer(self) -> "CorridorParams":
        """
        Aligne ``corridor_type``, ``swimmer_name`` et ``swimmer_country``.

        Si un nageur est fourni, bascule automatiquement en ``age_target``.
        Si ``swimmer_country`` est omis, il vaut ``country`` (peloton).

        Returns:
            CorridorParams: Instance validée.

        Raises:
            ValueError: Si ``age_target`` sans nageur.
        """
        if self.swimmer_name and self.corridor_type == CorridorType.AGE_GLOBAL:
            self.corridor_type = CorridorType.AGE_TARGET
        if self.corridor_type == CorridorType.AGE_TARGET and not self.swimmer_name:
            raise ValueError(
                "swimmer_name est requis lorsque corridor_type=age_target"
            )
        if self.swimmer_name and self.swimmer_country is None:
            self.swimmer_country = self.country
        return self


class EventsParams(BaseModel):
    """Query params pour ``GET /referentiels/epreuves``.

    Attributes:
        country (CountryCode): Pays.
    """

    country: CountryCode = CountryCode.FR


class CompareParams(BaseModel):
    """Query params validés pour ``GET /comparaison``.

    Attributes:
        country (CountryCode): Pays du couloir de référence.
        stroke (StrokeCode): Nage.
        distance (int): Distance (m).
        pool (PoolCode): Bassin.
        gender (GenderFilter): Filtre genre.
        swimmer_a_name (str): Premier nageur.
        swimmer_a_yob (Optional[int]): YOB A.
        swimmer_a_country (Optional[CountryCode]): Pays source A.
        swimmer_b_name (str): Second nageur.
        swimmer_b_yob (Optional[int]): YOB B.
        swimmer_b_country (Optional[CountryCode]): Pays source B (ex. MA).
    """

    country: CountryCode = CountryCode.FR
    stroke: StrokeCode
    distance: int = Field(..., gt=0, le=1500, description="Distance en mètres")
    pool: PoolCode
    gender: GenderFilter = GenderFilter.ALL
    swimmer_a_name: str = Field(..., min_length=1, max_length=120)
    swimmer_a_yob: Optional[int] = Field(None, ge=1900, le=2100)
    swimmer_a_country: Optional[CountryCode] = None
    swimmer_b_name: str = Field(..., min_length=1, max_length=120)
    swimmer_b_yob: Optional[int] = Field(None, ge=1900, le=2100)
    swimmer_b_country: Optional[CountryCode] = None

    @field_validator("swimmer_a_name", "swimmer_b_name")
    @classmethod
    def strip_swimmer_names(cls, value: str) -> str:
        """
        Strip les noms des nageurs.

        Args:
            value (str): Nom brut.

        Returns:
            str: Nom stripé.

        Raises:
            ValueError: Si vide après strip.
        """
        text = value.strip()
        if not text:
            raise ValueError("le nom du nageur ne peut pas être vide")
        return text
