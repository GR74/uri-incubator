"""Preserve safe normalization provenance beside immutable quality dimensions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260913_0007"
down_revision = "20260911_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "source_quality_assessments",
        sa.Column(
            "normalization",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade():
    op.drop_column("source_quality_assessments", "normalization")
