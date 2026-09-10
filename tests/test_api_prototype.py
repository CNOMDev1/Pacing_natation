"""Tests du prototype API (api_core + routes FastAPI + Pydantic)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from pacing.api.export_openapi import OPENAPI_PATH, check as openapi_is_fresh
from pacing.api.main import app
from pacing.api.schemas import (
    ApiErrorResponse,
    CorridorParams,
    CorridorType,
    CountriesResponse,
    CountryCode,
    GraphCatalogResponse,
    SwimmerSearchParams,
)
from pacing.application.api_core import (
    list_countries,
    list_graph_catalog,
    resolve_country_code,
)


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


def test_validation_error_uses_single_format() -> None:
    """Une erreur de validation a la forme {"error": {code, message, details}}."""
    client = TestClient(app)
    resp = client.get("/api/v1/couloir", params={"country": "FR"})
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" not in body
    ApiErrorResponse.model_validate(body)
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"]
    fields = {item["field"] for item in body["error"]["details"]}
    assert {"query.stroke", "query.distance", "query.pool"} <= fields


def test_http_error_uses_single_format() -> None:
    """Une route inconnue renvoie aussi {"error": {...}}, sans "detail"."""
    client = TestClient(app)
    resp = client.get("/api/v1/route-inexistante")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" not in body
    ApiErrorResponse.model_validate(body)
    assert body["error"]["code"] == "not_found"
    assert body["error"].get("details") is None


def test_graph_catalog_endpoint() -> None:
    """GET /graphiques expose le catalogue et les endpoints disponibles."""
    client = TestClient(app)
    resp = client.get("/api/v1/graphiques", params={"country": "FR"})
    assert resp.status_code == 200
    body = resp.json()
    GraphCatalogResponse.model_validate(body)
    assert body["country"] == "FR"
    assert body["count"] > 0
    assert body["categories"]

    graphs = [
        graph for category in body["categories"] for graph in category["graphs"]
    ]
    assert all(graph["key"] for graph in graphs), "toute entrée porte une clé stable"

    endpoints = {graph["endpoint"] for graph in graphs}
    assert "/api/v1/couloir" in endpoints, "le couloir doit être servi par l'API"
    assert None in endpoints, "les graphiques non exposés doivent rester visibles"


def test_graph_catalog_endpoint_depends_on_country() -> None:
    """Le couloir servi par l'API diffère entre la France et les États-Unis."""
    client = TestClient(app)

    def served_keys(country: str) -> set[str]:
        body = client.get("/api/v1/graphiques", params={"country": country}).json()
        return {
            graph["key"]
            for category in body["categories"]
            for graph in category["graphs"]
            if graph["endpoint"]
        }

    assert served_keys("FR") == {
        "performance_corridor_plot_time",
        "performance_corridor_global_plot_time",
    }
    assert served_keys("US") == {"performance_corridor_global_by_agegroup"}


def test_graph_catalog_rejects_unknown_country() -> None:
    """Un pays inconnu lève une ValueError côté cœur métier."""
    with pytest.raises(ValueError):
        list_graph_catalog("ZZ")


def test_openapi_snapshot_is_up_to_date() -> None:
    """docs/openapi.json doit refléter le code (contrat versionné)."""
    assert OPENAPI_PATH.exists(), (
        "docs/openapi.json absent : lancez "
        "python -m pacing.api.export_openapi"
    )
    assert openapi_is_fresh(), (
        "docs/openapi.json est obsolète : relancez "
        "python -m pacing.api.export_openapi"
    )


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
