from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_response"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESPONSE_STATUS = sa.Enum(
    "added", "received", "accepted", "not_accepted", "response_started",
    "arrived", "work_in_progress", "work_completed", "work_refused",
    name="responsestatus", native_enum=False, length=40,
)
LIFECYCLE_STATUS = sa.Enum(
    "registered", "processed", "checked", "not_notified", "refusal",
    "not_finished", "completed",
    name="cardlifecyclestatus", native_enum=False, length=40,
)


def upgrade() -> None:
    op.create_table(
        "response_statuses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("service_name", sa.String(length=128), nullable=True),
        sa.Column("status", RESPONSE_STATUS, nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("work_order_no", sa.String(length=64), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("offset_ms", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("is_late", sa.Boolean(), nullable=False),
        sa.Column("set_by_system", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["card_attempts.id"],
            name=op.f("fk_response_statuses_attempt_id_card_attempts"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.id"],
            name=op.f("fk_response_statuses_lesson_id_lessons"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["users.id"],
            name=op.f("fk_response_statuses_student_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_response_statuses")),
        sa.UniqueConstraint("attempt_id", "sequence_no", name="response_status_sequence"),
    )
    op.create_index(
        "ix_response_statuses_attempt_status", "response_statuses", ["attempt_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_response_statuses_lesson_id"), "response_statuses", ["lesson_id"], unique=False
    )

    op.add_column(
        "card_attempts", sa.Column("response_deadline_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("card_attempts", sa.Column("first_response_status", RESPONSE_STATUS, nullable=True))
    op.add_column(
        "card_attempts", sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("card_attempts", sa.Column("first_response_seconds", sa.Float(), nullable=True))
    # server_default нужен, чтобы миграция прошла на уже существующих строках.
    op.add_column(
        "card_attempts",
        sa.Column("is_response_late", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("card_attempts", sa.Column("last_response_status", RESPONSE_STATUS, nullable=True))
    op.add_column(
        "card_attempts",
        sa.Column("lifecycle_status", LIFECYCLE_STATUS, nullable=False, server_default="registered"),
    )
    op.alter_column("card_attempts", "is_response_late", server_default=None)
    op.alter_column("card_attempts", "lifecycle_status", server_default=None)


def downgrade() -> None:
    op.drop_column("card_attempts", "lifecycle_status")
    op.drop_column("card_attempts", "last_response_status")
    op.drop_column("card_attempts", "is_response_late")
    op.drop_column("card_attempts", "first_response_seconds")
    op.drop_column("card_attempts", "first_response_at")
    op.drop_column("card_attempts", "first_response_status")
    op.drop_column("card_attempts", "response_deadline_at")
    op.drop_index(op.f("ix_response_statuses_lesson_id"), table_name="response_statuses")
    op.drop_index("ix_response_statuses_attempt_status", table_name="response_statuses")
    op.drop_table("response_statuses")
