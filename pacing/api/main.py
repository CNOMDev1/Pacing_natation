"""Point d'entrée de l'API FastAPI Pacing."""
from fastapi import FastAPI

from pacing.api.routers import extranat, omega, usaswimming

app = FastAPI(
    title="Pacing",
    version="0.2.0",
    description="API pour la récupération et l'analyse de données (Omega, Extranat, etc.).",
)

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
    }
