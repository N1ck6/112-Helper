"""Схемы карточек происшествий и их шаблонов."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import CardOrigin, CardStatus, DifficultyLevel
from app.schemas.common import ORMModel


class CardTemplateRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    version: int
    is_default: bool
    fields_schema: list[Any] = []


class CardTemplateCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=255)
    fields_schema: list[dict[str, Any]]
    is_default: bool = False


class CardRead(ORMModel):
    id: uuid.UUID
    card_no: str
    title: str
    template_id: uuid.UUID | None = None
    scenario_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    origin: CardOrigin
    status: CardStatus
    difficulty: DifficultyLevel
    caller_profile: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    #: Код типа происшествия в классификаторе заказчика.
    incident_type_code: str | None = None
    #: Службы, получившие карточку (формируется по ЕКП, см. app.core.arm112).
    notification_list: list[dict[str, Any]] = []
    audio_path: str | None = None
    time_limit_seconds: int | None = None
    author_id: uuid.UUID | None = None
    created_at: datetime


class CardWithExpected(CardRead):
    """Вариант для преподавателя: с эталонным содержимым."""

    expected_payload: dict[str, Any] = {}


class CardCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    card_no: str | None = Field(default=None, max_length=32)
    template_id: uuid.UUID | None = None
    scenario_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    origin: CardOrigin = CardOrigin.MANUAL
    difficulty: DifficultyLevel = DifficultyLevel.BASIC
    caller_profile: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    expected_payload: dict[str, Any] = {}
    #: Код типа происшествия из классификатора: по нему подставляются службы.
    incident_type_code: str | None = Field(default=None, max_length=64)
    extra_services: list[str] = []
    time_limit_seconds: int | None = Field(default=None, ge=5, le=3600)


class CardUpdate(BaseModel):
    title: str | None = None
    category_id: uuid.UUID | None = None
    incident_type_code: str | None = None
    status: CardStatus | None = None
    difficulty: DifficultyLevel | None = None
    caller_profile: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    expected_payload: dict[str, Any] | None = None
    time_limit_seconds: int | None = None


class CardImportResult(BaseModel):
    """Итог пакетного импорта карточек из внешней системы (п.2.9 ТЗ)."""

    imported: int
    skipped: int
    card_ids: list[uuid.UUID] = []
    #: Причины пропуска: дубль номера, отсутствие обязательных данных.
    warnings: list[str] = []
