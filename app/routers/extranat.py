"""Endpoints Extranat"""
import asyncio
from datetime import date
from fastapi import APIRouter, Query
from app.models.competition import TypeCompetitionLabel
from app.services.extranat_service import (
    get_all_results_by_type,
    get_results_by_date_range,
    save_results_to_data_dir,
    save_type_competitions_to_folder,
)

router = APIRouter(prefix="/extranat", tags=["extranat"])


@router.get("/results")
async def get_all_results():
    """Tous les résultats Extranat"""
    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_all_results_by_type(delay_between_comps=0.5, debug=True)
    )
    save_results_to_data_dir(data)
    for t in data.get("types", []):
        idtyp = t.get("idtyp")
        label = t.get("label", "") or f"type_{idtyp}"
        if idtyp is not None:
            save_type_competitions_to_folder({"types": [t]}, idtyp, label)
    return data


@router.get("/results/by-date")
async def get_results_by_date(start_date: date = Query(...), end_date: date = Query(...)):
    """Résultats Extranat entre deux dates."""
    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_results_by_date_range(start_date, end_date)
    )
    types_out = data.get("types", [])
    n_comp = sum(len(t.get("competitions", [])) for t in types_out)
    return {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "count_types": len(types_out),
        "count_competitions": n_comp,
        "data": data,
    }


@router.get("/results/by-type")
async def get_results_by_type(type_competition: TypeCompetitionLabel = Query(..., alias="type_competition")):
    """Résultats pour un type de compétition"""
    idtyp = type_competition.idtyp
    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_all_results_by_type(delay_between_comps=0.5, debug=True, only_idtyps=[idtyp])
    )
    save_type_competitions_to_folder(data, idtyp, type_competition.value)
    return {
        "idtyp": idtyp,
        "type_competition": type_competition.value,
        "count_competitions": sum(len(t.get("competitions", [])) for t in data.get("types", [])),
        "data": data,
    }
