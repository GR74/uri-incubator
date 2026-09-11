"""Create immutable source and artifact registry.

Revision ID: 20260911_0003
Revises: 20260911_0002
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_0003"
down_revision: str | Sequence[str] | None = "20260911_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "artifacts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(128), nullable=False, unique=True),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "sources",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("family", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "family", "external_id", name="uq_source_project_identity"),
    )
    op.create_table(
        "source_versions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("source_id", uuid, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("artifact_id", uuid, sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("family", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("native_version", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "family", "external_id", "native_version", "artifact_id", name="uq_source_version_idempotency"),
    )
    op.create_table(
        "content_parts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("source_version_id", uuid, sa.ForeignKey("source_versions.id"), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("locator", postgresql.JSONB, nullable=False),
        sa.Column("author_label", sa.String(500)),
        sa.Column("source_time", timestamp),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("source_version_id", "ordinal", name="uq_content_part_ordinal"),
    )
    op.create_table(
        "source_quality_assessments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("source_version_id", uuid, sa.ForeignKey("source_versions.id"), nullable=False),
        sa.Column("dimensions", postgresql.JSONB, nullable=False),
        sa.Column("warnings", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
    )
    for table in ("artifacts", "sources", "source_versions", "content_parts", "source_quality_assessments"):
        function = f"prevent_{table}_mutation"
        trigger = f"{table}_append_only"
        op.execute(f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '{table} are immutable'; END; $$")
        op.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()")


def downgrade() -> None:
    for table in ("source_quality_assessments", "content_parts", "source_versions", "sources", "artifacts"):
        trigger = f"{table}_append_only"
        function = f"prevent_{table}_mutation"
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
        op.drop_table(table)
