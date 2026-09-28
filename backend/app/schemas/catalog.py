"""Схемы классификатора происшествий и нормативов времени."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ActionType, DifficultyLevel, LessonMode, ServiceLevel
from app.schemas.common import ORMModel


class CategoryRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    parent_id: uuid.UUID | None = None
    dds_profile: str | None = None
    default_difficulty: DifficultyLevel
    required_fields: list = []
    is_active: bool


class CategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    dds_profile: str | None = None
    default_difficulty: DifficultyLevel = DifficultyLevel.BASIC
    required_fields: list[str] = []


class CategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    dds_profile: str | None = None
    default_difficulty: DifficultyLevel | None = None
    required_fields: list[str] | None = None


class TimeNormRead(ORMModel):
    id: uuid.UUID
    category_id: uuid.UUID | None = None
    mode: LessonMode | None = None
    action_type: ActionType | None = None
    seconds: int
    comment: str | None = None


class TimeNormUpsert(BaseModel):
    category_id: uuid.UUID | None = None
    mode: LessonMode | None = None
    action_type: ActionType | None = None
    seconds: int = Field(ge=1, le=3600, default=30)
    comment: str | None = None


# ------------------------------------------------- классификатор происшествий (ЕКП)
class IncidentFeature(BaseModel):
    """Признак происшествия из классификатора."""

    type: str = Field(description="object / detail / feature")
    value: str


class IncidentTypeRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    category_name: str | None = None
    category_id: uuid.UUID | None = None
    features: list[dict] = []
    main_service: str | None = None
    services: list[dict] = []
    agency_classifiers: dict = {}
    #: Исходная строка таблицы — нужна аналитику при разборе спорных классификаций.
    raw: dict = {}


class IncidentTypeImportItem(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=512)
    category_name: str | None = Field(default=None, max_length=255)
    category_code: str | None = Field(
        default=None, description="Код учебной категории, к которой относится тип"
    )
    features: list[IncidentFeature] = []
    main_service: str | None = Field(default=None, max_length=128)
    services: list[str] = Field(default_factory=list, description="Коды служб оповещения")
    agency_classifiers: dict = {}
    raw: dict = {}


class IncidentTypeImportRequest(BaseModel):
    items: list[IncidentTypeImportItem] = Field(min_length=1)
    #: Заменять существующие записи с теми же кодами.
    update_existing: bool = True


class IncidentTypeImportResult(BaseModel):
    imported: int
    updated: int
    skipped: int
    warnings: list[str] = []


class IncidentCategorySummary(BaseModel):
    """Категория классификатора со счётчиком типов — для выпадающих списков."""

    category_name: str
    types_total: int
    category_id: uuid.UUID | None = None
    category_code: str | None = None


# ------------------------------------------- справочник ДДС (маршрутизация)
class DutyServiceRead(ORMModel):
    """Дежурно-диспетчерская служба в справочнике маршрутизации."""

    id: uuid.UUID
    code: str
    name: str
    short_name: str | None = None
    level: ServiceLevel
    okrug: str | None = None
    area: str | None = None
    parent_id: uuid.UUID | None = None
    phone_extension: str | None = None
    phone: str | None = None
    supervisor: dict[str, Any] = {}
    categories: list[Any] = []
    is_primary: bool
    is_active: bool


class DutyServiceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=2, max_length=255)
    short_name: str | None = Field(default=None, max_length=128)
    level: ServiceLevel = ServiceLevel.OTHER
    #: Административный округ. Пусто — служба городского уровня.
    okrug: str | None = Field(default=None, max_length=64)
    #: Район обслуживания. Пусто — вся территория округа.
    area: str | None = Field(default=None, max_length=128)
    #: Код вышестоящей службы: ДДС управы подчинена ДДС округа.
    parent_code: str | None = Field(default=None, max_length=64)
    #: Внутренний номер для симулятора IP-телефона: 3–4 цифры.
    phone_extension: str | None = Field(default=None, max_length=16)
    phone: str | None = Field(default=None, max_length=32)
    #: Должностное лицо, которому докладывает диспетчер: ФИО, должность, номер.
    supervisor: dict[str, Any] = {}
    #: Категории происшествий, по которым служба привлекается всегда.
    categories: list[str] = []
    is_primary: bool = False
    is_active: bool = True


class DutyServiceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    short_name: str | None = Field(default=None, max_length=128)
    level: ServiceLevel | None = None
    okrug: str | None = Field(default=None, max_length=64)
    area: str | None = Field(default=None, max_length=128)
    parent_code: str | None = Field(default=None, max_length=64)
    phone_extension: str | None = Field(default=None, max_length=16)
    phone: str | None = Field(default=None, max_length=32)
    supervisor: dict[str, Any] | None = None
    categories: list[str] | None = None
    is_primary: bool | None = None
    is_active: bool | None = None


class RoutingPreviewRequest(BaseModel):
    category_id: uuid.UUID | None = None
    incident_type_code: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Поля карточки; достаточно адреса и признаков"
    )
    extra_services: list[str] = []
