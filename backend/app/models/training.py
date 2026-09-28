from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDelete, Timestamped, UUIDPrimaryKey
from app.db.types import JSONType, TimestampType, enum_column
from app.models.enums import (
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


class Workplace(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    __tablename__ = "workplaces"
    __table_args__ = (sa.UniqueConstraint("number", name="workplace_number_unique"),)

    #: Номер, который видит обучающийся и называет преподаватель.
    number: Mapped[str] = mapped_column(sa.String(16), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    #: Учебный класс или зал: в одном центре может быть несколько классов.
    room: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: Сетевой адрес АРМ — администратору для поиска места в классе.
    host: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    phone_extension: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=sa.true(), nullable=False
    )
    #: Кто сейчас за этим местом. Снимается при выходе и при завершении занятия.
    occupied_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    occupied_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class Assignment(UUIDPrimaryKey, Timestamped, SoftDelete, Base):
    """Назначение задания группе или отдельному обучающемуся."""

    __tablename__ = "assignments"
    __table_args__ = (
        sa.CheckConstraint(
            "group_id IS NOT NULL OR student_id IS NOT NULL", name="target_required"
        ),
    )

    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[LessonMode] = mapped_column(
        enum_column(LessonMode), default=LessonMode.CARD_FILL, nullable=False
    )
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        enum_column(DifficultyLevel), default=DifficultyLevel.BASIC, nullable=False
    )
    difficulty_weight: Mapped[int] = mapped_column(
        sa.SmallInteger, default=2, server_default="2", nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    max_errors: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    params: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class Lesson(UUIDPrimaryKey, Timestamped, Base):
    """Занятие: жизненный цикл planned → running → finished/aborted."""

    __tablename__ = "lessons"
    __table_args__ = (sa.Index("ix_lessons_status_started", "status", "started_at"),)

    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    mode: Mapped[LessonMode] = mapped_column(
        enum_column(LessonMode), default=LessonMode.CARD_FILL, nullable=False
    )
    #: Вид мероприятия: обычное занятие, аттестация или переподготовка (п.2.4 ТЗ).
    purpose: Mapped[LessonPurpose] = mapped_column(
        enum_column(LessonPurpose), default=LessonPurpose.TRAINING, nullable=False, index=True
    )
    #: Порог зачёта для аттестации, баллов из 100.
    passing_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    status: Mapped[LessonStatus] = mapped_column(
        enum_column(LessonStatus), default=LessonStatus.PLANNED, nullable=False, index=True
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("study_groups.id", ondelete="SET NULL"), nullable=True
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True
    )

    #: Выбранные преподавателем категории событий (множественный выбор, п.10 ТЗ).
    category_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Источник карточек для второго режима: сгенерированные / обучающихся / смешанно.
    card_source: Mapped[CardSource] = mapped_column(
        enum_column(CardSource), default=CardSource.GENERATED, nullable=False
    )
    difficulty: Mapped[DifficultyLevel | None] = mapped_column(enum_column(DifficultyLevel), nullable=True)
    difficulty_weight: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    adaptive_difficulty: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )
    time_limit_seconds: Mapped[int] = mapped_column(sa.Integer, default=30, nullable=False)
    max_cards: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    success_criteria: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    finished_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    abort_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    participants: Mapped[list[LessonParticipant]] = relationship(
        back_populates="lesson", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def is_active(self) -> bool:
        return self.status in (LessonStatus.RUNNING, LessonStatus.PAUSED)


class LessonParticipant(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "lesson_participants"
    __table_args__ = (sa.UniqueConstraint("lesson_id", "student_id", name="participant_unique"),)

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ParticipantStatus] = mapped_column(
        enum_column(ParticipantStatus), default=ParticipantStatus.INVITED, nullable=False
    )
    joined_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Токен возобновления: клиент восстанавливает состояние после сбоя сети до 30 сек (п.2.8).
    resume_token: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    #: Снимок клиентского состояния (открытая карточка, черновик) для восстановления.
    state: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    cards_issued: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    cards_submitted: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    #: Итог мероприятия: средний балл и решение о зачёте (заполняются при завершении).
    final_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    is_passed: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)

    workplace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("workplaces.id", ondelete="SET NULL"), nullable=True
    )
    assigned_card_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    difficulty_weight: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    #: Как менялась сложность и почему — для объяснения преподавателю.
    difficulty_log: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    lesson: Mapped[Lesson] = relationship(back_populates="participants")
    workplace: Mapped[Workplace | None] = relationship(lazy="selectin")


class CardAttempt(UUIDPrimaryKey, Timestamped, Base):
    """Одна выданная карточка и работа обучающегося с ней."""

    __tablename__ = "card_attempts"
    __table_args__ = (
        sa.UniqueConstraint("lesson_id", "participant_id", "sequence_no", name="attempt_sequence"),
        sa.Index("ix_card_attempts_student_status", "student_id", "status"),
    )

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lesson_participants.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("incident_cards.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scenario_references.id", ondelete="SET NULL"), nullable=True
    )
    sequence_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        enum_column(AttemptStatus), default=AttemptStatus.ISSUED, nullable=False, index=True
    )

    issued_at: Mapped[datetime] = mapped_column(TimestampType, server_default=sa.func.now(), nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Фактическая длительность и сравнение с нормативом (п.2.5 ТЗ).
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    norm_seconds: Mapped[int] = mapped_column(sa.Integer, default=30, nullable=False)
    time_delta_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    is_overtime: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    response_deadline_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    first_response_status: Mapped[ResponseStatus | None] = mapped_column(
        enum_column(ResponseStatus), nullable=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    first_response_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    is_response_late: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    last_response_status: Mapped[ResponseStatus | None] = mapped_column(
        enum_column(ResponseStatus), nullable=True
    )
    #: Статус карточки в системе-112: зарегистрирована / не оповещено / отказ / завершена.
    lifecycle_status: Mapped[CardLifecycleStatus] = mapped_column(
        enum_column(CardLifecycleStatus), default=CardLifecycleStatus.REGISTERED, nullable=False
    )
    notification_list: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    #: Служба, от имени которой работает обучающийся в этой попытке.
    service_code: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    difficulty_weight: Mapped[int] = mapped_column(
        sa.SmallInteger, default=2, server_default="2", nullable=False
    )
    #: Рабочее место, за которым отрабатывалась карточка.
    workplace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("workplaces.id", ondelete="SET NULL"), nullable=True
    )
    work_deadline_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    #: Черновик (промежуточное сохранение) и итоговое содержимое карточки.
    draft_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    submitted_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    #: Связанный учебный вызов (модуль телефонии).
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("call_records.id", ondelete="SET NULL", use_alter=True), nullable=True
    )

    actions: Mapped[list[StudentAction]] = relationship(
        back_populates="attempt", lazy="noload", cascade="all, delete-orphan",
        order_by="StudentAction.sequence_no",
    )
    answers: Mapped[list[CardAnswer]] = relationship(
        back_populates="attempt", lazy="noload", cascade="all, delete-orphan"
    )
    response_statuses: Mapped[list[ResponseStatusEntry]] = relationship(
        back_populates="attempt",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ResponseStatusEntry.sequence_no",
    )
    processings: Mapped[list[CardProcessing]] = relationship(
        back_populates="attempt",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="CardProcessing.sequence_no",
    )


class ResponseStatusEntry(UUIDPrimaryKey, Base):
    __tablename__ = "response_statuses"
    __table_args__ = (
        sa.UniqueConstraint("attempt_id", "sequence_no", name="response_status_sequence"),
        sa.Index("ix_response_statuses_attempt_status", "attempt_id", "status"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Служба, от имени которой работает обучающийся (его ДДС).
    service_name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    #: Код службы из списка оповещения (см. app.core.arm112.SERVICE_TITLES).
    service_code: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)

    status: Mapped[ResponseStatus] = mapped_column(enum_column(ResponseStatus), nullable=False)
    sequence_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: Комментарий: обязателен для «Не принята» и «Отказа от выполнения работ».
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Номер наряда — поле блока оповещения в ПОВ-112.
    work_order_no: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    at: Mapped[datetime] = mapped_column(TimestampType, server_default=sa.func.now(), nullable=False)
    #: Время от направления карточки в службу, мс — по нему считается норматив 30 с.
    offset_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    is_late: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    #: Проставлен системой (Добавлена / Получена службой) либо обучающимся.
    set_by_system: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    attempt: Mapped[CardAttempt] = relationship(back_populates="response_statuses")


class CardProcessing(UUIDPrimaryKey, Base):
    __tablename__ = "card_processings"
    __table_args__ = (
        sa.Index("ix_card_processings_attempt", "attempt_id", "sequence_no"),
        sa.Index("ix_card_processings_lesson_kind", "lesson_id", "kind"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sequence_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    kind: Mapped[ProcessingKind] = mapped_column(
        enum_column(ProcessingKind), default=ProcessingKind.SERVICE, nullable=False
    )
    #: Куда звонили: код и название службы из списка оповещения карточки.
    service_code: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    service_name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    #: ФИО того, кто принял сообщение — обязательное поле строки отработки.
    answered_by: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    #: Суть сообщения: что передал обучающийся. Оценивается на полноту.
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    at: Mapped[datetime] = mapped_column(TimestampType, server_default=sa.func.now(), nullable=False)
    #: Время от выдачи карточки, мс — видно, на каком этапе был сделан звонок.
    offset_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: Учебный вызов телефонии: отсюда берётся запись разговора и расшифровка.
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("call_records.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    workplace_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("workplaces.id", ondelete="SET NULL"), nullable=True
    )
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    attempt: Mapped[CardAttempt] = relationship(back_populates="processings")


class StudentAction(UUIDPrimaryKey, Base):
    """Журнал действий обучающегося — основа для оценки последовательности."""

    __tablename__ = "student_actions"
    __table_args__ = (sa.Index("ix_student_actions_attempt_seq", "attempt_id", "sequence_no"),)

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[ActionType] = mapped_column(enum_column(ActionType), nullable=False)
    sequence_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    field_code: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    value_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    #: Время сервера и время клиента: расхождение помогает выявлять проблемы сети.
    at: Mapped[datetime] = mapped_column(TimestampType, server_default=sa.func.now(), nullable=False)
    client_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    #: Время от выдачи карточки до действия, мс — используется при оценке тайминга.
    offset_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    attempt: Mapped[CardAttempt] = relationship(back_populates="actions")


class CardAnswer(UUIDPrimaryKey, Base):
    """Итоговые значения полей карточки (в т.ч. свободный текст оператора)."""

    __tablename__ = "card_answers"
    __table_args__ = (sa.UniqueConstraint("attempt_id", "field_code", name="answer_unique"),)

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("card_attempts.id", ondelete="CASCADE"), nullable=False
    )
    field_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    value_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    value_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    char_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        TimestampType, server_default=sa.func.now(), nullable=False
    )

    attempt: Mapped[CardAttempt] = relationship(back_populates="answers")
