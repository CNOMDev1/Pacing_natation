"""Tests de validation Pydantic (Extranat, FRM, USA Swimming)."""
from __future__ import annotations

from app.models.extranat_models import CompetitionExtranat
from app.models.frmn_models import FrmCompetition
from app.models.usaswimming_models import NageurRecord, NageursList


def test_frm_competition_minimal() -> None:
    """FrmCompetition accepte un JSON compétition minimal."""
    model = FrmCompetition.model_validate(
        {
            "Meet": "Championnats Maroc",
            "SwimDate": "2024-01-15",
            "SwimYear": 2024,
            "location": "Casablanca",
            "Country": "MAR",
            "epreuves": [
                {
                    "Event": "100 FR LCM",
                    "Distance": 100,
                    "Stroke": "FR",
                    "Course": "LCM",
                    "performances": [
                        {
                            "Rank": 1,
                            "club": "Rabat",
                            "SwimTime": "55.12",
                            "SwimTimeSeconds": 55.12,
                            "swimmer": {
                                "Name": "ALAMI Youssef",
                                "Gender": "M",
                                "Year_of_birth": 2005,
                            },
                        }
                    ],
                }
            ],
        }
    )
    assert model.Meet == "Championnats Maroc"
    assert len(model.epreuves) == 1
    assert model.epreuves[0].performances[0].SwimTimeSeconds == 55.12


def test_usa_nageurs_list_minimal() -> None:
    """NageursList valide une liste d'enregistrements best-time."""
    model = NageursList.model_validate(
        [
            {
                "Name": "DOE Jane",
                "Event": "100 FR LCM",
                "Gender": "Female",
                "Meet": "Trials",
                "SwimTime": "53.20",
                "SwimTimeSeconds": 53.2,
            }
        ]
    )
    assert len(model.root) == 1
    assert isinstance(model.root[0], NageurRecord)
    assert model.root[0].Name == "DOE Jane"


def test_extranat_competition_minimal() -> None:
    """CompetitionExtranat valide un objet compétition minimal."""
    model = CompetitionExtranat.model_validate(
        {
            "date": "Samedi 01/01 - Dimanche 02/01/2024",
            "name": "Meeting Test",
            "competition_id": "1",
            "url": "https://example.com",
            "location": "Paris",
            "original_title": "Meeting Test",
            "competition_type": "National",
            "pool_size": "50m",
            "level": "National",
            "results_count": 0,
            "epreuves": [],
        }
    )
    assert model.name == "Meeting Test"
    assert model.epreuves == []
