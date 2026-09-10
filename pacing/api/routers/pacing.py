"""Router FastAPI prototype : couloir + recherche nageur (+ pays).

Endpoints minimaux branchés sur ``services.api_core``.
Entrées / sorties validées par ``pacing.api.schemas`` (Pydantic).
Doc interactive : ``/docs``.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from pacing.api.schemas import (
    ApiErrorResponse,
    CompareParams,
    CompareResponse,
    CorridorParams,
    CorridorResponse,
    CountriesResponse,
    CreateSwimmerRequest,
    CreateSwimmerResponse,
    EventsParams,
    EventsReferentialResponse,
    GraphCatalogResponse,
    SwimmerSearchParams,
    SwimmerSearchResponse,
)
from pacing.application.manual_swimmer_store import save_manual_swimmer
from pacing.grammar.corridor import (
    compare_spec_from_payload,
    corridor_spec_from_payload,
)
from pacing.application.api_core import (
    build_compare_payload,
    build_corridor_payload,
    list_countries,
    list_event_combos,
    list_graph_catalog,
    search_swimmers,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["pacing"],
    responses={
        400: {"model": ApiErrorResponse, "description": "Requête invalide"},
        422: {"model": ApiErrorResponse, "description": "Paramètres invalides"},
    },
)


@router.get("/pays", response_model=CountriesResponse)
def get_pays() -> CountriesResponse:
    """
    Liste les pays disponibles (référentiel minimal).

    Returns:
        CountriesResponse: ``{ countries: [{ code, label }, ...] }``.
    """
    return CountriesResponse.model_validate(list_countries())


@router.get("/nageur/recherche", response_model=SwimmerSearchResponse)
def get_nageur_recherche(
    params: Annotated[SwimmerSearchParams, Query()],
) -> SwimmerSearchResponse:
    """
    Recherche de nageurs (autocomplete) dans un scope donné.

    Args:
        params (SwimmerSearchParams): Query params validés (q, country, …).

    Returns:
        SwimmerSearchResponse: Payload ``status``, ``results[]``.
    """
    try:
        payload = search_swimmers(
            q=params.q,
            country=params.country.value,
            stroke=params.stroke.value if params.stroke else None,
            distance=params.distance,
            pool=params.pool.value if params.pool else None,
            event=params.event,
            gender=params.gender.value,
            limit=params.limit,
        )
        return SwimmerSearchResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/nageur", response_model=CreateSwimmerResponse)
def post_nageur(body: CreateSwimmerRequest) -> CreateSwimmerResponse:
    """
    Enregistre une performance (nageur + épreuve + temps) dans ``manual_performances``.
    """
    try:
        payload = save_manual_swimmer(
            name=body.name,
            year_of_birth=body.year_of_birth,
            gender=body.gender,
            country=body.country.value,
            club=body.club,
            stroke=body.stroke.value,
            distance=body.distance,
            pool=body.pool.value,
            time_s=body.time_s,
            time_text=body.time_text,
            meet_date=body.meet_date,
            age=body.age,
        )
        return CreateSwimmerResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/couloir", response_model=CorridorResponse)
def get_couloir(
    params: Annotated[CorridorParams, Query()],
) -> CorridorResponse:
    """
    Couloir de performance (bandes percentiles + courbe nageur optionnelle).

    ``country`` = pays du peloton (percentiles).
    ``swimmer_country`` = pays source du nageur (défaut = country).

    Temps en **secondes**, âge en **années**, distance en **mètres**.

    Args:
        params (CorridorParams): Query params validés.

    Returns:
        CorridorResponse: ``meta``, ``bands[]``, ``swimmer``, ``spec``.
    """
    try:
        payload = build_corridor_payload(
            country=params.country.value,
            stroke=params.stroke.value,
            distance=params.distance,
            pool=params.pool.value,
            gender=params.gender.value,
            swimmer_name=params.swimmer_name,
            swimmer_yob=params.swimmer_yob,
            swimmer_country=(
                params.swimmer_country.value if params.swimmer_country else None
            ),
            corridor_type=params.corridor_type.value,
        )
        payload["spec"] = corridor_spec_from_payload(payload).to_dict()
        return CorridorResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/comparaison", response_model=CompareResponse)
def get_comparaison(
    params: Annotated[CompareParams, Query()],
) -> CompareResponse:
    """
    Compare deux nageurs sur le même couloir de performance.

    Le peloton de référence vient de ``country`` ; chaque nageur peut venir
    d'un autre pays (ex. overlay Maroc sur couloir France).

    Args:
        params (CompareParams): Query params validés (A / B + épreuve).

    Returns:
        CompareResponse: ``bands``, ``swimmer_a``, ``swimmer_b``, ``spec``.
    """
    try:
        payload = build_compare_payload(
            country=params.country.value,
            stroke=params.stroke.value,
            distance=params.distance,
            pool=params.pool.value,
            gender=params.gender.value,
            swimmer_a_name=params.swimmer_a_name,
            swimmer_a_yob=params.swimmer_a_yob,
            swimmer_a_country=(
                params.swimmer_a_country.value if params.swimmer_a_country else None
            ),
            swimmer_b_name=params.swimmer_b_name,
            swimmer_b_yob=params.swimmer_b_yob,
            swimmer_b_country=(
                params.swimmer_b_country.value if params.swimmer_b_country else None
            ),
        )
        payload["spec"] = compare_spec_from_payload(payload).to_dict()
        return CompareResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/referentiels/epreuves", response_model=EventsReferentialResponse)
def get_epreuves(
    params: Annotated[EventsParams, Query()],
) -> EventsReferentialResponse:
    """
    Référentiel léger : nages / distances / bassins (ou events USA).

    Args:
        params (EventsParams): Query params (country).

    Returns:
        EventsReferentialResponse: Arbre ``strokes`` ou liste ``events``.
    """
    try:
        payload = list_event_combos(params.country.value)
        return EventsReferentialResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/graphiques", response_model=GraphCatalogResponse)
def get_graphiques(
    params: Annotated[EventsParams, Query()],
) -> GraphCatalogResponse:
    """
    Catalogue des graphiques disponibles pour un pays.

    Chaque entrée porte un champ ``endpoint`` : il indique par quel appel HTTP
    le graphique est réellement obtenable sous forme de ``ChartSpec``. Un
    ``endpoint`` nul signale un graphique aujourd'hui rendu uniquement par
    l'application Flet, en local.

    Args:
        params (EventsParams): Query params (country).

    Returns:
        GraphCatalogResponse: ``country``, ``count``, ``categories[]``.
    """
    try:
        payload = list_graph_catalog(params.country.value)
        return GraphCatalogResponse.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
