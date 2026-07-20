"""Tests du prototype API (api_core + routes FastAPI + Pydantic)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.main import app
from app.models.api_models import (
    CorridorParams,
    CorridorType,
    CountriesResponse,
    CountryCode,
    SwimmerSearchParams,
)
from services.api_core import list_countries, resolve_country_code


def test_resolve_country_code() -> None:
    """Les codes et libellés pays sont normalisés."""
    assert resolve_country_code("FR") == "FR"
    assert resolve_country_code("France") == "FR"
    assert resolve_country_code("MA") == "MA"


def test_list_countries() -> None:
    """Le référentiel pays expose FR, US, MA."""
    payload = list_countries()
    codes = {c["code"] for c in payload["countries"]}
    assert codes == {"FR", "US", "MA"}
    CountriesResponse.model_validate(payload)


def test_docs_available() -> None:
    """Swagger UI est servi sur /docs."""
    client = TestClient(app)
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_pays_endpoint() -> None:
    """GET /api/v1/pays répond un JSON countries."""
    client = TestClient(app)
    resp = client.get("/api/v1/pays")
    assert resp.status_code == 200
    body = resp.json()
    assert "countries" in body
    assert len(body["countries"]) >= 3
    CountriesResponse.model_validate(body)


def test_couloir_validation_missing_params() -> None:
    """GET /couloir sans stroke/distance/pool → 422."""
    client = TestClient(app)
    resp = client.get("/api/v1/couloir", params={"country": "FR"})
    assert resp.status_code == 422


def test_nageur_recherche_requires_q() -> None:
    """GET /nageur/recherche sans q → 422."""
    client = TestClient(app)
    resp = client.get("/api/v1/nageur/recherche", params={"country": "FR"})
    assert resp.status_code == 422


def test_couloir_rejects_invalid_stroke() -> None:
    """Un code nage inconnu est rejeté par Pydantic (422)."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/couloir",
        params={
            "country": "FR",
            "stroke": "XX",
            "distance": 100,
            "pool": "LCM",
        },
    )
    assert resp.status_code == 422


def test_couloir_age_target_requires_swimmer() -> None:
    """age_target sans swimmer_name → 422."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/couloir",
        params={
            "country": "FR",
            "stroke": "FR",
            "distance": 100,
            "pool": "LCM",
            "corridor_type": "age_target",
        },
    )
    assert resp.status_code == 422


def test_corridor_params_model_ok() -> None:
    """CorridorParams accepte une requête FR valide."""
    params = CorridorParams(
        country=CountryCode.FR,
        stroke="FR",
        distance=100,
        pool="LCM",
        corridor_type=CorridorType.AGE_GLOBAL,
    )
    assert params.distance == 100


def test_swimmer_search_params_empty_q() -> None:
    """q vide après strip est invalide."""
    with pytest.raises(ValidationError):
        SwimmerSearchParams(q="   ")


def test_couloir_with_swimmer_auto_age_target() -> None:
    """Fournir swimmer_name bascule en age_target (même sans corridor_type)."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/couloir",
        params={
            "country": "FR",
            "stroke": "BK",
            "distance": 50,
            "pool": "SCM",
            "swimmer_name": "Nageur Inexistant XYZ",
            "swimmer_yob": 1997,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["corridor_type"] == "age_target"
    assert body["meta"]["swimmer_country"] == "FR"
    assert body["swimmer"] is not None
    assert body["status"] in ("not_found", "ok")


def test_couloir_peloton_fr_swimmer_ma() -> None:
    """Peloton FR + nageur MA via swimmer_country."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/couloir",
        params={
            "country": "FR",
            "stroke": "BK",
            "distance": 50,
            "pool": "SCM",
            "swimmer_name": "ACHBABI Yousra",
            "swimmer_yob": 1997,
            "swimmer_country": "MA",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["country"] == "FR"
    assert body["meta"]["swimmer_country"] == "MA"
    assert body["meta"]["corridor_type"] == "age_target"
    # Si les données MA sont présentes localement → ok + points
    if body["status"] == "ok":
        assert body["swimmer"] is not None
        assert body["swimmer"]["country"] == "MA"
        assert len(body["swimmer"]["points"]) >= 1
    else:
        assert body["status"] == "not_found"
        assert body["missing"] == ["swimmer"]


def test_comparaison_requires_swimmers() -> None:
    """GET /comparaison sans nageurs → 422."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/comparaison",
        params={
            "country": "FR",
            "stroke": "FR",
            "distance": 100,
            "pool": "LCM",
        },
    )
    assert resp.status_code == 422


def test_couloir_accepts_us_country() -> None:
    """country=US est supporté sur /couloir (AgeGroup)."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/couloir",
        params={
            "country": "US",
            "stroke": "BK",
            "distance": 50,
            "pool": "SCM",
            "swimmer_name": "Milana Hamza",
            "swimmer_country": "US",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["country"] == "US"
    assert "usa_agegroup" in body["meta"]["corridor_type"]
    assert body["status"] in ("ok", "not_found", "empty")


def test_comparaison_accepts_us_country() -> None:
    """country=US n'est plus rejeté (422) sur /comparaison."""
    client = TestClient(app)
    resp = client.get(
        "/api/v1/comparaison",
        params={
            "country": "US",
            "stroke": "BK",
            "distance": 50,
            "pool": "SCM",
            "swimmer_a_name": "ACHBABI Yousra",
            "swimmer_a_yob": 1997,
            "swimmer_a_country": "MA",
            "swimmer_b_name": "Milana Hamza",
            "swimmer_b_country": "US",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["country"] == "US"
    assert body["meta"]["corridor_type"] == "usa_agegroup"
    assert body["status"] in ("ok", "not_found", "empty")


def test_comparaison_endpoint_smoke() -> None:
    """GET /comparaison renvoie un payload validé (ok ou not_found)."""
    client = TestClient(app)
    # Récupère deux nageurs réels si possible
    search = client.get(
        "/api/v1/nageur/recherche",
        params={
            "q": "a",
            "country": "FR",
            "stroke": "FR",
            "distance": 100,
            "pool": "LCM",
            "limit": 2,
        },
    )
    assert search.status_code == 200
    results = search.json().get("results") or []
    if len(results) < 2:
        # Pas assez de données locales : au moins la route existe
        resp = client.get(
            "/api/v1/comparaison",
            params={
                "country": "FR",
                "stroke": "FR",
                "distance": 100,
                "pool": "LCM",
                "swimmer_a_name": "TEST A",
                "swimmer_b_name": "TEST B",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] in ("not_found", "empty", "ok")
        return

    a, b = results[0], results[1]
    resp = client.get(
        "/api/v1/comparaison",
        params={
            "country": "FR",
            "stroke": "FR",
            "distance": 100,
            "pool": "LCM",
            "swimmer_a_name": a["name"],
            "swimmer_a_yob": a.get("year_of_birth"),
            "swimmer_b_name": b["name"],
            "swimmer_b_yob": b.get("year_of_birth"),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "not_found", "empty")
    assert "swimmer_a" in body and "swimmer_b" in body
    assert "bands" in body
