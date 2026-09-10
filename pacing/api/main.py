"""Point d'entrée de l'API FastAPI Pacing."""
from typing import Any, Dict

from fastapi import FastAPI

from pacing.api.errors import register_error_handlers
from pacing.api.routers.pacing import router

app = FastAPI(
    title="Pacing",
    version="0.3.0",
    description=(
        "API Pacing métier (couloir, comparaison, recherche nageur, "
        "référentiels, catalogue de graphiques). "
        "Toute erreur 4xx/5xx a la forme {\"error\": {\"code\", \"message\"}}. "
        "Doc interactive : /docs — contrat détaillé : docs/api_contract.md"
    ),
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)

register_error_handlers(app)
app.include_router(router)


@app.get("/")
def root() -> Dict[str, Any]:
    """
    Endpoint racine pour vérifier rapidement que l'API répond.

    Returns:
        dict: Message de bienvenue et liens de documentation.
    """
    return {
        "message": "Bienvenue sur l'API Pacing.",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "version": app.version,
        "pacing_prototype": {
            "pays": "/api/v1/pays",
            "nageur_recherche": "/api/v1/nageur/recherche?q=dup&country=FR",
            "couloir": "/api/v1/couloir?country=FR&stroke=FR&distance=100&pool=LCM",
            "comparaison": (
                "/api/v1/comparaison?country=FR&stroke=FR&distance=100&pool=LCM"
                "&swimmer_a_name=A&swimmer_b_name=B"
            ),
            "epreuves": "/api/v1/referentiels/epreuves?country=FR",
        },
    }
