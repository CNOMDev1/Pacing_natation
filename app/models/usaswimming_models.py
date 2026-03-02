"""Modèles Pydantic pour les données générées par l'API USA Swimming"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, RootModel


class NageurRecord(BaseModel):
    """Un enregistrement de temps de nage (best time)."""

    Name: Optional[str] = Field(None, description="Nom du nageur")
    Federation: Optional[str] = Field(None, description="Fédération / pays du nageur")
    Team: Optional[str] = Field(None, description="Club / équipe du nageur")
    Event: Optional[str] = Field(None, description="Code de l'épreuve (ex: 800 FR SCM, 50 FR LCM)")
    Gender: Optional[str] = Field(None, description="Catégorie (Male / Female)")
    LSC: Optional[str] = Field(None, description="LSC (Local Swimming Committee)")
    Meet: Optional[str] = Field(None, description="Nom de la compétition")
    SwimDate: Optional[datetime] = Field(None, description="Date de la nage")
    SwimTime: Optional[str] = Field(None, description="Temps formaté (ex: 9:41.49)")
    SwimTimeSeconds: Optional[float] = Field(None, description="Temps en secondes", ge=0)
    Points: Optional[float] = Field(None, description="Points marqués pour cette performance")
    TimeStandard: Optional[str] = Field(None, description="Time standard atteint (ex: AAA, JR NATS, etc.)")

    model_config = {
        "str_strip_whitespace": True,
    }

NageursList = RootModel[list[NageurRecord]]
