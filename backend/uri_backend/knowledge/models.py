from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from uri_backend.ingestion.models import ExtractionRun
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


def _enum_column(enum_class: type[StrEnum]) -> sa.Enum:
    """Keep application enums aligned with the migration's VARCHAR(32) checks."""
    return sa.Enum(enum_class, native_enum=False, create_constraint=False, length=32, values_callable=_enum_values)


class DraftSet(Base):
    __tablename__ = "draft_sets"
    __table_args__ = (
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'changes_requested', 'approved', 'published')", name="ck_draft_set_status"),
        sa.CheckConstraint("version > 0", name="ck_draft_set_version"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    author_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    extraction_run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("extraction_runs.id"))
    status: Mapped[DraftStatus] = mapped_column(_enum_column(DraftStatus), nullable=False, default=DraftStatus.DRAFT, server_default="draft")
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())
    candidates: Mapped[list[DraftCandidate]] = relationship(back_populates="draft_set")
    extraction_run: Mapped[ExtractionRun | None] = relationship()

    @property
    def validation_warnings(self) -> list[object]:
        """Warnings are persisted on the provenance run, never in model response text."""
        from types import SimpleNamespace

        return [SimpleNamespace(**warning) for warning in (self.extraction_run.warnings if self.extraction_run else [])]


class GraphEntity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (sa.CheckConstraint("entity_type IN ('project', 'record', 'source', 'artifact', 'research_item', 'person')", name="ck_graph_entity_type"), sa.UniqueConstraint("project_id", "entity_type", "native_id", name="uq_graph_entity_native"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    entity_type: Mapped[GraphEntityType] = mapped_column(_enum_column(GraphEntityType), nullable=False)
    native_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class DraftCandidate(Base):
    __tablename__ = "draft_candidates"
    __table_args__ = (
        sa.CheckConstraint("candidate_type IN ('decision', 'method', 'result', 'dead_end', 'blocker', 'next_step', 'claim', 'dataset', 'protocol', 'experiment', 'analysis_run', 'artifact_reference', 'project_event')", name="ck_draft_candidate_type"),
        sa.CheckConstraint("status IN ('draft', 'pending_review', 'changes_requested', 'approved', 'published')", name="ck_draft_candidate_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_draft_candidate_confidence"),
        sa.CheckConstraint("version > 0", name="ck_draft_candidate_version"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_sets.id", ondelete="CASCADE"), nullable=False)
    extraction_run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("extraction_runs.id"))
    candidate_type: Mapped[CandidateType] = mapped_column(_enum_column(CandidateType), nullable=False)
    statement: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
    event_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    actors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False)
    uncertainty: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[DraftStatus] = mapped_column(_enum_column(DraftStatus), nullable=False, default=DraftStatus.DRAFT, server_default="draft")
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    draft_set: Mapped[DraftSet] = relationship(back_populates="candidates")
    citations: Mapped[list[CandidateCitation]] = relationship(back_populates="candidate")


class CandidateCitation(Base):
    __tablename__ = "candidate_citations"
    __table_args__ = (sa.UniqueConstraint("candidate_id", "content_part_id", "quote", name="uq_candidate_citations_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_candidate_citations_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_candidates.id", ondelete="CASCADE"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    candidate: Mapped[DraftCandidate] = relationship(back_populates="citations")


class DraftRelation(Base):
    __tablename__ = "draft_relations"
    __table_args__ = (
        sa.CheckConstraint("relation_type IN ('proposes', 'accepts', 'rejects', 'explains', 'implements', 'tests', 'uses', 'produces', 'supports', 'challenges', 'summarizes', 'cites', 'defines', 'deviates_from', 'assigned_to', 'reviewed_by', 'supersedes', 'belongs_to', 'continued_from')", name="ck_draft_relation_type"),
        sa.CheckConstraint("source_candidate_id <> target_candidate_id", name="ck_draft_relation_distinct_endpoints"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_draft_relation_confidence"),
        sa.CheckConstraint("(source_candidate_id IS NULL) <> (source_record_id IS NULL)", name="ck_draft_relation_source_endpoint"),
        sa.CheckConstraint("(target_candidate_id IS NULL) <> (target_record_id IS NULL)", name="ck_draft_relation_target_endpoint"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_sets.id", ondelete="CASCADE"), nullable=False)
    extraction_run_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("extraction_runs.id"))
    source_candidate_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("draft_candidates.id"))
    source_record_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("records.id"))
    target_candidate_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("draft_candidates.id"))
    target_record_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("records.id"))
    relation_type: Mapped[RelationType] = mapped_column(_enum_column(RelationType), nullable=False)
    statement: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    citations: Mapped[list[DraftRelationCitation]] = relationship(back_populates="relation")


class DraftRelationCitation(Base):
    __tablename__ = "draft_relation_citations"
    __table_args__ = (sa.UniqueConstraint("draft_relation_id", "content_part_id", "quote", name="uq_draft_relation_citations_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_draft_relation_citations_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_relation_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_relations.id", ondelete="CASCADE"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    relation: Mapped[DraftRelation] = relationship(back_populates="citations")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (sa.CheckConstraint("decision IN ('approve', 'request_changes')", name="ck_review_decision"), sa.CheckConstraint("draft_version > 0", name="ck_review_draft_version"), sa.UniqueConstraint("draft_set_id", "draft_version", "reviewer_id", name="uq_review_draft_version_reviewer"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    draft_set_id: Mapped[UUID] = mapped_column(sa.ForeignKey("draft_sets.id"), nullable=False)
    draft_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    decision: Mapped[ReviewDecision] = mapped_column(_enum_column(ReviewDecision), nullable=False)
    comment: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (sa.CheckConstraint("record_type IN ('decision', 'method', 'result', 'dead_end', 'blocker', 'next_step', 'claim', 'dataset', 'protocol', 'experiment', 'analysis_run', 'artifact_reference', 'project_event')", name="ck_record_type"),)

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    record_type: Mapped[CandidateType] = mapped_column(_enum_column(CandidateType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class RecordVersion(Base):
    __tablename__ = "record_versions"
    __table_args__ = (sa.CheckConstraint("version > 0", name="ck_record_version"), sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_record_version_confidence"), sa.UniqueConstraint("record_id", "version", name="uq_record_version"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    record_id: Mapped[UUID] = mapped_column(sa.ForeignKey("records.id"), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    statement: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb"))
    event_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    actors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    uncertainty: Mapped[str | None] = mapped_column(sa.Text)
    published_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    published_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class RecordCitation(Base):
    __tablename__ = "record_citations"
    __table_args__ = (sa.UniqueConstraint("record_version_id", "content_part_id", "quote", name="uq_record_citations_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_record_citations_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    record_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("record_versions.id"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class Relation(Base):
    __tablename__ = "relations"
    __table_args__ = (sa.CheckConstraint("relation_type IN ('proposes', 'accepts', 'rejects', 'explains', 'implements', 'tests', 'uses', 'produces', 'supports', 'challenges', 'summarizes', 'cites', 'defines', 'deviates_from', 'assigned_to', 'reviewed_by', 'supersedes', 'belongs_to', 'continued_from')", name="ck_relation_type"), sa.CheckConstraint("source_entity_id <> target_entity_id", name="ck_relation_distinct_endpoints"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(sa.ForeignKey("projects.id"), nullable=False)
    source_entity_id: Mapped[UUID] = mapped_column(sa.ForeignKey("graph_entities.id"), nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(sa.ForeignKey("graph_entities.id"), nullable=False)
    relation_type: Mapped[RelationType] = mapped_column(_enum_column(RelationType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class RelationCitation(Base):
    __tablename__ = "relation_citations"
    __table_args__ = (sa.UniqueConstraint("relation_id", "content_part_id", "quote", name="uq_relation_citations_exact"), sa.CheckConstraint("length(btrim(quote)) > 0", name="ck_relation_citations_quote"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    relation_id: Mapped[UUID] = mapped_column(sa.ForeignKey("relations.id"), nullable=False)
    content_part_id: Mapped[UUID] = mapped_column(sa.ForeignKey("content_parts.id"), nullable=False)
    quote: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


class Supersession(Base):
    __tablename__ = "supersessions"
    __table_args__ = (sa.CheckConstraint("predecessor_version_id <> successor_version_id", name="ck_supersession_distinct_versions"), sa.UniqueConstraint("predecessor_version_id", name="uq_supersession_predecessor"), sa.UniqueConstraint("successor_version_id", name="uq_supersession_successor"))

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    predecessor_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("record_versions.id"), nullable=False)
    successor_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("record_versions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _reject_published_mutation(*_: object) -> None:
    raise ImmutableRecordError("Published record versions and citations are immutable.")


@event.listens_for(CandidateCitation, "before_update")
@event.listens_for(DraftRelationCitation, "before_update")
def _reject_draft_citation_reparent(
    _mapper: object, _connection: object, target: CandidateCitation | DraftRelationCitation
) -> None:
    owner_key = "candidate_id" if isinstance(target, CandidateCitation) else "draft_relation_id"
    if sa.inspect(target).attrs[owner_key].history.has_changes():
        raise ImmutableRecordError("Draft citation owner is immutable.")


for _model in (GraphEntity, Record, RecordVersion, RecordCitation, Relation, RelationCitation, Review, Supersession):
    event.listen(_model, "before_update", _reject_published_mutation)
    event.listen(_model, "before_delete", _reject_published_mutation)
