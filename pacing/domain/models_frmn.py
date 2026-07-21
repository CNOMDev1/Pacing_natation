"""Modèles Pydantic pour les données FRM Natation (Maroc).

Ce module décrit la hiérarchie JSON produite par le scraping HTML externe
et consommée par ``frmnatation_preprocessing`` puis
``FrmnatationHtmlResultsDataLoader`` :

``FrmCompetition`` → ``FrmEpreuve`` → ``FrmPerformance`` → ``FrmNageur``.

Le flux de données :
1. **Scraping externe** — un outil hors dépôt écrit un JSON par compétition
   sous ``data/raw/frmnatation/html_results/``.
2. **Validation** — ``FrmCompetition.model_validate`` ou ``from_json_file``
   vérifie la structure à la lecture.
3. **Prétraitement** — ``frmnatation_preprocessing`` filtre les chronos
   invalides, normalise les noms et convertit les codes nage FRM (DOS, PAP, 4N).
4. **Chargement** — ``FrmnatationHtmlResultsDataLoader`` lit
   ``data/processed/frmnatation/html_results/`` pour l'overlay UI.

Le format est proche du schéma unifié Pacing (Meet, Event, SwimTimeSeconds).
Particularités FRM : ``splits`` toujours vides, ``swimmer`` souvent un dict
(unique) plutôt qu'une liste, champ ``club`` en minuscules.
"""
from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator


class FrmNageur(BaseModel):
    """Nageur ou nageuse dans une performance FRM Natation.

    Attributes:
        Name: Nom complet (souvent NOM Prénom).
        Gender: Genre (F, M, Femme, Homme, etc.).
        Year_of_birth: Année de naissance.
        Age: Âge à la date de la compétition.
        AgeGroup: Catégorie d'âge USA Swimming (ex. ``13-14``), ajoutée au prétraitement.
        Nationality: Code ou libellé pays (ex. MAR).
    """

    Name: Optional[str] = Field(None, description="Nom complet du nageur")
    Gender: Optional[str] = Field(None, description="Genre (F, M, Femme, Homme, …)")
    Year_of_birth: Optional[int] = Field(None, description="Année de naissance")
    Age: Optional[int] = Field(None, description="Âge à la date de la compétition")
    AgeGroup: Optional[str] = Field(
        None, description="Catégorie d'âge USA Swimming (ex. 13-14, 19 & Over)"
    )
    Nationality: Optional[str] = Field(None, description="Nationalité (ex. MAR)")

    model_config = {"extra": "ignore", "str_strip_whitespace": True}


FrmNageurOuRelais = Union[FrmNageur, list[FrmNageur]]


class FrmPerformance(BaseModel):
    """Une performance (résultat) dans une épreuve FRM Natation.

    Le champ ``swimmer`` accepte un dict unique ou une liste (relais).
    Les ``splits`` sont en principe toujours vides pour le Maroc.

    Attributes:
        Rank: Classement (1, 2, 3, …).
        club: Nom du club (clé en minuscules dans les JSON source).
        SwimTime: Temps affiché (ex. ``52.34`` ou ``1:02.15``).
        SwimTimeSeconds: Temps en secondes (≥ 0 si la performance est valide).
        Status: Statut du résultat (ex. OK, DSQ).
        Speed: Vitesse moyenne (m/s) si disponible.
        swimmer: Nageur unique ou liste de nageurs (relais).
        splits: Passages intermédiaires (habituellement vide pour FRM).
    """

    Rank: Optional[int] = Field(None, description="Classement")
    club: Optional[str] = Field(None, description="Nom du club")
    SwimTime: Optional[str] = Field(None, description="Temps affiché")
    SwimTimeSeconds: Optional[float] = Field(
        None, description="Temps en secondes", ge=0
    )
    Status: Optional[str] = Field(None, description="Statut du résultat")
    Speed: Optional[float] = Field(None, description="Vitesse moyenne (m/s)")
    swimmer: Optional[FrmNageurOuRelais] = Field(
        None, description="Nageur unique ou liste de nageurs (relais)"
    )
    splits: list[dict] = Field(
        default_factory=list,
        description="Passages intermédiaires (souvent vide pour FRM Natation)",
    )

    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    @field_validator("swimmer", mode="before")
    @classmethod
    def normalize_swimmer(cls, v: object) -> Optional[FrmNageurOuRelais]:
        """Normalise le champ swimmer en ``FrmNageur`` ou ``list[FrmNageur]``.

        Args:
            v (object): Valeur brute (dict, liste de dicts, None).

        Returns:
            Optional[FrmNageurOuRelais]: Instance(s) validée(s), ou None si absent.
        """
        if v is None:
            return None
        if isinstance(v, list):
            return [FrmNageur.model_validate(x) for x in v]
        if isinstance(v, dict):
            return FrmNageur.model_validate(v)
        return None


class FrmEpreuve(BaseModel):
    """Une épreuve (course) dans une compétition FRM Natation.

    Attributes:
        Event: Libellé unifié (ex. ``100 FR LCM``).
        Distance: Distance en mètres.
        Stroke: Code nage (FR, BK, BR, FL, IM ; ou DOS, PAP, 4N avant prétraitement).
        Course: Type de bassin (LCM, SCM).
        PoolLength: Longueur de bassin en mètres (25 ou 50).
        tour: Tour ou série (ex. Finale, Séries).
        performances: Liste des résultats de l'épreuve.
    """

    Event: Optional[str] = Field(None, description="Libellé épreuve (ex. 100 FR LCM)")
    Distance: Optional[int] = Field(None, description="Distance en mètres")
    Stroke: Optional[str] = Field(None, description="Code nage (FR, BK, DOS, PAP, …)")
    Course: Optional[str] = Field(None, description="Bassin (LCM, SCM)")
    PoolLength: Optional[int] = Field(None, description="Longueur de bassin (25 ou 50)")
    tour: Optional[str] = Field(None, description="Tour ou série")
    performances: list[FrmPerformance] = Field(
        default_factory=list, description="Liste des performances"
    )

    model_config = {"extra": "ignore", "str_strip_whitespace": True}


class FrmCompetition(BaseModel):
    """Données complètes d'une compétition FRM Natation (un fichier JSON).

    Représente un fichier tel que stocké sous ``data/raw/frmnatation/html_results/``
    ou ``data/processed/frmnatation/html_results/``. Les champs supplémentaires
    non déclarés sont ignorés.

    Attributes:
        Meet: Nom de la compétition.
        SwimDate: Date de la compétition (ISO ou texte brut).
        SwimYear: Année de la compétition.
        location: Lieu (clé en minuscules dans les JSON source).
        Country: Code pays (ex. MAR).
        epreuves: Liste des épreuves et performances.
    """

    Meet: Optional[str] = Field(None, description="Nom de la compétition")
    SwimDate: Optional[str] = Field(None, description="Date de la compétition")
    SwimYear: Optional[int] = Field(None, description="Année de la compétition")
    location: Optional[str] = Field(None, description="Lieu de la compétition")
    Country: Optional[str] = Field(None, description="Code pays (ex. MAR)")
    epreuves: list[FrmEpreuve] = Field(
        default_factory=list, description="Liste des épreuves"
    )

    model_config = {"extra": "ignore", "str_strip_whitespace": True}

    @classmethod
    def from_json_file(cls, path: str) -> FrmCompetition:
        """Charge et valide une compétition FRM depuis un fichier JSON.

        Args:
            path (str): Chemin vers le fichier ``.json``.

        Returns:
            FrmCompetition: Instance validée.

        Raises:
            ValidationError: Si le JSON ne respecte pas le schéma.
            OSError: Si le fichier est illisible.
        """
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_json_file(self, path: str, indent: int = 2) -> None:
        """Sérialise la compétition dans un fichier JSON UTF-8.

        Args:
            path (str): Chemin de sortie.
            indent (int): Indentation JSON (défaut 2).

        Returns:
            None
        """
        import json

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=indent)
