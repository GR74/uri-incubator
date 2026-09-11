from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class AdapterInput(BaseModel):
    artifact_path: Path
    media_type: str
    family: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizationWarning(BaseModel):
    code: str
    message: str


class NormalizedPart(BaseModel):
    ordinal: int
    kind: str
    text: str
    locator: dict[str, JsonValue]
    author_label: str | None = None
    source_time: datetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizationResult(BaseModel):
    adapter: str
    adapter_version: str
    status: Literal["normalized", "needs_ocr", "unsupported", "failed"]
    parts: list[NormalizedPart]
    warnings: list[NormalizationWarning] = Field(default_factory=list)
    parse_coverage: float = Field(ge=0.0, le=1.0)
