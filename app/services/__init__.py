# Services (logique métier: scraping Omega, Extranat)
from app.services.omega_service import (
    BASE_URL,
    DIRECT_COMPETITION_URLS,
    END_YEAR,
    REVERSE_ORDER,
    START_YEAR,
    TIMEOUT_INDEX,
    TIMEOUT_OLD_YEARS,
    fetch_with_retries,
    session,
    download_total_ranking_pdfs_for_meet,
)
from app.services.extranat_service import (
    get_competition_types,
    get_competitions_for_url,
    get_competition_data,
    get_all_results_by_type,
    get_results_for_competitions_url,
    get_international_results,
    generate_resume,
)

__all__ = [
    "BASE_URL",
    "DIRECT_COMPETITION_URLS",
    "END_YEAR",
    "REVERSE_ORDER",
    "START_YEAR",
    "TIMEOUT_INDEX",
    "TIMEOUT_OLD_YEARS",
    "fetch_with_retries",
    "session",
    "download_total_ranking_pdfs_for_meet",
    "get_competition_types",
    "get_competitions_for_url",
    "get_competition_data",
    "get_all_results_by_type",
    "get_results_for_competitions_url",
    "get_international_results",
    "generate_resume",
]
