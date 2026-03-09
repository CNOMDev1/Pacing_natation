from fastapi import APIRouter, HTTPException
from app.services.usaswimming_service import run_one_shot_full_download, get_all_results
import asyncio

router = APIRouter(prefix="/usaswimming", tags=["usaswimming"])


def _download_then_get_results():
    download_result = run_one_shot_full_download()
    data = get_all_results()
    return download_result, data


@router.get("/results")
async def get_all_usaswimming_results():
    loop = asyncio.get_event_loop()
    download_result, data = await loop.run_in_executor(None, _download_then_get_results)
    if not download_result.get("success", False):
        raise HTTPException(
            status_code=download_result.get("http_status", 503),
            detail=download_result.get("message", "Échec du téléchargement USA Swimming."),
        )
    return data