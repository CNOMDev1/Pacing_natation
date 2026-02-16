"""Endpoints Omega"""
import asyncio
from fastapi import APIRouter, Query
from app.services.omega_service import get_all_pdfs_response, get_pdfs_by_years_response

router = APIRouter(prefix="/omega", tags=["omega"])


@router.get("/pdfs")
async def get_all_pdfs():
    """Tous les PDFs"""
    return await asyncio.get_event_loop().run_in_executor(None, get_all_pdfs_response)


@router.get("/pdfs/by-years")
async def get_pdfs_by_years(start_year: int = Query(...), end_year: int = Query(...)):
    """Collecte les PDFs Omega pour la plage d'années"""
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_pdfs_by_years_response(start_year, end_year, execute=True)
    )
