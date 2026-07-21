"""Prototype DearPyGUI — client desktop de l'API Pacing.

Réutilise ``pacing.ui.web.api_client`` et ``pacing.ui.web.charts`` (même contrat
JSON que NiceGUI). Objectif mission §5.4 : évaluer ergonomie / installation
face à Flet et NiceGUI, sans migrer toute l'UI Flet.

Prérequis : API FastAPI démarrée
    uvicorn pacing.api.main:app --reload

Lancement :
    python -m pacing.ui.dearpygui.app
    # ou : pacing-dpg
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import dearpygui.dearpygui as dpg
import matplotlib.pyplot as plt

from pacing.ui.web.api_client import PacingApiClient, PacingApiError, get_default_client
from pacing.ui.web.charts import build_compare_figure, build_corridor_figure

STROKE_CODES = ["FR", "BK", "BR", "FL", "IM"]
POOL_CODES = ["LCM", "SCM", "SCY"]
GENDER_CODES = ["all", "F", "M"]
COUNTRY_CODES = ["FR", "US", "MA"]

_TEXTURE_TAG = "pacing_dpg_chart_texture"
_IMAGE_TAG = "pacing_dpg_chart_image"
_STATUS_TAG = "pacing_dpg_status"
_SEARCH_RESULTS: Dict[str, Dict[str, Any]] = {}


def _set_status(message: str) -> None:
    """
    Met à jour le libellé de statut de la fenêtre.

    Args:
        message (str): Texte à afficher.
    """
    if dpg.does_item_exist(_STATUS_TAG):
        dpg.set_value(_STATUS_TAG, message)


def _save_figure_png(fig: Any) -> Path:
    """
    Enregistre une figure Matplotlib en PNG temporaire.

    Args:
        fig (Any): Figure Matplotlib.

    Returns:
        Path: Chemin du fichier PNG.
    """
    fd, name = tempfile.mkstemp(prefix="pacing_dpg_", suffix=".png")
    os.close(fd)
    path = Path(name)
    fig.savefig(path, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path


def _show_png(path: Path) -> None:
    """
    Affiche un PNG dans la zone image DearPyGUI (texture dynamique).

    Args:
        path (Path): Fichier image.
    """
    width, height, _channels, data = dpg.load_image(str(path))
    if dpg.does_item_exist(_IMAGE_TAG):
        dpg.delete_item(_IMAGE_TAG)
    if dpg.does_item_exist(_TEXTURE_TAG):
        dpg.delete_item(_TEXTURE_TAG)

    with dpg.texture_registry():
        dpg.add_static_texture(width, height, data, tag=_TEXTURE_TAG)

    parent = "pacing_dpg_chart_slot"
    if dpg.does_item_exist(parent):
        dpg.add_image(_TEXTURE_TAG, tag=_IMAGE_TAG, parent=parent, width=900)


def _client() -> PacingApiClient:
    """
    Retourne le client API configuré.

    Returns:
        PacingApiClient: Client HTTP.
    """
    return get_default_client()


def _on_ping() -> None:
    """
    Teste la connexion à l'API.

    Returns:
        None: Met à jour le statut.
    """
    try:
        countries = _client().list_countries()
        codes = ", ".join(c.get("code", "?") for c in countries)
        _set_status(f"API OK — pays : {codes} ({_client().base_url})")
    except PacingApiError as exc:
        _set_status(f"API injoignable : {exc.detail}")


def _on_search() -> None:
    """
    Recherche des nageurs et remplit la combo de sélection.

    Returns:
        None: Met à jour la liste et le statut.
    """
    q = str(dpg.get_value("dpg_search_q") or "").strip()
    if len(q) < 2:
        _set_status("Saisir au moins 2 caractères pour la recherche.")
        return
    try:
        payload = _client().search_swimmers(
            q=q,
            country=str(dpg.get_value("dpg_swimmer_country")),
            stroke=str(dpg.get_value("dpg_stroke")),
            distance=int(dpg.get_value("dpg_distance")),
            pool=str(dpg.get_value("dpg_pool")),
            gender=str(dpg.get_value("dpg_gender")),
        )
    except (PacingApiError, ValueError) as exc:
        _set_status(str(exc))
        return

    _SEARCH_RESULTS.clear()
    labels: List[str] = []
    for row in payload.get("results") or []:
        label = str(row.get("label") or row.get("name") or "?")
        labels.append(label)
        _SEARCH_RESULTS[label] = row

    dpg.configure_item("dpg_search_pick", items=labels)
    if labels:
        dpg.set_value("dpg_search_pick", labels[0])
        _set_status(f"Recherche : {len(labels)} résultat(s)")
    else:
        dpg.set_value("dpg_search_pick", "")
        _set_status(payload.get("message") or "Aucun nageur trouvé")


def _selected_swimmer() -> tuple[Optional[str], Optional[int]]:
    """
    Lit le nageur sélectionné dans la combo.

    Returns:
        tuple[Optional[str], Optional[int]]: Nom et année de naissance.
    """
    label = str(dpg.get_value("dpg_search_pick") or "")
    row = _SEARCH_RESULTS.get(label)
    if not row:
        return None, None
    yob = row.get("year_of_birth")
    return row.get("name"), int(yob) if yob is not None else None


def _on_corridor() -> None:
    """
    Charge un couloir via l'API et affiche le graphique.

    Returns:
        None: Met à jour l'image et le statut.
    """
    name, yob = _selected_swimmer()
    try:
        payload = _client().get_corridor(
            country=str(dpg.get_value("dpg_country")),
            stroke=str(dpg.get_value("dpg_stroke")),
            distance=int(dpg.get_value("dpg_distance")),
            pool=str(dpg.get_value("dpg_pool")),
            gender=str(dpg.get_value("dpg_gender")),
            swimmer_name=name,
            swimmer_yob=yob,
            swimmer_country=(
                str(dpg.get_value("dpg_swimmer_country")) if name else None
            ),
        )
    except (PacingApiError, ValueError) as exc:
        _set_status(str(exc))
        return

    status = payload.get("status")
    meta = payload.get("meta") or {}
    _set_status(
        f"status={status} · event={meta.get('event')} · "
        f"rows={meta.get('row_count')} · bands={len(payload.get('bands') or [])}"
    )
    fig = build_corridor_figure(payload)
    path = _save_figure_png(fig)
    try:
        _show_png(path)
    finally:
        path.unlink(missing_ok=True)


def _on_compare() -> None:
    """
    Compare deux nageurs (noms saisis) sur le même couloir.

    Returns:
        None: Met à jour l'image et le statut.
    """
    a_name = str(dpg.get_value("dpg_a_name") or "").strip()
    b_name = str(dpg.get_value("dpg_b_name") or "").strip()
    if not a_name or not b_name:
        _set_status("Renseigner les noms A et B pour la comparaison.")
        return

    def _yob(tag: str) -> Optional[int]:
        raw = str(dpg.get_value(tag) or "").strip()
        return int(raw) if raw else None

    try:
        payload = _client().compare_swimmers(
            country=str(dpg.get_value("dpg_country")),
            stroke=str(dpg.get_value("dpg_stroke")),
            distance=int(dpg.get_value("dpg_distance")),
            pool=str(dpg.get_value("dpg_pool")),
            gender=str(dpg.get_value("dpg_gender")),
            swimmer_a_name=a_name,
            swimmer_b_name=b_name,
            swimmer_a_yob=_yob("dpg_a_yob"),
            swimmer_b_yob=_yob("dpg_b_yob"),
            swimmer_a_country=str(dpg.get_value("dpg_a_country")),
            swimmer_b_country=str(dpg.get_value("dpg_b_country")),
        )
    except (PacingApiError, ValueError) as exc:
        _set_status(str(exc))
        return

    status = payload.get("status")
    meta = payload.get("meta") or {}
    missing = payload.get("missing") or []
    _set_status(
        f"status={status} · event={meta.get('event')} · missing={missing}"
    )
    fig = build_compare_figure(payload)
    path = _save_figure_png(fig)
    try:
        _show_png(path)
    finally:
        path.unlink(missing_ok=True)


def _build_ui() -> None:
    """
    Construit la fenêtre principale DearPyGUI.

    Returns:
        None: Enregistre les widgets dans le contexte DPG.
    """
    with dpg.window(
        label="Pacing — DearPyGUI (prototype)",
        tag="pacing_dpg_main",
        width=1100,
        height=820,
        no_close=True,
    ):
        dpg.add_text("Prototype §5.4 — même API que NiceGUI (httpx → FastAPI)")
        dpg.add_text(
            f"API : {get_default_client().base_url}",
            tag=_STATUS_TAG,
        )
        dpg.add_spacer(height=6)
        dpg.add_button(label="Tester l'API", callback=lambda: _on_ping())

        dpg.add_separator()
        dpg.add_text("Filtres épreuve / peloton")
        with dpg.group(horizontal=True):
            dpg.add_text("Peloton")
            dpg.add_combo(
                COUNTRY_CODES, default_value="FR", tag="dpg_country", width=80
            )
            dpg.add_text("Nage")
            dpg.add_combo(
                STROKE_CODES, default_value="FR", tag="dpg_stroke", width=80
            )
            dpg.add_text("Distance")
            dpg.add_input_int(
                default_value=100, tag="dpg_distance", width=90, min_value=25
            )
            dpg.add_text("Bassin")
            dpg.add_combo(POOL_CODES, default_value="LCM", tag="dpg_pool", width=80)
            dpg.add_text("Genre")
            dpg.add_combo(
                GENDER_CODES, default_value="all", tag="dpg_gender", width=80
            )

        dpg.add_separator()
        dpg.add_text("Recherche nageur → couloir")
        with dpg.group(horizontal=True):
            dpg.add_text("Pays nageur")
            dpg.add_combo(
                COUNTRY_CODES,
                default_value="FR",
                tag="dpg_swimmer_country",
                width=80,
            )
            dpg.add_input_text(
                hint="ex. Dupont", tag="dpg_search_q", width=180
            )
            dpg.add_button(label="Rechercher", callback=lambda: _on_search())
            dpg.add_combo([], tag="dpg_search_pick", width=280)
            dpg.add_button(label="Afficher couloir", callback=lambda: _on_corridor())

        dpg.add_separator()
        dpg.add_text("Comparaison A / B")
        with dpg.group(horizontal=True):
            dpg.add_text("A")
            dpg.add_combo(
                COUNTRY_CODES, default_value="FR", tag="dpg_a_country", width=70
            )
            dpg.add_input_text(hint="Nom A", tag="dpg_a_name", width=160)
            dpg.add_input_text(hint="YOB A", tag="dpg_a_yob", width=70)
            dpg.add_text("B")
            dpg.add_combo(
                COUNTRY_CODES, default_value="MA", tag="dpg_b_country", width=70
            )
            dpg.add_input_text(hint="Nom B", tag="dpg_b_name", width=160)
            dpg.add_input_text(hint="YOB B", tag="dpg_b_yob", width=70)
            dpg.add_button(label="Comparer", callback=lambda: _on_compare())

        dpg.add_separator()
        dpg.add_text("Graphique (PNG depuis bands/points API)")
        with dpg.child_window(tag="pacing_dpg_chart_slot", width=980, height=480):
            dpg.add_text("(aucun graphique pour l'instant)")


def run() -> None:
    """
    Point d'entrée CLI du prototype DearPyGUI.

    Returns:
        None: Démarre la boucle DearPyGUI.
    """
    dpg.create_context()
    _build_ui()
    dpg.create_viewport(
        title="Pacing — DearPyGUI",
        width=1120,
        height=860,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("pacing_dpg_main", True)
    _on_ping()
    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    run()
