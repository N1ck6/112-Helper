from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_assignments"
down_revision = "0006_workplaces"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "lesson_participants",
        sa.Column("assigned_card_ids", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("lesson_participants", "assigned_card_ids", server_default=None)


def downgrade() -> None:
    op.drop_column("lesson_participants", "assigned_card_ids")
