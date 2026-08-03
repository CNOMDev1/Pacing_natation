"""Modèles Pydantic pour les données générées par l'API USA Swimming Data Hub.

Ce module décrit la structure d'un enregistrement « best time » tel que
renvoyé par l'API USA Swimming avant normalisation par
``usaswimming_preprocessing``.

Le flux de données :
1. **Réponse API** — liste d'objets JSON mappés sur ``NageurRecord``.
2. **Validation** — Pydantic coerce les dates et supprime les espaces de bord.
3. **Persistance** — les enregistrements validés sont écrits en JSON brut
   sous ``data/raw/usaswimming/`` puis retraités vers le format Extranat unifié.

Point d'entrée type : ``NageursList`` (``RootModel[list[NageurRecord]]``).
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, RootModel


class NageurRecord(BaseModel):
    """Un enregistrement de temps de nage (best time) USA Swimming.

    Correspond à une ligne de résultat de l'API Data Hub. Les champs
    ``Place`` / ``Rank`` restent typés largement car la source peut fournir
    des entiers ou des chaînes (« N/A », etc.).

    Attributes:
        Name: Nom du nageur.
        Federation: Fédération / pays du nageur.
        Team: Club ou équipe.
        DateOfBirth: Date de naissance si disponible.
        Event: Code épreuve (ex. ``800 FR SCM``).
        Gender: Catégorie (Male / Female).
        Session: Session (Prelim, Final, etc.).
        LSC: Local Swimming Committee.
        AgeGroup: Catégorie d'âge.
        Meet: Nom de la compétition.
        Place: Place brute telle que fournie par l'API.
        Rank: Rang normalisé (souvent dérivé de Place).
        SwimDate: Date de la nage.
        SwimTime: Temps formaté (ex. ``9:41.49``).
        SwimTimeSeconds: Temps en secondes (≥ 0).
        Points: Points marqués pour la performance.
        TimeStandard: Standard atteint (AAA, JR NATS, etc.).
    """

    Name: Optional[str] = Field(None, description="Nom du nageur")
    Federation: Optional[str] = Field(None, description="Fédération / pays du nageur")
    Team: Optional[str] = Field(None, description="Club / équipe du nageur")
    Club: Optional[str] = Field(None, description="Club (alias de Team dans certains exports)")
    DateOfBirth: Optional[datetime] = Field(None, description="Date de naissance (si disponible)")
    Year_of_birth: Optional[int] = Field(None, description="Année de naissance")
    Nationality: Optional[str] = Field(None, description="Nationalité (code pays)")
    Event: Optional[str] = Field(None, description="Code de l'épreuve (ex: 800 FR SCM, 50 FR LCM)")
    Gender: Optional[str] = Field(None, description="Catégorie (Male / Female)")
    Session: Optional[str] = Field(None, description="Session (Prelim / TimedFinal / Final, etc.)")
    LSC: Optional[str] = Field(None, description="LSC (Local Swimming Committee)")
    AgeGroup: Optional[str] = Field(None, description="Catégorie d'âge (AgeGroup1)")
    Meet: Optional[str] = Field(None, description="Nom de la compétition")
    Place: Optional[Any] = Field(None, description="Place / finish position (si disponible)")
    Rank: Optional[Any] = Field(None, description="Rang (normalisé à partir de Place)")
    SwimDate: Optional[datetime] = Field(None, description="Date de la nage")
    SwimTime: Optional[str] = Field(None, description="Temps formaté (ex: 9:41.49)")
    SwimTimeSeconds: Optional[float] = Field(None, description="Temps en secondes", ge=0)
    Points: Optional[float] = Field(None, description="Points marqués pour cette performance")
    TimeStandard: Optional[str] = Field(None, description="Time standard atteint (ex: AAA, JR NATS, etc.)")

    model_config = {
        "extra": "ignore",
        "str_strip_whitespace": True,
    }

    def resolved_year_of_birth(self) -> Optional[int]:
        """Retourne ``Year_of_birth`` ou l'année extraite de ``DateOfBirth``."""
        if self.Year_of_birth is not None:
            return self.Year_of_birth
        if self.DateOfBirth is not None:
            return self.DateOfBirth.year
        return None

    def resolved_club(self) -> Optional[str]:
        """Retourne le club depuis ``Club`` ou ``Team``."""
        return self.Club or self.Team


class NageursList(RootModel[list[NageurRecord]]):
    """Liste racine de performances USA Swimming (réponse API typique).

    Utilisé pour valider un fichier JSON contenant un tableau d'enregistrements
    ``NageurRecord`` en une seule passe Pydantic.
    """

    root: list[NageurRecord]

    @classmethod
    def from_json_file(cls, path: str | Path) -> "NageursList":
        """Charge et valide une liste de performances USA Swimming depuis un JSON.

        Args:
            path (str | Path): Chemin vers le fichier ``.json`` (racine = liste).

        Returns:
            NageursList: Instance validée.

        Raises:
            ValidationError: Si le JSON ne respecte pas le schéma.
            OSError: Si le fichier est illisible.
            ValueError: Si la racine JSON n'est pas une liste.
        """
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"Le fichier {path} ne contient pas une liste JSON.")
        return cls.model_validate(data)
