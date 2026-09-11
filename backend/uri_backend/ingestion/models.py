from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from uri_backend.projects.models import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (sa.UniqueConstraint("source_version_id", "pipeline_version", name="uq_ingestion_run_source_pipeline"),)
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(sa.ForeignKey("source_versions.id"), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="queued")
    error_code: Mapped[str | None] = mapped_column(sa.String(100))
    error_detail: Mapped[str | None] = mapped_column(sa.String(1000))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(sa.ForeignKey("ingestion_runs.id"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="queued")
    available_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(sa.String(200))
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=3)
    error_code: Mapped[str | None] = mapped_column(sa.String(100))
    error_detail: Mapped[str | None] = mapped_column(sa.String(1000))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class IngestionJobAttempt(Base):
    __tablename__ = "ingestion_job_attempts"
    __table_args__ = (sa.UniqueConstraint("job_id", "attempt", name="uq_ingestion_job_attempt"),)
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(sa.ForeignKey("ingestion_jobs.id"), nullable=False)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(sa.String(32))
    error_code: Mapped[str | None] = mapped_column(sa.String(100))
    error_detail: Mapped[str | None] = mapped_column(sa.String(1000))
