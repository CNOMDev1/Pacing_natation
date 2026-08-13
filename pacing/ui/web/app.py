"""Application web NiceGUI — client de l'API Pacing.

Pages : accueil, données (référentiels), couloir, comparaison.
Prérequis : API FastAPI démarrée (``uvicorn pacing.api.main:app --reload``).

Lancement :
    python -m pacing.ui.web.app
    # ou : pacing-web
    # ou : python pacing/ui/web/app.py
"""
from __future__ import annotations

from pathlib import Path
import sys

# Lancement direct du fichier (sans ``pip install -e .`` ni ``-m``).
if __package__ is None:
    _project_root = Path(__file__).resolve().parents[3]
    _root_str = str(_project_root)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)

import asyncio
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from nicegui import ui

from pacing.config.paths import PROJECT_DIR
from pacing.ui.web.api_client import PacingApiClient, PacingApiError, get_default_client
from pacing.ui.web.charts import build_compare_figure, build_corridor_figure

STROKE_LABELS = {
    "FR": "Nage libre",
    "BK": "Dos",
    "BR": "Brasse",
    "FL": "Papillon",
    "IM": "4 nages",
}
POOL_LABELS = {"LCM": "50 m", "SCM": "25 m", "SCY": "Yards"}
GENDER_OPTIONS = {"all": "Tous", "F": "Féminin", "M": "Masculin"}

# Processus uvicorn démarré depuis l'UI (un seul à la fois).
_API_PROCESS: Optional[subprocess.Popen] = None


def _start_api_backend(base_url: str) -> subprocess.Popen:
    """
    Lance ``uvicorn pacing.api.main:app --reload`` en arrière-plan.

    Args:
        base_url (str): URL de base API (host/port extraits).

    Returns:
        subprocess.Popen: Processus détaché.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "pacing.api.main:app",
            "--reload",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


async def _ensure_api_reachable(
    client: PacingApiClient,
    status: Any,
) -> Optional[List[Dict[str, Any]]]:
    """
    Ping l'API ; si injoignable, démarre uvicorn puis attend qu'elle réponde.

    Args:
        client (PacingApiClient): Client HTTP.
        status (Any): Label NiceGUI de statut.

    Returns:
        Optional[List[Dict[str, Any]]]: Liste pays si OK, sinon ``None``.
    """
    global _API_PROCESS

    try:
        return client.list_countries()
    except PacingApiError:
        pass

    if _API_PROCESS is not None and _API_PROCESS.poll() is None:
        status.set_text("Statut API : uvicorn déjà lancé, attente…")
    else:
        status.set_text("Statut API : lancement de uvicorn en arrière-plan…")
        status.classes(replace="text-caption")
        try:
            _API_PROCESS = _start_api_backend(client.base_url)
        except OSError as exc:
            status.set_text(f"Statut API : impossible de lancer uvicorn — {exc}")
            status.classes(replace="text-caption text-negative")
            return None

    for _ in range(40):
        await asyncio.sleep(0.5)
        if _API_PROCESS is not None and _API_PROCESS.poll() is not None:
            status.set_text(
                "Statut API : uvicorn s'est arrêté "
                "(port occupé ou erreur de démarrage)"
            )
            status.classes(replace="text-caption text-negative")
            return None
        try:
            return client.list_countries()
        except PacingApiError:
            continue

    status.set_text("Statut API : timeout — uvicorn ne répond pas")
    status.classes(replace="text-caption text-negative")
    return None


def _nav(active: str) -> None:
    """
    Affiche la barre de navigation commune.

    Args:
        active (str): Identifiant de page active (``home``, ``data``, …).
    """
    links = [
        ("home", "/", "Accueil"),
        ("data", "/donnees", "Données"),
        ("corridor", "/couloir", "Couloir"),
        ("compare", "/comparaison", "Comparaison"),
    ]
    with ui.header().classes("items-center px-4 bg-slate-800 text-white"):
        ui.label("Pacing").classes("text-h6 font-bold mr-6")
        for key, path, label in links:
            props = "flat color=white"
            if key == active:
                props += " unelevated"
                ui.button(label, on_click=lambda p=path: ui.navigate.to(p)).props(
                    "flat color=white text-weight-bold"
                ).classes("bg-slate-600")
            else:
                ui.button(label, on_click=lambda p=path: ui.navigate.to(p)).props(props)
        ui.space()
        ui.label("API → NiceGUI").classes("text-caption opacity-70")


def _notify_error(exc: Exception) -> None:
    """
    Affiche une notification d'erreur.

    Args:
        exc (Exception): Exception à signaler.
    """
    ui.notify(str(exc), type="negative", position="top", timeout=6000)


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    """
    Parse un entier optionnel depuis un champ texte.

    Args:
        raw (Optional[str]): Valeur brute.

    Returns:
        Optional[int]: Entier ou None.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return int(text)


def _stroke_choices(events_payload: Dict[str, Any]) -> List[str]:
    """
    Construit la liste des codes nage depuis le référentiel.

    Args:
        events_payload (Dict[str, Any]): Payload ``/referentiels/epreuves``.

    Returns:
        List[str]: Codes nage.
    """
    strokes = events_payload.get("strokes") or []
    codes = [str(s.get("code")) for s in strokes if s.get("code")]
    if codes:
        return codes
    return list(STROKE_LABELS.keys())


def _distance_pool_choices(
    events_payload: Dict[str, Any], stroke: str
) -> Tuple[List[int], List[str]]:
    """
    Distances et bassins disponibles pour une nage.

    Args:
        events_payload (Dict[str, Any]): Référentiel épreuves.
        stroke (str): Code nage.

    Returns:
        Tuple[List[int], List[str]]: Distances (m) et codes bassin.
    """
    for item in events_payload.get("strokes") or []:
        if str(item.get("code")) != stroke:
            continue
        distances: List[int] = []
        pools: List[str] = []
        for dist in item.get("distances") or []:
            d = dist.get("distance")
            if d is not None:
                distances.append(int(d))
            for pool in dist.get("pools") or []:
                code = pool.get("code")
                if code and code not in pools:
                    pools.append(str(code))
        return distances or [50, 100, 200], pools or ["LCM", "SCM"]
    return [50, 100, 200], ["LCM", "SCM"]


def _show_figure(fig: Any, container: ui.column) -> None:
    """
    Affiche une figure via PNG base64 (fidèle aux rubans).

    Args:
        fig (Any): Figure Matplotlib.
        container (ui.column): Conteneur UI.
    """
    import base64
    import io

    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    container.clear()
    with container:
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        ui.image(f"data:image/png;base64,{b64}").classes("w-full max-w-5xl rounded")


@ui.page("/")
def page_home() -> None:
    """
    Page d'accueil du prototype web.

    Returns:
        None: Rendu NiceGUI.
    """
    _nav("home")
    client = get_default_client()
    with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-4"):
        ui.label("Prototype web Pacing").classes("text-h4")
        ui.markdown(
            "Interface **NiceGUI** qui consomme l'API FastAPI (`/api/v1`). "
            "Le moteur métier reste côté serveur Python."
        )
        with ui.card().classes("w-full p-4"):
            ui.label("Prérequis").classes("text-h6")
            ui.markdown(
                "1. Le bouton ci-dessous lance l'API si besoin "
                "(`uvicorn pacing.api.main:app --reload`)  \n"
                f"2. Base URL : `{client.base_url}`  \n"
                "3. Doc Swagger : `/docs`"
            )
            status = ui.label("Statut API : …").classes("text-caption")

            def _set_ok(countries: List[Dict[str, Any]]) -> None:
                """Affiche le statut OK avec les codes pays."""
                codes = ", ".join(c.get("code", "?") for c in countries)
                status.set_text(f"Statut API : OK ({codes})")
                status.classes(replace="text-caption text-positive")

            async def _ping_only() -> None:
                """Ping sans démarrer uvicorn (chargement de page)."""
                try:
                    _set_ok(client.list_countries())
                except PacingApiError as exc:
                    status.set_text(f"Statut API : erreur — {exc.detail}")
                    status.classes(replace="text-caption text-negative")

            async def _ping_and_start() -> None:
                """
                Vérifie l'API et lance uvicorn en arrière-plan si besoin.

                Returns:
                    None: Met à jour le libellé de statut.
                """
                status.set_text("Statut API : vérification…")
                status.classes(replace="text-caption")
                countries = await _ensure_api_reachable(client, status)
                if countries is not None:
                    _set_ok(countries)

            ui.button(
                "Tester la connexion API", on_click=_ping_and_start
            ).props("unelevated")
            ui.timer(0.1, _ping_only, once=True)

        with ui.row().classes("gap-3"):
            ui.button("Données", on_click=lambda: ui.navigate.to("/donnees")).props(
                "outline"
            )
            ui.button("Couloir", on_click=lambda: ui.navigate.to("/couloir")).props(
                "unelevated"
            )
            ui.button(
                "Comparaison", on_click=lambda: ui.navigate.to("/comparaison")
            ).props("outline")


@ui.page("/donnees")
def page_data() -> None:
    """
    Page référentiels (pays + épreuves).

    Returns:
        None: Rendu NiceGUI.
    """
    _nav("data")
    client = get_default_client()
    with ui.column().classes("w-full max-w-4xl mx-auto p-6 gap-4"):
        ui.label("Données / référentiels").classes("text-h4")
        ui.markdown("Endpoints : `GET /api/v1/pays`, `GET /api/v1/referentiels/epreuves`.")

        country = ui.select(
            options={"FR": "France", "US": "États-Unis", "MA": "Maroc"},
            value="FR",
            label="Pays",
        ).classes("w-48")
        result_box = ui.column().classes("w-full gap-2")

        def _load() -> None:
            """
            Charge et affiche le référentiel d'épreuves.

            Returns:
                None: Met à jour ``result_box``.
            """
            result_box.clear()
            try:
                payload = client.list_events(str(country.value))
            except (PacingApiError, Exception) as exc:
                _notify_error(exc)
                return
            with result_box:
                ui.label(f"Pays : {payload.get('country')}").classes("text-subtitle1")
                events = payload.get("events") or []
                if events:
                    ui.label(f"{len(events)} épreuves (liste US)").classes("text-caption")
                    ui.select(
                        options=events[:200],
                        label="Épreuves (aperçu)",
                        with_input=True,
                    ).classes("w-full")
                strokes = payload.get("strokes") or []
                if strokes:
                    rows = []
                    for i, stroke in enumerate(strokes):
                        code = stroke.get("code")
                        label = stroke.get("label") or STROKE_LABELS.get(code, code)
                        for j, dist in enumerate(stroke.get("distances") or []):
                            pools = ", ".join(
                                p.get("code", "") for p in (dist.get("pools") or [])
                            )
                            rows.append(
                                {
                                    "id": f"{code}-{dist.get('distance')}-{j}-{i}",
                                    "nage": f"{code} — {label}",
                                    "distance": dist.get("distance"),
                                    "bassins": pools,
                                }
                            )
                    ui.table(
                        columns=[
                            {"name": "nage", "label": "Nage", "field": "nage"},
                            {
                                "name": "distance",
                                "label": "Distance (m)",
                                "field": "distance",
                            },
                            {"name": "bassins", "label": "Bassins", "field": "bassins"},
                        ],
                        rows=rows,
                        row_key="id",
                    ).classes("w-full")

        ui.button("Charger", on_click=_load).props("unelevated")
        _load()


@ui.page("/couloir")
def page_corridor() -> None:
    """
    Page couloir de performance + recherche nageur.

    Returns:
        None: Rendu NiceGUI.
    """
    _nav("corridor")
    client = get_default_client()
    events_cache: Dict[str, Dict[str, Any]] = {}

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
        ui.label("Couloir de performance").classes("text-h4")
        ui.markdown("Endpoint : `GET /api/v1/couloir` (+ recherche nageur).")

        with ui.row().classes("w-full flex-wrap gap-3 items-end"):
            country = ui.select(
                {"FR": "France (peloton)", "US": "USA (peloton)", "MA": "Maroc"},
                value="FR",
                label="Pays peloton",
            ).classes("w-44")
            gender = ui.select(GENDER_OPTIONS, value="all", label="Genre").classes(
                "w-36"
            )
            stroke = ui.select(
                {k: f"{k} — {v}" for k, v in STROKE_LABELS.items()},
                value="FR",
                label="Nage",
            ).classes("w-48")
            distance = ui.select(
                {str(d): f"{d} m" for d in [50, 100, 200, 400, 800, 1500]},
                value="100",
                label="Distance",
            ).classes("w-36")
            pool = ui.select(
                {k: f"{k} ({v})" for k, v in POOL_LABELS.items()},
                value="LCM",
                label="Bassin",
            ).classes("w-40")

        with ui.row().classes("w-full flex-wrap gap-3 items-end"):
            swimmer_country = ui.select(
                {"FR": "FR", "US": "US", "MA": "MA"},
                value="FR",
                label="Pays nageur",
            ).classes("w-36")
            search_q = ui.input("Recherche nageur", placeholder="ex. Dupont").classes(
                "w-64"
            )
            search_results = ui.select(
                options=[], label="Sélection nageur", with_input=True
            ).classes("w-80")
            # map label -> {name, yob}
            selected_meta: Dict[str, Dict[str, Any]] = {}

        # Boutons juste sous le formulaire (avant le graphique)
        with ui.row().classes("gap-3"):
            btn_search = ui.button("Rechercher nageur").props("outline")
            btn_corridor = ui.button("Afficher le couloir").props(
                "unelevated color=primary"
            )

        chart_box = ui.column().classes("w-full")
        meta_label = ui.label("").classes("text-caption")

        def _refresh_events() -> None:
            """
            Recharge le référentiel pour le pays peloton.

            Returns:
                None: Met à jour les listes nage / distance / bassin.
            """
            code = str(country.value)
            try:
                if code not in events_cache:
                    events_cache[code] = client.list_events(code)
                payload = events_cache[code]
                strokes = _stroke_choices(payload)
                stroke.options = {
                    s: f"{s} — {STROKE_LABELS.get(s, s)}" for s in strokes
                }
                if stroke.value not in strokes and strokes:
                    stroke.value = strokes[0]
                dists, pools = _distance_pool_choices(payload, str(stroke.value))
                distance.options = {str(d): f"{d} m" for d in dists}
                if str(distance.value) not in distance.options and dists:
                    distance.value = str(dists[0])
                pool.options = {
                    p: f"{p} ({POOL_LABELS.get(p, p)})" for p in pools
                }
                if pool.value not in pool.options and pools:
                    pool.value = pools[0]
            except PacingApiError as exc:
                _notify_error(exc)

        def _do_search() -> None:
            """
            Lance la recherche nageur.

            Returns:
                None: Remplit ``search_results``.
            """
            q = (search_q.value or "").strip()
            if len(q) < 2:
                ui.notify("Saisir au moins 2 caractères", type="warning")
                return
            try:
                payload = client.search_swimmers(
                    q=q,
                    country=str(swimmer_country.value),
                    stroke=str(stroke.value),
                    distance=int(distance.value),
                    pool=str(pool.value),
                    gender=str(gender.value),
                )
            except PacingApiError as exc:
                _notify_error(exc)
                return
            selected_meta.clear()
            options: Dict[str, str] = {}
            for row in payload.get("results") or []:
                label = row.get("label") or row.get("name") or "?"
                options[label] = label
                selected_meta[label] = row
            search_results.options = options
            search_results.value = next(iter(options), None)
            if payload.get("status") == "empty":
                ui.notify(payload.get("message") or "Aucun nageur", type="info")

        def _load_corridor() -> None:
            """
            Appelle ``/couloir`` et affiche le graphique.

            Returns:
                None: Met à jour le graphique.
            """
            sw_name = None
            sw_yob = None
            label = search_results.value
            if label and label in selected_meta:
                row = selected_meta[label]
                sw_name = row.get("name")
                sw_yob = row.get("year_of_birth")
            try:
                payload = client.get_corridor(
                    country=str(country.value),
                    stroke=str(stroke.value),
                    distance=int(distance.value),
                    pool=str(pool.value),
                    gender=str(gender.value),
                    swimmer_name=sw_name,
                    swimmer_yob=sw_yob,
                    swimmer_country=str(swimmer_country.value) if sw_name else None,
                )
            except PacingApiError as exc:
                _notify_error(exc)
                return
            status = payload.get("status")
            meta = payload.get("meta") or {}
            meta_label.set_text(
                f"status={status} · event={meta.get('event')} · "
                f"rows={meta.get('row_count')} · bands={len(payload.get('bands') or [])}"
            )
            if status in ("empty", "not_found"):
                ui.notify(f"Réponse API : {status}", type="warning")
            fig = build_corridor_figure(payload)
            _show_figure(fig, chart_box)

        btn_search.on_click(_do_search)
        btn_corridor.on_click(_load_corridor)
        country.on_value_change(lambda _: _refresh_events())
        stroke.on_value_change(lambda _: _refresh_events())

        _refresh_events()


@ui.page("/comparaison")
def page_compare() -> None:
    """
    Page comparaison de deux nageurs sur un couloir.

    Returns:
        None: Rendu NiceGUI.
    """
    _nav("compare")
    client = get_default_client()

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
        ui.label("Comparaison de nageurs").classes("text-h4")
        ui.markdown("Endpoint : `GET /api/v1/comparaison`.")

        with ui.row().classes("w-full flex-wrap gap-3 items-end"):
            country = ui.select(
                {"FR": "France (réf.)", "US": "USA (réf.)"},
                value="FR",
                label="Peloton",
            ).classes("w-40")
            stroke = ui.select(
                {k: f"{k} — {v}" for k, v in STROKE_LABELS.items()},
                value="FR",
                label="Nage",
            ).classes("w-44")
            distance = ui.select(
                {str(d): f"{d} m" for d in [50, 100, 200, 400]},
                value="100",
                label="Distance",
            ).classes("w-32")
            pool = ui.select(
                {"LCM": "LCM", "SCM": "SCM", "SCY": "SCY"},
                value="LCM",
                label="Bassin",
            ).classes("w-32")
            gender = ui.select(GENDER_OPTIONS, value="F", label="Genre").classes(
                "w-32"
            )

        with ui.card().classes("w-full p-4"):
            ui.label("Nageur A").classes("text-subtitle1")
            with ui.row().classes("w-full flex-wrap gap-3"):
                a_country = ui.select(
                    {"FR": "FR", "US": "US", "MA": "MA"}, value="FR", label="Pays A"
                ).classes("w-28")
                a_name = ui.input("Nom A").classes("w-64")
                a_yob = ui.input("YOB A", placeholder="2008").classes("w-28")

        with ui.card().classes("w-full p-4"):
            ui.label("Nageur B (overlay)").classes("text-subtitle1")
            with ui.row().classes("w-full flex-wrap gap-3"):
                b_country = ui.select(
                    {"FR": "FR", "US": "US", "MA": "MA"}, value="MA", label="Pays B"
                ).classes("w-28")
                b_name = ui.input("Nom B").classes("w-64")
                b_yob = ui.input("YOB B", placeholder="2009").classes("w-28")

        btn_compare = ui.button("Comparer").props("unelevated color=primary")
        chart_box = ui.column().classes("w-full")
        meta_label = ui.label("").classes("text-caption")

        def _run_compare() -> None:
            """
            Lance la comparaison via l'API.

            Returns:
                None: Affiche le graphique.
            """
            if not (a_name.value or "").strip() or not (b_name.value or "").strip():
                ui.notify("Renseigner les deux noms", type="warning")
                return
            try:
                payload = client.compare_swimmers(
                    country=str(country.value),
                    stroke=str(stroke.value),
                    distance=int(distance.value),
                    pool=str(pool.value),
                    gender=str(gender.value),
                    swimmer_a_name=str(a_name.value).strip(),
                    swimmer_b_name=str(b_name.value).strip(),
                    swimmer_a_yob=_parse_optional_int(a_yob.value),
                    swimmer_b_yob=_parse_optional_int(b_yob.value),
                    swimmer_a_country=str(a_country.value),
                    swimmer_b_country=str(b_country.value),
                )
            except (PacingApiError, ValueError) as exc:
                _notify_error(exc)
                return
            status = payload.get("status")
            meta = payload.get("meta") or {}
            missing = payload.get("missing") or []
            meta_label.set_text(
                f"status={status} · event={meta.get('event')} · missing={missing}"
            )
            if status != "ok":
                ui.notify(f"Réponse : {status} {missing}", type="warning")
            fig = build_compare_figure(payload)
            _show_figure(fig, chart_box)

        btn_compare.on_click(_run_compare)


def run() -> None:
    """
    Point d'entrée CLI de l'interface NiceGUI.

    Returns:
        None: Démarre le serveur web NiceGUI.
    """
    host = os.getenv("PACING_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("PACING_WEB_PORT", "8080"))
    show = os.getenv("PACING_WEB_SHOW", "1") not in {"0", "false", "False"}
    ui.run(
        title="Pacing — NiceGUI",
        host=host,
        port=port,
        reload=False,
        show=show,
    )


# NiceGUI enregistre les pages au chargement du module.
# En entrée CLI (`python -m …` / `pacing-web`), on démarre le serveur.
if __name__ in {"__main__", "__mp_main__"}:
    run()
