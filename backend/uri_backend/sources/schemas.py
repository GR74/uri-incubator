from __future__ import annotations

from datetime import datetime
from pathlib import Path
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


class GitSourceCommand(BaseModel):
    repository_root: Path
    ref_name: str
    start_commit: str
    end_commit: str
    include_paths: list[str] = Field(min_length=1)


class GitRegistrationCommand(GitSourceCommand):
    title: str | None = None


class GitPreviewResponse(BaseModel):
    resolved_head_sha: str
    commit_count: int
    allowed_file_count: int
    excluded_file_count: int
    total_allowed_bytes: int
    exclusions: list[dict[str, str]]


class ConversationPreviewResponse(BaseModel):
    stage_id: str
    conversations: list[dict[str, JsonValue]]
    expires_at: datetime


class ConversationSelectionCommand(BaseModel):
    conversation_ids: list[str] = Field(default_factory=list)


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
