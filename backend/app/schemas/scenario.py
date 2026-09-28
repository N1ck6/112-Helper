"""Схемы сценариев, эталонов, материалов и заявок на генерацию."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    DifficultyLevel,
    MaterialKind,
    ScenarioOrigin,
    ScenarioStatus,
)
from app.schemas.common import ORMModel


class ReferenceRead(ORMModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    card_id: uuid.UUID | None = None
    expected_fields: dict[str, Any] = {}
    expected_actions: list[Any] = []
    expected_text: dict[str, Any] = {}
    weight: float
    approved_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    teacher_comment: str | None = None


class ReferenceCreate(BaseModel):
    card_id: uuid.UUID | None = None
    expected_fields: dict[str, Any] = {}
    expected_actions: list[str] = []
    expected_text: dict[str, Any] = {}
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class ReferenceUpdate(BaseModel):
    expected_fields: dict[str, Any] | None = None
    expected_actions: list[str] | None = None
    expected_text: dict[str, Any] | None = None
    weight: float | None = None
    teacher_comment: str | None = None


class ScenarioRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    category_id: uuid.UUID | None = None
    difficulty: DifficultyLevel
    status: ScenarioStatus
    origin: ScenarioOrigin
    author_id: uuid.UUID | None = None
    approved_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    time_limit_seconds: int | None = None
    success_criteria: dict[str, Any] = {}
    briefing: dict[str, Any] = {}
    ml_model: str | None = None
    version: int
    is_active: bool
    created_at: datetime
    references: list[ReferenceRead] = []


class ScenarioCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str | None = None
    category_id: uuid.UUID | None = None
    difficulty: DifficultyLevel = DifficultyLevel.BASIC
    time_limit_seconds: int | None = Field(default=None, ge=5, le=3600)
    success_criteria: dict[str, Any] = {}
    briefing: dict[str, Any] = {}
    references: list[ReferenceCreate] = []


class ScenarioUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category_id: uuid.UUID | None = None
    difficulty: DifficultyLevel | None = None
    time_limit_seconds: int | None = None
    success_criteria: dict[str, Any] | None = None
    briefing: dict[str, Any] | None = None


class ScenarioApproveRequest(BaseModel):
    """Полное или частичное утверждение эталонов (п.10 ТЗ)."""

    reference_ids: list[uuid.UUID] | None = Field(
        default=None, description="None → утвердить все эталоны сценария"
    )
    comment: str | None = None


class GenerateScenariosRequest(BaseModel):
    category_id: uuid.UUID | None = None
    difficulty: DifficultyLevel = DifficultyLevel.BASIC
    count: int = Field(default=1, ge=1, le=20)
    prompt: str | None = Field(default=None, max_length=2000)
    with_cards: bool = True


class CorrectScenarioRequest(BaseModel):
    """Контекстное поле преподавателя для корректировки вопроса/ответа (п.10 ТЗ)."""

    comment: str = Field(min_length=3, max_length=2000)
    reference_id: uuid.UUID | None = None


class MaterialRead(ORMModel):
    id: uuid.UUID
    title: str
    kind: MaterialKind
    category_id: uuid.UUID | None = None
    description: str | None = None
    file_path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    indexed_by_ml: bool
    indexed_at: datetime | None = None
    created_at: datetime


class GrammarCheckRequest(BaseModel):
    """Принудительная проверка грамматики после ручных правок (п.10 ТЗ)."""

    text: str | None = Field(default=None, max_length=20000)
    scenario_id: uuid.UUID | None = None
