"""Format d'erreur unique de l'API Pacing.

Sans ces gestionnaires, FastAPI renvoie deux formes différentes selon
l'origine de l'échec : ``{"detail": "..."}`` pour une ``HTTPException`` et
``{"detail": [ {...}, ... ]}`` pour une erreur de validation Pydantic. Un
client doit alors distinguer une chaîne d'une liste pour afficher un message.

Toutes les erreurs sont donc normalisées en ::

    {"error": {"code": "validation_error", "message": "...", "details": [...]}}

``code`` est un identifiant stable destiné au code client, ``message`` est
lisible par un humain, ``details`` n'est présent que pour les erreurs de
validation et liste les champs fautifs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

#: Correspondance statut HTTP → code d'erreur stable exposé aux clients.
ERROR_CODE_BY_STATUS: Dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
}

DEFAULT_ERROR_CODE = "error"


def error_code_for_status(status_code: int) -> str:
    """Retourne le code d'erreur stable associé à un statut HTTP.

    Args:
        status_code (int): Statut HTTP de la réponse.

    Returns:
        str: Code d'erreur (``bad_request``, ``not_found``, …).
    """
    return ERROR_CODE_BY_STATUS.get(status_code, DEFAULT_ERROR_CODE)


def error_payload(
    code: str,
    message: str,
    details: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Construit le corps JSON d'une erreur au format unique.

    Args:
        code (str): Code d'erreur stable.
        message (str): Message lisible par un humain.
        details (Optional[List[Dict[str, Any]]]): Champs fautifs éventuels.

    Returns:
        Dict[str, Any]: Corps ``{"error": {...}}`` prêt à sérialiser.
    """
    body: Dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def _validation_details(exc: RequestValidationError) -> List[Dict[str, Any]]:
    """Réduit les erreurs Pydantic à une liste champ / message exploitable.

    Args:
        exc (RequestValidationError): Exception levée par FastAPI.

    Returns:
        List[Dict[str, Any]]: Entrées ``{field, message, type}``.
    """
    details: List[Dict[str, Any]] = []
    for raw in exc.errors():
        location = [str(part) for part in raw.get("loc", ()) if part != "body"]
        details.append(
            {
                "field": ".".join(location) or "(requête)",
                "message": str(raw.get("msg", "")),
                "type": str(raw.get("type", "")),
            }
        )
    return details


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Convertit une ``HTTPException`` au format d'erreur unique.

    Le type intercepté est celui de Starlette, classe mère de
    ``fastapi.HTTPException`` : c'est lui que lève le routeur pour une URL
    inconnue. S'abonner seulement à la version FastAPI laisserait les 404 de
    routage au format ``{"detail": ...}``.

    Args:
        request (Request): Requête entrante (non utilisée, signature FastAPI).
        exc (StarletteHTTPException): Exception levée par un endpoint ou le routeur.

    Returns:
        JSONResponse: Réponse ``{"error": {...}}`` au statut d'origine.
    """
    detail = exc.detail
    message = detail if isinstance(detail, str) else str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(error_code_for_status(exc.status_code), message),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Convertit une erreur de validation Pydantic au format unique.

    Args:
        request (Request): Requête entrante (non utilisée, signature FastAPI).
        exc (RequestValidationError): Erreur de validation des paramètres.

    Returns:
        JSONResponse: Réponse 422 ``{"error": {..., "details": [...]}}``.
    """
    details = _validation_details(exc)
    first = details[0]["message"] if details else "paramètres invalides"
    return JSONResponse(
        status_code=422,
        content=error_payload("validation_error", first, details),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Branche les gestionnaires d'erreur sur l'application FastAPI.

    Args:
        app (FastAPI): Application à configurer.

    Returns:
        None
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
