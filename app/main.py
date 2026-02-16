"""
Point d'entrée de l'API FastAPI.
"""
from fastapi import FastAPI
from app.routers import extranat, omega

app = FastAPI(
    title="Pacing",
    version="0.1.0",
    description="API pour la récupération et l'analyse de données (Omega, Extranat, etc.).",
)

app.include_router(omega.router)
app.include_router(extranat.router)

@app.get("/")
def root():
    """
    Endpoint racine.
    pour vérifier rapidement que l'API répond.
    """
    return {
        "message": "Bienvenue sur l'API Pacing.",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "version": app.version,
    }
