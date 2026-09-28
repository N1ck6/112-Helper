from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import AuditAction, LogLevel


class AuditLog(UUIDPrimaryKey, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_logs_at_action", "at", "action"),
        sa.Index("ix_audit_logs_object", "object_type", "object_id"),
    )

    at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False, index=True
    )
    action: Mapped[AuditAction] = mapped_column(enum_column(AuditAction), nullable=False)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_username: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    actor_roles: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    object_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    #: Состояние до и после изменения — обязательный элемент аудита оценок.
    before: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    after: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    result: Mapped[str] = mapped_column(sa.String(16), default="success", nullable=False)
    is_security: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False, index=True)


class SystemLog(UUIDPrimaryKey, Base):
    """Системный журнал и журнал ошибок для кабинета администратора (п.1.3, п.2.7)."""

    __tablename__ = "system_logs"
    __table_args__ = (sa.Index("ix_system_logs_at_level", "at", "level"),)

    at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False, index=True
    )
    level: Mapped[LogLevel] = mapped_column(enum_column(LogLevel), default=LogLevel.INFO, nullable=False)
    component: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="backend")
    logger: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    traceback: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
