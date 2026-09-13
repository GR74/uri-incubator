"""Content-free participant-row detection for pre-publication validation."""

from __future__ import annotations

import re
from typing import Any

MAX_PRIVACY_DEPTH = 40
MAX_PRIVACY_NODES = 100_000
MAX_PRIVACY_ROWS = 10_000


def contains_participant_rows(value: Any) -> bool:
    """Detect row-shaped participant data without preserving source values.

    Traversal is bounded and fails closed when an untrusted structured input is
    too deep or large to inspect completely.
    """
    budget = _PrivacyBudget()
    try:
        return _contains_participant_rows(value, budget, 0)
    except _PrivacyLimitExceeded:
        return True


def _contains_participant_rows(value: Any, budget: _PrivacyBudget, depth: int) -> bool:
    budget.visit(depth)
    if isinstance(value, dict):
        budget.row()
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
        return any(_contains_participant_rows(child, budget, depth + 1) for child in value.values())
    if isinstance(value, list):
        return any(_contains_participant_rows(child, budget, depth + 1) for child in value)
    return False


class _PrivacyLimitExceeded(Exception):
    pass


class _PrivacyBudget:
    def __init__(self) -> None:
        self.nodes = 0
        self.rows = 0

    def visit(self, depth: int) -> None:
        self.nodes += 1
        if depth > MAX_PRIVACY_DEPTH or self.nodes > MAX_PRIVACY_NODES:
            raise _PrivacyLimitExceeded

    def row(self) -> None:
        self.rows += 1
        if self.rows > MAX_PRIVACY_ROWS:
            raise _PrivacyLimitExceeded


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
