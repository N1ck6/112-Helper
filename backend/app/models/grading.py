"""Оценки, ошибки, результаты ИИ, рекомендации, история и статистика (п.2.2, 2.6 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import (
    ErrorCategory,
    ErrorSeverity,
    EvaluationSource,
    MLTaskKind,
    MLTaskStatus,
    RecommendationTarget,
)


class Evaluation(UUIDPrimaryKey, Timestamped, Base):
    """Оценка одной попытки: автоматическая (ИИ) + возможная экспертная корректировка."""

    __tablename__ = "evaluations"
    __table_args__ = (sa.UniqueConstraint("attempt_id", name="evaluation_per_attempt"),)

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[EvaluationSource] = mapped_column(
        enum_column(EvaluationSource), default=EvaluationSource.AI, nullable=False
    )

    score: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(sa.Float, nullable=False, default=100.0)
    passed: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    # Частные показатели — из них собирается итог и графики в кабинете преподавателя.
    timing_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    procedure_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    accuracy_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    grammar_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    error_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    critical_error_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    details: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    ml_model: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    ml_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )

    # --- экспертная корректировка (обязательно фиксируется в аудите, п.2.3 ТЗ)
    overridden_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overridden_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    original_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    teacher_comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    errors: Mapped[list[ErrorRecord]] = relationship(
        back_populates="evaluation", lazy="selectin", cascade="all, delete-orphan"
    )


class ErrorRecord(UUIDPrimaryKey, Base):
    """Отдельное замечание: тайминг, регламент, данные, грамматика, синтаксис."""

    __tablename__ = "error_records"
    __table_args__ = (sa.Index("ix_error_records_category_severity", "category", "severity"),)

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[ErrorCategory] = mapped_column(enum_column(ErrorCategory), nullable=False)
    severity: Mapped[ErrorSeverity] = mapped_column(
        enum_column(ErrorSeverity), default=ErrorSeverity.MINOR, nullable=False
    )
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    field_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    expected: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    position: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    penalty: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )

    evaluation: Mapped[Evaluation] = relationship(back_populates="errors")


class MLResult(UUIDPrimaryKey, Base):
    """Сырой обмен с ML-сервисом: нужен для воспроизводимости оценок и разбора спорных случаев."""

    __tablename__ = "ml_results"

    kind: Mapped[MLTaskKind] = mapped_column(enum_column(MLTaskKind), nullable=False, index=True)
    status: Mapped[MLTaskStatus] = mapped_column(
        enum_column(MLTaskStatus), default=MLTaskStatus.OK, nullable=False
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="SET NULL"), nullable=True
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    endpoint: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    response_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    model: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False, index=True
    )


class Recommendation(UUIDPrimaryKey, Base):
    """Рекомендации ИИ: обучающемуся, преподавателю по группе, по типичным ошибкам."""

    __tablename__ = "recommendations"

    target: Mapped[RecommendationTarget] = mapped_column(
        enum_column(RecommendationTarget), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=True
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    priority: Mapped[int] = mapped_column(sa.Integer, default=3, nullable=False)
    source: Mapped[EvaluationSource] = mapped_column(
        enum_column(EvaluationSource), default=EvaluationSource.AI, nullable=False
    )
    based_on: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False, index=True
    )


class TrainingHistory(UUIDPrimaryKey, Base):
    """Денормализованная история обучения — быстрые выборки прогресса и успеваемости."""

    __tablename__ = "training_history"
    __table_args__ = (sa.Index("ix_training_history_student_at", "student_id", "recorded_at"),)

    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    error_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )
