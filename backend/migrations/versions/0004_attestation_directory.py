from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_attestation"
down_revision: Union[str, None] = "0003_notification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LESSON_PURPOSE = sa.Enum(
    "training", "attestation", "refresher",
    name="lessonpurpose", native_enum=False, length=40,
)


def upgrade() -> None:
    # --- вид мероприятия и порог зачёта
    op.add_column(
        "lessons",
        sa.Column("purpose", LESSON_PURPOSE, nullable=False, server_default="training"),
    )
    op.alter_column("lessons", "purpose", server_default=None)
    op.add_column("lessons", sa.Column("passing_score", sa.Float(), nullable=True))
    op.create_index(op.f("ix_lessons_purpose"), "lessons", ["purpose"], unique=False)

    # --- итог участника мероприятия
    op.add_column("lesson_participants", sa.Column("final_score", sa.Float(), nullable=True))
    op.add_column("lesson_participants", sa.Column("is_passed", sa.Boolean(), nullable=True))

    # --- учётные записи из каталога организации
    op.add_column("users", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.add_column(
        "users",
        sa.Column("auth_source", sa.String(length=16), nullable=False, server_default="local"),
    )
    op.alter_column("users", "auth_source", server_default=None)
    op.add_column(
        "users", sa.Column("directory_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_users_external_id"), "users", ["external_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_external_id"), table_name="users")
    op.drop_column("users", "directory_synced_at")
    op.drop_column("users", "auth_source")
    op.drop_column("users", "external_id")
    op.drop_column("lesson_participants", "is_passed")
    op.drop_column("lesson_participants", "final_score")
    op.drop_index(op.f("ix_lessons_purpose"), table_name="lessons")
    op.drop_column("lessons", "passing_score")
    op.drop_column("lessons", "purpose")
