from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_notification"
down_revision: Union[str, None] = "0002_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _add_json_list(table: str, column: str) -> None:
    """JSON-колонка со списком: server_default нужен для уже существующих строк."""
    op.add_column(
        table,
        sa.Column(column, JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column(table, column, server_default=None)


def upgrade() -> None:
    _add_json_list("incident_categories", "notify_services")
    _add_json_list("incident_cards", "notification_list")
    _add_json_list("card_attempts", "notification_list")
    op.add_column("card_attempts", sa.Column("service_code", sa.String(length=32), nullable=True))
    op.add_column("response_statuses", sa.Column("service_code", sa.String(length=32), nullable=True))
    op.create_index(
        op.f("ix_response_statuses_service_code"), "response_statuses", ["service_code"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_response_statuses_service_code"), table_name="response_statuses")
    op.drop_column("response_statuses", "service_code")
    op.drop_column("card_attempts", "service_code")
    op.drop_column("card_attempts", "notification_list")
    op.drop_column("incident_cards", "notification_list")
    op.drop_column("incident_categories", "notify_services")
