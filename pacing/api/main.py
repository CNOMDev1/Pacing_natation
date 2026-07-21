"""Point d'entrée de l'API FastAPI Pacing."""
from fastapi import FastAPI

from app.routers import pacing
from pacing.api.routers import extranat, omega, usaswimming

app = FastAPI(
    title="Pacing",
    version="0.2.0",
    description=(
        "API Pacing métier (couloir, recherche nageur, référentiels) "
        "et ingestion (Omega, Extranat, USA Swimming). "
        "Doc interactive : /docs"
    ),
)

app.include_router(pacing.router)
app.include_router(omega.router)
app.include_router(extranat.router)
app.include_router(usaswimming.router)


@app.get("/")
def root():
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
