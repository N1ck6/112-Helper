from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_drop_stats"
down_revision = "0007_assignments"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.drop_table("progress_stats")


def downgrade() -> None:
    op.create_table(
        "progress_stats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts_total", sa.Integer(), nullable=False),
        sa.Column("attempts_passed", sa.Integer(), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("avg_duration_ms", sa.Integer(), nullable=True),
        sa.Column("overtime_rate", sa.Float(), nullable=True),
        sa.Column("error_rate", sa.Float(), nullable=True),
        sa.Column("top_errors", JSON_TYPE, nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["study_groups.id"],
            name=op.f("fk_progress_stats_group_id_study_groups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_progress_stats_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_progress_stats")),
        sa.UniqueConstraint(
            "student_id", "group_id", "period_start", "period_end", name="stat_scope"
        ),
    )
