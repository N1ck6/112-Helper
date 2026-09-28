"""Схемы отчётности и сертификатов."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ReportFormat, ReportStatus, ReportType
from app.schemas.common import ORMModel


class ReportRead(ORMModel):
    id: uuid.UUID
    type: ReportType
    format: ReportFormat
    status: ReportStatus
    title: str
    lesson_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    params: dict[str, Any] = {}
    data: dict[str, Any] = {}
    file_path: str | None = None
    file_size: int | None = None
    row_count: int | None = None
    generation_ms: int | None = None
    generated_at: datetime | None = None
    error: str | None = None
    created_at: datetime


class ReportCreate(BaseModel):
    type: ReportType
    format: ReportFormat = ReportFormat.JSON
    lesson_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    params: dict[str, Any] = {}


class CertificateRead(ORMModel):
    id: uuid.UUID
    serial: str
    student_id: uuid.UUID
    lesson_id: uuid.UUID | None = None
    program_name: str
    issued_by_id: uuid.UUID | None = None
    issued_at: datetime
    score: float | None = None
    hours: int | None = None
    file_path: str | None = None
    verification_code: str


class CertificateIssueRequest(BaseModel):
    student_id: uuid.UUID
    lesson_id: uuid.UUID | None = None
    program_name: str = Field(
        default="Подготовка оператора ДДС города Москвы", min_length=3, max_length=255
    )
    hours: int | None = Field(default=None, ge=1, le=1000)
