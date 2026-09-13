from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from uri_backend.knowledge.models import CandidateType, RelationType


class CandidatePayload(BaseModel):
    data: dict[str, JsonValue] = Field(default_factory=dict)


class CandidateCitationInput(BaseModel):
    content_part_id: UUID
    quote: str = Field(min_length=1)


class ExtractedCandidate(BaseModel):
    candidate_type: CandidateType
    statement: str = Field(min_length=1)
    payload: CandidatePayload = Field(default_factory=CandidatePayload)
    citations: list[CandidateCitationInput] = Field(min_length=1)
    event_time: datetime | None = None
    actors: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    uncertainty: str | None = None


class ExtractedRelation(BaseModel):
    source_candidate_id: UUID
    target_candidate_id: UUID
    relation_type: RelationType
    citations: list[CandidateCitationInput] = Field(min_length=1)
    statement: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
