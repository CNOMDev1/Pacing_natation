from fastapi import APIRouter, Query
import asyncio
import subprocess
import json
import os

from pacing.ingestion.extranat.service import (
    get_all_results_grouped_by_event_by_type,
    COMPETITIONS_PER_TYPE_DIR,
)

router = APIRouter(prefix="/extranat", tags=["extranat"])


@router.get("/results")
async def get_results():
    """
    Récupère tous les résultats de toutes les compétitions en utilisant
    la logique basée sur le formulaire (get_results_for_competitions_url),
    via la fonction métier `get_all_results_grouped_by_event_by_type`.
    """
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None,
        lambda: get_all_results_grouped_by_event_by_type(
            delay_between_comps=1.0,
            debug=True,
            only_idtyps=None,
        ),
    )
    return data


@router.get("/results/by-date")
async def get_results_by_date():
    return {"endpoint": "results_by_date"}


