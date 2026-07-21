"""Client HTTP pour consommer l'API Pacing ``/api/v1``.

La UI NiceGUI ne recalcule pas les couloirs : elle appelle FastAPI et
trace les payloads structurés (``bands``, ``points``).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


class PacingApiError(RuntimeError):
    """
    Erreur HTTP ou métier lors d'un appel à l'API Pacing.

    Attributes:
        status_code (Optional[int]): Code HTTP si disponible.
        detail (str): Message d'erreur.
    """

    def __init__(self, detail: str, status_code: Optional[int] = None) -> None:
        """
        Initialise l'erreur API.

        Args:
            detail (str): Message lisible.
            status_code (Optional[int]): Code HTTP optionnel.
        """
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class PacingApiClient:
    """
    Client synchrone minimal pour les endpoints prototype ``/api/v1``.

    Attributes:
        base_url (str): Racine de l'API (sans slash final).
        timeout (float): Timeout HTTP en secondes.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        """
        Crée le client.

        Args:
            base_url (Optional[str]): URL de base ; défaut
                ``PACING_API_BASE_URL`` ou ``http://127.0.0.1:8000``.
            timeout (float): Timeout des requêtes.
        """
        raw = (base_url or os.getenv("PACING_API_BASE_URL") or DEFAULT_API_BASE_URL)
        self.base_url = raw.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Exécute un ``GET`` JSON.

        Args:
            path (str): Chemin relatif (ex. ``/api/v1/pays``).
            params (Optional[Dict[str, Any]]): Query params (None ignorés).

        Returns:
            Dict[str, Any]: Corps JSON.

        Raises:
            PacingApiError: Si la requête échoue ou le JSON est invalide.
        """
        clean_params = {
            key: value
            for key, value in (params or {}).items()
            if value is not None and value != ""
        }
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=clean_params)
        except httpx.HTTPError as exc:
            raise PacingApiError(
                f"API injoignable ({self.base_url}). "
                "Lancez d'abord : uvicorn pacing.api.main:app --reload"
            ) from exc

        if response.status_code >= 400:
            detail = response.text
            try:
                payload = response.json()
                detail = str(payload.get("detail", payload))
            except Exception:
                pass
            raise PacingApiError(detail, status_code=response.status_code)

        try:
            data = response.json()
        except Exception as exc:
            raise PacingApiError("Réponse API non JSON") from exc
        if not isinstance(data, dict):
            raise PacingApiError("Réponse API inattendue (objet JSON requis)")
        return data

    def list_countries(self) -> List[Dict[str, Any]]:
        """
        Liste les pays du référentiel.

        Returns:
            List[Dict[str, Any]]: Entrées ``{code, label}``.
        """
        payload = self._get("/api/v1/pays")
        return list(payload.get("countries") or [])

    def list_events(self, country: str) -> Dict[str, Any]:
        """
        Charge le référentiel d'épreuves pour un pays.

        Args:
            country (str): Code pays (``FR`` / ``MA`` / ``US``).

        Returns:
            Dict[str, Any]: Payload ``strokes`` / ``events``.
        """
        return self._get("/api/v1/referentiels/epreuves", {"country": country})

    def search_swimmers(
        self,
        *,
        q: str,
        country: str,
        stroke: Optional[str] = None,
        distance: Optional[int] = None,
        pool: Optional[str] = None,
        event: Optional[str] = None,
        gender: str = "all",
        limit: int = 30,
    ) -> Dict[str, Any]:
        """
        Recherche des nageurs (autocomplete).

        Args:
            q (str): Texte de recherche.
            country (str): Pays source.
            stroke (Optional[str]): Code nage.
            distance (Optional[int]): Distance (m).
            pool (Optional[str]): Bassin.
            event (Optional[str]): Épreuve exacte (utile US).
            gender (str): Filtre genre.
            limit (int): Nombre max de résultats.

        Returns:
            Dict[str, Any]: Payload recherche.
        """
        return self._get(
            "/api/v1/nageur/recherche",
            {
                "q": q,
                "country": country,
                "stroke": stroke,
                "distance": distance,
                "pool": pool,
                "event": event,
                "gender": gender,
                "limit": limit,
            },
        )

    def get_corridor(
        self,
        *,
        country: str,
        stroke: str,
        distance: int,
        pool: str,
        gender: str = "all",
        corridor_type: str = "age_global",
        swimmer_name: Optional[str] = None,
        swimmer_yob: Optional[int] = None,
        swimmer_country: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Charge un couloir de performance.

        Args:
            country (str): Pays du peloton.
            stroke (str): Code nage.
            distance (int): Distance (m).
            pool (str): Bassin.
            gender (str): Filtre genre.
            corridor_type (str): ``age_global`` ou ``age_target``.
            swimmer_name (Optional[str]): Nageur cible.
            swimmer_yob (Optional[int]): Année de naissance.
            swimmer_country (Optional[str]): Pays source du nageur.

        Returns:
            Dict[str, Any]: Payload couloir.
        """
        return self._get(
            "/api/v1/couloir",
            {
                "country": country,
                "stroke": stroke,
                "distance": distance,
                "pool": pool,
                "gender": gender,
                "corridor_type": corridor_type,
                "swimmer_name": swimmer_name,
                "swimmer_yob": swimmer_yob,
                "swimmer_country": swimmer_country,
            },
        )

    def compare_swimmers(
        self,
        *,
        country: str,
        stroke: str,
        distance: int,
        pool: str,
        gender: str,
        swimmer_a_name: str,
        swimmer_b_name: str,
        swimmer_a_yob: Optional[int] = None,
        swimmer_b_yob: Optional[int] = None,
        swimmer_a_country: Optional[str] = None,
        swimmer_b_country: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compare deux nageurs sur le même couloir.

        Args:
            country (str): Pays du peloton de référence.
            stroke (str): Code nage.
            distance (int): Distance (m).
            pool (str): Bassin.
            gender (str): Filtre genre.
            swimmer_a_name (str): Nom nageur A.
            swimmer_b_name (str): Nom nageur B.
            swimmer_a_yob (Optional[int]): YOB A.
            swimmer_b_yob (Optional[int]): YOB B.
            swimmer_a_country (Optional[str]): Pays A.
            swimmer_b_country (Optional[str]): Pays B.

        Returns:
            Dict[str, Any]: Payload comparaison.
        """
        return self._get(
            "/api/v1/comparaison",
            {
                "country": country,
                "stroke": stroke,
                "distance": distance,
                "pool": pool,
                "gender": gender,
                "swimmer_a_name": swimmer_a_name,
                "swimmer_a_yob": swimmer_a_yob,
                "swimmer_a_country": swimmer_a_country,
                "swimmer_b_name": swimmer_b_name,
                "swimmer_b_yob": swimmer_b_yob,
                "swimmer_b_country": swimmer_b_country,
            },
        )


def get_default_client() -> PacingApiClient:
    """
    Retourne un client configuré via l'environnement.

    Returns:
        PacingApiClient: Instance partagée légère (stateless).
    """
    return PacingApiClient()
