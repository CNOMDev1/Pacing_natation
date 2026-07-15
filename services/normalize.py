"""Normalisations métier partagées (texte, genre, nageurs).

Unifie les variantes autrefois dupliquées entre UI, couloirs et loaders.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional, Tuple

import pandas as pd


def normalize_text(value: Any) -> str:
    """
    Normalise un texte pour comparaison (minuscules, sans accents).

    Args:
        value (Any): Chaîne ou valeur pandas.

    Returns:
        str: Texte normalisé ASCII, espaces réduits.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def normalize_name(value: object) -> str:
    """
    Normalise un nom pour recherche fuzzy / déduplication.

    Args:
        value (object): Nom brut.

    Returns:
        str: Nom normalisé ASCII.
    """
    return normalize_text(value)


def normalize_gender_code(value: object) -> Optional[str]:
    """
    Normalise un libellé genre en code interne ``F`` ou ``M``.

    Args:
        value (object): Genre brut (Extranat, USA, libellés français, etc.).

    Returns:
        Optional[str]: ``F``, ``M`` ou None si non reconnu.
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in ("F", "FEMME", "FEMALE", "W", "FÉMININ", "FEMININ"):
        return "F"
    if s in ("M", "H", "HOMME", "MALE", "MAN", "MASCULIN"):
        return "M"
    return None


def slugify(text: str) -> str:
    """
    Convertit un libellé en identifiant URL/fichier (kebab-case).

    Args:
        text (str): Texte source.

    Returns:
        str: Slug sans caractères spéciaux.
    """
    value = normalize_text(text)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def primary_swimmer_name(swimmers: Any) -> Optional[str]:
    """
    Retourne le nom du premier nageur si ``swimmer`` est une liste non vide.

    Args:
        swimmers (Any): Valeur de la colonne ``swimmer``.

    Returns:
        Optional[str]: Nom du nageur ou None.
    """
    if not isinstance(swimmers, list) or len(swimmers) == 0:
        return None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None
    name = first.get("Name")
    return str(name) if name is not None else None


def primary_swimmer_name_and_yob(
    swimmers: Any,
) -> Tuple[Optional[str], Optional[int]]:
    """
    Retourne nom et année de naissance du nageur solo (liste à un seul élément).

    Args:
        swimmers (Any): Valeur de la colonne ``swimmer``.

    Returns:
        Tuple[Optional[str], Optional[int]]: Nom et YOB, ou (None, None) si relais.
    """
    if not isinstance(swimmers, list) or len(swimmers) != 1:
        return None, None
    first = swimmers[0]
    if not isinstance(first, dict):
        return None, None
    name = first.get("Name")
    yob = first.get("Year_of_birth")
    yob_int: Optional[int] = None
    try:
        if yob is not None and yob == yob:
            yob_int = int(yob)
    except (TypeError, ValueError):
        yob_int = None
    return (str(name) if name is not None else None), yob_int
