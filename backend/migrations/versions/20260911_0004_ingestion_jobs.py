"""Create durable ingestion runs and jobs.

Revision ID: 20260911_0004
Revises: 20260911_0003
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_0004"
down_revision: str | Sequence[str] | None = "20260911_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid, timestamp = postgresql.UUID(as_uuid=True), sa.DateTime(timezone=True)
    op.create_table("ingestion_runs", sa.Column("id", uuid, primary_key=True), sa.Column("source_version_id", uuid, sa.ForeignKey("source_versions.id"), nullable=False), sa.Column("pipeline_version", sa.String(100), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("error_code", sa.String(100)), sa.Column("error_detail", sa.String(1000)), sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")), sa.Column("completed_at", timestamp), sa.UniqueConstraint("source_version_id", "pipeline_version", name="uq_ingestion_run_source_pipeline"))
    op.create_table("ingestion_jobs", sa.Column("id", uuid, primary_key=True), sa.Column("run_id", uuid, sa.ForeignKey("ingestion_runs.id"), nullable=False, unique=True), sa.Column("status", sa.String(32), nullable=False), sa.Column("available_at", timestamp, nullable=False, server_default=sa.text("now()")), sa.Column("lease_expires_at", timestamp), sa.Column("heartbeat_at", timestamp), sa.Column("worker_id", sa.String(200)), sa.Column("attempt", sa.Integer, nullable=False, server_default="0"), sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"), sa.Column("error_code", sa.String(100)), sa.Column("error_detail", sa.String(1000)), sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")), sa.Column("completed_at", timestamp))
    op.create_index("ix_ingestion_jobs_claim", "ingestion_jobs", ["status", "available_at"])
    op.create_table("ingestion_job_attempts", sa.Column("id", uuid, primary_key=True), sa.Column("job_id", uuid, sa.ForeignKey("ingestion_jobs.id"), nullable=False), sa.Column("attempt", sa.Integer, nullable=False), sa.Column("worker_id", sa.String(200), nullable=False), sa.Column("started_at", timestamp, nullable=False, server_default=sa.text("now()")), sa.Column("finished_at", timestamp), sa.Column("outcome", sa.String(32)), sa.Column("error_code", sa.String(100)), sa.Column("error_detail", sa.String(1000)), sa.UniqueConstraint("job_id", "attempt", name="uq_ingestion_job_attempt"))


def downgrade() -> None:
    op.drop_table("ingestion_job_attempts")
    op.drop_index("ix_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("ingestion_runs")
