"""Tests de validation Pydantic (Extranat, FRM, USA Swimming)."""
from __future__ import annotations

import json
from pathlib import Path

from pacing.domain.models_extranat import CompetitionExtranat
from pacing.domain.models_frmn import FrmCompetition
from pacing.domain.models_usaswimming import NageurRecord, NageursList
from pacing.ingestion.extranat.preprocessing import clean_extranat_competition
from pacing.ingestion.frmnatation.preprocessing import preprocess_competition
from pacing.ingestion.usaswimming.preprocessing import clean_record

EXTRANAT_RAW_SAMPLE = {
    "date": "Samedi 01/02 - Dimanche 02/02/2024",
    "name": "Meeting Test-Dames",
    "competition_id": "92298",
    "url": "https://example.com",
    "location": "BÉTHUNE (FRA)",
    "original_title": "Meeting Test",
    "competition_type": "National",
    "pool_size": "50m",
    "level": "NationalNat.",
    "results_count": 1,
    "epreuves": [
        {
            "nom": "50 Nage Libre",
            "categorie": "Dames",
            "tour": "Finale A Dimanche 4 Février 2024",
            "performances": [
                {
                    "classement": 1,
                    "nageur": {
                        "name": "DUPONT Marie 2005 FRA",
                        "sexe": "F",
                        "annee_naissance": 2005,
                        "age": 19,
                        "nationalite": "FRA",
                    },
                    "club": "Paris Natation",
                    "temps": "00:26.14",
                    "points": 850,
                }
            ],
        }
    ],
}


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


def test_extranat_from_json_file(tmp_path: Path) -> None:
    """CompetitionExtranat.from_json_file charge et valide un fichier JSON."""
    json_path = tmp_path / "meeting.json"
    json_path.write_text(json.dumps(EXTRANAT_RAW_SAMPLE), encoding="utf-8")

    model = CompetitionExtranat.from_json_file(json_path)

    assert model.name == "Meeting Test-Dames"
    assert model.epreuves[0].nom == "50 Nage Libre"
    assert model.epreuves[0].performances[0].temps == "00:26.14"


def test_clean_extranat_competition_uses_typed_fields() -> None:
    """clean_extranat_competition consomme un CompetitionExtranat typé."""
    competition = CompetitionExtranat.model_validate(EXTRANAT_RAW_SAMPLE)
    cleaned = clean_extranat_competition(competition, default_gender="F")

    assert cleaned["Meet"] == "Meeting Test"
    assert cleaned["Country"] == "FRA"
    assert cleaned["epreuves"][0]["Event"] == "50 FR LCM"
    perf = cleaned["epreuves"][0]["performances"][0]
    assert perf["SwimTime"] == "00:26.14"
    assert perf["Rank"] == 1
    assert perf["swimmer"]["Gender"] == "F"
    assert perf["swimmer"]["Year_of_birth"] == 2005


FRM_RAW_SAMPLE = {
    "Meet": "Championnats Maroc",
    "SwimDate": "2024-01-15",
    "SwimYear": 2024,
    "location": "Casablanca",
    "Country": "MAR",
    "epreuves": [
        {
            "Event": "100 DOS LCM",
            "Distance": 100,
            "Stroke": "DOS",
            "Course": "LCM",
            "PoolLength": 50,
            "tour": "Finale",
            "performances": [
                {
                    "Rank": 1,
                    "club": "Rabat",
                    "SwimTime": "55.12",
                    "SwimTimeSeconds": 55.12,
                    "Status": "OK",
                    "swimmer": {
                        "Name": "ALAMI YOUSSEF",
                        "Gender": "M",
                        "Year_of_birth": 2005,
                        "Age": 19,
                    },
                },
                {
                    "Rank": 2,
                    "club": "Casa",
                    "SwimTime": "NaN",
                    "SwimTimeSeconds": None,
                    "swimmer": {"Name": "IGNORE ME"},
                },
            ],
        }
    ],
}

USA_RAW_SAMPLE = [
    {
        "Name": "DOE Jane",
        "Event": "100 FR LCM",
        "Gender": "Female",
        "Meet": "Trials",
        "SwimDate": "2024-06-01",
        "SwimTime": "53.20",
        "SwimTimeSeconds": 53.2,
        "Rank": 1,
        "Team": "Aquatic Club",
        "Federation": "United States",
    }
]


def test_frm_from_json_file(tmp_path: Path) -> None:
    """FrmCompetition.from_json_file charge et valide un fichier JSON."""
    json_path = tmp_path / "maroc.json"
    json_path.write_text(json.dumps(FRM_RAW_SAMPLE), encoding="utf-8")

    model = FrmCompetition.from_json_file(json_path)

    assert model.Meet == "Championnats Maroc"
    assert model.epreuves[0].Stroke == "DOS"
    assert model.epreuves[0].performances[0].SwimTimeSeconds == 55.12


def test_preprocess_frm_competition_uses_typed_fields() -> None:
    """preprocess_competition consomme un FrmCompetition typé."""
    competition = FrmCompetition.model_validate(FRM_RAW_SAMPLE)
    cleaned, before, after, names_changed = preprocess_competition(competition)

    assert before == 2
    assert after == 1
    assert names_changed == 1
    assert cleaned["epreuves"][0]["Stroke"] == "BK"
    assert cleaned["epreuves"][0]["Event"] == "100 BK LCM"
    assert cleaned["epreuves"][0]["performances"][0]["swimmer"]["Name"] == "ALAMI Youssef"


def test_usa_from_json_file(tmp_path: Path) -> None:
    """NageursList.from_json_file charge une liste de performances USA."""
    json_path = tmp_path / "usa.json"
    json_path.write_text(json.dumps(USA_RAW_SAMPLE), encoding="utf-8")

    model = NageursList.from_json_file(json_path)

    assert len(model.root) == 1
    assert model.root[0].Name == "DOE Jane"
    assert model.root[0].resolved_club() == "Aquatic Club"


def test_clean_usa_record_uses_typed_fields() -> None:
    """clean_record consomme un NageurRecord typé."""
    record = NageurRecord.model_validate(USA_RAW_SAMPLE[0])
    cleaned = clean_record(record)

    assert cleaned is not None
    assert cleaned["Name"] == "Doe Jane"
    assert cleaned["Gender"] == "F"
    assert cleaned["Country"] == "USA"
    assert cleaned["Club"] == "Aquatic Club"
    assert cleaned["Event"] == "100 FR LCM"
