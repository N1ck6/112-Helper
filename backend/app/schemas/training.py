"""Схемы учебного процесса: назначения, занятия, попытки, действия."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from app.models.enums import (
    RESPONSE_STATUS_TITLES,
    ActionType,
    AttemptStatus,
    CardLifecycleStatus,
    CardSource,
    DifficultyLevel,
    LessonMode,
    LessonPurpose,
    LessonStatus,
    ParticipantStatus,
    ProcessingKind,
    ResponseStatus,
)
from app.schemas.card import CardRead
from app.schemas.common import ORMModel


# ------------------------------------------------------------------ назначения
class AssignmentRead(ORMModel):
    id: uuid.UUID
    title: str
    scenario_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    assigned_by_id: uuid.UUID | None = None
    mode: LessonMode
    difficulty: DifficultyLevel
    due_at: datetime | None = None
    time_limit_seconds: int | None = None
    max_errors: int | None = None
    params: dict[str, Any] = {}
    is_active: bool
    created_at: datetime


class AssignmentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    scenario_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    mode: LessonMode = LessonMode.CARD_FILL
    difficulty: DifficultyLevel = DifficultyLevel.BASIC
    due_at: datetime | None = None
    time_limit_seconds: int | None = Field(default=None, ge=5, le=3600)
    max_errors: int | None = Field(default=None, ge=0, le=100)
    params: dict[str, Any] = {}


# --------------------------------------------------------------------- занятия
class ParticipantRead(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    status: ParticipantStatus
    joined_at: datetime | None = None
    last_seen_at: datetime | None = None
    cards_issued: int
    cards_submitted: int
    #: Итог мероприятия: средний балл и решение о зачёте (аттестация, переподготовка).
    final_score: float | None = None
    is_passed: bool | None = None
    #: Рабочее место, за которым обучающийся работает в этом занятии.
    workplace_id: uuid.UUID | None = None
    #: Текущий вес сложности 1-10 при адаптивном режиме.
    difficulty_weight: int | None = None


class LessonRead(ORMModel):
    id: uuid.UUID
    title: str
    mode: LessonMode
    purpose: LessonPurpose = LessonPurpose.TRAINING
    passing_score: float | None = None
    status: LessonStatus
    teacher_id: uuid.UUID
    group_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    category_ids: list[Any] = []
    card_source: CardSource
    difficulty: DifficultyLevel | None = None
    #: Вес сложности 1-10: шкала, которую просил заказчик. Уровень выше - производная.
    difficulty_weight: int | None = None
    #: Подстраивать сложность под результаты обучающегося.
    adaptive_difficulty: bool = False
    time_limit_seconds: int
    max_cards: int | None = None
    success_criteria: dict[str, Any] = {}
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    participants: list[ParticipantRead] = []


class LessonCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    mode: LessonMode = LessonMode.CARD_FILL
    #: Вид мероприятия: учебное занятие, аттестация или периодическая переподготовка.
    purpose: LessonPurpose = LessonPurpose.TRAINING
    #: Порог зачёта для аттестации; по умолчанию берётся из настроек системы.
    passing_score: float | None = Field(default=None, ge=0, le=100)
    group_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    student_ids: list[uuid.UUID] = Field(
        default_factory=list, description="Если не задано — берутся все обучающиеся группы"
    )
    category_ids: list[uuid.UUID] = Field(default_factory=list, description="Множественный выбор категорий")
    card_source: CardSource = CardSource.GENERATED
    difficulty: DifficultyLevel | None = None
    difficulty_weight: int | None = Field(default=None, ge=1, le=10)
    adaptive_difficulty: bool = False
    time_limit_seconds: int | None = Field(default=None, ge=5, le=3600)
    max_cards: int | None = Field(default=None, ge=1, le=500)
    success_criteria: dict[str, Any] = {}


class LessonUpdate(BaseModel):
    title: str | None = None
    purpose: LessonPurpose | None = None
    passing_score: float | None = Field(default=None, ge=0, le=100)
    category_ids: list[uuid.UUID] | None = None
    card_source: CardSource | None = None
    difficulty: DifficultyLevel | None = None
    difficulty_weight: int | None = Field(default=None, ge=1, le=10)
    adaptive_difficulty: bool | None = None
    time_limit_seconds: int | None = None
    max_cards: int | None = None
    success_criteria: dict[str, Any] | None = None


class LessonFinishRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=512)


class LessonMonitorRow(BaseModel):
    """Строка мониторинга занятия в реальном времени (кабинет преподавателя)."""

    student_id: uuid.UUID
    student_name: str
    workplace: str | None = None
    participant_status: ParticipantStatus
    #: Сколько карточек сейчас в списке происшествий у обучающегося (поток ДДС).
    active_cards: int = 0
    current_attempt_id: uuid.UUID | None = None
    current_card_no: str | None = None
    seconds_left: float | None = None
    cards_issued: int
    cards_submitted: int
    avg_score: float | None = None
    error_count: int = 0
    last_seen_at: datetime | None = None


class LessonMonitorResponse(BaseModel):
    lesson: LessonRead
    rows: list[LessonMonitorRow]
    server_time: datetime


# -------------------------------------------------- статусы реагирования (АРМ-112)
class ResponseStatusRead(ORMModel):
    """Отметка о реагировании службы в блоке оповещения карточки."""

    id: uuid.UUID
    status: ResponseStatus
    sequence_no: int
    comment: str | None = None
    work_order_no: str | None = None
    service_name: str | None = None
    service_code: str | None = None
    at: datetime
    offset_ms: int | None = None
    is_primary: bool
    is_late: bool
    set_by_system: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def title(self) -> str:
        """Название статуса так, как оно выглядит в ПОВ-112."""
        return RESPONSE_STATUS_TITLES.get(self.status, self.status.value)


class ResponseStatusCreate(BaseModel):
    status: ResponseStatus
    comment: str | None = Field(default=None, max_length=2000)
    work_order_no: str | None = Field(default=None, max_length=64)
    #: Служба из списка оповещения карточки. По умолчанию — служба обучающегося.
    service_code: str | None = Field(default=None, max_length=32)
    client_at: datetime | None = None


class ResponseStatusOptions(BaseModel):
    """Какие статусы доступны обучающемуся прямо сейчас — для выпадающего списка."""

    current_status: ResponseStatus | None = None
    available: list[dict[str, Any]] = []
    comment_required: list[ResponseStatus] = []
    response_seconds_left: float | None = None
    primary_status_set: bool = False
    #: Служба, от имени которой работает обучающийся, и весь список оповещения карточки.
    service_code: str | None = None
    service_name: str | None = None
    is_primary_service: bool = False
    notification_list: list[dict[str, Any]] = []
    #: Типовые формулировки комментариев из памятки — подсказка обучающемуся.
    comment_examples: list[str] = []


# --------------------------------------------------------------------- попытки
class AttemptRead(ORMModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    student_id: uuid.UUID
    card_id: uuid.UUID
    scenario_id: uuid.UUID | None = None
    sequence_no: int
    status: AttemptStatus
    issued_at: datetime
    deadline_at: datetime | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    duration_ms: int | None = None
    norm_seconds: int
    time_delta_seconds: float | None = None
    is_overtime: bool
    draft_payload: dict[str, Any] = {}
    submitted_payload: dict[str, Any] = {}
    call_id: uuid.UUID | None = None

    # --- реагирование (режим «действия с карточками»)
    response_deadline_at: datetime | None = None
    first_response_status: ResponseStatus | None = None
    first_response_at: datetime | None = None
    first_response_seconds: float | None = None
    is_response_late: bool = False
    last_response_status: ResponseStatus | None = None
    lifecycle_status: CardLifecycleStatus = CardLifecycleStatus.REGISTERED
    response_statuses: list[ResponseStatusRead] = []
    #: Список оповещения карточки и служба самого обучающегося.
    notification_list: list[dict[str, Any]] = []
    service_code: str | None = None
    #: Вес сложности этой карточки 1-10 на момент выдачи.
    difficulty_weight: int = 2
    #: Рабочее место, за которым отрабатывалась карточка.
    workplace_id: uuid.UUID | None = None
    work_deadline_at: datetime | None = None
    opened_at: datetime | None = None


class AttemptWithCard(BaseModel):
    """То, что видит обучающийся: карточка + параметры попытки и таймер."""

    attempt: AttemptRead
    card: CardRead
    seconds_left: float | None = None
    #: Сколько секунд осталось на первичный статус «Принята»/«Не принята» (норматив 30 с).
    response_seconds_left: float | None = None
    #: И сколько - на полную отработку карточки (норматив 3 минуты).
    work_seconds_left: float | None = None
    template_fields: list[Any] = []


class ActionCreate(BaseModel):
    action_type: ActionType
    field_code: str | None = Field(default=None, max_length=64)
    value_text: str | None = None
    payload: dict[str, Any] = {}
    client_at: datetime | None = None


class ActionRead(ORMModel):
    id: uuid.UUID
    attempt_id: uuid.UUID
    action_type: ActionType
    sequence_no: int
    field_code: str | None = None
    value_text: str | None = None
    payload: dict[str, Any] = {}
    at: datetime
    offset_ms: int | None = None


class DraftSaveRequest(BaseModel):
    """Промежуточное сохранение карточки (п.2.4: хранение промежуточного результата)."""

    payload: dict[str, Any]


class SubmitRequest(BaseModel):
    payload: dict[str, Any]
    client_at: datetime | None = None


class SubmitResponse(BaseModel):
    attempt: AttemptRead
    evaluation_id: uuid.UUID | None = None
    score: float | None = None
    passed: bool | None = None
    errors: list[dict[str, Any]] = []
    next_attempt: AttemptWithCard | None = None
    lesson_finished: bool = False


class ResponseStatusResult(BaseModel):
    """Итог простановки статуса реагирования."""

    entry: ResponseStatusRead
    attempt: AttemptRead
    card_closed: bool = False
    evaluation_id: uuid.UUID | None = None
    score: float | None = None
    passed: bool | None = None
    errors: list[dict[str, Any]] = []
    next_attempt: AttemptWithCard | None = None


class ResumeRequest(BaseModel):
    """Возобновление после сетевого сбоя до 30 секунд (п.2.8)."""

    resume_token: str


# ------------------------------------------------------- вход и рабочее место
class JoinRequest(BaseModel):
    workplace_number: str | None = Field(default=None, max_length=16)


class WorkplaceRead(ORMModel):
    id: uuid.UUID
    number: str
    title: str | None = None
    room: str | None = None
    host: str | None = None
    phone_extension: str | None = None
    is_active: bool
    occupied_by_id: uuid.UUID | None = None
    occupied_at: datetime | None = None


class WorkplaceCreate(BaseModel):
    number: str = Field(min_length=1, max_length=16)
    title: str | None = Field(default=None, max_length=128)
    room: str | None = Field(default=None, max_length=64)
    host: str | None = Field(default=None, max_length=64)
    #: Внутренний номер IP-телефона на этом месте: 3-4 цифры, как просил заказчик.
    phone_extension: str | None = Field(default=None, max_length=16)
    is_active: bool = True
    meta: dict[str, Any] = {}


class WorkplaceUpdate(BaseModel):
    number: str | None = Field(default=None, max_length=16)
    title: str | None = Field(default=None, max_length=128)
    room: str | None = Field(default=None, max_length=64)
    host: str | None = Field(default=None, max_length=64)
    phone_extension: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None


class WorkplaceAssignRequest(BaseModel):
    lesson_id: uuid.UUID
    assignments: dict[str, uuid.UUID] = Field(
        description="Номер рабочего места -> сценарий или карточка"
    )


# ---------------------------------------------- список происшествий (поток ДДС)
class IncidentListRow(BaseModel):
    """Строка «Списка происшествий» на АРМ диспетчера ДДС."""

    attempt_id: uuid.UUID
    sequence_no: int
    card_no: str | None = None
    title: str | None = None
    status: AttemptStatus
    lifecycle_status: CardLifecycleStatus
    difficulty_weight: int = 2
    issued_at: datetime
    opened_at: datetime | None = None
    first_response_status: ResponseStatus | None = None
    #: Обратный отсчёт до норматива первичного статуса - 30 секунд.
    response_seconds_left: float | None = None
    #: И до конца отработки карточки - 3 минуты.
    work_seconds_left: float | None = None
    is_response_late: bool = False
    service_code: str | None = None


class MyAttemptRow(BaseModel):
    """Карточка обучающегося в занятии — очередь оператора и история диспетчера."""

    attempt_id: uuid.UUID
    card_no: str | None = None
    incident_class: str | None = None
    address: str | None = None
    phone: str | None = None
    status: AttemptStatus
    issued_at: datetime
    submitted_at: datetime | None = None
    first_response_status: ResponseStatus | None = None
    last_response_status: ResponseStatus | None = None
    score: float | None = None
    passed: bool | None = None


class IncidentListResponse(BaseModel):
    """Весь список целиком: таймеры ожидающих карточек идут параллельно."""

    lesson_id: uuid.UUID
    mode: LessonMode
    #: Сколько карточек держится в потоке одновременно.
    stream_window: int
    workplace: str | None = None
    cards_issued: int
    cards_submitted: int
    max_cards: int | None = None
    rows: list[IncidentListRow] = []


# ---------------------------------------------------------------- отработки
class ProcessingCreate(BaseModel):
    kind: ProcessingKind = ProcessingKind.SERVICE
    service_code: str | None = Field(default=None, max_length=32)
    service_name: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    answered_by: str | None = Field(default=None, max_length=128)
    summary: str = Field(min_length=3, max_length=2000)
    duration_ms: int | None = Field(default=None, ge=0)
    #: Звонок уже состоялся через модуль телефонии (или телефон в браузере): его id.
    #: Тогда вызов не поднимается повторно, а отработка привязывается к записи разговора.
    sip_call_id: str | None = Field(default=None, max_length=128)
    recording_url: str | None = Field(default=None, max_length=512)
    #: failed — не дозвонились: строка «не оповещено», кто принял — не нужен.
    outcome: str = Field(default="completed", pattern="^(completed|failed)$")


class ProcessingRead(ORMModel):
    id: uuid.UUID
    attempt_id: uuid.UUID
    sequence_no: int
    kind: ProcessingKind
    service_code: str | None = None
    service_name: str | None = None
    phone: str | None = None
    answered_by: str | None = None
    summary: str | None = None
    at: datetime
    offset_ms: int | None = None
    duration_ms: int | None = None
    call_id: uuid.UUID | None = None
    workplace_id: uuid.UUID | None = None
    #: sip_call_id, recording_url, outcome — звонок, по которому записана отработка.
    meta: dict[str, Any] = {}


class ProcessingContact(BaseModel):
    """Кому можно позвонить по этой карточке — для панели телефона."""

    kind: ProcessingKind
    service_code: str | None = None
    service_name: str
    phone: str | None = None
    supervisor: dict[str, Any] = {}
    is_primary: bool = False
