from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_classifier"
down_revision: Union[str, None] = "0004_attestation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "incident_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("category_name", sa.String(length=255), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("features", JSON_TYPE, nullable=False),
        sa.Column("main_service", sa.String(length=128), nullable=True),
        sa.Column("services", JSON_TYPE, nullable=False),
        sa.Column("agency_classifiers", JSON_TYPE, nullable=False),
        sa.Column("raw", JSON_TYPE, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["incident_categories.id"],
            name=op.f("fk_incident_types_category_id_incident_categories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_types")),
        sa.UniqueConstraint("code", name=op.f("uq_incident_types_code")),
    )
    op.create_index("ix_incident_types_category_type", "incident_types", ["category_name", "name"])
    op.create_index(op.f("ix_incident_types_is_active"), "incident_types", ["is_active"])
    op.create_index(op.f("ix_incident_types_category_name"), "incident_types", ["category_name"])
    op.create_index(op.f("ix_incident_types_main_service"), "incident_types", ["main_service"])

    op.add_column(
        "incident_cards", sa.Column("incident_type_code", sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f("ix_incident_cards_incident_type_code"), "incident_cards", ["incident_type_code"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_incident_cards_incident_type_code"), table_name="incident_cards")
    op.drop_column("incident_cards", "incident_type_code")
    op.drop_index(op.f("ix_incident_types_main_service"), table_name="incident_types")
    op.drop_index(op.f("ix_incident_types_is_active"), table_name="incident_types")
    op.drop_index(op.f("ix_incident_types_category_name"), table_name="incident_types")
    op.drop_index("ix_incident_types_category_type", table_name="incident_types")
    op.drop_table("incident_types")
