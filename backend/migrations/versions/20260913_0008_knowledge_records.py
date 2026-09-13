"""Create cited draft knowledge and immutable published records.

Revision ID: 20260913_0008
Revises: 20260913_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_0008"
down_revision: str | Sequence[str] | None = "20260913_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _citation_table(name: str, owner_column: str, owner_table: str) -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        name,
        sa.Column("id", uuid, primary_key=True),
        sa.Column(owner_column, uuid, sa.ForeignKey(f"{owner_table}.id"), nullable=False),
        sa.Column("content_part_id", uuid, sa.ForeignKey("content_parts.id"), nullable=False),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(owner_column, "content_part_id", "quote", name=f"uq_{name}_exact"),
        sa.CheckConstraint("length(btrim(quote)) > 0", name=f"ck_{name}_quote"),
    )


def _immutable(table: str) -> None:
    function = f"prevent_{table}_mutation"
    op.execute(
        f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN RAISE EXCEPTION '{table} are immutable'; END; $$"
    )
    op.execute(
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {function}()"
    )


def upgrade() -> None:
    uuid, timestamp, jsonb = postgresql.UUID(as_uuid=True), sa.DateTime(timezone=True), postgresql.JSONB
    candidate_types = "'decision', 'method', 'result', 'dead_end', 'blocker', 'next_step', 'claim', 'dataset', 'protocol', 'experiment', 'analysis_run', 'artifact_reference', 'project_event'"
    relation_types = "'supports', 'contradicts', 'derived_from', 'uses', 'produces', 'blocks', 'supersedes', 'related_to'"
    draft_statuses = "'draft', 'submitted', 'changes_requested', 'approved', 'published'"
    review_decisions = "'approve', 'request_changes'"

    op.create_table(
        "draft_sets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("author_id", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"status IN ({draft_statuses})", name="ck_draft_set_status"),
        sa.CheckConstraint("version > 0", name="ck_draft_set_version"),
    )
    op.create_table(
        "draft_candidates",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("draft_set_id", uuid, sa.ForeignKey("draft_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_type", sa.String(32), nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("payload", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("event_time", timestamp),
        sa.Column("actors", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("uncertainty", sa.Text),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"candidate_type IN ({candidate_types})", name="ck_draft_candidate_type"),
        sa.CheckConstraint(f"status IN ({draft_statuses})", name="ck_draft_candidate_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_draft_candidate_confidence"),
        sa.CheckConstraint("version > 0", name="ck_draft_candidate_version"),
    )
    _citation_table("candidate_citations", "candidate_id", "draft_candidates")
    op.create_table(
        "draft_relations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("draft_set_id", uuid, sa.ForeignKey("draft_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_candidate_id", uuid, sa.ForeignKey("draft_candidates.id"), nullable=False),
        sa.Column("target_candidate_id", uuid, sa.ForeignKey("draft_candidates.id"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("statement", sa.Text),
        sa.Column("confidence", sa.Float),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"relation_type IN ({relation_types})", name="ck_draft_relation_type"),
        sa.CheckConstraint("source_candidate_id <> target_candidate_id", name="ck_draft_relation_distinct_endpoints"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_draft_relation_confidence"),
    )
    _citation_table("draft_relation_citations", "draft_relation_id", "draft_relations")
    op.create_table(
        "reviews",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("draft_set_id", uuid, sa.ForeignKey("draft_sets.id"), nullable=False),
        sa.Column("draft_version", sa.Integer, nullable=False),
        sa.Column("reviewer_id", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"decision IN ({review_decisions})", name="ck_review_decision"),
        sa.CheckConstraint("draft_version > 0", name="ck_review_draft_version"),
        sa.UniqueConstraint("draft_set_id", "draft_version", "reviewer_id", name="uq_review_draft_version_reviewer"),
    )
    op.create_table(
        "records",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"record_type IN ({candidate_types})", name="ck_record_type"),
    )
    op.create_table(
        "record_versions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("record_id", uuid, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("payload", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("event_time", timestamp),
        sa.Column("actors", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Float),
        sa.Column("uncertainty", sa.Text),
        sa.Column("published_by", uuid, sa.ForeignKey("users.id")),
        sa.Column("published_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("version > 0", name="ck_record_version"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_record_version_confidence"),
        sa.UniqueConstraint("record_id", "version", name="uq_record_version"),
    )
    _citation_table("record_citations", "record_version_id", "record_versions")
    op.create_table(
        "relations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("project_id", uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_record_id", uuid, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("target_record_id", uuid, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"relation_type IN ({relation_types})", name="ck_relation_type"),
        sa.CheckConstraint("source_record_id <> target_record_id", name="ck_relation_distinct_endpoints"),
    )
    _citation_table("relation_citations", "relation_id", "relations")
    op.create_table(
        "supersessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("predecessor_version_id", uuid, sa.ForeignKey("record_versions.id"), nullable=False),
        sa.Column("successor_version_id", uuid, sa.ForeignKey("record_versions.id"), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("predecessor_version_id <> successor_version_id", name="ck_supersession_distinct_versions"),
        sa.UniqueConstraint("predecessor_version_id", name="uq_supersession_predecessor"),
        sa.UniqueConstraint("successor_version_id", name="uq_supersession_successor"),
    )

    op.execute("""
        CREATE FUNCTION validate_knowledge_citation() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owner_id uuid;
        BEGIN
          IF TG_TABLE_NAME = 'candidate_citations' THEN owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.candidate_id ELSE NEW.candidate_id END;
          ELSIF TG_TABLE_NAME = 'draft_relation_citations' THEN owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.draft_relation_id ELSE NEW.draft_relation_id END;
          ELSIF TG_TABLE_NAME = 'record_citations' THEN owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.record_version_id ELSE NEW.record_version_id END;
          ELSE owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.relation_id ELSE NEW.relation_id END;
          END IF;
          IF TG_TABLE_NAME = 'candidate_citations' AND EXISTS (
            SELECT 1 FROM candidate_citations cc JOIN draft_candidates dc ON dc.id = cc.candidate_id
            JOIN draft_sets ds ON ds.id = dc.draft_set_id JOIN content_parts cp ON cp.id = cc.content_part_id
            JOIN source_versions sv ON sv.id = cp.source_version_id WHERE cc.candidate_id = owner_id AND ds.project_id <> sv.project_id
          ) THEN RAISE EXCEPTION 'candidate citation project mismatch'; END IF;
          IF TG_TABLE_NAME = 'draft_relation_citations' AND EXISTS (
            SELECT 1 FROM draft_relation_citations rc JOIN draft_relations dr ON dr.id = rc.draft_relation_id
            JOIN draft_sets ds ON ds.id = dr.draft_set_id JOIN content_parts cp ON cp.id = rc.content_part_id
            JOIN source_versions sv ON sv.id = cp.source_version_id WHERE rc.draft_relation_id = owner_id AND ds.project_id <> sv.project_id
          ) THEN RAISE EXCEPTION 'draft relation citation project mismatch'; END IF;
          IF TG_TABLE_NAME = 'record_citations' AND EXISTS (
            SELECT 1 FROM record_citations rc JOIN record_versions rv ON rv.id = rc.record_version_id
            JOIN records r ON r.id = rv.record_id JOIN content_parts cp ON cp.id = rc.content_part_id
            JOIN source_versions sv ON sv.id = cp.source_version_id WHERE rc.record_version_id = owner_id AND r.project_id <> sv.project_id
          ) THEN RAISE EXCEPTION 'record citation project mismatch'; END IF;
          IF TG_TABLE_NAME = 'relation_citations' AND EXISTS (
            SELECT 1 FROM relation_citations rc JOIN relations r ON r.id = rc.relation_id
            JOIN content_parts cp ON cp.id = rc.content_part_id JOIN source_versions sv ON sv.id = cp.source_version_id
            WHERE rc.relation_id = owner_id AND r.project_id <> sv.project_id
          ) THEN RAISE EXCEPTION 'relation citation project mismatch'; END IF;
          RETURN NULL;
        END; $$
    """)
    for table in ("candidate_citations", "draft_relation_citations", "record_citations", "relation_citations"):
        op.execute(f"CREATE CONSTRAINT TRIGGER {table}_project_integrity AFTER INSERT OR UPDATE OR DELETE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_knowledge_citation()")

    op.execute("""
        CREATE FUNCTION validate_knowledge_owner() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owner_id uuid := COALESCE(NEW.id, OLD.id);
        BEGIN
          IF TG_TABLE_NAME = 'draft_candidates' AND NOT EXISTS (SELECT 1 FROM candidate_citations WHERE candidate_id = owner_id) THEN RAISE EXCEPTION 'draft candidate requires a citation'; END IF;
          IF TG_TABLE_NAME = 'draft_relations' THEN
            IF NOT EXISTS (SELECT 1 FROM draft_relation_citations WHERE draft_relation_id = owner_id) THEN RAISE EXCEPTION 'draft relation requires a citation'; END IF;
            IF EXISTS (SELECT 1 FROM draft_relations dr JOIN draft_candidates src ON src.id = dr.source_candidate_id JOIN draft_candidates dst ON dst.id = dr.target_candidate_id WHERE dr.id = owner_id AND (src.draft_set_id <> dr.draft_set_id OR dst.draft_set_id <> dr.draft_set_id)) THEN RAISE EXCEPTION 'draft relation endpoints must belong to its draft set'; END IF;
          END IF;
          IF TG_TABLE_NAME = 'record_versions' AND NOT EXISTS (SELECT 1 FROM record_citations WHERE record_version_id = owner_id) THEN RAISE EXCEPTION 'record version requires a citation'; END IF;
          IF TG_TABLE_NAME = 'relations' THEN
            IF NOT EXISTS (SELECT 1 FROM relation_citations WHERE relation_id = owner_id) THEN RAISE EXCEPTION 'relation requires a citation'; END IF;
            IF EXISTS (SELECT 1 FROM relations rel JOIN records src ON src.id = rel.source_record_id JOIN records dst ON dst.id = rel.target_record_id WHERE rel.id = owner_id AND (src.project_id <> rel.project_id OR dst.project_id <> rel.project_id)) THEN RAISE EXCEPTION 'relation endpoints must belong to its project'; END IF;
          END IF;
          IF TG_TABLE_NAME = 'supersessions' AND EXISTS (SELECT 1 FROM supersessions s JOIN record_versions oldv ON oldv.id = s.predecessor_version_id JOIN record_versions newv ON newv.id = s.successor_version_id WHERE s.id = owner_id AND (oldv.record_id <> newv.record_id OR oldv.version >= newv.version)) THEN RAISE EXCEPTION 'supersession must link a later version of the same record'; END IF;
          RETURN NULL;
        END; $$
    """)
    for table in ("draft_candidates", "draft_relations", "record_versions", "relations", "supersessions"):
        op.execute(f"CREATE CONSTRAINT TRIGGER {table}_integrity AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_knowledge_owner()")
    op.execute("""
        CREATE FUNCTION validate_knowledge_citation_presence() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owner_id uuid;
        BEGIN
          IF TG_TABLE_NAME = 'candidate_citations' THEN owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.candidate_id ELSE NEW.candidate_id END;
          ELSIF TG_TABLE_NAME = 'draft_relation_citations' THEN owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.draft_relation_id ELSE NEW.draft_relation_id END;
          ELSIF TG_TABLE_NAME = 'record_citations' THEN owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.record_version_id ELSE NEW.record_version_id END;
          ELSE owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.relation_id ELSE NEW.relation_id END;
          END IF;
          IF TG_TABLE_NAME = 'candidate_citations' AND EXISTS (SELECT 1 FROM draft_candidates WHERE id = owner_id) AND NOT EXISTS (SELECT 1 FROM candidate_citations WHERE candidate_id = owner_id) THEN RAISE EXCEPTION 'draft candidate requires a citation'; END IF;
          IF TG_TABLE_NAME = 'draft_relation_citations' AND EXISTS (SELECT 1 FROM draft_relations WHERE id = owner_id) AND NOT EXISTS (SELECT 1 FROM draft_relation_citations WHERE draft_relation_id = owner_id) THEN RAISE EXCEPTION 'draft relation requires a citation'; END IF;
          IF TG_TABLE_NAME = 'record_citations' AND EXISTS (SELECT 1 FROM record_versions WHERE id = owner_id) AND NOT EXISTS (SELECT 1 FROM record_citations WHERE record_version_id = owner_id) THEN RAISE EXCEPTION 'record version requires a citation'; END IF;
          IF TG_TABLE_NAME = 'relation_citations' AND EXISTS (SELECT 1 FROM relations WHERE id = owner_id) AND NOT EXISTS (SELECT 1 FROM relation_citations WHERE relation_id = owner_id) THEN RAISE EXCEPTION 'relation requires a citation'; END IF;
          RETURN NULL;
        END; $$
    """)
    for table in ("candidate_citations", "draft_relation_citations", "record_citations", "relation_citations"):
        op.execute(f"CREATE CONSTRAINT TRIGGER {table}_owner_citation_integrity AFTER INSERT OR UPDATE OR DELETE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_knowledge_citation_presence()")
    _immutable("record_versions")
    _immutable("record_citations")
    _immutable("relations")
    _immutable("relation_citations")
    _immutable("supersessions")


def downgrade() -> None:
    for table in ("supersessions", "relation_citations", "relations", "record_citations", "record_versions"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
        op.execute(f"DROP FUNCTION prevent_{table}_mutation()")
    for table in ("candidate_citations", "draft_relation_citations", "record_citations", "relation_citations"):
        op.execute(f"DROP TRIGGER {table}_project_integrity ON {table}")
        op.execute(f"DROP TRIGGER {table}_owner_citation_integrity ON {table}")
    for table in ("draft_candidates", "draft_relations", "record_versions", "relations", "supersessions"):
        op.execute(f"DROP TRIGGER {table}_integrity ON {table}")
    op.execute("DROP FUNCTION validate_knowledge_owner()")
    op.execute("DROP FUNCTION validate_knowledge_citation()")
    op.execute("DROP FUNCTION validate_knowledge_citation_presence()")
    for table in ("supersessions", "relation_citations", "relations", "record_citations", "record_versions", "records", "reviews", "draft_relation_citations", "draft_relations", "candidate_citations", "draft_candidates", "draft_sets"):
        op.drop_table(table)
