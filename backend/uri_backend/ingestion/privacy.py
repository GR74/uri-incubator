"""Content-free participant-row detection for pre-publication validation."""

from __future__ import annotations

import re
from typing import Any


def contains_participant_rows(value: Any, container: str = "") -> bool:
    if isinstance(value, dict):
        fields = {_field_name(key) for key in value}
        has_identifier = any(_is_person_identifier_field(field) for field in fields)
        has_measurement = any(
            re.search(
                r"(?:age|gender|sex|measure|metric|score|trial|condition|session|response|outcome|value)",
                field,
            )
            for field in fields
        )
        if has_identifier and has_measurement:
            return True
        return any(contains_participant_rows(child, str(key)) for key, child in value.items())
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, dict)]
        if not records:
            return False
        return any(contains_participant_rows(item, container) for item in records)
    return False


def _field_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _is_person_identifier_field(field: str) -> bool:
    tokens = field.split("_")
    person_tokens = {"participant", "person", "subject", "patient"}
    if field in person_tokens:
        return True
    return bool(person_tokens.intersection(tokens)) and tokens[-1] in {
        "id",
        "identifier",
        "code",
    }
