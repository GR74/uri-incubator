from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from uri_backend.projects.models import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    storage_key: Mapped[str] = mapped_column(
        sa.String(128), nullable=False, unique=True
    )
    byte_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id", "family", "external_id", name="uq_source_project_identity"
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("projects.id"), nullable=False
    )
    family: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    title: Mapped[str | None] = mapped_column(sa.String(500))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class SourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id",
            "family",
            "external_id",
            "native_version",
            "artifact_id",
            name="uq_source_version_idempotency",
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(sa.ForeignKey("sources.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("projects.id"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("artifacts.id"), nullable=False
    )
    family: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    native_version: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_by: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class ContentPart(Base):
    __tablename__ = "content_parts"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_version_id", "ordinal", name="uq_content_part_ordinal"
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("source_versions.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    locator: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    author_label: Mapped[str | None] = mapped_column(sa.String(500))
    source_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class SourceQualityAssessment(Base):
    __tablename__ = "source_quality_assessments"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_version_id", name="uq_source_quality_assessment_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("source_versions.id"), nullable=False
    )
    dimensions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    normalization: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
