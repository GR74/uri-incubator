"""Add durable cited-extraction provenance.

Revision ID: 20260913_0009
Revises: 20260913_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0009"
down_revision: str | Sequence[str] | None = "20260913_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid, timestamp, jsonb = postgresql.UUID(as_uuid=True), sa.DateTime(timezone=True), postgresql.JSONB
    op.create_table(
        "extraction_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("source_version_id", uuid, sa.ForeignKey("source_versions.id"), nullable=False),
        sa.Column("ingestion_run_id", uuid, sa.ForeignKey("ingestion_runs.id")),
        sa.Column("job_id", uuid, sa.ForeignKey("ingestion_jobs.id")),
        sa.Column("attempt", sa.Integer),
        sa.Column("worker_id", sa.String(200)),
        sa.Column("pipeline_version", sa.String(100), nullable=False),
        sa.Column("provider_id", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(300), nullable=False),
        sa.Column("model_digest", sa.String(300), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("sampling_config", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sampling_version", sa.String(100), nullable=False),
        sa.Column("call_metadata", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("response_metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_detail", sa.String(1000)),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", timestamp),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'retry', 'failed')", name="ck_extraction_run_status"),
        sa.UniqueConstraint("job_id", "attempt", name="uq_extraction_run_job_attempt"),
    )
    op.execute("""
        CREATE FUNCTION reject_extraction_run_provenance_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.source_version_id IS DISTINCT FROM OLD.source_version_id
             OR NEW.ingestion_run_id IS DISTINCT FROM OLD.ingestion_run_id
             OR NEW.job_id IS DISTINCT FROM OLD.job_id
             OR NEW.attempt IS DISTINCT FROM OLD.attempt
             OR NEW.worker_id IS DISTINCT FROM OLD.worker_id
             OR NEW.pipeline_version IS DISTINCT FROM OLD.pipeline_version
             OR NEW.provider_id IS DISTINCT FROM OLD.provider_id
             OR NEW.model_id IS DISTINCT FROM OLD.model_id
             OR NEW.model_digest IS DISTINCT FROM OLD.model_digest
             OR NEW.prompt_version IS DISTINCT FROM OLD.prompt_version
             OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
             OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
             OR NEW.sampling_config IS DISTINCT FROM OLD.sampling_config
             OR NEW.sampling_version IS DISTINCT FROM OLD.sampling_version THEN
            RAISE EXCEPTION 'extraction run provenance is immutable';
          END IF;
          RETURN NEW;
        END; $$
    """)
    op.execute("""
        CREATE TRIGGER extraction_runs_provenance_immutable
        BEFORE UPDATE ON extraction_runs FOR EACH ROW
        EXECUTE FUNCTION reject_extraction_run_provenance_mutation()
    """)
    op.add_column("draft_sets", sa.Column("extraction_run_id", uuid, sa.ForeignKey("extraction_runs.id")))
    op.create_unique_constraint("uq_draft_set_extraction_run", "draft_sets", ["extraction_run_id"])
    op.add_column("draft_candidates", sa.Column("extraction_run_id", uuid, sa.ForeignKey("extraction_runs.id")))
    op.add_column("draft_relations", sa.Column("extraction_run_id", uuid, sa.ForeignKey("extraction_runs.id")))
    op.add_column("draft_relations", sa.Column("source_record_id", uuid, sa.ForeignKey("records.id")))
    op.add_column("draft_relations", sa.Column("target_record_id", uuid, sa.ForeignKey("records.id")))
    op.alter_column("draft_relations", "source_candidate_id", existing_type=uuid, nullable=True)
    op.alter_column("draft_relations", "target_candidate_id", existing_type=uuid, nullable=True)
    op.create_check_constraint(
        "ck_draft_relation_source_endpoint",
        "draft_relations",
        "(source_candidate_id IS NULL) <> (source_record_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_draft_relation_target_endpoint",
        "draft_relations",
        "(target_candidate_id IS NULL) <> (target_record_id IS NULL)",
    )
    op.execute("""
        CREATE FUNCTION validate_draft_relation_endpoints() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.source_candidate_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM draft_candidates WHERE id = NEW.source_candidate_id AND draft_set_id = NEW.draft_set_id
          ) THEN RAISE EXCEPTION 'draft relation source candidate must belong to its draft set'; END IF;
          IF NEW.target_candidate_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM draft_candidates WHERE id = NEW.target_candidate_id AND draft_set_id = NEW.draft_set_id
          ) THEN RAISE EXCEPTION 'draft relation target candidate must belong to its draft set'; END IF;
          IF NEW.source_record_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM records r JOIN draft_sets ds ON ds.id = NEW.draft_set_id
            WHERE r.id = NEW.source_record_id AND r.project_id = ds.project_id
          ) THEN RAISE EXCEPTION 'draft relation source record project mismatch'; END IF;
          IF NEW.target_record_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM records r JOIN draft_sets ds ON ds.id = NEW.draft_set_id
            WHERE r.id = NEW.target_record_id AND r.project_id = ds.project_id
          ) THEN RAISE EXCEPTION 'draft relation target record project mismatch'; END IF;
          IF NEW.source_candidate_id IS NOT NULL AND NEW.source_candidate_id = NEW.target_candidate_id THEN
            RAISE EXCEPTION 'draft relation endpoints must be distinct';
          END IF;
          IF NEW.source_record_id IS NOT NULL AND NEW.source_record_id = NEW.target_record_id THEN
            RAISE EXCEPTION 'draft relation endpoints must be distinct';
          END IF;
          RETURN NULL;
        END; $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER draft_relations_endpoint_integrity
        AFTER INSERT OR UPDATE ON draft_relations DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_draft_relation_endpoints()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS extraction_runs_provenance_immutable ON extraction_runs")
    op.execute("DROP FUNCTION IF EXISTS reject_extraction_run_provenance_mutation()")
    op.execute("DROP TRIGGER IF EXISTS draft_relations_endpoint_integrity ON draft_relations")
    op.execute("DROP FUNCTION IF EXISTS validate_draft_relation_endpoints()")
    op.drop_constraint("ck_draft_relation_target_endpoint", "draft_relations", type_="check")
    op.drop_constraint("ck_draft_relation_source_endpoint", "draft_relations", type_="check")
    op.execute("DELETE FROM draft_relations WHERE source_record_id IS NOT NULL OR target_record_id IS NOT NULL")
    uuid = postgresql.UUID(as_uuid=True)
    op.alter_column("draft_relations", "target_candidate_id", existing_type=uuid, nullable=False)
    op.alter_column("draft_relations", "source_candidate_id", existing_type=uuid, nullable=False)
    op.drop_column("draft_relations", "target_record_id")
    op.drop_column("draft_relations", "source_record_id")
    op.drop_column("draft_relations", "extraction_run_id")
    op.drop_column("draft_candidates", "extraction_run_id")
    op.execute("ALTER TABLE draft_sets DROP CONSTRAINT IF EXISTS uq_draft_set_extraction_run")
    op.drop_column("draft_sets", "extraction_run_id")
    op.drop_table("extraction_runs")
