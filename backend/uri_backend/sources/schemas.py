from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue


class RegisterSourceVersion(BaseModel):
    project_id: UUID
    family: str
    external_id: str
    native_version: str
    media_type: str
    title: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizedPart(BaseModel):
    ordinal: int
    kind: str
    text: str
    locator: dict[str, str | int]
    author_label: str | None = None
    source_time: datetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ArtifactResponse(BaseModel):
    id: UUID
    sha256: str
    storage_key: str
    byte_size: int


class SourceResponse(BaseModel):
    id: UUID
    project_id: UUID
    family: str
    external_id: str
    title: str | None


class SourceVersionResponse(BaseModel):
    id: UUID
    source_id: UUID
    project_id: UUID
    family: str
    external_id: str
    native_version: str
    media_type: str
    artifact_id: UUID


class ContentPartResponse(BaseModel):
    id: UUID
    ordinal: int
    kind: str
    text: str
    locator: dict[str, str | int]
    author_label: str | None
    source_time: datetime | None
    metadata: dict[str, JsonValue]
