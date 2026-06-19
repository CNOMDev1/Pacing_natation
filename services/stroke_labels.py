"""Libellés français des codes de nage (FR, BK, BR, FL, IM, MD).

Les données internes conservent les codes anglais ; ce module sert à l'affichage
dans l'interface et sur les graphiques.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

STROKE_CODE_TO_LABEL: dict[str, str] = {
    "FR": "Nage libre",
    "BK": "Dos",
    "BR": "Brasse",
    "FL": "Papillon",
    "IM": "4 nages",
    "MD": "Quatre nages individuel",
}

STROKE_LABEL_TO_CODE: dict[str, str] = {
    label: code for code, label in STROKE_CODE_TO_LABEL.items()
}


def stroke_code_to_label(code: Any) -> str:
    """Convertit un code de nage en libellé français.

    Args:
        code (Any): Code de nage (ex. ``FR``, ``BK``).

    Returns:
        str: Libellé français ou la valeur d'origine si le code est inconnu.
    """
    if code is None:
        return ""
    key = str(code).strip().upper()
    if not key:
        return ""
    return STROKE_CODE_TO_LABEL.get(key, str(code).strip())


def stroke_label_to_code(label: Any) -> str:
    """Convertit un libellé français en code de nage interne.

    Args:
        label (Any): Libellé affiché (ex. ``Nage libre``) ou code brut.

    Returns:
        str: Code de nage (ex. ``FR``) ou la valeur normalisée si inconnue.
    """
    if label is None:
        return ""
    text = str(label).strip()
    if not text:
        return ""
    if text in STROKE_LABEL_TO_CODE:
        return STROKE_LABEL_TO_CODE[text]
    upper = text.upper()
    if upper in STROKE_CODE_TO_LABEL:
        return upper
    return upper


def format_event_label(
    distance: Any,
    stroke: Any,
    pool: Any,
) -> str:
    """Formate un libellé d'épreuve avec la nage en français.

    Args:
        distance (Any): Distance en mètres.
        stroke (Any): Code de nage interne.
        pool (Any): Type de bassin (ex. ``LCM``, ``SCM``).

    Returns:
        str: Libellé du type ``100 Nage libre LCM``.
    """
    stroke_label = stroke_code_to_label(stroke)
    return f"{distance} {stroke_label} {pool}".strip()


def relabel_stroke_column(
    df: pd.DataFrame,
    stroke_col: str = "Stroke",
) -> pd.DataFrame:
    """Retourne une copie du DataFrame avec la colonne nage en libellés français.

    Args:
        df (pd.DataFrame): Données source.
        stroke_col (str): Nom de la colonne contenant les codes de nage.

    Returns:
        pd.DataFrame: Copie avec libellés français dans ``stroke_col``.
    """
    if stroke_col not in df.columns:
        return df.copy()
    out = df.copy()
    out[stroke_col] = out[stroke_col].map(stroke_code_to_label)
    return out


def localize_event_string(event: Optional[str]) -> str:
    """Remplace le code de nage dans un libellé ``Event`` par son libellé français.

    Args:
        event (Optional[str]): Libellé type ``100 FR LCM``.

    Returns:
        str: Libellé localisé ou chaîne vide si l'entrée est vide.
    """
    if not event:
        return ""
    parts = str(event).strip().split()
    if len(parts) < 2:
        return str(event).strip()
    parts[1] = stroke_code_to_label(parts[1])
    return " ".join(parts)
