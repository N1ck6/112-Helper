from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDelete, Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import (
    DifficultyLevel,
    GenerationStatus,
    MaterialKind,
    ScenarioOrigin,
    ScenarioStatus,
)


class Scenario(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "scenarios"
    __table_args__ = (sa.Index("ix_scenarios_status_difficulty", "status", "difficulty"),)

    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="SET NULL"), nullable=True
    )
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        enum_column(DifficultyLevel), default=DifficultyLevel.BASIC, nullable=False
    )
    #: Вес сложности 1–10: ставит преподаватель либо предлагает ML на утверждение.
    difficulty_weight: Mapped[int] = mapped_column(
        sa.SmallInteger, default=2, server_default="2", nullable=False
    )
    suggested_weight: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    status: Mapped[ScenarioStatus] = mapped_column(
        enum_column(ScenarioStatus), default=ScenarioStatus.DRAFT, nullable=False, index=True
    )
    origin: Mapped[ScenarioOrigin] = mapped_column(
        enum_column(ScenarioOrigin), default=ScenarioOrigin.MANUAL, nullable=False
    )

    author_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Норматив на карточку; None → значение из настроек занятия/системы (30 сек).
    time_limit_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Критерии успешности: {"max_errors": 3, "min_score": 70, "syntax": {...}}
    success_criteria: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    #: Фабула вызова, реплики звонящего, вводные для обучающегося.
    briefing: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    # --- происхождение из ML-модуля
    generation_prompt: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    ml_model: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    ml_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)

    references: Mapped[list[ScenarioReference]] = relationship(
        back_populates="scenario", lazy="selectin", cascade="all, delete-orphan"
    )


class ScenarioReference(UUIDPrimaryKey, Timestamped, Base):
    """Эталонный ответ/последовательность действий, с которыми сравнивается обучающийся."""

    __tablename__ = "scenario_references"

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_cards.id", ondelete="SET NULL"), nullable=True
    )
    #: {"address": "...", "incident_type": "fire", ...}
    expected_fields: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: ["call_accepted", "classified", "routed_to_dds", "card_submitted"]
    expected_actions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Требования к формулировкам: ключевые фразы, запрещённые слова, regexp.
    expected_text: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    weight: Mapped[float] = mapped_column(sa.Float, default=1.0, nullable=False)

    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    #: Комментарий преподавателя для повторной генерации (п.3.2 ТЗ).
    teacher_comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="references")


class TrainingMaterial(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    """Методические материалы и первичные данные (памятка АРМ-112, классификатор, билеты)."""

    __tablename__ = "training_materials"

    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    kind: Mapped[MaterialKind] = mapped_column(
        enum_column(MaterialKind), default=MaterialKind.DOC, nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Передан ли материал в базу знаний ML-модуля (п.3.3 ТЗ).
    indexed_by_ml: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class GenerationRequest(UUIDPrimaryKey, Timestamped, Base):
    """Заявка преподавателя на генерацию сценариев нейросетью и её коррекцию."""

    __tablename__ = "generation_requests"

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_categories.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        enum_column(DifficultyLevel), default=DifficultyLevel.BASIC, nullable=False
    )
    count: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    prompt: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    teacher_comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[GenerationStatus] = mapped_column(
        enum_column(GenerationStatus), default=GenerationStatus.QUEUED, nullable=False
    )
    ml_response: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
