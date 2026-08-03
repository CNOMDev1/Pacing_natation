"""Router FastAPI prototype : couloir + recherche nageur (+ pays).

Endpoints minimaux branchés sur ``services.api_core``.
Entrées / sorties validées par ``pacing.api.schemas`` (Pydantic).
Doc interactive : ``/docs``.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from pacing.api.schemas import (
    CompareParams,
    CompareResponse,
    CorridorParams,
    CorridorResponse,
    CountriesResponse,
    EventsParams,
    EventsReferentialResponse,
    SwimmerSearchParams,
    SwimmerSearchResponse,
)
from services.api_core import (
    build_compare_payload,
    build_corridor_payload,
    list_countries,
    list_event_combos,
    search_swimmers,
)

router = APIRouter(prefix="/api/v1", tags=["pacing"])


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
        CorridorResponse: ``meta``, ``bands[]``, ``swimmer``.
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
        CompareResponse: ``bands``, ``swimmer_a``, ``swimmer_b``.
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
