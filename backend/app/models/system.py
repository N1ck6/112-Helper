from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import (
    BackupStatus,
    CallDirection,
    CallStatus,
    OutboxStatus,
    ServiceStatus,
)


class SystemSetting(UUIDPrimaryKey, Timestamped, Base):
    """Изменяемые администратором параметры (п.1.3 ТЗ) без перезапуска сервиса."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    category: Mapped[str] = mapped_column(sa.String(64), default="general", nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Параметры безопасности требуют отдельного права на изменение.
    is_protected: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ServiceState(UUIDPrimaryKey, Base):
    """Состояние компонентов комплекса: backend, ML, SIP, БД, frontend."""

    __tablename__ = "service_states"

    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(32), default="service", nullable=False)
    status: Mapped[ServiceStatus] = mapped_column(
        enum_column(ServiceStatus), default=ServiceStatus.UNKNOWN, nullable=False
    )
    version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    details: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )


class BackupRecord(UUIDPrimaryKey, Base):
    """Журнал резервного копирования — не реже 1 раза в сутки (п.9 ТЗ)."""

    __tablename__ = "backup_records"

    kind: Mapped[str] = mapped_column(sa.String(32), default="full", nullable=False)
    status: Mapped[BackupStatus] = mapped_column(
        enum_column(BackupStatus), default=BackupStatus.STARTED, nullable=False
    )
    path: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class TelephonyConfig(UUIDPrimaryKey, Timestamped, Base):
    """Параметры локального SIP-сервера (настраивает администратор, п.1.3)."""

    __tablename__ = "telephony_configs"

    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False, default="default")
    sip_host: Mapped[str] = mapped_column(sa.String(255), nullable=False, default="localhost")
    sip_port: Mapped[int] = mapped_column(sa.Integer, default=5060, nullable=False)
    sip_domain: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    transport: Mapped[str] = mapped_column(sa.String(16), default="UDP", nullable=False)
    codec: Mapped[str] = mapped_column(sa.String(32), default="PCMU", nullable=False)
    #: Требование п.2.8/п.7 ТЗ: задержка голоса не более 150 мс.
    max_latency_ms: Mapped[int] = mapped_column(sa.Integer, default=150, nullable=False)
    record_calls: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    audio_format: Mapped[str] = mapped_column(sa.String(8), default="wav", nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CallRecord(UUIDPrimaryKey, Base):
    """Учебный вызов: создаётся модулем телефонии, связывается с попыткой."""

    __tablename__ = "call_records"
    __table_args__ = (sa.Index("ix_call_records_lesson_status", "lesson_id", "status"),)

    sip_call_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, unique=True)
    direction: Mapped[CallDirection] = mapped_column(
        enum_column(CallDirection), default=CallDirection.INBOUND, nullable=False
    )
    status: Mapped[CallStatus] = mapped_column(
        enum_column(CallStatus), default=CallStatus.RINGING, nullable=False
    )
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("card_attempts.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    caller_number: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    callee_number: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )
    answered_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    audio_format: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class OutboxMessage(UUIDPrimaryKey, Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (sa.Index("ix_outbox_status_next", "status", "next_attempt_at"),)

    topic: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        enum_column(OutboxStatus), default=OutboxStatus.PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
