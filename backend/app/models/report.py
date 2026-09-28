from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import ReportFormat, ReportStatus, ReportType


class Report(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "reports"
    __table_args__ = (sa.Index("ix_reports_type_status", "type", "status"),)

    type: Mapped[ReportType] = mapped_column(enum_column(ReportType), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(
        enum_column(ReportFormat), default=ReportFormat.JSON, nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        enum_column(ReportStatus), default=ReportStatus.PENDING, nullable=False
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("study_groups.id", ondelete="SET NULL"), nullable=True
    )

    params: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Готовые данные отчёта (для формата JSON и для отрисовки графиков на frontend).
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    file_path: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    row_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    generation_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class Certificate(UUIDPrimaryKey, Timestamped, Base):
    """Сертификат о прохождении обучения — PDF (п.2.6, п.12 ТЗ)."""

    __tablename__ = "certificates"

    serial: Mapped[str] = mapped_column(sa.String(32), unique=True, nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    program_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )
    score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    hours: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    file_path: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    #: Код для локальной проверки подлинности сертификата.
    verification_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
