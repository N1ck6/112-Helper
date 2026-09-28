from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_workplaces"
down_revision = "0005_classifier"
branch_labels = None
depends_on = None

#: JSON-колонки: на PostgreSQL — JSONB, на остальных СУБД — обычный JSON.
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

SERVICE_LEVEL = sa.Enum(
    "emergency",
    "department",
    "district",
    "okrug",
    "utility",
    "other",
    name="servicelevel",
    native_enum=False,
    length=40,
)
PROCESSING_KIND = sa.Enum(
    "service",
    "supervisor",
    "brigade",
    "applicant",
    "incoming_report",
    name="processingkind",
    native_enum=False,
    length=40,
)


def upgrade() -> None:
    # ------------------------------------------------- справочник ДДС
    op.create_table(
        "duty_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=128), nullable=True),
        sa.Column("level", SERVICE_LEVEL, nullable=False),
        sa.Column("okrug", sa.String(length=64), nullable=True),
        sa.Column("area", sa.String(length=128), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("phone_extension", sa.String(length=16), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("supervisor", JSON_TYPE, nullable=False),
        sa.Column("categories", JSON_TYPE, nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("meta", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["duty_services.id"],
            name=op.f("fk_duty_services_parent_id_duty_services"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_duty_services")),
        sa.UniqueConstraint("code", name=op.f("uq_duty_services_code")),
    )
    op.create_index(op.f("ix_duty_services_area"), "duty_services", ["area"])
    op.create_index(op.f("ix_duty_services_created_at"), "duty_services", ["created_at"])
    op.create_index(op.f("ix_duty_services_level"), "duty_services", ["level"])
    op.create_index("ix_duty_services_level_area", "duty_services", ["level", "area"])
    op.create_index(op.f("ix_duty_services_okrug"), "duty_services", ["okrug"])

    # ------------------------------------------------- рабочие места
    op.create_table(
        "workplaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("room", sa.String(length=64), nullable=True),
        sa.Column("host", sa.String(length=64), nullable=True),
        sa.Column("phone_extension", sa.String(length=16), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("occupied_by_id", sa.Uuid(), nullable=True),
        sa.Column("occupied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["occupied_by_id"],
            ["users.id"],
            name=op.f("fk_workplaces_occupied_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workplaces")),
        sa.UniqueConstraint("number", name="workplace_number_unique"),
    )
    op.create_index(op.f("ix_workplaces_created_at"), "workplaces", ["created_at"])
    op.create_index(op.f("ix_workplaces_number"), "workplaces", ["number"])

    # ------------------------------------------------- отработки (звонки)
    op.create_table(
        "card_processings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("kind", PROCESSING_KIND, nullable=False),
        sa.Column("service_code", sa.String(length=32), nullable=True),
        sa.Column("service_name", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("answered_by", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("offset_ms", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("workplace_id", sa.Uuid(), nullable=True),
        sa.Column("meta", JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["card_attempts.id"],
            name=op.f("fk_card_processings_attempt_id_card_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["lessons.id"],
            name=op.f("fk_card_processings_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_card_processings_student_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workplace_id"],
            ["workplaces.id"],
            name=op.f("fk_card_processings_workplace_id_workplaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_processings")),
    )
    op.create_index("ix_card_processings_attempt", "card_processings", ["attempt_id", "sequence_no"])
    op.create_index(op.f("ix_card_processings_lesson_id"), "card_processings", ["lesson_id"])
    op.create_index("ix_card_processings_lesson_kind", "card_processings", ["lesson_id", "kind"])
    op.create_index(op.f("ix_card_processings_service_code"), "card_processings", ["service_code"])
    op.create_foreign_key(
        op.f("fk_card_processings_call_id_call_records"),
        "card_processings",
        "call_records",
        ["call_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )

    # ------------------------------------------------- веса сложности 1–10
    op.add_column(
        "assignments",
        sa.Column("difficulty_weight", sa.SmallInteger(), server_default="2", nullable=False),
    )
    op.add_column(
        "scenarios",
        sa.Column("difficulty_weight", sa.SmallInteger(), server_default="2", nullable=False),
    )
    op.add_column("scenarios", sa.Column("suggested_weight", sa.SmallInteger(), nullable=True))
    op.add_column(
        "incident_cards",
        sa.Column("difficulty_weight", sa.SmallInteger(), server_default="2", nullable=False),
    )
    op.create_index(
        op.f("ix_incident_cards_difficulty_weight"), "incident_cards", ["difficulty_weight"]
    )
    op.add_column("lessons", sa.Column("difficulty_weight", sa.SmallInteger(), nullable=True))
    op.add_column(
        "lessons",
        sa.Column(
            "adaptive_difficulty", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )

    # ------------------------------------------------- участник: место и сложность
    op.add_column("lesson_participants", sa.Column("workplace_id", sa.Uuid(), nullable=True))
    op.add_column(
        "lesson_participants", sa.Column("difficulty_weight", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "lesson_participants",
        sa.Column("difficulty_log", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("lesson_participants", "difficulty_log", server_default=None)
    op.create_foreign_key(
        op.f("fk_lesson_participants_workplace_id_workplaces"),
        "lesson_participants",
        "workplaces",
        ["workplace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------- попытка: поток и таймеры
    op.add_column(
        "card_attempts",
        sa.Column("difficulty_weight", sa.SmallInteger(), server_default="2", nullable=False),
    )
    op.add_column("card_attempts", sa.Column("workplace_id", sa.Uuid(), nullable=True))
    op.add_column(
        "card_attempts", sa.Column("work_deadline_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("card_attempts", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_card_attempts_workplace_id_workplaces"),
        "card_attempts",
        "workplaces",
        ["workplace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        op.f("fk_call_records_attempt_id_card_attempts"),
        "call_records",
        "card_attempts",
        ["attempt_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_card_attempts_call_id_call_records"),
        "card_attempts",
        "call_records",
        ["call_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_incident_cards_source_attempt_id_card_attempts"),
        "incident_cards",
        "card_attempts",
        ["source_attempt_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_index(op.f("ix_incident_types_created_at"), "incident_types", ["created_at"])

    for table in ("scenarios", "incident_cards", "assignments"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET difficulty_weight = CASE difficulty "  # noqa: S608
                "WHEN 'medium' THEN 5 WHEN 'hard' THEN 9 ELSE 2 END"
            )
        )
    op.execute(
        sa.text(
            "UPDATE lessons SET difficulty_weight = CASE difficulty "
            "WHEN 'medium' THEN 5 WHEN 'hard' THEN 9 ELSE 2 END"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_incident_types_created_at"), table_name="incident_types")
    op.drop_constraint(
        op.f("fk_incident_cards_source_attempt_id_card_attempts"),
        "incident_cards",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_card_attempts_call_id_call_records"), "card_attempts", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_call_records_attempt_id_card_attempts"), "call_records", type_="foreignkey"
    )

    op.drop_constraint(
        op.f("fk_card_attempts_workplace_id_workplaces"), "card_attempts", type_="foreignkey"
    )
    op.drop_column("card_attempts", "opened_at")
    op.drop_column("card_attempts", "work_deadline_at")
    op.drop_column("card_attempts", "workplace_id")
    op.drop_column("card_attempts", "difficulty_weight")

    op.drop_constraint(
        op.f("fk_lesson_participants_workplace_id_workplaces"),
        "lesson_participants",
        type_="foreignkey",
    )
    op.drop_column("lesson_participants", "difficulty_log")
    op.drop_column("lesson_participants", "difficulty_weight")
    op.drop_column("lesson_participants", "workplace_id")

    op.drop_column("lessons", "adaptive_difficulty")
    op.drop_column("lessons", "difficulty_weight")
    op.drop_index(op.f("ix_incident_cards_difficulty_weight"), table_name="incident_cards")
    op.drop_column("incident_cards", "difficulty_weight")
    op.drop_column("scenarios", "suggested_weight")
    op.drop_column("scenarios", "difficulty_weight")
    op.drop_column("assignments", "difficulty_weight")

    op.drop_index(op.f("ix_card_processings_service_code"), table_name="card_processings")
    op.drop_index("ix_card_processings_lesson_kind", table_name="card_processings")
    op.drop_index(op.f("ix_card_processings_lesson_id"), table_name="card_processings")
    op.drop_index("ix_card_processings_attempt", table_name="card_processings")
    op.drop_table("card_processings")

    op.drop_index(op.f("ix_workplaces_number"), table_name="workplaces")
    op.drop_index(op.f("ix_workplaces_created_at"), table_name="workplaces")
    op.drop_table("workplaces")

    op.drop_index(op.f("ix_duty_services_okrug"), table_name="duty_services")
    op.drop_index("ix_duty_services_level_area", table_name="duty_services")
    op.drop_index(op.f("ix_duty_services_level"), table_name="duty_services")
    op.drop_index(op.f("ix_duty_services_created_at"), table_name="duty_services")
    op.drop_index(op.f("ix_duty_services_area"), table_name="duty_services")
    op.drop_table("duty_services")
