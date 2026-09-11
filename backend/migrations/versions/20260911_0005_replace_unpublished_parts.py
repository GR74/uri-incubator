"""Permit retry replacement of unpublished parts from the same ingestion run.

Revision ID: 20260911_0005
Revises: 20260911_0004
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0005"
down_revision: str | Sequence[str] | None = "20260911_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER content_parts_append_only ON content_parts")
    op.execute("DROP FUNCTION prevent_content_parts_mutation()")
    op.execute(
        "CREATE FUNCTION prevent_content_parts_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "IF TG_OP = 'DELETE' "
        "AND OLD.metadata ->> 'ingestion_run_id' = current_setting('uri.ingestion_run_id', true) "
        "THEN RETURN OLD; END IF; "
        "RAISE EXCEPTION 'content_parts are immutable'; "
        "END; $$"
    )
    op.execute(
        "CREATE TRIGGER content_parts_append_only BEFORE UPDATE OR DELETE ON content_parts "
        "FOR EACH ROW EXECUTE FUNCTION prevent_content_parts_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER content_parts_append_only ON content_parts")
    op.execute("DROP FUNCTION prevent_content_parts_mutation()")
    op.execute(
        "CREATE FUNCTION prevent_content_parts_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'content_parts are immutable'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER content_parts_append_only BEFORE UPDATE OR DELETE ON content_parts "
        "FOR EACH ROW EXECUTE FUNCTION prevent_content_parts_mutation()"
    )
