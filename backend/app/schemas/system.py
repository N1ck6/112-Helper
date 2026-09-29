"""Схемы административных функций, журналов и телефонии."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    AuditAction,
    BackupStatus,
    CallDirection,
    CallStatus,
    LogLevel,
    ServiceStatus,
)
from app.schemas.common import ORMModel


# ------------------------------------------------------------------- журналы
class AuditLogRead(ORMModel):
    id: uuid.UUID
    at: datetime
    action: AuditAction
    actor_id: uuid.UUID | None = None
    actor_username: str | None = None
    actor_roles: str | None = None
    object_type: str | None = None
    object_id: str | None = None
    summary: str | None = None
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    ip_address: str | None = None
    request_id: str | None = None
    result: str
    is_security: bool


class SystemLogRead(ORMModel):
    id: uuid.UUID
    at: datetime
    level: LogLevel
    component: str
    logger: str | None = None
    message: str
    context: dict[str, Any] = {}
    request_id: str | None = None


# ------------------------------------------------------- конфигурация и сервисы
class SettingRead(ORMModel):
    id: uuid.UUID
    key: str
    value: dict[str, Any] | list | str | int | float | bool | None
    category: str
    description: str | None = None
    is_protected: bool
    updated_at: datetime


class SettingUpsert(BaseModel):
    key: str = Field(min_length=2, max_length=128)
    value: Any
    category: str = "general"
    description: str | None = None


class ServiceStateRead(ORMModel):
    id: uuid.UUID
    name: str
    kind: str
    status: ServiceStatus
    version: str | None = None
    endpoint: str | None = None
    last_heartbeat_at: datetime | None = None
    last_error: str | None = None
    details: dict[str, Any] = {}
    updated_at: datetime


class ServiceControlRequest(BaseModel):
    action: str = Field(pattern="^(start|stop|restart)$")
    reason: str | None = Field(default=None, max_length=512)


class BackupRead(ORMModel):
    id: uuid.UUID
    kind: str
    status: BackupStatus
    path: str | None = None
    size_bytes: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    #: Команда восстановления: выполняется администратором вручную.
    restore_command: str | None = None


class BackupRegister(BaseModel):
    """Регистрация копии, снятой внешним планировщиком контура."""

    path: str = Field(min_length=3, max_length=512)
    size_bytes: int | None = Field(default=None, ge=0)


class SystemStats(BaseModel):
    users_total: int
    users_active: int
    lessons_running: int
    attempts_today: int
    evaluations_today: int
    db_size_bytes: int | None = None
    outbox_pending: int
    services: list[ServiceStateRead] = []
    uptime_seconds: float


# ------------------------------------------------------------------- телефония
class TelephonyConfigRead(ORMModel):
    id: uuid.UUID
    name: str
    sip_host: str
    sip_port: int
    sip_domain: str | None = None
    transport: str
    codec: str
    max_latency_ms: int
    record_calls: bool
    audio_format: str
    is_active: bool
    extra: dict[str, Any] = {}
    updated_at: datetime


class TelephonyConfigUpdate(BaseModel):
    sip_host: str | None = None
    sip_port: int | None = Field(default=None, ge=1, le=65535)
    sip_domain: str | None = None
    transport: str | None = Field(default=None, pattern="^(UDP|TCP|TLS)$")
    codec: str | None = None
    max_latency_ms: int | None = Field(default=None, ge=1, le=2000)
    record_calls: bool | None = None
    audio_format: str | None = Field(default=None, pattern="^(wav|mp3)$")
    extra: dict[str, Any] | None = None


class CallRead(ORMModel):
    id: uuid.UUID
    sip_call_id: str | None = None
    direction: CallDirection
    status: CallStatus
    lesson_id: uuid.UUID | None = None
    attempt_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    caller_number: str | None = None
    callee_number: str | None = None
    started_at: datetime
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    latency_ms: int | None = None
    audio_path: str | None = None


class CallEventRequest(BaseModel):
    """Вебхук от модуля телефонии (участник 4) о событии вызова."""

    sip_call_id: str = Field(min_length=1, max_length=128)
    event: str = Field(pattern="^(ringing|answered|missed|ended|failed)$")
    attempt_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    caller_number: str | None = None
    callee_number: str | None = None
    latency_ms: int | None = Field(default=None, ge=0, le=100000)
    duration_ms: int | None = Field(default=None, ge=0)
    audio_path: str | None = None
    audio_format: str | None = None
    meta: dict[str, Any] = {}
