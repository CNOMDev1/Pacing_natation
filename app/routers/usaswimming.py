"""Endpoints USA Swimming."""
import asyncio
from fastapi import APIRouter, HTTPException
from app.services.usaswimming_service import run_one_shot_full_download, get_all_results

router = APIRouter(prefix="/usaswimming", tags=["usaswimming"])


def _download_then_get_results():
    """Lance le téléchargement complet puis retourne (result_download, data)."""
    download_result = run_one_shot_full_download()
    data = get_all_results()
    return download_result, data


@router.get("/results")
async def get_all_usaswimming_results():
    """Tous les résultats USA Swimming : lance le téléchargement puis retourne les données."""
    download_result, data = await asyncio.get_event_loop().run_in_executor(None, _download_then_get_results)
    if not download_result.get("success"): raise HTTPException(status_code=download_result.get("http_status", 503), detail=download_result.get("message", "Échec du téléchargement USA Swimming."))
    return {"count_competitions": data["count_competitions"], "count_results": data["count_results"], "data": data}
