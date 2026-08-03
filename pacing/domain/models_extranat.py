"""Modèles Pydantic pour les données de compétition Extranat (JSON brut).

Ce module décrit la hiérarchie JSON produite par ``extranat_service`` avant
le prétraitement ``extranat_preprocessing`` :

``CompetitionExtranat`` → ``Epreuve`` → ``Performance`` → ``Nageur``.

Le flux de données :
1. **Scraping** — ``extranat_service`` écrit des fichiers JSON conformes à
   ces schémas sous ``data/raw/extranat/``.
2. **Validation** — ``CompetitionExtranat.model_validate`` ou ``from_json_file``
   vérifie la structure à la lecture.
3. **Prétraitement** — ``extranat_preprocessing`` convertit vers le format
   unifié Pacing (Meet, Event, SwimTimeSeconds, etc.).
"""
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


class Nageur(BaseModel):
    """Nageur ou nageuse dans une performance Extranat brute.

    Attributes:
        name: Nom complet (NOM Prénom).
        sexe: Genre (F ou M).
        annee_naissance: Année de naissance.
        age: Âge à la date de la compétition.
        nationalite: Code pays ISO 3 lettres (ex. FRA).
    """

    name: Optional[str] = Field(None, description="Nom complet (NOM Prénom)")
    sexe: Optional[str] = Field(None, description="F ou M")
    annee_naissance: Optional[int] = Field(None, description="Année de naissance")
    age: Optional[int] = Field(None, description="Âge à la date de la compétition")
    nationalite: Optional[str] = Field(None, description="Code pays (ex: FRA)")


# Un résultat peut avoir 1 nageur (individuel) ou plusieurs (relais)
NageurOuRelais = Union[Nageur, list[Nageur]]


class Performance(BaseModel):
    """Une performance (résultat) dans une épreuve Extranat brute.

    Le champ ``nageur`` accepte un dict unique ou une liste (relais).
    Le validateur ``normalize_nageur`` uniformise les deux cas.

    Attributes:
        classement: Rang (1, 2, 3, …).
        nageur: Nageur unique ou liste de nageurs.
        club: Nom du club.
        temps: Temps affiché (ex. ``00:26.14``).
        points: Points FFN.
        mpp: Meilleure performance personnelle (texte brut).
    """

    classement: Optional[int] = Field(None, description="Rang (1, 2, 3, ...)")
    nageur: NageurOuRelais = Field(..., description="Nageur unique ou liste de nageurs (relais)")
    club: Optional[str] = Field(None, description="Nom du club")
    temps: Optional[str] = Field(None, description="Temps affiché (ex: 00:26.14)")
    points: Optional[int] = Field(None, description="Points FFN")
    mpp: Optional[str] = Field(None, description="Meilleure performance personnelle (optionnel)")
    splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Passages intermédiaires (distance, cumul, split, …)",
    )

    model_config = {"extra": "ignore"}

    @field_validator("nageur", mode="before")
    @classmethod
    def normalize_nageur(cls, v: object) -> NageurOuRelais:
        """Normalise le champ nageur en ``Nageur`` ou ``list[Nageur]``.

        Args:
            v (object): Valeur brute (dict, liste de dicts).

        Returns:
            NageurOuRelais: Instance(s) ``Nageur`` validée(s).
        """
        if isinstance(v, list):
            return [Nageur.model_validate(x) for x in v]
        return Nageur.model_validate(v)


class Epreuve(BaseModel):
    """Une épreuve (course) dans une compétition Extranat brute.

    Attributes:
        nom: Libellé français (ex. ``50 Nage Libre``).
        categorie: Dames, Messieurs, etc.
        tour: Tour et date (ex. ``Finale A Dimanche …``).
        performances: Liste des résultats de l'épreuve.
    """

    nom: str = Field(..., description="Nom de l'épreuve (ex: 50 Nage Libre)")
    categorie: str = Field(..., description="Dames, Messieurs, etc.")
    tour: str = Field(..., description="Finale A, Séries, etc. + date")
    performances: list[Performance] = Field(default_factory=list, description="Liste des résultats")

    model_config = {"extra": "ignore"}


class CompetitionExtranat(BaseModel):
    """Données complètes d'une compétition Extranat (format JSON sauvegardé).

    Représente un fichier JSON tel qu'écrit par le scraper. Les champs
    supplémentaires non déclarés sont ignorés (``extra = ignore``).

    Attributes:
        date: Plage de dates affichée sur le site.
        name: Nom de la compétition.
        competition_id: Identifiant FFN.
        url: URL des résultats sur Extranat.
        location: Lieu (ex. ``BÉTHUNE (FRA)``).
        original_title: Titre d'origine de la page.
        competition_type: Type labellisé FFN.
        pool_size: Taille de bassin (ex. ``50m``).
        level: Niveau (National, Régional, etc.).
        results_count: Nombre total de résultats scrapés.
        epreuves: Liste des épreuves et performances.
    """

    date: str = Field(..., description="Plage de dates affichée (ex: Samedi 07/02 - Dimanche 08/02/2026)")
    name: str = Field(..., description="Nom de la compétition")
    competition_id: str = Field(..., description="Identifiant FFN (ex: 92298)")
    url: str = Field(..., description="URL des résultats sur extranat")
    location: str = Field(..., description="Lieu (ex: BÉTHUNE (FRA))")
    original_title: str = Field(..., description="Titre d'origine de la compétition")
    competition_type: str = Field(..., description="Type (ex: Meeting National labellisé (106))")
    pool_size: str = Field(..., description="Bassin (ex: 50m)")
    level: str = Field(..., description="Niveau (ex: NationalNat.)")
    results_count: int = Field(..., description="Nombre total de résultats")
    epreuves: list[Epreuve] = Field(default_factory=list, description="Liste des épreuves et performances")

    model_config = {"extra": "ignore"}

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CompetitionExtranat":
        """Charge et valide une compétition depuis un fichier JSON.

        Args:
            path (str | Path): Chemin vers le fichier ``.json``.

        Returns:
            CompetitionExtranat: Instance validée.

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
