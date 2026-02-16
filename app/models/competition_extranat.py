"""Modèles Pydantic pour les données de compétition Extranat (JSON)."""
from typing import Optional, Union
from pydantic import BaseModel, Field, field_validator


class Nageur(BaseModel):
    """Nageur / nageuse."""
    name: Optional[str] = Field(None, description="Nom complet (NOM Prénom)")
    sexe: Optional[str] = Field(None, description="F ou M")
    annee_naissance: Optional[int] = Field(None, description="Année de naissance")
    age: Optional[int] = Field(None, description="Âge à la date de la compétition")
    nationalite: Optional[str] = Field(None, description="Code pays (ex: FRA)")


# Un résultat peut avoir 1 nageur (individuel) ou plusieurs (relais)
NageurOuRelais = Union[Nageur, list[Nageur]]


class Performance(BaseModel):
    """Une performance (résultat) dans une épreuve."""
    classement: Optional[int] = Field(None, description="Rang (1, 2, 3, ...)")
    nageur: NageurOuRelais = Field(..., description="Nageur unique ou liste de nageurs (relais)")
    club: Optional[str] = Field(None, description="Nom du club")
    temps: Optional[str] = Field(None, description="Temps affiché (ex: 00:26.14)")
    points: Optional[int] = Field(None, description="Points FFN")
    mpp: Optional[str] = Field(None, description="Meilleure performance personnelle (optionnel)")

    @field_validator("nageur", mode="before")
    @classmethod
    def normalize_nageur(cls, v: object) -> NageurOuRelais:
        if isinstance(v, list):
            return [Nageur.model_validate(x) for x in v]
        return Nageur.model_validate(v)


class Epreuve(BaseModel):
    """Une épreuve (course) dans la compétition."""
    nom: str = Field(..., description="Nom de l'épreuve (ex: 50 Nage Libre)")
    categorie: str = Field(..., description="Dames, Messieurs, etc.")
    tour: str = Field(..., description="Finale A, Séries, etc. + date")
    performances: list[Performance] = Field(default_factory=list, description="Liste des résultats")


class CompetitionExtranat(BaseModel):
    """Données complètes d'une compétition Extranat (format JSON sauvegardé)."""
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
    def from_json_file(cls, path: str) -> "CompetitionExtranat":
        """Charge une compétition depuis un fichier JSON."""
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_json_file(self, path: str, indent: int = 2) -> None:
        """Sauvegarde la compétition dans un fichier JSON."""
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=indent)
