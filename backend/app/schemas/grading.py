"""Схемы оценок, ошибок, рекомендаций и аналитики."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    ErrorCategory,
    ErrorSeverity,
    EvaluationSource,
    RecommendationTarget,
)
from app.schemas.common import ORMModel


class ErrorRecordRead(ORMModel):
    id: uuid.UUID
    category: ErrorCategory
    severity: ErrorSeverity
    code: str
    message: str
    field_code: str | None = None
    expected: str | None = None
    actual: str | None = None
    penalty: float


class EvaluationRead(ORMModel):
    id: uuid.UUID
    attempt_id: uuid.UUID
    lesson_id: uuid.UUID
    student_id: uuid.UUID
    source: EvaluationSource
    score: float
    max_score: float
    passed: bool
    timing_score: float | None = None
    procedure_score: float | None = None
    accuracy_score: float | None = None
    grammar_score: float | None = None
    error_count: int
    critical_error_count: int
    details: dict[str, Any] = {}
    ml_model: str | None = None
    evaluated_at: datetime
    overridden_by_id: uuid.UUID | None = None
    overridden_at: datetime | None = None
    original_score: float | None = None
    override_reason: str | None = None
    teacher_comment: str | None = None
    errors: list[ErrorRecordRead] = []


class EvaluationOverrideRequest(BaseModel):
    """Экспертная корректировка оценки. Всегда фиксируется в журнале аудита (п.2.3)."""

    score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=3, max_length=1000)
    passed: bool | None = None
    teacher_comment: str | None = Field(default=None, max_length=2000)


class RecommendationRead(ORMModel):
    id: uuid.UUID
    target: RecommendationTarget
    student_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    title: str
    text: str
    priority: int
    source: EvaluationSource
    based_on: dict[str, Any] = {}
    is_read: bool
    created_at: datetime


class HistoryRead(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    lesson_id: uuid.UUID | None = None
    attempt_id: uuid.UUID | None = None
    scenario_id: uuid.UUID | None = None
    score: float | None = None
    passed: bool | None = None
    duration_ms: int | None = None
    error_count: int
    recorded_at: datetime


class ErrorBucket(BaseModel):
    code: str
    category: ErrorCategory
    count: int
    share: float


class TimingPoint(BaseModel):
    label: str
    avg_duration_seconds: float
    norm_seconds: float
    overtime_share: float


class ScorePoint(BaseModel):
    label: str
    avg_score: float
    attempts: int


class AnalyticsSummary(BaseModel):
    """Данные для графиков и тепловых карт в кабинете преподавателя (п.1.7, 2.6)."""

    scope: str
    attempts_total: int
    attempts_submitted: int
    attempts_overtime: int
    avg_score: float | None = None
    pass_rate: float | None = None
    avg_duration_seconds: float | None = None
    top_errors: list[ErrorBucket] = []
    timing: list[TimingPoint] = []
    score_dynamics: list[ScorePoint] = []
    error_heatmap: list[dict[str, Any]] = []
    generated_in_ms: int | None = None


class ReadinessForecast(BaseModel):
    student_id: uuid.UUID
    attempts_used: int
    trend_per_attempt: float
    current_score: float | None = None
    forecast_next_score: float | None = None
    forecast_attempts_to_target: int | None = None
    target_score: float
    confidence: float
    method: str = "linear_regression_ols"
