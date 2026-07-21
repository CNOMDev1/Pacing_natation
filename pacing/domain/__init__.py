"""Domaine Pacing : labels, normalisation et schémas métier."""

from pacing.domain.normalize import (
    normalize_gender_code,
    normalize_name,
    normalize_text,
    primary_swimmer_name,
    primary_swimmer_name_and_yob,
    slugify,
    solo_swimmer_dict,
)
from pacing.domain.stroke_labels import (
    STROKE_CODE_TO_LABEL,
    STROKE_LABEL_TO_CODE,
    format_event_label,
    localize_event_string,
    relabel_stroke_column,
    stroke_code_to_label,
    stroke_label_to_code,
)

__all__ = [
    "STROKE_CODE_TO_LABEL",
    "STROKE_LABEL_TO_CODE",
    "format_event_label",
    "localize_event_string",
    "normalize_gender_code",
    "normalize_name",
    "normalize_text",
    "primary_swimmer_name",
    "primary_swimmer_name_and_yob",
    "relabel_stroke_column",
    "slugify",
    "solo_swimmer_dict",
    "stroke_code_to_label",
    "stroke_label_to_code",
]
