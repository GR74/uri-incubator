"""Create project membership and audit tables.

Revision ID: 20260911_0002
Revises: 20260911_0001
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_0002"
down_revision: str | Sequence[str] | None = "20260911_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column(
            "is_pilot_actor", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at", timestamp, nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_table(
        "labs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "created_at", timestamp, nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_table(
        "projects",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("lab_id", uuid, sa.ForeignKey("labs.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at", timestamp, nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_table(
        "project_memberships",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", timestamp, nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_membership_user"),
    )
    op.create_table(
        "membership_capabilities",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "membership_id",
            uuid,
            sa.ForeignKey("project_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.UniqueConstraint(
            "membership_id", "capability", name="uq_membership_capability"
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("actor_id", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", uuid, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", timestamp, nullable=False, server_default=sa.text("now()")
        ),
    )
    op.execute(
        "CREATE FUNCTION prevent_audit_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit_events are append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION prevent_audit_event_mutation()")
    op.drop_table("audit_events")
    op.drop_table("membership_capabilities")
    op.drop_table("project_memberships")
    op.drop_table("projects")
    op.drop_table("labs")
    op.drop_table("users")
