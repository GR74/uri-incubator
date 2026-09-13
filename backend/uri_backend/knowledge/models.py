from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from uri_backend.knowledge.errors import ImmutableRecordError
from uri_backend.projects.models import Base


class CandidateType(StrEnum):
    DECISION = "decision"
    METHOD = "method"
    RESULT = "result"
    DEAD_END = "dead_end"
    BLOCKER = "blocker"
    NEXT_STEP = "next_step"
    CLAIM = "claim"
    DATASET = "dataset"
    PROTOCOL = "protocol"
    EXPERIMENT = "experiment"
    ANALYSIS_RUN = "analysis_run"
    ARTIFACT_REFERENCE = "artifact_reference"
    PROJECT_EVENT = "project_event"


class RelationType(StrEnum):
    PROPOSES = "proposes"
    ACCEPTS = "accepts"
    REJECTS = "rejects"
    EXPLAINS = "explains"
    IMPLEMENTS = "implements"
    TESTS = "tests"
    USES = "uses"
    PRODUCES = "produces"
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    SUMMARIZES = "summarizes"
    CITES = "cites"
    DEFINES = "defines"
    DEVIATES_FROM = "deviates_from"
    ASSIGNED_TO = "assigned_to"
    REVIEWED_BY = "reviewed_by"
    SUPERSEDES = "supersedes"
    BELONGS_TO = "belongs_to"
    CONTINUED_FROM = "continued_from"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    PUBLISHED = "published"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class GraphEntityType(StrEnum):
    PROJECT = "project"
    RECORD = "record"
    SOURCE = "source"
    ARTIFACT = "artifact"
    RESEARCH_ITEM = "research_item"
    PERSON = "person"


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class DraftSet(Base):
    __tablename__ = "draft_sets"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    author_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    status: Mapped[DraftStatus] = mapped_column(sa.Enum(DraftStatus, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False, default=DraftStatus.DRAFT)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())
    candidates: Mapped[list[DraftCandidate]] = relationship(back_populates="draft_set")


class GraphEntity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (sa.UniqueConstraint("project_id", "entity_type", "native_id", name="uq_graph_entity_native"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    entity_type: Mapped[GraphEntityType] = mapped_column(sa.Enum(GraphEntityType, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False)
    native_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class DraftCandidate(Base):
    __tablename__ = "draft_candidates"
    __table_args__ = (sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_draft_candidate_confidence"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_sets.id", ondelete="CASCADE"), nullable=False)
    candidate_type: Mapped[CandidateType] = mapped_column(sa.Enum(CandidateType, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False)
    statement: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    event_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    actors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False)
    uncertainty: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[DraftStatus] = mapped_column(sa.Enum(DraftStatus, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False, default=DraftStatus.DRAFT)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    draft_set: Mapped[DraftSet] = relationship(back_populates="candidates")
    citations: Mapped[list[CandidateCitation]] = relationship(back_populates="candidate")


class CandidateCitation(Base):
    __tablename__ = "candidate_citations"
    __table_args__ = (sa.UniqueConstraint("candidate_id", "content_part_id", "quote", name="uq_candidate_citation_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_candidate_citation_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_candidates.id", ondelete="CASCADE"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    candidate: Mapped[DraftCandidate] = relationship(back_populates="citations")


class DraftRelation(Base):
    __tablename__ = "draft_relations"
    __table_args__ = (sa.CheckConstraint("source_candidate_id <> target_candidate_id", name="ck_draft_relation_distinct_endpoints"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_sets.id", ondelete="CASCADE"), nullable=False)
    source_candidate_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_candidates.id"), nullable=False)
    target_candidate_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_candidates.id"), nullable=False)
    relation_type: Mapped[RelationType] = mapped_column(sa.Enum(RelationType, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False)
    statement: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    citations: Mapped[list[DraftRelationCitation]] = relationship(back_populates="relation")


class DraftRelationCitation(Base):
    __tablename__ = "draft_relation_citations"
    __table_args__ = (sa.UniqueConstraint("draft_relation_id", "content_part_id", "quote", name="uq_draft_relation_citation_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_draft_relation_citation_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_relation_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_relations.id", ondelete="CASCADE"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    relation: Mapped[DraftRelation] = relationship(back_populates="citations")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (sa.UniqueConstraint("draft_set_id", "draft_version", "reviewer_id", name="uq_review_draft_version_reviewer"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_sets.id"), nullable=False)
    draft_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    decision: Mapped[ReviewDecision] = mapped_column(sa.Enum(ReviewDecision, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False)
    comment: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class Record(Base):
    __tablename__ = "records"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    record_type: Mapped[CandidateType] = mapped_column(sa.Enum(CandidateType, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class RecordVersion(Base):
    __tablename__ = "record_versions"
    __table_args__ = (sa.UniqueConstraint("record_id", "version", name="uq_record_version"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    record_id: Mapped[UUID] = mapped_column(sa.ForeignKey("records.id"), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    statement: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    event_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    actors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    uncertainty: Mapped[str | None] = mapped_column(sa.Text)
    published_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class RecordCitation(Base):
    __tablename__ = "record_citations"
    __table_args__ = (sa.UniqueConstraint("record_version_id", "content_part_id", "quote", name="uq_record_citation_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_record_citation_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    record_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("record_versions.id"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class Relation(Base):
    __tablename__ = "relations"
    __table_args__ = (sa.CheckConstraint("source_entity_id <> target_entity_id", name="ck_relation_distinct_endpoints"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    source_entity_id: Mapped[UUID] = mapped_column(sa.ForeignKey("graph_entities.id"), nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(sa.ForeignKey("graph_entities.id"), nullable=False)
    relation_type: Mapped[RelationType] = mapped_column(sa.Enum(RelationType, native_enum=False, create_constraint=True, values_callable=_enum_values), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class RelationCitation(Base):
    __tablename__ = "relation_citations"
    __table_args__ = (sa.UniqueConstraint("relation_id", "content_part_id", "quote", name="uq_relation_citation_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_relation_citation_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    relation_id: Mapped[UUID] = mapped_column(sa.ForeignKey("relations.id"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class Supersession(Base):
    __tablename__ = "supersessions"
    __table_args__ = (sa.UniqueConstraint("predecessor_version_id", name="uq_supersession_predecessor"), sa.UniqueConstraint("successor_version_id", name="uq_supersession_successor"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    predecessor_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("record_versions.id"), nullable=False)
    successor_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("record_versions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _reject_published_mutation(*_: object) -> None:
    raise ImmutableRecordError("Published record versions and citations are immutable.")


for _model in (GraphEntity, Record, RecordVersion, RecordCitation, Relation, RelationCitation, Review, Supersession):
    event.listen(_model, "before_update", _reject_published_mutation)
    event.listen(_model, "before_delete", _reject_published_mutation)
