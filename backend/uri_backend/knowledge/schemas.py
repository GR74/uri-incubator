from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, JsonValue, model_validator

from uri_backend.knowledge.models import CandidateType, RelationType


class CandidatePayload(BaseModel):
    data: dict[str, JsonValue] = Field(default_factory=dict)


class CandidateCitationInput(BaseModel):
    part_id: UUID = Field(validation_alias=AliasChoices("part_id", "content_part_id"))
    quote: str = Field(min_length=1)

    @property
    def content_part_id(self) -> UUID:
        return self.part_id


class ExtractedCandidate(BaseModel):
    candidate_key: str = Field(min_length=1, pattern=r".*\S.*")
    candidate_type: CandidateType
    statement: str = Field(min_length=1)
    payload: CandidatePayload = Field(default_factory=CandidatePayload)
    citations: list[CandidateCitationInput] = Field(min_length=1)
    event_time: datetime | None = None
    actors: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    uncertainty: str | None = None


class ExtractedRelation(BaseModel):
    source: RelationEndpointReference
    target: RelationEndpointReference
    relation_type: RelationType
    citations: list[CandidateCitationInput] = Field(min_length=1)
    statement: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class RelationEndpointReference(BaseModel):
    candidate_key: str | None = Field(default=None, min_length=1, pattern=r".*\S.*")
    record_id: UUID | None = None

    @model_validator(mode="after")
    def has_exactly_one_reference(self) -> RelationEndpointReference:
        if (self.candidate_key is None) == (self.record_id is None):
            raise ValueError("Exactly one of candidate_key or record_id is required.")
        return self
