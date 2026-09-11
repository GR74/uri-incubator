"""Require one immutable quality assessment for every source version.

Revision ID: 20260911_0006
Revises: 20260911_0005
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0006"
down_revision: str | Sequence[str] | None = "20260911_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT source_version_id FROM source_quality_assessments "
        "GROUP BY source_version_id HAVING count(*) > 1) THEN "
        "RAISE EXCEPTION 'duplicate immutable source quality assessments require manual review'; "
        "END IF; "
        "END $$"
    )
    op.create_unique_constraint(
        "uq_source_quality_assessment_version",
        "source_quality_assessments",
        ["source_version_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_source_quality_assessment_version",
        "source_quality_assessments",
        type_="unique",
    )
