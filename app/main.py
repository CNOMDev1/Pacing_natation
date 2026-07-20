"""
Point d'entrée de l'API FastAPI.
"""
from fastapi import FastAPI

from app.routers import pacing

app = FastAPI(
    title="Pacing",
    version="0.2.0",
    description=(
        "API Pacing métier (couloir, recherche nageur, référentiels). "
        "Doc interactive : /docs"
    ),
)

app.include_router(pacing.router)


@app.get("/")
def root():
    """
    Endpoint racine pour vérifier rapidement que l'API répond.

    Returns:
        dict: Message d'accueil et liens utiles.
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
